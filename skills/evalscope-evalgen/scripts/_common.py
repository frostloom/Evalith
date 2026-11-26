"""Shared path and URL rules for the EvalGen scripts."""

from __future__ import annotations

import os
from pathlib import Path

HTTP_PREFIXES = ('http://127.0.0.1', 'http://localhost')
SENSITIVE_DIRS = {'.ssh', '.aws', '.gnupg', '.docker', '.git'}
SENSITIVE_NAMES = {'.env', '.npmrc', '.pypirc', '.netrc'}
SENSITIVE_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.kdbx', '.env')
SENSITIVE_PREFIXES = ('id_rsa', 'id_ed25519', 'id_ecdsa', 'credentials')


def is_allowed_http(url: object) -> bool:
    """Accept the literal loopback prefixes without lookalike hosts."""
    if not isinstance(url, str):
        return False
    for prefix in HTTP_PREFIXES:
        if url.startswith(prefix):
            rest = url[len(prefix):]
            return rest == '' or rest.startswith((':','/'))
    return False


def is_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and '..' not in path.parts


def assert_under_root(relative: str, root: str | Path) -> Path:
    """Resolve a relative path and reject escapes and symlinks under root."""
    if not is_relative_path(relative):
        raise ValueError(f'path must stay under project root: {relative!r}')
    root_resolved = Path(root).resolve()
    candidate = root_resolved / relative
    if candidate.is_symlink():
        raise ValueError(f'path must not be a symlink: {relative!r}')
    resolved = candidate.resolve()
    try:
        common = os.path.commonpath([str(root_resolved), str(resolved)])
    except ValueError as exc:
        raise ValueError(f'path is outside project root: {relative!r}') from exc
    if common != str(root_resolved):
        raise ValueError(f'path is outside project root: {relative!r}')
    return candidate


def is_sensitive_path(relative: str | Path) -> bool:
    path = Path(relative)
    for part in path.parts:
        name = part.lower()
        if name in SENSITIVE_DIRS or name.startswith('secrets'):
            return True
    name = path.name.lower()
    if name in SENSITIVE_NAMES or name.startswith('.env'):
        return True
    if name.endswith(SENSITIVE_SUFFIXES):
        return True
    return name.startswith(SENSITIVE_PREFIXES)


__all__ = [
    'HTTP_PREFIXES',
    'assert_under_root',
    'is_allowed_http',
    'is_relative_path',
    'is_sensitive_path',
]
