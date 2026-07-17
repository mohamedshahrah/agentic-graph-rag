# Agentic Graph RAG

A retrieval system that answers questions over your documents by combining two
views of the data — a **vector index** for meaning and a **knowledge graph** for
relationships — and letting a **tool-using agent** decide how to search.

It runs fully **local** (Ollama + open models, no API keys) or on **cloud APIs**
(Claude, Gemini, OpenAI, Voyage). Run just the API with `uvicorn`, or the whole
stack — graph database, cache, API, and web UI — with a single `docker compose up`.

---

## Why this exists

Ordinary RAG embeds your documents and returns the chunks closest to your
question. That is great for *"find the passage about X"* and useless for
*"how are X and Y connected?"* — because closeness in meaning is not the same as
a relationship in the world.

So this project stores your data **twice**:

| Representation | Answers questions like | How |
| --- | --- | --- |
| Vector index | "find text about warehouse robots" | embed chunks, nearest-neighbor search |
| Knowledge graph | "who founded the company that makes the Pallet Pilot?" | entities + typed relationships |

An agent reads your question and chooses the right tool — vector search, graph
traversal, keyword lookup, or a combination. That is the "agentic" part: it is
not a fixed pipeline, it *reasons about how to retrieve*.

---

## How it works (the 60-second version)

**Ingesting a document:**

```
file ──▶ load ──▶ chunk ──▶ embed ──▶ vector index
   (PDF/Word/    │                        │
    HTML/CSV/    └──▶ LLM extracts ──▶ knowledge graph ──▶ resolve duplicates
    text/image)       entities +       (entities linked to      + summarize
                      relationships     the chunks that           communities
                                        mention them)
```

Images and scanned PDFs are read by a small vision model (**OCR**) before
chunking, so a picture of text becomes searchable text. A page goes to OCR when
its text layer is thinner than `ocr.min_text_chars` — not merely when it's empty,
because scans usually carry a page number or a scanner header, and "has some
text" is not "was read".

After a document lands, two enrichment passes run: **entity resolution** folds
duplicates the per-chunk extractor couldn't see were the same thing ("Acme" and
"Acme Robotics"), and **community summaries** cluster the graph and describe each
cluster, so the agent can answer whole-corpus questions, not just chunk lookups.

**Answering a question:**

```
question ──▶ agent ──▶ picks tool(s) ──▶ hybrid retrieval ──▶ rerank ──▶ answer + sources
                        │                 (vector ⊕ graph ⊕ keyword,
                        │                  run in parallel, fused with RRF)
                        └── graph_neighbors, expand_subgraph, compare,
                            get_entity, global_search, ...
```

The agent cites the exact chunks it used. Answers come in a **style** you choose
(concise / detailed / technical / ELI5), it can **compare** several subjects side
by side, and for corpus-wide questions ("what are the main themes?") it reads the
**community summaries** instead of hunting for a single passage. The three legs of
hybrid retrieval run concurrently, and the UI shows which tool the agent is
running while you wait.

For the full picture, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Quickstart

### Option A — one command (Docker)

Brings up Neo4j, Redis, the API, an **ingest worker**, the web UI, and a **TLS
reverse proxy** together. Per-container RAM/CPU caps are set in `.env`
(`*_MEM_LIMIT` / `*_CPU_LIMIT`) — tune them to your machine.

```bash
git clone <your-repo-url> agentic-graph-rag && cd agentic-graph-rag
cp .env.example .env          # then edit .env: set NEO4J password (+ API keys if using the api profile)
make setup PROFILE=api        # or: PROFILE=local  (fully local, no keys)
make up
```

The frontend only starts once the API reports healthy (compose waits on a
healthcheck), so when it's up, the whole stack is up. Then open:

- **Web UI** — http://localhost:5173
- **API docs (Swagger, test any endpoint here)** — http://localhost:8000/docs
- **Neo4j browser** — http://localhost:7474

**The whole workflow lives in the browser:** the web UI has a live status bar
(API / Neo4j / Redis), a drag-and-drop **document upload** with per-file ingest
progress, and a streaming chat that shows the **sources** behind every answer.
Add documents, ask questions, and watch the system — end to end, no terminal
needed after `make up`.

Ingest the sample corpus and ask a question:

```bash
docker compose exec api graphrag ingest data/sample.md
# then ask in the web UI: "How are Acme Robotics and Riverside University connected?"
```

Fully local? The `local` profile talks to **the Ollama already running on your
host** (`host.docker.internal:11434`), so it reuses models you've pulled instead
of downloading them again inside a container. Pull these:

```bash
ollama pull gemma4:e4b-it-q4_K_M   # chat + reranking + graph extraction
ollama pull gemma3:4b              # OCR (reads images; see note below)
ollama pull bge-m3                 # embeddings
make setup PROFILE=local && make up
```

No Ollama on the host? Bring up the bundled one instead — `docker compose
--profile local up -d ollama`, set `GRAPHRAG_OLLAMA_BASE_URL_INTERNAL=http://ollama:11434`,
and pull the models inside that container.

**Why two models:** OCR and reasoning have different requirements, and a model
that claims both doesn't always deliver both. `gemma4:e4b-it-q4_K_M` reports
`vision` in `ollama show` but ignores attached images, so OCR uses `gemma3:4b`.
Extraction stays on gemma4 — gemma3 is small enough that it fills the graph with
document-local labels. Every role is a separate config key, so pick per role and
verify rather than trust the capability list. See
[`docs/PROVIDERS.md`](docs/PROVIDERS.md).

### Option B — just the API (no Docker)

You need a Neo4j and a Redis reachable from your machine (local installs, cloud,
or `docker compose up neo4j redis`).

```bash
pip install -e ".[dev,extras]"   # extras = Voyage/Cohere providers the api profile uses
cp .env.example .env          # point GRAPHRAG_NEO4J_* / GRAPHRAG_REDIS_URL at your services
make serve PROFILE=api        # uvicorn on :8000, docs at /docs
graphrag ingest data/sample.md
graphrag query "How are Acme Robotics and Riverside University connected?"
```

---

## The API

Every request is scoped to a **user** via the `X-User-Id` header (the UI has a
user picker; the CLI takes `--user`). Each user has a fully isolated knowledge
base, while the heavy models are loaded once and shared across everyone — so
adding users costs almost no extra memory. See
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) → Multi-user.

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/users` · `GET` `/users` | Create / list users (isolated namespaces). Admin-gated when auth is on. |
| `DELETE` | `/users/{id}/keys` | Revoke every API key a user holds (data stays). |
| `POST` | `/query` | Ask a question. Streams the answer (SSE) by default; returns sources used. |
| `POST` | `/compare` | Side-by-side comparison of several subjects. |
| `POST` | `/search` | Raw hybrid retrieval, no LLM — see exactly what the retriever returns. |
| `POST` | `/ingest` | Ingest a server-side path (under `data/`) **or an http(s) URL** (background job). |
| `POST` | `/ingest/upload` | Upload and ingest a file. |
| `GET`  | `/ingest/{job_id}` | Check ingest progress. |
| `GET`  | `/ingest/files` | List your uploaded files and slots used. |
| `DELETE` | `/ingest/files/{file_id}` | Delete a file, its chunks and orphaned entities, and free its slot. |
| `GET`  | `/usage` | Per-user token usage (admin-gated). |
| `GET`  | `/health` · `/ready` · `/metrics` | Liveness / readiness / Prometheus metrics. |

Every endpoint is testable interactively at **`/docs`** — that page is generated
by FastAPI, so "write and test a request" needs no extra tool.

---

## Configuration in one breath

Settings are layered: `configs/default.yaml` → `configs/<profile>.yaml` → `.env`.
Two ready-made profiles ship with the repo:

- **`local.yaml`** — everything on your host's Ollama, no keys and no model
  weights downloaded: gemma4 for chat/rerank/extraction, gemma3 for OCR, `bge-m3`
  for embeddings. (`local-gemma.yaml` swaps in a larger Gemma 4 for chat.)
- **`api.yaml`** — Claude (`claude-opus-4-8`), Voyage embeddings, Gemini OCR.

Every model role is its own key — `llm`, `ingestion.llm`, `ocr.vision_llm`,
`retrieval.rerank`, `embeddings` — so you can run a different model per role, or
the same one everywhere. See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) and
[`docs/PROVIDERS.md`](docs/PROVIDERS.md). The embedding block exposes fine-grained
control (device, batch size, normalization, prefixes, Matryoshka dimensions,
caching).

**On a small GPU, `num_ctx` matters more than the model you pick** — twice over.

*It decides whether the model fits.* Ollama sizes its KV cache from the context
length, and that cache — not the weights — is usually what spills a model onto
the CPU: gemma4 at Ollama's default context is 9.9 GB and lands 71% on CPU, but
3.3 GB and 100% on GPU at `num_ctx: 8192`. `ollama ps` shows the split.

*And it decides how many models you load.* **Ollama keys a loaded runner by
(model, options), so the same model at two context sizes is two runners.** Give
chat 8192 and reranking 2048 and you haven't saved memory — you've told a 6 GB
card to hold two copies, so it evicts one to rerank and the other to answer,
twice per query. Measured: **33.4s split across two runners, 5.5s sharing one.**
That's why the local profile gives chat, reranking and extraction the *identical*
`num_ctx`, even where a smaller one would do — 4096 and 8192 are both 3.3 GB
anyway (16384 is the cliff), so the smaller number buys nothing and costs a swap.

The rule: **pick one context per model and use it everywhere that model appears.**
Different *models* (gemma3 for OCR, gemma4 for the rest) will still swap — that's
unavoidable on a small card — but the same model should never swap with itself.

---

## Which model runs what

Five roles, five independent config keys. The `local` profile fills them like
this — the choices aren't arbitrary, and the reasons generalise:

| Role | Config key | Default (`local`) | Why this one |
| --- | --- | --- | --- |
| **Chat / agent** | `llm.model` | `gemma4:e4b-it-q4_K_M` | Needs reliable tool calling; runs on every question |
| **Graph extraction** | `ingestion.llm.model` | `gemma4:e4b-it-q4_K_M` | Must resist naming notation; small models can't |
| **Reranking** | `retrieval.rerank.model` | `gemma4:e4b-it-q4_K_M` | Any model that returns a bare number |
| **OCR** | `ocr.vision_llm.model` | `gemma3:4b` | Needs vision that *works* — gemma4's doesn't |
| **Embeddings** | `embeddings.model` | `bge-m3:latest` | 1024-dim, multilingual, strong retrieval |

### Swapping a model

Change the key and restart — no code, no rebuild:

```yaml
llm:
  model: qwen2.5:7b-instruct     # ollama pull it first
  extra: { num_ctx: 8192 }       # then check `ollama ps` — see below
```

**Chat** — any Ollama model listing `tools` in `ollama show` (the agent binds
tools; without them it can't retrieve at all), or an API provider (`anthropic`,
`openai`, `gemini`). Note `gemma3:4b` has **no** `tools` — fine for OCR, useless
as the agent.

**Extraction** — needs to follow instructions well enough to skip notation, which
is a real bar: on notes full of transition tables, gemma3:4b filled the graph with
state names (`Q0`..`Q16`) while gemma4 on the same prompt emitted none. If graph
expansion looks like noise, this is the knob.

**Reranking** — the least fussy: it only has to answer with a number. Any chat
model, `cross_encoder` (faster and better, needs the `local-models` extra),
`cohere` / `voyage`, or `none`.

### A bigger model that doesn't fit is a slower model

Reach for a larger model and you'll usually get a worse system, not a better one.
The moment weights + KV cache exceed VRAM, Ollama runs the overflow on CPU and
the quality gain is spent paying for it. Measured on a 6 GB card (RTX 2060),
same prompt, both warm:

| Chat model | VRAM @ ctx 8192 | On GPU | Speed |
| --- | --- | --- | --- |
| `gemma4:e4b-it-q4_K_M` (8B) | 3.3 GB | **100%** | **41.2 tok/s** |
| `qwen2.5:7b-instruct` (7B) | 5.4 GB | 79% | 27.7 tok/s |

qwen2.5 is the stronger model and its tool calling works — but at 5.4 GB it never
fits alongside the ~1 GB the desktop already holds, so a fifth of it runs on CPU
and it ends up **~50% slower**. No context helps: it's 82% on GPU even at 4096.

So size the model to the card, not the benchmark. `ollama ps` is the whole test —
anything under `100% GPU` means you're paying for weights you can't use. On a
larger card the same comparison flips, which is exactly why this is a config key
and not a hardcoded default.

**OCR** — must be a *vision* model, and the capability list lies. `gemma3:4b`
works; `gemma4:e4b-it-q4_K_M` advertises `vision` and silently ignores images.
`gemini` + `gemini-2.5-flash` is the cloud option, and `ocr.engine: tesseract`
skips models entirely (good for clean printed text, poor for handwriting).

**Embeddings** — `bge-m3:latest` (1024), `nomic-embed-text` (768),
`mxbai-embed-large` (1024), or an API provider. Two catches: point
`embeddings.tokenizer` at the matching HF repo when the model name is an Ollama
tag (Ollama tags aren't HF repo ids, and chunk sizing silently degrades without
it), and **changing dimensions means re-ingesting** — the Neo4j vector index is
created with a fixed width, so a 768-dim model against a 1024-dim index will not
work. Drop the index and re-ingest when you switch.

### Test the model, don't trust the tag

`ollama show <model>` lists capabilities, and it's worth reading — it reliably
tells you what's ruled *out* (no `tools` means it can't be the agent; no
`embedding` means it can't embed). It does not tell you what works:

- `gemma4:e4b-it-q4_K_M` lists `vision`, then answers "please provide the image".
- A GGUF named `Qwen3-VL-Reranker` reports **no** `vision` at all despite the
  "VL", and scores an irrelevant document 10/10 — it reranks nothing.

Both failures are silent: ingest still reports `status=done`, queries still
return an answer. **Swap a model, then check one page, one chunk, one query**
before trusting it.

---

## Project layout

The shape follows the two things the system does: **put documents in** and **get
answers out**. Read it in that order and it explains itself.

```
src/graphrag/
├── core/           Domain vocabulary. Everything else imports FROM here.
│   ├── types.py      Document · Chunk · Entity · Relation · RetrievedChunk
│   ├── errors.py     ConfigError · ProviderError · IngestionError · StorageError
│   └── logging.py    structlog setup (structured key=value logs)
│
├── config/         Layered settings: default.yaml < <profile>.yaml < env
│   ├── settings.py   Typed models. Every knob in the system is a field here.
│   └── loader.py     Deep-merges the YAML layers, reads secrets from env
│
├── ─────────────── INGEST SIDE: file ──▶ graph + vectors ───────────────
│
├── ocr/            Picture of text ──▶ text
│   ├── vision_llm.py Sends the page image to a vision model
│   └── tesseract.py  Offline fallback, no model needed
│
├── ingestion/      The ingest half, in pipeline order
│   ├── loaders/      PDF · Word · HTML · CSV · text · image ──▶ Document (OCR on scans)
│   ├── chunking/     Document ──▶ Chunks. Three strategies:
│   │                   token     fixed windows, exact
│   │                   recursive split on structure, then size  (default)
│   │                   semantic  split where meaning shifts (uses the embedder)
│   ├── extraction/   Chunk ──▶ Entities + Relations, via an LLM
│   └── enrich.py     Post-ingest: entity resolution + community summaries
│
├── embeddings/     Text ──▶ vectors. One `Embedder` interface, several backends
│   ├── ollama.py     Reuses a model you've pulled (no weights downloaded)
│   ├── sentence_transformers.py  In-process, full control (optional extra)
│   ├── api_providers.py          OpenAI · Gemini · Voyage · Cohere
│   └── cache.py      Redis cache keyed by (model, text) — re-ingest is cheap
│
├── ─────────────── QUERY SIDE: question ──▶ answer ─────────────────────
│
├── retrieval/      Finding the right chunks. The interesting part.
│   ├── vector.py           Nearest-neighbour by meaning
│   ├── graph_augmented.py  Follows relationships out from matched entities
│   ├── hybrid.py           Runs several retrievers and combines them
│   ├── fusion.py           Reciprocal Rank Fusion — merges ranked lists fairly
│   └── reranker.py         Re-scores candidates (candidate_k ──▶ top_k)
│
├── agent/          Decides HOW to retrieve — this is the "agentic" part
│   ├── graph.py      LangGraph loop: think ──▶ call tool ──▶ look ──▶ repeat
│   │                   (run/arun/astream_events — sync CLI, async API, streaming)
│   ├── tools.py      What the agent may call: hybrid_search, graph_neighbors,
│   │                   global_search, …
│   ├── prompts.py    System prompts that steer the loop
│   └── styles.py     concise / detailed / technical / eli5
│
├── ─────────────── PLUMBING ────────────────────────────────────────────
│
├── llm/factory.py  One function ──▶ a chat model for any provider
├── storage/        GraphStore + VectorStore interfaces ──▶ Neo4j | local adapters
│   └── vector/       neo4j_vector (native index) · local_store (numpy files)
├── pipelines/      Wires the above into `ingest` and `query` flows
├── jobs.py         Ingest job status, persisted in Redis
├── worker.py       Arq worker — runs ingest off the API process
├── auth.py         API keys (SHA-256 hashed) — the key identifies the user
├── __main__.py     The `graphrag` CLI
├── api/            FastAPI: routers · SSE streaming · deps · /metrics
└── container.py    Composition root: reads config, builds everything, once

frontend/           React + Vite chat UI (threads, upload, sources), nginx
configs/            The YAML profiles — default · local · api · local-gemma
docker/             API image + Caddy reverse-proxy config
scripts/eval.py     Score retrieval + answers against data/eval/qa.yaml (make eval)
tests/unit/         Fast, no services needed. Start here to learn the codebase.
```

### How a request moves through it

**Ingesting** `report.pdf`:

```
api/routers/ingest.py   accepts the upload, queues a job
        │
worker.py               picks it up (so a big PDF never blocks the API)
        │
pipelines/ingest.py     drives the rest:
  loaders/pdf.py          PDF ──▶ text   (ocr/ if a page is a scan)
  chunking/               text ──▶ chunks
  embeddings/             chunks ──▶ vectors ──▶ storage/vector  (Neo4j index)
  extraction/             chunks ──▶ entities + relations ──▶ storage/graph
```

**Answering** *"How are Acme and Riverside connected?"*:

```
api/routers/query.py    receives it, opens an SSE stream
        │
pipelines/query.py      starts an agent session
        │
agent/graph.py          the loop: which tool would answer this?
        │                   └── calls a tool from agent/tools.py
retrieval/hybrid.py         vector + graph + keyword, in parallel
retrieval/fusion.py         merge the ranked lists (RRF)
retrieval/reranker.py       score candidate_k ──▶ keep top_k
        │
agent/graph.py          reads the chunks, answers (or calls another tool)
        │
api/streaming.py        tokens ──▶ browser, then the sources behind them
```

### Why it's shaped this way

**`core/` depends on nothing.** Types and errors sit at the bottom, so no two
modules ever need to import each other to agree on what a `Chunk` is.

**Every provider hides behind an interface.** `Embedder`, `GraphStore`,
`VectorStore`, `Reranker`, `OCREngine` — each is a small abstract class with a
concrete implementation per backend. Swapping Ollama for OpenAI is one new class
and one config line; nothing around it changes. That's why every model in this
README is a config key and not an `if` statement somewhere.

**`container.py` is the only place that knows how the pieces fit.** It reads the
config and builds the object graph once. Heavy things (models, drivers) are
`@cached_property`, so they load on first use and are shared by every user. That's
why adding users costs almost no memory — only the small per-tenant wrappers are
duplicated.

**Ingest and query are separate processes.** The worker does the slow work
(OCR, embedding, extraction) so the API stays responsive, and you can cap their
resources independently in `docker-compose.yml`.

**Reading it for the first time?** `core/types.py` (the vocabulary) ──▶
`configs/default.yaml` (every knob, commented) ──▶ `container.py` (how it's
wired) ──▶ `pipelines/` (the two flows end to end). `tests/unit/` runs in under a
second with no Neo4j or Ollama, and each test documents one real failure mode.

---

## Production hardening

This is built to run as a controllable service, not just a demo. What's in place:

- **Background ingest queue.** Uploads are queued to a separate **Arq worker**
  container (Redis-backed), so large ingests never block the API and the heavy
  work (embeddings + graph extraction) runs where you can cap its resources. Job
  status is persisted in Redis and polled by id. If no worker/Redis is present,
  it falls back to in-process tasks so single-container dev still works.
- **Durable agent memory.** Conversation memory uses a Redis-backed LangGraph
  checkpointer, so multi-turn context survives restarts and is shared across API
  replicas. The API uses the async saver (its streaming needs it), the CLI the
  sync one — same keyspace, so both see the same threads. A Redis that's actually
  unreachable (not just a missing package) degrades to in-process memory instead
  of failing every query.
- **Resource controls.** Every container has RAM/CPU caps (`.env`:
  `API_MEM_LIMIT`, `WORKER_MEM_LIMIT`, `NEO4J_MEM_LIMIT`, `NEO4J_HEAP`, …), plus
  CPU-thread caps (`OMP_NUM_THREADS`) and worker concurrency
  (`GRAPHRAG_WORKER_CONCURRENCY`) so local models can't starve the host.
- **Limits.** Per-user file cap (**10 files**, `api.max_files_per_user`), upload
  size cap (`api.max_upload_mb`), and per-user **rate limiting** (`api.rate_limit`;
  keyed by the *verified* user when auth is on, IP otherwise — never a spoofable
  header, and Redis-backed so limits hold across replicas). CORS is restricted to
  configured origins/methods/headers, and the API warns on a default Neo4j
  password. The file cap counts what you currently store, not what you have ever
  uploaded — `DELETE /ingest/files/{id}` frees a slot. Raising `max_upload_mb`
  also needs `MAX_UPLOAD_MB` in `.env` raised (nginx rejects oversized bodies
  before the API sees them, and its own default is 1 MB).
- **Confined server-side ingest.** `POST /ingest` with a path is fenced to
  `data/` (an attempt to reach `.env` or any other server file is a 400), and it
  also accepts an http(s) URL, fetched with a size cap. Uploads go through
  `/ingest/upload` regardless.
- **API-key authentication.** Set `auth.enabled: true` and requests must carry a
  valid key (`Authorization: Bearer <key>`); the verified key determines the user,
  so tenant identity is trustworthy (not a spoofable header). Keys are stored only
  as SHA-256 hashes. User management **fails closed**: with auth on and no
  `GRAPHRAG_ADMIN_KEY` set, `POST /users` is *locked*, not open — otherwise anyone
  could mint themselves a key. Mint one with `graphrag apikey <user>` or (admin)
  `POST /users`; revoke a leaked one with `graphrag revoke <user>` or
  `DELETE /users/{id}/keys`. Off by default for local dev.
- **Observability.** Prometheus metrics at `/metrics` (request counts + latency
  histograms, labeled by route template so cardinality stays bounded), and
  approximate per-user token usage at `/usage`. A `make eval` target scores
  retrieval and answers against a golden set (`data/eval/qa.yaml`) so retrieval
  changes are measured, not guessed.
- **TLS + reverse proxy.** A **Caddy** proxy is the public entrypoint (80/443):
  it terminates TLS, routes `/api/*` → API and everything else → the UI (and
  streams SSE). Behind it the UI and API share one origin, so CORS isn't needed.

### Exposing it over HTTPS

The proxy handles certificates automatically — you just set `SITE_ADDRESS`:

| `SITE_ADDRESS` | Result |
|---|---|
| `:80` (default) | Plain HTTP on port 80 — local dev |
| `localhost` | HTTPS via Caddy's local self-signed CA |
| `rag.example.com` | **HTTPS via automatic Let's Encrypt** (also set `TLS_EMAIL`) |

For a public domain: point its DNS A record at the host, set `SITE_ADDRESS` and
`TLS_EMAIL` in `.env`, and `docker compose up` — Caddy provisions and renews the
cert on :443 and redirects HTTP→HTTPS. For a real deployment, also remove the
host `ports` from the `api`/`frontend` services so only the proxy is reachable.

Still on the roadmap before untrusted-internet exposure: per-tenant vector
isolation at scale (Enterprise DB-per-user), backups, and distributed tracing.
Metrics are now exported at `/metrics`; the `local` vector provider (exact numpy
search, no service) is a first step toward the quantized ANN backends —
TurboQuant and friends — sketched in
[`docs/OPTIMIZATION-NOTES.md`](docs/OPTIMIZATION-NOTES.md).

## Development

```bash
make install     # editable install with dev + extra providers
make test        # unit tests (fast, no services)
make eval        # score retrieval + answers vs the golden set (needs the stack up)
make lint        # ruff + mypy
make fmt         # auto-format
```

Design decisions and the reasoning behind them live in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

MIT — see [LICENSE](LICENSE).
