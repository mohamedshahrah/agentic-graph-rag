"""Tracing core: SpanRecord (the handle you enrich), context managers `trace`
and `span`, the `observe` decorator, and low-level `start`/`finish` used by the
provider callback integrations."""

from __future__ import annotations

import contextvars
import functools
import inspect
import random
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from llmlens.config import get_config
from llmlens.exporter import get_exporter
from llmlens.ids import gen_span_id, gen_trace_id

_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llmlens_trace", default=None
)
_current_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llmlens_span", default=None
)
# None = no sampling decision in this context; False = trace was sampled out,
# so every descendant span must be dropped too.
_trace_sampled: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "llmlens_sampled", default=None
)
_trace_attrs: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "llmlens_attrs", default=None
)


def _attrs() -> dict:
    return _trace_attrs.get() or {}


def _sample() -> bool:
    return random.random() < get_config().sample_rate


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SpanRecord:
    trace_id: str
    span_id: str
    name: str
    kind: str = "span"
    parent_span_id: str = ""
    start_time: datetime = field(default_factory=_now)
    end_time: datetime | None = None
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    status: str = "ok"
    status_message: str = ""
    user_id: str = ""
    session_id: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    content: list[dict] = field(default_factory=list)

    # -- enrichment helpers (chainable) --------------------------------------
    def update(self, **kwargs) -> "SpanRecord":
        for key, value in kwargs.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, value)
        return self

    def usage(self, input_tokens: int = 0, output_tokens: int = 0) -> "SpanRecord":
        self.input_tokens = int(input_tokens or 0)
        self.output_tokens = int(output_tokens or 0)
        self.total_tokens = self.input_tokens + self.output_tokens
        return self

    def input(self, text: str, role: str = "input") -> "SpanRecord":
        if get_config().record_content and text:
            self.content.append({"role": role, "content": str(text)})
        return self

    def output(self, text: str, role: str = "output") -> "SpanRecord":
        if get_config().record_content and text:
            self.content.append({"role": role, "content": str(text)})
        return self

    def error(self, message: str) -> "SpanRecord":
        self.status = "error"
        self.status_message = str(message)[:2000]
        return self

    def to_event(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "kind": self.kind,
            "provider": self.provider,
            "model": self.model,
            "start_time": self.start_time.isoformat(),
            "end_time": (self.end_time or _now()).isoformat(),
            "status": self.status,
            "status_message": self.status_message,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens or (self.input_tokens + self.output_tokens),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "tags": self.tags,
            "metadata": self.metadata,
            "content": self.content,
        }


class _NoopSpan(SpanRecord):
    """Returned when disabled/sampled-out so `with span(): ...` still works."""

    def __init__(self) -> None:
        super().__init__(trace_id="", span_id="", name="noop")


def _inherit_attrs(rec: SpanRecord) -> None:
    attrs = _attrs()
    rec.user_id = rec.user_id or attrs.get("user_id", "")
    rec.session_id = rec.session_id or attrs.get("session_id", "")
    if not rec.tags:
        rec.tags = list(attrs.get("tags", []))


def _emit(rec: SpanRecord) -> None:
    if not (rec.trace_id and rec.span_id):  # noop / sampled-out span
        return
    rec.end_time = rec.end_time or _now()
    get_exporter().emit(rec.to_event())


# -- low-level API (for callback-based integrations) --------------------------
def start(name: str, kind: str = "span", trace_id: str | None = None,
          parent_span_id: str | None = None, **attrs) -> SpanRecord:
    if not get_config().enabled or _trace_sampled.get() is False:
        return _NoopSpan()
    if trace_id is not None and not trace_id:
        return _NoopSpan()  # parent was sampled out — drop the whole chain
    if trace_id is None and _current_trace_id.get() is None and not _sample():
        return _NoopSpan()  # this would start a new trace: apply head sampling
    tid = trace_id or _current_trace_id.get() or gen_trace_id()
    parent = parent_span_id if parent_span_id is not None else (_current_span_id.get() or "")
    rec = SpanRecord(trace_id=tid, span_id=gen_span_id(), name=name, kind=kind,
                     parent_span_id=parent)
    rec.update(**attrs)
    _inherit_attrs(rec)
    return rec


def finish(rec: SpanRecord, status: str | None = None, status_message: str = "") -> None:
    if status:
        rec.status = status
    if status_message:
        rec.status_message = status_message
    _emit(rec)


# -- context-manager API (for manual / decorator use) -------------------------
@contextmanager
def trace(name: str, user_id: str = "", session_id: str = "", tags=None, metadata=None):
    cfg = get_config()
    if not cfg.enabled or not _sample():
        # Mark this context sampled-out so nested spans (and auto-instrumented
        # provider calls) are dropped too, instead of leaking as orphan traces.
        smp = _trace_sampled.set(False)
        try:
            yield _NoopSpan()
        finally:
            _trace_sampled.reset(smp)
        return
    rec = SpanRecord(trace_id=gen_trace_id(), span_id=gen_span_id(), name=name, kind="trace",
                     user_id=user_id, session_id=session_id, tags=list(tags or []),
                     metadata=dict(metadata or {}))
    t = _current_trace_id.set(rec.trace_id)
    s = _current_span_id.set(rec.span_id)
    a = _trace_attrs.set({"user_id": user_id, "session_id": session_id, "tags": list(tags or [])})
    try:
        yield rec
    except Exception as exc:
        rec.error(str(exc))
        raise
    finally:
        _emit(rec)
        _current_trace_id.reset(t)
        _current_span_id.reset(s)
        _trace_attrs.reset(a)


@contextmanager
def span(name: str, kind: str = "span", **attrs):
    cfg = get_config()
    if not cfg.enabled or _trace_sampled.get() is False:
        yield _NoopSpan()
        return
    started_trace = _current_trace_id.get() is None
    if started_trace and not _sample():
        # A standalone span starts a new trace, so head sampling applies here too.
        smp = _trace_sampled.set(False)
        try:
            yield _NoopSpan()
        finally:
            _trace_sampled.reset(smp)
        return
    tid = _current_trace_id.get() or gen_trace_id()
    rec = SpanRecord(trace_id=tid, span_id=gen_span_id(), name=name, kind=kind,
                     parent_span_id=_current_span_id.get() or "")
    rec.update(**attrs)
    _inherit_attrs(rec)
    t = _current_trace_id.set(tid) if started_trace else None
    s = _current_span_id.set(rec.span_id)
    try:
        yield rec
    except Exception as exc:
        rec.error(str(exc))
        raise
    finally:
        _emit(rec)
        _current_span_id.reset(s)
        if t is not None:
            _current_trace_id.reset(t)


def observe(name: str | None = None, kind: str = "span"):
    """Decorator: wrap a function call in a span."""

    def decorator(fn):
        span_name = name or fn.__name__
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                with span(span_name, kind=kind):
                    return await fn(*args, **kwargs)
            return awrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with span(span_name, kind=kind):
                return fn(*args, **kwargs)
        return wrapper

    return decorator


# -- context helpers ----------------------------------------------------------
def _set_attr(key: str, value) -> None:
    # Copy-on-write into the current context only: mutating the ContextVar's
    # shared default dict would leak the value into every other trace/thread.
    _trace_attrs.set({**_attrs(), key: value})


def set_user(user_id: str) -> None:
    _set_attr("user_id", user_id)


def set_session(session_id: str) -> None:
    _set_attr("session_id", session_id)


def set_tags(tags: list[str]) -> None:
    _set_attr("tags", list(tags))


def flush(timeout: float = 5.0) -> None:
    get_exporter().flush(timeout)
