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
    assert "sk-json-secret-value" not in request["body"]
    assert "sk-prefixed-secret" not in request["body"]
    assert "db-prefixed-secret" not in request["body"]
    assert "eu-central" in request["body"]
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


def test_upstream_error_echoing_configured_key_is_scrubbed(
    client: TestClient, project_root: Path, recording_server, settings
) -> None:
    _RecordingHandler.fail = True
    _RecordingHandler.fail_body = f"Incorrect API key provided: {SECRET_KEY}"
    model = client.post(
        "/api/model-configs",
        json={
            "name": "echo",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
            "api_key": SECRET_KEY,
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert detail["project"]["analysis_error"]
    assert SECRET_KEY not in str(detail)
    assert "[REDACTED]" in detail["project"]["analysis_error"]
    connection = client.post(f"/api/model-configs/{model['id']}/test")
    assert SECRET_KEY not in str(connection.json())
    import sqlite3

    connection_db = sqlite3.connect(settings.database_path)
    try:
        rows = connection_db.execute("SELECT content, payload FROM messages").fetchall()
        errors = connection_db.execute(
            "SELECT analysis_error FROM projects"
        ).fetchall()
    finally:
        connection_db.close()
    assert SECRET_KEY not in str(rows) + str(errors)


def test_literal_configured_key_is_scrubbed_from_content(
    client: TestClient,
    project_root: Path,
    recording_server,
    settings,
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "literal-key",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
            "api_key": SECRET_KEY,
        },
    ).json()
    detail = import_project(
        client,
        project_root,
        model_config_id=model["id"],
        supplemental=[
            {"title": "note", "content": f"the configured value is {SECRET_KEY}"}
        ],
    )
    assert detail.status_code == 201, detail.text
    assert SECRET_KEY not in detail.text

    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "understanding": {
            "summary": detail.json()["understanding"]["summary"],
            "agent_or_flow": detail.json()["understanding"]["agent_or_flow"],
            "known": detail.json()["understanding"]["known"],
            "inferred": detail.json()["understanding"]["inferred"],
            "unknowns": detail.json()["understanding"]["unknowns"],
            "sufficient": False,
            "sufficient_reason": detail.json()["understanding"]["sufficient_reason"],
        },
    }
    chat = client.post(
        f"/api/projects/{detail.json()['project']['id']}/messages",
        json={"content": f"please use {SECRET_KEY} here"},
    )
    assert chat.status_code == 200, chat.text
    assert SECRET_KEY not in chat.text
    for recorded in _RecordingHandler.requests:
        assert SECRET_KEY not in recorded["body"]

    import sqlite3

    connection = sqlite3.connect(settings.database_path)
    try:
        rows = connection.execute("SELECT content, payload FROM messages").fetchall()
        project_row = connection.execute("SELECT supplemental FROM projects").fetchone()
    finally:
        connection.close()
    assert SECRET_KEY not in str(rows) + str(project_row)


def test_child_loggers_redact_credentials(client: TestClient, caplog) -> None:
    logger = logging.getLogger("evalith.model")
    with caplog.at_level(logging.DEBUG, logger="evalith.model"):
        logger.error("upstream said OPENAI_API_KEY=%s", SECRET_KEY)
    assert SECRET_KEY not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_supplemental_and_chat_are_redacted(
    client: TestClient,
    project_root: Path,
    recording_server,
    settings,
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "redaction",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
            "api_key": SECRET_KEY,
        },
    ).json()
    detail = import_project(
        client,
        project_root,
        model_config_id=model["id"],
        supplemental=[
            {
                "title": "OPENAI_API_KEY=title-secret-value",
                "content": "DB_PASSWORD=supplement-secret-value\nsafe context",
            }
        ],
    )
    assert detail.status_code == 201, detail.text
    first = detail.json()
    assert "title-secret-value" not in str(first)
    assert "supplement-secret-value" not in str(first)
    assert "safe context" in str(first)

    _RecordingHandler.body_override = {
        "reply": "收到补充。",
        "continue_requested": False,
        "understanding": {
            "summary": first["understanding"]["summary"],
            "agent_or_flow": first["understanding"]["agent_or_flow"],
            "known": first["understanding"]["known"],
            "inferred": first["understanding"]["inferred"],
            "unknowns": first["understanding"]["unknowns"],
            "sufficient": False,
            "sufficient_reason": first["understanding"]["sufficient_reason"],
        },
    }
    chat = client.post(
        f"/api/projects/{first['project']['id']}/messages",
        json={"content": "OPENAI_API_KEY=chat-secret-value\nplease continue"},
    )
    assert chat.status_code == 200, chat.text
    assert "chat-secret-value" not in chat.text

    for recorded in _RecordingHandler.requests:
        for secret in (
            "title-secret-value",
            "supplement-secret-value",
            "chat-secret-value",
        ):
            assert secret not in recorded["body"]

    import sqlite3

    connection = sqlite3.connect(settings.database_path)
    try:
        rows = connection.execute(
            "SELECT content, payload FROM messages"
        ).fetchall()
        project_row = connection.execute(
            "SELECT supplemental FROM projects"
        ).fetchone()
    finally:
        connection.close()
    stored = str(rows) + str(project_row)
    for secret in (
        "title-secret-value",
        "supplement-secret-value",
        "chat-secret-value",
    ):
        assert secret not in stored


def test_stub_connection_test_is_clearly_labelled(client: TestClient) -> None:
    model = create_stub_model(client)
    response = client.post(f"/api/model-configs/{model['id']}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "替身" in body["message"]
