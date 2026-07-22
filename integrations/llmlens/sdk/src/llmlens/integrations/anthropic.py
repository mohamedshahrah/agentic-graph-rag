"""Auto-instrument the Anthropic SDK by wrapping Messages.create in a span."""

from __future__ import annotations

from llmlens.tracer import span


def instrument_anthropic() -> bool:
    try:
        from anthropic.resources.messages import Messages
    except ImportError:
        return False

    original = Messages.create
    if getattr(original, "_llmlens", False):
        return True

    def wrapped(self, *args, **kwargs):
        model = kwargs.get("model", "")
        with span(f"anthropic.messages {model}".strip(), kind="generation",
                  provider="anthropic", model=model) as sp:
            for msg in kwargs.get("messages", []) or []:
                sp.input(str(msg.get("content", "")), role=str(msg.get("role", "user")))
            resp = original(self, *args, **kwargs)
            try:
                usage = getattr(resp, "usage", None)
                if usage:
                    sp.usage(usage.input_tokens, usage.output_tokens)
                blocks = getattr(resp, "content", []) or []
                text = "".join(getattr(b, "text", "") for b in blocks)
                sp.output(text)
            except Exception:
                pass
            return resp

    wrapped._llmlens = True  # type: ignore[attr-defined]
    Messages.create = wrapped  # type: ignore[method-assign]
    return True
