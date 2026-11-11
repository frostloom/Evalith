"""Copy only verified ordinary project files; never follow source symlinks."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from .project_access import scan_project
from .service import WorkspaceError


def copy_project(project: Any, destination: Path, *, go_adapter: bool = False) -> dict:
    root = Path(project["root_path"])
    includes = ["go.mod", "go.sum", "internal"] if go_adapter else []
    excludes = [
        ".evalith",
        ".codex",
        ".superpowers",
        ".tmp",
        ".hallmark",
        "node_modules",
        ".venv",
        "dist",
        "build",
        "__pycache__",
    ]
    if go_adapter:
        excludes += [
            "*_test.go",
            "internal/taskbench",
            "internal/localpaired",
            "internal/gateway/web",
        ]
    scan = scan_project(
        root,
        includes,
        excludes,
        max_files=10000,
        max_file_bytes=2_000_000,
        expected_dev=project["root_dev"],
        expected_ino=project["root_ino"],
    )
    if scan.read_errors:
        raise WorkspaceError("隔离副本存在无法读取的源文件", status_code=422)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    copied = []
    try:
        actual = os.fstat(root_fd)
        if (actual.st_dev, actual.st_ino) != (project["root_dev"], project["root_ino"]):
            raise WorkspaceError("项目根目录身份变化", status_code=409)
        for record in scan.files:
            parts = Path(record.path).parts
            parent = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    child = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=parent,
                    )
                    os.close(parent)
                    parent = child
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                with os.fdopen(fd, "rb") as source:
                    info = os.fstat(source.fileno())
                    if not stat.S_ISREG(info.st_mode):
                        raise WorkspaceError("源文件类型变化", status_code=409)
                    data = source.read(2_000_001)
                if len(data) > 2_000_000:
                    raise WorkspaceError(
                        "运行依赖文件过大，需显式准备", status_code=422
                    )
                digest = hashlib.sha256(data).hexdigest()
                if digest != record.sha256:
                    raise WorkspaceError("准备期间源文件变化", status_code=409)
                target = destination / record.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o600 | (info.st_mode & 0o111))
                copied.append(
                    {"path": record.path, "sha256": digest, "size": len(data)}
                )
            finally:
                os.close(parent)
    finally:
        os.close(root_fd)
    digest = hashlib.sha256(
        json.dumps(copied, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = {
        "source_root": str(root),
        "source_identity": [project["root_dev"], project["root_ino"]],
        "files": copied,
        "digest": digest,
        "excluded_count": len(scan.excluded),
    }
    (destination.parent / "source-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    return manifest
