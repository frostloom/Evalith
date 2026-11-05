# Stage 0 validation assets

This directory contains the reproducible parts of the Evalith stage-0 validation.
It is separate from `docs/stage0/`, which holds the report and its evidence.

Nothing here uses real business data, real credentials, or a real model. All model
responses are deterministic stubs. A stub run proves interface behaviour, not model
capability.

## 1. Synthetic task harness (no Rhesis dependency)

The harness proves the execution boundary Evalith needs: read-only project access with
secret/symlink exclusion, a non-conversation event input, a restrictive container,
an independent hidden verifier, and cleanup.

Requirements: Docker, Python 3.12+ (stdlib only).

```bash
cd <repository root>
python3 stage0/harness/runner/run.py
```

It builds three role-scoped images (`stage0-agent`, `stage0-verifier`,
`stage0-reader`) and runs five scenarios:

| Scenario | Expected | What it proves |
| --- | --- | --- |
| `local_project_access` | pass | allowlisted files read, `.env`/`secrets` excluded, escaping symlink rejected, mount read-only |
| `pass` | passed | correct final state + audit evidence |
| `fail` | failed | verifier catches a wrong release even though the agent reported success |
| `missing_evidence` | unverified | missing audit evidence is not treated as pass |
| `claim_mismatch` | passed | a wrong agent self-report does not change the state verdict |

The agent gets a filtered project snapshot (no `.env`, no `secrets/`), an event-only
input directory, and an image that contains no verifier. The expectation file is mounted
only into the verifier. Each case records an access probe for `/app/verify.py`,
`/input/expectation.json`, `/project/.env` and `/project/secrets/credentials.txt`, plus
the agent image/mount contents, so the claimed hidden-verifier boundary is evidence, not
just prose.

Evidence is written to `stage0/evidence/runs/<UTC timestamp>-summary.json`. The run
exits `0` only when every expected verdict and every cleanup check succeeds.

Layout:

- `agent/agent.py` — synthetic non-conversation agent (reads project policy, applies a
  naive release transition).
- `verifier/verify.py` — independent verifier; exit codes 0/2/3 for passed/failed/
  unverified.
- `project_reader/read_project.py` — read-only project scanner.
- `fixtures/project/` — synthetic project; `.env` and `secrets/` contain only fake
  markers.
- `runner/run.py` — Docker driver, isolation flags, evidence writer, cleanup checks.

## 2. Rhesis runtime flow (stub model + stub target)

This flow starts the frozen Rhesis source, connects it to a deterministic
OpenAI-compatible stub (not a model), creates a synthetic project/test set/test/metric,
and runs one test against a deterministic non-conversation target. It then compares
Rhesis' metric verdict with the independent verifier in `stage0/harness/verifier/`.

Requirements:

- a Rhesis checkout at `ce24bb1993fc545bb0ccb0d8b3951683ac14fff1` (the ticket does not
  vendor it);
- Docker with enough disk for the Rhesis images;
- ports 8080/3000 free, or override them in the local env file.

See [rhesis-flow/README.md](rhesis-flow/README.md) for exact commands and limitations.

## 3. Evidence

- `docs/stage0/evidence/rhesis-code-map.md` — source/data dependency map.
- `docs/stage0/evidence/license-audit.md` — license and brand audit.
- `docs/stage0/evidence/harbor-eval.md` — Harbor 0.25.0 hands-on evaluation.
- `stage0/evidence/runs/` — synthetic harness summaries.
- `stage0/evidence/rhesis-runtime/` — Rhesis flow output (created by the flow).

## 4. Cleanup

The synthetic harness removes its containers and volumes in a `finally`-style cleanup
and records any leftover. For the Rhesis flow, stop the stack with:

```bash
cd <rhesis checkout>
docker compose -f docker-compose.yml -f <local override> --env-file <local env> \
  -p rhesis-stage0 down -v
docker rm -f stage0-stub
```

`down -v` deletes the local Rhesis database and storage volumes. Use it only on the
disposable stage-0 stack, never on data you want to keep.
