import json
from pathlib import Path

from conftest import create_stub_model, import_project
from evalith.evaluation_store import EvaluationStore


DEFINITION = {
    "title": "查余额",
    "category": "查询",
    "objective": "返回真实余额",
    "kind": "conversation",
    "input": {"turns": ["查一下余额"]},
    "checks": [
        {"type": "file_contains", "path": "notes.txt", "expected": "agent", "description": "检查"}
    ],
    "rubric": "回答引用真实余额",
    "source_refs": ["README.md"],
    "uncertainties": [],
}


def _seed(client, project_root: Path):
    model = create_stub_model(client)
    project = import_project(
        client,
        project_root,
        model_config_id=model["id"],
        include=["README.md", "notes.txt"],
    ).json()["project"]
    store = EvaluationStore(client.app.state.db)
    task = store.save_task(project["id"], {
        "definition": DEFINITION,
        "source_snapshot_id": project["snapshot_id"],
        "source_digest": project["snapshot_digest"],
    })
    executor = client.post(
        "/api/executor-configs",
        json={"name": "local http", "backend": "http_api", "base_url": "http://127.0.0.1:9105"},
    )
    assert executor.status_code == 201, executor.text
    return project, task, executor.json()


def test_export_endpoint_writes_eval_set(client, project_root):
    project, task, executor = _seed(client, project_root)
    response = client.post(
        f"/api/projects/{project['id']}/exports/evalscope",
        json={
            "task_ids": [task["id"]],
            "executor_id": executor["id"],
            "out_path": "demo/eval_set.v1.jsonl",
        },
    )
    assert response.status_code == 200, response.text
    path = Path(response.json()["path"])
    assert path.is_file()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["id"] == task["id"]
    assert rows[0]["exec"]["type"] == "agent_api"


def test_export_rejects_path_outside_export_root(client, project_root):
    project, task, executor = _seed(client, project_root)
    response = client.post(
        f"/api/projects/{project['id']}/exports/evalscope",
        json={
            "task_ids": [task["id"]],
            "executor_id": executor["id"],
            "out_path": "../../escape/eval_set.v1.jsonl",
        },
    )
    assert response.status_code == 422
