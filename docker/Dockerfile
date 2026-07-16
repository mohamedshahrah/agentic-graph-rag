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

# Optional extras, e.g. --build-arg EXTRAS='[local-models]' to run the embedder
# and cross-encoder reranker in-process. That pulls torch plus ~2.7 GB of CUDA
# libraries this container has no GPU to use, so it's off by default; the
# `local` profile serves both roles from Ollama instead.
ARG EXTRAS=""
RUN pip install ".${EXTRAS}"

COPY configs ./configs

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=30 --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "graphrag.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
