"""PII + secret detection and redaction.

``scan(text)`` returns :class:`RuleHit`s (category ``"pii"`` or ``"secrets"``; ``rule_id``
is the redaction label, e.g. ``EMAIL``, ``OPENAI_KEY``). ``redact(text)`` replaces the
matched spans with ``[REDACTED:{LABEL}]``. Credit-card candidates are Luhn-gated to cut
false positives. Runs on the **original** text (not the normalized copy) so redaction
offsets line up with what the caller sent.
"""

from __future__ import annotations

import re
from typing import Literal, NamedTuple

from ..schemas import RuleHit

Category = Literal["pii", "secrets"]


class _Pattern(NamedTuple):
    label: str
    category: Category
    pattern: re.Pattern[str]
    luhn_gated: bool = False
    enabled_by_default: bool = True


# ── Secret patterns (ordered: most specific first) ──────────────────────────
_SECRETS: list[_Pattern] = [
    _Pattern("ANTHROPIC_KEY", "secrets", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    _Pattern("STRIPE_KEY", "secrets", re.compile(r"\b[rsp]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    _Pattern("OPENAI_KEY", "secrets", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    _Pattern("AWS_ACCESS_KEY", "secrets", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    _Pattern("GOOGLE_API_KEY", "secrets", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    _Pattern("GITHUB_TOKEN", "secrets", re.compile(r"\bgh[posru]_[A-Za-z0-9]{36,}\b")),
    _Pattern("SLACK_TOKEN", "secrets", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    _Pattern(
        "JWT",
        "secrets",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"),
    ),
    _Pattern(
        "PRIVATE_KEY",
        "secrets",
        re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    ),
    _Pattern(
        "GENERIC_SECRET",
        "secrets",
        re.compile(
            r"\b(?:api[_\-]?key|secret[_\-]?key|secret|access[_\-]?token|auth[_\-]?token"
            r"|token|password|passwd|pwd)\b\s*[=:]\s*['\"]?[A-Za-z0-9_\-./+]{8,}['\"]?",
            re.IGNORECASE,
        ),
    ),
]

# ── PII patterns ────────────────────────────────────────────────────────────
_PII: list[_Pattern] = [
    _Pattern(
        "EMAIL",
        "pii",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    _Pattern("SSN", "pii", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    _Pattern(
        "IBAN",
        "pii",
        re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b"),
    ),
    _Pattern(
        "PHONE",
        "pii",
        re.compile(
            r"(?<![\w.])(?:\+?\d{1,3}[\s.\-]?)?"
            r"(?:\(\d{3}\)|\d{3})[\s.\-]\d{3}[\s.\-]\d{4}(?![\w])"
            r"|(?<![\w.])\+\d{7,15}(?![\w])"
        ),
    ),
    _Pattern(
        "CREDIT_CARD",
        "pii",
        re.compile(r"\b(?:\d[ \-]?){13,19}\b"),
        luhn_gated=True,
    ),
    # Off by default (too noisy): IPv4.
    _Pattern(
        "IP",
        "pii",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
        enabled_by_default=False,
    ),
]

_ALL: list[_Pattern] = [*_SECRETS, *_PII]
_BY_LABEL: dict[str, _Pattern] = {p.label: p for p in _ALL}


def luhn(number: str) -> bool:
    """Return True iff the digits of ``number`` pass the Luhn checksum."""
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan(text: str, *, include_disabled: bool = False) -> list[RuleHit]:
    """Return non-overlapping PII/secret matches, most-specific pattern winning."""
    raw: list[tuple[int, int, _Pattern]] = []
    for pat in _ALL:
        if not pat.enabled_by_default and not include_disabled:
            continue
        for m in pat.pattern.finditer(text):
            if pat.luhn_gated and not luhn(m.group()):
                continue
            raw.append((m.start(), m.end(), pat))

    # Resolve overlaps: prefer earlier start, then longer match, then list order.
    order = {id(p): i for i, p in enumerate(_ALL)}
    raw.sort(key=lambda t: (t[0], -(t[1] - t[0]), order[id(t[2])]))

    hits: list[RuleHit] = []
    covered_to = -1
    for start, end, pat in raw:
        if start < covered_to:
            continue  # overlaps an already-accepted, higher-priority span
        hits.append(
            RuleHit(
                rule_id=pat.label,
                category=pat.category,
                tier="flag",
                span=(start, end),
                snippet=text[start:end][:120],
            )
        )
        covered_to = end
    hits.sort(key=lambda h: h.span[0])
    return hits


def redact(
    text: str,
    *,
    categories: tuple[Category, ...] = ("pii", "secrets"),
    include_disabled: bool = False,
    hits: list[RuleHit] | None = None,
) -> tuple[str, list[RuleHit]]:
    """Replace matched spans with ``[REDACTED:{LABEL}]``.

    Returns ``(redacted_text, applied_hits)``. Only hits whose category is in
    ``categories`` are redacted; other detected hits are left in place but still
    returned so callers can see everything that was found.
    """
    found = hits if hits is not None else scan(text, include_disabled=include_disabled)
    applied = [h for h in found if h.category in categories]
    # Replace right-to-left so earlier spans keep their offsets.
    out = text
    for hit in sorted(applied, key=lambda h: h.span[0], reverse=True):
        start, end = hit.span
        out = f"{out[:start]}[REDACTED:{hit.rule_id}]{out[end:]}"
    return out, found
