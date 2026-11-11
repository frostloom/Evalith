from pathlib import Path

import pytest
from evalith.api import create_app
from evalith.config import Settings
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "backend, fields",
    [
        (
            "local_command",
            {"command": ["python", "agent.py"], "working_directory": "/tmp/agent"},
        ),
        ("http_api", {"base_url": "http://127.0.0.1:8800/evaluate"}),
        ("harbor", {"command": ["harbor"], "working_directory": "/tmp/tasks"}),
    ],
)
def test_executor_definitions_persist_separately_without_running(
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
    backend: str,
    fields: dict,
) -> None:
    marker = tmp_path / "must-not-run"
    if backend == "local_command":
        fields["command"] = ["touch", str(marker)]
    response = client.post(
        "/api/executor-configs",
        json={"name": "My runner", "backend": backend, **fields},
    )
    assert response.status_code == 201
    saved = response.json()
    assert saved["execution_available"] is False
    assert saved["verified"] is False
    with TestClient(create_app(settings)) as reopened:
        items = reopened.get("/api/executor-configs").json()["items"]
        assert items[0]["id"] == saved["id"]
        assert items[0]["command"] == fields.get("command", [])
        assert reopened.get("/api/model-configs").json()["items"] == []
        changed = reopened.put(
            f"/api/executor-configs/{saved['id']}",
            json={
                "name": "Renamed",
                "backend": backend,
                "timeout_seconds": 90,
                **fields,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["timeout_seconds"] == 90
        assert (
            reopened.delete(f"/api/executor-configs/{saved['id']}").status_code == 204
        )
        assert reopened.get("/api/executor-configs").json()["items"] == []
    assert not marker.exists()
    assert b"must-not-run" not in settings.database_path.read_bytes()


@pytest.mark.parametrize(
    "payload",
    [
        {"backend": "unknown", "command": ["echo"]},
        {"backend": "http_api", "base_url": "file:///etc/passwd"},
        {"backend": "http_api", "base_url": "https://user:password@example.com"},
        {"backend": "local_command", "command": "echo hello"},
        {"backend": "local_command", "command": ["agent", "--api-key", "secret"]},
        {"backend": "harbor", "command": ["harbor"], "timeout_seconds": -1},
    ],
)
def test_executor_validation_does_not_save_invalid_or_credential_values(
    client: TestClient, payload: dict
) -> None:
    assert (
        client.post(
            "/api/executor-configs", json={"name": "Bad runner", **payload}
        ).status_code
        == 422
    )
    assert client.get("/api/executor-configs").json()["items"] == []


def test_executor_conflicts_missing_ids_and_origin_guard(client: TestClient) -> None:
    body = {"name": "Runner", "backend": "local_command", "command": ["echo"]}
    assert client.post("/api/executor-configs", json=body).status_code == 201
    assert client.post("/api/executor-configs", json=body).status_code == 409
    assert client.delete("/api/executor-configs/missing").status_code == 404
    assert client.put("/api/executor-configs/missing", json=body).status_code == 404
    assert (
        client.post(
            "/api/executor-configs",
            json=body,
            headers={"origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
