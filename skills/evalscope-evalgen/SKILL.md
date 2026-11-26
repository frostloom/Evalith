---
name: evalscope-evalgen
description: >-
  Generate EvalScope business-agent eval sets from a local project and its
  knowledge base. Read-only scans selected source/docs, produces eval_set.v1.jsonl
  with reference answers, expected/forbidden facts, rubrics and end-state checks,
  then hands it to EvalScope for execution. Trigger on: generate eval set,
  create evaluation tasks from a repo, project eval, evalgen, 生成评测集,
  根据源码出题, 知识库出题, 业务 Agent 评测, EvalScope 项目评测. Do NOT trigger
  for: model training, serving, or writing benchmark adapters.
---

# EvalScope EvalGen

This skill is an **external authoring tool** for EvalScope. It does not modify
EvalScope and does not depend on Evalith. It reads a user-selected local project
and knowledge base, writes an `eval_set.v1.jsonl`, and EvalScope consumes that
file through the `project_eval` benchmark.

Read only the reference file for the current step; do not preload everything.
Commands below use `scripts/...` relative to this skill directory; when your
working directory is the user's project, run them with the absolute path to
this skill's `scripts/` folder.

| Step | Reference |
|---|---|
| Task planning (required before generation) | [task-planning.md](references/task-planning.md) |
| Output format | [jsonl-contract.md](references/jsonl-contract.md) |
| Source / knowledge-base scope | [source-scope.md](references/source-scope.md) |
| Checks and read-only state API | [checks.md](references/checks.md) |
| Agent API envelope | [agent-api.md](references/agent-api.md) |
| Trace capability levels | [trace-levels.md](references/trace-levels.md) |

## Install

Copy this directory into the coding agent's skill-discovery path. For Claude
Code that is usually `~/.claude/skills/evalscope-evalgen/`; other agents use
their own skill path. The skill only needs Python 3.11+ and its bundled
scripts (standard library only). `check_evalscope.py` additionally requires an
EvalScope build that contains `evalscope.project_eval` (the
`feat/project-eval` branch or the patch); the released PyPI package does not
provide it.

## Required inputs

Ask for these before generating:

- **project root** — the local project to evaluate;
- **knowledge base** — one or more document directories or files under the
  project root; copy or mount external docs under the root, because the scanner
  never reads outside it;
- **output directory** — where `eval_set.v1.jsonl` and `manifest.json` go;
- **task count and difficulty ratio** — ask the user (default 50 tasks,
  `4:4:2`); they may freely adjust both;
- **system under test** — HTTP agent URL, or a local service; and optionally a
  read-only state endpoint;
- **trace level** — L0/L1/L2 if known; otherwise `auto`.

## Workflow

### 1. Scan selected materials (read-only)

```bash
python scripts/scan_sources.py \
  --root <project-root> \
  --include src \
  --knowledge-dir docs \
  --summary \
  --out artifacts/scan.json
```

The scanner enforces the allowlist, default excludes, sensitive-file denylist,
symlink rejection, file/byte/character limits, redaction and SHA-256.
`--knowledge-dir` accepts a directory or a single file, is scanned
automatically and is marked `knowledge: true`; it does not need to be repeated
in `--include`. The default excerpt budget is 120,000 characters total and
8,000 per file, split 50/50 between knowledge and code; adjust with
`--knowledge-share` (0–1) and the budget flags. Show the summary (selected
files, sent chars, sensitive rejects, omitted reasons) to the user and get
confirmation before generating tasks. **Read only `scan.json` for project
context; never read raw project files directly.**

### 2. Build source analysis

From the scanner excerpts only, produce a short structured analysis:

- modules, routes, tools, data models, entry points;
- business rules and state transitions;
- observable end state (database/API/file);
- open questions / unsupported facts.

Every fact must cite `path:line` or `doc#heading`, and the reference must exist
in `scan.json`; the validator enforces this. Do not invent unsupported rules;
mark them as inference or ask the user.

### 3. Discuss and approve a task plan (required)

This step is mandatory: always ask the user, even if they said "use the
defaults". Do not generate tasks yet. Ask only:

1. how many tasks (default 50);
2. the difficulty ratio (default `easy:medium:hard = 4:4:2`).

The user may freely adjust both values; accept any positive count and any
three non-negative difficulty weights. Expected-failure tasks are included
automatically at 20% (at least one when the count is 5 or more), so do not ask
the user to enumerate categories. If the user wants a different failure share,
pass `--failure-ratio`.

```bash
python scripts/plan_eval_set.py \
  --project <name> --count 50 --difficulty 4:4:2 \
  --out artifacts/eval_plan.json
```

Show the resulting counts. When the user explicitly approves, set
`approved_by_user: true` and `approved_at`. Generate nothing while it is
`false`. See [task-planning.md](references/task-planning.md).

### 4. Generate tasks

For each task write:

- `question` (and `messages` for multi-turn);
- `reference_answer` (the expected business outcome, derived from source/docs);
- `expected_facts` / `forbidden_facts`;
- `rubric` with `must_pass` / `weight` / `evidence_requirement`;
- `checks` — read-only file / sqlite / http / http_json / json_path;
- `exec` — agent API or HTTP, plus an optional loopback `reset_url`;
- `source_refs` and materials with SHA-256;
- `metadata.plan_id`, `metadata.difficulty`, `metadata.expect_failure`;
- `metadata.source_analysis` (required: at least one `code_refs` or `doc_refs`
  entry and a `facts` list).

Every task needs at least one `must_pass` outcome criterion and at least one
final-state check. The schema cannot link a criterion to a check; at runtime,
if a task has a must_pass outcome criterion and ANY check fails, the task is
zeroed. Include only checks that must pass for that outcome. Also include at
least one answer criterion. Use [jsonl-contract.md](references/jsonl-contract.md).
Write one task per line to `artifacts/eval_set.v1.jsonl`.

### 5. Validate (required)

```bash
python scripts/validate_eval_set.py \
  --eval-set artifacts/eval_set.v1.jsonl \
  --scan artifacts/scan.json \
  --plan artifacts/eval_plan.json \
  --root <project-root> \
  --strict

python scripts/check_evalscope.py \
  --eval-set artifacts/eval_set.v1.jsonl \
  --project-root <project-root>
```

`validate_eval_set.py` checks the EvalScope `EvalTask` contract, source
references (file/line/heading), material hashes, source changes, the approved
plan, excerpt coverage, check paths/URLs and the standard rubric. A reference to
a file that produced no excerpt fails: re-scan with a larger `--max-total-chars`
instead of citing unseen code. `check_evalscope.py` is the authoritative smoke
test: it validates the schema with EvalScope's own loader, resolves every check
path against `--project-root`, and converts every task through the
`project_eval` adapter. It requires an EvalScope build that contains
`evalscope.project_eval` (the `feat/project-eval` branch or the patch); the
released PyPI package does not include it. **Do not hand off until both
commands pass.**

### 6. Build manifest

```bash
python scripts/build_manifest.py \
  --scan artifacts/scan.json \
  --eval-set artifacts/eval_set.v1.jsonl \
  --out artifacts/manifest.json
```

The manifest records source digest, material hashes, task versions and the
generation timestamp. Editing a task increments its `version`; keep prior run
files unchanged.

### 7. Hand off to EvalScope

```bash
mkdir -p outputs
evalscope service --host 127.0.0.1 --port 9000 --outputs ./outputs \
  --enable-project-eval --eval-set-root artifacts
```

Import the JSONL in **Eval Sets**, or run it through the `project_eval`
benchmark with `dataset_args.local_path` pointing at the file. The direct
`TaskConfig` route must also set
`dataset_args.project_eval.project_root` to the project root; otherwise relative
check paths resolve against the current directory and fail silently. The
evaluator owns execution, trace, judge and report; this skill only authored the
set.

## Safety invariants

- Read only through `scan_sources.py`; do not `Read`/`cat` arbitrary project paths.
- Never include `.env`, keys, certificates, credentials or private keys.
- Never execute project code, install dependencies, or run shell commands from
  generated task inputs.
- Checks must be read-only; command checks are not supported.
- Do not include secrets in `source_refs`, `materials`, `expected_facts` or the
  judge prompt.
- Do not claim trace evidence that the agent did not return.

## Quality bar

- The approved plan controls count, difficulty counts and the expected-failure
  count; do not silently change them.
- Every task has a reference answer, expected facts, at least one final-state
  check and `metadata.source_analysis` with a code/doc reference.
- Every rubric has at least one `must_pass` outcome criterion and at least one
  additional `answer` criterion. Any failed check zeroes a task with a
  must_pass outcome, so include only checks that must pass.
- Expected-failure tasks must carry `forbidden_facts`. The default plan includes
  them; an explicit `--failure-ratio 0` is honored only when the user asks for
  an all-pass set.
- `must_pass` is reserved for criteria that are truly mandatory.
- Prefer `http_json` against a read-only state API for separately deployed
  agents; use `sqlite` only when EvalScope can read the business DB.
- If there is no trace, omit `process` criteria or accept that they will be
  `not_evaluable`; do not fabricate tool calls.
