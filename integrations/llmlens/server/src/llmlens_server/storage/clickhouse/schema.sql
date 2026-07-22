-- Core span table: append-only, one row per observation. Wide + columnar so
-- aggregations (SUM cost, COUNT errors) read only the columns they need.
-- {{RETENTION_DAYS}} is substituted at apply time from app.retention_days.

CREATE TABLE IF NOT EXISTS spans
(
    project_id      String,
    trace_id        String,
    span_id         String,
    parent_span_id  String,
    name            String,
    kind            LowCardinality(String),   -- trace | generation | span | tool | event
    provider        LowCardinality(String),
    model           LowCardinality(String),
    start_time      DateTime64(3),
    end_time        DateTime64(3),
    duration_ms     Float64,
    status          LowCardinality(String),   -- ok | error
    status_message  String,
    input_tokens    UInt32,
    output_tokens   UInt32,
    total_tokens    UInt32,
    cost_usd        Float64,
    user_id         String,
    session_id      String,
    tags            Array(String),
    metadata        String,                    -- JSON blob
    created_at      DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree
ORDER BY (project_id, toStartOfHour(start_time), trace_id, span_id)
TTL toDateTime(start_time) + INTERVAL {{RETENTION_DAYS}} DAY;

-- Prompt/response bodies live here, separate from the indexed span row.
-- Recorded only when ingest.record_content is true, and easy to drop for PII.
CREATE TABLE IF NOT EXISTS span_content
(
    project_id  String,
    trace_id    String,
    span_id     String,
    role        LowCardinality(String),        -- system | user | assistant | tool | input | output
    content     String,
    start_time  DateTime64(3),
    created_at  DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree
ORDER BY (project_id, trace_id, span_id)
TTL toDateTime(start_time) + INTERVAL {{RETENTION_DAYS}} DAY;
