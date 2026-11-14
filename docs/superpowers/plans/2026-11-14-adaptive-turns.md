# Adaptive Multi-Turn — Implementation Plan

> Implement personally; continuation of the established cadence (spec → RED tests → implementation → validation → review → merge).

**Goal:** Conversation tasks whose follow-up user turns are generated during execution from the live transcript, budgeted and recorded like every other model call.
**Architecture:** TaskSpec gains `input.adaptive`; the runner resolves a `simulator` model role per run; a token-protected simulator endpoint serves next-turn decisions through `model_call`; the Evalith-owned Go adapter drives the loop against the real Handler.
**Tech Stack:** Python3.12/FastAPI/SQLite/Pydantic, Go adapter (Evalith-owned), React19/MUI7/TypeScript.
**Spec:** docs/superpowers/specs/2026-11-14-adaptive-turns-design.md

## Global constraints

- Original ai-gateway and rhesis untouched; only `examples/aigateway/adapter.go` (Evalith-owned) changes.
- Scripted multi-turn behavior unchanged; adaptive is additive and rejected where unsupported.
- Every simulator call goes through `model_call` (budget, fingerprint, usage); cap enforced server-side; failures visible.

### Task 1 — Definition, run planning and simulator endpoint

Files: evaluation_assets.py (TaskSpec), evaluation_runner.py (role + env + endpoint), evaluation_api.py (route); tests: test_adaptive_turns.py (new), test_evaluation_runs.py.

- [x] Failing tests: adaptive validation (single opening turn, 2–12 max, instruction bounds, unknown fields); preflight rejects non-bridge executor, stub simulator, conflicting simulator models; simulator role resolved by payload > task > judge and snapshotted; endpoint auth 403, cap returns end without a call, happy path records usage, malformed reply fails visibly; execute_task passes `EVALITH_SIMULATOR_URL` only for adaptive tasks.
- [x] Implement TaskSpec adaptive input, `_plan` simulator resolution and rejections, `simulator` endpoint with SIMULATOR_SYSTEM_PROMPT, env wiring.

### Task 2 — Go adapter interactive loop

Files: examples/aigateway/adapter.go.

- [x] Accept `adaptive {max_turns, instruction}`; require simulator URL/token; after each reply below the cap, POST the transcript and follow `{"message","end"}`; stop on end/error/cap with visible status; scripted path untouched; document re-prepare requirement.

### Task 3 — Frontend, docs and delivery

Files: EvaluationDialogs.tsx, EvaluationDialogs/EvaluationWorkspace tests, evalith/README.md, docs/validation/2026-11-14-adaptive-turns.md.

- [x] Adaptive section in the conversation task form (opening turn locked to 1, max turns, instruction, simulator model select); frontend test.
- [x] README note; full backend pytest + frontend tests + build + Ruff; adapter compiles (Go build via environment prepare or `go build`); validation doc; ledger; two-axis review; fix findings; merge to main and push.
