"""Auto-instrumentation dispatcher: `instrument("openai", "anthropic", "langchain")`."""

from __future__ import annotations

import contextvars

_lc_handler_var: contextvars.ContextVar | None = None


def _instrument_langchain() -> bool:
    try:
        from langchain_core.tracers.context import register_configure_hook

        from llmlens.integrations.langchain import LlmlensCallbackHandler
    except ImportError:
        return False
    global _lc_handler_var
    if _lc_handler_var is None:
        _lc_handler_var = contextvars.ContextVar("llmlens_lc_handler", default=None)
        register_configure_hook(_lc_handler_var, True)
    _lc_handler_var.set(LlmlensCallbackHandler())
    return True


def callback_handler():
    """Return a LangChain callback handler for manual attachment
    (`config={"callbacks": [callback_handler()]}`)."""
    from llmlens.integrations.langchain import LlmlensCallbackHandler

    return LlmlensCallbackHandler()


def instrument(*names: str) -> dict[str, bool]:
    """Patch the named providers. Returns which succeeded (a provider whose
    library isn't installed simply reports False)."""
    from llmlens.integrations.anthropic import instrument_anthropic
    from llmlens.integrations.openai import instrument_openai

    result: dict[str, bool] = {}
    for name in names:
        if name == "openai":
            result["openai"] = instrument_openai()
        elif name == "anthropic":
            result["anthropic"] = instrument_anthropic()
        elif name == "langchain":
            result["langchain"] = _instrument_langchain()
        else:
            result[name] = False
    return result


__all__ = ["instrument", "callback_handler"]
