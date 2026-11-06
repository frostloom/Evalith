"""Credential handling and log redaction.

Model API keys are encrypted at rest with a Fernet key derived from
``EVALITH_SECRET_KEY`` (or a generated 0600 key file in the data directory).
Keys are never returned by the API, never written to message payloads, and a
logging filter removes credential-shaped values from log records.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_SECRET_PATTERNS = [
    # YAML literal/folded block scalars, e.g. api_key: |
    #   sk-project-secret
    re.compile(
        r"(?im)^[ \t]*(?:-[ \t]+)?[\"']?"
        r"(?:[A-Za-z0-9_-]*(?:secret|token|key|password)[A-Za-z0-9_-]*)"
        r"[\"']?[ \t]*:\s*[|>][-+0-9]*[ \t]*\n(?:[ \t]+.*(?:\n|$))*"
    ),
    # key=value / "key": "value" forms, including JSON and quoted values.
    # The optional identifier prefix (e.g. OPENAI_API_KEY, DB_PASSWORD) is what
    # makes prefixed credential names visible; a bare word-boundary would miss
    # them because "_" is a word character.
    re.compile(
        r"(?i)(?<![A-Za-z0-9])[\"']?(?:[A-Za-z0-9]+[_-])*"
        r"(?:secret[_-]?access[_-]?key|secret[_-]?key|signing[_-]?key|"
        r"npm[_-]?auth[_-]?token|npmAuthToken|access[_-]?key[_-]?id|"
        r"api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|"
        r"password|authorization)[\"']?\s*[:=]\s*"
        r"(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\n,}]+)"
    ),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    # Connection strings with userinfo, including token-only forms such as
    # https://ghp_token@github.com and user:password@ forms.
    re.compile(
        r"(?i)\b[a-z][a-z0-9+.-]*://[^@\s/]+@[^\s,}\"']+"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]

_REDACTED = "[REDACTED]"


def redact_text(value: str) -> str:
    """Remove credential-shaped substrings from free text."""
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def mask_secret(secret: str | None) -> str | None:
    if not secret:
        return None
    if len(secret) <= 4:
        return "****"
    return "****" + secret[-4:]


class CredentialCipher:
    """Small wrapper around Fernet with an explicit key source."""

    def __init__(self, secret_key: str | None, data_dir: Path) -> None:
        self._fernet = Fernet(self._resolve_key(secret_key, data_dir))

    @staticmethod
    def _resolve_key(secret_key: str | None, data_dir: Path) -> bytes:
        if secret_key:
            raw = secret_key.encode("utf-8")
            # Accept either a Fernet key or an arbitrary passphrase.
            try:
                base64.urlsafe_b64decode(raw)
                if len(base64.urlsafe_b64decode(raw)) == 32:
                    return raw
            except Exception:  # noqa: BLE001 - fall through to derivation
                pass
            return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        key_file = data_dir / "secret.key"
        if key_file.exists():
            return key_file.read_bytes().strip()
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = Fernet.generate_key()
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return key

    def encrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:  # pragma: no cover - configuration error
            raise RuntimeError(
                "the stored model credential cannot be decrypted; the secret key changed"
            ) from exc


class RedactionFilter(logging.Filter):
    """Redact credential-shaped values from a log record's message and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging
            return True
        record.msg = redact_text(message)
        record.args = ()
        return True


_LOG_NAMES = (
    "",
    "evalith",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
    "httpcore",
    "rhesis",
)


def install_log_redaction() -> None:
    """Install the filter on app, server and HTTP-client loggers and handlers.

    A filter attached only to the root logger does not run for records emitted
    by child loggers, so credential redaction is installed on the loggers that
    can actually see request/response text as well as on root handlers.
    """
    for name in _LOG_NAMES:
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactionFilter) for item in logger.filters):
            logger.addFilter(RedactionFilter())
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, RedactionFilter) for item in handler.filters):
            handler.addFilter(RedactionFilter())
