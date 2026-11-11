# Real evaluation workspace Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans, implementing directly in this session. The user has explicitly opted out of questions and requested execution. Do not delegate.

**Goal:** Ship a usable local evaluation workflow and prove it on read-only ai-gateway with the signed-in account and gpt-6-luna.

**Architecture:** Retain FastAPI/SQLite and React. Add a bounded local-account model transport, declarative versioned evaluation assets, isolated adapters and an incremental background runner. Keep immutable task/run evidence and separate result analysis.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Codex CLI transport, TypeScript/React/MUI, Go adapter for the example.

**Spec:** `docs/superpowers/specs/2026-11-11-real-evaluation-design.md` and `docs/PRD.md`.

## Global Constraints

- All new artifacts and state inside Evalith; ai-gateway and other projects unchanged.
- Exactly gpt-6-luna for real validation; no silent provider/model fallback or exposed login credentials.
- Desktop light/dark, project-first flow, models/executors independent.
- Unknown costs/tokens remain unknown; no passing without evidence; no automatic production writes.
- No questions and no frostloom2/delegation.

## Review Focus

- Timeouts/cancellation/process crashes retain partial results and reap owned children.
- Stale source, wrong project IDs, cross-project task/run selection fail closed.
- Task edits cannot alter historical executions; missing evidence is not a pass or a zero score.
- Output, credentials, path traversal and generated commands cannot escape the Evalith-owned environment.
- Budget exhaustion blocks later model calls; ongoing/unknown-cost work is disclosed and analysis has its own budget.

### Task 1: Local account model integration

Files: `evalith/src/evalith/codex_provider.py`, `model_gateway.py`, `service.py`, `config.py`; `evalith/tests/test_codex_provider.py`; frontend model configuration/types.

- [x] Test JSON events, actual model identity, usage, failed/timeout/login cases and process argument boundaries using a fake CLI.
- [x] Add ephemeral tools-disabled transport with explicit local runtime paths and a real connection check. Preserve credentials in the existing login store.
- [x] Integrate codex_local in the model gateway/settings and expose login availability without tokens.
- [x] Verify real gpt-6-luna inference and baseline regressions.

### Task 2: Versioned test assets and readiness

Files: new `evaluation_store.py`, `evaluation_assets.py`, API routes; `tests/test_evaluation_assets.py`.

- [x] Test readiness/stale/project boundaries, schema checks, source references, revisions and historical snapshots.
- [x] Generate categorized tasks through the configured model; persist immutable revisions and editable current assets with preparation reasons.
- [x] Add list/detail/edit/generation APIs and disclose unknown token/monetary estimates with explicit call caps. No code execution from generated content.

### Task 3: Isolated environments and incremental execution

Files: new `environments.py`, `evaluation_runner.py`, adapter modules; `tests/test_evaluation_runs.py`.

- [x] Test environment confirmation, paths/network target boundaries, execution errors, missing evidence, stop/cancel/budgets and incremental persistence.
- [x] Add owned copy/manifests and local command/HTTP adapters, explicit plan/confirm lifecycle and cleanup status.
- [x] Snapshot selected revisions, execute in a background worker, persist per-task checks/evidence/usage and terminal states.

### Task 4: Independent result analysis

Files: new `result_analysis.py`, routes; `tests/test_result_analysis.py`.

- [x] Test terminal-batch requirement, selection filters, missing-score treatment, independent budget and immutable results.
- [x] Produce sourced facts/inferences/limitations and save independent model/usage reports.

### Task 5: Complete product frontend

Files: new test-set/run/results components plus `App.tsx`, `Navigation.tsx`, `Workspace.tsx`, `types.ts`, `api.ts`, shared styles.

- [x] Add project test sets, task detail/edit/version, selected run preparation, environment disclosure, budget, incremental status/evidence and analysis screens.
- [x] Integrate generation entry from the conversation and display real failure/progress/cost states.
- [x] Verify project isolation, busy states, keyboard/dialog behavior, desktop light/dark and actual screenshots.

### Task 6: Real example, launch and delivery

Files: `examples/aigateway/`, `scripts/` launch/validation, `docs/validation/` sanitized evidence.

- [x] Build the actual ai-gateway handler only in its owned copy, with isolated storage and synthetic billing.
- [x] Run gpt-6-luna-backed generated tasks and result analysis, plus file/command and failure/missing-evidence/budget validation.
- [x] Prove original source unchanged, capture actual UI/results, document exact limitations, provide one-command start and update the PR.
- [x] Run appropriate backend/frontend checks, follow remote CI and leave the app usable.

## Delivery notes

Completed locally on 2026-11-12. macOS command isolation only; other hosts fail closed. Harbor execution remains explicitly unsupported. Source and final receipts: `docs/validation/2026-11-12-real-evaluation.md`. An earlier three-case batch passed all cases; the hardened final repeat completed with two passed and one genuine tool-use failure. No production quality or calibrated-score claim. The independent marketing-page taste checker remains GATE: ERROR; real application flows were checked with agent-browser. PR remains open, not merged.
