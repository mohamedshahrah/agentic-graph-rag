"""End-to-end tests against a RUNNING llmlens stack (`docker compose up -d`).

Skipped by default (`make test`); run explicitly with:

    pytest -m integration            # or: make test-e2e

Each run creates its own throwaway project, so runs never see each other's
data. Configuration via env vars:

    LLMLENS_E2E_URL         API base        (default http://localhost:8000)
    LLMLENS_E2E_PROXY_URL   Caddy base      (default http://localhost)
    LLMLENS_E2E_ADMIN_KEY   admin key       (default change-me-admin)

Only stdlib is used, so the suite runs anywhere pytest is installed.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid

import pytest

pytestmark = pytest.mark.integration

BASE = os.getenv("LLMLENS_E2E_URL", "http://localhost:8000")
PROXY = os.getenv("LLMLENS_E2E_PROXY_URL", "http://localhost")
ADMIN = os.getenv("LLMLENS_E2E_ADMIN_KEY", "change-me-admin")


# -- tiny stdlib HTTP client ---------------------------------------------------
def _call(method, path, body=None, headers=None, base=BASE, timeout=15):
    """Returns (status, parsed_json_or_text). Never raises on HTTP errors."""
    data = body if isinstance(body, bytes) else (
        json.dumps(body).encode() if body is not None else None
    )
    req = urllib.request.Request(
        base + path, method=method, data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        try:
            detail = json.loads(detail)
        except ValueError:
            pass
        return exc.code, detail


def _admin(**extra):
    return {"X-Admin-Key": ADMIN, **extra}


def _bearer(key):
    return {"Authorization": f"Bearer {key}"}


def _wait_for(check, timeout=30.0, interval=1.0, what="condition"):
    deadline = time.time() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.time() > deadline:
            raise AssertionError(f"{what} not met within {timeout:.0f}s")
        time.sleep(interval)


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + "+00:00"


# -- fixtures -------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def stack():
    """Skip the whole module when the stack isn't up."""
    try:
        status, _ = _call("GET", "/health", timeout=3)
    except OSError:
        pytest.skip(f"llmlens API not reachable at {BASE} — run `docker compose up -d`")
    assert status == 200


@pytest.fixture(scope="session")
def project():
    """A fresh project + secret ingest key for this run."""
    status, created = _call(
        "POST", "/api/projects", {"name": f"e2e-{uuid.uuid4().hex[:8]}"}, _admin()
    )
    assert status == 200, created
    return created["id"], created["secret_key"]


@pytest.fixture(scope="session")
def auth_on(project):
    """True when ingest auth is enforced (default profile); False for local."""
    status, _ = _call("POST", "/api/v1/ingest", {"events": []},
                      _bearer("sk_definitely_wrong"))
    return status == 401


@pytest.fixture(scope="session")
def seeded(project):
    """Ingest a known workload and wait for the worker to persist it:
    - a 2-span trace (root with ISO times, generation with MILLISECOND epochs,
      1k+1k tokens on claude-sonnet-5 -> $0.018 at seed pricing)
    - a 1-span errored generation
    - one OTLP gen_ai span (gpt-4o-mini, cost-enriched by the worker)
    """
    project_id, key = project
    now = time.time()
    trace_ok, trace_err = uuid.uuid4().hex, uuid.uuid4().hex
    root_id, gen_id = uuid.uuid4().hex[:16], uuid.uuid4().hex[:16]

    events = [
        {"trace_id": trace_ok, "span_id": root_id, "name": "chat_request",
         "kind": "trace", "start_time": _iso(now - 2), "end_time": _iso(now),
         "user_id": "alice", "tags": ["e2e"]},
        {"trace_id": trace_ok, "span_id": gen_id, "parent_span_id": root_id,
         "name": "chat claude-sonnet-5", "kind": "generation",
         "provider": "anthropic", "model": "claude-sonnet-5",
         "start_time": int((now - 1.8) * 1000), "end_time": int(now * 1000),
         "input_tokens": 1000, "output_tokens": 1000, "user_id": "alice",
         "content": [{"role": "user", "content": "hello?"},
                     {"role": "output", "content": "hi!"}]},
        {"trace_id": trace_err, "span_id": uuid.uuid4().hex[:16],
         "name": "chat gpt-4o", "kind": "generation", "provider": "openai",
         "model": "gpt-4o", "start_time": _iso(now - 1), "end_time": _iso(now),
         "status": "error", "status_message": "RateLimitError: 429",
         "input_tokens": 50, "user_id": "bob"},
    ]
    status, resp = _call("POST", "/api/v1/ingest", {"events": events}, _bearer(key))
    assert status == 200 and resp["accepted"] == 3, resp

    otlp = {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "traceId": uuid.uuid4().hex, "spanId": uuid.uuid4().hex[:16],
        "name": "otel chat",
        "startTimeUnixNano": str(int((now - 1) * 1e9)),
        "endTimeUnixNano": str(int(now * 1e9)),
        "attributes": [
            {"key": "gen_ai.system", "value": {"stringValue": "openai"}},
            {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o-mini"}},
            {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "100"}},
            {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "20"}},
        ],
        "status": {"code": 1}}]}]}]}
    status, resp = _call("POST", "/v1/traces", otlp, _bearer(key))
    assert status == 200 and resp["accepted"] == 1, resp

    def ingested():
        _, r = _call("GET", f"/api/traces?project_id={project_id}&hours=1",
                     headers=_admin())
        traces = r.get("traces", []) if isinstance(r, dict) else []
        return traces if len(traces) >= 3 else None

    traces = _wait_for(ingested, what="worker to persist seeded traces")
    return {"project_id": project_id, "key": key,
            "trace_ok": trace_ok, "trace_err": trace_err, "traces": traces}


# -- health ----------------------------------------------------------------------
def test_ready_reports_all_backends():
    status, ready = _call("GET", "/ready")
    assert status == 200
    assert ready == {"ready": True, "clickhouse": True, "postgres": True, "redis": True}


# -- empty state (NaN regression) -------------------------------------------------
def test_overview_is_clean_on_empty_project():
    status, created = _call(
        "POST", "/api/projects", {"name": f"e2e-empty-{uuid.uuid4().hex[:8]}"}, _admin()
    )
    assert status == 200, created
    status, ov = _call(
        "GET", f"/api/metrics/overview?project_id={created['id']}", headers=_admin()
    )
    assert status == 200, ov  # NaN latencies used to 500 here
    assert ov["requests"] == 0 and ov["errors"] == 0
    assert ov["latency_p50"] == ov["latency_p95"] == ov["latency_p99"] == 0.0


# -- auth --------------------------------------------------------------------------
def test_ingest_rejects_bad_key(auth_on):
    if not auth_on:
        pytest.skip("auth disabled (local profile)")
    status, _ = _call("POST", "/api/v1/ingest", {"events": []}, _bearer("sk_wrong"))
    assert status == 401


def test_reads_require_admin_key(project, auth_on):
    if not auth_on:
        pytest.skip("auth disabled (local profile)")
    project_id, _ = project
    status, _ = _call(
        "GET", f"/api/metrics/overview?project_id={project_id}",
        headers={"X-Admin-Key": "nope"},
    )
    assert status == 403


# -- traces -------------------------------------------------------------------------
def test_traces_list_shape(seeded):
    ok = [t for t in seeded["traces"] if t["trace_id"] == seeded["trace_ok"]][0]
    err = [t for t in seeded["traces"] if t["trace_id"] == seeded["trace_err"]][0]

    assert ok["spans"] == 2 and not ok["has_error"] and ok["user_id"] == "alice"
    assert ok["tokens"] == 2000
    assert abs(ok["cost_usd"] - 0.018) < 1e-9  # 1k+1k on claude-sonnet-5
    assert ok["duration_ms"] > 0
    # regression: ClickHouse datetimes must be serialized WITH a UTC marker
    assert str(ok["start_time"]).endswith("Z") or "+00:00" in str(ok["start_time"])

    assert err["has_error"] and err["user_id"] == "bob"


def test_trace_waterfall_tree_and_content(seeded):
    status, detail = _call(
        "GET", f"/api/traces/{seeded['trace_ok']}?project_id={seeded['project_id']}",
        headers=_admin(),
    )
    assert status == 200
    assert detail["span_count"] == 2
    root = detail["spans"][0]
    assert root["name"] == "chat_request" and len(root["children"]) == 1
    gen = root["children"][0]
    # this span was ingested with MILLISECOND epochs (regression for _parse_time)
    assert gen["model"] == "claude-sonnet-5" and gen["kind"] == "generation"
    assert len(gen["content"]) == 2
    assert gen["end_ms"] > gen["start_ms"]


# -- metrics --------------------------------------------------------------------------
def test_metrics_overview_and_timeseries(seeded):
    pid = seeded["project_id"]
    status, ov = _call("GET", f"/api/metrics/overview?project_id={pid}&hours=1",
                       headers=_admin())
    assert status == 200
    assert ov["requests"] >= 2 and ov["errors"] >= 1
    assert 0.0 < ov["error_rate"] < 1.0
    assert ov["latency_p95"] > 0

    status, ts = _call("GET", f"/api/metrics/timeseries?project_id={pid}&hours=1",
                       headers=_admin())
    assert status == 200 and len(ts["points"]) >= 1
    assert sum(p["requests"] for p in ts["points"]) >= 2


def test_cost_breakdowns(seeded):
    pid = seeded["project_id"]
    _, users = _call("GET", f"/api/metrics/cost/users?project_id={pid}&hours=1",
                     headers=_admin())
    by_user = {u["user_id"]: u["cost_usd"] for u in users["users"]}
    assert abs(by_user["alice"] - 0.018) < 1e-9
    assert "bob" in by_user

    _, models = _call("GET", f"/api/metrics/cost/models?project_id={pid}&hours=1",
                      headers=_admin())
    names = {m["model"] for m in models["models"]}
    assert {"claude-sonnet-5", "gpt-4o", "gpt-4o-mini"} <= names


def test_top_errors(seeded):
    _, errors = _call(
        "GET", f"/api/metrics/errors?project_id={seeded['project_id']}&hours=1",
        headers=_admin(),
    )
    top = errors["errors"][0]
    assert "RateLimitError" in top["status_message"] and top["n"] >= 1


# -- OTLP ------------------------------------------------------------------------------
def test_otlp_span_ingested_and_cost_enriched(seeded):
    otel = [t for t in seeded["traces"] if t["name"] == "otel chat"]
    assert len(otel) == 1
    assert otel[0]["cost_usd"] > 0  # worker priced it from gpt-4o-mini seed pricing


def test_otlp_rejects_malformed_body(project):
    _, key = project
    status, _ = _call("POST", "/v1/traces", b"{not json", _bearer(key))
    assert status == 400
    status, _ = _call("POST", "/v1/traces", [1, 2, 3], _bearer(key))
    assert status == 400


# -- alert rule lifecycle (create -> toggle -> delete) ----------------------------------
def test_alert_rule_lifecycle(project):
    project_id, _ = project

    _, ch = _call("POST", "/api/alerts/channels",
                  {"project_id": project_id, "kind": "log", "target": ""}, _admin())
    channel_id = ch["id"]

    status, rule = _call("POST", "/api/alerts/rules", {
        "project_id": project_id, "name": "e2e lifecycle", "type": "volume",
        "threshold": 1e12, "window_seconds": 60, "cooldown_seconds": 900,
        "channel_id": channel_id,
    }, _admin())
    assert status == 200
    rule_id = rule["id"]

    _, listed = _call("GET", f"/api/alerts/rules?project_id={project_id}",
                      headers=_admin())
    mine = [r for r in listed["rules"] if r["id"] == rule_id]
    assert len(mine) == 1 and mine[0]["enabled"] is True

    status, r = _call("PATCH", f"/api/alerts/rules/{rule_id}", {"enabled": False},
                      _admin())
    assert status == 200 and r["enabled"] is False
    _, listed = _call("GET", f"/api/alerts/rules?project_id={project_id}",
                      headers=_admin())
    assert [x for x in listed["rules"] if x["id"] == rule_id][0]["enabled"] is False

    status, _ = _call("DELETE", f"/api/alerts/rules/{rule_id}", headers=_admin())
    assert status == 200
    _, listed = _call("GET", f"/api/alerts/rules?project_id={project_id}",
                      headers=_admin())
    assert not [x for x in listed["rules"] if x["id"] == rule_id]
    status, _ = _call("DELETE", f"/api/alerts/rules/{rule_id}", headers=_admin())
    assert status == 404

    status, _ = _call("DELETE", f"/api/alerts/channels/{channel_id}", headers=_admin())
    assert status == 200
    status, _ = _call("DELETE", f"/api/alerts/channels/{channel_id}", headers=_admin())
    assert status == 404


def test_bad_rule_type_rejected(project):
    project_id, _ = project
    status, _ = _call("POST", "/api/alerts/rules", {
        "project_id": project_id, "name": "bad", "type": "nonsense",
        "threshold": 1, "window_seconds": 60, "cooldown_seconds": 900,
        "channel_id": None,
    }, _admin())
    assert status == 422


# -- reverse proxy -----------------------------------------------------------------------
def test_proxy_routes_api_and_dashboard(seeded):
    try:
        status, ov = _call(
            "GET", f"/api/metrics/overview?project_id={seeded['project_id']}&hours=1",
            headers=_admin(), base=PROXY, timeout=5,
        )
    except OSError:
        pytest.skip(f"proxy not reachable at {PROXY}")
    assert status == 200 and ov["requests"] >= 2

    req = urllib.request.Request(PROXY + "/")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert "llmlens" in resp.read().decode()
