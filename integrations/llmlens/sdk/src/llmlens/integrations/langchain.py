"""LangChain callback handler → llmlens spans.

This is the primary way to instrument LangChain / LangGraph apps (like the
agentic-graph-rag project): it maps LangChain's run events onto our trace/span
model, capturing model, tokens, latency, tool calls, and errors.
"""

from __future__ import annotations

from typing import Any

from llmlens.tracer import SpanRecord, finish, start

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # pragma: no cover - only imported when instrumenting LangChain
    BaseCallbackHandler = object  # type: ignore[assignment,misc]


def _provider(serialized: dict | None) -> str:
    ids = " ".join(str(x).lower() for x in (serialized or {}).get("id", []))
    for name in ("anthropic", "openai", "google", "ollama", "cohere", "mistral", "bedrock"):
        if name in ids:
            return name
    return ""


def _model(serialized: dict | None, kwargs: dict) -> str:
    params = kwargs.get("invocation_params") or {}
    if params.get("model"):
        return str(params["model"])
    if params.get("model_name"):
        return str(params["model_name"])
    ser_kwargs = (serialized or {}).get("kwargs", {})
    return str(ser_kwargs.get("model") or ser_kwargs.get("model_name") or "")


class LlmlensCallbackHandler(BaseCallbackHandler):  # type: ignore[misc]
    def __init__(self) -> None:
        self._runs: dict[Any, SpanRecord] = {}

    # -- helpers --------------------------------------------------------------
    def _begin(self, run_id, parent_run_id, name, kind, **attrs) -> None:
        parent = self._runs.get(parent_run_id) if parent_run_id else None
        rec = start(
            name, kind=kind,
            trace_id=parent.trace_id if parent else None,
            parent_span_id=parent.span_id if parent else "",
            **attrs,
        )
        self._runs[run_id] = rec

    def _end(self, run_id, *, status="ok", status_message="", **updates) -> None:
        rec = self._runs.pop(run_id, None)
        if rec is None:
            return
        rec.update(**{k: v for k, v in updates.items() if k in rec.__dataclass_fields__})
        finish(rec, status=status, status_message=status_message)

    # -- LLM ------------------------------------------------------------------
    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
        model = _model(serialized, kwargs)
        self._begin(run_id, parent_run_id, f"llm {model}".strip(), "generation",
                    provider=_provider(serialized), model=model)
        rec = self._runs.get(run_id)
        if rec:
            for p in prompts or []:
                rec.input(str(p), role="user")

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        model = _model(serialized, kwargs)
        self._begin(run_id, parent_run_id, f"chat {model}".strip(), "generation",
                    provider=_provider(serialized), model=model)
        rec = self._runs.get(run_id)
        if rec:
            for batch in messages or []:
                for msg in batch:
                    rec.input(str(getattr(msg, "content", msg)),
                              role=getattr(msg, "type", "user"))

    def on_llm_end(self, response, *, run_id, **kwargs):
        rec = self._runs.get(run_id)
        if rec is not None:
            self._apply_llm_result(rec, response)
        self._end(run_id)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", status_message=str(error))

    def _apply_llm_result(self, rec: SpanRecord, response) -> None:
        out = getattr(response, "llm_output", None) or {}
        usage = out.get("token_usage") or out.get("usage") or {}
        in_tok = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        out_tok = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        if out.get("model_name"):
            rec.model = rec.model or str(out["model_name"])
        try:
            gen = response.generations[0][0]
            if not (in_tok or out_tok):
                um = getattr(getattr(gen, "message", None), "usage_metadata", None) or {}
                in_tok = um.get("input_tokens", 0)
                out_tok = um.get("output_tokens", 0)
            rec.output(getattr(gen, "text", "") or "")
        except Exception:
            pass
        rec.usage(in_tok, out_tok)

    # -- chains ---------------------------------------------------------------
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "chain"
        self._begin(run_id, parent_run_id, str(name), "span")

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._end(run_id)

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", status_message=str(error))

    # -- tools ----------------------------------------------------------------
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        name = (serialized or {}).get("name") or "tool"
        self._begin(run_id, parent_run_id, str(name), "tool")
        rec = self._runs.get(run_id)
        if rec:
            rec.input(str(input_str), role="tool_input")

    def on_tool_end(self, output, *, run_id, **kwargs):
        rec = self._runs.get(run_id)
        if rec:
            rec.output(str(output), role="tool_output")
        self._end(run_id)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", status_message=str(error))
