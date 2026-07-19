"""Neutralize document-derived text before it enters a prompt.

Retrieved chunks, graph entity names, OCR output — anything extracted from an
uploaded document — is untrusted: it can carry chat-template special tokens
that break message framing, control characters, or text that forges our own
data envelope. This strips what could change how a model *parses* the context;
refusing to *follow* instructions embedded in the data is the system prompt's
job (see agent/prompts.py).
"""

from __future__ import annotations

import re

# C0 controls except \n and \t, plus DEL.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_SPECIAL_TOKENS = re.compile(
    r"<\|[a-zA-Z0-9_]+\|>"  # <|im_start|>, <|endoftext|>, <|eot_id|>, ...
    r"|\[/?INST\]"          # llama-2 instruction markers
    r"|<</?SYS>>"           # llama-2 system markers
    r"|</?s>"               # sentencepiece BOS/EOS
)

# The literal envelope tag from agent/prompts.py. A document containing the
# closing tag could otherwise break out of the data envelope and speak with
# the authority of the surrounding prompt.
_ENVELOPE = re.compile(r"(?i)</?\s*untrusted_data")


def sanitize_untrusted(text: str, max_chars: int = 4000) -> str:
    """Make document-derived text safe to place inside a prompt envelope."""
    text = _CONTROL.sub("", text)
    text = _SPECIAL_TOKENS.sub("", text)
    # `untrusted_data` -> `untrusted-data`: still readable, can no longer
    # open or close the real envelope.
    text = _ENVELOPE.sub(lambda m: m.group().replace("_", "-"), text)
    if len(text) > max_chars:
        text = text[:max_chars] + " …[truncated]"
    return text
