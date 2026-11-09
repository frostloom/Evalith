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
        'PRIVATE_KEY = "raw-private-key-value"\n'
        'GITHUB_PAT=github_pat_examplecredential\n' 
        "The agent approves releases.\n",
        encoding="utf-8",
    )
    (root / "bearer-token.txt").write_text(
        "Authorization: Bearer abc/def+ghi==\n", encoding="utf-8"
    )
    (root / ".git-credentials").write_text(
        "https://ghp_syntheticGitToken@github.com\n", encoding="utf-8"
    )
    (root / ".yarnrc.yml").write_text(
        'npmAuthToken: "registry-secret-value"\n', encoding="utf-8"
    )
    (root / "config").mkdir()
    (root / "config" / "kube.yaml").write_text(
        "client-key-data: c2VjcmV0LXN5bnRoZXRpYw==", encoding="utf-8"
    )
    (root / "config" / "gitlab.txt").write_text(
        "token=glpat-examplegitlabtoken\n", encoding="utf-8"
    )
    (root / "config" / "classic-token.txt").write_text(
        "token=ghp_exampleclassictoken\n", encoding="utf-8"
    )
    (root / "config" / "sas.txt").write_text(
        "https://example.blob.core.windows.net/container/blob?"
        "sv=2023-01-03&sig=SYNTHETIC-SAS-VALUE\n",
        encoding="utf-8",
    )
    (root / "config" / "azure.txt").write_text(
        "DefaultEndpointsProtocol=https;AccountName=acct;"
        "AccountKey=synthetic-azure-account-key;EndpointSuffix=core\n",
        encoding="utf-8",
    )
    (root / "config" / "numeric.json").write_text(
        '{"prod2ApiKey": "example-credential"}\n', encoding="utf-8"
    )
    (root / "config" / "ordinary.json").write_text(
        '{"author": "alice", "keyboard": "qwerty", "compass": "north"}\n',
        encoding="utf-8",
    )
    (root / ".terraform").mkdir()
    (root / ".terraform" / "terraform.tfstate").write_text(
        '{"sensitive": true, "value": "synthetic-tf-password"}\n',
        encoding="utf-8",
    )
    (root / ".pgpass").write_text(
        "localhost:5432:app:alice:synthetic-pg-password\n", encoding="utf-8"
    )
    (root / ".htpasswd").write_text(
        "alice:$apr1$synthetic$hashvalue\n", encoding="utf-8"
    )
    (root / "config" / "google.json").write_text(
        '{"key": "AIzaExampleGoogleApiKey1234567890"}\n', encoding="utf-8"
    )
    (root / "config" / "slack-session.txt").write_text(
        "xoxc-example-slack-session-token\n", encoding="utf-8"
    )
    (root / "config" / "slack.json").write_text(
        '{"slack": "xoxb-example-slack-token"}\n', encoding="utf-8"
    )
    (root / "config" / "escaped.json").write_text(
        '{"pass\\u0077ord": "escaped-secret-value"}\n', encoding="utf-8"
    )
    (root / "config" / "auth.json").write_text(
        '{"auth": "sk-example-project-credential"}\n', encoding="utf-8"
    )
    (root / "config" / "credential.json").write_text(
        '{"credential": "sensitive-value"}\n', encoding="utf-8"
    )
    (root / "config" / "settings.xml").write_text(
        "<config><password>synthetic-xml-password</password>"
        '<property name="password" value="synthetic-xml-attribute"/>'
        "</config>\n",
        encoding="utf-8",
    )
    (root / "config" / "tagged.yaml").write_text(
        "api_key: !vault |\n  synthetic-tagged-secret\n"
        "password: !!str |\n  synthetic-multibang-secret\n"
        "authorization: |\n  synthetic-authorization-token\n"
        "password: !!str\n  synthetic-tagged-plain\n"
        "password: &pw |\n  synthetic-anchored-secret\n"
        "password: plain-first\n  synthetic-plain-second\n"
        "password: &apw anchored-first\n  synthetic-anchored-plain\n"
        "password: &bare\n  synthetic-anchored-only\n"
        "password: !!str &saved\n  synthetic-tag-anchor\n"
        "pass: |\n  synthetic-pass-literal\n"
        "pass: >\n  synthetic-pass-folded\n",
        encoding="utf-8",
    )
    (root / "config" / "multiline.toml").write_text(
        'password = """\nsynthetic-multiline-secret\n"""\n',
        encoding="utf-8",
    )
    (root / "config" / "camel-credentials.txt").write_text(
        'openaiApiKey = "secret-value"\ngithubToken: ghp_example\n',
        encoding="utf-8",
    )
    (root / "config" / "camel.json").write_text(
        '{"dbPassword": "hunter2"}\n', encoding="utf-8"
    )
    (root / "config" / "structured.json").write_text(
        '{"api_key": ["first-secret", "second-secret"], '
        '"nested": {"api_key": "nested-secret"}, '
        '"password": {"nested": {"value": "nested-first"}, '
        '"backup": "nested-second"}}\n',
        encoding="utf-8",
    )
    (root / "config" / "settings.json").write_text(
        '{"api_key": "sk-json-secret-value", "region": "eu-central"}\n',
        encoding="utf-8",
    )
    (root / "config" / "database.py").write_text(
        'DATABASE_URL = "postgresql://alice:synthetic-password@db/app"\n'
        'DB_PASS = "synthetic-db-pass"\n'
        'APP_DB_PASS = "synthetic-app-db-pass"\n'
        'DB_PWD = "synthetic-db-pwd"\n',
        encoding="utf-8",
    )
    (root / "config" / "application.yaml").write_text(
        'api_key: |\n  sk-yaml-project-secret\n'
        '"quoted_key": |\n  sk-quoted-yaml-secret\n'
        "tokens:\n  - secret_key: |\n      sk-sequence-yaml-secret\n"
        "DB_PASS: |\n  synthetic-yaml-db-pass\n"
        "DB_PWD: >\n  synthetic-yaml-db-pwd\n"
        "blank_secret: |\n  first-part\n\n  second-part\n"
        "password: | # deployment credential\n  synthetic-comment-secret\n",
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
