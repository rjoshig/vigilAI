# vigilAI api — FastAPI (docs/design.md "Architecture").
# Phase 0 stub: the image builds but the app module lands in Phase 3.
# Python floor is 3.10 (ADR-010); the image pins the same major.minor as .python-version.
FROM python:3.10-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e "."

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "vigilai.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
