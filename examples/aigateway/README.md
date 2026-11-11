# AI Gateway isolated example

The adapter compiles an Evalith-owned source copy of `github.com/frostloom/ai-gateway/internal/agent.Handler`. Original source files remain unchanged. It accepts one JSON case on stdin, executes the actual handler and emits JSON reply/turns/writes/audit evidence.

Each case owns SQLite session/audit tables, miniredis, and a loopback synthetic billing server. Default synthetic balance is 200000 cents. The only supported fixture field is `balance_cent`. There is no access to existing MySQL, Redis, financial services or old evaluation campaigns. Routes beyond the narrow billing fixture may be unsupported; a missing route must remain an execution limitation.

The target model endpoint/token/name are supplied by the Evalith runner. The token grants access only to this run's local model bridge; it is not the user's ChatGPT credential. The bridge converts model-produced JSON into OpenAI-style tool-call messages. This is an adapted inference transport rather than a native custom-tools API benchmark. Model identity is explicitly checked against the run snapshot. The actual Handler selects and executes its tools against the synthetic services.

Use the product UI: import the local repository read-only, choose a real model, inspect/continue understanding, generate conversation tasks, select them and choose the AI Gateway environment. Review and confirm the plan before preparation. Runtime code is copied to `cmd/evalith-adapter/main.go` only inside the owned environment. A separate SQLite driver requirement is added only to the copied go.mod.

Preparation needs Go, a working C compiler/SDK and a reachable Go module proxy. All build caches are under the Evalith data directory. `EVALITH_GO_PROXY` and `EVALITH_GO_SDKROOT` are local overrides; no global Go or Xcode settings are modified. Command execution currently requires the macOS sandbox. Other platforms reject execution until an equivalent adapter is implemented.
