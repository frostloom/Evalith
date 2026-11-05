# Harbor — execution-backend evaluation for Evalith (stage 0)

Status: **hands-on probe completed, one real run succeeded (reward 1.0)**.
Environment: macOS arm64, Docker 29.8.2, Python 3.12.15.
Date of evidence: 2026-11-05 (Asia/Shanghai). Scratch work is under `/tmp` and is **not committed**.

---

## 1. Project, version, license

| Item | Value | How verified |
|---|---|---|
| Official repo | https://github.com/harbor-framework/harbor | GitHub API `repos/harbor-framework/harbor` → `full_name`; HTTP 200 |
| Description | "Framework for evaluating and improving agents" | GitHub API |
| License | **Apache-2.0** | `raw.githubusercontent.com/harbor-framework/harbor/main/LICENSE` header ("Apache License, Version 2.0, January 2004"), GitHub API `license.spdx_id = Apache-2.0`, PyPI `license_expression = Apache-2.0` |
| Latest release / tag | **v0.25.0** (published 2026-10-25) | GitHub `/releases/latest`; tags list `v0.25.0, v0.24.0, v0.23.0, ...` |
| Latest PyPI version | **0.25.0** | `https://pypi.org/pypi/harbor/json` |
| Python package | `harbor` on PyPI (CLI binary also `harbor`) | PyPI metadata |
| Python requirement | `>=3.12` | PyPI `requires_python` |
| Install | `pip install harbor` (extras exist for cloud sandboxes: `harbor[modal]`, `harbor[e2b]`, `harbor[daytona]`, … — **not needed** for Docker) | PyPI `requires_dist` |
| Docker requirement | Docker CLI + daemon reachable; local `docker` environment provider is the default (`harbor run --env docker`). Compose is used internally for multi-service/verifier setups. | `harbor run --help` (`--env [ack\|...\|docker\|...]`, default docker); job log shows Docker image builds |

Note: this is the **agent-eval framework Harbor** (`harbor-framework`), not the CNCF container-registry "Harbor" (goharbor). Same name, unrelated project.

## 2. Install commands actually used

```bash
python3 -m venv /tmp/harbor-eval-venv
/tmp/harbor-eval-venv/bin/pip install --upgrade pip
/tmp/harbor-eval-venv/bin/pip install harbor
# installed: harbor 0.25.0  (pip show → Version: 0.25.0)
/tmp/harbor-eval-venv/bin/harbor --version   # → 0.25.0
```

Isolation: dedicated venv at `/tmp/harbor-eval-venv`; nothing installed into system Python; no repo changes.

## 3. Task format for 0.25.0 (scaffolded, not guessed)

Scaffolded with the installed CLI, then inspected:

```bash
/tmp/harbor-eval-venv/bin/harbor init -t evalith/smoke --output-dir /tmp/harbor-scratch
```

Resulting layout (single-step task, schema_version `1.4`):

```
smoke/
  task.toml                 # schema_version, artifacts, [task] [verifier] [agent] [environment] [solution.env]
  instruction.md            # natural-language task for the agent
  environment/Dockerfile    # agent sandbox image (WORKDIR /app)
  tests/Dockerfile          # verifier image (scaffold: python:3.12-slim + uv + pytest + pytest-json-ctrf)
  tests/test.sh             # runs pytest, writes /logs/verifier/reward.txt (1/0)
  tests/test_outputs.py     # hidden verifier tests
  solution/solve.sh         # reference solution used by the `oracle` agent
  README.md, .gitignore
```

Key `task.toml` fields used in the probe:

```toml
schema_version = "1.4"
artifacts = ["/app/out/status.txt"]      # collected from agent env, re-materialized in verifier env

[task]  name/version/description/authors = [{name,email}]/keywords
[verifier] timeout_sec = 300.0
           environment_mode = "separate" # verifier runs in its own container; sees only collected artifacts
[agent]    timeout_sec = 300.0
[environment] network_mode = "no-network"  # enum: "no-network" | "public" | "allowlist"
              build_timeout_sec = 600.0
```

Notes on semantics (read from installed source, `harbor/models/task/config.py`):
- `verifier.environment_mode`: `shared` = verifier runs in the agent's container (sees the whole agent filesystem);
  `separate` = dedicated container built from `tests/Dockerfile`, and only declared `artifacts` are re-materialized
  into it (same container paths). `separate` is the scaffolded default and the stronger hidden-verifier isolation.
- `verifier.collect` = commands run in compose services after the agent phase, to snapshot runtime state into files
  that artifacts can collect (relevant for Evalith-style "state after the agent touched services" checks).
- `artifacts` may be a plain path or `{source, destination, exclude, service}` (service = compose service name,
  e.g. capture DB state from a `postgres` service).
- Built-in agents include **`nop`** (does nothing) and **`oracle`** (runs `solution/solve.sh`) — **no API key, no
  model calls**. This is why the probe needed no credentials.

## 4. The synthetic task (fully local, no business data, no LLM)

Files: `/tmp/harbor-scratch/smoke/` (reproducible; scratch only, **not committed**).

- `environment/Dockerfile`: `FROM python:3.13-slim`, `WORKDIR /app`, `RUN mkdir -p /app/out` (base image already local).
- `instruction.md`: "create `/app/out/status.txt` containing exactly `status=READY` + newline".
- `solution/solve.sh`: `printf 'status=READY\n' > /app/out/status.txt` (the deterministic state change).
- `tests/test_outputs.py` (hidden; never copied into the agent container because verifier is `separate`):
  - `test_file_exists` — `/app/out/status.txt` is a file
  - `test_exact_content` — content == `"status=READY\n"`
  - `test_no_extra_state` — `/app/out/unexpected.txt` absent
- `tests/test.sh`: runs `pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA`; `1`/`0` → `/logs/verifier/reward.txt`.

`harbor lint ./smoke` → **exit 0** (clean). Two lint errors were fixed first and are worth recording:
`network_mode = "none"` is invalid (must be `"no-network"`); `authors` must be objects `{name,email}`, not strings.

## 5. Actual run — command and evidence

```bash
cd /tmp/harbor-scratch
/tmp/harbor-eval-venv/bin/harbor run -p ./smoke -a oracle \
  -o /tmp/harbor-scratch/jobs --job-name oracle-1 --yes
```

**Exit code 0. Total runtime 3m38s** (dominated by first-time image builds). Verbatim tail of the run:

```
  1/1 Mean: 1.000 ━━━━━━━━━━━━━━━━━━━━━━━━━ 0:03:38
adhoc • oracle
 Trials  Exceptions  Mean
      1           0  1.000
 Reward  Count
 1.0         1
Total runtime: 3m 38s
Results written to /tmp/harbor-scratch/jobs/oracle-1/result.json
```

Verifier (`separate` container) output — `/tmp/harbor-scratch/jobs/oracle-1/smoke__8MtYJFr/verifier/test-stdout.txt`:

```
collected 3 items
../tests/test_outputs.py ...                                             [100%]
PASSED ../tests/test_outputs.py::test_file_exists
PASSED ../tests/test_outputs.py::test_exact_content
PASSED ../tests/test_outputs.py::test_no_extra_state
3 passed in 0.06s
```

- `verifier/reward.txt` → `1`
- `verifier/ctrf.json` → `{'tests': 3, 'passed': 3, 'failed': 0, ...}`
- Trial result `.../smoke__8MtYJFr/result.json`: `verifier_environment_mode: "separate"`, `exception_info: null`,
  `started_at 05:41:31Z → finished_at 05:44:53Z`.
- Collected artifact on host: `.../artifacts/app/out/status.txt` == `status=READY` (exactly what was declared).
- Job `config.json`, `job.log`, `lock.json` (task digest lockfile) also written under `jobs/oracle-1/`.

Job/result layout on disk:

```
jobs/oracle-1/
  config.json  job.log  lock.json  result.json
  smoke__8MtYJFr/
    agent/oracle.txt           # oracle agent transcript (empty: no model turns)
    artifacts/app/out/status.txt
    artifacts/manifest.json    # artifact manifest
    verifier/reward.txt  verifier/ctrf.json  verifier/test-stdout.txt
    result.json  config.json  lock.json  trial.log
```

### Negative case — NOT executed (timebox)

The planned negative check was `harbor run -p ./smoke -a nop ...` (nop agent makes no change → `test_exact_content`
fails → reward 0). It was **not run**: the timebox expired and Docker capacity was needed elsewhere. The mechanism is
verified by construction (reward = `1` iff pytest exits 0; `test-output`/reward plumbing proven by the passing run), but
**fail-path discrimination is unproven by execution** and remains a cheap follow-up (~1 min once images are cached).

## 6. Isolation and cleanup observations

Baseline/after snapshots: `/tmp/harbor-scratch/{ps,net,vol}-before.txt` vs `-after.txt` / `-final.txt`.

- **Containers**: Harbor created project-scoped containers (observed mid-run:
  `smoke__8mtyjfr__verifier__trial-harbor-docker-egress-control-sidecar-1`). After the job:
  `docker ps -a | grep -Ei 'harbor|smoke__'` → **none**. No orphaned agent/verifier containers.
- **Networks**: `docker network ls` diff before/after → **no new networks** remained (Harbor creates per-trial compose
  networks and removes them).
- **Volumes**: the raw volume diff showed 2 anonymous volumes, but inspection proved they belong to an unrelated
  concurrently-running `auth-cache-test-*` stack (volume in use by those containers, created in the same window) —
  **no Harbor volume leak**. `docker volume rm` was attempted only after confirming they were not mine; it failed with
  "volume is in use" and they were left untouched.
- **Images**: Harbor leaves reusable images by design: `harbor-prebuilt:harbor-docker-egress-control-sidecar--<hash>`
  (75 MB) and per-task `hb__<hash>` images. This is a normal cache, not a leak, but it does grow the image store.
- **Scaffolding pollution**: `harbor init` created `tests/__pycache__/` inside the task dir (harmless; the repo copy
  must not include it).
- **Isolation**: agent phase ran with `network_mode = "no-network"`; task had no credentials and no host mounts. The
  verifier ran in a **separate container** that never saw the agent's full filesystem, only the declared artifact path —
  the strongest isolation signal observed. Harbor also reported a `harbor-docker-egress-control-sidecar` container,
  i.e. network policy is enforced by a sidecar, not just compose flags.
- **No host project mount by default**: the task dir is *built into* the image (`COPY`), not bind-mounted; Evalith's
  "run against a local project" would need either `COPY` of the repo into `environment/Dockerfile`, an artifact-style
  mount, or a custom environment provider (not exercised here).
- **No repo mutation**: the ticket workspace was not modified except this evidence file; all scratch under `/tmp`.

## 7. Capability gaps / fit for Evalith

| Evalith need | Harbor 0.25.0 support | Evidence / caveat |
|---|---|---|
| Non-conversation **state** tasks (files, DB rows, service responses) | **Strong**: task = environment + instruction + hidden verifier; verifier inspects state, not transcript | proven: file-state task, 3 hidden tests, reward from pytest |
| **Hidden independent verifier** | **Strong**: `environment_mode = "separate"` + `tests/Dockerfile`; tests never enter agent env | proven: separate verifier container passed all 3 checks |
| **Artifacts** collection | **Strong**: `artifacts` (paths or `{source,destination,service}`), host `artifacts/` + `manifest.json`; per-step artifacts | proven: `/app/out/status.txt` mirrored to host |
| **Local project mounting** | **Weak/indirect**: no documented host bind-mount of a project dir into the sandbox; repo must be baked into the environment image (or provided via a custom environment/provider). Not tested. | task dir is build context, not a mount |
| **Async / long-running services** | **Medium-good**: compose-style environments with `healthcheck`, `verifier.collect` against services (e.g. `service = "postgres"`), per-phase timeouts, `--agent-setup-timeout-multiplier` etc. Docker environment is compose-capable. Not exercised in this probe. | `task schema` documents `service`, healthcheck, collect |
| **Budget / model control** | **Strong for LLM agents**: `--model`, `--effort`, `--ak` agent kwargs, per-trial token/cost accounting (`result.json` stats: `n_input_tokens`, `cost_usd`), retries, timeouts. **N/A for non-LLM "agents"**: oracle/nop are deterministic and burn no tokens | `result.json` has cost/token fields (null here because oracle made no calls) |
| Cloud/remote sandboxes | Broad: modal, e2b, daytona, runloop, ec2, gke, beam, … via extras | from PyPI extras and `--env` list |
| Deterministic CI-style reruns | `lock.json` task digests, `--diff` reuse/regrade preview, caching | observed `lock.json`; `--diff` not exercised |

Other observations:
- Startup cost is real on a cold image store: **3m38s** for a 3-file task (two image builds, one sidecar build, plus
  pulls). Expect ~10–60 s per trial once cached.
- Harbor emits a LiteLLM warning about fetching a remote cost map over the network (harmless; falls back to a local
  backup) — this is noise for non-LLM agents.
- macOS/Docker Desktop worked out of the box; no Linux-only requirement hit in this probe.

## 8. Verdict

**Supported (with caveats).** Harbor 0.25.0 (Apache-2.0) is a credible execution backend for Evalith's core loop —
synthetic Docker environment → deterministic agent action → **hidden, separate** verifier → machine-readable
reward/artifacts — and it ran end-to-end here with **no API keys and no model calls** using the built-in `oracle`
agent (reward `1.0`, 3/3 verifier tests, exit 0). Cleanup of containers/networks was correct.

Caveats for Evalith adoption:
1. **Fail-path not executed** in this probe (negative `nop` run skipped on timebox) — one cheap run closes it.
2. **Local project mounting is the main design gap**: plan on baking the project into the environment image or writing
   a custom environment provider; do not assume a host bind mount.
3. **Long-running/async service tasks** rely on compose + `verifier.collect`; not exercised here — validate with a
   Postgres-backed synthetic task before committing.
4. Cold-start build time and residual image cache (75 MB sidecar + `hb__*` images) should be budgeted in CI.

## 9. Reproduction paths (scratch, uncommitted)

- venv: `/tmp/harbor-eval-venv` (harbor 0.25.0)
- task: `/tmp/harbor-scratch/smoke/` (`task.toml`, `instruction.md`, `environment/Dockerfile`,
  `tests/{Dockerfile,test.sh,test_outputs.py}`, `solution/solve.sh`)
- run log: `/tmp/harbor-scratch/run-oracle.log`
- results: `/tmp/harbor-scratch/jobs/oracle-1/` (`result.json`, `smoke__8MtYJFr/verifier/*`, `artifacts/`)
- docker snapshots: `/tmp/harbor-scratch/{ps,net,vol}-{before,after,final}.txt`

Reproduce:

```bash
python3 -m venv /tmp/harbor-eval-venv && /tmp/harbor-eval-venv/bin/pip install harbor
cd /tmp/harbor-scratch && /tmp/harbor-eval-venv/bin/harbor run -p ./smoke -a oracle -o ./jobs --yes
# negative: ... -a nop ...   → expected reward 0
```

**These `/tmp` paths are scratch and are not committed to the ticket repo.**
