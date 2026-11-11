# EE-free Rhesis workbench

This directory builds a reproducible, EE-free workbench tree from the Rhesis
baseline pinned in `pin.json`:

- repository: `https://github.com/rhesis-ai/rhesis`
- commit: `ce24bb1993fc545bb0ccb0d8b3951683ac14fff1`
- version: `0.20.1`
- license: MIT core; the non-MIT `/ee/` directory is deleted, not disabled

The generated tree lives in `workbench/.workbench/ee-free/` and is not
committed. `build.py` exports the pinned commit's **committed objects** with
`git archive` (never the mutable working tree), applies 30+ asserted patches
(EE removal, brand removal, legal imprint, telemetry/SaaS defaults, unlicensed
fonts), regenerates the dependency locks, and verifies that no EE package,
brand artwork or unlicensed font family remains. The full change list and
whether the source checkout was dirty are written to
`.workbench/ee-free/BUILD_INFO.json`.

Committed reproducibility inputs:

- `workbench/locks/backend-uv.lock` and `workbench/locks/frontend-package-lock.json`
- `workbench/locks/tools.json` records their SHA-256 hashes and the Python, uv, Node and npm versions used for the recorded build/smoke run. `BUILD_INFO.json` records the same hashes and versions.

No published Rhesis image is used: the official images contain `/ee/` and must
not be redistributed as Evalith artifacts.

## Build

```bash
python3 workbench/build.py --source /absolute/path/to/rhesis
```

Without `--source`, the builder clones the pinned commit into
`workbench/.workbench/src`. The source checkout must be at the pinned commit;
the builder refuses anything else.

Then install dependencies from the generated tree:

```bash
cd workbench/.workbench/ee-free/apps/backend
uv sync --frozen --extra all --extra cpu --no-install-package torch --no-dev

cd ../frontend
npm ci
NEXT_TELEMETRY_DISABLED=1 npm run build
```

## Run (host processes, Docker only for PostgreSQL/Redis)

```bash
workbench/run_local.sh
```

This generates `workbench/.workbench/rhesis.env` with disposable local secrets,
starts PostgreSQL/Redis from `compose.deps.yaml`, runs migrations, and starts
the backend on `127.0.0.1:8080` and the frontend on `127.0.0.1:3000`
(`npm start -- --hostname 127.0.0.1`; Next's default listener is not loopback-only).
The backend image sets the same telemetry/platform-key/connector disables as the
host launcher. It sets:

```text
QUICK_START=true
OTEL_RHESIS_TELEMETRY_ENABLED=false
OTEL_SDK_DISABLED=true
ENABLE_RHESIS_KEY=false
RHESIS_CONNECTOR_DISABLED=true
```

Stop with `workbench/stop_local.sh` (add `--volumes` to remove the disposable
database and Redis volume).

## Smoke test

```bash
python3 workbench/smoke.py
```

The smoke script logs in through quick start, reads the community feature
report, creates and reads a project, creates a model and tests its connection
against a deterministic local OpenAI-compatible stub, creates an Architect
session with an initial message, waits for the worker to persist and return the
assistant turn, fetches the frontend, and checks the generated artifact for EE
residue. `run_local.sh` starts a solo-pool Celery architect worker so the
session message/worker path is exercised; the model is still the deterministic
stub. Evidence is written to
`docs/stage1/evidence/workbench-smoke-<timestamp>.json`.

Limits: no real model and no real business data. The Architect session
message/worker path is exercised against the deterministic stub, not a real
model; real-model quality and container project access remain unverified.

## Optional container images

`docker/backend.Dockerfile` and `docker/frontend.Dockerfile` build only from the
generated EE-free tree and copy `LICENSE`, `NOTICE` and
`THIRD_PARTY_NOTICES.md` into the images. They are provided for the next phase's
image pipeline; the stage-1 verification run uses the host build recorded in
`docs/stage1/阶段1-交付说明.md`.
