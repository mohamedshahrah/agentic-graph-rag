"""HTTP client for the Guardrails & Safety Layer service.

Two calls around the agent, exactly as the guardrails README describes:

    verdict = await client.check_input(question)          # before the model
    if verdict.blocked:
        return verdict.refusal_message                     # never call the model

    answer = await run_agent(question)

    verdict = await client.check_output(question, answer, docs=sources)
    if verdict.blocked:
        return verdict.refusal_message
    answer = verdict.sanitized_output or answer            # PII/secrets redacted

The client owns one shared `httpx.AsyncClient`, created lazily on the running
event loop. Every failure mode — disabled, unreachable, timeout, malformed
response — resolves to a `GuardVerdict`, never an exception into the request
path: an observability/safety add-on must not be able to take the app down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from graphrag.config import SafetyCfg
from graphrag.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class GuardVerdict:
    """The normalized outcome of one guard call.

    `checked` is False when the guard was disabled or unreachable and the call
    failed open — i.e. the `allow` is a default, not a judgement. Callers that
    want to surface "not actually screened" can read it; enforcement only cares
    about `blocked` / `flagged`.
    """

    action: str = "allow"  # allow | flag | block
    refusal_message: str | None = None
    sanitized_output: str | None = None
    modified: bool = False
    reasons: list[str] = field(default_factory=list)
    categories: list[dict[str, Any]] = field(default_factory=list)
    checked: bool = True
    error: str | None = None

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    @property
    def flagged(self) -> bool:
        return self.action == "flag"

    @classmethod
    def allow(cls, *, checked: bool = True, error: str | None = None) -> GuardVerdict:
        return cls(action="allow", checked=checked, error=error)

    @classmethod
    def block(
        cls, message: str, *, checked: bool = False, error: str | None = None
    ) -> GuardVerdict:
        return cls(action="block", refusal_message=message, checked=checked, error=error)


# Shown when the guard blocks but the service didn't supply its own wording, and
# when fail-closed blocks a request the guard never got to see.
_DEFAULT_REFUSAL = "I can't help with that request."


class GuardrailsClient:
    """Thin async wrapper over `POST /v1/guard/input` and `/v1/guard/output`."""

    def __init__(
        self,
        cfg: SafetyCfg,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cfg = cfg
        self._api_key = api_key
        # An injected client (tests pass one backed by httpx.MockTransport).
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            if self._api_key:
                # The guardrails server accepts either header; send both so it
                # works whichever the deployment configured.
                headers["Authorization"] = f"Bearer {self._api_key}"
                headers["X-API-Key"] = self._api_key
            self._client = httpx.AsyncClient(
                base_url=self._cfg.base_url.rstrip("/"),
                timeout=self._cfg.timeout_s,
                headers=headers,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- the two checks -------------------------------------------------------
    async def check_input(
        self, text: str, *, context: list[dict[str, str]] | None = None
    ) -> GuardVerdict:
        """Judge a user message before the model runs."""
        if not self._cfg.enabled or not self._cfg.check_input:
            return GuardVerdict.allow(checked=False)
        payload: dict[str, Any] = {"input": text, "policy_id": self._cfg.policy_id}
        if context:
            payload["context"] = context
        return await self._post("/v1/guard/input", payload)

    async def check_output(
        self,
        input_text: str,
        output_text: str,
        *,
        docs: list[dict[str, str]] | None = None,
        system_prompt: str | None = None,
    ) -> GuardVerdict:
        """Judge the model's answer after the fact.

        `docs` (the retrieved chunks behind the answer) turns on the
        groundedness check; `system_prompt` drives the *local* leak check and is
        never forwarded to the judge.
        """
        if not self._cfg.enabled or not self._cfg.check_output:
            return GuardVerdict.allow(checked=False)
        if not output_text.strip():  # nothing to screen (e.g. an errored turn)
            return GuardVerdict.allow(checked=False)
        payload: dict[str, Any] = {
            "input": input_text,
            "output": output_text,
            "policy_id": self._cfg.policy_id,
        }
        if docs:
            payload["context_docs"] = docs
        if system_prompt:
            payload["system_prompt"] = system_prompt
        return await self._post("/v1/guard/output", payload)

    # -- transport ------------------------------------------------------------
    async def _post(self, path: str, payload: dict[str, Any]) -> GuardVerdict:
        try:
            resp = await self._http().post(path, json=payload)
            resp.raise_for_status()
            return self._parse(resp.json())
        except Exception as exc:
            # Unreachable / slow / 5xx / malformed body all land here. fail_open
            # keeps the app answering; fail_closed refuses rather than let an
            # unscreened answer through.
            detail = str(exc) or type(exc).__name__
            mode = "fail_open" if self._cfg.fail_open else "fail_closed"
            log.warning("guardrails_unreachable", path=path, error=detail, mode=mode)
            if self._cfg.fail_open:
                return GuardVerdict.allow(checked=False, error=detail)
            return GuardVerdict.block(_DEFAULT_REFUSAL, checked=False, error=detail)

    @staticmethod
    def _parse(body: dict[str, Any]) -> GuardVerdict:
        action = body.get("action", "allow")
        if action not in ("allow", "flag", "block"):
            action = "allow"
        refusal = body.get("refusal_message")
        if action == "block" and not refusal:
            refusal = _DEFAULT_REFUSAL
        return GuardVerdict(
            action=action,
            refusal_message=refusal,
            sanitized_output=body.get("sanitized_output"),
            modified=bool(body.get("modified", False)),
            reasons=list(body.get("reasons", []) or []),
            categories=list(body.get("categories", []) or []),
            checked=True,
        )
