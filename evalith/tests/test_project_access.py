from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import create_stub_model, import_project, sha256


def test_selected_scope_is_read_and_fingerprinted(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    response = import_project(
        client,
        project_root,
        model_config_id=model["id"],
        include=["docs", "src", "README.md", "notes.txt"],
        supplemental=[{"title": "业务补充", "content": "发布失败必须可回滚。"}],
    )
    assert response.status_code == 201, response.text
    detail = response.json()
    snapshot = detail["snapshot"]
    paths = {item["path"] for item in snapshot["files"]}
    assert paths == {"README.md", "docs/RELEASE_POLICY.md", "src/agent.py", "notes.txt"}
    assert snapshot["digest"] == detail["project"]["snapshot_digest"]
    for item in snapshot["files"]:
        assert item["sha256"] == sha256(project_root / item["path"])
        assert item["size"] == (project_root / item["path"]).stat().st_size
    notes = next(item for item in snapshot["files"] if item["path"] == "notes.txt")
    assert notes["redactions"] >= 1

    message = next(
        item for item in detail["messages"] if item["role"] == "assistant"
    )
    scope = message["sent_scope"]
    sent_paths = {item["path"] for item in scope["sources"] if item.get("sent")}
    assert "docs/RELEASE_POLICY.md" in sent_paths
    assert "supplement:业务补充" in sent_paths
    assert scope["snapshot_digest"] == snapshot["digest"]
    assert scope["redactions"] >= 1

    # The model context is bounded and contains no excluded secret content.
    text = message["content"] + str(message["payload"])
    assert "sk-env-secret-123456" not in text
    assert "sk-file-secret-abcdef" not in text
    assert "sk-inline-secret-value" not in text


def test_default_scope_excludes_secrets_and_symlinks(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    response = import_project(client, project_root, model_config_id=model["id"])
    assert response.status_code == 201, response.text
    snapshot = response.json()["snapshot"]
    excluded_paths = {item["path"] for item in snapshot["excluded"]}
    assert ".env" in excluded_paths
    assert "secrets/" in excluded_paths
    assert "escape.txt" in excluded_paths
    assert "docs/leak.txt" in excluded_paths
    files = {item["path"] for item in snapshot["files"]}
    assert ".env" not in files
    assert "secrets/credentials.txt" not in files
    assert "escape.txt" not in files


def test_explicit_selection_cannot_override_secret_denylist(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    for selected in (".env", "secrets/credentials.txt", "secrets"):
        response = import_project(
            client, project_root, model_config_id=model["id"], include=[selected]
        )
        assert response.status_code == 422, (selected, response.text)
        assert response.json()["code"] in {"sensitive_path_denied", "path_outside_root"}


def test_scope_rejects_traversal_and_symlink_escape(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    response = import_project(
        client, project_root, model_config_id=model["id"], include=["../outside"]
    )
    assert response.status_code == 422
    assert response.json()["code"] == "path_outside_root"

    response = import_project(
        client, project_root, model_config_id=model["id"], include=["docs/leak.txt"]
    )
    assert response.status_code == 422
    assert response.json()["code"] == "symlink_rejected"


def test_unreadable_required_file_is_rejected(
    client: TestClient, project_root: Path
) -> None:
    target = project_root / "src" / "agent.py"
    target.chmod(0o000)
    try:
        if os.access(target, os.R_OK):  # pragma: no cover - environment-dependent
            return
        model = create_stub_model(client)
        response = import_project(
            client, project_root, model_config_id=model["id"], include=["src/agent.py"]
        )
        assert response.status_code == 422
        assert response.json()["code"] == "read_error"
    finally:
        target.chmod(0o644)


def test_scan_does_not_modify_the_project(
    client: TestClient, project_root: Path
) -> None:
    def tree_state() -> dict[str, tuple[int, int, str]]:
        state: dict[str, tuple[int, int, str]] = {}
        for path in sorted(project_root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                stat = path.stat()
                state[str(path.relative_to(project_root))] = (
                    stat.st_mtime_ns,
                    stat.st_size,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
        return state

    before = tree_state()
    model = create_stub_model(client)
    response = import_project(client, project_root, model_config_id=model["id"])
    assert response.status_code == 201, response.text
    after = tree_state()
    assert before == after


def test_selected_exclude_pattern_removes_subtree(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    response = import_project(
        client,
        project_root,
        model_config_id=model["id"],
        include=["src", "docs"],
        exclude=["docs"],
    )
    assert response.status_code == 201, response.text
    files = {item["path"] for item in response.json()["snapshot"]["files"]}
    assert files == {"src/agent.py"}


def test_snapshot_digest_is_deterministic_for_unchanged_files(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    first = import_project(client, project_root, model_config_id=model["id"], name="A")
    second = import_project(client, project_root, model_config_id=model["id"], name="B")
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["snapshot"]["digest"] == second.json()["snapshot"]["digest"]
