"""The local ChatGPT login (codex CLI) inference channel is removed.

Legacy database rows keep their history but must fail every new request with
an explicit message; creation and the status endpoint are gone. These tests
run without any real model call or CLI process.
"""
from __future__ import annotations

import pytest
from conftest import create_stub_model, import_project
from evalith.model_gateway import ModelError
from fastapi.testclient import TestClient


def test_codex_local_provider_creation_is_rejected_with_removal_message(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/model-configs",
        json={
            "name": "Local account",
            "provider": "codex_local",
            "model_name": "gpt-6-luna",
        },
    )
    assert response.status_code == 422, response.text
    assert "已移除" in response.json()["error"]


def test_legacy_codex_local_rows_fail_requests_and_connection_tests(
    client: TestClient,
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "legacy",
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "model_name": "gpt-6-luna",
        },
    ).json()
    with client.app.state.db.connection() as connection:
        connection.execute(
            "UPDATE model_configs SET provider='codex_local' WHERE id=?",
            (model["id"],),
        )
    listing = client.get("/api/model-configs").json()["items"]
    assert any(item["provider"] == "codex_local" for item in listing), listing

    tested = client.post(f"/api/model-configs/{model['id']}/test")
    assert tested.status_code == 200, tested.text
    payload = tested.json()
    assert payload["ok"] is False
    assert "已移除" in payload["message"]

    gateway = client.app.state.service.gateway_for(model["id"])
    with pytest.raises(ModelError, match="已移除"):
        gateway.complete_json("system", {"task": "understanding"})


def test_local_model_status_endpoint_is_removed(client: TestClient) -> None:
    assert client.get("/api/local-model/status").status_code == 404


def test_binding_legacy_codex_model_is_rejected_at_selection_time(
    client: TestClient, project_root
) -> None:
    stub = create_stub_model(client)
    legacy = client.post(
        "/api/model-configs",
        json={
            "name": "legacy-bind",
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "model_name": "gpt-6-luna",
        },
    ).json()
    with client.app.state.db.connection() as connection:
        connection.execute(
            "UPDATE model_configs SET provider='codex_local' WHERE id=?",
            (legacy["id"],),
        )

    created = client.post(
        "/api/projects",
        json={
            "name": "Bind check",
            "root_path": str(project_root),
            "model_config_id": legacy["id"],
        },
    )
    assert created.status_code == 422, created.text
    assert "已移除" in created.json()["error"]

    project = import_project(
        client, project_root, model_config_id=stub["id"], name="Approval Agent"
    ).json()["project"]
    client.post(f"/api/projects/{project['id']}/continue")
    assigned = client.put(
        f"/api/projects/{project['id']}/model",
        json={"model_config_id": legacy["id"]},
    )
    assert assigned.status_code == 422, assigned.text
    assert "已移除" in assigned.json()["error"]

    grader = client.post(
        f"/api/projects/{project['id']}/graders",
        json={
            "name": "Answer correctness",
            "description": "Check evidence",
            "rubric": "Answer must match the observed facts",
            "steps": ["Read evidence", "Compare answer"],
            "check": {"type": "judge", "expected": "Match facts"},
            "model_config_id": legacy["id"],
            "threshold": 0.9,
        },
    )
    assert grader.status_code == 422, grader.text
    assert "已移除" in grader.json()["error"]
