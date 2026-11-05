# Multi-stage harness image. Each target contains only the code that role needs, so the
# agent image never carries the verifier and the verifier image never carries the agent.

FROM python:3.13-slim AS base

# Debian slim already provides uid/gid 65534 (nobody); use it instead of adding one.
RUN mkdir -p /state /out \
    && chown 65534:65534 /state /out

USER 65534:65534
WORKDIR /app

FROM base AS agent
COPY --chmod=644 agent/agent.py /app/agent.py

FROM base AS verifier
COPY --chmod=644 verifier/verify.py /app/verify.py

FROM base AS reader
COPY --chmod=644 project_reader/read_project.py /app/read_project.py
