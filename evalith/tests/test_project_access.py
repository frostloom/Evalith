from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import create_stub_model, import_project, sha256
from evalith.project_access import (
    AccessError,
    MAX_EXCERPT_CHARS,
    MAX_HASH_BYTES,
    _record_from_fd,
    resolve_root,
    resolve_root_with_identity,
    scan_project,
)


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
    assert paths == {
        "README.md",
        "docs/RELEASE_POLICY.md",
        "docs/internal/plan.md",
        "src/agent.py",
        "notes.txt",
    }
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


def test_sensitive_directory_cannot_be_the_project_root(
    client: TestClient, tmp_path: Path
) -> None:
    root = tmp_path / "secrets"
    root.mkdir()
    (root / "deploy-token.txt").write_text("unlabelled-token-value\n", encoding="utf-8")
    model = create_stub_model(client)
    response = import_project(client, root, model_config_id=model["id"])
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "sensitive_path_denied"


def test_sensitive_names_are_casefolded_for_explicit_selection(tmp_path: Path) -> None:
    root = tmp_path / "casefold-project"
    root.mkdir()
    (root / ".ENV").write_text("SECRET=1\n", encoding="utf-8")
    secrets = root / "SECRETS"
    secrets.mkdir()
    (secrets / "credentials.txt").write_text("token\n", encoding="utf-8")

    for selected in (".ENV", "SECRETS/credentials.txt"):
        with pytest.raises(AccessError) as excinfo:
            scan_project(root, [selected], [])
        assert excinfo.value.code == "sensitive_path_denied"


def test_unreadable_gitignore_fails_closed(tmp_path: Path, monkeypatch) -> None:
    import errno
    import evalith.project_access as project_access

    root = tmp_path / "unreadable-gitignore"
    root.mkdir()
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    (root / ".gitignore").write_text("private/\n", encoding="utf-8")
    real_open = project_access.os.open

    def fake_open(path, *args, **kwargs):
        if path == ".gitignore":
            raise PermissionError(errno.EACCES, "denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(project_access.os, "open", fake_open)
    with pytest.raises(AccessError) as excinfo:
        project_access.scan_project(root, [], [])
    assert excinfo.value.code == "gitignore_unreadable"


def test_resolve_root_preserves_identity_for_initial_scan(tmp_path: Path) -> None:
    root = tmp_path / "identity-project"
    root.mkdir()
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    resolved = resolve_root_with_identity(str(root))
    assert resolved.path == root
    assert (resolved.dev, resolved.ino) == (
        os.lstat(root).st_dev,
        os.lstat(root).st_ino,
    )

    replaced = tmp_path / "identity-project-old"
    root.rename(replaced)
    root.mkdir()
    (root / "other.txt").write_text("other\n", encoding="utf-8")
    with pytest.raises(AccessError) as excinfo:
        scan_project(
            root,
            [],
            [],
            expected_dev=resolved.dev,
            expected_ino=resolved.ino,
        )
    assert excinfo.value.code == "root_changed"


def test_gitignore_excludes_default_and_explicit_selection(tmp_path: Path) -> None:
    root = tmp_path / "gitignore-project"
    root.mkdir()
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    (root / ".gitignore").write_text("private/\n", encoding="utf-8")
    private = root / "private"
    private.mkdir()
    (private / "customer-export.json").write_text(
        '{"customer": "synthetic"}\n', encoding="utf-8"
    )

    default = scan_project(root, [], [])
    assert "private/customer-export.json" not in {item.path for item in default.files}
    assert any(
        item["path"] == "private/" and "gitignore" in item["reason"]
        for item in default.excluded
    )

    selected = scan_project(root, ["private/customer-export.json"], [])
    records = {item.path: item for item in selected.files}
    assert "private/customer-export.json" in records
    assert records["private/customer-export.json"].reason == (
        "explicitly selected despite .gitignore"
    )


def test_gitignore_error_closes_root_descriptor(
    tmp_path: Path, monkeypatch
) -> None:
    import evalith.project_access as project_access

    root = tmp_path / "gitignore-error"
    root.mkdir()
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    opened: list[int] = []
    real_open_root = project_access._open_root

    def tracking_open(*args, **kwargs):
        fd, info = real_open_root(*args, **kwargs)
        opened.append(fd)
        return fd, info

    def boom(_fd: int):
        raise AccessError("forced .gitignore failure", code="gitignore_not_regular")

    closed: list[int] = []
    real_close = project_access.os.close
    monkeypatch.setattr(project_access, "_open_root", tracking_open)
    monkeypatch.setattr(project_access, "_read_gitignore", boom)
    monkeypatch.setattr(
        project_access.os,
        "close",
        lambda fd: (closed.append(fd), real_close(fd)),
    )
    with pytest.raises(AccessError):
        project_access.scan_project(root, [], [])
    assert opened and opened[0] in closed


def test_fifo_gitignore_is_not_read_blocking(tmp_path: Path) -> None:
    root = tmp_path / "fifo-gitignore"
    root.mkdir()
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    os.mkfifo(root / ".gitignore")
    with pytest.raises(AccessError) as excinfo:
        scan_project(root, [], [])
    assert excinfo.value.code == "gitignore_not_regular"


def test_symlinked_project_root_is_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    real = tmp_path / "real-project"
    real.mkdir()
    (real / "README.md").write_text("# Real\n", encoding="utf-8")
    link = tmp_path / "linked-project"
    link.symlink_to(real)
    model = create_stub_model(client)
    response = import_project(client, link, model_config_id=model["id"])
    assert response.status_code == 422
    assert response.json()["code"] == "root_symlink"


def test_replaced_project_root_is_rejected_on_chat(
    client: TestClient, project_root: Path, tmp_path: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]

    outside = tmp_path / "replacement"
    outside.mkdir()
    (outside / "unrelated-secret.txt").write_text(
        "unrelated content api_key=must-not-be-read\n", encoding="utf-8"
    )
    original = tmp_path / "original-project"
    project_root.rename(original)
    project_root.symlink_to(outside)

    response = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "继续"}
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "root_changed"
    assert "must-not-be-read" not in response.text
    detail_after = client.get(f"/api/projects/{project_id}").json()
    assert "must-not-be-read" not in str(detail_after)
    assert any(
        item["payload"]["kind"] == "error"
        and item["payload"].get("stage") == "rescan"
        for item in detail_after["messages"]
    )


def test_replaced_project_root_is_rejected_on_reanalyse(
    client: TestClient, project_root: Path, tmp_path: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    original = tmp_path / "old-project"
    project_root.rename(original)
    project_root.mkdir()
    (project_root / "README.md").write_text("# Replaced\n", encoding="utf-8")

    response = client.post(f"/api/projects/{project_id}/reanalyse")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "root_changed"


def test_pem_block_crossing_excerpt_boundary_is_redacted(project_root: Path) -> None:
    prefix = "a" * (MAX_EXCERPT_CHARS - 10)
    pem = (
        "-----BEGIN PRIVATE KEY-----\n"
        + "secret-key-material\n" * 20
        + "-----END PRIVATE KEY-----\n"
    )
    path = project_root / "README_PEM.md"
    path.write_text(prefix + "\n" + pem, encoding="utf-8")
    result = scan_project(project_root, ["README_PEM.md"], [], max_file_bytes=512_000)
    assert result.files
    excerpt = result.files[0].excerpt
    assert "BEGIN PRIVATE KEY" not in excerpt
    assert "secret-key-material" not in excerpt
    assert result.files[0].redactions >= 1


def test_oversized_explicit_file_returns_structured_error(
    client: TestClient, project_root: Path
) -> None:
    (project_root / "oversized.bin").write_bytes(b"x" * (MAX_HASH_BYTES + 1))
    model = create_stub_model(client)
    response = import_project(
        client, project_root, model_config_id=model["id"], include=["oversized.bin"]
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "file_too_large"


def test_explicit_nested_directory_respects_ancestor_exclusion(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    response = import_project(
        client,
        project_root,
        model_config_id=model["id"],
        include=["docs/internal"],
        exclude=["docs/internal"],
    )
    assert response.status_code == 201, response.text
    snapshot = response.json()["snapshot"]
    assert not any(item["path"].startswith("docs/internal") for item in snapshot["files"])
    assert any(
        item["path"] == "docs/internal" for item in snapshot["excluded"]
    )


def test_explicit_nested_file_respects_ancestor_exclusion(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    response = import_project(
        client,
        project_root,
        model_config_id=model["id"],
        include=["docs/internal/plan.md"],
        exclude=["docs/internal"],
    )
    assert response.status_code == 201, response.text
    snapshot = response.json()["snapshot"]
    assert not snapshot["files"]
    assert any(
        item["path"] == "docs/internal/plan.md" for item in snapshot["excluded"]
    )


def test_record_from_fd_closes_once_on_read_error(
    project_root: Path, monkeypatch
) -> None:
    target = project_root / "README.md"
    fd = os.open(target, os.O_RDONLY)
    closed: list[int] = []
    real_close = os.close

    class BadHandle:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            closed.append(fd)
            real_close(fd)

        def read(self, _size):
            raise OSError("forced read failure")

    monkeypatch.setattr(os, "fdopen", lambda _fd, _mode: BadHandle())
    monkeypatch.setattr(os, "close", lambda value: (closed.append(value), real_close(value)))
    with pytest.raises(AccessError) as excinfo:
        _record_from_fd(fd, "README.md", max_file_bytes=512_000)
    assert excinfo.value.code == "read_error"
    assert closed == [fd]


def test_special_file_selection_is_rejected_without_blocking(
    client: TestClient, project_root: Path
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is unavailable")
    os.mkfifo(project_root / "pipe.fifo")
    model = create_stub_model(client)
    started = time.monotonic()
    response = import_project(
        client, project_root, model_config_id=model["id"], include=["pipe.fifo"]
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "not_regular_file"
    assert time.monotonic() - started < 5


def test_container_mode_fails_closed(project_root: Path) -> None:
    with pytest.raises(AccessError) as excinfo:
        resolve_root(str(project_root), access_mode="container")
    assert excinfo.value.code == "container_mode_unavailable"


def test_snapshot_digest_is_deterministic_for_unchanged_files(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    first = import_project(client, project_root, model_config_id=model["id"], name="A")
    second = import_project(client, project_root, model_config_id=model["id"], name="B")
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["snapshot"]["digest"] == second.json()["snapshot"]["digest"]
