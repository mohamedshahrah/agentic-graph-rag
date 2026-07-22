# llmlens

**A self-hostable LLM observability platform** — a mini Langfuse/LangSmith you run yourself.
Instrument any LLM app to capture every prompt, response, latency, token count, and tool call
as a **trace**, then explore traces, cost-per-user, latency percentiles, and error rates in a
dashboard — with alerting when error rate or cost spikes.

Built on a production-grade stack: an **OpenTelemetry-aligned** data model, **ClickHouse** for
span analytics, **Postgres** for configuration, **Redis Streams** for the ingest queue, a
**React** dashboard, and a **Caddy** TLS proxy — all up with one command.

This README doubles as a **teaching reference**: beyond "how to run it," it explains *why*
each piece exists and what every folder and file does, so you can use the codebase to learn
how observability systems are built.

---

## 1. The problem this solves

Building an LLM app is half the job; **running** it is the other half. In production you must
be able to answer:

- *What did this request cost?* (per user, per model, per day)
- *Why was it slow?* (was it the LLM call, the retrieval step, a tool?)
- *What's our error rate right now?* (and was it a spike or the normal baseline?)
- *Which user or feature is burning the budget?*

Plain logs can't answer these. Percentiles and cost-per-user over millions of calls need
**traces** (structured, tree-shaped records of each request) stored in an **analytics
database** built for aggregation. That combination — instrumentation + trace store + query
layer + alerting — is what llmlens is.

## 2. How it works — the life of a request

```
 your app ──SDK / OTLP──▶ Ingest API ──▶ Redis ──▶ Worker ──▶ ClickHouse ──▶ Dashboard
   @observe / instrument()   (auth)      (queue)   (cost)     (+ matviews)     (React)
                                                                   │
                                                         Alert engine ──▶ webhook / Slack
```

1. **Your app** runs with the SDK attached. A request becomes a *trace*: a root span plus
   child spans for each LLM call, tool call, or retrieval step. Spans record timing, tokens,
   model, status, and (optionally) prompt/response text.
2. The SDK's **background exporter thread** batches finished spans and POSTs them to the
   **ingest API**. If the server is down or slow, spans are dropped — never your requests.
3. The API **authenticates** the project key, normalizes events, and pushes them onto a
   **Redis Stream**. It returns immediately; nothing waits on the database.
4. The **worker** consumes the stream in batches, **prices** each generation from its token
   counts (`pricing/`), and bulk-inserts rows into **ClickHouse**.
5. ClickHouse **materialized views** pre-aggregate per-minute metrics (count, errors, cost,
   latency t-digests) so dashboard queries read a tiny table instead of scanning raw spans.
6. The worker's **alert engine** evaluates rules (error rate, cost spike, p95 latency,
   volume) every minute against those metrics and notifies a webhook/Slack channel, with a
   Redis-backed cooldown so you aren't spammed.

## 3. Quickstart

### Bring up the stack

```bash
git clone <repo> llmlens && cd llmlens
cp .env.example .env          # change LLMLENS_ADMIN_KEY (and Postgres password)
docker compose up -d --build
```

- **Dashboard** — http://localhost:5173
- **API docs (Swagger)** — http://localhost:8000/docs
- Behind the Caddy proxy, everything is also on **http://localhost** (`:443` with TLS — see §10)

### Send traffic and watch it

Auth is on by default, so mint a project key first (or set `LLMLENS_PROFILE=local` in `.env`
to run auth-less locally):

```bash
docker compose exec api llmlens-server create-project "demo"   # prints sk_...
export LLMLENS_API_KEY=sk_...                                  # the key printed above

pip install -e ./sdk
python examples/generate_traffic.py            # steady traffic
python examples/generate_traffic.py --spike    # a cost + error spike (trips alerts)
```

Enter the same `project_id` (printed by `create-project`) and your admin key in the
dashboard header.

### Instrument a real app

```python
import llmlens
llmlens.configure(api_key="sk_...", url="http://localhost:8000")
llmlens.instrument("openai", "anthropic", "langchain")   # auto-trace provider calls

with llmlens.trace("handle_request", user_id="u42"):     # optional manual root
    ...
```

Already on OpenTelemetry? Point your OTLP/HTTP exporter at `/v1/traces` — no SDK needed.
Full SDK guide: [`docs/SDK.md`](docs/SDK.md). Instrumenting the agentic-graph-rag project:
[`examples/instrument_project1.md`](examples/instrument_project1.md).

## 4. Design decisions — the "why" behind the architecture

These six decisions shape everything in the repo. Understanding them is understanding the
system.

**Why three datastores instead of one?** Each store does the one thing it's best at.
*ClickHouse* (columnar OLAP) makes `SUM(cost) GROUP BY user` over millions of spans take
milliseconds, but it's bad at small transactional updates. *Postgres* (OLTP) holds the small,
relational, frequently-updated things: projects, hashed API keys, pricing, alert rules.
*Redis* is the glue: a durable queue plus tiny shared state (alert cooldowns). Using one
database for all three roles is how observability stacks fall over.

**Why a queue between the API and the database?** Decoupling. The API can accept a burst of
10k spans instantly (Redis `XADD` is ~O(1)) while the worker drains at its own pace and
writes in large batches — which is exactly how ClickHouse wants to be written to (few big
inserts, not many small ones). If the worker or ClickHouse dies, events wait safely in the
stream; consumer groups + acks give at-least-once delivery, and `XAUTOCLAIM` recovers
batches a crashed worker read but never acknowledged.

**Why materialized views?** Dashboards ask the same aggregate questions over and over.
`metrics_by_minute` is an `AggregatingMergeTree` fed by a materialized view on `spans`: at
insert time ClickHouse maintains per-minute sums (requests, errors, cost, tokens) and a
**t-digest sketch** of latencies. Reading a day of metrics touches ~1,440 rows instead of
millions, and p50/p95/p99 come from merging sketches — the trick that turns multi-second
dashboard queries into milliseconds.

**Why must the SDK never block or crash the host app?** An observability tool that takes
down the app it observes is worse than useless. So the SDK: keeps a **bounded** in-memory
queue (drops on overflow rather than growing), exports from a **daemon thread** (never on
your request path), swallows every network error (retrying 5xx a few times), and logs *one*
warning if the server rejects events with a 4xx — silence there would mean "empty dashboard,
no clue why." Head **sampling** decides at the trace root and propagates to every child span,
so a sampled-out trace disappears completely instead of leaking orphan children.

**Why OpenTelemetry semantic conventions?** Interoperability. Spans carry the standard
`gen_ai.*` attribute names (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, …), and the
server accepts standard **OTLP/HTTP** exports. Any OTel-instrumented app can point its
exporter at llmlens with zero SDK adoption — and llmlens data stays meaningful to the wider
ecosystem.

**Why hash API keys, and why compute cost server-side?** Keys are shown once and stored only
as SHA-256 hashes — a database leak leaks no credentials. Cost is computed in the worker
(tokens × price table) rather than trusted from clients, so pricing updates apply uniformly
and apps can't misreport spend.

## 5. Repository map — the teaching reference

```
llmlens/
├── docker-compose.yml      # the whole stack: 7 services, health-gated startup
├── Makefile                # one-liners: up, test, test-e2e, lint, generate
├── .env / .env.example     # secrets + connection strings (env layer of config)
├── configs/                # YAML config layer: default.yaml < <profile>.yaml < env
├── docker/                 # Dockerfile.api (api+worker image) + Caddyfile (proxy)
├── sdk/                    # pip-installable client library  (Python ≥ 3.9)
├── server/                 # FastAPI ingest/query server + worker  (Python ≥ 3.11)
├── dashboard/              # React + Vite + Tailwind UI, served by nginx in Docker
├── tests/                  # unit/ (pure logic) + integration/ (against live stack)
├── examples/               # synthetic traffic generator + real-app guide
└── docs/                   # ARCHITECTURE, DATA-MODEL, SDK deep dives
```

### 5.1 Root — configuration & orchestration

| File | What it does — and why |
|---|---|
| `docker-compose.yml` | Declares all 7 services (clickhouse, postgres, redis, api, worker, dashboard, proxy). Teaches three patterns: **healthcheck-gated startup** (`depends_on: condition: service_healthy` so the API only starts once databases answer), **restart policies** (`unless-stopped` — crashed ≠ dead forever), and **resource caps** per container (a runaway ClickHouse can't eat the host). The api/worker share one image; only the `command` differs. |
| `Makefile` | Developer ergonomics: `make up`, `make test`, `make test-e2e`, `make lint`. A Makefile is the README you can execute. |
| `configs/default.yaml` | Shared behavioral config (queue names, batch sizes, CORS, rate limit, alert interval). Deliberately **contains no secrets** — those live in the environment. |
| `configs/local.yaml` | A profile overlay: turns auth off for local hacking. Select with `LLMLENS_PROFILE=local`. Layered config (defaults < profile < env) is the standard pattern for "same code, many environments." |
| `.env.example` | Documents every environment variable with its default. Copy to `.env` (which is gitignored — secrets never enter history). |
| `pytest.ini` | Makes `server/src` and `sdk/src` importable in tests and registers the `integration` marker so `make test` can exclude tests that need live databases. |
| `.gitattributes` | Forces LF line endings — files here get mounted into Linux containers, where CRLF breaks things. |
| `.github/workflows/ci.yml` | CI: install, ruff lint, mypy (advisory), unit tests on every push/PR. |

### 5.2 `sdk/` — the client library (`import llmlens`)

The SDK has **one dependency** (`httpx`) because every dependency you add is a dependency you
force on every app that instruments with you. Provider libraries are imported lazily.

| File | What it does — and why |
|---|---|
| `src/llmlens/config.py` | Env-first config (`LLMLENS_URL`, `LLMLENS_API_KEY`, `LLMLENS_SAMPLE_RATE`, …) with a `configure()` override. Parsing is defensive: a malformed env var falls back to defaults, because an SDK must never crash a host app at import time. |
| `src/llmlens/ids.py` | 128-bit trace ids / 64-bit span ids as hex — the exact widths OpenTelemetry uses, so ids stay compatible across systems. |
| `src/llmlens/tracer.py` | The core. `SpanRecord` (the mutable handle you enrich with `.usage()`, `.input()`, `.error()`), the `trace()`/`span()` context managers, the `@observe` decorator, and low-level `start()/finish()` for callback-style integrations. **Teaching highlight:** `contextvars` carry the current trace/span/sampling decision, which is how nesting works implicitly across sync *and* async code without passing objects around. Head sampling is decided once at the root and a `sampled=False` marker propagates so children never leak as orphan traces. |
| `src/llmlens/exporter.py` | The background pipeline: bounded `queue.Queue` → daemon thread → batched `POST /api/v1/ingest` → 3 retries on 5xx → drop. Embodies the SDK's prime directive (never block/crash the app) and warns once on 4xx so misconfiguration is discoverable. |
| `src/llmlens/integrations/openai.py`, `anthropic.py` | Auto-instrumentation via **monkeypatching**: wrap `Completions.create` / `Messages.create` in a `span(kind="generation")`, harvest model/tokens/output from the response. Idempotent (a `_llmlens` flag prevents double-wrapping) and import-safe (returns `False` if the library isn't installed). |
| `src/llmlens/integrations/langchain.py` | A `BaseCallbackHandler` mapping LangChain run events (`on_chat_model_start`, `on_tool_start`, …) onto spans. LangChain gives you `run_id`/`parent_run_id`, and a dict of run_id → SpanRecord rebuilds the tree — the callback pattern used by every LangChain tracing tool. |
| `src/llmlens/integrations/__init__.py` | `instrument("openai", "anthropic", "langchain")` dispatcher + `callback_handler()` for manual attachment. |

### 5.3 `server/` — the platform (`llmlens_server`)

#### `config/` — typed, layered configuration

| File | What it does — and why |
|---|---|
| `settings.py` | Two pydantic models: `Settings` mirrors the YAML (behavior), `Secrets` reads env vars (connections/keys). Splitting them keeps "what the app does" separate from "where it connects," which is what lets configs be committed while secrets are not. |
| `loader.py` | Merges `default.yaml < <profile>.yaml`, validates into `Settings`. Resolves the config directory in order: `$LLMLENS_CONFIG_DIR` → `./configs` (how Docker finds it) → repo-relative (how editable installs find it). Path resolution that works both installed and from-source is a classic packaging gotcha. |

#### `core/` — shared vocabulary

| File | What it does — and why |
|---|---|
| `types.py` | The **canonical `Span` dataclass** — the internal contract every ingest path normalizes into and the writer persists. `SpanKind` (trace / generation / span / tool / event) is the taxonomy the whole UI is built on. One canonical type means N sources × 1 format instead of N × M. |
| `semconv.py` | The OTel `gen_ai.*` attribute names as constants — one place to keep the vocabulary honest between the OTLP receiver and the SDK. |
| `keys.py` | `sk_...` key generation (`secrets.token_urlsafe`) + SHA-256 hashing. Keys are shown once; only hashes are stored. |
| `errors.py` | A small exception taxonomy (`ConfigError`, `StorageError`, `IngestError`, `AuthError`) so callers can catch *deliberate* failures distinctly from bugs. |
| `logging.py` | `structlog` setup — structured key-value logs (`log.warning("bad_event", error=...)`) that stay grep-able and machine-parsable. |

#### `ingest/` — getting data in

| File | What it does — and why |
|---|---|
| `native.py` | Validates SDK batches (required ids/timestamps) and stamps the authenticated `project_id` **server-side** — clients must never choose which project they write to. |
| `otlp.py` | Parses OTLP/HTTP JSON: unwraps `resourceSpans → scopeSpans → spans`, decodes OTel's typed `AnyValue`s, maps `gen_ai.*` attributes to canonical fields, infers span kind, and keeps unknown attributes as metadata rather than dropping them. |
| `canonical.py` | The **queue wire format**: JSON-safe event dict ⇄ `Span`. `_parse_time` accepts ISO strings and epoch seconds/millis/micros/nanos (tiered by magnitude) — timestamp forgiveness is bought here so both parsers stay simple. |
| `producer.py` | `XADD`s events onto the Redis Stream through a pipeline (one round-trip per batch, not per event). |

#### `storage/` — the two databases

| File | What it does — and why |
|---|---|
| `clickhouse/schema.sql` | The wide, append-only `spans` table. **Teaching highlights:** `LowCardinality(String)` for enum-ish columns (dictionary encoding), `ORDER BY (project_id, toStartOfHour(start_time), …)` so time-ranged project queries skip data, a TTL for retention, and prompt/response text in a **separate** `span_content` table so bulky, PII-ish text never sits in the hot analytics path and can be dropped independently. |
| `clickhouse/matviews.sql` | The per-minute pre-aggregation: `SimpleAggregateFunction(sum, …)` columns merge by summing across parts; `AggregateFunction(quantilesTDigest, …)` stores latency *sketches* that merge losslessly — how you get percentiles without keeping raw values. |
| `clickhouse/client.py` | Connection factory + idempotent schema apply (statement-by-statement, comment-aware) + a `query()` helper that returns dict rows and **tags naive datetimes as UTC** so JSON responses carry an offset (browsers parse offset-less timestamps as local time — a classic display bug). |
| `clickhouse/writer.py` | `Span` → tuple rows → batched insert with `async_insert`. Column list lives in one place next to the conversion. |
| `clickhouse/queries.py` | Every dashboard read: trace list (grouped per trace), waterfall spans, overview, timeseries, cost by user/model, top errors. Uses ClickHouse **server-side bind parameters** (`{name:Type}`) — the SQL-injection-safe form. Guards `NaN` from empty-window quantiles (JSON encoders reject NaN). Comment in `list_traces` documents a real ClickHouse gotcha: SELECT aliases substitute into WHERE, so naming an aggregate after a column breaks the query. |
| `postgres/schema.sql` | The config store: `projects`, `api_keys` (hashes only), `model_pricing` (versioned by `effective_from`), `notification_channels`, `alert_rules`, `alert_events`. Foreign keys with `ON DELETE CASCADE` keep cleanup automatic. |
| `postgres/client.py` | psycopg3 connections (dict rows, autocommit) + schema apply. |
| `postgres/repos.py` | All SQL behind plain functions (`create_project`, `resolve_project_by_key`, `set_rule_enabled`, …). The **repository pattern**: routers never write SQL, and `ON CONFLICT DO NOTHING/UPDATE` makes operations idempotent. |
| `storage/__init__.py` | `setup_storage()` — applies both schemas and seeds pricing; safe to run repeatedly. |

#### `pricing/` — token cost

| File | What it does — and why |
|---|---|
| `seed.py` | Starter price table (USD per 1K tokens) per (provider, model). Approximate by design — the *mechanism* is the point; live prices belong in the `model_pricing` table. |
| `calculator.py` | Lookup with graceful degradation: exact match → longest **prefix** match (so `gpt-4o-2024-08-06` resolves to `gpt-4o` — providers version models with date suffixes) → provider-wide default (ollama → free) → `None` (unknown ≠ $0; don't fake data). |

#### `worker/` — the consumer process

| File | What it does — and why |
|---|---|
| `run.py` | One deliberately boring loop: consume → (every 60s) reclaim stale batches → (every 60s) evaluate alerts → (every 5m) refresh pricing. Blocks at startup until storage is ready (a queue consumer with no HTTP surface should retry, not crash-loop). Scales horizontally: replicas join the same consumer group and Redis shards the stream between them. |
| `consumer.py` | Redis Streams mechanics: `XREADGROUP` batches, per-event decode + cost enrichment, batch write, `XACK`. A poison event is logged and acked (never wedge the queue on one bad message); an unacked batch from a dead consumer is recovered via `XAUTOCLAIM` — the at-least-once contract. |
| `alerts.py` | Evaluates enabled rules and fires notifications. The cooldown is a Redis `SET NX EX` — an **atomic** "only one firing per window" that stays correct even with multiple workers. |

#### `alerting/` — rule logic (kept separate from the worker so it's testable)

| File | What it does — and why |
|---|---|
| `rules.py` | The four rule types (`error_rate`, `cost_spike`, `latency_p95`, `volume`) + validation. |
| `evaluators.py` | Turns a rule into a number by querying the pre-aggregated metrics over the rule's window, and compares against the threshold. Alerts read the same fast tables the dashboard does. |
| `notifiers.py` | Webhook/Slack/log delivery. Wrapped in try/except: a dead webhook must never break the alert loop, so failures fall back to logging. |

#### `query/` — read models

| File | What it does — and why |
|---|---|
| `traces.py` | Assembles the **waterfall**: fetches a trace's spans + content, then builds the parent→children tree in one O(n) pass with a span_id map. Orphaned spans become roots instead of disappearing — ingestion is at-least-once, so reads must tolerate gaps. |
| `metrics.py` | Thin pass-throughs to the ClickHouse metric queries — kept as a layer so routers depend on read-model functions, not on storage details. |

#### `api/` — the HTTP surface

| File | What it does — and why |
|---|---|
| `app.py` | The **application factory** (`create_app()`): loads config, wires CORS + rate limiting (slowapi, keyed by API key or client IP), mounts routers, and uses a **lifespan** hook to set up storage. Startup is resilient: if a database is down, the API still boots and retries on first use rather than serving 500s forever. |
| `deps.py` | FastAPI **dependency injection**: shared singletons (ClickHouse client, Redis, settings), per-request Postgres connections, and the two auth gates — `ingest_project` (resolves the *project* from a secret key hash; 401 otherwise) and `require_admin` (constant-time compare of `X-Admin-Key`; gates management + dashboard reads). Auth as a dependency = one implementation, declared per-route. |
| `schemas.py` | Pydantic request/response models for inputs and small outputs. Trace/metric reads return the query layer's dicts directly — modeling those twice buys nothing. |
| `routers/ingest.py` | `POST /api/v1/ingest` — authenticate, normalize, enqueue, return. No database on the hot path. |
| `routers/otlp.py` | `POST /v1/traces` — the standard OTLP/HTTP endpoint (OTel exporters expect this exact path). Rejects malformed JSON with 400 and keeps the sync Redis call off the event loop. |
| `routers/traces.py`, `routers/metrics.py` | Dashboard reads, all scoped by `project_id` + a `?hours=` window and admin-gated. |
| `routers/projects.py` | Create/list projects; creating mints the secret key (returned exactly once). |
| `routers/alerts.py` | Channels + rules CRUD: create, list, `PATCH` (pause/resume), `DELETE`, plus fired-event history. |
| `routers/health.py` | `/health` (liveness: process is up) vs `/ready` (readiness: each backend individually probed). Two endpoints because orchestrators treat those questions differently. |
| `__main__.py` | The `llmlens-server` CLI (typer): `init`, `create-project`, `worker`, `serve`. |

### 5.4 `dashboard/` — the UI

Small on purpose: React + Vite + Tailwind and **zero chart libraries** — the charts are
~80 lines of SVG. When a dashboard only needs lines and bars, a charting dependency costs
more than it gives.

| File | What it does — and why |
|---|---|
| `src/lib/api.ts` | The API client: base `/api` (same-origin — nginx/vite proxy handles routing, so no CORS in production), `X-Admin-Key` header, and `project_id` + `hours` stamped onto every read. State persists in `localStorage`. |
| `src/App.tsx`, `components/Layout.tsx` | View switching + the header controls (project, time window, admin key, refresh). Plain `useState` — no router or global store needed at this size. |
| `src/pages/Overview.tsx` | Stat tiles (requests, error rate, cost, p50/p95/p99) + time-series charts, all reading the pre-aggregated metrics endpoints. |
| `src/pages/Traces.tsx` | Trace list → click → **waterfall** detail. |
| `src/components/Waterfall.tsx` | Flattens the span tree depth-first and draws each span as a positioned bar on the trace's timeline; expanding a span reveals status, tokens, cost, and recorded prompt/response content. The signature visualization of tracing tools. |
| `src/pages/Cost.tsx`, `Errors.tsx` | Cost-by-user / cost-by-model bar lists; top error messages with counts and last-seen. |
| `src/pages/Alerts.tsx` | Create rules (optionally with a webhook channel), pause/resume, delete, and the recent-firings feed. |
| `src/components/Chart.tsx`, `Stat.tsx` | The dependency-free `LineChart`/`BarList` and card primitives. |
| `nginx.conf`, `Dockerfile` | Multi-stage build (node → static files → nginx). nginx serves the SPA and proxies `/api/*` and `/v1/*` to the api container — the same-origin trick. `vite.config.ts` does the equivalent proxying in dev. |

### 5.5 `docker/`, `tests/`, `examples/`, `docs/`

| Path | What it does — and why |
|---|---|
| `docker/Dockerfile.api` | One image for api **and** worker (same code, different `command`) — half the builds, guaranteed version consistency. Sets `LLMLENS_CONFIG_DIR=/app/configs` because pip-installed packages can't find repo-relative paths. |
| `docker/Caddyfile` | Reverse proxy: `/api/*` and `/v1/*` → api, everything else → dashboard. Set `SITE_ADDRESS` to a domain and Caddy provisions Let's Encrypt TLS automatically. |
| `tests/unit/` | Pure-logic tests (no databases): canonical parsing incl. every epoch-timestamp tier, OTLP mapping, pricing fallbacks, alert threshold logic, SDK sampling/emission, and the SQL statement splitter — each file guards a bug class that actually occurred. |
| `tests/integration/test_e2e.py` | The whole pipeline against a **running** stack (`make test-e2e`): mints a throwaway project, ingests native + OTLP traffic, then asserts traces, waterfall, metrics, costs, errors, the alert rule lifecycle, auth failures, and proxy routing. stdlib-only HTTP so it runs anywhere pytest does. |
| `examples/generate_traffic.py` | Synthetic-but-realistic traffic (varied models/users/latencies/errors; `--spike` mode to trip alerts) so you can see the dashboard working without a real app. |
| `docs/` | Deep dives: [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) (system design), [`DATA-MODEL.md`](docs/DATA-MODEL.md) (span schema & semantics), [`SDK.md`](docs/SDK.md) (full client guide). |

## 6. The data model in one minute

A **trace** is one logical request; a **span** is one step inside it. Spans form a tree via
`parent_span_id` and carry: identity (`project_id`, `trace_id`, `span_id`), a `kind`
(`trace` root, `generation` LLM call, `tool`, `span` generic, `event`), timing
(`start_time`, `end_time`, `duration_ms`), LLM facts (`provider`, `model`, token counts,
`cost_usd`), outcome (`status`, `status_message`), attribution (`user_id`, `session_id`,
`tags`), and free-form `metadata`. Prompt/response text lives apart in `span_content`,
recorded only when `ingest.record_content` is true. Details: [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md).

## 7. HTTP API reference

| Method & path | Purpose | Auth |
|---|---|---|
| `POST /api/v1/ingest` | Native SDK event batches | project key (`Authorization: Bearer` or `X-Api-Key`) |
| `POST /v1/traces` | OTLP/HTTP trace export | project key |
| `GET /api/traces` | Trace list (`?project_id=&hours=&user_id=&status=&limit=&offset=`) | admin key (`X-Admin-Key`) |
| `GET /api/traces/{trace_id}` | One trace as a span tree + content | admin key |
| `GET /api/metrics/overview` | Requests, errors, cost, tokens, p50/p95/p99 | admin key |
| `GET /api/metrics/timeseries` | Per-minute series for charts | admin key |
| `GET /api/metrics/cost/users` · `/cost/models` | Cost breakdowns | admin key |
| `GET /api/metrics/errors` | Top error messages | admin key |
| `POST /api/projects` · `GET /api/projects` | Create (mints key, shown once) / list | admin key |
| `POST /api/alerts/channels` · `GET` · `DELETE /{id}` | Notification channels | admin key |
| `POST /api/alerts/rules` · `GET` · `PATCH /{id}` · `DELETE /{id}` | Alert rules (PATCH toggles `enabled`) | admin key |
| `GET /api/alerts/events` | Recent firings | admin key |
| `GET /health` · `GET /ready` | Liveness / per-backend readiness | none |

Interactive docs at `/docs`. Ingest is rate-limited (default `600/minute` per key/IP).

## 8. Configuration reference

Layering: `configs/default.yaml` < `configs/<LLMLENS_PROFILE>.yaml` < environment.

**Server env** (see `.env.example`): `LLMLENS_PROFILE`, `LLMLENS_CLICKHOUSE_HOST/PORT/USER/PASSWORD/DB`,
`LLMLENS_POSTGRES_DSN`, `LLMLENS_REDIS_URL`, `LLMLENS_ADMIN_KEY`, `LLMLENS_CONFIG_DIR`,
`SITE_ADDRESS`, plus per-container resource caps.

**SDK env**: `LLMLENS_URL`, `LLMLENS_API_KEY`, `LLMLENS_ENABLED`, `LLMLENS_RECORD_CONTENT`,
`LLMLENS_SAMPLE_RATE` (0..1 head sampling).

**Behavior** (`configs/*.yaml`): retention days, queue/batch sizes, `record_content`
(privacy switch for prompt/response storage), alert interval & cooldown, CORS, rate limit,
`auth.enabled`.

## 9. Development & testing

```bash
make install     # server + sdk, editable, with dev extras
make test        # unit tests (no services needed)
make test-e2e    # integration tests (docker compose up -d first)
make lint        # ruff + mypy
make serve       # run the API bare against local services
make worker      # run the worker bare
```

Server targets Python ≥ 3.11; the SDK stays ≥ 3.9 (it must install anywhere your apps run).

## 10. Production notes

**API-key auth** (project keys for ingest, admin key for reads/management; disable with the
`local` profile), **TLS** via Caddy (set `SITE_ADDRESS` to your domain for automatic
Let's Encrypt), per-container **resource caps**, rate limiting, health-gated startup, and
`restart: unless-stopped` everywhere. Before real exposure: change `LLMLENS_ADMIN_KEY` and
the Postgres password, and bind the ClickHouse/Postgres/Redis port mappings to
`127.0.0.1` (or remove them) — the containers only need the internal network. Set
`ingest.record_content: false` for strict prompt privacy.

## License

MIT — see [LICENSE](LICENSE).
