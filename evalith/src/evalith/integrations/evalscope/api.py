"""HTTP route that exports Evalith task records for EvalScope."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI

from ...evaluation_store import EvaluationStore
from ...service import WorkspaceError
from .exporter import export_eval_set


def install_evalscope_routes(app: FastAPI, workspace: Any, executors: Any, export_root: Path) -> None:
    root = Path(export_root).resolve()

    @app.post("/api/projects/{project_id}/exports/evalscope")
    def export_project(project_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        project = workspace.db.get_project(project_id)
        if project is None:
            raise WorkspaceError("项目不存在", status_code=404)
        snapshot = workspace.serialize_snapshot(workspace.db.get_snapshot(project["snapshot_id"]))
        if snapshot is None:
            raise WorkspaceError("项目缺少资料快照，请先重新扫描", status_code=409)

        task_ids = payload.get("task_ids") or []
        if not isinstance(task_ids, list) or not task_ids:
            raise WorkspaceError("task_ids 必须是非空数组", status_code=422)
        records = [EvaluationStore(workspace.db).get(project_id, "task", task_id) for task_id in task_ids]

        executor_id = payload.get("executor_id")
        executor = next(
            (item for item in executors.list() if item["id"] == executor_id),
            None,
        ) if executor_id else None

        requested = payload.get("out_path") or f"{project_id}/eval_set.v1.jsonl"
        candidate = Path(requested)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_relative_to(root):
            raise WorkspaceError("out_path 必须位于导出目录内", status_code=422)

        export_eval_set(records, snapshot=snapshot, executor=executor, out_path=candidate)
        return {"path": str(candidate), "task_count": len(records)}
