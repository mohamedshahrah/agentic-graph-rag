"""Deterministic prompt-injection / jailbreak rules.

``scan(matchable)`` returns :class:`RuleHit`s. Two tiers:

* ``block`` — near-zero benign use; the pipeline short-circuits to BLOCK on these.
* ``flag``  — suspicious but ambiguous; scored 0.65 for the judge to adjudicate.

All patterns use **bounded** quantifiers (``{0,N}``) so a hostile input can't trigger
catastrophic backtracking (ReDoS). Patterns run on the normalized ``matchable`` text.
"""

from __future__ import annotations

import re
from typing import Literal, NamedTuple

from ..schemas import RuleHit

Tier = Literal["block", "flag"]


class _Rule(NamedTuple):
    rule_id: str
    category: str
    tier: Tier
    pattern: re.Pattern[str]


_I = re.IGNORECASE

# ── Block-tier families (short-circuit; near-zero benign use) ────────────────
_BLOCK_RULES: list[_Rule] = [
    # Instruction override: verb + qualifier(previous/all/system/...) + target.
    _Rule(
        "instruction_override",
        "prompt_injection",
        "block",
        re.compile(
            r"\b(?:ignore|disregard|forget|overrid\w+|pay\s+no\s+attention\s+to|"
            r"do\s+not\s+follow|don'?t\s+follow)\b"
            r"(?:\s+\w+){0,3}?\s+"
            r"(?:previous|prior|above|earlier|preceding|initial|original|all|any|"
            r"the\s+system|system|your)\b"
            r"(?:\s+\w+){0,3}?\s+"
            r"(?:instruction|instructions|prompt|prompts|rule|rules|direction|"
            r"directions|guideline|guidelines|command|commands|context)\b",
            _I,
        ),
    ),
    # Chat-template smuggling markers.
    _Rule(
        "chat_template_smuggling",
        "prompt_injection",
        "block",
        re.compile(
            r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|<\|system\|>|<\|user\|>|"
            r"<\|assistant\|>|<<SYS>>|<</SYS>>|\[/?INST\]|###\s*(?:system|instruction)\s*:",
            _I,
        ),
    ),
    # System-prompt / instruction extraction.
    _Rule(
        "prompt_extraction",
        "prompt_injection",
        "block",
        re.compile(
            r"\b(?:reveal|show|share|print|display|repeat(?:\s+back)?|output|expose|"
            r"leak|disclose|give\s+me|tell\s+me|send\s+me)\b"
            r"(?:\s+\w+){0,3}?\s+"
            r"(?:your|the\s+system|system)\s+"
            r"(?:initial\s+|original\s+|full\s+|exact\s+|verbatim\s+)?"
            r"(?:system\s+)?(?:prompt|message|instructions?|guidelines?|directives?)\b",
            _I,
        ),
    ),
    # Jailbreak personas / modes with genuinely near-zero benign use.
    _Rule(
        "jailbreak_persona",
        "jailbreak",
        "block",
        re.compile(
            r"\bdo\s+anything\s+now\b|"
            r"\b(?:god|sudo|kernel|root|jailbreak|jailbroken|unfiltered|unrestricted|evil)"
            r"\s+mode\b",
            _I,
        ),
    ),
    # "DAN" / "STAN" only when upper-case (avoids the name "Dan").
    _Rule(
        "jailbreak_persona_acronym",
        "jailbreak",
        "block",
        re.compile(r"\b(?:DAN|STAN|DUDE)\b"),  # case-SENSITIVE on purpose
    ),
]

# ── Flag-tier families (0.65; judge adjudicates) ────────────────────────────
_FLAG_RULES: list[_Rule] = [
    # Leetspeak / spaced "ignore ... instructions".
    _Rule(
        "leetspeak_override",
        "prompt_injection",
        "flag",
        re.compile(
            r"\b[i1l|]\s*g\s*n\s*[o0]\s*r\s*e\b(?:\s+\w+){0,4}?\s+"
            r"(?:instruction|prompt|rule)",
            _I,
        ),
    ),
    # Role-line smuggling ("system:" / "assistant:" at the start of a line).
    _Rule(
        "role_line",
        "prompt_injection",
        "flag",
        re.compile(r"^\s*(?:system|assistant)\s*:", _I | re.MULTILINE),
    ),
    # Probing for the instructions.
    _Rule(
        "instruction_probe",
        "prompt_injection",
        "flag",
        re.compile(
            r"\bwhat\s+(?:are|were|is)\s+your\s+"
            r"(?:instructions?|system\s+prompt|rules?|guidelines?|directives?)\b",
            _I,
        ),
    ),
    # "no restrictions / filters".
    _Rule(
        "no_restrictions",
        "jailbreak",
        "flag",
        re.compile(
            r"\bno\s+(?:restrictions?|filters?|limitations?|rules?|guidelines?|"
            r"censorship|boundaries|guardrails?)\b",
            _I,
        ),
    ),
    # "developer / debug mode" (benign uses exist -> flag, not block).
    _Rule(
        "developer_mode",
        "jailbreak",
        "flag",
        re.compile(r"\b(?:developer|dev|debug)\s+mode\b", _I),
    ),
    # "pretend you are unrestricted / free from rules".
    _Rule(
        "pretend_unrestricted",
        "jailbreak",
        "flag",
        re.compile(
            r"\bpretend\b(?:\s+\w+){0,4}?\s+"
            r"(?:unrestricted|unfiltered|not\s+bound|no\s+longer\s+bound|"
            r"free\s+from|without\s+(?:any\s+)?(?:restrictions?|rules?|filters?))",
            _I,
        ),
    ),
    # Hypothetical framing adjacent to harm vocabulary.
    _Rule(
        "hypothetical_harm",
        "harmful_content",
        "flag",
        re.compile(
            r"\b(?:hypothetical\w*|imagine|suppose|for\s+(?:educational|research)\s+"
            r"purposes|in\s+a\s+(?:fictional|story|roleplay))\b.{0,60}?\b"
            r"(?:weapon|bomb|explosive|malware|ransomware|virus|exploit|hack|"
            r"poison|toxin|meth|fentanyl)\w*",
            _I,
        ),
    ),
    # Decode-then-execute.
    _Rule(
        "decode_and_execute",
        "prompt_injection",
        "flag",
        re.compile(
            r"\b(?:decode|decrypt|un[\- ]?base64|from\s+base64|rot13|reverse)\b"
            r"(?:\s+\w+){0,6}?\s+(?:and\s+)?"
            r"(?:execute|run|follow|do|obey|comply|perform)\b",
            _I,
        ),
    ),
]

# Opt-in: a long base64 blob (noisy — off by default).
_BASE64_RULE = _Rule(
    "base64_blob",
    "evasion",
    "flag",
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
)


def scan(matchable: str, *, include_base64: bool = False) -> list[RuleHit]:
    """Scan normalized text and return every rule match as a :class:`RuleHit`."""
    rules = [*_BLOCK_RULES, *_FLAG_RULES]
    if include_base64:
        rules.append(_BASE64_RULE)

    hits: list[RuleHit] = []
    for rule in rules:
        for m in rule.pattern.finditer(matchable):
            hits.append(
                RuleHit(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    tier=rule.tier,
                    span=(m.start(), m.end()),
                    snippet=matchable[m.start() : m.end()][:120],
                )
            )
    return hits
