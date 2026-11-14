"""Evaluation asset/job routes, independent of the project conversation API."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import Body, FastAPI, Header
from fastapi.responses import JSONResponse

from .environments import EnvironmentManager
from .evaluation_assets import EvaluationAssets
from .evaluation_runner import BudgetStop, EvaluationRunner, RunCancelled
from .evaluation_store import EvaluationStore
from .model_gateway import ModelError
from .result_analysis import ResultAnalysis
from .service import WorkspaceError, WorkspaceService


def install_evaluation_routes(app: FastAPI, workspace: WorkspaceService) -> None:
    store = EvaluationStore(workspace.db)
    assets = EvaluationAssets(workspace, store)
    app.state.evaluation_store = store
    app.state.evaluation_assets = assets
    from .evaluation_library import install_library_routes
    install_library_routes(app, workspace, store)
    from .evaluation_calibration import install_calibration_routes
    install_calibration_routes(app, workspace, store)
    environments = EnvironmentManager(workspace, store)
    runner = EvaluationRunner(workspace, store, environments)
    app.state.environments = environments
    app.state.evaluation_runner = runner
    analysis = ResultAnalysis(workspace, store)
    app.state.result_analysis = analysis

    @app.get("/api/projects/{project_id}/analyses")
    def analysis_list(project_id: str):
        assets.list(project_id)
        return {"items": store.list(project_id, "analysis")}

    @app.get("/api/projects/{project_id}/analyses/{analysis_id}")
    def analysis_detail(project_id: str, analysis_id: str):
        return store.get(project_id, "analysis", analysis_id)

    @app.post("/api/projects/{project_id}/runs/{run_id}/analyses", status_code=202)
    def analysis_start(
        project_id: str, run_id: str, payload: dict[str, Any] = Body(default={})
    ):
        return analysis.start(project_id, run_id, payload)

    # No worker from a previous process can still report progress to this app.
    # Preserve its evidence and expose the uncertainty about orphan cleanup.
    with workspace.db.connection() as connection:
        active = connection.execute(
            "SELECT project_id,kind,id FROM evaluation_records WHERE status IN ('running','pending','preparing','cancelling') AND kind IN ('run','job','environment','analysis')"
        ).fetchall()
    for item in active:
        store.update(
            item["project_id"],
            item["kind"],
            item["id"],
            status="interrupted",
            error="服务已重启；已有记录保留，请重新启动未完成的操作",
            cleanup_status="unknown_after_restart",
        )

    @app.get("/api/projects/{project_id}/environments")
    def environment_list(project_id: str):
        workspace.db.get_project(project_id)
        return {
            "items": [
                environments.public(item)
                for item in store.list(project_id, "environment")
            ]
        }

    @app.post("/api/projects/{project_id}/environments/plan", status_code=201)
    def environment_plan(project_id: str, payload: dict[str, Any] = Body(...)):
        return environments.public(environments.plan(project_id, payload))

    @app.get("/api/projects/{project_id}/environments/{environment_id}")
    def environment_detail(project_id: str, environment_id: str):
        return environments.public(store.get(project_id, "environment", environment_id))

    @app.post(
        "/api/projects/{project_id}/environments/{environment_id}/confirm",
        status_code=202,
    )
    def environment_confirm(
        project_id: str, environment_id: str, payload: dict[str, Any] = Body(...)
    ):
        return environments.confirm(
            project_id, environment_id, str(payload.get("plan_digest", ""))
        )

    @app.get("/api/projects/{project_id}/runs")
    def run_list(project_id: str):
        workspace.db.get_project(project_id)
        return {
            "items": [runner.public(item) for item in store.list(project_id, "run")]
        }

    @app.post("/api/projects/{project_id}/runs", status_code=202)
    def run_start(project_id: str, payload: dict[str, Any] = Body(...)):
        return runner.start(project_id, payload)

    @app.post("/api/projects/{project_id}/runs/preview")
    def run_preview(project_id: str, payload: dict[str, Any]):
        return runner.preview(project_id, payload)

    @app.get("/api/projects/{project_id}/runs/{run_id}")
    def run_detail(project_id: str, run_id: str):
        return runner.public(store.get(project_id, "run", run_id))

    @app.post("/api/projects/{project_id}/runs/{run_id}/cancel")
    def run_cancel(project_id: str, run_id: str):
        return runner.cancel(project_id, run_id)

    @app.post("/api/projects/{project_id}/runs/{run_id}/model/v1/chat/completions")
    def model_bridge(
        project_id: str,
        run_id: str,
        payload: dict[str, Any] = Body(...),
        authorization: str = Header(default=""),
    ):
        token = (
            authorization.removeprefix("Bearer ")
            if authorization.startswith("Bearer ")
            else ""
        )
        try:
            return runner.bridge(project_id, run_id, token, payload)
        except BudgetStop as exc:
            store.update(project_id, "run", run_id, budget_stop_reason=str(exc))
            return JSONResponse(
                status_code=429,
                content={"error": {"message": str(exc), "type": "budget_stopped"}},
            )
        except RunCancelled:
            return JSONResponse(
                status_code=409,
                content={"error": {"message": "运行已取消", "type": "cancelled"}},
            )
        except ModelError as exc:
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "message": workspace._scrub_saved_secrets(str(exc)),
                        "type": "model_error",
                    }
                },
            )

    @app.post("/api/projects/{project_id}/runs/{run_id}/simulator/v1")
    def simulator_bridge(
        project_id: str,
        run_id: str,
        payload: dict[str, Any] = Body(...),
        authorization: str = Header(default=""),
    ):
        token = (
            authorization.removeprefix("Bearer ")
            if authorization.startswith("Bearer ")
            else ""
        )
        try:
            return runner.simulator(project_id, run_id, token, payload)
        except BudgetStop as exc:
            store.update(project_id, "run", run_id, budget_stop_reason=str(exc))
            return JSONResponse(
                status_code=429,
                content={"error": {"message": str(exc), "type": "budget_stopped"}},
            )
        except RunCancelled:
            return JSONResponse(
                status_code=409,
                content={"error": {"message": "运行已取消", "type": "cancelled"}},
            )
        except ModelError as exc:
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "message": workspace._scrub_saved_secrets(str(exc)),
                        "type": "model_error",
                    }
                },
            )

    @app.get("/api/projects/{project_id}/tasks")
    def tasks(project_id: str) -> dict[str, Any]:
        return {"items": assets.list(project_id)}

    @app.get("/api/projects/{project_id}/tasks/{task_id}")
    def task(project_id: str, task_id: str) -> dict[str, Any]:
        return store.get(project_id, "task", task_id)

    @app.post("/api/projects/{project_id}/tasks", status_code=201)
    def add_task(
        project_id: str, payload: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        return assets.add(project_id, payload)

    @app.get("/api/projects/{project_id}/tasks/{task_id}/versions")
    def versions(project_id: str, task_id: str) -> dict[str, Any]:
        return {"items": store.versions(project_id, task_id)}

    @app.put("/api/projects/{project_id}/tasks/{task_id}")
    def edit(
        project_id: str, task_id: str, payload: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        return assets.edit(project_id, task_id, payload)

    @app.get("/api/projects/{project_id}/jobs/{job_id}")
    def job(project_id: str, job_id: str) -> dict[str, Any]:
        return store.get(project_id, "job", job_id)

    @app.get("/api/projects/{project_id}/jobs")
    def jobs(project_id: str) -> dict[str, Any]:
        assets.list(project_id)  # Verify project identity even when no jobs exist.
        return {"items": store.list(project_id, "job")}

    def generate_job(project_id: str, payload: dict[str, Any], *, prepare: bool = False) -> dict[str, Any]:
        count = payload.get("count", 4)
        direction = payload.get("direction", "")
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not 1 <= count <= 12
            or not isinstance(direction, str)
            or len(direction) > 4000
        ):
            raise WorkspaceError(
                "生成数量为 1–12，评测方向最多 4000 字", status_code=422
            )
        with workspace._project_lock(project_id):
            detail = workspace.get_project_detail(project_id)
            if not detail["readiness"]["generation_allowed"]:
                raise WorkspaceError(
                    detail["readiness"]["reason"],
                    status_code=409,
                    code="generation_not_ready",
                )
            model = workspace.gateway_for(detail["project"]["model_config_id"])
            if model.config is None or model.config.provider == "stub":
                raise WorkspaceError(
                    "请先选择真实模型；离线演示不会生成真实评测资产",
                    status_code=422,
                    code="real_model_required",
                )
            if any(
                j["status"] in ("pending", "running")
                and j.get("operation") in {"generation", "preparation"}
                for j in store.list(project_id, "job")
            ):
                raise WorkspaceError(
                    "此项目已有题目生成任务在运行",
                    status_code=409,
                    code="generation_busy",
                )
            record = store.create(
                project_id,
                "job",
                {
                    "operation": "preparation" if prepare else "generation",
                    "count": count,
                    "direction": workspace._scrub_saved_secrets(direction),
                    "model": model.name,
                    "usage": None,
                    "result": None,
                    "error": None,
                },
            )

        def execute():
            store.update(project_id, "job", record["id"], status="running")
            try:
                operation = assets.prepare if prepare else assets.generate
                result = operation(project_id, count=count, direction=direction)
                store.update(
                    project_id,
                    "job",
                    record["id"],
                    status="completed",
                    usage=result["usage"],
                    result={
                        "task_ids": [item["id"] for item in result["items"]],
                        "generation_id": result["generation_id"],
                        "grader_ids": [g["id"] for g in result.get("graders", [])],
                        "test_set_id": result.get("test_set", {}).get("id"),
                    },
                )
            except Exception as exc:
                store.update(
                    project_id,
                    "job",
                    record["id"],
                    status="failed",
                    error=workspace._scrub_saved_secrets(str(exc))[:1500],
                )

        threading.Thread(
            target=execute, name="evalith-generation-" + record["id"], daemon=True
        ).start()
        return record

    @app.post("/api/projects/{project_id}/preparations", status_code=202)
    def prepare_assets(project_id: str, payload: dict[str, Any]):
        return generate_job(project_id, payload, prepare=True)

    @app.post("/api/projects/{project_id}/graders/synthesize")
    def synthesize_grader(project_id: str, payload: dict[str, Any]):
        from .evaluation_preparation import EvaluationPreparation
        if set(payload) != {"description"}:
            raise WorkspaceError("请仅提供评分要求 description", status_code=422)
        return EvaluationPreparation(workspace, store).synthesize_grader(project_id, payload["description"])

    @app.post("/api/projects/{project_id}/generate", status_code=202)
    def generate(
        project_id: str, payload: dict[str, Any] = Body(default={})
    ) -> dict[str, Any]:
        return generate_job(project_id, payload)

    @app.post("/api/projects/{project_id}/test-sets/generate", status_code=202)
    def generate_test_set(
        project_id: str, payload: dict[str, Any] = Body(default={})
    ) -> dict[str, Any]:
        return generate_job(project_id, payload)
