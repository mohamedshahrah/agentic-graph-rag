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
   (PDF/text/image)   │                     │
                      └──▶ LLM extracts ──▶ knowledge graph
                           entities +       (entities linked to
                           relationships     the chunks that mention them)
```

Images and scanned PDFs are read by a small vision model (**OCR**) before
chunking, so a picture of text becomes searchable text. A page goes to OCR when
its text layer is thinner than `ocr.min_text_chars` — not merely when it's empty,
because scans usually carry a page number or a scanner header, and "has some
text" is not "was read".

**Answering a question:**

```
question ──▶ agent ──▶ picks tool(s) ──▶ hybrid retrieval ──▶ rerank ──▶ answer + sources
                        │                 (vector ⊕ graph ⊕ keyword,
                        │                  fused with RRF)
                        └── graph_neighbors, compare, get_entity, ...
```

The agent cites the exact chunks it used. Answers come in a **style** you choose
(concise / detailed / technical / ELI5), and it can **compare** several subjects
side by side.

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
pip install -e ".[dev]"
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
| `POST` | `/users` · `GET` `/users` | Create / list users (isolated namespaces). |
| `POST` | `/query` | Ask a question. Streams the answer (SSE) by default; returns sources used. |
| `POST` | `/compare` | Side-by-side comparison of several subjects. |
| `POST` | `/search` | Raw hybrid retrieval, no LLM — see exactly what the retriever returns. |
| `POST` | `/ingest` | Ingest a server-side path (background job). |
| `POST` | `/ingest/upload` | Upload and ingest a file. |
| `GET`  | `/ingest/{job_id}` | Check ingest progress. |
| `GET`  | `/ingest/files` | List your uploaded files and slots used. |
| `DELETE` | `/ingest/files/{file_id}` | Delete a file, its chunks and orphaned entities, and free its slot. |
| `GET`  | `/health` · `/ready` | Liveness / readiness. |

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

**On a small GPU, `num_ctx` matters more than the model you pick.** Ollama sizes
its KV cache from the context length, and that cache — not the weights — is
usually what spills a model onto the CPU: gemma4 at Ollama's default context is
9.9 GB and lands 71% on CPU, but 3.3 GB and 100% on GPU at `num_ctx: 8192`.
Extraction gets 4096 (it sees one chunk), reranking 2048 (a query and one chunk).
`ollama ps` shows the CPU/GPU split — that's the number to watch.

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

```
src/graphrag/
  config/       layered settings + secrets
  core/         domain types, errors, logging
  ingestion/    loaders · chunking (token / recursive / semantic) · KG extraction
  ocr/          vision-LLM (Ollama / Gemini) · Tesseract
  embeddings/   Ollama · API providers · in-process (optional extra), Redis-cached
  llm/          one factory across Ollama / Claude / OpenAI / Gemini
  storage/      GraphStore + VectorStore interfaces → Neo4j adapter
  retrieval/    vector · graph-augmented · hybrid · RRF fusion · rerank
  agent/        LangGraph loop · tools · answer styles
  pipelines/    ingest · query
  api/          FastAPI app, routers, SSE streaming
  container.py  the composition root (all wiring, one place)
frontend/       React + Vite chat UI (own Docker container)
```

Each layer talks to the next through an interface, so replacing a piece (a
different LLM, an embedded graph DB) means writing one adapter — not editing the
layers around it.

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
  replicas (falls back to in-process memory if unavailable).
- **Resource controls.** Every container has RAM/CPU caps (`.env`:
  `API_MEM_LIMIT`, `WORKER_MEM_LIMIT`, `NEO4J_MEM_LIMIT`, `NEO4J_HEAP`, …), plus
  CPU-thread caps (`OMP_NUM_THREADS`) and worker concurrency
  (`GRAPHRAG_WORKER_CONCURRENCY`) so local models can't starve the host.
- **Limits.** Per-user file cap (**10 files**, `api.max_files_per_user`), upload
  size cap (`api.max_upload_mb`), and per-user **rate limiting**
  (`api.rate_limit`, keyed by `X-User-Id` / IP). CORS is restricted to configured
  origins/methods/headers, and the API warns on a default Neo4j password. The
  file cap counts what you currently store, not what you have ever uploaded —
  `DELETE /ingest/files/{id}` frees a slot. Raising `max_upload_mb` also needs
  `MAX_UPLOAD_MB` in `.env` raised (nginx rejects oversized bodies before the API
  sees them, and its own default is 1 MB).
- **API-key authentication.** Set `auth.enabled: true` and requests must carry a
  valid key (`Authorization: Bearer <key>`); the verified key determines the user,
  so tenant identity is trustworthy (not a spoofable header). Keys are stored only
  as SHA-256 hashes. Mint one with `graphrag apikey <user>` or `POST /users`
  (gated by `GRAPHRAG_ADMIN_KEY` when set). Off by default for local dev.
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
isolation at scale (Enterprise DB-per-user), backups, and metrics/tracing.
Vector-quantization opportunities (e.g. TurboQuant) are noted in
[`docs/OPTIMIZATION-NOTES.md`](docs/OPTIMIZATION-NOTES.md).

## Development

```bash
make install     # editable install with dev + extra providers
make test        # unit tests
make lint        # ruff + mypy
make fmt         # auto-format
```

Design decisions and the reasoning behind them live in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

MIT — see [LICENSE](LICENSE).
