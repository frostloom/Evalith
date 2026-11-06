from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import _RecordingHandler, create_stub_model, import_project

SECRET_KEY = "sk-super-secret-model-key-987654"


def test_model_key_is_encrypted_and_never_returned(
    client: TestClient, settings
) -> None:
    response = client.post(
        "/api/model-configs",
        json={
            "name": "real",
            "provider": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model_name": "gpt-x",
            "api_key": SECRET_KEY,
        },
    )
    assert response.status_code == 201, response.text
    assert SECRET_KEY not in response.text
    assert response.json()["has_api_key"] is True

    listing = client.get("/api/model-configs")
    assert SECRET_KEY not in listing.text

    database_bytes = settings.database_path.read_bytes()
    assert SECRET_KEY.encode() not in database_bytes


def test_model_request_carries_key_only_in_authorization_header(
    client: TestClient,
    project_root: Path,
    recording_server,
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "recording",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
            "api_key": SECRET_KEY,
        },
    ).json()
    response = import_project(client, project_root, model_config_id=model["id"])
    assert response.status_code == 201, response.text
    assert _RecordingHandler.requests, "the model endpoint was not called"
    request = _RecordingHandler.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["Authorization"] == f"Bearer {SECRET_KEY}"
    assert SECRET_KEY not in request["body"]
    assert "sk-env-secret-123456" not in request["body"]
    assert "sk-file-secret-abcdef" not in request["body"]
    assert "sk-inline-secret-value" not in request["body"]
    assert "RELEASE_POLICY" in request["body"]
    assert "[REDACTED]" in request["body"]

    detail = response.json()
    sent_scope = next(
        item["sent_scope"] for item in detail["messages"] if item["role"] == "assistant"
    )
    assert SECRET_KEY not in str(sent_scope)
    assert "sk-env-secret-123456" not in str(sent_scope)


def test_credentials_do_not_reach_logs_or_errors(
    client: TestClient, project_root: Path, recording_server, caplog
) -> None:
    _RecordingHandler.fail = True
    with caplog.at_level(logging.DEBUG):
        model = client.post(
            "/api/model-configs",
            json={
                "name": "logging",
                "provider": "openai_compatible",
                "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
                "model_name": "fake",
                "api_key": SECRET_KEY,
            },
        ).json()
        detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert SECRET_KEY not in caplog.text
    assert SECRET_KEY not in str(detail)
    assert "sk-env-secret-123456" not in str(detail)


def test_child_loggers_redact_credentials(client: TestClient, caplog) -> None:
    logger = logging.getLogger("evalith.model")
    with caplog.at_level(logging.DEBUG, logger="evalith.model"):
        logger.error("upstream said api_key=%s", SECRET_KEY)
    assert SECRET_KEY not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_stub_connection_test_is_clearly_labelled(client: TestClient) -> None:
    model = create_stub_model(client)
    response = client.post(f"/api/model-configs/{model['id']}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "替身" in body["message"]
