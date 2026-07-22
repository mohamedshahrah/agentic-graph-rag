"""Policy model + registry.

A ``Policy`` fully specifies how one app is guarded: its scope (for the judge), per-
category thresholds, judge behaviour, custom rules, and limits. Every field has a
default, so a minimal YAML of just ``id`` + ``scope.app_description`` is valid.

``PolicyRegistry.load_dir()`` scans ``*.yaml``, always guarantees a ``default`` policy,
compiles ``deny_topics``/``custom_rules`` regexes once at load, and exposes
``policy.content_hash`` (used as part of the verdict-cache key so editing a policy
auto-invalidates its cached verdicts).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .config import FailMode
from .schemas import PolicySummary, RuleHit, Scope

RuleAction = Literal["block", "flag", "ignore"]


class CheckConfig(BaseModel):
    """Per-category detection configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    flag_at: float = Field(default=0.6, ge=0.0, le=1.1)
    block_at: float = Field(default=0.85, ge=0.0, le=1.1)  # 1.1 == never auto-block
    rule_action: RuleAction = "flag"
    redact: bool = False
    redact_before_judge: bool = False
    min_overlap_chars: int = 40  # system_prompt_leak only


def _cfg(**kw: object) -> CheckConfig:
    return CheckConfig(**kw)  # type: ignore[arg-type]


class InputChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_injection: CheckConfig = Field(default_factory=lambda: _cfg(rule_action="block"))
    jailbreak: CheckConfig = Field(default_factory=lambda: _cfg(rule_action="block"))
    off_topic: CheckConfig = Field(default_factory=lambda: _cfg(block_at=1.1))
    harmful_content: CheckConfig = Field(default_factory=CheckConfig)
    secrets: CheckConfig = Field(
        default_factory=lambda: _cfg(redact=True, redact_before_judge=True, block_at=1.1)
    )
    pii: CheckConfig = Field(default_factory=lambda: _cfg(redact=True, block_at=1.1))
    evasion: CheckConfig = Field(default_factory=lambda: _cfg(block_at=1.1))


class OutputChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ungrounded: CheckConfig = Field(default_factory=lambda: _cfg(flag_at=0.6, block_at=0.9))
    harmful_content: CheckConfig = Field(default_factory=CheckConfig)
    off_topic: CheckConfig = Field(default_factory=lambda: _cfg(block_at=1.1))
    pii: CheckConfig = Field(default_factory=lambda: _cfg(redact=True, block_at=1.1))
    secrets: CheckConfig = Field(
        default_factory=lambda: _cfg(redact=True, redact_before_judge=True, block_at=1.1)
    )
    system_prompt_leak: CheckConfig = Field(
        default_factory=lambda: _cfg(rule_action="block", block_at=0.85)
    )


class Checks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: InputChecks = Field(default_factory=InputChecks)
    output: OutputChecks = Field(default_factory=OutputChecks)


class JudgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    trigger: Literal["always", "on_rule_flag", "never"] = "always"
    include_context_turns: int = Field(default=6, ge=0)
    max_context_doc_chars: int = Field(default=2000, ge=0)
    max_total_doc_chars: int = Field(default=8000, ge=0)


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_input_chars: int = Field(default=20_000, ge=1)
    max_output_chars: int = Field(default=20_000, ge=1)


class CacheConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    ttl_seconds: int = Field(default=300, ge=0)


class CustomRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    pattern: str
    category: str = "custom"
    action: Literal["block", "flag"] = "flag"
    description: str = ""


class Policy(BaseModel):
    """Full guard configuration for a single app."""

    model_config = ConfigDict(extra="forbid")

    id: str
    description: str = ""
    scope: Scope = Field(default_factory=Scope)
    refusal_message: str = "Sorry, I can't help with that request."
    fail_mode: FailMode = "flag"
    checks: Checks = Field(default_factory=Checks)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    custom_rules: list[CustomRule] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    # Compiled at load; excluded from serialization + content_hash.
    _deny_patterns: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _custom_compiled: list[tuple[CustomRule, re.Pattern[str]]] = PrivateAttr(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        self._deny_patterns = [_compile(t) for t in self.scope.deny_topics if t.strip()]
        self._custom_compiled = [(r, _compile(r.pattern)) for r in self.custom_rules]

    @property
    def content_hash(self) -> str:
        """sha256 of the canonical policy content (cache-key component)."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def scan_policy_rules(self, matchable: str) -> list[RuleHit]:
        """Deterministic deny-topic + custom-rule matches against normalized text."""
        hits: list[RuleHit] = []
        for pat in self._deny_patterns:
            for m in pat.finditer(matchable):
                hits.append(
                    RuleHit("deny_topic", "off_topic", "flag", (m.start(), m.end()),
                            matchable[m.start() : m.end()][:120])
                )
        for rule, pat in self._custom_compiled:
            for m in pat.finditer(matchable):
                hits.append(
                    RuleHit(rule.id, rule.category, rule.action, (m.start(), m.end()),
                            matchable[m.start() : m.end()][:120])
                )
        return hits

    def to_summary(self) -> PolicySummary:
        return PolicySummary(
            id=self.id,
            description=self.description,
            scope=self.scope,
            fail_mode=self.fail_mode,
            input_checks=[k for k, v in self.checks.input if v.enabled],
            output_checks=[k for k, v in self.checks.output if v.enabled],
        )


def _compile(pattern: str) -> re.Pattern[str]:
    """Compile a policy pattern case-insensitively; fall back to a literal match."""
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)


class PolicyRegistry:
    """In-memory set of loaded policies, always including a ``default``."""

    def __init__(self, policies: dict[str, Policy], default_id: str = "default") -> None:
        self._policies = policies
        self.default_id = default_id

    @classmethod
    def load_dir(cls, path: str | Path, default_id: str = "default") -> PolicyRegistry:
        policies: dict[str, Policy] = {}
        directory = Path(path)
        if directory.is_dir():
            for f in sorted(directory.glob("*.yaml")):
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                pol = Policy(**data)
                policies[pol.id] = pol
        # Guarantee a packaged default even with an empty/missing directory.
        if default_id not in policies:
            policies[default_id] = Policy(id=default_id, description="Built-in default policy.")
        return cls(policies, default_id)

    def get(self, policy_id: str) -> Policy:
        return self._policies[policy_id]

    def __contains__(self, policy_id: str) -> bool:
        return policy_id in self._policies

    def ids(self) -> list[str]:
        return sorted(self._policies)

    def summaries(self) -> list[PolicySummary]:
        return [self._policies[pid].to_summary() for pid in self.ids()]
