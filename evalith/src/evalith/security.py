"""Credential handling and log redaction.

Model API keys are encrypted at rest with a Fernet key derived from
``EVALITH_SECRET_KEY`` (or a generated 0600 key file in the data directory).
Keys are never returned by the API, never written to message payloads, and a
logging filter removes credential-shaped values from log records.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_SECRET_PATTERNS = [
    # Tagged YAML plain scalars continued on indented lines, e.g. password: !!str
    #   secret
    re.compile(
        r"(?im)^(?P<indent>[ \t]*)(?:-[ \t]+)?[\"']?"
        r"(?:[A-Za-z0-9_-]*(?:private[_-]?key|credential|secret|token|key|"
        r"(?<![A-Za-z0-9])pass|db[_-]?pass|app[_-]?db[_-]?pass|account[_-]?key|client[_-]?key[_-]?data|password|passwd|pwd|auth|authorization|github[_-]?pat|githubToken)[A-Za-z0-9_-]*)"
        r"[\"']?[ \t]*:\s*(?:(?:![^ \t\n]+|&[^ \t\n]+)[ \t]*)+\r?\n"
        r"(?:(?:[ \t]*\r?\n)|(?P=indent)[ \t]+.*(?:\r?\n|$))*"
    ),
    # YAML literal/folded block scalars, e.g. api_key: |
    #   sk-project-secret
    re.compile(
        r"(?im)^(?P<indent>[ \t]*)(?:-[ \t]+)?[\"']?"
        r"(?:[A-Za-z0-9_-]*(?:(?<![A-Za-z0-9])pass|private[_-]?key|credential|secret|token|key|db[_-]?pass|app[_-]?db[_-]?pass|account[_-]?key|client[_-]?key[_-]?data|password|passwd|pwd|auth|authorization|github[_-]?pat|githubToken)[A-Za-z0-9_-]*)"
        r"[\"']?[ \t]*:\s*(?:(?:![^ \t\n]+|&[^ \t\n]+)[ \t]+)*[|>][-+0-9]*[ \t]*(?:#[^\n]*)?\r?\n"
        r"(?:(?:[ \t]*\r?\n)|(?P=indent)[ \t]+.*(?:\r?\n|$))*"
    ),
    # Multiline triple-quoted values (TOML/Python style).
    re.compile(
        r"(?is)[\"']?(?:[A-Za-z0-9_]+[_-])*"
        r"(?:private[_-]?key|privateKey|apiKey|accessToken|dbPassword|jwtSecret|"
        r"clientSecret|refreshToken|credential|secret[_-]?access[_-]?key|"
        r"secret[_-]?key|signing[_-]?key|npm[_-]?auth[_-]?token|npmAuthToken|"
        r"access[_-]?key[_-]?id|api[_-]?key|access[_-]?token|client[_-]?secret|"
        r"token|secret|account[_-]?key|client[_-]?key[_-]?data|sig|signature|password|passwd|pwd|pass|auth|authorization|github[_-]?pat|githubToken)[\"']?\s*[:=]\s*"
        r"(?:[\"']{3}.*?[\"']{3}|[\"']{3}.*?[\"']{3})"
    ),
    # Untagged YAML plain scalars continued on indented lines.
    re.compile(
        r"(?im)^(?P<indent>[ \t]*)(?:-[ \t]+)?[\"']?"
        r"(?:[A-Za-z0-9_-]*(?:private[_-]?key|credential|secret|token|key|"
        r"(?<![A-Za-z0-9])pass|db[_-]?pass|app[_-]?db[_-]?pass|account[_-]?key|client[_-]?key[_-]?data|password|passwd|pwd|auth|authorization|github[_-]?pat|githubToken)[A-Za-z0-9_-]*)"
        r"[\"']?[ \t]*:\s*"
        r"(?:&[^ \t\r\n]+(?:[ \t]+[^\r\n]*)?|[^ \t\r\n|>!&][^\r\n]*)"
        r"\r?\n"
        r"(?:(?:[ \t]*\r?\n)|(?P=indent)[ \t]+.*(?:\r?\n|$))*"
    ),
    # key=value / "key": "value" forms, including JSON and quoted values.
    # The optional identifier prefix (e.g. OPENAI_API_KEY, DB_PASSWORD) is what
    # makes prefixed credential names visible; a bare word-boundary would miss
    # them because "_" is a word character.
    re.compile(
        r"(?i)(?<![A-Za-z0-9])[\"']?(?:[A-Za-z0-9]+[_-]|[A-Za-z][A-Za-z0-9]*(?=apiKey|Token|Password|Secret|Credential|Authorization))*"
        r"(?:private[_-]?key|privateKey|apiKey|accessToken|dbPassword|jwtSecret|"
        r"clientSecret|refreshToken|credential|secret[_-]?access[_-]?key|secret[_-]?key|signing[_-]?key|"
        r"npm[_-]?auth[_-]?token|npmAuthToken|access[_-]?key[_-]?id|"
        r"api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|"
        r"account[_-]?key|client[_-]?key[_-]?data|sig|signature|password|passwd|pwd|pass|auth|authorization|github[_-]?pat|githubToken)[\"']?\s*[:=]\s*"
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

_YAML_PATTERNS = _SECRET_PATTERNS[:3]
_SECRET_PATTERNS = _SECRET_PATTERNS[3:]
_SECRET_PATTERNS.insert(
    0,
    re.compile(
        r"(?is)<[A-Za-z0-9_.:-]*(?:private[_-]?key|credential|secret|token|"
        r"key|db[_-]?pass|app[_-]?db[_-]?pass|account[_-]?key|client[_-]?key[_-]?data|password|passwd|pwd|auth|authorization|github[_-]?pat|githubToken)[A-Za-z0-9_.:-]*"
        r"(?:\s[^>]*)?>.*?</[A-Za-z0-9_.:-]+\s*>"
    ),
)
_SECRET_PATTERNS.insert(
    1,
    re.compile(
        r"(?is)<[^>]*\b(?:name|key|id)\s*=\s*[\"'][^\"']*"
        r"(?:private[_-]?key|credential|secret|token|key|password|passwd|pwd|"
        r"pass|auth|authorization|github[_-]?pat|githubToken)[^\"']*[\"'][^>]*>.*?</[A-Za-z0-9_.:-]+\s*>"
    ),
)
_SECRET_PATTERNS.insert(
    2,
    re.compile(
        r"(?is)<[^>]*\b(?:name|key|id)\s*=\s*[\"'][^\"']*"
        r"(?:private[_-]?key|credential|secret|token|key|password|passwd|pwd|"
        r"pass|auth|authorization|github[_-]?pat|githubToken)[^\"']*[\"'][^>]*>"
    ),
)
_SECRET_PATTERNS.insert(
    3,
    re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{8,}|github_pat_[A-Za-z0-9_]{8,}|"
        r"gh[pousr]_[A-Za-z0-9]{8,}|xox[a-z]-[A-Za-z0-9-]{8,}|"
        r"AIza[0-9A-Za-z_-]{20,}|glpat-[A-Za-z0-9_-]{8,})\b"
    ),
)

_REDACTED = "[REDACTED]"

_STRUCTURED_CREDENTIAL = re.compile(
    r"(?is)(?<![A-Za-z0-9])[\"']?(?:[A-Za-z0-9]+[_-]|[A-Za-z][A-Za-z0-9]*(?=apiKey|Token|Password|Secret|Credential|Authorization))*"
    r"(?:private[_-]?key|privateKey|apiKey|accessToken|dbPassword|jwtSecret|"
    r"clientSecret|refreshToken|credential|secret[_-]?access[_-]?key|secret[_-]?key|"
    r"signing[_-]?key|npm[_-]?auth[_-]?token|npmAuthToken|"
    r"access[_-]?key[_-]?id|api[_-]?key|access[_-]?token|client[_-]?secret|"
    r"token|secret|account[_-]?key|client[_-]?key[_-]?data|sig|signature|password|passwd|pwd|pass|auth|authorization|github[_-]?pat|githubToken)[\"']?\s*[:=]\s*"
    r"(?=[\[{])"
)


def _structured_value_end(text: str, start: int) -> int:
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            continue
        if char in "[{":
            stack.append("]" if char == "[" else "}")
            continue
        if char in "]}":
            if stack and stack[-1] == char:
                stack.pop()
                if not stack:
                    return index + 1
            else:
                return index + 1
    return len(text)


def _redact_structured_values(text: str) -> str:
    out: list[str] = []
    cursor = 0
    for match in _STRUCTURED_CREDENTIAL.finditer(text):
        if match.start() < cursor:
            continue
        end = _structured_value_end(text, match.end())
        out.append(text[cursor : match.start()])
        out.append(_REDACTED)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


_XML_TAG = re.compile(r"(?is)<\s*(/)?\s*([A-Za-z0-9_.:-]+)([^>]*)>")
_XML_CREDENTIAL_TERM = re.compile(
    r"(?i)(?:private[_-]?key|credential|secret|token|key|password|passwd|pwd|"
    r"pass|auth|authorization|github[_-]?pat)"
)


_XML_CDATA = re.compile(r"(?s)<!\[CDATA\[.*?\]\]>")


def _redact_xml_credential_elements(text: str) -> str:
    out: list[str] = []
    cursor = 0
    cdata = [(item.start(), item.end()) for item in _XML_CDATA.finditer(text)]

    def in_cdata(position: int) -> bool:
        return any(start <= position < end for start, end in cdata)

    for match in _XML_TAG.finditer(text):
        if match.start() < cursor or match.group(1) or in_cdata(match.start()):
            continue
        name = match.group(2)
        attrs = match.group(3) or ""
        if not _XML_CREDENTIAL_TERM.search(name + attrs):
            continue
        if attrs.rstrip().endswith("/"):
            end = match.end()
        else:
            depth = 1
            end = len(text)
            for tag in _XML_TAG.finditer(text, match.end()):
                if in_cdata(tag.start()):
                    continue
                if (tag.group(2) or "").casefold() != name.casefold():
                    continue
                if tag.group(1):
                    depth -= 1
                elif not (tag.group(3) or "").rstrip().endswith("/"):
                    depth += 1
                if depth == 0:
                    end = tag.end()
                    break
        out.append(text[cursor : match.start()])
        out.append(_REDACTED)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


_JSON_EXACT_CREDENTIAL_KEYS = {
    "apikey",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "privatekey",
    "secretkey",
    "signingkey",
    "password",
    "passwd",
    "pwd",
    "pass",
    "token",
    "secret",
    "auth",
    "authorization",
    "credential",
    "credentials",
    "githubpat",
    "accountkey",
    "clientkeydata",
}
_JSON_CREDENTIAL_SUFFIXES = (
    "apikey",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "privatekey",
    "secretkey",
    "signingkey",
    "password",
    "passwd",
    "token",
    "secret",
    "credential",
    "authorization",
    "auth",
    "accountkey",
    "clientkeydata",
)
_JSON_CREDENTIAL_PREFIXES = {
    "db",
    "api",
    "jwt",
    "github",
    "slack",
    "openai",
    "aws",
    "gcp",
    "azure",
    "my",
    "storage",
}


def is_credential_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    if normalized in _JSON_EXACT_CREDENTIAL_KEYS:
        return True
    for suffix in _JSON_CREDENTIAL_SUFFIXES:
        if not normalized.endswith(suffix):
            continue
        prefix = normalized[: -len(suffix)]
        if prefix in _JSON_CREDENTIAL_PREFIXES or re.fullmatch(
            r"[a-z]+[0-9]+", prefix
        ):
            return True
    return False


def _redact_json_credentials(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return text
    try:
        parsed = json.loads(text)
    except ValueError:
        return text

    def walk(value):
        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                if is_credential_key(key):
                    cleaned[key] = _REDACTED
                else:
                    cleaned[key] = walk(item)
            return cleaned
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return json.dumps(walk(parsed), ensure_ascii=False)


_YAML_ALIAS_REFERENCE = re.compile(
    r"(?im)^[ \t]*(?:-[ \t]+)?[\"']?([^:\r\n\"']+?)[\"']?"
    r"[ \t]*:[ \t]*\*([A-Za-z0-9_-]+)"
)


def _redact_yaml_anchor_values(text: str) -> str:
    anchors = {
        anchor
        for key, anchor in _YAML_ALIAS_REFERENCE.findall(text)
        if is_credential_key(key)
    }
    for anchor in anchors:
        text = re.sub(
            rf"(?m)^(?P<anchor_indent>[ \t]*)[^\r\n]*"
            rf"&{re.escape(anchor)}\b[^\r\n]*(?:\r?\n|$)"
            r"(?:(?:[ \t]*\r?\n)|"
            r"(?P=anchor_indent)[ \t]+[^\r\n]*(?:\r?\n|$))*",
            _REDACTED + "\n",
            text,
        )
    return text


def redact_text(value: str) -> str:
    """Remove credential-shaped substrings from free text."""
    redacted = _redact_yaml_anchor_values(value)
    redacted = _redact_json_credentials(redacted)
    redacted = _redact_xml_credential_elements(redacted)
    redacted = _redact_structured_values(redacted)
    for pattern in _YAML_PATTERNS:
        # Keep the line break so following YAML keys remain anchored.
        redacted = pattern.sub(f"{_REDACTED}\n", redacted)
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
