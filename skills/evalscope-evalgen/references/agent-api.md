# Agent API envelope

`exec.type: agent_api` with `protocol: rest_steps` calls a small REST contract on
the business agent. The agent keeps its own business logic; this is only the
evaluation endpoint.

Export the base URL before running EvalScope:

```bash
export EVAL_AGENT_URL=http://127.0.0.1:9201
```

`exec.agent_url_env` names the variable (default `EVAL_AGENT_URL`).

## Request

One request per user message:

```http
POST {EVAL_AGENT_URL}/v1/eval/chat
Content-Type: application/json
```

```json
{"session_id": "task-id", "message": "客户想退 100 元，可以吗？"}
```

`session_id` is the eval task id, so the business side can key its audit/state
by task.

## Response

```json
{
  "reply": "已退回 100 元，当前余额 1900 元。",
  "steps": [
    {"type": "tool", "name": "refund_recharge",
     "arguments": {"amount_cent": 10000}, "result": "ok", "elapsed_ms": 12}
  ],
  "trace_id": "trace-123",
  "state": {"balance_cent": 190000},
  "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}
}
```

Rules:

- `reply` is required and must be a string.
- `steps`, `tool_calls` or `trace` is optional; when absent the run is L0
  (answer + end state) and `process` criteria become `not_evaluable`.
- A step needs `name` or `tool`; `arguments` (object) or `args` (JSON string),
  `result`, `elapsed_ms`/`duration_ms` and `type` are optional.
- `state` and `usage` are optional.
- Multi-turn tasks send one request per `user` message; assistant/system
  messages are not sent to this endpoint.

## Other protocols

- `openai_compat` calls `{base_url}/chat/completions` and records only the final
  answer (L0).
- `exec.type: http` posts the custom `request` and records only the final
  response (L0); use it for an agent that already has an evaluation endpoint.

For a separately deployed agent, pair this with the read-only state API in
[checks.md](checks.md). Do not change business logic just to return trace; a
proxy or OTel instrumentation is acceptable when the user wants L2.
