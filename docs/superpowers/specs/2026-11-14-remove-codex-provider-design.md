# Remove the local ChatGPT login inference channel

User direction (2026-11-14): continue development, and stop using the codex-based configuration. The local ChatGPT-account inference channel is therefore removed from the product; it is no longer a supported way to reach a real model.

Removed surface: `codex_provider.py` (Codex CLI process, ephemeral ChatGPT transport, gpt-6-luna defaults), the `codex_local` model provider (creation validation, gateway request/test branches, `EVALITH_CODEX_BIN`/`EVALITH_CODEX_TIMEOUT` settings), the `/api/local-model/status` endpoint, the ChatGPT.app bundled-CLI auto-probe in `scripts/start-local.sh`, and the 本地 ChatGPT 账号 option in the model settings UI.

Real-model inference after this change uses the OpenAI-compatible provider only, unchanged in behavior and still disabled unless `EVALITH_ALLOW_PAID_MODELS` is explicitly set by the maintainer. The stub provider stays for offline flows. No new provider, credential store or budget behavior is introduced.

Historical records are preserved: existing model-config rows with `provider="codex_local"` stay in the database, past runs, usage records and validation documents are not rewritten. Legacy `codex_local` rows cannot serve new work: every request path fails with an explicit "channel removed" error, and a connection test reports failed with the same message instead of invoking any CLI. Creating or selecting the provider is rejected with a message that names the removal. The frontend keeps `codex_local` in the provider union only to render legacy rows, labeled 已移除.

The Go aigateway adapter needs no protocol change: its model bridge already routes through the workspace model gateway, so it follows whatever OpenAI-compatible model configuration a run selects.

This iteration makes no real model calls; validation is unit, contract and UI-level with the offline stub, per the no-codex direction. Removal is not a claim about model quality, and the known unimplemented capabilities (Harbor execution, adaptive multi-turn, grader calibration) remain unimplemented.
