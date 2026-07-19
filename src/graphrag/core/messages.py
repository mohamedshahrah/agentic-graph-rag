"""Reading text out of an LLM reply, whatever shape the provider returns.

A chat model's `.content` is not always a string. Providers that support
multi-part output — Gemini, Anthropic — return a *list of content blocks*
(`[{"type": "text", "text": "..."}, ...]`), and `str()` on that list yields a
Python repr, not the text: `json.loads` on it fails, a regex matches the wrong
braces, OCR returns garbage. Every place that consumes model text must go
through here so one provider's format can't silently break a downstream parse.
"""

from __future__ import annotations

from typing import Any


def content_to_text(content: Any) -> str:
    """Flatten a LangChain message `.content` to plain text.

    Handles the three shapes seen in practice: a plain string, a list of
    content blocks (dicts with a `text` key, or objects exposing `.text`), and
    anything else (coerced with `str`, as a last resort).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Text blocks carry `text`; skip non-text parts (images,
                # reasoning traces) rather than stringifying them in.
                if block.get("type", "text") in ("text", None) or "text" in block:
                    parts.append(str(block.get("text", "")))
            else:
                text = getattr(block, "text", None)
                if text is not None:
                    parts.append(str(text))
        return "".join(parts)
    return str(content)
