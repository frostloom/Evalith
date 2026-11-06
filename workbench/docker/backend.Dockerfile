# EE-free Evalith workbench backend. Build context is the generated tree
# (workbench/.workbench/ee-free), not the upstream checkout.
#
# Single stage on purpose: the upstream multi-stage Dockerfile copies a large
# .venv between stages and stalled on Docker Desktop in stage 0. This image
# installs only the EE-free tree and never copies `/ee/`.
FROM mirror.gcr.io/library/python:3.12.8-slim

COPY --from=mirror.gcr.io/astral/uv:0.11.19 /uv /bin/uv

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential libpq-dev curl git git-lfs \
    && rm -rf /var/lib/apt/lists/*

COPY LICENSE NOTICE THIRD_PARTY_NOTICES.md /app/

COPY sdk /app/sdk
COPY skills /app/skills
COPY penelope /app/penelope
COPY packages /app/packages
COPY apps/backend /app/apps/backend

WORKDIR /app/apps/backend

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_MANAGED_PYTHON=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/backend/src \
    PATH="/app/apps/backend/.venv/bin:$PATH" \
    OTEL_RHESIS_TELEMETRY_ENABLED=false \
    OTEL_SDK_DISABLED=true \
    ENABLE_RHESIS_KEY=false \
    RHESIS_CONNECTOR_DISABLED=true

RUN uv sync --extra all --extra cpu --no-install-package torch

RUN adduser --disabled-password --gecos '' evalith && \
    mkdir -p /app/storage && \
    chown -R evalith:evalith /app/storage /app/apps/backend

COPY --chown=evalith:evalith LICENSE NOTICE THIRD_PARTY_NOTICES.md /app/

USER evalith

EXPOSE 8080

CMD ["sh", "-c", "cd /app/apps/backend/src/rhesis/backend && alembic upgrade head && cd /app/apps/backend && python -m uvicorn rhesis.backend.app.main:app --host 0.0.0.0 --port 8080"]
