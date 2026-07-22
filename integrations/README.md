# integrations/ — the two features wired into this RAG

This folder holds **vendored copies** of two standalone projects that are also
integrated into this app as features. They keep their own code, README, tests and
Docker setup; this RAG repo owns only the *glue* that connects them (in
`src/graphrag/safety/` and `src/graphrag/observability/`).

| Folder | Feature | Upstream repo |
|---|---|---|
| `guardrails/` | **Guardrails & Safety Layer** — an `allow`/`flag`/`block` verdict service that screens LLM inputs and outputs. | github.com/mohamedshahrah/Guardrails-Safety-Layer-for-LLM-Apps |
| `llmlens/` | **llmlens** — self-hostable LLM observability (traces, cost-per-user, latency, alerting). | github.com/mohamedshahrah/LLMlens |

**How they're connected → [`../docs/INTEGRATIONS.md`](../docs/INTEGRATIONS.md).**
That's the file to read: where each hooks into the query path, how to switch it
on, and how to run everything together.

## These are copies, not forks

Each folder is a source snapshot with `.git`, `.venv`, and build caches removed —
so there are no nested git repos and nothing here mixes into the RAG history's
notion of those projects. The canonical versions live in their own repos above.
To refresh a copy or switch to git submodules, see
[Keeping the vendored copies in sync](../docs/INTEGRATIONS.md#keeping-the-vendored-copies-in-sync).

## Run a feature on its own

Each is self-contained — its README is the authority:

```bash
# Guardrails (offline mock judge, no keys)
cd guardrails && cp .env.example .env && pip install -e ".[dev]" && guardrails-server

# llmlens (full stack)
cd llmlens && cp .env.example .env && docker compose up -d
```

To run them *alongside* the RAG stack (ports remapped so nothing collides), use
the compose files referenced in [`../docs/INTEGRATIONS.md`](../docs/INTEGRATIONS.md#run-it).
