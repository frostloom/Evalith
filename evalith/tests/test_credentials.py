from __future__ import annotations

import json
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
    assert "AKIAEXAMPLESECRET" not in request["body"]
    assert "synthetic-secret-value" not in request["body"]
    assert "synthetic-password" not in request["body"]
    assert "synthetic-db-pass" not in request["body"]
    assert "synthetic-app-db-pass" not in request["body"]
    assert "synthetic-db-pwd" not in request["body"]
    assert "synthetic-yaml-db-pass" not in request["body"]
    assert "synthetic-yaml-db-pwd" not in request["body"]
    assert "raw-private-key-value" not in request["body"]
    assert "synthetic-signing-secret" not in request["body"]
    assert "sk-yaml-project-secret" not in request["body"]
    assert "registry-secret-value" not in request["body"]
    assert "ghp_syntheticGitToken" not in request["body"]
    assert "abc/def+ghi==" not in request["body"]
    assert "sk-quoted-yaml-secret" not in request["body"]
    assert "sk-sequence-yaml-secret" not in request["body"]
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


def test_paid_models_are_disabled_by_default(tmp_path: Path) -> None:
    from evalith.config import Settings

    assert Settings(data_dir=tmp_path).allow_paid_models is False


def test_existing_paid_model_is_disabled_after_restart(
    client: TestClient, settings, project_root: Path, recording_server
) -> None:
    from dataclasses import replace

    from evalith.api import create_app

    model = client.post(
        "/api/model-configs",
        json={
            "name": "persisted-paid",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()

    disabled = replace(settings, allow_paid_models=False)
    with TestClient(create_app(disabled)) as other:
        response = other.post(f"/api/projects/{detail['project']['id']}/reanalyse")
        assert response.status_code == 200, response.text
        refreshed = response.json()
        assert "付费模型默认禁用" in refreshed["understanding"]["error"]
        errors = [
            item
            for item in refreshed["messages"]
            if item["payload"]["kind"] == "error"
            and item["payload"]["stage"] == "analysis"
        ]
        assert errors
        assert errors[-1]["sent_scope"]["files_sent"] == 0
        assert errors[-1]["sent_scope"]["bytes_sent"] == 0
        assert all(
            item["sent"] is False for item in errors[-1]["sent_scope"]["sources"]
        )
        assert errors[-1]["payload"]["prepared_scope"]["files_sent"] > 0
        errors = [
            item
            for item in refreshed["messages"]
            if item["payload"]["kind"] == "error"
            and item["payload"]["stage"] == "analysis"
        ]
        assert errors
        assert errors[-1]["sent_scope"]["files_sent"] == 0
        assert errors[-1]["sent_scope"]["bytes_sent"] == 0
        assert all(
            item["sent"] is False for item in errors[-1]["sent_scope"]["sources"]
        )
        assert errors[-1]["payload"]["prepared_scope"]["files_sent"] > 0


def test_rfc6750_bearer_tokens_are_redacted() -> None:
    from evalith.security import redact_text

    for token in ("/private-token==", "abc/def+ghi==", "abc~def="):
        redacted = redact_text(f"Authorization: Bearer {token}\n")
        assert token not in redacted
        assert "[REDACTED]" in redacted


def test_git_token_url_is_redacted() -> None:
    from evalith.security import redact_text

    redacted = redact_text("https://ghp_syntheticGitToken@github.com\n")
    assert "ghp_syntheticGitToken" not in redacted
    assert "[REDACTED]" in redacted


def test_yarn_registry_token_is_redacted() -> None:
    from evalith.security import redact_text

    redacted = redact_text('npmAuthToken: "registry-secret-value"\n')
    assert "registry-secret-value" not in redacted
    assert "[REDACTED]" in redacted


def test_yaml_block_scalar_secret_is_redacted() -> None:
    from evalith.security import redact_text

    text = (
        "api_key: |\n  sk-yaml-project-secret\n"
        '"quoted_key": |\n  sk-quoted-yaml-secret\n'
        "tokens:\n  - secret_key: |\n      sk-sequence-yaml-secret\n"
    )
    redacted = redact_text(text)
    for secret in (
        "sk-yaml-project-secret",
        "sk-quoted-yaml-secret",
        "sk-sequence-yaml-secret",
        "synthetic-yaml-db-pass",
        "synthetic-yaml-db-pwd",
    ):
        assert secret not in redacted
    assert "[REDACTED]" in redacted


def test_malformed_direction_cannot_smuggle_configured_key(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "summary": "ok",
        "agent_or_flow": "",
        "known": [{"text": "policy", "source": "README.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "direction-leak",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
            "api_key": SECRET_KEY,
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "direction_update": {SECRET_KEY: "x"},
        "understanding": {
            "summary": "ok",
            "agent_or_flow": "",
            "known": [{"text": "policy", "source": "README.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": "pending",
        },
    }
    response = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "补充"},
    )
    assert response.status_code == 200, response.text
    assert SECRET_KEY not in response.text
    refreshed = client.get(f"/api/projects/{detail['project']['id']}")
    assert SECRET_KEY not in refreshed.text


def test_late_saved_credential_is_scrubbed_from_history(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "summary": "ok",
        "agent_or_flow": "",
        "known": [],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    selected = client.post(
        "/api/model-configs",
        json={
            "name": "selected-history",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(
        client, project_root, model_config_id=selected["id"]
    ).json()
    project_id = detail["project"]["id"]
    other = 'other"key\\value'
    first = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": f"remember {other} temporarily"},
    )
    assert first.status_code == 200, first.text
    client.post(
        "/api/model-configs",
        json={
            "name": "late-other",
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "model_name": "fake",
            "api_key": other,
        },
    )
    second = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "继续"}
    )
    assert second.status_code == 200, second.text
    body = _RecordingHandler.requests[-1]["body"]
    assert "other" not in body
    assert "other%22key%5Cvalue" not in body


def test_other_saved_credentials_are_redacted(
    client: TestClient, tmp_path: Path, recording_server
) -> None:
    other = "other/key+value"
    encoded = "other%2Fkey%2Bvalue"
    root = tmp_path / "cross-config-secret"
    root.mkdir()
    (root / "README.md").write_text(
        "x" * 5_990 + other + "y" * 100, encoding="utf-8"
    )
    client.post(
        "/api/model-configs",
        json={
            "name": "other-config",
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "model_name": "fake",
            "api_key": other,
        },
    )
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "summary": "ok",
        "agent_or_flow": "",
        "known": [],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    selected = client.post(
        "/api/model-configs",
        json={
            "name": "selected-config",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(
        client,
        root,
        name=f"Project {other}",
        model_config_id=selected["id"],
        supplemental=[{"title": "凭据", "content": f"please use {encoded} here"}],
    ).json()
    assert other not in json.dumps(detail["messages"], ensure_ascii=False)
    assert encoded not in json.dumps(detail["messages"], ensure_ascii=False)
    assert other not in json.dumps(
        detail["understanding"], ensure_ascii=False
    )
    assert encoded not in _RecordingHandler.requests[-1]["body"]
    project_id = detail["project"]["id"]
    chat = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": f"please use {encoded} here"},
    )
    assert chat.status_code == 200, chat.text
    serialized = json.dumps(chat.json()["messages"], ensure_ascii=False)
    assert other not in serialized
    assert encoded not in serialized
    assert other not in _RecordingHandler.requests[-1]["body"]
    assert encoded not in _RecordingHandler.requests[-1]["body"]
    refreshed = client.get(f"/api/projects/{project_id}").json()
    serialized = json.dumps(refreshed["messages"], ensure_ascii=False)
    assert other not in serialized
    assert encoded not in serialized


def test_signing_secret_is_redacted() -> None:
    from evalith.security import redact_text

    text = 'JWT_SECRET_KEY = "synthetic-signing-secret"\n'
    redacted = redact_text(text)
    assert "synthetic-signing-secret" not in redacted
    assert "[REDACTED]" in redacted


def test_private_key_assignment_is_redacted() -> None:
    from evalith.security import redact_text

    redacted = redact_text('private_key = "raw-private-key-value"\n')
    assert "raw-private-key-value" not in redacted
    assert "[REDACTED]" in redacted


def test_password_aliases_are_redacted() -> None:
    from evalith.security import redact_text

    for line, secret in (
        ('DB_PASS = "synthetic-db-pass"', "synthetic-db-pass"),
        ('APP_DB_PASS = "synthetic-app-db-pass"', "synthetic-app-db-pass"),
        ('DB_PWD = "synthetic-db-pwd"', "synthetic-db-pwd"),
    ):
        redacted = redact_text(line)
        assert secret not in redacted
        assert "[REDACTED]" in redacted


def test_withdrawal_persists_when_paid_models_are_disabled(
    client: TestClient, settings, project_root: Path, recording_server
) -> None:
    from dataclasses import replace

    from evalith.api import create_app

    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": True,
        "understanding": {
            "summary": "sufficient",
            "agent_or_flow": "",
            "known": [],
            "inferred": [],
            "unknowns": [],
            "sufficient": True,
            "sufficient_reason": "enough",
        },
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "withdrawal-disabled",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    continued = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "继续"}
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["understanding"]["user_continued"] is True

    disabled = replace(settings, allow_paid_models=False)
    with TestClient(create_app(disabled)) as other:
        refused = other.post(
            f"/api/projects/{project_id}/messages",
            json={"content": "我不同意继续。"},
        )
        assert refused.status_code == 502, refused.text
        after_consent = other.get(f"/api/projects/{project_id}").json()
        assert after_consent["understanding"]["user_continued"] is False

        insufficient = other.post(
            f"/api/projects/{project_id}/messages",
            json={"content": "资料还不够。"},
        )
        assert insufficient.status_code == 502, insufficient.text
        after_sufficiency = other.get(f"/api/projects/{project_id}").json()
        assert after_sufficiency["understanding"]["sufficient"] is False
        assert after_sufficiency["readiness"]["generation_allowed"] is False


def test_aws_credential_assignments_are_redacted() -> None:
    from evalith.security import redact_text

    text = (
        'AWS_ACCESS_KEY_ID = "AKIAEXAMPLESECRET"\n'
        'AWS_SECRET_ACCESS_KEY = "synthetic-secret-value"\n'
    )
    redacted = redact_text(text)
    assert "AKIAEXAMPLESECRET" not in redacted
    assert "synthetic-secret-value" not in redacted
    assert redacted.count("[REDACTED]") == 2


def test_connection_uri_credentials_are_redacted_in_inputs(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "uri-redaction",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(
        client,
        project_root,
        model_config_id=model["id"],
        supplemental=[
            {
                "title": "database",
                "content": "DATABASE_URL=redis://:supplement-password@cache:6379/0",
            }
        ],
    )
    assert detail.status_code == 201, detail.text
    assert "supplement-password" not in detail.text
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "understanding": detail.json()["understanding"],
    }
    chat = client.post(
        f"/api/projects/{detail.json()['project']['id']}/messages",
        json={"content": "DATABASE_URL=mysql://root:chat-password@db/app"},
    )
    assert chat.status_code == 200, chat.text
    for secret in ("supplement-password", "chat-password", "synthetic-password"):
        assert all(secret not in item["body"] for item in _RecordingHandler.requests)
        assert secret not in str(chat.json())


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


def test_successful_response_echo_is_scrubbed(
    client: TestClient,
    project_root: Path,
    recording_server,
    settings,
) -> None:
    _RecordingHandler.body_override = {
        "summary": f"Echoed credential {SECRET_KEY}",
        "agent_or_flow": f"bare {SECRET_KEY}",
        "known": [{"text": f"key {SECRET_KEY}", "source": "README.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": f"reason {SECRET_KEY}",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "response-echo",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
            "api_key": SECRET_KEY,
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert SECRET_KEY not in str(detail)
    assert detail["understanding"]["summary"].startswith("Echoed credential")

    _RecordingHandler.body_override = {
        "reply": f"reply {SECRET_KEY}",
        "continue_requested": False,
        "understanding": {
            "summary": f"summary {SECRET_KEY}",
            "agent_or_flow": "",
            "known": [],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": f"reason {SECRET_KEY}",
        },
    }
    chat = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "continue"},
    )
    assert chat.status_code == 200, chat.text
    assert SECRET_KEY not in chat.text
    import sqlite3

    connection = sqlite3.connect(settings.database_path)
    try:
        rows = connection.execute("SELECT content, payload FROM messages").fetchall()
        project_row = connection.execute("SELECT supplemental FROM projects").fetchone()
    finally:
        connection.close()
    assert SECRET_KEY not in str(rows) + str(project_row)


def test_provider_error_secret_crossing_truncation_boundary(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.fail = True
    _RecordingHandler.fail_body = "x" * 295 + SECRET_KEY + " trailing"
    model = client.post(
        "/api/model-configs",
        json={
            "name": "error-boundary",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
            "api_key": SECRET_KEY,
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert SECRET_KEY[:8] not in detail["project"]["analysis_error"]
    assert "REDA" in detail["project"]["analysis_error"]


def test_file_secret_crossing_excerpt_boundary(
    client: TestClient, project_root: Path, recording_server
) -> None:
    from evalith.project_access import MAX_EXCERPT_CHARS

    padding = "a" * (MAX_EXCERPT_CHARS - 5)
    (project_root / "docs" / "long.md").write_text(
        padding + SECRET_KEY + " trailing\n", encoding="utf-8"
    )
    model = client.post(
        "/api/model-configs",
        json={
            "name": "excerpt-boundary",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
            "api_key": SECRET_KEY,
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert SECRET_KEY[:8] not in str(detail)
    assert all(SECRET_KEY[:8] not in item["body"] for item in _RecordingHandler.requests)


def test_known_requires_resolvable_source(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "summary": "unsourced",
        "agent_or_flow": "",
        "known": [{"text": "unsupported fact", "source": ""}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "no source",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "unsourced",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert detail["project"]["analysis_error"]
    assert "known" in detail["project"]["analysis_error"]

    _RecordingHandler.body_override = {
        "summary": "bad path",
        "agent_or_flow": "",
        "known": [{"text": "unsupported fact", "source": "not-in-snapshot.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "no source",
    }
    second = client.post(
        "/api/projects",
        json={
            "name": "bad-path",
            "root_path": str(project_root),
            "model_config_id": model["id"],
        },
    ).json()
    assert second["project"]["analysis_error"]
    assert "来源无法核对" in second["project"]["analysis_error"]


def test_questions_and_quoted_instructions_do_not_open_gate(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]

    for text in (
        "继续前需要补充哪些资料？",
        "为什么认为依据足够？",
        "用户说“依据足够”，但我不确定。",
        "纠正：按钮文案应为“可以继续”。",
        "纠正：按钮文案是“点击继续”。",
        "请解释“继续”的含义。",
        "我拒绝继续。",
        "我不打算继续。",
        "纠正：继续按钮应位于右侧。",
        "纠正：依据足够是一个状态名称。",
        "机器人会继续处理请求。",
        "请先等我确认再继续。",
        "现在不应该继续。",
        "等补充材料到齐后才算依据足够。",
        "请勿继续。",
        "切勿继续。",
        "我会考虑继续。",
        "请检查继续读取文件的逻辑。",
        "我会不会继续。",
        "请在材料齐全后继续。",
        "请翻译成英文：继续。",
        "请将依据足够翻译成英文。",
        "现在没有必要继续。",
        "请在审批通过时继续。",
        "请判断可否继续。",
        "依据足够与否尚不清楚。",
        "我不认为依据足够。",
    ):
        response = client.post(
            f"/api/projects/{project_id}/messages", json={"content": text}
        )
        assert response.status_code == 200, response.text
        assert response.json()["readiness"]["generation_allowed"] is False
        assert response.json()["understanding"]["sufficient"] is False
        assert response.json()["understanding"]["user_continued"] is False


def test_child_loggers_redact_credentials(client: TestClient, caplog) -> None:
    logger = logging.getLogger("evalith.model")
    with caplog.at_level(logging.DEBUG, logger="evalith.model"):
        logger.error("upstream said OPENAI_API_KEY=%s", SECRET_KEY)
        logger.error("AWS_SECRET_ACCESS_KEY=%s", SECRET_KEY)
        logger.error("DB_PASS=%s", "synthetic-db-pass")
        logger.error("APP_DB_PASS=%s", "synthetic-app-db-pass")
        logger.error("DB_PWD=%s", "synthetic-db-pwd")
        logger.error("DB_PASS: |")
        logger.error("  synthetic-yaml-db-pass")
        logger.error('PRIVATE_KEY = "raw-private-key-value"')
        logger.error("DB_PWD: >")
        logger.error("  synthetic-yaml-db-pwd")
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
