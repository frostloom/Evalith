# Checks and read-only state API

Checks assert the business end state, not the model's self-report. They run
after the agent call and are read-only.

## Supported check types

| Type | Fields | Meaning |
|---|---|---|
| `file_exists` | `path` | file exists under the project root |
| `file_content` | `path`, `contains` | text contains substring |
| `json_path` | `path`, `json_path`, `expect` | dot path in a JSON file equals expected |
| `sqlite` | `dsn`, `query`, `expect` | read-only query; first row/first column equals expected |
| `http` | `method`, `url`, `expect_status` | HTTP status equals expected |
| `http_json` | `url`, `json_path`, `expect` | GET JSON and compare a dot path |

`dsn`/`path` are relative to `project_root`; they must stay under it and must not
point to sensitive files (`.env`, `.ssh`, key files, `secrets*`); EvalScope
denies those at runtime.
`expect` is required for `json_path`, `sqlite` and `http_json`; missing it would
compare the observed value against `null`. HTTP URLs must use
`http://127.0.0.1[:port]` or `http://localhost[:port]`; uppercase schemes,
userinfo, IPv6 loopback and lookalike hosts such as `localhost.example.com` are
rejected. Command/exit-code checks are not supported by this skill.

## Read-only state API contract

For a separately deployed business agent, ask the business side to expose a
read-only endpoint:

```http
GET /v1/eval/state?session_id=<task id>
```

```json
{
  "audit": [
    {"tool": "refund_recharge", "confirmed": true, "result": "..."}
  ],
  "balance_cent": 190000,
  "orders": [{"id": "T-1001", "status": "refunded"}],
  "pending": null
}
```

Rules:

- GET only; no writes; no credentials in query strings;
- stable field names; return the state after the task;
- include tool/action audit entries with `confirmed` when confirmation matters;
- if the agent is local, a read-only SQLite query is also acceptable.

Use `http_json` against this endpoint, e.g.:

```json
{"id": "state-1", "type": "http_json",
 "url": "http://127.0.0.1:9201/v1/eval/state?session_id=refund-001",
 "json_path": "audit.0.confirmed", "expect": true}
```

## Choosing checks

- Prefer an explicit final-state check per task.
- For “nothing happened” cases, check an empty audit or an unchanged count.
- For “confirmed” writes, check the confirmed audit entry or the status field.
- For boundaries, check the capped amount / final balance, not only the answer.
- Do not check implementation details that are not business-observable.
