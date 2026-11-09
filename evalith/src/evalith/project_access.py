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
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

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
    ".git-credentials",
    ".npmrc",
    ".yarnrc",
    ".yarnrc.yml",
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
MAX_GITIGNORE_BYTES = 512_000
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
    # Case-insensitive filesystems resolve PRIVATE/ to private/; exclusion
    # matching must use the same equivalence before anything is opened.
    folded_name = name.casefold()
    folded_relpath = relpath.casefold()
    folded_parts = [part.casefold() for part in PurePosixPath(relpath).parts]
    for pattern in patterns:
        folded = pattern.casefold()
        if (
            fnmatch.fnmatchcase(folded_name, folded)
            or fnmatch.fnmatchcase(folded_relpath, folded)
            or any(fnmatch.fnmatchcase(part, folded) for part in folded_parts)
        ):
            return pattern
    return None


def _always_excluded(name: str, relpath: str) -> str | None:
    # Case-insensitive filesystems (macOS by default) resolve .ENV to .env and
    # SECRETS/ to secrets/.  Denylist checks must use the same equivalence.
    folded_name = name.casefold()
    folded_relpath = relpath.casefold()
    parts = [part.casefold() for part in PurePosixPath(relpath).parts]
    for pattern in ALWAYS_EXCLUDED:
        folded = pattern.casefold()
        if (
            fnmatch.fnmatchcase(folded_name, folded)
            or fnmatch.fnmatchcase(folded_relpath, folded)
            or any(fnmatch.fnmatchcase(part, folded) for part in parts)
        ):
            return pattern
    return None


@dataclass(frozen=True)
class ResolvedRoot:
    path: Path
    dev: int
    ino: int


def resolve_root(root_path: str, *, access_mode: str = "host") -> Path:
    """Return the validated path (identity-preserving callers use the helper)."""
    return resolve_root_with_identity(root_path, access_mode=access_mode).path


def resolve_root_with_identity(
    root_path: str, *, access_mode: str = "host"
) -> ResolvedRoot:
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
    try:
        canonical = candidate.resolve(strict=True)
    except OSError as exc:
        raise AccessError(
            f"项目目录不可访问：{exc.strerror}", code="root_missing"
        ) from exc
    if canonical == Path("/"):
        raise AccessError(
            "不能将文件系统根目录作为项目范围", code="root_too_broad"
        )
    if canonical == Path.home():
        raise AccessError("不能将整个用户主目录作为项目范围", code="root_too_broad")
    for part in canonical.parts:
        denied = _always_excluded(part, part)
        if denied:
            raise AccessError(
                f"项目根目录命中敏感凭据排除规则，不会读取：{part}",
                code="sensitive_path_denied",
            )
    return ResolvedRoot(path=canonical, dev=stat_result.st_dev, ino=stat_result.st_ino)


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


def _record_from_fd(
    fd: int,
    relative: str,
    *,
    max_file_bytes: int,
    scrub: Callable[[str], str] | None = None,
) -> FileRecord:
    # This function owns *fd* unconditionally: it closes it on every error
    # before ownership moves to the file object, and the file object closes it
    # thereafter.  Callers must never close the descriptor after calling.
    owned = fd
    try:
        stat_result = os.fstat(owned)
        if not stat.S_ISREG(stat_result.st_mode):
            raise AccessError(f"不是普通文件：{relative}", code="not_regular_file")
        if stat_result.st_size > MAX_HASH_BYTES:
            raise AccessError(
                f"文件超过指纹上限（{MAX_HASH_BYTES} 字节）：{relative}",
                code="file_too_large",
            )
        try:
            handle = os.fdopen(owned, "rb")
        except OSError as exc:
            raise AccessError(
                f"无法读取文件：{relative}（{exc.strerror}）", code="read_error"
            ) from exc
        owned = -1
        try:
            with handle:
                data = handle.read(MAX_HASH_BYTES + 1)
        except OSError as exc:
            raise AccessError(
                f"无法读取文件：{relative}（{exc.strerror}）", code="read_error"
            ) from exc
        if len(data) > MAX_HASH_BYTES:
            raise AccessError(f"文件超过指纹上限：{relative}", code="file_too_large")
    finally:
        if owned >= 0:
            _safe_close(owned)

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
        # Redact the complete decoded content before truncating.  A PEM block
        # whose closing marker lies beyond the excerpt boundary must still be
        # removed as a block; truncating first would leave its header and key
        # bytes behind.
        # Literal-key scrubbing must see the complete text before truncation;
        # otherwise a configured key crossing the excerpt boundary would
        # survive as a prefix.
        redacted = scrub(text) if scrub is not None else redact_text(text)
        redactions = _count_redactions(text, redacted)
        if len(redacted) > MAX_EXCERPT_CHARS:
            redacted = redacted[:MAX_EXCERPT_CHARS] + "\n…[truncated]"
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


def _selection_exclusion(parts: tuple[str, ...], patterns: list[str]) -> str | None:
    """Return the first matched pattern on the selected path or an ancestor."""
    accumulated: list[str] = []
    for part in parts:
        accumulated.append(part)
        relpath = "/".join(accumulated)
        matched = _matches(part, relpath, patterns)
        if matched:
            return matched
    return None


def _validate_gitignore_pattern(pattern: str) -> None:
    for part in pattern.split("/"):
        if "\\" not in part and "[:" not in part:
            continue
        try:
            _git_segment_regex(part)
        except re.error as exc:
            raise AccessError(
                f"无效的 .gitignore 模式：{pattern}",
                code="gitignore_invalid",
            ) from exc


def _read_gitignore(root_fd: int) -> list[tuple[str, bool]]:
    try:
        fd = os.open(
            ".gitignore",
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=root_fd,
        )
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return []
        raise AccessError(
            f"无法读取项目 .gitignore：{exc.strerror}", code="gitignore_unreadable"
        ) from exc
    try:
        info = os.fstat(fd)
    except OSError as exc:
        os.close(fd)
        raise AccessError(
            f"无法检查项目 .gitignore：{exc.strerror}", code="gitignore_unreadable"
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise AccessError(
            "项目 .gitignore 不是普通文件，不能读取",
            code="gitignore_not_regular",
        )
    try:
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_GITIGNORE_BYTES:
            chunk = os.read(
                fd, min(64_000, MAX_GITIGNORE_BYTES + 1 - total)
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        if total > MAX_GITIGNORE_BYTES:
            raise AccessError(
                f".gitignore 超过支持上限（{MAX_GITIGNORE_BYTES} 字节）",
                code="gitignore_too_large",
            )
    except OSError as exc:
        raise AccessError(
            f"无法读取项目 .gitignore：{exc.strerror}", code="gitignore_unreadable"
        ) from exc
    finally:
        os.close(fd)
    rules: list[tuple[str, bool]] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        while line and line[-1] in " \t":
            slashes = 0
            cursor = len(line) - 2
            while cursor >= 0 and line[cursor] == "\\":
                slashes += 1
                cursor -= 1
            if slashes % 2 == 1:
                break
            line = line[:-1]
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        if line:
            _validate_gitignore_pattern(line)
            rules.append((line, negated))
    return rules


def _unescape_gitignore_pattern(pattern: str) -> str:
    """Translate Git escaping into fnmatch patterns with literal wildcards."""
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            # Keep the escape; the bracket-aware translator below decides
            # whether it is a literal inside or outside a character class.
            out.append("\\")
            out.append(pattern[index + 1])
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


_POSIX_REGEX = {
    "alnum": "A-Za-z0-9",
    "alpha": "A-Za-z",
    "blank": " \t",
    "cntrl": r"\x00-\x1f\x7f",
    "digit": "0-9",
    "graph": r"\x21-\x7e",
    "lower": "a-z",
    "print": r"\x20-\x7e",
    "punct": r"\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e",
    "space": r"\x20\x09\x0a\x0d\x0c\x0b",
    "upper": "A-Z",
    "xdigit": "0-9A-Fa-f",
}


def _git_segment_regex(segment: str) -> re.Pattern[str]:
    out: list[str] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        if char == "*":
            out.append(".*")
            index += 1
        elif char == "?":
            out.append(".")
            index += 1
        elif char == "[":
            cursor = index + 1
            negated = False
            if cursor < len(segment) and segment[cursor] in "!^":
                negated = True
                cursor += 1
            body: list[str] = []
            if cursor < len(segment) and segment[cursor] == "]":
                # A closing bracket is literal in the first class position.
                body.append(re.escape("]"))
                cursor += 1
            while cursor < len(segment) and segment[cursor] != "]":
                if segment.startswith("[:", cursor):
                    close = segment.find(":]", cursor + 2)
                    if close != -1:
                        body.append(
                            _POSIX_REGEX.get(
                                segment[cursor + 2 : close], ""
                            )
                        )
                        cursor = close + 2
                        continue
                if segment[cursor] == "\\" and cursor + 1 < len(segment):
                    body.append(re.escape(segment[cursor + 1]))
                    cursor += 2
                    continue
                if segment[cursor] == "-":
                    body.append("-")
                else:
                    body.append(re.escape(segment[cursor]))
                cursor += 1
            if cursor < len(segment) and segment[cursor] == "]":
                body_text = "".join(body)
                out.append("[" + ("^" if negated else "") + body_text + "]")
                index = cursor + 1
                continue
            out.append(re.escape(char))
            index += 1
        else:
            if char == "\\" and index + 1 < len(segment):
                out.append(re.escape(segment[index + 1]))
                index += 2
                continue
            out.append(re.escape(char))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def _git_segment_match(path_part: str, pattern_part: str) -> bool:
    if "\\" in pattern_part or "[:" in pattern_part:
        return bool(_git_segment_regex(pattern_part).match(path_part))
    return fnmatch.fnmatchcase(path_part, pattern_part)

def _normalize_class_negation(pattern: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern[index] == "\\" and index + 1 < len(pattern):
            out.append(pattern[index])
            out.append(pattern[index + 1])
            index += 2
            continue
        if pattern.startswith("[^", index):
            out.append("[!")
            index += 2
            continue
        out.append(pattern[index])
        index += 1
    return "".join(out)


def _git_glob_match(path: str, pattern: str) -> bool:
    """Component-aware glob where a single * does not cross '/'."""
    path_parts = path.split("/")
    pattern_parts = pattern.split("/")

    def match(pattern_index: int, path_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        part = pattern_parts[pattern_index]
        if part == "**":
            if pattern_index == len(pattern_parts) - 1:
                # A trailing /** matches descendants, not the parent itself.
                return path_index < len(path_parts)
            return match(pattern_index + 1, path_index) or (
                path_index < len(path_parts)
                and match(pattern_index, path_index + 1)
            )
        if path_index >= len(path_parts):
            return False
        if not _git_segment_match(path_parts[path_index], part):
            return False
        return match(pattern_index + 1, path_index + 1)

    return match(0, 0)


def _gitignore_decision(
    relative: str, is_dir: bool, rules: list[tuple[str, bool]]
) -> tuple[bool, bool, str | None]:
    """Return (matched, ignored, pattern) for the last matching rule."""
    matched_any = False
    ignored = False
    matched_pattern: str | None = None
    for pattern, negated in rules:
        candidate = _normalize_class_negation(
            _unescape_gitignore_pattern(pattern)
        )
        dir_only = candidate.endswith("/")
        candidate = candidate.rstrip("/")
        if not candidate:
            continue
        anchored = candidate.startswith("/")
        candidate = candidate.lstrip("/")
        if "/" in candidate or anchored:
            matched = _git_glob_match(relative, candidate)
            if dir_only and not is_dir:
                ancestors = relative.split("/")[:-1]
                matched = any(
                    _git_glob_match("/".join(ancestors[: index + 1]), candidate)
                    for index in range(len(ancestors))
                )
        else:
            parts = relative.split("/")
            matched = any(_git_segment_match(part, candidate) for part in parts)
            if dir_only and not is_dir:
                matched = any(
                    _git_segment_match(part, candidate) for part in parts[:-1]
                )
        if matched:
            matched_any = True
            if negated:
                ignored = False
                matched_pattern = None
            else:
                ignored = True
                matched_pattern = pattern
    return matched_any, ignored, matched_pattern


def _gitignore_match(
    relative: str, is_dir: bool, rules: list[tuple[str, bool]]
) -> str | None:
    matched, ignored, pattern = _gitignore_decision(relative, is_dir, rules)
    return pattern if matched and ignored else None


def _nested_gitignore_match(
    relative: str,
    is_dir: bool,
    rulesets: list[tuple[str, list[tuple[str, bool]]]],
) -> str | None:
    for base, rules in reversed(rulesets):
        if base:
            if relative == base:
                local = ""
            elif relative.startswith(base + "/"):
                local = relative[len(base) + 1 :]
            else:
                continue
        else:
            local = relative
        matched, ignored, pattern = _gitignore_decision(local, is_dir, rules)
        if matched:
            return pattern if ignored else ""
    return None


def scan_project(
    root: Path,
    include_paths: list[str] | None,
    exclude_patterns: list[str] | None,
    *,
    max_files: int = 400,
    max_file_bytes: int = 512_000,
    expected_dev: int | None = None,
    expected_ino: int | None = None,
    scrub: Callable[[str], str] | None = None,
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
    strict_patterns = ALWAYS_EXCLUDED + user_excludes
    result = ScanResult(root=str(root), digest="", selected_scope=includes or ["."])
    root_fd, root_stat = _open_root(root, expected_dev, expected_ino)
    result.root_dev = root_stat.st_dev
    result.root_ino = root_stat.st_ino

    def add_file_from_fd(
        fd: int,
        relative: str,
        *,
        required: bool,
        scrub_text: Callable[[str], str] | None,
        rulesets: list[tuple[str, list[tuple[str, bool]]]] | None = None,
    ) -> None:
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
        ignored = _nested_gitignore_match(
            relative, False, rulesets or []
        )
        if ignored and not required:
            os.close(fd)
            result.excluded.append(
                {"path": relative, "reason": f"gitignore: {ignored}"}
            )
            return
        matched = _matches(
            name, relative, strict_patterns if required else patterns
        )
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
            record = _record_from_fd(
                fd,
                relative,
                max_file_bytes=max_file_bytes,
                scrub=scrub_text,
            )
            if ignored and required:
                record.reason = "explicitly selected despite .gitignore"
            result.files.append(record)
        except AccessError as exc:
            if required:
                raise
            result.read_errors.append({"path": relative, "error": str(exc), "code": exc.code})
        except OSError as exc:
            if required:
                raise AccessError(f"无法读取文件：{relative}", code="read_error") from exc
            result.read_errors.append(
                {"path": relative, "error": str(exc), "code": "read_error"}
            )

    visited: set[tuple[int, int]] = set()

    def walk(
        dir_fd: int,
        prefix: str,
        rulesets: list[tuple[str, list[tuple[str, bool]]]],
        *,
        force: bool = False,
    ) -> None:
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
                ignored = _nested_gitignore_match(relative, True, rulesets)
                if ignored and not force:
                    result.excluded.append(
                        {"path": relative + "/", "reason": f"gitignore: {ignored}"}
                    )
                    continue
                matched = _matches(
                    name, relative, strict_patterns if force else patterns
                )
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
                    child_rulesets = list(rulesets)
                    if not force:
                        child_rulesets.append(
                            (relative, _read_gitignore(child_fd))
                        )
                    walk(child_fd, relative, child_rulesets, force=force)
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
                add_file_from_fd(
                    fd,
                    relative,
                    required=force,
                    scrub_text=scrub,
                    rulesets=rulesets,
                )
            else:
                result.excluded.append(
                    {"path": relative, "reason": "not a regular file or directory"}
                )

    try:
        root_rulesets = [("", _read_gitignore(root_fd))]
        if includes:
            for relative in includes:
                parts = _include_parts(relative)
                matched = _selection_exclusion(parts, strict_patterns)
                if matched:
                    result.excluded.append(
                        {"path": relative, "reason": f"excluded: {matched}"}
                    )
                    continue
                fd, entry_stat = _open_relative(root_fd, parts)
                try:
                    if stat.S_ISDIR(entry_stat.st_mode):
                        walk(fd, relative, root_rulesets, force=True)
                    elif stat.S_ISREG(entry_stat.st_mode):
                        # Transfer ownership before the helper runs: it closes
                        # the descriptor on success and on every error path.
                        owned_fd = fd
                        fd = -1
                        add_file_from_fd(
                            owned_fd,
                            relative,
                            required=True,
                            scrub_text=scrub,
                            rulesets=root_rulesets,
                        )
                    else:
                        raise AccessError(
                            f"选定的路径不是普通文件或目录：{relative}",
                            code="not_regular_file",
                        )
                finally:
                    if fd >= 0:
                        os.close(fd)
        else:
            walk(root_fd, "", root_rulesets)
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
        separator = "\n" if blocks else ""
        framing = (
            len(separator)
            + len(header)
            + len("\n```text\n")
            + len("\n```\n")
        )
        if framing > remaining:
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
        chunk = header + "\n```text\n" + body + "\n```\n"
        if len(separator) + len(chunk) > remaining:
            marker = "…[truncated]"
            body_budget = remaining - framing - len(marker)
            if body_budget < 0:
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
            body = body[:body_budget] + marker
            chunk = header + "\n```text\n" + body + "\n```\n"
        blocks.append(separator + chunk)
        remaining -= len(separator) + len(chunk)
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
        content_digest = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()[:12]
        source_id = f"supplement:{title} [{content_digest}]"
        redaction_count += _count_redactions(raw_title + raw_content, title + content)
        prefix = "### SUPPLEMENT "
        footer = "\n```text\n\n```\n"
        separator = "\n" if blocks else ""
        label_suffix = f" [{content_digest}]"
        label_budget = (
            remaining - len(separator) - len(prefix) - len(footer) - len(label_suffix)
        )
        if label_budget < 1:
            sources.append(
                {
                    "path": source_id,
                    "sha256": hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
                    "size": len(raw_content.encode("utf-8")),
                    "sent": False,
                    "supplemental": True,
                    "reason": "model context budget reached",
                    "redactions": 0,
                }
            )
            continue
        title_budget = min(len(title), label_budget, 200)
        if title_budget < len(title):
            title = title[: max(0, title_budget - 1)] + "…"
        source_id = f"supplement:{title}{label_suffix}"
        content_budget = (
            remaining
            - len(separator)
            - len(prefix)
            - len(source_id)
            - len(footer)
        )
        if content_budget < 0:
            sources.append(
                {
                    "path": source_id,
                    "sha256": hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
                    "size": len(raw_content.encode("utf-8")),
                    "sent": False,
                    "supplemental": True,
                    "reason": "model context budget reached",
                    "redactions": 0,
                }
            )
            continue
        if len(content) > content_budget:
            marker = "…[truncated]"
            if content_budget >= len(marker):
                content = content[: content_budget - len(marker)] + marker
            else:
                content = ""
        chunk = f"{prefix}{source_id}\n```text\n{content}\n```\n"
        blocks.append(separator + chunk)
        remaining -= len(separator) + len(chunk)
        sent_bytes += len(content.encode("utf-8"))
        sources.append(
            {
                "path": source_id,
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
    return sources, "".join(blocks), scope
