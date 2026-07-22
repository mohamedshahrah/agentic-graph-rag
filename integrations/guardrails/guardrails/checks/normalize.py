"""Unicode normalization + evasion scoring.

Produces a ``matchable`` copy of the text for the deterministic rule scanners while the
``original`` is preserved verbatim (the original is what gets redacted / returned /
judged — NFKC can change meaning, so we never mutate it in place).

Pipeline: NFKC -> strip invisibles -> fold ~40 Cyrillic/Greek confusables to Latin ->
collapse whitespace. Mixed-script words and invisible density feed an ``evasion_score``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ── Invisible / zero-width characters to strip ──────────────────────────────
_INVISIBLE: frozenset[str] = frozenset(
    [chr(c) for c in range(0x200B, 0x2010)]  # zero-width space..RTL mark (200B-200F)
    + [chr(c) for c in range(0x2060, 0x2065)]  # word-joiner..invisible-plus (2060-2064)
    + [chr(c) for c in range(0xFE00, 0xFE10)]  # variation selectors 1-16
    + ["﻿", "­", "᠎"]  # BOM/ZWNBSP, soft hyphen, Mongolian vowel sep
)


def _is_invisible(ch: str) -> bool:
    if ch in _INVISIBLE:
        return True
    # Supplementary variation selectors (U+E0100–U+E01EF).
    return 0xE0100 <= ord(ch) <= 0xE01EF


# ── Confusable folding: ~40 Cyrillic/Greek homoglyphs -> Latin ──────────────
_CONFUSABLES: dict[str, str] = {
    # Cyrillic lower
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "і": "i", "ј": "j", "ѕ": "s", "һ": "h", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    "ѓ": "r", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h",
    # Cyrillic upper
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ј": "J",
    "Ѕ": "S",
    # Greek
    "ο": "o", "Ο": "O", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ρ": "P", "Τ": "T", "Υ": "Y",
    "Χ": "X", "α": "a", "ρ": "p", "τ": "t", "ν": "v", "κ": "k",
}

# Collapse horizontal whitespace runs to a single space, but keep line structure
# (a lone newline) so line-anchored rules like role-line smuggling still work.
_HWS_RUN = re.compile(r"[^\S\n]+")
_VWS_RUN = re.compile(r"\s*\n\s*")


def _char_script(ch: str) -> str:
    """Coarse script bucket for a single character (letters only, else 'common')."""
    if not ch.isalpha():
        return "common"
    cp = ord(ch)
    if 0x0400 <= cp <= 0x04FF or 0x0500 <= cp <= 0x052F:
        return "cyrillic"
    if 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF:
        return "greek"
    if cp < 0x0250 or 0x1E00 <= cp <= 0x1EFF:
        return "latin"
    # Fall back to Unicode name prefix for everything else.
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "other"
    return name.split(" ", 1)[0].lower()


def _mixed_script_words(text: str) -> list[str]:
    """Words whose letters mix >1 real script (a classic homoglyph tell)."""
    out: list[str] = []
    for word in text.split():
        scripts = {s for s in (_char_script(c) for c in word) if s != "common"}
        if len(scripts) > 1:
            out.append(word)
    return out


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """Result of :func:`normalize`."""

    original: str
    matchable: str
    invisible_removed: int
    confusables_folded: int
    mixed_script_words: list[str] = field(default_factory=list)
    evasion_score: float = 0.0


def normalize(text: str) -> NormalizedText:
    """Return a :class:`NormalizedText` for ``text`` (never mutates the original)."""
    # 1. NFKC on a working copy (original stays raw).
    work = unicodedata.normalize("NFKC", text)

    # Detect mixed-script words *before* folding (folding erases the evidence).
    mixed = _mixed_script_words(work)

    # 2. Strip invisibles.
    invisible_removed = 0
    buf: list[str] = []
    for ch in work:
        if _is_invisible(ch):
            invisible_removed += 1
        else:
            buf.append(ch)

    # 3. Fold confusables.
    confusables_folded = 0
    for i, ch in enumerate(buf):
        repl = _CONFUSABLES.get(ch)
        if repl is not None:
            buf[i] = repl
            confusables_folded += 1

    # 4. Collapse whitespace (keep single newlines for line-anchored rules).
    collapsed = _HWS_RUN.sub(" ", "".join(buf))
    matchable = _VWS_RUN.sub("\n", collapsed).strip()

    return NormalizedText(
        original=text,
        matchable=matchable,
        invisible_removed=invisible_removed,
        confusables_folded=confusables_folded,
        mixed_script_words=mixed,
        evasion_score=_evasion_score(text, invisible_removed, len(mixed)),
    )


def _evasion_score(original: str, invisible_removed: int, mixed_words: int) -> float:
    """Risk in [0,1] from invisible-char density + homoglyph words.

    Any zero-width splice or homoglyph word alone should clear the default flag
    threshold (0.6) so the judge adjudicates; density pushes it toward block.
    """
    score = 0.0
    if invisible_removed > 0:
        density = invisible_removed / max(len(original), 1)
        score = max(score, min(1.0, 0.6 + 0.1 * invisible_removed + density))
    if mixed_words > 0:
        score = max(score, min(1.0, 0.6 + 0.2 * mixed_words))
    return round(score, 4)
