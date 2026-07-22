from llmlens.config import configure
from llmlens.tracer import SpanRecord


def test_to_event_shape():
    configure(record_content=True)
    rec = SpanRecord(trace_id="t", span_id="s", name="chat", kind="generation",
                     provider="openai", model="gpt-4o")
    rec.usage(10, 5).input("hi", role="user").output("yo")
    ev = rec.to_event()
    assert ev["kind"] == "generation"
    assert ev["model"] == "gpt-4o"
    assert ev["total_tokens"] == 15
    assert any(c["role"] == "user" for c in ev["content"])
    assert "start_time" in ev and "end_time" in ev


def test_content_suppressed_when_disabled():
    configure(record_content=False)
    rec = SpanRecord(trace_id="t", span_id="s", name="x")
    rec.input("secret prompt")
    assert rec.to_event()["content"] == []
    configure(record_content=True)  # reset for other tests


def test_error_sets_status():
    rec = SpanRecord(trace_id="t", span_id="s", name="x")
    rec.error("RateLimitError")
    assert rec.to_event()["status"] == "error"


def test_sampled_out_trace_drops_children_too(monkeypatch):
    """sample_rate must drop the whole tree: child spans and start()/finish()
    chains of a sampled-out trace must not leak as orphan root traces."""
    from llmlens import tracer

    emitted: list[dict] = []

    class FakeExporter:
        def emit(self, event: dict) -> None:
            emitted.append(event)

        def flush(self, timeout: float = 5.0) -> None:
            pass

    monkeypatch.setattr(tracer, "get_exporter", lambda: FakeExporter())
    configure(sample_rate=0.0)
    try:
        with tracer.trace("root"):
            with tracer.span("child"):
                pass
            root = tracer.start("lc-root")
            child = tracer.start("lc-child", trace_id=root.trace_id,
                                 parent_span_id=root.span_id)
            tracer.finish(child)
            tracer.finish(root)
        with tracer.span("standalone"):
            pass
    finally:
        configure(sample_rate=1.0)
    assert emitted == []


def test_sampled_in_trace_keeps_ids_consistent(monkeypatch):
    from llmlens import tracer

    emitted: list[dict] = []

    class FakeExporter:
        def emit(self, event: dict) -> None:
            emitted.append(event)

        def flush(self, timeout: float = 5.0) -> None:
            pass

    monkeypatch.setattr(tracer, "get_exporter", lambda: FakeExporter())
    configure(sample_rate=1.0)
    with tracer.trace("root"):
        with tracer.span("child"):
            pass
    child, root = emitted
    assert child["trace_id"] == root["trace_id"] != ""
    assert child["parent_span_id"] == root["span_id"]
