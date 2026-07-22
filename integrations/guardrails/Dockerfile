# Guardrails server — small, non-root image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GUARD_HOST=0.0.0.0 \
    GUARD_PORT=8080

WORKDIR /app

# Install dependencies + package first (better layer caching).
COPY pyproject.toml README.md ./
COPY guardrails ./guardrails
COPY policies ./policies
RUN pip install --no-cache-dir .

# Run as a non-root user.
RUN useradd --create-home --uid 10001 guard && chown -R guard:guard /app
USER guard

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health').status==200 else 1)"

CMD ["guardrails-server"]
