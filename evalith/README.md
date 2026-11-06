# Evalith phase-1 service

A local, single-user service for the stage-1 project workspace:

- import a local project through an explicit, read-only scope;
- create one persistent main session per project (concurrency-safe);
- generate an evidence-backed initial understanding that separates known,
  inferred and unknown items;
- let the user correct the understanding, add supplemental material, or state
  that they want to continue — without treating "continue" as confirmation of
  unknown business rules;
- keep model credentials encrypted and out of the model context and logs.

Question generation, environments and runs belong to later phases. The service
does not create any of them; `POST /api/projects/{id}/generate` is a testable
gate that refuses before readiness and reports "not implemented in phase 1"
after it.

## Run

```bash
cd evalith
uv sync

cd web
npm install
npm run build
cd ..

EVALITH_DATA_DIR=$PWD/.evalith-data uv run uvicorn evalith.api:app --host 127.0.0.1 --port 8090
```

Open <http://127.0.0.1:8090>. The service refuses to bind a non-loopback
address unless `EVALITH_ALLOW_REMOTE=1` is set: it can read local project paths
and has no user authentication. The first model configuration should be the
`stub` provider if you want an offline walkthrough; it is a deterministic替身
and its output is not a real model assessment.

Without `EVALITH_SECRET_KEY`, the service generates a 0600 key file at
`$EVALITH_DATA_DIR/secret.key`. Model API keys are encrypted with that key and
never returned by the API.

## Test

```bash
cd evalith
uv run pytest -q

cd web
npm test
npm run build
```

The Python suite covers descriptor-anchored traversal, replaced/symlinked root
rejection, scope enforcement, secret denylist, read-only behaviour, source
fingerprints, session uniqueness under concurrency, reopen restoration,
cross-project isolation, credential redaction in supplemental/chat/model
requests/logs plus literal key scrubbing from upstream errors and outgoing
content, full-content PEM redaction before excerpt truncation, literal-key scrubbing of
successful responses, strict boolean/sufficiency/affirmative-intent handling,
sourced known facts, malformed understanding arrays, FIFO rejection, oversized
and read-error descriptor ownership, ancestor exclusions for explicit
selections, preservation of failed analysis until a validated replacement,
project model repair, reanalysis history/correction preservation, model-failure
visibility, and the question-generation gate. The frontend tests cover project-switch draft reset
and stale-response rejection.

## Project access

The service is host-only in phase 1. Container path translation is not
implemented: setting `EVALITH_ACCESS_MODE` to anything other than `host` fails
closed. A container deployment needs a verified read-only mount and UID model
first; the allowlist, secret denylist and symlink rules are already independent
of the access mode. See `docs/stage1/project-access.md` for the full boundary.

## Scope of this phase

This app is deliberately separate from the EE-free Rhesis workbench tree. The
workbench (projects, test sets, runs, results) is built and smoke-tested in
`workbench/`; this service owns the stage-1 local project access and main
session experience. The UI shows test-set and run entries as later-phase
placeholders; it does not claim those flows work yet.
