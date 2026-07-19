# API image. Includes Tesseract (OCR fallback) and poppler (PDF rendering).
#
# Two stages so the compiler toolchain needed to build wheels doesn't ship to
# production: the builder produces a virtualenv, the runtime copies it. Saves
# roughly 300 MB and removes gcc from the deployed image.
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

# `[extras]` ships the API embedders/rerankers (Cohere, Voyage) the cloud
# profiles select — without them those profiles cannot embed or rerank at all.
# They're small. What stays opt-in is `[local-models]` (torch, ~3.9 GB of it
# CUDA libraries this container has no GPU for): add it via
# --build-arg EXTRAS='[extras,local-models]' if you want the in-process
# embedder/cross-encoder; the `local` profile serves both roles from Ollama.
ARG EXTRAS="[extras]"
RUN pip install ".${EXTRAS}"


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/app/.cache/huggingface \
    GRAPHRAG_CONFIG_DIR=/app/configs

RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY configs ./configs
COPY migrations ./migrations

# Run as a non-root user. `data/` and the HF cache are the only paths written
# at runtime, so they're the only ones that need to be owned.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data /app/.cache/huggingface \
    && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=30 --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# One worker process: the duckdb vector provider requires a single owner per
# tenant file, and on 2 vCPUs a second worker would contend rather than help.
CMD ["uvicorn", "graphrag.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
