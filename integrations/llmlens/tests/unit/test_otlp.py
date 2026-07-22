from llmlens_server.ingest.otlp import parse_otlp


def test_parse_otlp_genai_span():
    payload = {
        "resourceSpans": [{
            "scopeSpans": [{
                "spans": [{
                    "traceId": "t1", "spanId": "s1", "name": "chat",
                    "startTimeUnixNano": "1700000000000000000",
                    "endTimeUnixNano": "1700000001000000000",
                    "attributes": [
                        {"key": "gen_ai.system", "value": {"stringValue": "openai"}},
                        {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
                        {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "100"}},
                        {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "20"}},
                        {"key": "custom.tag", "value": {"stringValue": "x"}},
                    ],
                    "status": {"code": 1},
                }]
            }]
        }]
    }
    events = parse_otlp(payload, "proj")
    assert len(events) == 1
    e = events[0]
    assert e["project_id"] == "proj"
    assert e["provider"] == "openai"
    assert e["model"] == "gpt-4o"
    assert e["input_tokens"] == 100 and e["output_tokens"] == 20
    assert e["kind"] == "generation"
    assert e["metadata"].get("custom.tag") == "x"  # non-genai attrs -> metadata


def test_parse_otlp_error_status():
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "traceId": "t", "spanId": "s", "name": "x",
        "startTimeUnixNano": "1700000000000000000",
        "status": {"code": 2, "message": "boom"},
        "attributes": [],
    }]}]}]}
    e = parse_otlp(payload, "p")[0]
    assert e["status"] == "error" and e["status_message"] == "boom"
