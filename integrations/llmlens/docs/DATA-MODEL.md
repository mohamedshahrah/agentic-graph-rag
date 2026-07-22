# Data model

## ClickHouse

### `spans` (append-only, one row per observation)

| column | notes |
|---|---|
| `project_id` | tenant scope |
| `trace_id` / `span_id` / `parent_span_id` | tree structure (resolved at query time) |
| `name`, `kind` | `trace` \| `generation` \| `span` \| `tool` \| `event` |
| `provider`, `model` | LowCardinality |
| `start_time`, `end_time`, `duration_ms` | timing |
| `status`, `status_message` | `ok` \| `error` |
| `input_tokens`, `output_tokens`, `total_tokens` | usage |
| `cost_usd` | computed at ingest from token usage × pricing |
| `user_id`, `session_id`, `tags`, `metadata` | attribution / filtering |

`ENGINE = MergeTree ORDER BY (project_id, toStartOfHour(start_time), trace_id, span_id)`,
with a `TTL` for retention (`app.retention_days`).

### `span_content` (opt-in, separate)

Prompt/response bodies (`role`, `content`) live here, not in the indexed span row — so they
can be dropped/redacted for PII and don't bloat the hot table. Written only when
`ingest.record_content` is true. (This mirrors the OTel guidance that content belongs in
events, not indexed attributes.)

### `metrics_by_minute` (materialized view)

`AggregatingMergeTree` populated by an MV off `spans`, per `(project_id, minute, model)`:
additive counters as `SimpleAggregateFunction(sum, …)` and latency as
`AggregateFunction(quantilesTDigest(0.5, 0.95, 0.99), Float64)`. Dashboards query this tiny
table (`quantilesTDigestMerge`, `sum`) instead of scanning raw spans.

## Postgres

`projects`, `api_keys` (hashed; `secret`/`public`), `model_pricing` (versioned by
`effective_from`), `notification_channels`, `alert_rules`, `alert_events`.

## Canonical event

Between the SDK/OTLP and the worker, everything is a JSON **canonical event** — a flat,
JSON-safe form of a span (see `ingest/canonical.py`). The native SDK emits this shape
directly; the OTLP receiver maps `gen_ai.*` spans into it. The worker turns it back into a
`Span` and adds cost.
