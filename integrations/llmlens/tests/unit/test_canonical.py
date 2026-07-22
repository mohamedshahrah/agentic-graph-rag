from llmlens_server.core.types import SpanKind, SpanStatus
from llmlens_server.ingest.canonical import event_to_span


def test_event_to_span_iso_times_and_tokens():
    span = event_to_span({
        "project_id": "p", "trace_id": "t", "span_id": "s", "name": "chat",
        "kind": "generation",
        "start_time": "2026-01-01T00:00:00+00:00",
        "end_time": "2026-01-01T00:00:01+00:00",
        "provider": "openai", "model": "gpt-4o", "status": "ok",
        "input_tokens": 10, "output_tokens": 5,
        "content": [{"role": "user", "content": "hi"}],
    })
    assert span.kind is SpanKind.GENERATION
    assert span.status is SpanStatus.OK
    assert span.total_tokens == 15
    assert abs(span.duration_ms - 1000) < 1
    assert span.content[0].role == "user"


def test_event_to_span_epoch_nanoseconds():
    span = event_to_span({
        "project_id": "p", "trace_id": "t", "span_id": "s", "name": "x",
        "kind": "span", "start_time": 1700000000000000000,
    })
    assert span.start_time.year == 2023


def test_event_to_span_epoch_milliseconds():
    span = event_to_span({
        "project_id": "p", "trace_id": "t", "span_id": "s", "name": "x",
        "kind": "span", "start_time": 1700000000000,
    })
    assert span.start_time.year == 2023


def test_event_to_span_epoch_microseconds():
    span = event_to_span({
        "project_id": "p", "trace_id": "t", "span_id": "s", "name": "x",
        "kind": "span", "start_time": 1700000000000000,
    })
    assert span.start_time.year == 2023


def test_unknown_kind_falls_back_to_span():
    span = event_to_span({
        "project_id": "p", "trace_id": "t", "span_id": "s", "name": "x",
        "kind": "banana", "start_time": "2026-01-01T00:00:00+00:00",
    })
    assert span.kind is SpanKind.SPAN
