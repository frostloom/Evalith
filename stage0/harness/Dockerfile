FROM python:3.13-slim

# The harness has no third-party dependencies. A single image is used for the
# agent, verifier and reader; the runner selects the entrypoint by service.
COPY agent/agent.py /app/agent.py
COPY verifier/verify.py /app/verify.py
COPY project_reader/read_project.py /app/read_project.py

# Debian slim already provides uid/gid 65534 (nobody); use it instead of adding one.
RUN chmod 0644 /app/*.py \
    && mkdir -p /state /out \
    && chown 65534:65534 /state /out

USER 65534:65534
WORKDIR /app
