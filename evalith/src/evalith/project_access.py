"""Read-only, allowlisted access to a user-selected local project.

Rules enforced here (and covered by tests):

* every path must stay under the selected root (``..`` and absolute paths are
  rejected; symbolic links are never followed);
* a fixed sensitive-name denylist always wins over user selection, so a
  selected file cannot pull ``.env`` or a private key into the model context;
* files are opened read-only and are never modified;
* binary and oversized files are fingerprinted but not sent to the model;
* excerpts are redacted for credential-shaped values;
* every analysed file records a SHA-256 content fingerprint and size, which is
  the source reference shown to the user and sent with the model request.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .security import redact_text

DEFAULT_EXCLUDE_PATTERNS = [
    # version control / dependency / build noise
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".next",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "coverage",
    ".DS_Store",
    # credential-bearing names: these are never overridable
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.kdbx",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "credentials*",
    "secrets*",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "netrc",
    ".docker",
    ".aws",
    ".ssh",
    ".gnupg",
]

#: These patterns are always excluded, even if the user selects the matching
#: path explicitly.  They are not a user preference.
ALWAYS_EXCLUDED = [
    ".git",
    ".hg",
    ".svn",
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.kdbx",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "credentials*",
    "secrets*",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "netrc",
    ".ssh",
    ".aws",
    ".gnupg",
    ".docker",
]

MAX_HASH_BYTES = 8_000_000
MAX_EXCERPT_CHARS = 6_000


class AccessError(ValueError):
    """A selection or access rule was violated."""

    def __init__(self, message: str, *, code: str = "project_access_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class FileRecord:
    path: str
    sha256: str
    size: int
    mtime_ns: int
    binary: bool
    excerpt: str = ""
    redactions: int = 0
    context_included: bool = True
    reason: str | None = None

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "binary": self.binary,
            "redactions": self.redactions,
            "context_included": self.context_included,
            "reason": self.reason,
        }


@dataclass
class ScanResult:
    root: str
    digest: str
    files: list[FileRecord] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    read_errors: list[dict[str, str]] = field(default_factory=list)
    selected_scope: list[str] = field(default_factory=list)

    def manifest(self) -> list[dict[str, Any]]:
        return [item.manifest_entry() for item in self.files]


def _matches(name: str, relpath: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(relpath, pattern):
            return pattern
        for part in PurePosixPath(relpath).parts:
            if fnmatch.fnmatch(part, pattern):
                return pattern
    return None


def _always_excluded(name: str, relpath: str) -> str | None:
    return _matches(name, relpath, ALWAYS_EXCLUDED)


def resolve_root(root_path: str, *, access_mode: str = "host") -> Path:
    """Resolve and validate the user-selected project root.

    In ``container`` mode the caller must have declared a host-to-container
    mount mapping; this function only accepts host roots that are inside a
    declared mount, which makes an unmapped path fail closed instead of
    silently reading an unrelated container directory.
    """
    if not root_path or not root_path.strip():
        raise AccessError("请选择本地项目目录", code="root_missing")
    raw = Path(root_path).expanduser()
    if not raw.is_absolute():
        raise AccessError("项目目录必须是绝对路径", code="root_not_absolute")
    resolved = raw.resolve(strict=True)
    if not resolved.is_dir():
        raise AccessError("项目路径不是目录", code="root_not_directory")
    if access_mode == "container":
        raise AccessError(
            "容器模式需要在部署配置中声明宿主机到容器的只读映射；未声明时拒绝访问",
            code="mount_not_mapped",
        )
    if str(resolved) == "/":
        raise AccessError("不能将文件系统根目录作为项目范围", code="root_too_broad")
    if resolved == Path.home():
        raise AccessError("不能将整个用户主目录作为项目范围", code="root_too_broad")
    return resolved


def _safe_path(root: Path, relative: str) -> Path:
    """Join *relative* to *root*, rejecting traversal and symlink components."""
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts:
        raise AccessError(f"分析范围必须是项目内的相对路径：{relative}", code="path_outside_root")
    if any(part in ("..", "") for part in rel.parts):
        raise AccessError(f"分析范围包含越界路径：{relative}", code="path_outside_root")
    current = root
    for part in rel.parts:
        current = current / part
        if not current.exists():
            raise AccessError(f"选定的路径不存在：{relative}", code="path_missing")
        mode = os.lstat(current).st_mode
        if stat.S_ISLNK(mode):
            raise AccessError(
                f"选定的路径包含符号链接，已拒绝：{relative}", code="symlink_rejected"
            )
    real = current.resolve(strict=True)
    if not real.is_relative_to(root):
        raise AccessError(f"选定的路径越出项目范围：{relative}", code="path_outside_root")
    return real


def _is_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    sample = data[:4096]
    if not sample:
        return False
    non_text = sum(
        byte < 9 or (13 < byte < 32) for byte in sample
    )
    return non_text / len(sample) > 0.10


def _read_file(root: Path, path: Path, *, max_file_bytes: int) -> FileRecord:
    relative = path.relative_to(root).as_posix()
    stat_result = os.lstat(path)
    if stat.S_ISLNK(stat_result.st_mode):
        raise AccessError(f"符号链接不读取：{relative}", code="symlink_rejected")
    if not stat.S_ISREG(stat_result.st_mode):
        raise AccessError(f"不是普通文件：{relative}", code="not_regular_file")
    if stat_result.st_size > MAX_HASH_BYTES:
        raise AccessError(
            f"文件超过指纹上限（{MAX_HASH_BYTES} 字节）：{relative}",
            code="file_too_large",
        )
    # Read-only, no-follow open.  There is deliberately no write path here.
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise AccessError(f"无法读取文件：{relative}（{exc.strerror}）", code="read_error") from exc
    try:
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(MAX_HASH_BYTES + 1)
    finally:
        pass
    if len(data) > MAX_HASH_BYTES:
        raise AccessError(f"文件超过指纹上限：{relative}", code="file_too_large")

    digest = hashlib.sha256(data).hexdigest()
    binary = _is_binary(data)
    excerpt = ""
    redactions = 0
    included = True
    reason: str | None = None
    if binary:
        included = False
        reason = "binary file: fingerprinted only"
    elif len(data) > max_file_bytes:
        included = False
        reason = f"file larger than model-context cap ({max_file_bytes} bytes)"
    else:
        text = data.decode("utf-8", errors="replace")
        if len(text) > MAX_EXCERPT_CHARS:
            text = text[:MAX_EXCERPT_CHARS] + "\n…[truncated]"
        redacted = redact_text(text)
        redactions = _count_redactions(text, redacted)
        excerpt = redacted
    return FileRecord(
        path=relative,
        sha256=digest,
        size=len(data),
        mtime_ns=stat_result.st_mtime_ns,
        binary=binary,
        excerpt=excerpt,
        redactions=redactions,
        context_included=included,
        reason=reason,
    )


def _count_redactions(before: str, after: str) -> int:
    marker = "[REDACTED]"
    if marker not in after:
        return 0
    return after.count(marker) if len(after) < len(before) else 0


def scan_project(
    root: Path,
    include_paths: list[str] | None,
    exclude_patterns: list[str] | None,
    *,
    max_files: int = 400,
    max_file_bytes: int = 512_000,
) -> ScanResult:
    """Scan an allowlisted project selection without writing anything."""
    includes = [item.strip() for item in (include_paths or []) if item.strip()]
    user_excludes = [item.strip() for item in (exclude_patterns or []) if item.strip()]
    patterns = DEFAULT_EXCLUDE_PATTERNS + user_excludes
    result = ScanResult(root=str(root), digest="", selected_scope=includes or ["."])

    def add_file(path: Path, *, required: bool) -> None:
        relative = path.relative_to(root).as_posix()
        name = path.name
        always = _always_excluded(name, relative)
        if always:
            result.excluded.append(
                {"path": relative, "reason": f"sensitive name denied: {always}"}
            )
            if required:
                raise AccessError(
                    f"选定路径命中敏感凭据排除规则，不会读取：{relative}",
                    code="sensitive_path_denied",
                )
            return
        matched = _matches(name, relative, patterns)
        if matched:
            result.excluded.append({"path": relative, "reason": f"excluded: {matched}"})
            return
        if len(result.files) >= max_files:
            result.excluded.append(
                {"path": relative, "reason": f"snapshot file cap reached ({max_files})"}
            )
            return
        try:
            result.files.append(_read_file(root, path, max_file_bytes=max_file_bytes))
        except AccessError as exc:
            if required:
                raise
            result.read_errors.append({"path": relative, "error": str(exc), "code": exc.code})
        except OSError as exc:
            entry = {"path": relative, "error": str(exc), "code": "read_error"}
            if required:
                raise AccessError(f"无法读取文件：{relative}", code="read_error") from exc
            result.read_errors.append(entry)

    visited_dirs: set[Path] = set()

    def walk(directory: Path) -> None:
        real = directory.resolve()
        if real in visited_dirs:
            return
        visited_dirs.add(real)
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            result.read_errors.append(
                {
                    "path": directory.relative_to(root).as_posix(),
                    "error": str(exc),
                    "code": "read_error",
                }
            )
            return
        for entry in entries:
            relative = Path(entry.path).relative_to(root).as_posix()
            if entry.is_symlink():
                result.excluded.append(
                    {"path": relative, "reason": "symbolic link is never followed"}
                )
                continue
            if entry.is_dir(follow_symlinks=False):
                matched = _matches(entry.name, relative, patterns)
                if matched:
                    result.excluded.append(
                        {"path": relative + "/", "reason": f"excluded: {matched}"}
                    )
                    continue
                walk(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                add_file(Path(entry.path), required=False)

    if includes:
        for relative in includes:
            selected = _safe_path(root, relative)
            denied = _always_excluded(selected.name, relative)
            if denied:
                raise AccessError(
                    f"选定路径命中敏感凭据排除规则，不会读取：{relative}",
                    code="sensitive_path_denied",
                )
            if selected.is_dir():
                walk(selected)
            else:
                add_file(selected, required=True)
    else:
        walk(root)

    result.files.sort(key=lambda item: item.path)
    result.digest = _digest(result.files)
    return result


def _digest(files: list[FileRecord]) -> str:
    hasher = hashlib.sha256()
    for item in files:
        hasher.update(item.path.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(item.sha256.encode("ascii"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def build_model_context(
    scan: ScanResult,
    supplemental: list[dict[str, str]],
    *,
    budget_chars: int,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Build a bounded, fingerprinted context block for the model.

    Returns ``(sources, text, scope)``.  ``scope`` is persisted with the
    message so the UI can show exactly which files and hashes were sent.
    """
    sources: list[dict[str, Any]] = []
    blocks: list[str] = []
    remaining = budget_chars
    sent_bytes = 0
    redaction_count = 0

    for item in scan.files:
        if not item.context_included:
            sources.append(
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "size": item.size,
                    "sent": False,
                    "reason": item.reason,
                }
            )
            continue
        if remaining <= 0:
            sources.append(
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "size": item.size,
                    "sent": False,
                    "reason": "model context budget reached",
                }
            )
            continue
        header = f"### FILE {item.path} (sha256 {item.sha256[:16]}…, {item.size} bytes)"
        body = item.excerpt
        chunk = header + "\n```text\n" + body + "\n```\n"
        if len(chunk) > remaining:
            body = body[: max(0, remaining - len(header) - 20)]
            chunk = header + "\n```text\n" + body + "…[truncated]\n```\n"
        blocks.append(chunk)
        remaining -= len(chunk)
        sent_bytes += len(body.encode("utf-8"))
        redaction_count += item.redactions
        sources.append(
            {
                "path": item.path,
                "sha256": item.sha256,
                "size": item.size,
                "sent": True,
                "redactions": item.redactions,
            }
        )

    for index, doc in enumerate(supplemental):
        content = doc.get("content", "")
        title = doc.get("title") or f"补充资料 {index + 1}"
        chunk = f"### SUPPLEMENT {title}\n```text\n{content}\n```\n"
        if len(chunk) > remaining:
            content = content[: max(0, remaining - 80)]
            chunk = f"### SUPPLEMENT {title}\n```text\n{content}…[truncated]\n```\n"
        if remaining > 0:
            blocks.append(chunk)
            remaining -= len(chunk)
            sent_bytes += len(content.encode("utf-8"))
            sources.append(
                {
                    "path": f"supplement:{title}",
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "size": len(content.encode("utf-8")),
                    "sent": True,
                    "supplemental": True,
                }
            )

    scope = {
        "root": scan.root,
        "snapshot_digest": scan.digest,
        "files_sent": sum(1 for item in sources if item.get("sent")),
        "files_listed": len(sources),
        "bytes_sent": sent_bytes,
        "redactions": redaction_count,
        "sources": sources,
    }
    return sources, "\n".join(blocks), scope
