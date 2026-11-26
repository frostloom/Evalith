# Task planning with the user

Only two knobs are user-facing: **how many tasks** and the **difficulty
ratio**. Expected-failure tasks are included by default at **20%** (at least
one when the count is 5 or more and the share is above zero), so the user does
not need to enumerate types.

## 1. Ask only what matters

Always ask the user before drafting a plan, even if they said "use the
defaults". The defaults are a proposal, not a decision.

Ask:

1. **How many tasks?** Default **50**. Accept any positive integer.
2. **Difficulty ratio?** Default `easy:medium:hard = 4:4:2`. Accept any
   three non-negative weights.

The user may freely adjust either value. If they have no preference, propose
the defaults and state the resulting counts. Do not ask them to configure task
categories, trace levels, state checks, or failure types.

## 2. Draft plan

```bash
python scripts/plan_eval_set.py \
  --project <name> \
  --count 50 \
  --difficulty 4:4:2 \
  --out artifacts/eval_plan.json
```

This writes a draft with `approved_by_user: false`. Show the summary:

```text
count=50  easy=20 medium=20 hard=10  expected_failure=10
```

Expected-failure tasks are part of the count. If the user wants a different
failure share, pass `--failure-ratio 0.25`; an explicit `--failure-ratio 0`
keeps the set all-pass, while the default 0.2 adds at least one failure task
when the count is 5 or more.

## 3. Approval gate

After the user explicitly approves, set `approved_by_user: true` and
`approved_at` in the plan. Generate nothing while it is `false`.

## 4. Default coverage behind the count

The task set should still cover these behaviors; distribute them across the
requested count without asking the user to enumerate them:

- normal business requests;
- missing-parameter clarification;
- permission / cross-tenant rejection;
- write preview → confirm → execute once;
- cancellation with no state change;
- boundary / over-limit / duplicate;
- at least one expected-failure or adversarial case.

The default plan includes expected-failure tasks. An explicit
`--failure-ratio 0` is honored only when the user deliberately asks for an
all-pass set; the bundled one-task example is structural and is all-pass.

## 5. Standard rubric per task

Every task must include:

- `reference_answer` — the gold business outcome;
- `expected_facts` and, for expected-failure tasks, `forbidden_facts`;
- at least one `outcome` rubric criterion with `must_pass: true`, plus a
  final-state check. The schema cannot link the two, and at runtime ANY failed
  check zeroes a task that has a must_pass outcome, so include only checks that
  must pass;
- at least one additional `answer` criterion (weighted);
- at least one check (`sqlite` / `http_json` / `json_path` / file);
- `metadata.plan_id`, `metadata.difficulty` and `metadata.expect_failure`;
- `metadata.source_analysis` with at least one code/doc reference and facts.

Optional `process` criteria are allowed only when trace is available; otherwise
they become `not_evaluable`.

## 6. Plan metadata on tasks

```json
"metadata": {
  "plan_id": "<plan id>",
  "difficulty": "medium",
  "expect_failure": false
}
```

`validate_eval_set.py --plan artifacts/eval_plan.json` checks:

- plan is approved;
- task count matches;
- difficulty counts match `difficulty_counts`;
- expected-failure tasks match `failure_count`, and each has `forbidden_facts`;
- every task uses the same `plan_id`.
