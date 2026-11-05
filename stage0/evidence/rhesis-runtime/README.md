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

`rhesis-flow-1793859070.json` contains the full output. The per-request `llm-requests.jsonl` / `target-requests.jsonl` files are local runtime artifacts (gitignored); the target request and raw response are also embedded in the JSON result. Key points:

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

This JSON was produced before the harness verifier's claim-diagnostic refactor. The
verdicts are unchanged: the failed case already failed the state checks, and the
missing-evidence case had a matching claim. The harness evidence
(`stage0/evidence/runs/20261105T065055Z-summary.json`) is the post-fix evidence for the
claim behavior.

## IDs from the run

```text
project_id    716c59a6-be63-46f6-aeb3-483f608fd69f
model_id      de8eda55-b13c-444e-b80a-77b0e2f9bb6a
endpoint_id   0bd7924f-ce95-441c-b214-976fb84684d0
architect     670518df-fe84-4441-ab0c-de2303d331f1
run pass      d21d64b1-efcd-4d4f-812a-2ac4dcc76484
run fail      ff765c15-5273-4bec-b75a-127a52ad6c89
run missing   6fd0a4f9-890d-4623-a264-39816660881c
```

## Reproduction and limits

- Commands: [stage0/rhesis-flow/README.md](../../rhesis-flow/README.md).
- The test state is reset from the host between cases; Rhesis itself does **not**
  reset an endpoint or create an isolated environment. This external reset is a
  limitation, not a Rhesis feature.
- The frontend and WebSocket live update were not exercised.
- The run does not prove real model behaviour, cancellation, budget enforcement, or
  cleanup of a real environment.
