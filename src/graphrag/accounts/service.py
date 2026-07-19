"""Accounts: signup, email verification, login, sessions.

The flow is deliberately ordinary — email + password, then a six-digit code to
prove the address is real, then a server-side session in an httpOnly cookie.
Two decisions worth stating:

**Codes only at signup, not every login.** Emailing a code per login would burn
a free-tier sending quota (Resend allows 100/day) and add friction to the most
common action, for little gain over a password the user chose.

**Server-side sessions, not JWTs.** The cookie carries an opaque token; the
database holds only its hash. That makes revocation instant — suspending or
deleting an account cuts every session immediately — which a stateless token
can only match by adding a denylist lookup, i.e. the same round trip with worse
failure modes.

Responses never reveal whether an address is registered. Signup, resend and
password login all answer the same way for known and unknown addresses;
otherwise the endpoints become an account-enumeration oracle.
"""

from __future__ import annotations

import contextlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from graphrag.accounts.emails import EmailSender
from graphrag.accounts.passwords import hash_password, validate_password, verify_password
from graphrag.config.settings import Settings
from graphrag.container import sanitize_user
from graphrag.core.logging import get_logger
from graphrag.db.engine import session_scope
from graphrag.db.models import EmailOTP, User
from graphrag.db.models import Session as SessionRow

log = get_logger(__name__)

_SESSION_CACHE = "graphrag:session:"
_SESSION_CACHE_TTL = 60
_TENANT_SUFFIX_BYTES = 4


class AccountError(Exception):
    """A problem worth showing the user (bad code, weak password, ...)."""

    def __init__(self, message: str, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Principal:
    """The authenticated identity attached to a request."""

    user_id: str
    tenant_id: str
    role: str
    email: str = ""

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_token(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _tenant_for(email: str) -> str:
    """A storage namespace derived from the address but not equal to it.

    The tenant id names a Neo4j corpus and a DuckDB filename, so it has to be a
    safe token; the random suffix keeps two similar addresses
    ("a.b@x" / "a-b@x") from colliding after sanitizing, and keeps the
    filesystem from spelling out who owns what.
    """
    local = sanitize_user(email.split("@", 1)[0])[:24].strip("-") or "user"
    return f"{local}-{secrets.token_hex(_TENANT_SUFFIX_BYTES)}"


class AccountService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession] | None,
        settings: Settings,
        email_sender: EmailSender,
        redis_client=None,
    ) -> None:
        self._factory = factory
        self._settings = settings
        self._email = email_sender
        self._redis = redis_client

    @property
    def _auth(self):
        return self._settings.auth

    # -- registration ---------------------------------------------------------
    async def signup(self, email: str, password: str) -> None:
        """Create a pending account and email a verification code.

        Returns nothing on purpose: the caller says the same thing whether or
        not the address was already taken.
        """
        email = normalize_email(email)
        if not email or "@" not in email:
            raise AccountError("Enter a valid email address.", "invalid_email")
        problem = validate_password(password)
        if problem:
            raise AccountError(problem, "weak_password")

        async with session_scope(self._factory) as s:
            existing = await self._by_email(s, email)
            if existing is not None:
                if existing.status == "pending":
                    # Signing up twice before verifying just resends the code.
                    code = await self._issue_otp(s, existing)
                else:
                    code = None
            else:
                user = User(
                    email=email,
                    password_hash=hash_password(password),
                    tenant_id=_tenant_for(email),
                    status="pending",
                    role="user",
                )
                s.add(user)
                await s.flush()
                code = await self._issue_otp(s, user)
                log.info("account_created", user=str(user.id))

        if code is not None:
            await self._send_code(email, code)

    async def resend_code(self, email: str) -> None:
        email = normalize_email(email)
        async with session_scope(self._factory) as s:
            user = await self._by_email(s, email)
            if user is None or user.status != "pending":
                return  # same silence as an unknown address
            code = await self._issue_otp(s, user)
        await self._send_code(email, code)

    async def verify(self, email: str, code: str) -> tuple[Principal, str]:
        """Confirm ownership of the address and open a session.

        Deliberately two transactions. The attempt counter has to be *committed*
        before the code is compared: doing both in one transaction means a
        rejected guess rolls the increment back with the error, the cap never
        rises, and a six-digit code is brute-forceable at request speed.
        """
        email = normalize_email(email)

        # 1. Charge the attempt. Commits even though the guess may be wrong.
        async with session_scope(self._factory) as s:
            user = await self._by_email(s, email)
            if user is None:
                raise AccountError("That code is not valid.", "invalid_code")
            if user.status == "active":
                raise AccountError("This account is already verified.", "already_verified")
            if user.status != "pending":
                raise AccountError("This account cannot be verified.", "not_verifiable")

            otp = (
                await s.execute(
                    select(EmailOTP)
                    .where(EmailOTP.user_id == user.id, EmailOTP.consumed_at.is_(None))
                    .order_by(EmailOTP.id.desc())
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if otp is None:
                raise AccountError("Request a new code.", "no_code")
            if otp.expires_at <= _now():
                raise AccountError("That code has expired. Request a new one.", "expired_code")
            if otp.attempts >= self._auth.otp_max_attempts:
                raise AccountError(
                    "Too many attempts. Request a new code.", "too_many_attempts"
                )

            otp.attempts += 1
            otp_id = otp.id
            matched = secrets.compare_digest(otp.code_hash, _hash_token(code.strip()))

        if not matched:
            raise AccountError("That code is not valid.", "invalid_code")

        # 2. The code was right: consume it and activate the account.
        async with session_scope(self._factory) as s:
            user = await self._by_email(s, email)
            if user is None or user.status != "pending":
                raise AccountError("That code is not valid.", "invalid_code")
            otp = (
                await s.execute(
                    select(EmailOTP).where(
                        EmailOTP.id == otp_id, EmailOTP.consumed_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
            if otp is None:  # raced with another verify of the same code
                raise AccountError("That code is not valid.", "invalid_code")

            otp.consumed_at = _now()
            user.status = "active"
            user.email_verified_at = _now()
            user.last_login_at = _now()
            principal = self._principal(user)
            token = await self._open_session(s, user)
            log.info("account_verified", user=str(user.id))
        return principal, token

    # -- sessions -------------------------------------------------------------
    async def login(
        self, email: str, password: str, ip: str | None = None, user_agent: str | None = None
    ) -> tuple[Principal, str]:
        email = normalize_email(email)
        async with session_scope(self._factory) as s:
            user = await self._by_email(s, email)
            # Verify even when the user is missing, against a dummy hash, so a
            # failed login costs the same either way — the timing difference
            # would otherwise reveal which addresses exist.
            stored = user.password_hash if user else _DUMMY_HASH
            ok = verify_password(stored, password)
            if user is None or not ok:
                raise AccountError("Email or password is incorrect.", "invalid_credentials")
            if user.status == "pending":
                raise AccountError("Verify your email address first.", "email_unverified")
            if user.status != "active":
                raise AccountError("This account is not active.", "account_inactive")

            user.last_login_at = _now()
            principal = self._principal(user)
            token = await self._open_session(s, user, ip=ip, user_agent=user_agent)
        return principal, token

    async def resolve_session(self, token: str) -> Principal | None:
        """Identify the holder of a session cookie, or None."""
        if not token:
            return None
        token_hash = _hash_token(token)
        cached = self._cache_get(token_hash)
        if cached is not None:
            return cached

        async with session_scope(self._factory) as s:
            row = (
                await s.execute(
                    select(SessionRow, User)
                    .join(User, User.id == SessionRow.user_id)
                    .where(
                        SessionRow.token_hash == token_hash,
                        SessionRow.revoked_at.is_(None),
                        SessionRow.expires_at > _now(),
                    )
                )
            ).first()
            if row is None:
                return None
            session_row, user = row
            if user.status != "active":
                return None  # suspension takes effect on the next request
            session_row.last_seen_at = _now()
            principal = self._principal(user)

        self._cache_put(token_hash, principal)
        return principal

    async def logout(self, token: str) -> None:
        if not token:
            return
        token_hash = _hash_token(token)
        async with session_scope(self._factory) as s:
            await s.execute(
                update(SessionRow)
                .where(SessionRow.token_hash == token_hash)
                .values(revoked_at=_now())
            )
        self._cache_drop(token_hash)

    async def revoke_sessions(self, user_id: str) -> int:
        """Drop every session a user holds (suspension, password change, or an
        admin cutting someone off)."""
        async with session_scope(self._factory) as s:
            hashes = (
                await s.execute(
                    select(SessionRow.token_hash).where(
                        SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None)
                    )
                )
            ).scalars().all()
            if hashes:
                await s.execute(
                    update(SessionRow)
                    .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
                    .values(revoked_at=_now())
                )
        for h in hashes:
            self._cache_drop(h)
        return len(hashes)

    # -- admin bootstrap ------------------------------------------------------
    async def promote_admin(self, email: str) -> bool:
        email = normalize_email(email)
        async with session_scope(self._factory) as s:
            user = await self._by_email(s, email)
            if user is None:
                return False
            if user.role != "admin":
                user.role = "admin"
                log.info("admin_promoted", email=email)
            # An admin bootstrapped from configuration should be usable without
            # a round trip through the inbox.
            if user.status == "pending":
                user.status = "active"
                user.email_verified_at = _now()
        await self._drop_user_session_cache(email)
        return True

    async def get_by_id(self, user_id: str) -> User | None:
        async with session_scope(self._factory) as s:
            return (
                await s.execute(select(User).where(User.id == uuid.UUID(str(user_id))))
            ).scalar_one_or_none()

    # -- internals ------------------------------------------------------------
    @staticmethod
    def _principal(user: User) -> Principal:
        return Principal(str(user.id), user.tenant_id, user.role, user.email)

    @staticmethod
    async def _by_email(s: AsyncSession, email: str) -> User | None:
        return (
            await s.execute(select(User).where(func.lower(User.email) == email))
        ).scalar_one_or_none()

    async def _issue_otp(self, s: AsyncSession, user: User) -> str:
        # Invalidate outstanding codes: two live codes doubles the guess space
        # for the same attempt budget.
        await s.execute(
            update(EmailOTP)
            .where(EmailOTP.user_id == user.id, EmailOTP.consumed_at.is_(None))
            .values(consumed_at=_now())
        )
        code = _generate_code()
        s.add(
            EmailOTP(
                user_id=user.id,
                code_hash=_hash_token(code),
                purpose="verify",
                expires_at=_now() + timedelta(minutes=self._auth.otp_ttl_minutes),
            )
        )
        return code

    async def _send_code(self, email: str, code: str) -> None:
        minutes = self._auth.otp_ttl_minutes
        await self._email.send(
            email,
            "Your verification code",
            f"Your verification code is {code}\n\n"
            f"It expires in {minutes} minutes. If you didn't request it, ignore this email.",
        )

    async def _open_session(
        self, s: AsyncSession, user: User, ip: str | None = None, user_agent: str | None = None
    ) -> str:
        token = secrets.token_urlsafe(32)
        s.add(
            SessionRow(
                user_id=user.id,
                token_hash=_hash_token(token),
                expires_at=_now() + timedelta(days=self._auth.session_ttl_days),
                ip=ip,
                user_agent=(user_agent or "")[:400] or None,
            )
        )
        return token

    async def _drop_user_session_cache(self, email: str) -> None:
        """Role changes must not wait out the session cache."""
        if self._redis is None:
            return
        with contextlib.suppress(Exception):
            for key in self._redis.scan_iter(match=_SESSION_CACHE + "*", count=500):
                self._redis.delete(key)

    def _cache_get(self, token_hash: str) -> Principal | None:
        if self._redis is None:
            return None
        with contextlib.suppress(Exception):
            raw = self._redis.get(_SESSION_CACHE + token_hash)
            if raw:
                user_id, tenant_id, role, email = raw.split("|", 3)
                return Principal(user_id, tenant_id, role, email)
        return None

    def _cache_put(self, token_hash: str, principal: Principal) -> None:
        if self._redis is None:
            return
        with contextlib.suppress(Exception):
            self._redis.setex(
                _SESSION_CACHE + token_hash,
                _SESSION_CACHE_TTL,
                f"{principal.user_id}|{principal.tenant_id}|{principal.role}|{principal.email}",
            )

    def _cache_drop(self, token_hash: str) -> None:
        if self._redis is None:
            return
        with contextlib.suppress(Exception):
            self._redis.delete(_SESSION_CACHE + token_hash)


# A real Argon2 hash of a random string. Verifying against it makes a login for
# an unknown address cost the same as one for a known address.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
