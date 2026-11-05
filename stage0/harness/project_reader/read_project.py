#!/usr/bin/env python3
"""Read-only project scanner for the stage 0 access boundary.

Walks a project mounted read-only at /project, skips secrets and symlinks that escape
the root, hashes included files, and records a manifest. It also records whether the
mount is writable.

Arguments:
    --root /project
    --output /out/manifest.json
    --max-file-bytes 20000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "secrets",
}
EXCLUDED_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.txt",
    "id_rsa",
}
TEXT_SUFFIXES = {".md", ".py", ".json", ".toml", ".yaml", ".yml", ".txt", ".cfg", ".ini"}


def is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/project")
    parser.add_argument("--output", default="/out/manifest.json")
    parser.add_argument("--max-file-bytes", type=int, default=20000)
    args = parser.parse_args()

    root = Path(args.root)
    files = []
    skipped = []
    secret_hits = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        # Prune excluded directories in place so os.walk does not descend into them.
        kept = []
        for name in dirnames:
            candidate = current / name
            if name in EXCLUDED_DIRS or name.startswith("."):
                skipped.append({"path": str(candidate.relative_to(root)), "reason": "excluded_dir"})
            elif candidate.is_symlink():
                skipped.append({"path": str(candidate.relative_to(root)), "reason": "symlink_dir"})
            else:
                kept.append(name)
        dirnames[:] = kept

        for name in filenames:
            candidate = current / name
            relative = str(candidate.relative_to(root))
            if name in EXCLUDED_NAMES or name.startswith(".env"):
                skipped.append({"path": relative, "reason": "excluded_name"})
                continue
            if candidate.is_symlink():
                if not is_within(root, candidate):
                    skipped.append({"path": relative, "reason": "symlink_escape"})
                else:
                    skipped.append({"path": relative, "reason": "symlink"})
                continue
            if not is_within(root, candidate):
                skipped.append({"path": relative, "reason": "path_escape"})
                continue
            try:
                size = candidate.stat().st_size
            except OSError as exc:
                skipped.append({"path": relative, "reason": f"stat_error:{type(exc).__name__}"})
                continue
            entry = {"path": relative, "size": size}
            if size <= args.max_file_bytes and candidate.suffix.lower() in TEXT_SUFFIXES:
                try:
                    data = candidate.read_bytes()
                    entry["sha256"] = hashlib.sha256(data).hexdigest()
                    if b"STAGE0_FAKE" in data:
                        secret_hits.append(relative)
                except OSError as exc:
                    entry["read_error"] = type(exc).__name__
            files.append(entry)

    write_probe = root / ".stage0-write-probe"
    try:
        write_probe.write_text("probe", encoding="utf-8")
        write_probe.unlink(missing_ok=True)
        writable = True
    except OSError:
        writable = False

    manifest = {
        "root": str(root),
        "files": sorted(files, key=lambda item: item["path"]),
        "skipped": sorted(skipped, key=lambda item: item["path"]),
        "secret_markers_found": secret_hits,
        "project_mount_writable": writable,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
