# Rhesis runtime check (stage 0)

This flow starts a Rhesis stack from the frozen source commit, points its model
provider at a deterministic OpenAI-compatible stub, creates a synthetic project and
test, runs it against a synthetic non-conversation target, and checks the final state
independently.

**It does not call a real model and does not use business data.** Rhesis' metric
evaluation uses `NumericJudge` backed by the stub, which always returns 1.0. That is
deliberate: the run shows that a metric pass is not the same as an independent state
check.

## Prerequisites

- Rhesis checkout at `ce24bb1993fc545bb0ccb0d8b3951683ac14fff1` (`VERSION` 0.20.1).
  The ticket does not vendor the source.
- Docker (the stack needs PostgreSQL, Redis, backend, worker, beat, frontend).
- Python 3.12+ on the host.
- Free ports 8080 (backend) and 3000 (frontend), or a local override.

## 1. Build and start Rhesis from source

Create a local env file with generated secrets. Do not commit it:

```bash
cd <rhesis checkout>
cp .env.example .env.docker.local
python3 - <<'PY'
import secrets, pathlib
p = pathlib.Path('.env.docker.local')
s = p.read_text()
s = s.replace('DB_ENCRYPTION_KEY=', 'DB_ENCRYPTION_KEY=' + secrets.token_urlsafe(32), 1)
# .env.example may use placeholders; set the other required secrets explicitly:
for key in ('JWT_SECRET_KEY', 'SESSION_SECRET_KEY', 'NEXTAUTH_SECRET'):
    s = s.replace(key + '=', key + '=' + secrets.token_hex(32), 1)
p.write_text(s)
PY
# Append the quick-start flags if the template does not already have them:
printf '\nQUICK_START=true\nBACKEND_PORT=8080\nFRONTEND_PORT=3000\nAPI_BASE_URL=http://localhost:8080\nFRONTEND_URL=http://localhost:3000\nOTEL_RHESIS_TELEMETRY_ENABLED=false\nENABLE_RHESIS_KEY=false\nRHESIS_SKIP_GARAK_WARM_CACHE=true\n' >> .env.docker.local
```

Build the images **from this checkout** (do not use the published images; they are not
the frozen commit and contain EE code):

```bash
BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose \
  -f docker-compose.yml \
  --env-file .env.docker.local -p rhesis-stage0 build backend worker beat frontend
```

Start the services:

```bash
docker compose -f docker-compose.yml --env-file .env.docker.local \
  -p rhesis-stage0 up -d postgres redis backend worker beat frontend
```

`RHESIS_SKIP_GARAK_WARM_CACHE=true` is a local convenience: without it the backend
spends several CPU-bound minutes enumerating Garak probes on first startup. It does not
change the test execution path.

Wait for the backend and worker health checks:

```bash
docker compose -f docker-compose.yml --env-file .env.docker.local \
  -p rhesis-stage0 ps
curl -fsS http://127.0.0.1:8080/health
```

## 2. Start the deterministic stub services

From this repository root:

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

## 3. Run the flow

```bash
python3 stage0/rhesis-flow/seed.py --base-url http://127.0.0.1:8080
```

It authenticates through `QUICK_START` (`/auth/local-login` + `/auth/exchange-code`),
creates a model, tests the connection, sets the user's default generation/evaluation/
execution models, creates a project, endpoint, test set, test, metric, and executes the
test. It repeats for three synthetic cases:

| Case | Rhesis stub metric | Independent verifier | Meaning |
| --- | --- | --- | --- |
| pass | pass | passed | correct release + audit |
| fail | pass | failed | contributor approval released the artifact; the stub judge cannot see state |
| missing_evidence | pass | unverified | release happened but audit evidence is missing |

The result JSON is written to `stage0/evidence/rhesis-runtime/rhesis-flow-<epoch>.json`.
`all_external_ok: true` means the independent verifier's expectation was met for every
case; it does not mean Rhesis' own verdict was correct for the fail case.

## 4. Stop and clean up

```bash
docker rm -f stage0-stub
cd <rhesis checkout>
docker compose -f docker-compose.yml --env-file .env.docker.local \
  -p rhesis-stage0 down -v
```

This deletes the disposable stack and its volumes. Do not run it against a stack whose
database or storage you need.

## Notes and limitations

- The model and target are stubs. The run validates interfaces and the Rhesis result
  pipeline, not model capability or business correctness.
- The Rhesis execution path does not create/reset environments. Both the endpoint and
  its state are shared across tests; the flow resets the stub's state between cases
  from the host. This is a recorded limitation, not a feature.
- The frontend is optional for this flow and was not started in the recorded run; the verification is API-level. The source-build frontend layer stalled under Docker Desktop.
- The Rhesis image built here includes `ee/` because the upstream Dockerfile copies it.
  That build is local-only and must not be published. Stage 1 needs an EE-free build.
- No real credentials, business data, or external side effects are used.
