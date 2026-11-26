# Trace capability levels

The skill authors the eval set; EvalScope executes and records trace. Do not
fabricate trace data in the JSONL.

| Level | Business agent provides | EvalScope can evaluate |
|---|---|---|
| **L2** | `steps` / `tool_calls` in the response, or `trace_id` + queryable trace | answer + tool process + end state |
| **L1** | only `trace_id`, trace lives in an external system | L2 if fetchable; otherwise L0 |
| **L0** | final answer only; business state queryable | answer + end state |

## Rules for authors

- If the user says the agent has no trace, do not create `process` criteria.
- If a `process` criterion is unavoidable, mark it `must_pass: false`; it will
  be `not_evaluable` when trace is absent, not failed.
- Prefer `outcome` criteria backed by checks; they are the most portable.
- In `exec.trace.mode`, use `auto` unless the user explicitly knows the level.
  The current adapter auto-detects steps from the response; the mode is a
  declaration, not a fetch switch. `exec.session.id_from` must be `sample_id`.
- Do not ask the business team to change business logic. Deployment-level
  instrumentation (proxy or OTel auto-instrumentation) is acceptable; code
  changes are not required by this skill.

The report exposes `evidence_coverage`: `可评条数 / 总条数`. A lower coverage
with `not_evaluable` is honest; a fabricated trace is not.
