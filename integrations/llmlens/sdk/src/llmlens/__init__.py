"""llmlens SDK — instrument any LLM app.

    import llmlens
    llmlens.configure(api_key="sk_...", url="http://localhost:8000")
    llmlens.instrument("openai", "anthropic", "langchain")

    with llmlens.trace("handle_request", user_id="u1"):
        ...   # nested spans + provider calls are captured automatically

    @llmlens.observe()
    def step(): ...
"""

from __future__ import annotations

from llmlens.config import configure, get_config
from llmlens.integrations import callback_handler, instrument
from llmlens.tracer import (
    flush,
    observe,
    set_session,
    set_tags,
    set_user,
    span,
    trace,
)

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "instrument",
    "callback_handler",
    "trace",
    "span",
    "observe",
    "set_user",
    "set_session",
    "set_tags",
    "flush",
]
