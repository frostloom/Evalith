from __future__ import annotations

from typing import Any

from conftest import create_stub_model, import_project
from evalith.api import create_app
from evalith.evaluation_store import EvaluationStore
from fastapi.testclient import TestClient


def _result(identifier: str, status: str, passed_score: float | None) -> dict[str, Any]:
    return {
        "id": identifier,
        "task": {
            "task_id": "task_" + identifier,
            "version_id": "ver_" + identifier,
            "definition": {"title": identifier},
        },
        "status": status,
        "score": passed_score,
        "checks": [],
        "observation": None,
        "error": None,
        "started_at": "2026-11-20T00:00:00+00:00",
        "finished_at": None,
        "duration_ms": None,
    }


def test_restart_interrupts_in_flight_results_and_keeps_finished_ones(settings, project_root):
    app = create_app(settings)
    with TestClient(app) as client:
        model = create_stub_model(client)
        project = import_project(
            client, project_root, model_config_id=model["id"], include=["README.md"]
        ).json()["project"]
        pid = project["id"]
        client.post(f"/api/projects/{pid}/continue")
        store = EvaluationStore(client.app.state.service.db)
        run = store.create(
            pid,
            "run",
            {
                "name": "restart recovery",
                "tasks": [],
                "results": [
                    _result("in_flight", "running", None),
                    _result("already_passed", "passed", 1),
                ],
                "usage": {
                    "model_calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": None,
                },
                "cleanup_status": "not_started",
            },
            status="running",
        )

    with TestClient(create_app(settings)) as reopened:
        recovered = reopened.get(f"/api/projects/{pid}/runs/{run['id']}").json()

    assert recovered["status"] == "interrupted"
    assert recovered["cleanup_status"] == "unknown_after_restart"
    assert "服务已重启" in recovered["error"]
    by_id = {item["id"]: item for item in recovered["results"]}
    assert by_id["in_flight"]["status"] == "interrupted"
    assert "未完成" in by_id["in_flight"]["error"]
    assert by_id["in_flight"]["finished_at"]
    assert by_id["already_passed"]["status"] == "passed"
    assert by_id["already_passed"]["score"] == 1


def test_restart_does_not_reinterrupt_a_finished_run(settings, project_root):
    app = create_app(settings)
    with TestClient(app) as client:
        model = create_stub_model(client)
        project = import_project(
            client, project_root, model_config_id=model["id"], include=["README.md"]
        ).json()["project"]
        pid = project["id"]
        store = EvaluationStore(client.app.state.service.db)
        run = store.create(
            pid,
            "run",
            {
                "name": "finished",
                "tasks": [],
                "results": [_result("done", "passed", 1)],
                "cleanup_status": "completed",
            },
            status="completed",
        )

    with TestClient(create_app(settings)) as reopened:
        recovered = reopened.get(f"/api/projects/{pid}/runs/{run['id']}").json()

    assert recovered["status"] == "completed"
    assert recovered["cleanup_status"] == "completed"
    assert recovered["results"][0]["status"] == "passed"
