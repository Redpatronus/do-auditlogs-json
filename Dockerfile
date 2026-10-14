FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN apt-get update && apt-get install -y --no-install-recommends xvfb \
 && rm -rf /var/lib/apt/lists/*

ENV DOAL_STORAGE_STATE_PATH=/data/storage_state.json \
    DOAL_OUTPUT_PATH=/data/audit_logs.ndjson \
    DOAL_STATE_PATH=/data/state.json \
    DOAL_LOCK_PATH=/data/scrape.lock
VOLUME /data
ENTRYPOINT ["do-audit"]
CMD ["scrape"]
