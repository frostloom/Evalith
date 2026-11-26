# EvalScope EvalGen

An external **coding-agent Skill** that turns a local project and its knowledge
base into an EvalScope `eval_set.v1.jsonl`. It is independent of Evalith and
does not modify EvalScope.

The business Agent stays as it is: expose it over HTTP, let EvalScope call it,
and use read-only state checks (SQLite or a status API) for the final outcome.

## Install as a Skill

Copy this folder into your coding agent's skill-discovery path. For Claude Code:

```bash
cp -R evalscope-evalgen ~/.claude/skills/evalscope-evalgen
```

Other agents use their own skill path. The skill only needs Python 3.11+ and
its bundled standard-library scripts. `check_evalscope.py` additionally needs an
EvalScope build that contains `evalscope.project_eval` (the `feat/project-eval`
branch or the patch); the released PyPI package does not provide it.

## Quick start

Run the bundled scripts with their absolute path when your shell is in the
target project (the skill may live under `~/.claude/skills/`).

```bash
# 1. Read-only scan; the agent reads scan.json, not raw project files.
#    --knowledge-dir is scanned automatically (it must stay under --root).
#    It accepts a directory or a single file; the 120k-char budget is split
#    50/50 between knowledge and code by default (--knowledge-share).
python scripts/scan_sources.py \
  --root /path/to/project \
  --include app \
  --knowledge-dir docs \
  --out artifacts/scan.json

# 2. Discuss and approve a plan (ask the user; default 50 tasks, 4:4:2)
python scripts/plan_eval_set.py \
  --project my-agent --count 50 --difficulty 4:4:2 \
  --out artifacts/eval_plan.json
# after the user approves, set approved_by_user=true in eval_plan.json

# 3. Author eval_set.v1.jsonl from scan.json + eval_plan.json
#    Each task has reference_answer / expected+forbidden facts / rubric / checks,
#    metadata.source_analysis, and metadata.plan_id / difficulty / expect_failure.

# 4. Validate and build a manifest
python scripts/validate_eval_set.py \
  --eval-set artifacts/eval_set.v1.jsonl \
  --scan artifacts/scan.json --plan artifacts/eval_plan.json \
  --root /path/to/project --strict

# Authoritative EvalScope check: schema, project_root, checks and adapter.
# Requires an EvalScope build with evalscope.project_eval (feat branch/patch).
python scripts/check_evalscope.py \
  --eval-set artifacts/eval_set.v1.jsonl \
  --project-root /path/to/project

python scripts/build_manifest.py \
  --scan artifacts/scan.json \
  --eval-set artifacts/eval_set.v1.jsonl \
  --out artifacts/manifest.json
```

## Hand off to EvalScope

```bash
mkdir -p outputs
evalscope service --host 127.0.0.1 --port 9000 --outputs ./outputs \
  --enable-project-eval --eval-set-root artifacts

# or via the project_eval benchmark / TaskConfig with
# dataset_args.local_path pointing at eval_set.v1.jsonl and
# dataset_args.project_eval.project_root pointing at the project
```

Import the JSONL in **Eval Sets**, then run. EvalScope owns the Agent call,
trace, rubric judge, checks and report.

## Layout

```text
SKILL.md
references/
  task-planning.md       # discuss count/type/quality with the user
  jsonl-contract.md      # output schema and examples
  source-scope.md        # allowlist, excludes, sensitive files, limits
  checks.md              # check types and read-only state API
  agent-api.md           # REST agent envelope for L0/L1/L2
  trace-levels.md        # L0/L1/L2 and degradation
scripts/
  scan_sources.py        # read-only snapshot with hashes and excerpts
  plan_eval_set.py       # draft plan; approval is explicit
  validate_eval_set.py   # schema/path/material/source/plan validation
  check_evalscope.py     # EvalScope's own loader + project_eval adapter smoke test
  build_manifest.py      # source digest + task versions
examples/minimal/        # one-task example
tests/                   # standard-library unittest suite
```

## Design boundaries

- **EvalScope does not read source.** This skill performs the source/KB scan
  and hands over a JSONL contract.
- **The Agent does not need code changes.** EvalScope calls its HTTP API; checks
  use SQLite or a read-only state endpoint.
- **Trace is optional.** Use L2 when the Agent returns steps; degrade to L0 and
  mark `process` criteria `not_evaluable` when it does not.
- **Security is in the scanner.** The agent must not read project files
  directly; it only reads `scan.json`, which excludes `.env`, keys, secrets,
  symlinks and over-budget files.

## Development

```bash
python -m unittest discover -s tests -v
```
