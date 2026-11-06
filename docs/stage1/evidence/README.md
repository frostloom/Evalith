# Stage-1 evidence

| File | What it is | How to regenerate |
| --- | --- | --- |
| `workbench-build-info.json` | Pinned source, version, dirty-input flag and the asserted patch list of the generated EE-free tree used for the run. | `python3 workbench/build.py --source <rhesis checkout>` then copy `workbench/.workbench/ee-free/BUILD_INFO.json`. |
| `workbench-smoke-1793935565.json` | EE-free backend/frontend smoke: community edition, project/model/Architect paths, frontend, EE/brand artifact checks. | `python3 workbench/smoke.py` with the stack from `workbench/run_local.sh`. |
| `evalith-tests.txt` | Last local run of the Python test suite (128 tests). | `cd evalith && uv run pytest -q`. |
| `evalith-web-tests.txt` | Frontend project-switch, stale-response and source-editor round-trip tests (13 tests). | `cd evalith/web && npm test`. |
| `workbench-project-before.png` | Before baseline: upstream Rhesis 0.20.1 project Overview in the EE-free tree, viewport 1440x900, light theme. | Open the workbench project page and capture with agent-browser. |
| `evalith-workspace-1440x900.png` | After: Evalith project workspace, same viewport/theme. | Import `examples/approval-agent`, open the project and capture. |
| `evalith-workspace-after.png` | Full-height workspace with conversation and composer. | Same, viewport 1440x1800. |
| `evalith-workspace-continue-after.png` | Workspace after the user chooses to continue; unknowns remain 2. | Click “表示可以继续”. |
| `evalith-home-after.png` | Home with the two synthetic project cards. | Import both `examples/*` projects. |
| `evalith-import-after.png` | Import form and the read boundary panel. | Open “导入本地项目”. |

All screenshots are actual application captures with synthetic data. No real business
data or real credentials are present.
