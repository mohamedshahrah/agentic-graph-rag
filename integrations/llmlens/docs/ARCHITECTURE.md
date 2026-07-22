# Architecture

This explains how llmlens is put together and why. Read it once; the code follows.

## The problem

Once an LLM app is in production you need to answer boring-but-critical questions:
*What did this request actually cost? Why was it slow? What's our error rate? Which
user is burning the budget?* Plain logs can't do percentiles or cost-per-user over
millions of calls. You need **traces** (a request as a tree of nested spans) plus an
**analytics database**.

## The trace model

A **trace** is one end-to-end operation (an agent run, a chat request). It contains
**spans** (a.k.a. observations):

- `generation` — an LLM call (model, tokens, cost, latency, prompt/response)
- `tool` — a tool / function call
- `span` — a generic step (a chain, a retrieval)
- `trace` — the root

Spans nest via `parent_span_id`, forming the waterfall you see in the UI. Attribute
names follow the **OpenTelemetry GenAI semantic conventions** (`gen_ai.request.model`,
`gen_ai.usage.input_tokens`, …), which is what makes the OTLP endpoint interoperable
with the whole OpenTelemetry ecosystem.

## The pipeline

```
 apps ──native SDK / OTLP──▶ Ingest API ──▶ Redis stream ──▶ Worker ──▶ ClickHouse
                              (auth, validate)                (cost enrich)   │
                                                                              ├─ spans (raw)
 Dashboard ◀── Query API ◀── aggregation queries ◀── materialized views ◀────┘
 Alert engine (in worker) ── evaluates rules vs ClickHouse ──▶ webhook / Slack / log
```

1. **Ingest.** Apps send batches to `/api/v1/ingest` (native) or `/v1/traces` (OTLP).
   The API authenticates the project by its secret key, normalizes events to one
   canonical shape, and pushes them onto a **Redis stream** — returning immediately so
   the caller is never blocked.
2. **Worker.** A consumer reads the stream, computes **cost** from token usage and a
   versioned pricing table, and batch-inserts into ClickHouse (`async_insert`). Parent/
   child links are resolved at *query* time, so ingestion stays fully asynchronous.
3. **Storage.** ClickHouse holds the append-only `spans` (and opt-in `span_content`).
   A **materialized view** (`metrics_by_minute`) pre-aggregates count/errors/cost/tokens
   and a t-digest of latency per minute — so cost, error-rate, and p50/p95/p99 dashboards
   read a tiny pre-computed table in milliseconds instead of scanning raw spans. Postgres
   holds config (projects, hashed keys, pricing, alert rules).
4. **Query + dashboard.** The query API turns those tables into the read models the React
   dashboard renders (trace list, waterfall, cost-per-user, latency percentiles, errors).
5. **Alerting.** The same worker, on an interval, evaluates alert rules against ClickHouse,
   respects a per-rule cooldown (Redis), and fires webhook/Slack/log notifications.

## Why these choices

- **ClickHouse for spans** — LLM logs are append-only and write-heavy; ClickHouse's
  columnar engine reads only the columns a query needs (cost, model) and does percentiles
  cheaply. This is the same stack Langfuse landed on.
- **Postgres for config** — projects, keys, pricing, and alert rules want transactions and
  constraints, which ClickHouse isn't for.
- **Redis stream between API and worker** — decouples the fast, non-blocking ingest path
  from the slower write path, and lets you scale workers horizontally (same consumer group).
- **Native SDK *and* OTLP** — the SDK gives great LLM-specific DX (auto-instrument
  OpenAI/Anthropic/LangChain); OTLP keeps us open to any OpenTelemetry-instrumented app.

## Deployment

`docker compose up` starts ClickHouse, Postgres, Redis, the API, the worker, the React
dashboard, and a **Caddy TLS reverse proxy** (the public entrypoint on 80/443, routing
`/api/*` and `/v1/*` to the API and everything else to the dashboard). Every container has
RAM/CPU caps from `.env`. Auth (project keys for ingest, an admin key for the dashboard) is
on by default and can be turned off for local dev.
