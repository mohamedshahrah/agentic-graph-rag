"""Auto-instrument the OpenAI SDK by wrapping chat completions in a span."""

from __future__ import annotations

from llmlens.tracer import span


def instrument_openai() -> bool:
    try:
        from openai.resources.chat.completions import Completions
    except ImportError:
        return False

    original = Completions.create
    if getattr(original, "_llmlens", False):
        return True

    def wrapped(self, *args, **kwargs):
        model = kwargs.get("model", "")
        with span(f"openai.chat {model}".strip(), kind="generation",
                  provider="openai", model=model) as sp:
            for msg in kwargs.get("messages", []) or []:
                sp.input(str(msg.get("content", "")), role=str(msg.get("role", "user")))
            resp = original(self, *args, **kwargs)
            try:
                usage = getattr(resp, "usage", None)
                if usage:
                    sp.usage(usage.prompt_tokens, usage.completion_tokens)
                sp.output(resp.choices[0].message.content or "")
            except Exception:
                pass
            return resp

    wrapped._llmlens = True  # type: ignore[attr-defined]
    Completions.create = wrapped  # type: ignore[method-assign]
    return True
