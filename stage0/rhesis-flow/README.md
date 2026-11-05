# Rhesis runtime check (stage 0)

This flow starts a Rhesis stack, points its model provider at a deterministic
OpenAI-compatible stub, creates a synthetic project and test, runs it against a synthetic
non-conversation target, and checks the final state independently.

**It does not call a real model and does not use business data.** Rhesis' metric
evaluation uses `NumericJudge` backed by the stub, which always returns 1.0. That is
deliberate: the run shows that a metric pass is not the same as an independent state
check.

There are two startup paths:

1. **Recorded runtime (recommended for reproducing the committed evidence).** Published
   Rhesis 0.20.1 images plus a sanitized override that mounts the two files differing
   from the frozen checkout. This is what produced
   `stage0/evidence/rhesis-runtime/rhesis-flow-1793869085.json`.
2. **Full source build (preferred for a final product build, if the host can finish it).**
   Build backend/worker/beat/frontend from the frozen checkout. On this machine the
   backend/worker runtime `.venv` copy stalled under Docker Desktop, so it was not the
   path used for the recorded evidence.

## Prerequisites

- Rhesis checkout at `ce24bb1993fc545bb0ccb0d8b3951683ac14fff1` (`VERSION` 0.20.1).
  The ticket does not vendor the source.
- Docker; the stack needs PostgreSQL, Redis, backend, worker and beat. The frontend is
  optional for the API-level flow.
- Python 3.12+ on the host.
- Free port 8080 for the backend (the frontend port 3000 is only needed if started).

## 1. Create the local env file

Create a local env file with generated secrets. Do not commit it:

```bash
cd "$RHESIS_SRC"
cp .env.example .env.docker.local
python3 - <<'PY'
import secrets, pathlib
p = pathlib.Path('.env.docker.local')
s = p.read_text()
s = s.replace('DB_ENCRYPTION_KEY=', 'DB_ENCRYPTION_KEY=' + secrets.token_urlsafe(32), 1)
for key in ('JWT_SECRET_KEY', 'SESSION_SECRET_KEY', 'NEXTAUTH_SECRET'):
    s = s.replace(key + '=', key + '=' + secrets.token_hex(32), 1)
p.write_text(s)
PY
cat >> .env.docker.local <<'EOF'
QUICK_START=true
BACKEND_PORT=8080
FRONTEND_PORT=3000
API_BASE_URL=http://localhost:8080
FRONTEND_URL=http://localhost:3000
OTEL_RHESIS_TELEMETRY_ENABLED=false
ENABLE_RHESIS_KEY=false
RHESIS_SKIP_GARAK_WARM_CACHE=true
EOF
```

`RHESIS_SKIP_GARAK_WARM_CACHE=true` is a local convenience: without it the backend
spends several CPU-bound minutes enumerating Garak probes on first startup. It does not
change the test execution path.

## 2. Start the stack

### 2.1 Recorded runtime: published images + frozen-file mounts

The override is [compose.stage0.yaml](compose.stage0.yaml). It pins the backend,
worker, beat and frontend images to the recorded digests, binds the two Python files that
differ between the published 0.20.1 image and the frozen commit, keeps the backend on
localhost, and sets the local runtime flags. Image digests are recorded in
[`stage0/evidence/rhesis-runtime/README.md`](../evidence/rhesis-runtime/README.md).

From the Evalith repository root:

```bash
export RHESIS_SRC=/absolute/path/to/rhesis
docker compose \
  -f "$RHESIS_SRC/docker-compose.yml" \
  -f "$RHESIS_SRC/docker-compose.ghcr.yml" \
  -f "$PWD/stage0/rhesis-flow/compose.stage0.yaml" \
  --env-file "$RHESIS_SRC/.env.docker.local" \
  -p rhesis-stage0 up -d postgres redis backend worker beat
```

The exact recorded image digests were:

```text
ghcr.io/rhesis-ai/backend@sha256:9fb3fa0c3d9a24232de3686062f4fbb38ba94b2db3aa6fc1abb09e1b1620cd08
ghcr.io/rhesis-ai/worker@sha256:cafe6e840d16bf251788b8fefd73c5bb70e4c359511e9cf7e182768572367272
```

The two mounted files and their frozen hashes are:

```text
apps/backend/src/rhesis/backend/app/services/invokers/common/connection_errors.py
  b9f5fa214e9fd354be57fda82a2aa28b2ea9cd63837c8d8a5bd38f692cc6ab07
apps/backend/src/rhesis/backend/app/services/invokers/rest_invoker.py
  c1f527e3b222f64ca9124154003a69903c0c135fb8061e99140a1cf34f2f5fdb
```

The published image is from the parent commit and differs only in those two files; the
images still contain `ee/` because the upstream Dockerfile copies it. This run is
local-only and must not be published.

### 2.2 Alternative: full source build

Build the images **from the frozen checkout**; do not use the published images for a
final Evalith artifact:

```bash
cd "$RHESIS_SRC"
BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose \
  -f docker-compose.yml \
  --env-file .env.docker.local -p rhesis-stage0 build backend worker beat frontend

docker compose -f docker-compose.yml --env-file .env.docker.local \
  -p rhesis-stage0 up -d postgres redis backend worker beat frontend
```

If the backend/worker runtime `.venv` copy stalls (as it did here), use a Linux builder
or a prebuilt runtime image; see
[`docs/stage0/evidence/source-build-attempt.md`](../../docs/stage0/evidence/source-build-attempt.md).

### 2.3 Health check

```bash
docker compose \
  -f "$RHESIS_SRC/docker-compose.yml" \
  -f "$RHESIS_SRC/docker-compose.ghcr.yml" \
  -f "$PWD/stage0/rhesis-flow/compose.stage0.yaml" \
  --env-file "$RHESIS_SRC/.env.docker.local" \
  -p rhesis-stage0 ps
curl -fsS http://127.0.0.1:8080/health
```

## 3. Start the deterministic stub services

From the Evalith repository root:

```bash
docker build -t stage0-stub:local stage0/rhesis-flow
mkdir -p "$PWD/stage0/evidence/rhesis-runtime"
docker run -d --name stage0-stub \
  --network rhesis-stage0_rhesis-network \
  -v "$PWD/stage0/evidence/rhesis-runtime:/data" \
  stage0-stub:local
```

The compose project network name depends on the compose file (the Rhesis compose file
declares `rhesis-network`, so the network is usually named
`rhesis-stage0_rhesis-network`; inspect `docker network ls` and use the actual name).
The backend/worker must be able to resolve `stage0-stub` on that network.

The stub exposes:

- `stage0-stub:18081` — OpenAI-compatible model endpoint (connection test, AgentAction,
  NumericScoreResponse);
- `stage0-stub:18082` — synthetic target endpoint (`POST /invoke`), which applies a
  deliberately naive release transition to `/data/target-state.json`.

## 4. Run the flow

```bash
python3 stage0/rhesis-flow/seed.py --base-url http://127.0.0.1:8080
```

It authenticates through `QUICK_START` (`/auth/local-login` + `/auth/exchange-code`),
creates a model, tests the connection, sets the user's default generation/evaluation/
execution models, creates a project, endpoint, test set, test, metric, and executes the
test. It repeats for three synthetic cases:

| Case | Rhesis stub metric | Independent verifier | Meaning |
| --- | --- | --- | --- |
| pass | pass | passed | correct release + audit + untouched snapshot |
| fail | pass | failed | contributor approval released the artifact; the stub judge cannot see state |
| missing_evidence | pass | unverified | release happened but audit evidence is missing |

The result JSON is written to `stage0/evidence/rhesis-runtime/rhesis-flow-<epoch>.json`.
`all_external_ok: true` requires each scenario to reach `Completed` with one `ok`
result, the verifier's exit code to match its verdict, and the independent expectation
to be met. A polling timeout is recorded explicitly; the flow requests cancellation,
waits for a terminal status, and aborts later scenarios before any shared-state reset.
The committed run did not trigger a timeout, so this branch remains runtime-unverified.
It still does not mean Rhesis' own verdict was correct for the fail case.

## 5. Stop and clean up

```bash
docker rm -f stage0-stub
cd "$RHESIS_SRC"
docker compose \
  -f docker-compose.yml \
  -f docker-compose.ghcr.yml \
  -f <evalith checkout>/stage0/rhesis-flow/compose.stage0.yaml \
  --env-file .env.docker.local -p rhesis-stage0 down -v
```

This deletes the disposable stack and its volumes. Do not run it against a stack whose
database or storage you need.

## Notes and limitations

- The model and target are stubs. The run validates interfaces and the Rhesis result
  pipeline, not model capability or business correctness.
- The Rhesis execution path does not create/reset environments. Both the endpoint and
  its state are shared across tests; the flow resets the stub's state between cases
  from the host. This is a recorded limitation, not a feature.
- The frontend was not started in the recorded run; the verification is API-level.
- The published images contain `ee/`; this run is local-only and must not be published.
- No real credentials, business data, or external side effects are used.
