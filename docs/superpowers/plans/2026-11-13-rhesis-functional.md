# Rhesis Functional Alignment Implementation Plan

> Implement personally with executing-plans; user opted out of questions and delegation.

**Goal:** Natural-language preparation produces executable linked evaluation assets, with real grader resolution and preflight.
**Architecture:** Reuse FastAPI/SQLite/model gateway and existing runner. Add a focused preparation service, atomic store insertion and grading-plan builder; wire existing controls to them.
**Tech Stack:** Python3.12, SQLite, React19/MUI7/TypeScript.
**Spec:** docs/superpowers/specs/2026-11-13-rhesis-functional-design.md

## Global constraints

- No writes to ai-gateway or reference rhesis; all artifacts in Evalith. No delegation, no questions, no merge.
- Real model gpt-6-luna only. Preparation does not authorize execution or calibrate graders.
- Preserve legacy task generation, runs, budgets, environment confirmation and missing-evidence semantics.

## Review focus

- Invalid references, duplicate standard names and invalid generated assets must leave no partial records.
- Source changes during inference reject persistence; supplied model IDs cannot redirect generation to another provider.
- Different task defaults must not leak graders into other tasks; explicit empty override has distinct semantics.
- Scope filtering never turns no applicable graders into a passing result; archived/foreign defaults reject before calls.
- Preview has no execution/model side effects and actual start rebuilds/fixes its own snapshot.

### Task 1 — Atomic structured asset and grader synthesis

Files: evaluation_preparation.py (new), evaluation_store.py, evaluation_assets.py, evaluation_library.py, evaluation_api.py; test_evaluation_preparation.py (new).

- [x] Write/run failing tests for linked assets, invalid reference/source and DB rollback.
- [x] Add validated structured preparation, natural-language grader draft, atomic insertion and background preparation API/jobs.
- [x] Preserve task grader bindings across revisions and avoid duplicate projected collections.
- [x] Focused tests, relevant existing asset/library regressions.

### Task 2 — Per-task resolution and preflight

Files: grading_plan.py (new), evaluation_runner.py, evaluation_api.py, test_grading_plan.py (new).

- [x] Write/run failing tests for precedence, scope, no-applicable, archive/foreign isolation and snapshot preservation.
- [x] Same plan builder for preview/start; freeze actual checks per version, all models and default bindings.
- [x] Runner evaluates frozen checks and preserves old-run fallback.
- [x] Focused runner/budget regressions.

### Task 3 — Existing entry points and real validation

Files: EvaluationDialogs.tsx, EvaluationLibraryPage.tsx, evaluationApi.ts, evaluationTypes.ts, Workspace/App handlers; relevant interaction tests.

- [x] Wire preparation and natural-language grader draft to existing controls, with preview before run; no restyling.
- [x] Run backend/frontend/build/static checks; real generated assets → preflight → gpt-6-luna evaluation.
- [x] Verify source protection, document functional gaps honestly, restart service and update original PR without merge.
