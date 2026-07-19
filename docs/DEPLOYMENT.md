# Deployment

Target: a single small VPS — 2 vCPU, 8 GB RAM (Hetzner CX32 class). Everything
below assumes that shape; on a bigger box the only thing that changes is the
memory caps.

## What runs

| Service | Memory cap | Why it's there |
| --- | --- | --- |
| `api` | 2 GB | FastAPI + the agent. Also runs ingest (see below). |
| `neo4j` | 1.5 GB | The knowledge graph. Heap 640m + pagecache 320m fits inside with JVM headroom. |
| `postgres` | 768 MB | Accounts, limits, usage, chat history, agent memory. |
| `redis` | 256 MB | Caches, rate-limit windows, live job status. All rebuildable. |
| `frontend` | 64 MB | nginx serving the built SPA. |
| `proxy` | 128 MB | Caddy: TLS and the public entrypoint. |

That's ~4.7 GB of limits, leaving room for the OS and page cache. Two services
are off by default: `ollama` (profile `local`) and `worker` (profile `worker`).

**No torch.** The production profile uses Cohere for embeddings and reranking,
so the ~3.9 GB of CUDA libraries `sentence-transformers` would pull in are never
installed. Adding `--build-arg EXTRAS='[extras,local-models]'` puts them back if
you want in-process models — on a CPU-only box you almost certainly don't.

## First run

```bash
cp .env.example .env
# Set at minimum:
#   GRAPHRAG_NEO4J_PASSWORD, GRAPHRAG_POSTGRES_PASSWORD
#   GOOGLE_API_KEY (chat + OCR), COHERE_API_KEY (embeddings + rerank)
#   GRAPHRAG_ADMIN_EMAIL (the address you'll sign up with)
#   RESEND_API_KEY or BREVO_API_KEY (so verification codes actually send)
#   SITE_ADDRESS=your.domain, TLS_EMAIL=you@example.com

make up            # builds, starts, and applies migrations
```

Then sign up in the browser, enter the code, and restart the API once so
`GRAPHRAG_ADMIN_EMAIL` is promoted — or skip the restart:

```bash
make admin EMAIL=you@example.com
```

Without an email provider configured, codes are written to the log instead of
sent:

```bash
docker compose logs api | grep "code is"
```

## The two settings that decide whether you're exposed

**`GRAPHRAG_PROFILE`.** `local` and `api` disable authentication — any caller
can act as any user via the `X-User-Id` header. Only `production` turns accounts
on. The API logs a warning at startup when auth is off; if you see
`auth_disabled` in a deployed server's log, that server is open.

**`SITE_ADDRESS`.** Set it to your domain and Caddy provisions a Let's Encrypt
certificate and redirects HTTP to HTTPS. Left at `:80`, everything is plaintext
on the wire, including session cookies and passwords.

For a real deployment also remove the host `ports:` from the `api` and
`frontend` services in `docker-compose.yml`, so only the proxy is reachable.

## Why ingest runs inside the API

The DuckDB vector store gives each user their own database file. DuckDB takes an
exclusive lock on an open file, so exactly one OS process may hold a given
tenant's database — and the API needs it for every query.

Rather than coordinate two processes over a lock, the deployment removes the
second one: ingest runs as a background task in the API under a semaphore, so
one upload at a time, off the request path. With cloud embedding and extraction
this work is I/O-bound, so it doesn't fight the chat stream for CPU.

The Arq worker still exists for deployments using the Neo4j vector provider:

```bash
GRAPHRAG_USE_WORKER=1 docker compose --profile worker up -d
```

It refuses to start against the `duckdb` provider rather than corrupt a file.

## Backups

Two things hold user data, and both need backing up:

```bash
# Postgres: accounts, limits, usage, chat history
docker compose exec -T postgres pg_dump -U graphrag graphrag | gzip > pg-$(date +%F).sql.gz

# Neo4j: the knowledge graph
docker compose exec neo4j neo4j-admin database dump neo4j --to-path=/data/backups

# Vectors + uploads: plain files on the host
tar czf data-$(date +%F).tar.gz data/
```

`data/vectors/` holds one `.duckdb` file per tenant, so a single user can be
restored without touching anyone else's. Restore has to be rehearsed to count —
untested backups are a belief, not a policy.

## Scaling past one box

The design has room, in roughly this order:

1. **Postgres and Neo4j move to managed services.** Both are already reached by
   URL; nothing in the app assumes they're local.
2. **More API replicas.** Rate limits and caches are already Redis-backed and
   shared. The blocker is DuckDB's single-writer file: replicas need either the
   Neo4j vector provider, or sticky routing per tenant, or a networked vector
   store behind the same `VectorStore` interface.
3. **An ANN index.** The exact cosine scan is milliseconds at the per-user chunk
   ceiling and always exact. Past that, see
   [OPTIMIZATION-NOTES.md](OPTIMIZATION-NOTES.md).
