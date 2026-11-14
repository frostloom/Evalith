# Grader Calibration — Implementation Plan

> Implement personally; continuation of the established cadence (spec → RED tests → implementation → validation → review → merge).

**Goal:** Known-outcome sample calibration for judge graders, recorded immutably, driving `calibration_state`.
**Architecture:** New evaluation_calibration.py service reusing grader_check compilation, the runner's judge prompt (extracted to a shared constant) and the job-record/thread pattern from generation; store kind `calibration`.
**Tech Stack:** Python3.12/FastAPI/SQLite/Pydantic, React19/MUI7/TypeScript.
**Spec:** docs/superpowers/specs/2026-11-14-grader-calibration-design.md

## Global constraints

- No writes outside Evalith; original ai-gateway and rhesis reference untouched.
- No target execution, no environment changes, no auto-confirmation of unknowns, no rewriting of history.
- Exact runtime judge semantics: same criteria, prompt, evidence-quote validation, threshold; stub cannot calibrate.

### Task 1 — Backend calibration service, state transitions and API

Files: evaluation_calibration.py (new), evaluation_runner.py (extract JUDGE_SYSTEM_PROMPT), evaluation_library.py (edit resets calibration_state), evaluation_api.py (routes); tests: test_evaluation_calibration.py (new).

- [x] Failing tests: matched samples set calibrated, mismatch sets disagreement with details; unquoted evidence is missing_evidence; deterministic grader and model-less grader reject; concurrent job rejects; mid-job edit marks report stale without state change; edit resets state; stub rejects.
- [x] Implement CalibrationSpec validation, async job execution, immutable report records, stale guard, routes POST/GET.

### Task 2 — Frontend calibration panel

Files: evaluationTypes.ts, evaluationApi.ts, EvaluationLibraryPage.tsx; tests: EvaluationLibrary.test.tsx.

- [x] Failing test: grader card badge reflects state (已校准/校准不一致/未校准); detail view exposes 校准 action.
- [x] Sample editor + model selector + job progress + latest report + history in the grader detail drawer.

### Task 3 — Docs, validation, review, merge

Files: evalith/README.md, docs/validation/2026-11-14-grader-calibration.md.

- [x] README usage note; full backend pytest + frontend tests + build + Ruff; live service check; validation doc; ledger; two-axis review; fix findings; merge to main and push.
