#!/usr/bin/env python3
"""Read-only project scanner for EvalScope EvalGen.

The scanner is the enforcement boundary: the coding agent should read its JSON
output, not the project files directly.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from _common import is_sensitive_path

DEFAULT_EXCLUDES = {
    '.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '.next',
    '__pycache__', '.idea', '.vscode', 'target', 'vendor', '.pytest_cache',
    '.mypy_cache', '.ruff_cache', 'coverage', '.evalith', 'artifacts', 'outputs',
}
DEFAULT_EXCLUDES_LOWER = {name.lower() for name in DEFAULT_EXCLUDES}
TEXT_SUFFIXES = {
    '.py', '.pyi', '.js', '.jsx', '.ts', '.tsx', '.go', '.java', '.kt', '.rs',
    '.rb', '.php', '.cs', '.c', '.h', '.cc', '.cpp', '.hpp', '.m', '.mm',
    '.sh', '.bash', '.zsh', '.ps1', '.sql', '.yaml', '.yml', '.toml', '.ini',
    '.cfg', '.json', '.md', '.markdown', '.txt', '.rst', '.html', '.css',
    '.scss', '.vue', '.svelte', '.proto', '.graphql', '.tf', '.dockerfile',
}
SENSITIVE_KEY_NAMES = {
    'apikey', 'apikeys', 'accesstoken', 'accesstokens', 'refreshtoken',
    'refreshtokens', 'authtoken', 'authtokens', 'idtoken', 'bearertoken',
    'clientsecret', 'clientsecrets', 'privatekey', 'privatekeys',
    'secretkey', 'secretkeys', 'secretaccesskey', 'secretaccesskeys',
    'password', 'passwords', 'passwd', 'authorization', 'credential',
    'credentials', 'token', 'secret', 'secrets',
}
SENSITIVE_KEY_SUFFIXES = (
    'apikey', 'apikeys', 'accesstoken', 'accesstokens', 'refreshtoken',
    'refreshtokens', 'authtoken', 'authtokens', 'idtoken', 'bearertoken',
    'clientsecret', 'clientsecrets', 'privatekey', 'privatekeys',
    'secretkey', 'secretkeys', 'secretaccesskey', 'secretaccesskeys',
    'password', 'passwords', 'passwd', 'authorization',
)
PRIVATE_KEY_RE = re.compile(
    r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?'
    r'-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----',
    re.I | re.S,
)
URL_USERINFO_RE = re.compile(r'(?i)\b([a-z][a-z0-9+.-]*://)[^\s]+@')
RAW_TOKEN_RE = re.compile(
    r'(?i)(?<![A-Za-z0-9])(?:sk-|ghp_|gho_|glpat-|xox[baprs]-|AKIA)[A-Za-z0-9_\-./+=]{8,}'
)
AUTHORIZATION_RE = re.compile(
    r'(?i)(["\']?(?:proxy-)?authorization["\']?\s*[:=]\s*)'
    r'(?:"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|[^\n,}]+)'
)
WHOLE_LINE_RE = re.compile(
    r'^(?P<indent>\s*)(?P<quote>["\']?)(?P<key>[^"\'=:\n]{1,80}?)(?P=quote)'
    r'(?P<delim>\s*[:=]\s*)(?P<value>[^\n]*?)(?P<newline>\r?\n)?$'
)
INLINE_PAIR_RE = re.compile(
    r'(?i)(["\']?)([^"\'=:\n]{1,80}?)\1(\s*[:=]\s*)'
    r'("(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|\[[^\]\n]*\]|\{[^}\n]*\}|[^\s,}\n]+)'
)


def _normalize_key(raw: str) -> str:
    text = unquote(str(raw).strip().strip('"\''))
    text = unicodedata.normalize('NFKC', text)
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Cf')
    return re.sub(r'[^a-z0-9]', '', text.lower())


def _is_sensitive_key(raw: str) -> bool:
    text = unquote(str(raw).strip().strip('"\''))
    normalized = _normalize_key(text)
    if normalized in SENSITIVE_KEY_NAMES or normalized.endswith(SENSITIVE_KEY_SUFFIXES):
        return True
    if any(ord(ch) > 127 for ch in text):
        ascii_only = normalized.encode('ascii', 'ignore').decode('ascii')
        return any(word in ascii_only for word in ('key', 'token', 'secret', 'password', 'credential'))
    return False


def _redact_value_line(match: re.Match[str]) -> tuple[str, int, tuple[str, int] | None]:
    value = match.group('value')
    stripped = value.strip()
    newline = match.group('newline') or ''
    line = (
        f"{match.group('indent')}{match.group('quote')}{match.group('key')}"
        f"{match.group('quote')}{match.group('delim')}[REDACTED]{newline}"
    )
    state: tuple[str, int] | None = None
    if stripped.startswith(('[', '{')):
        depth = stripped.count('[') + stripped.count('{') - stripped.count(']') - stripped.count('}')
        if depth > 0:
            state = ('bracket', depth)
    elif stripped.startswith(('|', '>')):
        state = ('indent', len(match.group('indent')))
    return line, 1, state


def _redact_block_line(line: str, state: tuple[str, int]) -> tuple[str, int, tuple[str, int] | None]:
    kind, value = state
    body = line.rstrip('\r\n')
    newline = line[len(body):]
    if kind == 'indent':
        if not body.strip():
            return '[REDACTED]' + newline, 1, state
        indent = len(body) - len(body.lstrip())
        if indent > value:
            return '[REDACTED]' + newline, 1, state
        return line, 0, None
    depth = value + body.count('[') + body.count('{') - body.count(']') - body.count('}')
    if depth <= 0:
        return '[REDACTED]' + newline, 1, None
    return '[REDACTED]' + newline, 1, ('bracket', depth)


def _redact_line(line: str, state: tuple[str, int] | None) -> tuple[str, int, tuple[str, int] | None]:
    if state is not None:
        return _redact_block_line(line, state)
    count = 0
    line, hits = AUTHORIZATION_RE.subn(r'\1[REDACTED]', line)
    count += hits
    match = WHOLE_LINE_RE.match(line)
    if match and _is_sensitive_key(match.group('key')):
        return _redact_value_line(match)
    hits = 0

    def replace_inline(match: re.Match[str]) -> str:
        nonlocal hits
        if not _is_sensitive_key(match.group(2)):
            return match.group(0)
        hits += 1
        return f'{match.group(1)}{match.group(2)}{match.group(1)}{match.group(3)}[REDACTED]'

    line = INLINE_PAIR_RE.sub(replace_inline, line)
    return line, count + hits, None


def _redact(text: str) -> tuple[str, int]:
    count = 0
    text, hits = PRIVATE_KEY_RE.subn('[REDACTED]', text)
    count += hits
    text, hits = URL_USERINFO_RE.subn(r'\1[REDACTED]@', text)
    count += hits
    text, hits = RAW_TOKEN_RE.subn('[REDACTED]', text)
    count += hits
    out: list[str] = []
    state: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        line, hits, state = _redact_line(line, state)
        out.append(line)
        count += hits
    return ''.join(out), count


def _safe_label(relative: Path) -> str:
    text, changed = _redact(relative.as_posix())
    return text if changed == 0 else '[REDACTED_PATH]'


def _excluded(relative: Path, patterns: list[str], *, ignore_defaults: bool = False) -> bool:
    text = relative.as_posix()
    if not ignore_defaults:
        for part in relative.parts:
            if part.lower() in DEFAULT_EXCLUDES_LOWER:
                return True
    for pattern in patterns:
        if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(relative.name, pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in relative.parts):
            return True
    return False


def _sha256(path: Path, limit: int) -> tuple[str, bool]:
    digest = hashlib.sha256()
    remaining = limit
    truncated = False
    with path.open('rb') as handle:
        while True:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
            if remaining <= 0:
                truncated = path.stat().st_size > limit
                break
    return digest.hexdigest(), truncated


def _is_binary(path: Path) -> bool:
    try:
        with path.open('rb') as handle:
            sample = handle.read(8192)
    except OSError:
        return True
    return b'\x00' in sample


def _headings(text: str) -> list[str]:
    return [line.lstrip('#').strip() for line in text.splitlines() if line.startswith('#')]


def _selected_paths(root: Path, includes: list[str]) -> list[Path]:
    if not includes:
        return [root]
    selected = []
    for raw in includes:
        rel = Path(raw)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError(f'include path must stay under root: {raw}')
        if is_sensitive_path(rel):
            raise ValueError(f'include path is sensitive: {raw}')
        candidate = root / rel
        if candidate.is_symlink():
            raise ValueError(f'include path is a symlink: {raw}')
        if not candidate.exists():
            raise ValueError(f'include path does not exist: {raw}')
        resolved = candidate.resolve()
        if os.path.commonpath([str(root), str(resolved)]) != str(root):
            raise ValueError(f'include path escapes root: {raw}')
        selected.append(candidate)
    return selected


def _dedupe_selected(selected: list[Path]) -> list[Path]:
    """Drop paths already covered by a shorter selected ancestor."""
    paths = sorted({path.resolve() for path in selected}, key=lambda path: (len(path.parts), str(path)))
    kept: list[Path] = []
    for path in paths:
        if any(path == parent or parent in path.parents for parent in kept):
            continue
        kept.append(path)
    return kept


def scan(
    root: Path,
    includes: list[str],
    excludes: list[str],
    knowledge_dirs: list[str],
    *,
    max_files: int = 400,
    max_total_chars: int = 120_000,
    max_file_bytes: int = 512_000,
    excerpt_chars: int = 8_000,
    fingerprint_bytes: int = 8 * 1024 * 1024,
    knowledge_share: float = 0.5,
) -> dict[str, Any]:
    if not 0 <= knowledge_share <= 1:
        raise ValueError('knowledge-share must be between 0 and 1')
    root = root.expanduser()
    if root.is_symlink():
        raise ValueError('project root must not be a symlink')
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f'project root is not a directory: {root}')

    selected = _selected_paths(root, includes)
    knowledge_roots = []
    for raw in knowledge_dirs:
        rel = Path(raw)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError(f'knowledge dir must stay under root: {raw}')
        if is_sensitive_path(rel):
            raise ValueError(f'knowledge dir is sensitive: {raw}')
        candidate = root / rel
        if candidate.is_symlink():
            raise ValueError(f'knowledge path is a symlink: {raw}')
        if not candidate.exists():
            raise ValueError(f'knowledge path does not exist: {raw}')
        resolved = candidate.resolve()
        if os.path.commonpath([str(root), str(resolved)]) != str(root):
            raise ValueError(f'knowledge path escapes root: {raw}')
        knowledge_roots.append(resolved)
    selected = _dedupe_selected(selected)
    walk_paths = list(knowledge_roots)
    for selected_path in selected:
        if selected_path not in walk_paths:
            walk_paths.append(selected_path)

    def relative_label(relative: Path) -> str:
        return relative.as_posix() or '.'

    def under_knowledge(relative: Path) -> bool:
        absolute = root / relative
        return any(absolute == knowledge or knowledge in absolute.parents for knowledge in knowledge_roots)

    files: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    sensitive: list[str] = []
    seen: set[Path] = set()
    knowledge_file_limit = 0
    knowledge_char_limit = 0
    code_file_limit = max_files
    code_char_limit = max_total_chars
    if knowledge_roots and knowledge_share > 0:
        knowledge_file_limit = max(1, int(max_files * knowledge_share))
        knowledge_char_limit = max(1, int(max_total_chars * knowledge_share))
        code_file_limit = max_files - knowledge_file_limit
        code_char_limit = max_total_chars - knowledge_char_limit
    knowledge_files = 0
    code_files = 0
    knowledge_chars = 0
    code_chars = 0

    def handle_file(path: Path) -> None:
        nonlocal knowledge_files, code_files, knowledge_chars, code_chars
        try:
            relative = path.relative_to(root)
        except ValueError:
            return
        if relative in seen:
            return
        seen.add(relative)
        label = relative_label(relative)
        if _safe_label(relative) != label:
            sensitive.append('[REDACTED_PATH]')
            return
        if is_sensitive_path(relative):
            sensitive.append(label)
            return
        is_knowledge = under_knowledge(relative)
        if _excluded(relative, excludes, ignore_defaults=is_knowledge):
            excluded.append({'path': label, 'reason': 'excluded'})
            return
        file_limit = knowledge_file_limit if is_knowledge else code_file_limit
        file_count = knowledge_files if is_knowledge else code_files
        if file_count >= file_limit:
            excluded.append({'path': label, 'reason': 'file_limit'})
            return
        try:
            stat = path.stat()
            sha, truncated = _sha256(path, fingerprint_bytes)
            binary = _is_binary(path)
        except OSError as exc:
            excluded.append({'path': label, 'reason': f'read_error: {exc}'})
            return

        excerpt = None
        sent = False
        reason = None
        redactions = 0
        headings: list[str] = []
        line_count = 0
        if binary:
            reason = 'binary'
        elif stat.st_size > max_file_bytes:
            reason = 'file_too_large'
        elif path.suffix.lower() not in TEXT_SUFFIXES and path.name.lower() != 'dockerfile':
            reason = 'unsupported_text_type'
        else:
            try:
                text = path.read_text(encoding='utf-8', errors='replace')
            except OSError as exc:
                excluded.append({'path': label, 'reason': f'read_error: {exc}'})
                return
            line_count = len(text.splitlines())
            text, redactions = _redact(text)
            headings = _headings(text)
            snippet = text[:excerpt_chars]
            used_chars = knowledge_chars if is_knowledge else code_chars
            char_limit = knowledge_char_limit if is_knowledge else code_char_limit
            if used_chars + len(snippet) > char_limit:
                reason = 'char_budget'
            else:
                excerpt = snippet
                sent = True
                if is_knowledge:
                    knowledge_chars += len(snippet)
                else:
                    code_chars += len(snippet)

        if is_knowledge:
            knowledge_files += 1
        else:
            code_files += 1
        files.append({
            'path': label,
            'sha256': sha,
            'hash_truncated': truncated,
            'size': stat.st_size,
            'mtime_ns': stat.st_mtime_ns,
            'binary': binary,
            'knowledge': is_knowledge,
            'headings': headings,
            'line_count': line_count,
            'sent': sent,
            'sent_reason': reason,
            'redactions': redactions,
            'excerpt': excerpt,
        })

    for selected_path in walk_paths:
        if selected_path.is_file():
            if selected_path.is_symlink():
                sensitive.append('[REDACTED_PATH]')
            else:
                handle_file(selected_path)
            continue
        for current, dirnames, filenames in os.walk(selected_path, followlinks=False):
            current_path = Path(current)
            relative_dir = current_path.relative_to(root)
            kept_dirs = []
            for name in sorted(dirnames):
                candidate = current_path / name
                relative = relative_dir / name
                label = relative_label(relative)
                if candidate.is_symlink():
                    excluded.append({'path': label, 'reason': 'symlink_dir'})
                    continue
                if _safe_label(relative) != label:
                    sensitive.append('[REDACTED_PATH]')
                    continue
                if is_sensitive_path(relative):
                    sensitive.append(label)
                    continue
                if _excluded(relative, excludes, ignore_defaults=under_knowledge(relative)):
                    excluded.append({'path': label, 'reason': 'excluded'})
                    continue
                kept_dirs.append(name)
            dirnames[:] = kept_dirs
            for name in sorted(filenames):
                candidate = current_path / name
                if candidate.is_symlink():
                    excluded.append({'path': relative_label(relative_dir / name), 'reason': 'symlink'})
                    continue
                handle_file(candidate)

    for knowledge_root in knowledge_roots:
        relative = knowledge_root.relative_to(root)
        label = relative_label(relative)
        if knowledge_root.is_file():
            found = any(item['knowledge'] and item['path'] == label for item in files)
        else:
            prefix = '' if label == '.' else label + '/'
            found = any(
                item['knowledge'] and (
                    label == '.' or item['path'] == label or item['path'].startswith(prefix)
                )
                for item in files
            )
        if not found:
            raise ValueError(f'knowledge path produced no files: {label}')

    files.sort(key=lambda item: item['path'])
    digest = hashlib.sha256(
        '\n'.join(f"{item['path']}:{item['sha256']}" for item in files).encode('utf-8')
    ).hexdigest()
    selected_labels: list[str] = []
    for path in selected:
        relative = path.relative_to(root)
        label = relative_label(relative)
        if _safe_label(relative) != label:
            raise ValueError('selected path contains a credential-like value')
        selected_labels.append(label)
    knowledge_labels: list[str] = []
    for path in knowledge_roots:
        relative = path.relative_to(root)
        label = relative_label(relative)
        if _safe_label(relative) != label:
            raise ValueError('knowledge dir contains a credential-like value')
        knowledge_labels.append(label)
    return {
        'root': str(root),
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'selected': selected_labels,
        'exclude_patterns': sorted(set(excludes)),
        'knowledge_dirs': knowledge_labels,
        'limits': {
            'max_files': max_files,
            'max_total_chars': max_total_chars,
            'max_file_bytes': max_file_bytes,
            'excerpt_chars': excerpt_chars,
            'fingerprint_bytes': fingerprint_bytes,
            'knowledge_share': knowledge_share,
            'knowledge_file_limit': knowledge_file_limit,
            'code_file_limit': code_file_limit,
            'knowledge_char_limit': knowledge_char_limit,
            'code_char_limit': code_char_limit,
        },
        'files': files,
        'excluded': excluded,
        'sensitive_rejected': sorted(set(sensitive)),
        'scope_digest': digest,
        'total_chars': knowledge_chars + code_chars,
        'knowledge_chars': knowledge_chars,
        'code_chars': code_chars,
    }


def _print_summary(snapshot: dict[str, Any]) -> None:
    print(f"root: {snapshot['root']}")
    print(f"selected: {', '.join(snapshot['selected'])}")
    print(f"files: {len(snapshot['files'])} "
          f"sent: {sum(1 for f in snapshot['files'] if f['sent'])} "
          f"chars: {snapshot['total_chars']}/{snapshot['limits']['max_total_chars']}")
    print(f"sensitive_rejected: {', '.join(snapshot['sensitive_rejected']) or '(none)'}")
    print(f"scope_digest: {snapshot['scope_digest']}")
    reasons: dict[str, int] = {}
    for item in snapshot['excluded']:
        reason = item.get('reason', 'unknown')
        reasons[reason] = reasons.get(reason, 0) + 1
    if reasons:
        print('excluded: ' + ', '.join(f'{key}={value}' for key, value in sorted(reasons.items())))
    unsent: dict[str, int] = {}
    for item in snapshot['files']:
        if not item['sent']:
            reason = item.get('sent_reason') or 'unknown'
            unsent[reason] = unsent.get(reason, 0) + 1
    if unsent:
        print('not sent: ' + ', '.join(f'{key}={value}' for key, value in sorted(unsent.items())))
    knowledge = [f for f in snapshot['files'] if f.get('knowledge')]
    print(f"knowledge files: {len(knowledge)} "
          f"sent: {sum(1 for f in knowledge if f['sent'])}")
    sent = [f for f in snapshot['files'] if f['sent']]
    if sent:
        print('context files:')
        for item in sent[:20]:
            print(f"  - {item['path']} ({len(item.get('excerpt') or '')} chars)")
        if len(sent) > 20:
            print(f'  ... and {len(sent) - 20} more')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--include', action='append', default=[])
    parser.add_argument('--exclude', action='append', default=[])
    parser.add_argument('--knowledge-dir', action='append', default=[],
                        help='document directory or file under root; may be repeated')
    parser.add_argument('--out', required=True)
    parser.add_argument('--summary', action='store_true')
    parser.add_argument('--max-files', type=int, default=400)
    parser.add_argument('--max-total-chars', type=int, default=120_000)
    parser.add_argument('--max-file-bytes', type=int, default=512_000)
    parser.add_argument('--excerpt-chars', type=int, default=8_000)
    parser.add_argument('--knowledge-share', type=float, default=0.5,
                        help='share of file/char budget reserved for knowledge dirs (0-1)')
    args = parser.parse_args()
    try:
        snapshot = scan(
            Path(args.root),
            args.include,
            args.exclude,
            args.knowledge_dir,
            max_files=args.max_files,
            max_total_chars=args.max_total_chars,
            max_file_bytes=args.max_file_bytes,
            excerpt_chars=args.excerpt_chars,
            knowledge_share=args.knowledge_share,
        )
    except ValueError as exc:
        print(f'error: {exc}')
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.summary:
        _print_summary(snapshot)
    print(f"scanned={len(snapshot['files'])} sent={sum(1 for f in snapshot['files'] if f['sent'])} "
          f"sensitive_rejected={len(snapshot['sensitive_rejected'])} digest={snapshot['scope_digest'][:12]}")
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
