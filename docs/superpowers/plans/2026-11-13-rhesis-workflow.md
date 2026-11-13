# Rhesis workflow implementation plan

> Implement personally using executing-plans. User has opted out of questions and delegation.

**Goal:** Replace the improvised evaluation UI with Rhesis-informed assets, configuration and result interactions.
**Architecture:** Keep React/MUI/FastAPI and existing data. Add project-scoped standards/collections atop EvaluationStore; snapshot standards in the runner. Separate library, collection, run and evidence components.
**Tech Stack:** Python3.12, React19, MUI7, TypeScript.
**Spec:** docs/superpowers/specs/2026-11-13-rhesis-workflow-design.md

## Global constraints

- Only Evalith writes; ai-gateway/reference remain read-only. No questions or delegation.
- Preserve project-first entry, real APIs, source gates, unknown costs, uncalibrated judge semantics and old run history.
- Desktop light/dark. No placeholder Harbor execution or fake activity.

## Review focus

- Foreign/archived standards and membership IDs reject before execution.
- Editing a standard must not alter historical runs; model and threshold frozen.
- No grading pass without valid actual evidence; budget/cancel semantics preserved.
- Project switch cannot apply stale library/form data to another project.
- Keyboard form validation and task text/JSON types remain correct.

### Task1 — Standards and collections

- [x] Tests: project scoping, validation, version updates, archive, legacy generation grouping and valid set membership.
- [x] Add evaluation_library.py + routes: /graders CRUD and /test-sets CRUD; generated rubric is editable as a standard.
- [x] Run selected grader_ids snapshots; use per-standard model and threshold, preserve default checks and call budget.
- [x] Verify runner snapshots/model/threshold and focused regressions.

### Task2 — Product pages

- [x] Standards library with two-step form, set library with membership/standard selection.
- [x] Grouped navigation and project workflow chat context; actual API counts and actions.
- [x] Task input/rubric/history tabs; conversation-turn fields; target/judge/standard selectors in run setup.
- [x] Run list -> summary/tests/config detail, wide conversation/evaluation evidence drawer.
- [x] Relevant interaction tests, build and actual light/dark desktop screenshots.

### Task3 — Local delivery

- [x] Use actual saved aigateway data and persisted standards to verify the new flow. Model requests, if used, remain gpt-6-luna.
- [x] Backend/frontend regression, original source protection, restart service with new build and leave usable preview.
- [x] Record exact changes and limits, commit/update existing PR without merge.
