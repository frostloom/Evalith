"""Read-only, allowlisted access to a user-selected local project.

Rules enforced here (and covered by tests):

* every path must stay under the selected root (``..`` and absolute paths are
  rejected; symbolic links are never followed);
* traversal is anchored to an open directory descriptor for the project root,
  and every child is opened relative to its parent with ``O_NOFOLLOW``.  A root
  or component replaced after the initial decision therefore cannot redirect a
  rescan to another directory;
* a fixed sensitive-name denylist always wins over user selection, so a
  selected file cannot pull ``.env`` or a private key into the model context;
* files are opened read-only and are never modified;
* binary and oversized files are fingerprinted but not sent to the model;
* excerpts and supplemental material are redacted for credential-shaped values;
* every analysed file records a SHA-256 content fingerprint and size, which is
  the source reference shown to the user and sent with the model request.
"""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .security import redact_text

#: Patterns that are always excluded, even if the user selects the matching
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

#: Dependency/build noise.  These are user-overridable, unlike the always
#: excluded credential names above.
NOISE_EXCLUDE_PATTERNS = [
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
]

DEFAULT_EXCLUDE_PATTERNS = NOISE_EXCLUDE_PATTERNS + ALWAYS_EXCLUDED

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
    root_dev: int = 0
    root_ino: int = 0
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

    The final path component must not be a symbolic link.  Symlinks in parent
    directories (for example ``/tmp``) are resolved, but the selected directory
    itself is anchored to its inode when the snapshot is taken.

    Phase 1 is host-only. A non-``host`` access mode fails closed: mapping a
    host path into a container without verified read-only mounts and UID
    semantics would be a false security claim, so it is not offered yet.
    """
    if access_mode != "host":
        raise AccessError(
            "阶段 1 仅支持宿主机本地只读访问；容器模式尚未实现，已拒绝",
            code="container_mode_unavailable",
        )
    if not root_path or not root_path.strip():
        raise AccessError("请选择本地项目目录", code="root_missing")
    raw = Path(os.path.abspath(os.path.expanduser(root_path)))
    if not raw.is_absolute():  # pragma: no cover - abspath always returns absolute
        raise AccessError("项目目录必须是绝对路径", code="root_not_absolute")
    if raw == Path("/"):
        raise AccessError("不能将文件系统根目录作为项目范围", code="root_too_broad")
    try:
        parent = raw.parent.resolve(strict=True)
    except OSError as exc:
        raise AccessError(f"项目目录的上级目录不可访问：{exc.strerror}", code="root_missing") from exc
    candidate = parent / raw.name
    try:
        stat_result = os.lstat(candidate)
    except OSError as exc:
        raise AccessError(f"项目目录不可访问：{exc.strerror}", code="root_missing") from exc
    if stat.S_ISLNK(stat_result.st_mode):
        raise AccessError(
            "项目根目录不能是符号链接；请选择真实目录", code="root_symlink"
        )
    if not stat.S_ISDIR(stat_result.st_mode):
        raise AccessError("项目路径不是目录", code="root_not_directory")
    if candidate == Path.home():
        raise AccessError("不能将整个用户主目录作为项目范围", code="root_too_broad")
    return candidate


def _open_root(root: Path, expected_dev: int | None, expected_ino: int | None) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(root, flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise AccessError(
                "项目根目录已变为符号链接或不再是目录；请重新导入项目",
                code="root_changed",
            ) from exc
        raise AccessError(f"无法只读打开项目目录：{exc.strerror}", code="read_error") from exc
    try:
        stat_result = os.fstat(fd)
        if not stat.S_ISDIR(stat_result.st_mode):
            raise AccessError("项目根目录不是目录", code="root_changed")
        if expected_dev is not None and expected_ino is not None:
            if (stat_result.st_dev, stat_result.st_ino) != (expected_dev, expected_ino):
                raise AccessError(
                    "项目根目录身份已变化（可能被替换）；请重新导入项目",
                    code="root_changed",
                )
        return fd, stat_result
    except Exception:
        os.close(fd)
        raise


def _open_relative(root_fd: int, parts: tuple[str, ...]) -> tuple[int, os.stat_result]:
    """Open a path relative to *root_fd* without following any symlink."""
    if not parts:
        raise AccessError("分析范围不能为空", code="path_outside_root")
    current = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=current,
                )
            except OSError as exc:
                _raise_open_error(part, exc)
            os.close(current)
            current = child
        try:
            final = os.open(
                parts[-1],
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=current,
            )
        except OSError as exc:
            _raise_open_error(parts[-1], exc)
        return final, os.fstat(final)
    finally:
        os.close(current)


def _raise_open_error(name: str, exc: OSError) -> None:
    if exc.errno == errno.ELOOP:
        raise AccessError(
            f"选定的路径包含符号链接，已拒绝：{name}", code="symlink_rejected"
        ) from exc
    if exc.errno == errno.ENOENT:
        raise AccessError(f"选定的路径不存在：{name}", code="path_missing") from exc
    if exc.errno == errno.ENOTDIR:
        raise AccessError(f"选定的路径不是预期类型：{name}", code="path_missing") from exc
    if exc.errno in (errno.EACCES, errno.EPERM):
        raise AccessError(f"无法读取选定的路径：{name}", code="read_error") from exc
    raise AccessError(f"无法打开选定的路径：{name}", code="read_error") from exc


def _include_parts(relative: str) -> tuple[str, ...]:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts:
        raise AccessError(
            f"分析范围必须是项目内的相对路径：{relative}", code="path_outside_root"
        )
    if any(part in ("..", "") for part in rel.parts):
        raise AccessError(f"分析范围包含越界路径：{relative}", code="path_outside_root")
    accumulated: list[str] = []
    for part in rel.parts:
        accumulated.append(part)
        denied = _always_excluded(part, "/".join(accumulated))
        if denied:
            raise AccessError(
                f"选定路径命中敏感凭据排除规则，不会读取：{relative}",
                code="sensitive_path_denied",
            )
    return rel.parts


def _safe_close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _is_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    sample = data[:4096]
    if not sample:
        return False
    non_text = sum(byte < 9 or (13 < byte < 32) for byte in sample)
    return non_text / len(sample) > 0.10


def _record_from_fd(fd: int, relative: str, *, max_file_bytes: int) -> FileRecord:
    stat_result = os.fstat(fd)
    if not stat.S_ISREG(stat_result.st_mode):
        raise AccessError(f"不是普通文件：{relative}", code="not_regular_file")
    if stat_result.st_size > MAX_HASH_BYTES:
        raise AccessError(
            f"文件超过指纹上限（{MAX_HASH_BYTES} 字节）：{relative}",
            code="file_too_large",
        )
    try:
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(MAX_HASH_BYTES + 1)
    except OSError as exc:
        raise AccessError(f"无法读取文件：{relative}（{exc.strerror}）", code="read_error") from exc
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
    expected_dev: int | None = None,
    expected_ino: int | None = None,
) -> ScanResult:
    """Scan an allowlisted project selection without writing anything.

    Traversal starts from an ``O_NOFOLLOW`` directory descriptor for ``root``
    and opens every child relative to it, so a path swapped after the root was
    validated cannot redirect the scan.  ``expected_dev``/``expected_ino`` let
    a rescan reject a project directory that has been replaced.
    """
    includes = [item.strip() for item in (include_paths or []) if item.strip()]
    user_excludes = [item.strip() for item in (exclude_patterns or []) if item.strip()]
    patterns = DEFAULT_EXCLUDE_PATTERNS + user_excludes
    result = ScanResult(root=str(root), digest="", selected_scope=includes or ["."])
    root_fd, root_stat = _open_root(root, expected_dev, expected_ino)
    result.root_dev = root_stat.st_dev
    result.root_ino = root_stat.st_ino

    def add_file_from_fd(fd: int, relative: str, *, required: bool) -> None:
        name = PurePosixPath(relative).name
        always = _always_excluded(name, relative)
        if always:
            os.close(fd)
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
            os.close(fd)
            result.excluded.append({"path": relative, "reason": f"excluded: {matched}"})
            return
        if len(result.files) >= max_files:
            os.close(fd)
            result.excluded.append(
                {"path": relative, "reason": f"snapshot file cap reached ({max_files})"}
            )
            return
        try:
            result.files.append(_record_from_fd(fd, relative, max_file_bytes=max_file_bytes))
        except AccessError as exc:
            _safe_close(fd)
            if required:
                raise
            result.read_errors.append({"path": relative, "error": str(exc), "code": exc.code})
        except OSError as exc:
            _safe_close(fd)
            if required:
                raise AccessError(f"无法读取文件：{relative}", code="read_error") from exc
            result.read_errors.append(
                {"path": relative, "error": str(exc), "code": "read_error"}
            )

    visited: set[tuple[int, int]] = set()

    def walk(dir_fd: int, prefix: str) -> None:
        dir_stat = os.fstat(dir_fd)
        key = (dir_stat.st_dev, dir_stat.st_ino)
        if key in visited:
            return
        visited.add(key)
        try:
            names = sorted(os.listdir(dir_fd))
        except OSError as exc:
            result.read_errors.append(
                {
                    "path": prefix or ".",
                    "error": str(exc),
                    "code": "read_error",
                }
            )
            return
        for name in names:
            relative = f"{prefix}/{name}" if prefix else name
            try:
                entry_stat = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            except OSError as exc:
                result.read_errors.append(
                    {"path": relative, "error": str(exc), "code": "read_error"}
                )
                continue
            if stat.S_ISLNK(entry_stat.st_mode):
                result.excluded.append(
                    {"path": relative, "reason": "symbolic link is never followed"}
                )
                continue
            if stat.S_ISDIR(entry_stat.st_mode):
                matched = _matches(name, relative, patterns)
                if matched:
                    result.excluded.append(
                        {"path": relative + "/", "reason": f"excluded: {matched}"}
                    )
                    continue
                try:
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=dir_fd,
                    )
                except OSError as exc:
                    result.read_errors.append(
                        {"path": relative, "error": str(exc), "code": "read_error"}
                    )
                    continue
                try:
                    walk(child_fd, relative)
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(entry_stat.st_mode):
                try:
                    fd = os.open(
                        name,
                        os.O_RDONLY
                        | getattr(os, "O_NOFOLLOW", 0)
                        | getattr(os, "O_NONBLOCK", 0),
                        dir_fd=dir_fd,
                    )
                except OSError as exc:
                    result.read_errors.append(
                        {"path": relative, "error": str(exc), "code": "read_error"}
                    )
                    continue
                add_file_from_fd(fd, relative, required=False)
            else:
                result.excluded.append(
                    {"path": relative, "reason": "not a regular file or directory"}
                )

    try:
        if includes:
            for relative in includes:
                parts = _include_parts(relative)
                fd, entry_stat = _open_relative(root_fd, parts)
                try:
                    if stat.S_ISDIR(entry_stat.st_mode):
                        walk(fd, relative)
                    elif stat.S_ISREG(entry_stat.st_mode):
                        add_file_from_fd(fd, relative, required=True)
                        fd = -1  # ownership transferred to _record_from_fd
                    else:
                        raise AccessError(
                            f"选定的路径不是普通文件或目录：{relative}",
                            code="not_regular_file",
                        )
                finally:
                    if fd >= 0:
                        os.close(fd)
        else:
            walk(root_fd, "")
    finally:
        os.close(root_fd)

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

    Supplemental titles and content are redacted here as a second line of
    defence even though the service now redacts them before storing.  Returns
    ``(sources, text, scope)``; ``scope`` is persisted with the message so the
    UI can show exactly which files, hashes and redactions were sent.
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
        raw_title = str(doc.get("title") or f"补充资料 {index + 1}")
        raw_content = str(doc.get("content", ""))
        title = redact_text(raw_title)
        content = redact_text(raw_content)
        redaction_count += _count_redactions(raw_title + raw_content, title + content)
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
                    "sha256": hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
                    "size": len(raw_content.encode("utf-8")),
                    "sent": True,
                    "supplemental": True,
                    "redactions": _count_redactions(raw_content, content),
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
