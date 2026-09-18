# vigilAI worker — the pipeline + PDF rendering (docs/design.md "Architecture").
# Same code as the api image, different command. Playwright's Chromium is needed only
# for PDF export (Phase 5); it is installed here so one worker image covers every stage.
# Phase 0 stub: the image builds but the worker module lands in Phase 3.
FROM python:3.10-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e "."
# Phase 5: RUN python -m playwright install --with-deps chromium

CMD ["python", "-m", "vigilai.worker"]
