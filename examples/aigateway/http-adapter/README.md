# ai-gateway synthetic HTTP wrapper

Builds the real `internal/agent.Handler` from the ai-gateway checkout into a
small HTTP service with isolated SQLite, miniredis and a synthetic billing
server. The original ai-gateway repository is never modified: `build.sh` copies
it to `.evalith/build/ai-gateway` and builds `cmd/eval-adapter` there.

## Endpoints

- `GET /health`
- `POST /v1/eval/chat` `{session_id, message}` → `{reply, trace, session_id, pending_confirm, ...}`
- `GET /v1/eval/state?session_id=...` → `{audit, writes, balance_cent, tenant_id}`
- `POST /v1/eval/reset` → reseed SQLite/miniredis/synthetic billing

## Environment

- `EVAL_AGENT_PORT` (default `9201`)
- `EVAL_AGENT_LLM_BASE_URL` (default `https://api.deepseek.com/v1`)
- `EVAL_AGENT_LLM_API_KEY`
- `EVAL_AGENT_LLM_MODEL` (default `deepseek-flash`)
- `EVAL_AGENT_TRACE_MODE` (`l2` or `l0`; `l0` strips `trace` from responses)
- `EVAL_AGENT_STATE_DIR` (default `.evalith/aigateway`)

## Build and run

```bash
./build.sh
EVAL_AGENT_LLM_API_KEY="$DEEPSEEK_API_KEY" .evalith/bin/ai-gateway-adapter
```
