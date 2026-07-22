-- Pre-aggregated per-minute metrics so cost / error-rate / latency-percentile
-- dashboards read a tiny table instead of scanning raw spans. This is the trick
-- that turns multi-second dashboard queries into milliseconds.
--
-- Additive columns use SimpleAggregateFunction(sum, ...) so parts merge by
-- summing; latency uses a t-digest aggregate state for cheap p50/p95/p99.

CREATE TABLE IF NOT EXISTS metrics_by_minute
(
    project_id     String,
    minute         DateTime,
    model          LowCardinality(String),
    count          SimpleAggregateFunction(sum, UInt64),
    errors         SimpleAggregateFunction(sum, UInt64),
    cost_usd       SimpleAggregateFunction(sum, Float64),
    input_tokens   SimpleAggregateFunction(sum, UInt64),
    output_tokens  SimpleAggregateFunction(sum, UInt64),
    latency_state  AggregateFunction(quantilesTDigest(0.5, 0.95, 0.99), Float64)
)
ENGINE = AggregatingMergeTree
ORDER BY (project_id, minute, model);

CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_by_minute_mv TO metrics_by_minute AS
SELECT
    project_id,
    toStartOfMinute(start_time) AS minute,
    model,
    toUInt64(count())                          AS count,
    toUInt64(countIf(status = 'error'))        AS errors,
    sum(cost_usd)                              AS cost_usd,
    sum(toUInt64(input_tokens))                AS input_tokens,
    sum(toUInt64(output_tokens))               AS output_tokens,
    quantilesTDigestState(0.5, 0.95, 0.99)(duration_ms) AS latency_state
FROM spans
WHERE kind = 'generation'
GROUP BY project_id, minute, model;
