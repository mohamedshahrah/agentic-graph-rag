# API image. Includes Tesseract (OCR fallback) and poppler (PDF rendering).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    GRAPHRAG_CONFIG_DIR=/app/configs

RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr poppler-utils build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

# `[extras]` ships the API embedders/rerankers (Voyage, Cohere) the `api`
# profile selects — without them that profile cannot embed or rerank at all.
# They're small. What stays opt-in is `[local-models]` (torch, ~3.9 GB of it
# CUDA libraries this container has no GPU for): add it via
# --build-arg EXTRAS='[extras,local-models]' if you want the in-process
# embedder/cross-encoder; the `local` profile serves both roles from Ollama.
ARG EXTRAS="[extras]"
RUN pip install ".${EXTRAS}"

COPY configs ./configs

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=30 --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "graphrag.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
