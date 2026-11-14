# Remove Local ChatGPT Login Provider — Implementation Plan

> Implement personally; user direction: continue development without the codex configuration.

**Goal:** Drop the codex CLI / local ChatGPT account inference channel; OpenAI-compatible stays the only real-model path.
**Architecture:** Delete the provider module and its wiring across service/gateway/config/API/UI/start script; add explicit legacy-row guards so historical data stays readable but unusable for new requests.
**Tech Stack:** Python3.12/FastAPI/SQLite, React19/MUI7/TypeScript.
**Spec:** docs/superpowers/specs/2026-11-14-remove-codex-provider-design.md

## Global constraints

- No writes outside Evalith; original ai-gateway and rhesis reference stay untouched.
- Historical runs, usage records, validation docs and existing DB rows are not rewritten.
- No real model calls in this iteration; stub/offline validation only.
- `EVALITH_ALLOW_PAID_MODELS` gate semantics unchanged.

### Task 1 — Backend provider removal with legacy guards

Files: codex_provider.py (delete), config.py, service.py, model_gateway.py, api.py, evaluation_runner.py, environments.py; tests: new test_model_provider_removal.py, test_evaluation_assets.py, test_evaluation_preparation.py (fixture updates), test_codex_provider.py (delete).

- [x] Failing tests: create rejects `codex_local` with removal message; legacy row fails requests and connection test with that message; `/api/local-model/status` is 404.
- [x] Remove provider module, settings fields/env vars, endpoint, gateway branches and runner codex-timeout clamp; keep `gateway.timeout` target clamp.
- [x] Update the two tests that simulated a real provider via `codex_local` to use `openai_compatible` with a loopback base URL.

### Task 2 — Frontend removal

Files: ModelSettings.tsx, types.ts (keep legacy union member), EvaluationLibrary.test.tsx, EvaluationWorkspace.test.tsx; new ModelSettings.test.tsx.

- [x] Failing test: add-model dialog offers no 本地 ChatGPT option; legacy config renders an 已移除 provider label.
- [x] Remove option/branch from ModelSettings; label legacy rows 已移除.

### Task 3 — Docs, script and delivery

Files: README.md, evalith/README.md, scripts/start-local.sh, docs/validation/2026-11-14-remove-codex-provider.md.

- [x] Rewrite README model sections for the OpenAI-compatible-only path; drop the ChatGPT.app codex auto-probe from the start script.
- [x] Full backend pytest, frontend tests, build, Ruff on changed modules; service restart and endpoint checks; validation doc; ledger entry; single commit on `agent/remove-chatgpt-login-provider`.
