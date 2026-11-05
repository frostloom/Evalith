# Rhesis runtime evidence (stage 0)

Status: API-level runtime flow completed on the local stack. The model and target are
deterministic stubs; this is interface evidence, not model-capability evidence.

## What was run

- Rhesis source baseline: `ce24bb1993fc545bb0ccb0d8b3951683ac14fff1` (`VERSION` 0.20.1).
- Stack: PostgreSQL, Redis, backend, worker, beat. The frontend was **not** started
  because the source-build frontend layer stalled and the flow is API-level.
- Runtime images: the published `ghcr.io/rhesis-ai/backend` / `worker` 0.20.1 images
  (digests below), **not** a complete source build. A source build of backend/worker
  was attempted; the final runtime layer (copying the multi-GB `.venv`) stalled under
  Docker Desktop and was abandoned after the cache had already built the Python venv.
- The two Python files that differ between the published image and the frozen commit
  were bind-mounted from the frozen checkout into backend and worker, so the executed
  invoker code matches the baseline. Hashes:
  - `connection_errors.py`: `b9f5fa214e9fd354be57fda82a2aa28b2ea9cd63837c8d8a5bd38f692cc6ab07`
  - `rest_invoker.py`: `c1f527e3b222f64ca9124154003a69903c0c135fb8061e99140a1cf34f2f5fdb`
- Source/image comparison: 943/945 backend Python files identical; the 2 files above
  differ because the published image was built from the parent commit (a TLS timeout
  classification fix). See the main report §2.
- `RHESIS_SKIP_GARAK_WARM_CACHE=true` was set for the local run to avoid a long
  CPU-bound Garak probe cache enumeration that blocked API latency.
- `QUICK_START=true`; telemetry disabled; ports bound to 127.0.0.1.

## Exact startup configuration

The sanitized override is `stage0/rhesis-flow/compose.stage0.yaml`. It pins the
backend/worker/beat/frontend image digests, overrides the backend port to `127.0.0.1:8080`, disables the Rhesis platform key and telemetry, skips
the Garak warm cache, and mounts the two frozen files at their container paths:

```text
${RHESIS_SRC}/apps/backend/src/rhesis/backend/app/services/invokers/common/connection_errors.py
  -> /app/apps/backend/src/rhesis/backend/app/services/invokers/common/connection_errors.py:ro
${RHESIS_SRC}/apps/backend/src/rhesis/backend/app/services/invokers/rest_invoker.py
  -> /app/apps/backend/src/rhesis/backend/app/services/invokers/rest_invoker.py:ro
```

Recorded service selection and command (run from the Evalith repository root):

```bash
export RHESIS_SRC=/absolute/path/to/rhesis
docker compose \
  -f "$RHESIS_SRC/docker-compose.yml" \
  -f "$RHESIS_SRC/docker-compose.ghcr.yml" \
  -f "$PWD/stage0/rhesis-flow/compose.stage0.yaml" \
  --env-file "$RHESIS_SRC/.env.docker.local" \
  -p rhesis-stage0 up -d postgres redis backend worker beat
```

The frontend is not part of the recorded run. `RHESIS_SRC` is the only path variable;
the override contains no personal absolute paths.

## Image digests

```text
ghcr.io/rhesis-ai/backend@sha256:9fb3fa0c3d9a24232de3686062f4fbb38ba94b2db3aa6fc1abb09e1b1620cd08
ghcr.io/rhesis-ai/worker@sha256:cafe6e840d16bf251788b8fefd73c5bb70e4c359511e9cf7e182768572367272
```

The images self-report `VERSION=0.20.1`; they are not byte-identical to the frozen
commit (see above). They contain `ee/` because the upstream Dockerfile copies it; the
run is local-only and must not be published.

## Stub endpoints

- `stage0-stub:18081` — deterministic OpenAI-compatible model. It returns `OK` for a
  plain call, and schema-shaped JSON for `AgentAction` and `NumericScoreResponse`.
- `stage0-stub:18082` — synthetic non-conversation target. It accepts
  `{input, test_parameters, files}` and applies the naive release transition to
  `target-state.json`.
- Stub image: `stage0-stub:local`, built from `stage0/rhesis-flow/Dockerfile`.

No real model, credential, external service, or business data was used.

## Observed results

`rhesis-flow-1793867196.json` contains the full output. The per-request `llm-requests.jsonl` / `target-requests.jsonl` files are local runtime artifacts (gitignored); the target request and raw response are also embedded in the JSON result. Key points:

| Check | Result |
| --- | --- |
| Model connection test (`litellm_proxy` -> stub) | success |
| Project / endpoint / test set / test / metric creation | success |
| Architect session create -> Celery task -> 68 tools -> `AgentAction` -> assistant message persisted | success (assistant text is the stub's short `OK`; the AgentAction call is in `llm-requests.jsonl`) |
| Single-turn run against the synthetic target | Completed, execution `ok`, verdict `pass` |
| `test_parameters` forwarded to target | observed in the target request embedded in the result JSON |
| Independent verifier vs Rhesis verdict | pass/pass, fail/**pass**, unverified/**pass** |

The last row is the key finding: Rhesis' stub metric says pass for a contributor
release that violates the synthetic policy, and for a release with no audit evidence.
The independent verifier says failed and unverified respectively. A metric pass is not
a state check.

This run uses the current shared verifier without `--require-hidden-access` (the
Rhesis flow has no agent container to probe), and supplies the initial doc-18 snapshot
for the complete untouched-artifact comparison. Each invocation writes a fresh verdict
file and requires the verifier exit code to match its verdict (0/2/3); a crashed
verifier cannot be mistaken for a previous result. A run polling timeout is explicit:
the flow requests cancellation, waits for a terminal status, and aborts later scenarios
before any shared-state reset. `all_external_ok` requires `Completed` execution and
one `ok` result per scenario, not just an external verdict. The pass case therefore returns
`passed`; the fail and missing-evidence cases still return `failed` / `unverified`. The
harness evidence (`stage0/evidence/runs/20261105T081350Z-summary.json`) is the
isolation-flagged counterpart.

## IDs from the run

```text
project_id    54bdd70d-9510-429a-ac4b-6536f5627a19
model_id      74625e49-8364-4068-ade4-423b927966a1
endpoint_id   fca17842-31c3-4327-9c65-e0869a876c90
architect     7eb4f726-5fda-49fa-8bae-aebaff10aaec
run pass      14fa0ebd-2b68-4255-ae4c-682e0e52bede
run fail      3ff09a43-15f9-4ea0-86a1-540cc620c930
run missing   a0ba80ec-0c6f-421a-8e1f-0e8c246f7345
```

## Reproduction and limits

- Commands: [stage0/rhesis-flow/README.md](../../rhesis-flow/README.md).
- The test state is reset from the host between cases; Rhesis itself does **not**
  reset an endpoint or create an isolated environment. This external reset is a
  limitation, not a Rhesis feature.
- The frontend and WebSocket live update were not exercised.
- The run does not prove real model behaviour, cancellation, budget enforcement, or
  cleanup of a real environment.
