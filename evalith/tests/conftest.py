from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from evalith.api import create_app
from evalith.config import Settings

SECRET_ENV = "OPENAI_API_KEY=sk-env-secret-123456"
SECRET_FILE = "token=sk-file-secret-abcdef"


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "synthetic-project"
    (root / "docs").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "secrets").mkdir()
    (root / ".git").mkdir()
    (root / "README.md").write_text(
        "# Approval Agent\n\nThis project runs a release approval agent.\n"
        "Only a release manager may publish an artifact.\n",
        encoding="utf-8",
    )
    (root / "docs" / "RELEASE_POLICY.md").write_text(
        "# Release policy\n\nA contributor may propose a release; only the release manager may publish.\n",
        encoding="utf-8",
    )
    (root / "docs" / "internal").mkdir()
    (root / "docs" / "internal" / "plan.md").write_text(
        "# Internal plan\nDo not send this outside the approved scope.\n",
        encoding="utf-8",
    )
    (root / "src" / "agent.py").write_text(
        "def can_publish(actor_role: str) -> bool:\n"
        "    return actor_role == 'release_manager'\n",
        encoding="utf-8",
    )
    (root / ".env").write_text(SECRET_ENV + "\n", encoding="utf-8")
    (root / "secrets" / "credentials.txt").write_text(SECRET_FILE + "\n", encoding="utf-8")
    (root / "notes.txt").write_text(
        'API_KEY = "sk-inline-secret-value"\n'
        "OPENAI_API_KEY=sk-prefixed-secret\n"
        "DB_PASSWORD=db-prefixed-secret\n"
        "AWS_ACCESS_KEY_ID=AKIAEXAMPLESECRET\n"
        "AWS_SECRET_ACCESS_KEY=synthetic-secret-value\n"
        "JWT_SECRET_KEY=synthetic-signing-secret\n"
        "The agent approves releases.\n",
        encoding="utf-8",
    )
    (root / ".yarnrc.yml").write_text(
        'npmAuthToken: "registry-secret-value"\n', encoding="utf-8"
    )
    (root / "config").mkdir()
    (root / "config" / "settings.json").write_text(
        '{"api_key": "sk-json-secret-value", "region": "eu-central"}\n',
        encoding="utf-8",
    )
    (root / "config" / "database.py").write_text(
        'DATABASE_URL = "postgresql://alice:synthetic-password@db/app"\n',
        encoding="utf-8",
    )
    (root / "config" / "application.yaml").write_text(
        'api_key: |\n  sk-yaml-project-secret\n'
        '"quoted_key": |\n  sk-quoted-yaml-secret\n'
        "tokens:\n  - secret_key: |\n      sk-sequence-yaml-secret\n",
        encoding="utf-8",
    )
    (root / "binary.dat").write_bytes(b"\x00\x01secret-binary\x02")
    (root / ".git" / "config").write_text("url = https://example.invalid\n", encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside-secret.txt").write_text("outside secret", encoding="utf-8")
    os.symlink(outside / "outside-secret.txt", root / "escape.txt")
    os.symlink(outside / "outside-secret.txt", root / "docs" / "leak.txt")
    return root


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "evalith.db",
        secret_key="test-secret-key",
        static_dir=tmp_path / "no-static",
        max_files=100,
        allow_paid_models=True,
    )


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def create_stub_model(client: TestClient, name: str = "stub") -> dict[str, Any]:
    response = client.post(
        "/api/model-configs",
        json={"name": name, "provider": "stub", "model_name": "stub-understanding"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def import_project(
    client: TestClient,
    root: Path,
    *,
    model_config_id: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    supplemental: list[dict[str, str]] | None = None,
    name: str = "Approval Agent",
) -> dict[str, Any]:
    response = client.post(
        "/api/projects",
        json={
            "name": name,
            "root_path": str(root),
            "model_config_id": model_config_id,
            "include_paths": include,
            "exclude_patterns": exclude,
            "supplemental": supplemental,
        },
    )
    return response


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _RecordingHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    fail = False
    fail_body: str | None = None
    body_override: dict[str, Any] | None = None

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        type(self).requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": raw.decode("utf-8", errors="replace"),
            }
        )
        if type(self).fail:
            self.send_response(500)
            self.end_headers()
            self.wfile.write((type(self).fail_body or "upstream failure").encode())
            return
        body = type(self).body_override or {
            "summary": "这是一个发布审批流程的初步理解。",
            "agent_or_flow": "release approval agent",
            "known": [
                {"text": "只有 release manager 可以发布。", "source": "docs/RELEASE_POLICY.md"}
            ],
            "inferred": [{"text": "存在发布门禁。", "basis": "政策文档标题"}],
            "unknowns": [{"text": "验收标准未知。", "why": "资料未写明"}],
            "sufficient": False,
            "sufficient_reason": "仍需确认验收标准。",
        }
        encoded = json.dumps(
            {"choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args: Any) -> None:
        return


@pytest.fixture()
def recording_server() -> Iterator[ThreadingHTTPServer]:
    _RecordingHandler.requests = []
    _RecordingHandler.fail = False
    _RecordingHandler.fail_body = None
    _RecordingHandler.body_override = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def outside_file(tmp_path: Path) -> Path:
    return tmp_path / "outside" / "outside-secret.txt"
