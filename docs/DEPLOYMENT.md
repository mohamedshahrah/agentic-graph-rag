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

> **Set the database passwords *before* this first `make up`.** Postgres and
> Neo4j bake their password in when their data volume is first created;
> changing `.env` afterwards doesn't change the stored password and every
> connection then fails auth. If you hit that, see
> [Operations & troubleshooting](#operations--troubleshooting) below.

Then sign up in the browser with the `GRAPHRAG_ADMIN_EMAIL` address, enter the
code, and claim admin (no restart needed):

```bash
make admin EMAIL=you@example.com
```

Without an email provider configured, codes are written to the log instead of
sent — enough for a first boot or a single admin:

```bash
docker compose logs api | grep "code is"
```

For real users to receive codes, wire up [email delivery](#email-delivery-verification-codes).

## The two settings that decide whether you're exposed

**`GRAPHRAG_PROFILE`.** `local` and `api` disable authentication — any caller
can act as any user via the `X-User-Id` header. Only `production` turns accounts
on. The API logs a warning at startup when auth is off; if you see
`auth_disabled` in a deployed server's log, that server is open.

**`SITE_ADDRESS`.** Set it to your domain and Caddy provisions a Let's Encrypt
certificate and redirects HTTP to HTTPS. Left at `:80`, everything is plaintext
on the wire, including session cookies and passwords.

Every published port except the proxy's 80/443 is bound to `127.0.0.1`, so
from the network only the proxy exists. Neo4j browser, Postgres, Redis, the
raw API and the llmlens dashboard are reachable from the box itself (or over
an SSH tunnel, e.g. `ssh -L 7474:localhost:7474 you@host`), never from outside.

## Email delivery (verification codes)

Signup emails a 6-digit code that the account must enter before it activates.
Where that code goes depends on config:

- **No provider key** → the code is written to the API log
  (`docker compose logs api | grep "code is"`). Fine for a first boot or a lone
  admin; useless for real users.
- **Resend or Brevo key set** → the code is emailed.

Sending is best-effort: a signup never fails because the email API had a bad
minute — the user is told to request a resend instead. An `email_send_failed`
line in the log carries the provider's reason when one is rejected.

### Resend

1. Create a key at your Resend dashboard → **API Keys → Create API Key** (a
   `re_…` string). Put it in `.env` as `RESEND_API_KEY=…`.
2. Choose a sender address — this decides who can receive mail:
   - **Testing** — `GRAPHRAG_EMAIL_FROM=Graph RAG <onboarding@resend.dev>`.
     Works with just the key, no DNS. But Resend's shared sender only delivers
     to the address your Resend account is registered under — enough to receive
     your *own* admin code, not anyone else's.
   - **Production** — verify a domain you own (Resend → **Domains → Add Domain**,
     then add the DNS records it shows), and set
     `GRAPHRAG_EMAIL_FROM=Graph RAG <noreply@yourdomain.com>`. Now codes reach
     any address.
3. Apply it — recreate, don't restart (see [troubleshooting](#operations--troubleshooting)):
   ```bash
   docker compose up -d --force-recreate api
   ```

On startup the API logs `email_provider_unconfigured` (falling back to console)
if the key wasn't picked up — usually because the container was `restart`ed
rather than recreated.

Verify delivery without creating an account (swap in an address your sender can
reach):

```bash
docker compose exec -T api python - <<'PY'
import asyncio
from graphrag.accounts.emails import build_email_sender
from graphrag.config.loader import load_settings
settings, secrets = load_settings()
sender = build_email_sender(settings, secrets)
print("sender:", type(sender).__name__, "from:", secrets.email_from)
print("sent :", asyncio.run(sender.send("you@example.com", "Test", "It works.")))
PY
```

`sender: ConsoleSender` means the key isn't active — check `RESEND_API_KEY` and
that you recreated the container.

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

## Operations & troubleshooting

### Changing `.env` needs a recreate, not a restart

`docker compose restart api` reuses the container's existing environment — a new
value in `.env` is silently ignored. To pick up **any** `.env` change (a key, a
password, the sender address):

```bash
docker compose up -d --force-recreate api
```

This is behind most "I changed it but nothing happened" confusion here.

### "password authentication failed" for user graphrag / neo4j

Postgres and Neo4j read their password **only when their data volume is first
created**. Changing `GRAPHRAG_POSTGRES_PASSWORD` / `GRAPHRAG_NEO4J_PASSWORD`
afterwards doesn't touch the stored password — the app sends the new one and the
database rejects it. Set them before the first `make up`. To fix a volume that's
already out of sync:

**Postgres** — reset the stored password in place (non-destructive):

```bash
docker compose exec -T postgres psql -U graphrag -d graphrag \
  -c "ALTER USER graphrag WITH PASSWORD 'the-value-from-your-env';"
docker compose up -d --force-recreate api
```

(The socket connection inside the container uses trust auth, so this works
without knowing the old password.)

**Neo4j** stores credentials in its system database — there's no in-place reset
without the old password. If the graph holds nothing you need (for instance you
never completed an ingest), recreate its volume so it reinitializes from `.env`:

```bash
docker compose rm -sf neo4j
docker volume rm agentic-graph-rag_neo4j_data   # wipes the graph ONLY
docker compose up -d neo4j
docker compose up -d --force-recreate api
```

Postgres (accounts) and the DuckDB vectors are separate volumes and are
untouched. If you *do* have graph data to keep, instead restart Neo4j once with
`NEO4J_dbms_security_auth__enabled=false`, run `ALTER USER neo4j SET PASSWORD`,
then remove that override and restart.

### Uploads fail with a permission error

The API runs as a non-root user; its entrypoint chowns the mounted `data/`
directory on start so it can write uploads and the per-user DuckDB files. If
uploads 500 with `PermissionError`, the entrypoint didn't run — check the image
was built from the current `docker/Dockerfile` (it must have an `ENTRYPOINT`),
and that `docker/entrypoint.sh` has LF line endings (a `.gitattributes` pins
this; a Windows checkout without it can reintroduce CRLF).

### Becoming admin / reaching the admin panel

The admin area at `/admin` needs an account with the admin role.

1. Sign up in the browser with the address in `GRAPHRAG_ADMIN_EMAIL`.
2. Promote it (no restart needed):
   ```bash
   make admin EMAIL=you@example.com
   # or: docker compose exec api graphrag promote-admin you@example.com
   ```
   Restarting the API also auto-promotes `GRAPHRAG_ADMIN_EMAIL` once that account
   exists.
3. Sign out and back in — an **Admin** link appears in the header.

Break-glass: `GRAPHRAG_ADMIN_KEY` in `.env` reaches admin endpoints with an
`X-Admin-Key` header even when no admin account exists — for bootstrap or
recovery when you're locked out.

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
