"""Sign-up, email verification, login, and personal API keys.

The session cookie is httpOnly (JavaScript cannot read it, so an XSS bug cannot
exfiltrate it) and SameSite=Lax (the browser withholds it from cross-site POSTs,
which is the CSRF defence for the mutating endpoints here).

Signup, resend and login are rate limited per IP: without that, the six-digit
verification code and the password field are both brute-forceable at network
speed, whatever the per-attempt caps say.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from graphrag.accounts import AccountError, AccountService
from graphrag.api.deps import (
    SESSION_COOKIE,
    AuthUser,
    get_accounts,
    get_container,
    get_current_user,
    get_key_store,
)
from graphrag.api.schemas import (
    Acknowledged,
    APIKeyCreate,
    APIKeyCreated,
    APIKeyInfo,
    APIKeyList,
    EmailRequest,
    LoginRequest,
    Me,
    ModelOption,
    SignupRequest,
    VerifyRequest,
)
from graphrag.container import Container
from graphrag.core.logging import get_logger
from graphrag.llm.registry import allowed_models, resolve_model

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)

# Deliberately identical for known and unknown addresses — anything more
# specific turns these endpoints into an account-enumeration oracle.
_SENT = "If that address can be registered, we've sent a code to it."


def _set_session_cookie(response: Response, token: str, container: Container) -> None:
    auth = container.settings.auth
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=auth.session_ttl_days * 86400,
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
        path="/",
    )


def _require_accounts(accounts: AccountService | None) -> AccountService:
    if accounts is None or accounts._factory is None:
        raise HTTPException(
            status_code=503,
            detail="Accounts are unavailable: the server has no database configured.",
        )
    return accounts


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/signup", response_model=Acknowledged)
async def signup(
    payload: SignupRequest,
    request: Request,
    accounts: AccountService = Depends(get_accounts),
    container: Container = Depends(get_container),
) -> Acknowledged:
    accounts = _require_accounts(accounts)
    if not container.settings.auth.open_registration:
        raise HTTPException(status_code=403, detail="Registration is by invitation only.")
    try:
        await accounts.signup(payload.email, payload.password)
    except AccountError as exc:
        # Validation problems are the user's to fix, so they are reported
        # plainly; "already registered" is never among them.
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from None
    return Acknowledged(message=_SENT)


@router.post("/resend", response_model=Acknowledged)
async def resend(
    payload: EmailRequest,
    accounts: AccountService = Depends(get_accounts),
) -> Acknowledged:
    await _require_accounts(accounts).resend_code(payload.email)
    return Acknowledged(message=_SENT)


@router.post("/verify", response_model=Me)
async def verify(
    payload: VerifyRequest,
    response: Response,
    accounts: AccountService = Depends(get_accounts),
    container: Container = Depends(get_container),
) -> Me:
    try:
        principal, token = await _require_accounts(accounts).verify(payload.email, payload.code)
    except AccountError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from None
    _set_session_cookie(response, token, container)
    return _me(principal, container)


@router.post("/login", response_model=Me)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    accounts: AccountService = Depends(get_accounts),
    container: Container = Depends(get_container),
) -> Me:
    try:
        principal, token = await _require_accounts(accounts).login(
            payload.email,
            payload.password,
            ip=_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )
    except AccountError as exc:
        # 403 for an unverified account so the UI can route to /verify;
        # 401 for bad credentials.
        status = 403 if exc.code in ("email_unverified", "account_inactive") else 401
        raise HTTPException(
            status_code=status, detail={"code": exc.code, "message": str(exc)}
        ) from None
    _set_session_cookie(response, token, container)
    return _me(principal, container)


@router.post("/logout", response_model=Acknowledged)
async def logout(
    request: Request,
    response: Response,
    accounts: AccountService = Depends(get_accounts),
) -> Acknowledged:
    token = request.cookies.get(SESSION_COOKIE)
    if token and accounts is not None:
        await accounts.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return Acknowledged(message="Signed out.")


@router.get("/me", response_model=Me)
async def me(
    user: AuthUser = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> Me:
    """Who am I, and what can I choose? The UI calls this on load."""
    return Me(
        user_id=user.user_id,
        email=user.email,
        role=user.role,
        tenant_id=user.tenant_id,
        models=_model_options(container),
        default_model=resolve_model(None, container.settings).model,
    )


# -- personal API keys --------------------------------------------------------

@router.get("/keys", response_model=APIKeyList)
async def list_keys(
    user: AuthUser = Depends(get_current_user),
    key_store=Depends(get_key_store),
) -> APIKeyList:
    rows = await key_store.list_keys(user.user_id)
    return APIKeyList(
        keys=[
            APIKeyInfo(
                id=k.id,
                label=k.label,
                created_at=k.created_at.isoformat() if k.created_at else "",
                last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            )
            for k in rows
        ]
    )


@router.post("/keys", response_model=APIKeyCreated)
async def create_key(
    payload: APIKeyCreate,
    user: AuthUser = Depends(get_current_user),
    key_store=Depends(get_key_store),
) -> APIKeyCreated:
    """Mint a key. The plaintext is returned exactly once — only its hash is
    stored, so a lost key is replaced, never recovered."""
    key = await key_store.create_key(user.user_id, payload.label)
    rows = await key_store.list_keys(user.user_id)
    return APIKeyCreated(id=rows[0].id if rows else 0, api_key=key)


@router.delete("/keys/{key_id}", response_model=Acknowledged)
async def revoke_key(
    key_id: int,
    user: AuthUser = Depends(get_current_user),
    key_store=Depends(get_key_store),
) -> Acknowledged:
    if not await key_store.revoke_one(user.user_id, key_id):
        raise HTTPException(status_code=404, detail="No such key.")
    return Acknowledged(message="Key revoked.")


# -- helpers ------------------------------------------------------------------

def _model_options(container: Container) -> list[ModelOption]:
    return [
        ModelOption(model=m.model, label=m.label or m.model, provider=m.provider)
        for m in allowed_models(container.settings)
    ]


def _me(principal, container: Container) -> Me:
    return Me(
        user_id=principal.user_id,
        email=principal.email,
        role=principal.role,
        tenant_id=principal.tenant_id,
        models=_model_options(container),
        default_model=resolve_model(None, container.settings).model,
    )
