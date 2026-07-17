# Configuration

Configuration is layered. Each layer overrides the one before it:

```
configs/default.yaml   <   configs/<profile>.yaml   <   environment (.env)
```

- **`default.yaml`** — every setting, with sensible defaults.
- **`<profile>.yaml`** — `local.yaml` (Ollama + open models, no keys) or
  `api.yaml` (cloud models). Pick with `GRAPHRAG_PROFILE`.
- **environment** — secrets (API keys) and service URLs only. Never put keys in
  YAML.

Change the profile with `make setup PROFILE=local` (or `api`), or set
`GRAPHRAG_PROFILE` directly.

## Embeddings — the knobs

The embedding block exposes fine-grained control:

| Key              | What it does |
|------------------|--------------|
| `provider`       | `ollama` (local, reuses a pulled model) / `sentence_transformers` (local, in-process) / `openai` / `gemini` / `voyage` / `cohere` |
| `model`          | The embedding model name |
| `tokenizer`      | HF tokenizer for chunk sizing; defaults to `model`. Set it when `model` isn't an HF repo id (Ollama tags like `bge-m3:latest` aren't) |
| `dimensions`     | Truncate output dim (Matryoshka models like bge-m3 support this) |
| `device`         | `auto` / `cpu` / `cuda` / `mps` |
| `batch_size`     | Encoding batch size |
| `normalize`      | L2-normalize vectors (recommended for cosine) |
| `max_seq_length` | Max tokens per chunk the embedder will read |
| `query_prefix`   | Prepended to queries (e.g. `"query: "` for e5 models) |
| `document_prefix`| Prepended to documents |
| `cache.enabled`  | Cache vectors in Redis, keyed by `(model, text)` |

Under `provider: ollama` the server owns `max_seq_length` and `device` — setting
them logs a warning and changes nothing. Every other key still applies.

## Chunking

`chunking.strategy` chooses how documents are split:

- **`recursive`** (default) — split on structure (paragraphs → lines →
  sentences) using a token-aware length function, then hard-cap any oversized
  piece with token windowing. Good boundaries, guaranteed to fit.
- **`token`** — pure `encode → slide a window → decode` over the embedder's
  tokenizer. Deterministic and cheap, but can cut mid-sentence.
- **`semantic`** — embed sentences and start a new chunk where meaning shifts
  (opt-in quality mode; costs embeddings at ingest time).

`max_tokens` and `overlap` are measured in the *embedder's* tokens.

## OCR

`ocr.engine`:

- **`vision_llm`** (default) — a small vision model transcribes images.
  `provider: ollama` + a vision model runs locally; switch to `provider: gemini`
  + `model: gemini-2.5-flash` for the cloud.
- **`tesseract`** — offline, no model download, best for clean printed text.

**Verify your vision model actually reads images.** `ollama show` listing
`vision` is a claim, not a guarantee: `gemma4:e4b-it-q4_K_M` advertises it and
then answers "please provide the image", which OCR cannot distinguish from a page
that legitimately has no text. `gemma3:4b` reads the same page correctly. Test
with one page before trusting a model here.

**`ocr.min_text_chars`** (default `100`) decides when a page is a scan. Scanned
pages usually carry a thin text layer — a page number, a scanner header — so
"extracted some text" is not "read the page". Pages with a shorter text layer go
to OCR; OCR only replaces the text if it reads *more*, so a failed render can't
destroy what the text layer had. `0` restores empty-only behaviour, which
silently misses any scan bearing a page label.

## Graph extraction (`ingestion`)

`extract_graph: false` skips entity/relation extraction entirely — vector-only
RAG, and by far the biggest ingest speedup available.

`ingestion.llm` is an optional model just for extraction; unset, it uses the
top-level `llm`. Worth splitting out: extraction sees one chunk at a time, so it
needs far less context than chat, and on a small GPU context size decides whether
a model fits in VRAM at all. Model choice matters here beyond speed — extraction
must resist naming things that only mean something inside the document (state
labels, variables, grammar symbols). Small models often can't, and fill the graph
with entities like `Q0`..`Q16`. If graph expansion looks noisy, that's the knob.

`ingestion.max_concurrency` is how many extraction LLM calls run in parallel per
document (extraction is the slow part of ingest; the writes stay serial).

Two post-ingest passes run automatically and can be tuned or disabled:

- **`ingestion.resolve_entities`** merges entities that name the same thing —
  "Acme" and "Acme Robotics" — which the per-chunk extractor can't see. It uses
  token containment plus name-embedding similarity (`similarity`, default 0.93),
  deliberately conservative because a wrong merge is worse than a missed one.
- **`ingestion.communities`** clusters the entity graph and LLM-summarizes each
  cluster (`max_communities`, `min_size`). Those summaries back the agent's
  `global_search` tool, which answers whole-corpus questions ("what are the main
  themes?") that no single chunk can. Both rebuild at the end of each ingest.

## Storage & retrieval

`storage.graph` / `storage.vector` select the backend. `storage.vector.provider`
is `neo4j` (vectors on `:Chunk` nodes, native ANN index) or `local` (exact numpy
search over files under `local_dir` — no service, fine to ~100k chunks per
corpus; chunk nodes still live in Neo4j for fulltext + graph edges).
`retrieval.top_k` is how many chunks reach the LLM; `candidate_k` is how many are
fetched before reranking; `graph_hops` bounds graph traversal *and* how far
graph-augmented retrieval follows relationships out from matched entities;
`rerank` picks the reranker (`ollama` / any chat model, `cross_encoder` local, or
`cohere` / `voyage`). See [`PROVIDERS.md`](PROVIDERS.md) for the trade-offs.

## Authentication (`auth`)

Off by default (dev). Turn on with `auth.enabled: true`:

- Requests must send `Authorization: Bearer <key>` (or `X-API-Key: <key>`).
- The **verified key determines the user** — the `X-User-Id` header is ignored,
  so tenant identity can't be spoofed.
- Keys are stored only as SHA-256 hashes (in Redis). They're shown **once** at
  creation.
- Mint keys with `graphrag apikey <user>` or (admin) `POST /users`; revoke every
  key a user holds with `graphrag revoke <user>` or `DELETE /users/{id}/keys`.
- User management is admin-gated and **fails closed**: with auth on you must set
  `GRAPHRAG_ADMIN_KEY` in `.env` and send it as `X-Admin-Key`. Without the key
  configured, `POST /users` / `GET /users` are locked — otherwise anyone could
  create a user and mint themselves a valid key.

## Limits & resources

**API limits (`api` block):**

| Key                   | What it does |
|-----------------------|--------------|
| `rate_limit`          | Requests per window, per user (falls back to IP), e.g. `"60/minute"` |
| `max_upload_mb`       | Reject uploads larger than this. **Also raise `MAX_UPLOAD_MB` in `.env`** — the frontend's nginx rejects bigger bodies before the API sees them, and its own default is 1 MB |
| `max_files_per_user`  | Files you may currently store (default **10**). `DELETE /ingest/files/{id}` frees a slot |
| `cors_origins` / `cors_methods` / `cors_headers` | Restrict cross-origin access |

**Container RAM/CPU (`.env`):** `API_MEM_LIMIT`, `API_CPU_LIMIT`,
`WORKER_MEM_LIMIT`, `WORKER_CPU_LIMIT`, `NEO4J_MEM_LIMIT`, `NEO4J_HEAP`,
`NEO4J_PAGECACHE`, `REDIS_MAXMEMORY`, `OLLAMA_MEM_LIMIT`, … plus
`OMP_NUM_THREADS` (CPU threads for local model math) and
`GRAPHRAG_WORKER_CONCURRENCY` (parallel ingest jobs). Tune to your machine.

## Multi-user (`tenancy`)

Each user gets an isolated knowledge base. The heavy models (embedder, reranker,
LLM) are loaded **once and shared** across all users — only lightweight
store/retriever wrappers are per-user, so memory stays flat as users grow.

| Key                    | What it does |
|------------------------|--------------|
| `enabled`              | Turn multi-user routing on/off |
| `default_user`         | Namespace used when no user is given |
| `per_tenant_database`  | `false`: isolate by a `corpus` tag inside one Neo4j DB (works on Community). `true`: a real Neo4j database per user (**requires Enterprise**) |
| `database_prefix`      | Prefix for per-user database names (Enterprise mode) |
| `max_active_tenants`   | Upper bound on the in-memory tenant cache; evicting a tenant drops only cheap wrappers, never the shared models |

**Choosing a user per request:**

- **API:** send an `X-User-Id: alice` header. Missing → `default_user`.
- **UI:** the user picker (top-right) selects/creates a user and stores it locally.
- **CLI:** `graphrag ingest data/x.pdf --user alice`, `graphrag query "..." --user alice`.

Conversation memory is namespaced per user, so threads never cross accounts.

## Secrets (`.env`)

Only set the keys for providers you actually enable:

```
ANTHROPIC_API_KEY=...   # reply LLM (api profile)
GOOGLE_API_KEY=...      # Gemini OCR / embeddings
VOYAGE_API_KEY=...      # embeddings + rerank
OPENAI_API_KEY=...      # optional
COHERE_API_KEY=...      # optional
```
