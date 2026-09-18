# The worker container. Claims queued jobs and runs the nine-stage pipeline.
# Scale with: docker compose up --scale worker=4
FROM python:3.10-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

COPY scripts/ ./scripts/

RUN mkdir -p /data && useradd --create-home --uid 10001 vigilai && chown -R vigilai /data /app
USER vigilai

ENV VIGILAI_DATA_DIR=/data

# No migrations here: the api applies them, and several workers racing to migrate the
# same database is a way to corrupt it.
CMD ["python", "-m", "vigilai.worker.app"]
