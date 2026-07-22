"""Judge orchestration: prompt -> provider call -> defensive parse -> typed verdict.

Concurrency is bounded by a semaphore. Each call is schema-constrained where the provider
supports it, but the defensive parser always runs regardless (models lie about JSON). One
repair retry is attempted on a parse failure before giving up with a ``JudgeParseError``.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError, model_validator

from ..config import Settings
from ..policy import Policy
from ..schemas import ChatTurn, ContextDoc
from .errors import JudgeParseError
from .prompts import (
    INPUT_VERDICT_SCHEMA,
    OUTPUT_VERDICT_SCHEMA_DOCS,
    OUTPUT_VERDICT_SCHEMA_NODOCS,
    build_input_prompt,
    build_output_prompt,
)
from .providers import LLMProvider

# Appended to the system prompt on the single repair retry (also the MockProvider's cue).
REPAIR_SUFFIX = "\n\nReturn ONLY valid JSON matching the schema. No prose, no code fences."

_MAX_REASON = 200
_MAX_PHRASE = 200
_MAX_LIST = 10


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


class InputVerdict(BaseModel):
    prompt_injection: float = 0.0
    jailbreak: float = 0.0
    off_topic: float = 0.0
    harmful_content: float = 0.0
    reason: str = ""
    flagged_phrases: list[str] = []

    @model_validator(mode="after")
    def _sanitize(self) -> "InputVerdict":
        self.prompt_injection = _clamp(self.prompt_injection)
        self.jailbreak = _clamp(self.jailbreak)
        self.off_topic = _clamp(self.off_topic)
        self.harmful_content = _clamp(self.harmful_content)
        self.reason = self.reason[:_MAX_REASON]
        self.flagged_phrases = [p[:_MAX_PHRASE] for p in self.flagged_phrases[:_MAX_LIST]]
        return self

    def scores(self) -> dict[str, float]:
        return {
            "prompt_injection": self.prompt_injection,
            "jailbreak": self.jailbreak,
            "off_topic": self.off_topic,
            "harmful_content": self.harmful_content,
        }


class OutputVerdict(BaseModel):
    ungrounded: float = 0.0
    harmful_content: float = 0.0
    off_topic: float = 0.0
    unsupported_claims: list[str] = []
    reason: str = ""

    @model_validator(mode="after")
    def _sanitize(self) -> "OutputVerdict":
        self.ungrounded = _clamp(self.ungrounded)
        self.harmful_content = _clamp(self.harmful_content)
        self.off_topic = _clamp(self.off_topic)
        self.reason = self.reason[:_MAX_REASON]
        self.unsupported_claims = [c[:_MAX_PHRASE] for c in self.unsupported_claims[:_MAX_LIST]]
        return self

    def scores(self) -> dict[str, float]:
        return {
            "ungrounded": self.ungrounded,
            "harmful_content": self.harmful_content,
            "off_topic": self.off_topic,
        }


@dataclass
class JudgeOutcome:
    verdict: InputVerdict | OutputVerdict
    latency_ms: float


# ── Defensive parsing ───────────────────────────────────────────────────────
def _first_balanced_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` substring, respecting string escapes."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_verdict(raw: str, model_cls: type[BaseModel]) -> BaseModel:
    """Strip fences/prose, grab the first JSON object, validate. Raise on any failure."""
    obj = _first_balanced_object(raw or "")
    if obj is None:
        raise JudgeParseError("no JSON object in response")
    try:
        data = json.loads(obj)
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise JudgeParseError("top-level JSON is not an object")
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise JudgeParseError(f"schema mismatch: {exc}") from exc


# ── Judge ───────────────────────────────────────────────────────────────────
class Judge:
    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings
        self._sem = asyncio.Semaphore(settings.max_concurrent_judge)

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def model(self) -> str | None:
        return self._provider.model

    async def evaluate_input(
        self, policy: Policy, text: str, context: list[ChatTurn]
    ) -> JudgeOutcome:
        system, user = build_input_prompt(policy, text, context)
        return await self._run(system, user, INPUT_VERDICT_SCHEMA, InputVerdict)

    async def evaluate_output(
        self, policy: Policy, user_input: str, output: str, docs: list[ContextDoc]
    ) -> JudgeOutcome:
        system, user, has_docs = build_output_prompt(policy, user_input, output, docs)
        schema = OUTPUT_VERDICT_SCHEMA_DOCS if has_docs else OUTPUT_VERDICT_SCHEMA_NODOCS
        return await self._run(system, user, schema, OutputVerdict)

    async def _run(
        self, system: str, user: str, schema: dict, model_cls: type[BaseModel]
    ) -> JudgeOutcome:
        t0 = time.perf_counter()
        async with self._sem:
            raw = await self._call(system, user, schema)
            try:
                verdict = parse_verdict(raw, model_cls)
            except JudgeParseError:
                raw = await self._call(system + REPAIR_SUFFIX, user, schema)
                verdict = parse_verdict(raw, model_cls)  # propagate on 2nd failure
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return JudgeOutcome(verdict=verdict, latency_ms=latency_ms)  # type: ignore[arg-type]

    async def _call(self, system: str, user: str, schema: dict) -> str:
        return await self._provider.complete(
            system=system,
            user=user,
            max_tokens=self._settings.llm_max_tokens,
            timeout=self._settings.llm_timeout_s,
            json_schema=schema,
        )
