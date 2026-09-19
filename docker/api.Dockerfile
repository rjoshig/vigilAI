# The API container. Accepts requests, validates uploads, writes rows, enqueues jobs.
# It never parses a file and never calls the model (docs/architecture.md).
FROM python:3.10-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a code change does not reinstall them.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

COPY alembic.ini ./
COPY scripts/ ./scripts/

# The shared volume: uploads, generated reports, PDFs (ADR-007).
RUN mkdir -p /data && useradd --create-home --uid 10001 greenlight && chown -R greenlight /data /app
USER greenlight

ENV GREENLIGHT_AI_DATA_DIR=/data

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Migrations run on start, so a fresh volume comes up with the current schema.
CMD ["sh", "-c", "alembic upgrade head && uvicorn greenlight_ai.api.app:get_app --factory --host 0.0.0.0 --port 8000"]
