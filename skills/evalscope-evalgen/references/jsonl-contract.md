# JSONL contract

One JSON object per line, UTF-8, no trailing commas. The file is consumed by
EvalScope's `project_eval` benchmark.

## Minimal task

```json
{
  "id": "refund-001",
  "version": 1,
  "question": "客户想把最近一笔充值退 100 元，可以吗？",
  "system": "",
  "messages": [],
  "reference_answer": "先预览退款 100 元；确认后执行一次，返回退回 100 元、余额 1900 元。",
  "expected_facts": ["退款 100 元", "余额 1900 元"],
  "forbidden_facts": ["重复退款", "退款 0 元"],
  "pass_threshold": 0.75,
  "rubric": [
    {"id": "c1", "criterion": "确认后审计中出现一次已确认的退款", "weight": 1,
     "must_pass": true, "evidence_requirement": "outcome"},
    {"id": "c2", "criterion": "先预览后确认，没有跳过确认", "weight": 2,
     "must_pass": false, "evidence_requirement": "process"},
    {"id": "c3", "criterion": "说明退款金额和结果", "weight": 2,
     "must_pass": false, "evidence_requirement": "answer"}
  ],
  "checks": [
    {"id": "db-1", "type": "sqlite", "dsn": "agent.db",
     "query": "select confirmed from agent_audit_log where session_id='refund-001' order by id desc limit 1",
     "expect": 1}
  ],
  "exec": {
    "type": "agent_api",
    "protocol": "rest_steps",
    "agent_url_env": "EVAL_AGENT_URL",
    "reset_url": "http://127.0.0.1:9201/v1/eval/reset",
    "trace": {"mode": "auto"},
    "session": {"id_from": "sample_id"}
  },
  "source_refs": ["internal/agent/tools.go:484", "docs/policy.md#退款"],
  "origin": "fact",
  "materials": [{"path": "internal/agent/tools.go", "sha256": "..."}],
  "metadata": {
    "plan_id": "plan-20261126061056",
    "difficulty": "medium",
    "expect_failure": false,
    "uncertainties": [],
    "source_analysis": {
      "code_refs": [{"path": "internal/agent/tools.go", "line": 484, "fact": "refund_recharge requires confirmation"}],
      "doc_refs": [{"path": "docs/policy.md", "line": 12, "heading": "退款", "fact": "refund is capped at balance"}],
      "facts": ["refund amount is capped at the current balance"],
      "scope_digest": "..."
    }
  }
}
```

## Fields

| Field | Rule |
|---|---|
| `id` | Unique string; used as session id by the adapter |
| `version` | Integer >= 1; increment on edit |
| `question` | Required non-empty string; `messages` are an optional multi-turn supplement |
| `messages` | Optional multi-turn messages; when present they are sent instead of question/system |
| `reference_answer` | Gold business outcome; shown as Expected Answer and used by the judge |
| `expected_facts` / `forbidden_facts` | Facts the judge should verify / reject |
| `pass_threshold` | 0–1; default 0.6, use 0.75 for multi-criteria tasks |
| `rubric` | Non-empty; each criterion needs `id`, `criterion`, `weight`, `must_pass`, `evidence_requirement` |
| `checks` | At least one final-state check is required |
| `exec` | `agent_api` or `http`; see below |
| `source_refs` | `path:line` or `doc#heading`, and the file must have an excerpt in scan.json |
| `materials` | Actual files with a 64-char hex SHA-256, no secrets |
| `metadata.source_analysis` | Required; structured facts + at least one code/doc ref + scope digest |
| `metadata.plan_id` / `metadata.difficulty` / `metadata.expect_failure` | Must match the approved `eval_plan.json` |
| `origin` | `fact` or `inference` |

## Evidence requirement

- `answer` — judged from the agent's final answer;
- `outcome` — judged from end-state checks;
- `process` — requires trace/tool calls. If trace is unavailable it becomes
  `not_evaluable`; never invent it.

`json_path`, `sqlite` and `http_json` checks must include `expect`; EvalScope
compares the observed value to it and a missing value would compare against
`null`. `http` checks use `expect_status` (default 200) instead.

## `exec`

```json
{"type": "agent_api", "protocol": "rest_steps", "agent_url_env": "EVAL_AGENT_URL",
 "reset_url": "http://127.0.0.1:9201/v1/eval/reset",
 "trace": {"mode": "auto"}, "session": {"id_from": "sample_id"}}
```

```json
{"type": "http", "base_url_env": "EVAL_AGENT_URL",
 "request": {"method": "POST", "path": "/chat", "json": {"message": "hi"}},
 "trace": {"mode": "none"}, "session": {"id_from": "sample_id"}}
```

`reset_url` must be `http://127.0.0.1[:port]` or `http://localhost[:port]` and
is called before every task; use it only when the business state is safe to
reset. Check URLs must use the same loopback forms; uppercase schemes, userinfo,
IPv6 loopback and lookalike hosts are rejected. `exec.trace.mode` accepts
`auto`/`inline`/`fetch`/`none`; the current adapter auto-detects steps from the
response. `exec.session.id_from` must be `sample_id`.

The REST agent envelope is in [agent-api.md](agent-api.md).

## Manifest

`build_manifest.py` writes:

```json
{
  "generated_at": "...",
  "source_scope_digest": "...",
  "file_hashes": {"internal/...": "..."},
  "task_versions": {"refund-001": 1}
}
```

Keep old eval-set files and manifests when editing; runs remain tied to the
version they used.
