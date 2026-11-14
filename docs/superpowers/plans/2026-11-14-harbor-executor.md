# Harbor Executor — Implementation Plan

> Implement personally; continuation of the established cadence (spec → RED tests → implementation → real validation → review → merge).

**Goal:** Command tasks execute in Harbor Docker sandboxes with artifacts collected back into Evalith's unchanged check/judge machinery.
**Architecture:** environments.py gains a harbor plan/prepare path (CLI + Docker availability, source copy); the runner materializes a per-case Harbor task and parses job artifacts; bounded_process gains an unsandboxed mode for the orchestrating CLI.
**Tech Stack:** Python3.12/FastAPI/SQLite, harbor CLI (0.24+ on host), Docker, React19/MUI7/TypeScript.
**Spec:** docs/superpowers/specs/2026-11-14-harbor-executor-design.md

## Global constraints

- Container isolation replaces sandbox-exec for the target; the harbor CLI runs unsandboxed but owned (timeout, cancel, output caps, clean env).
- Scoring stays Evalith's; Harbor reward is metadata. No credentials, no model calls in validation; synthetic project only.
- Original ai-gateway and rhesis untouched.

### Task 1 — Environment plan/prepare and unsandboxed process mode

Files: environments.py, execution_process.py; tests: test_harbor_executor.py (new).

- [x] Failing tests: harbor plan accepted with executor config, rejects without; prepare records CLI/Docker versions and source manifest (availability faked); bounded_process unsandboxed mode still times out/cancels/caps output.
- [x] Implement harbor plan branch (no sandbox requirement, honest plan strings), availability probes, prepare branch, `unsandboxed=` mode.

### Task 2 — Runner execution and preflight

Files: evaluation_runner.py; tests: test_harbor_executor.py, test_evaluation_runs.py.

- [x] Failing tests: compatible map accepts command tasks only; fake-harbor execution maps artifacts to observation (stdout/exit_code/evidence_directory/harbor metadata); materialized task content (command substitution, stdin, input files, no-network, artifacts); harbor failure raises visibly.
- [x] Implement the harbor branch in execute_task with per-case task materialization and artifact parsing.

### Task 3 — Frontend, real validation, docs and delivery

Files: ExecutorSettings.tsx, EvaluationDialogs.tsx; evalith/README.md, docs/validation/2026-11-14-harbor-executor.md.

- [x] Run dialog offers harbor configs for command tasks; executor settings copy updated (protocol connected).
- [x] Real run on this host: synthetic command task through a prepared Harbor environment, one passing and one failing check (closes stage-0 negative path); record versions, timings, cleanup observations.
- [x] README note; full backend pytest + frontend tests + build + Ruff; validation doc; ledger; two-axis review; fix findings; merge to main and push.
