# Rhesis source-build attempt (stage 0)

Date: 2026-11-05. Source baseline: `ce24bb1993fc545bb0ccb0d8b3951683ac14fff1` (`VERSION` 0.20.1).

## What completed

`docker compose ... build backend worker beat` built the Python environments and the
`build-backend` stages from the frozen checkout:

```text
#47 [worker build-backend 6/7] RUN uv sync --extra all --extra cpu --extra ee --no-install-package torch
#47 284.6 Prepared 360 packages in 4m 40s
#47 352.4 Installed 360 packages in 1m 07s
#47 DONE 417.9s
#49 [worker build-backend 7/7] COPY apps/backend/src ./src
#49 DONE 11.4s
```

The first full build (including frontend) also completed `npm install` for the
frontend, then stalled at `COPY --from=deps ... node_modules` for several minutes. It
was stopped to free Docker capacity.

## What stalled

The backend/worker runtime stage:

```text
#35 [worker base-runtime 6/14] COPY --from=build-backend --chown=rhesis-user:rhesis-user /app/apps/backend/.venv .venv
```

remained at this step for several minutes with no log or cache growth, under Docker
Desktop 4.95.0 on macOS arm64. It was stopped after the build cache had already grown
to ~10 GB. A retry hit the same step.

## Fallback used for runtime evidence

The runtime flow used the published 0.20.1 images and replaced the only two files that
differ from the frozen commit with the frozen versions via read-only bind mounts:

```text
ghcr.io/rhesis-ai/backend@sha256:9fb3fa0c3d9a24232de3686062f4fbb38ba94b2db3aa6fc1abb09e1b1620cd08
ghcr.io/rhesis-ai/worker@sha256:cafe6e840d16bf251788b8fefd73c5bb70e4c359511e9cf7e182768572367272
```

Diff (published image vs frozen source; both paths under
`apps/backend/src/rhesis/backend/app/services/invokers/`):

```text
common/connection_errors.py   a519c594... (image) vs b9f5fa21... (frozen)
rest_invoker.py               d0641ad3... (image) vs c1f527e3... (frozen)
```

The two files affect TLS timeout error classification, not the project/test/run paths.
Their frozen hashes were confirmed inside both running containers. The images also
contain `ee/` because the upstream Dockerfile copies it; this run is local-only and
must not be published.

## Reproduce

```bash
cd <rhesis checkout>
BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose \
  -f docker-compose.yml -f <local override> --env-file <local env> \
  -p rhesis-stage0 build backend worker beat
```

If the runtime `.venv` copy stalls on Docker Desktop, prefer a Linux builder or a
pre-built runtime image; do not use the published image as the final Evalith artifact.
