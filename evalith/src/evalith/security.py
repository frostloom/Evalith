"""Credential handling and log redaction.

Model API keys are encrypted at rest with a Fernet key derived from
``EVALITH_SECRET_KEY`` (or a generated 0600 key file in the data directory).
Keys are never returned by the API, never written to message payloads, and a
logging filter removes credential-shaped values from log records.
"""

from __future__ import annotations

import base64
import hashlib
import html
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
        r"(?<![A-Za-z0-9])pass|db[_-]?pass|app[_-]?db[_-]?pass|account[_-]?key|client[_-]?key[_-]?data|password|passphrase|passwd|pwd|auth|authorization|github[_-]?pat|githubToken)[A-Za-z0-9_-]*)"
        r"[\"']?[ \t]*:\s*(?:(?:![^ \t\n]+|&[^ \t\n]+)[ \t]*)+\r?\n"
        r"(?:(?:[ \t]*\r?\n)|(?P=indent)[ \t]+.*(?:\r?\n|$))*"
    ),
    # YAML literal/folded block scalars, e.g. api_key: |
    #   sk-project-secret
    re.compile(
        r"(?im)^(?P<indent>[ \t]*)(?:-[ \t]+)?[\"']?"
        r"(?:[A-Za-z0-9_-]*(?:(?<![A-Za-z0-9])pass|private[_-]?key|credential|secret|token|key|db[_-]?pass|app[_-]?db[_-]?pass|account[_-]?key|client[_-]?key[_-]?data|password|passphrase|passwd|pwd|auth|authorization|github[_-]?pat|githubToken)[A-Za-z0-9_-]*)"
        r"[\"']?[ \t]*:\s*(?:(?:![^ \t\n]+|&[^ \t\n]+)[ \t]+)*[|>][-+0-9]*[ \t]*(?:#[^\n]*)?\r?\n"
        r"(?:(?:[ \t]*\r?\n)|(?P=indent)[ \t]+.*(?:\r?\n|$))*"
    ),
    # Multiline triple-quoted values (TOML/Python style).
    re.compile(
        r"(?is)[\"']?(?:[A-Za-z0-9_]+[_-])*"
        r"(?:private[_-]?key|privateKey|apiKey|accessToken|dbPassword|jwtSecret|"
        r"clientSecret|refreshToken|credential|secret[_-]?access[_-]?key|"
        r"secret[_-]?key|signing[_-]?key|npm[_-]?auth[_-]?token|npmAuthToken|"
        r"access[_-]?key[_-]?id|access[_-]?key|accessKey|api[_-]?key|access[_-]?token|client[_-]?secret|"
        r"token|secret|account[_-]?key|client[_-]?key[_-]?data|sig|signature|password|passphrase|passwd|pwd|pass|auth|authorization|github[_-]?pat|githubToken)[\"']?\s*[:=]\s*"
        r"(?:[\"']{3}.*?[\"']{3}|[\"']{3}.*?[\"']{3})"
    ),
    # Untagged YAML plain scalars continued on indented lines.
    re.compile(
        r"(?im)^(?P<indent>[ \t]*)(?:-[ \t]+)?[\"']?"
        r"(?:[A-Za-z0-9_-]*(?:private[_-]?key|credential|secret|token|key|"
        r"(?<![A-Za-z0-9])pass|db[_-]?pass|app[_-]?db[_-]?pass|account[_-]?key|client[_-]?key[_-]?data|password|passphrase|passwd|pwd|auth|authorization|github[_-]?pat|githubToken)[A-Za-z0-9_-]*)"
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
        r"(?i)(?<![A-Za-z0-9])[\"']?(?:[A-Za-z0-9]+[_-]|[A-Za-z][A-Za-z0-9]*(?=apiKey|Token|Password|Passphrase|Secret|Credential|Authorization))*"
        r"(?:private[_-]?key|privateKey|apiKey|accessToken|dbPassword|jwtSecret|"
        r"clientSecret|refreshToken|credential|secret[_-]?access[_-]?key|secret[_-]?key|signing[_-]?key|"
        r"npm[_-]?auth[_-]?token|npmAuthToken|access[_-]?key[_-]?id|"
        r"access[_-]?key|accessKey|"
        r"api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|"
        r"account[_-]?key|client[_-]?key[_-]?data|sig|signature|password|passphrase|passwd|pwd|pass|auth|authorization|github[_-]?pat|githubToken)[\"']?\s*[:=]\s*"
        r"(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\n,}]+)"
    ),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[a-z0-9._~+/=-]+"),
    # Connection strings with userinfo, including token-only forms such as
    # https://ghp_token@github.com and user:password@ forms.
    re.compile(
        r"(?i)\b[a-z][a-z0-9+.-]*://[^@\s/]+@[^\s,}\"']+"
    ),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?"
        r"-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----",
        re.S,
    ),
]

_YAML_PATTERNS = _SECRET_PATTERNS[:3]
_SECRET_PATTERNS = _SECRET_PATTERNS[3:]
_SECRET_PATTERNS.insert(
    0,
    re.compile(
        r"(?is)<[A-Za-z0-9_.:-]*(?:private[_-]?key|credential|secret|token|"
        r"key|db[_-]?pass|app[_-]?db[_-]?pass|account[_-]?key|client[_-]?key[_-]?data|password|passphrase|passwd|pwd|auth|authorization|github[_-]?pat|githubToken)[A-Za-z0-9_.:-]*"
        r"(?:\s[^>]*)?>.*?</[A-Za-z0-9_.:-]+\s*>"
    ),
)
_SECRET_PATTERNS.insert(
    1,
    re.compile(
        r"(?is)<[A-Za-z][A-Za-z0-9_.:-]*[^>]*\b(?:name|key|id)\s*=\s*[\"'][^\"']*"
        r"(?:private[_-]?key|credential|secret|token|key|password|passphrase|passwd|pwd|"
        r"pass|auth|authorization|github[_-]?pat|githubToken)[^\"']*[\"'][^>]*>.*?</[A-Za-z0-9_.:-]+\s*>"
    ),
)
_SECRET_PATTERNS.insert(
    2,
    re.compile(
        r"(?is)<[A-Za-z][A-Za-z0-9_.:-]*[^>]*\b(?:name|key|id)\s*=\s*[\"'][^\"']*"
        r"(?:private[_-]?key|credential|secret|token|key|password|passphrase|passwd|pwd|"
        r"pass|auth|authorization|github[_-]?pat|githubToken)[^\"']*[\"'][^>]*>"
    ),
)
_SECRET_PATTERNS.insert(
    3,
    re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{8,}|github_pat_[A-Za-z0-9_]{8,}|"
        r"gh[pousr]_[A-Za-z0-9]{8,}|xox[a-z]-[A-Za-z0-9-]{8,}|"
        r"AIza[0-9A-Za-z_-]{20,}|glpat-[A-Za-z0-9_-]{8,}|"
        r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}|npm_[A-Za-z0-9]{20,}|"
        r"(?:hvs|hvb|hvr|hvt)\.[A-Za-z0-9_-]{8,})\b"
    ),
)

_REDACTED = "[REDACTED]"

_STRUCTURED_CREDENTIAL = re.compile(
    r"(?is)(?<![A-Za-z0-9])[\"']?(?:[A-Za-z0-9]+[_-]|[A-Za-z][A-Za-z0-9]*(?=apiKey|Token|Password|Passphrase|Secret|Credential|Authorization))*"
    r"(?:private[_-]?key|privateKey|apiKey|accessToken|dbPassword|jwtSecret|"
    r"clientSecret|refreshToken|credential|secret[_-]?access[_-]?key|secret[_-]?key|"
    r"signing[_-]?key|npm[_-]?auth[_-]?token|npmAuthToken|"
    r"access[_-]?key[_-]?id|access[_-]?key|accessKey|api[_-]?key|access[_-]?token|client[_-]?secret|"
    r"token|secret|account[_-]?key|client[_-]?key[_-]?data|sig|signature|password|passphrase|passwd|pwd|pass|auth|authorization|github[_-]?pat|githubToken)[\"']?\s*[:=]\s*"
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


_XML_TAG = re.compile(r"(?is)<\s*(/)?\s*([A-Za-z][A-Za-z0-9_.:-]*)([^>]*)>")
_XML_CREDENTIAL_TERM = re.compile(
    r"(?i)(?:private[_-]?key|credential|secret|token|key|password|passphrase|passwd|pwd|"
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
        if not _XML_CREDENTIAL_TERM.search(html.unescape(name + attrs)):
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
    "accesskey",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "privatekey",
    "secretkey",
    "signingkey",
    "password",
    "passphrase",
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
    "accesskey",
    "unresolvedcredential",
    "openaikey",
    "clientkeydata",
    "awsaccesskeyid",
    "awssecretaccesskey",
    "accesskeyid",
    "secretaccesskey",
}
_JSON_CREDENTIAL_SUFFIXES = (
    "apikey",
    "accesskey",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "privatekey",
    "secretkey",
    "signingkey",
    "password",
    "passphrase",
    "passwd",
    "pass",
    "pwd",
    "token",
    "secret",
    "credential",
    "authorization",
    "auth",
    "accountkey",
    "accesskey",
    "unresolvedcredential",
    "openaikey",
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
    "service",
    "svc",
    "stripe",
    "database",
    "prod",
    "production",
    "dev",
    "development",
    "stage",
    "staging",
    "test",
    "qa",
    "uat",
    "local",
    "primary",
    "replica",
    "readonly",
    "awssession",
    "smtp",
    "redis",
}


def is_credential_key(key: object) -> bool:
    raw_key = str(key)
    normalized = re.sub(r"[^a-z0-9]", "", raw_key.casefold())
    if normalized in _JSON_EXACT_CREDENTIAL_KEYS:
        return True
    for suffix in _JSON_CREDENTIAL_SUFFIXES:
        if not normalized.endswith(suffix):
            continue
        prefix = normalized[: -len(suffix)]
        if prefix and re.search(r"[^A-Za-z0-9]", raw_key):
            return True
        if prefix and re.search(r"[a-z][A-Z]", raw_key):
            return True
        while prefix:
            if prefix in _JSON_CREDENTIAL_PREFIXES or re.fullmatch(
                r"[a-z]+[0-9]+", prefix
            ):
                return True
            stripped = False
            for known in sorted(_JSON_CREDENTIAL_PREFIXES, key=len, reverse=True):
                if prefix.endswith(known) and len(prefix) > len(known):
                    prefix = prefix[: -len(known)]
                    stripped = True
                    break
            if not stripped:
                break
    return False


_ESCAPED_JSON_ENTRY = re.compile(
    r'"((?:[^"\\]|\\.)*)"[ \t]*:[ \t]*'
    r'("(?:[^"\\]|\\.)*"|[^,}\]\r\n]+)'
)


def _redact_embedded_json_keys(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_key = match.group(1)
        if "\\u" not in raw_key.casefold():
            return match.group(0)
        try:
            key = json.loads(f'"{raw_key}"')
        except ValueError:
            return match.group(0)
        if not is_credential_key(key):
            return match.group(0)
        return f'"{raw_key}": "[REDACTED]"'

    return _ESCAPED_JSON_ENTRY.sub(replace, text)


def _redact_json_credentials(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return text
    try:
        parsed = json.loads(text)
    except ValueError:
        return text

    def clean_annotation(item):
        if isinstance(item, str) and item.lstrip().startswith(("{", "[")):
            try:
                inner = json.loads(item)
            except ValueError:
                return item
            return json.dumps(walk(inner), ensure_ascii=False)
        return item

    def walk(value):
        if isinstance(value, dict):
            if (
                "name" in value
                and "value" in value
                and is_credential_key(value.get("name"))
            ):
                cleaned = {}
                for key, item in value.items():
                    cleaned[key] = _REDACTED if key == "value" else walk(item)
                return cleaned
            if str(value.get("kind", "")).casefold() == "secret":
                cleaned = {}
                for key, item in value.items():
                    if key in ("data", "stringData"):
                        cleaned[key] = _REDACTED
                    elif str(key).endswith("last-applied-configuration"):
                        cleaned[key] = clean_annotation(item)
                    else:
                        cleaned[key] = walk(item)
                return cleaned
            cleaned = {}
            for key, item in value.items():
                if is_credential_key(key):
                    cleaned[key] = _REDACTED
                elif str(key).endswith("last-applied-configuration"):
                    cleaned[key] = clean_annotation(item)
                else:
                    cleaned[key] = walk(item)
            return cleaned
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return json.dumps(walk(parsed), ensure_ascii=False)


_YAML_ALIAS_REFERENCE = re.compile(
    r"(?im)^[ \t]*(?:-[ \t]+)?[\"']?([^:\r\n\"']+?)[\"']?"
    r"[ \t]*:[ \t]*\*([^\s\[\]{},]+)"
)
_YAML_FLOW_ALIAS_REFERENCE = re.compile(
    r"(?i)[,{]\s*[\"']?([^:\r\n\"',}]+?)[\"']?\s*:\s*\*([^\s\[\]{},]+)"
)


def _redact_yaml_anchor_values(text: str) -> str:
    references = _YAML_ALIAS_REFERENCE.findall(text)
    references += _YAML_FLOW_ALIAS_REFERENCE.findall(text)
    anchors = {
        anchor for key, anchor in references if is_credential_key(key)
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
        text = re.sub(
            rf"&{re.escape(anchor)}\b[^,}}\r\n]*",
            _REDACTED,
            text,
        )
    return text


_K8S_ENV_ENTRY = re.compile(
    r"(?im)^(?P<indent>[ \t]*)-[ \t]+[\"']?name[\"']?[ \t]*:[ \t]*"
    r"(?P<name>[^\r\n]+?)[ \t]*\r?\n"
    r"(?P<body>(?:(?:[ \t]+[^\r\n]*|[ \t]*)\r?\n){0,6}?"
    r"[ \t]+[\"']?value[\"']?[ \t]*:)"
    r"(?P<value>[ \t]*(?:[|>][-+0-9]*[ \t]*(?:#[^\r\n]*)?\r?\n"
    r"(?:[ \t]+[^\r\n]*(?:\r?\n|$))*)|(?s:\"[^\"]*\")|(?s:'[^']*')|"
    r"[^\r\n]*)"
)


_K8S_ITEM = re.compile(
    r"(?m)^(?P<indent>[ \t]*)-[ \t]+(?P<first>[^\r\n]*)(?:\r?\n|$)"
    r"(?P<rest>(?:(?:(?P=indent)[ \t]+(?![ \t]*-[ \t])[^\r\n]*|[ \t]*)\r?\n)*"
    r"(?:(?P=indent)[ \t]+(?![ \t]*-[ \t])[^\r\n]*)?)"
)
_K8S_ITEM_NAME = re.compile(
    r"(?m)^(?P<prefix>[ \t]*(?:-[ \t]+)?[\"']?name[\"']?[ \t]*:[ \t]*)"
    r"(?P<name>[^\r\n#]+?)[ \t]*(?:#[^\r\n]*)?$"
)
_K8S_ITEM_VALUE = re.compile(
    r"(?m)^[ \t]*(?:-[ \t]+)?[\"']?value[\"']?[ \t]*:[ \t]*(?P<value>[ \t]*"
    r"(?:[|>][-+0-9]*[ \t]*(?:#[^\r\n]*)?\r?\n"
    r"(?:[ \t]+[^\r\n]*(?:\r?\n|$))*)|(?s:\"[^\"]*\")|(?s:'[^']*')|"
    r"[^\r\n]*)"
)


_FLOW_FIELD_SEGMENT = re.compile(
    r"^[ \t\r\n]*(?:#[^\r\n]*(?:\r?\n|$)[ \t\r\n]*)*"
    r"[\"']?([A-Za-z0-9_<>-]+)[\"']?[ \t\r\n]*:[ \t\r\n]*(.*)$",
    re.S,
)


def _flow_segment_fields(inner: str) -> dict[str, tuple[int, int]]:
    fields: dict[str, tuple[int, int]] = {}
    depth = 0
    quote: str | None = None
    escaped = False
    in_comment = False
    start = 0
    segments: list[tuple[int, int]] = []
    for index, char in enumerate(inner):
        if in_comment:
            if char == "\n":
                in_comment = False
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char == "#" and (index == 0 or inner[index - 1] in " \t\n"):
            in_comment = True
        elif char in "\"'" and _starts_yaml_quoted_scalar(inner, index):
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == "," and depth == 0:
            segments.append((start, index))
            start = index + 1
    segments.append((start, len(inner)))
    for seg_start, seg_end in segments:
        raw = inner[seg_start:seg_end]
        match = _FLOW_FIELD_SEGMENT.match(raw)
        if match is None:
            continue
        value_start = seg_start + match.start(2)
        value_end = seg_start + match.end(2)
        fields[match.group(1)] = (value_start, value_end)
    return fields


def _unquoted_brace_starts(text: str) -> list[int]:
    starts: list[int] = []
    quote: str | None = None
    escaped = False
    in_comment = False
    for index, char in enumerate(text):
        if in_comment:
            if char == "\n":
                in_comment = False
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char == "#" and (index == 0 or text[index - 1] in " \t\n"):
            in_comment = True
        elif char in "\"'" and _starts_yaml_quoted_scalar(text, index):
            quote = char
        elif char == "{":
            starts.append(index)
    return starts


def _merge_aliases(value: str) -> list[str]:
    stripped = value.strip()
    if stripped.startswith("["):
        return re.findall(r"\*([^\s\[\]{},]+)", stripped)
    if stripped.startswith("*") and len(stripped) > 1:
        return [stripped[1:].strip()]
    return []


def _redact_flow_map_block(
    block: str, source: str | None = None, base_offset: int = 0
) -> str:
    if len(block) < 2 or not block.startswith("{") or not block.endswith("}"):
        return block
    source = source if source is not None else block
    inner = block[1:-1]
    out: list[str] = []
    cursor = 0
    for start in _unquoted_brace_starts(inner):
        if start < cursor:
            continue
        end = _flow_mapping_end(inner, start)
        out.append(inner[cursor:start])
        out.append(
            _redact_flow_map_block(
                inner[start:end], source, base_offset + 1 + start
            )
        )
        cursor = end
    inner = "".join(out) + inner[cursor:]
    fields = _flow_segment_fields(inner)
    name_field = fields.get("name")
    value_field = fields.get("value")
    if name_field is None and value_field is not None:
        merge_field = fields.get("<<")
        name = ""
        if merge_field is not None:
            raw_merge = inner[merge_field[0] : merge_field[1]]
            for alias in _merge_aliases(raw_merge):
                resolved = _anchor_mapping_name(
                    source, alias, base_offset + 1 + merge_field[0]
                )
                if resolved is not None:
                    name = resolved
                    break
    elif name_field is not None:
        name = _resolve_env_name(
            source,
            inner[name_field[0] : name_field[1]],
            base_offset + 1 + name_field[0],
        )
    else:
        name = ""
    if value_field is not None:
        if is_credential_key(name):
            inner = (
                inner[: value_field[0]]
                + _REDACTED
                + inner[value_field[1] :]
            )
    return "{" + inner + "}"


def _redact_kubernetes_flow_env(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(text)
        except ValueError:
            pass
        else:
            return text

    out: list[str] = []
    cursor = 0
    for start in _unquoted_brace_starts(text):
        if start < cursor:
            continue
        end = _flow_mapping_end(text, start)
        if end <= start + 1:
            continue
        out.append(text[cursor:start])
        out.append(
            _redact_flow_map_block(text[start:end], text, start)
        )
        cursor = end
    out.append(text[cursor:])
    return "".join(out)

def _redact_kubernetes_env_values(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(text)
        except ValueError:
            pass
        else:
            return text
    text = _normalize_escaped_env_keys(text)
    text = _normalize_block_env_names(text)
    aliases: set[str] = set()
    for match in _K8S_ENV_ENTRY.finditer(text):
        if is_credential_key(_yaml_key_name(match.group("name"))):
            value = match.group("value").lstrip()
            if value.startswith("*") and len(value) > 1:
                aliases.add(value[1:].strip())
    for match in _K8S_ITEM.finditer(text):
        block = match.group(0)
        name_match = _K8S_ITEM_NAME.search(block)
        value_match = _K8S_ITEM_VALUE.search(block)
        if value_match is None:
            continue
        if name_match is not None:
            name = _resolve_env_name(
                text,
                name_match.group("name"),
                match.start() + name_match.start("name"),
            )
        else:
            merge_match = re.search(
                r"(?m)^[ \t]*(?:-[ \t]+)?<<[ \t]*:[ \t]*(?P<value>[^\r\n]+)",
                block,
            )
            if merge_match is None:
                continue
            name = ""
            for alias in _merge_aliases(merge_match.group("value")):
                merged = _anchor_mapping_name(
                    text, alias, match.start() + merge_match.start()
                )
                if merged is not None:
                    name = merged
                    break
        if not is_credential_key(name):
            continue
        value = value_match.group("value").lstrip()
        if value.startswith("*") and len(value) > 1:
            aliases.add(value[1:].strip())
    for start in _unquoted_brace_starts(text):
        end = _flow_mapping_end(text, start)
        if end <= start + 1:
            continue
        inner = text[start + 1 : end - 1]
        fields = _flow_segment_fields(inner)
        name_field = fields.get("name")
        value_field = fields.get("value")
        if value_field is None:
            continue
        if name_field is not None:
            name = _resolve_env_name(
                text,
                inner[name_field[0] : name_field[1]],
                start + 1 + name_field[0],
            )
        else:
            merge_field = fields.get("<<")
            if merge_field is None:
                continue
            name = ""
            for alias in _merge_aliases(inner[merge_field[0] : merge_field[1]]):
                merged = _anchor_mapping_name(
                    text, alias, start + 1 + merge_field[0]
                )
                if merged is not None:
                    name = merged
                    break
        if not is_credential_key(name):
            continue
        value = inner[value_field[0] : value_field[1]].strip().strip("\"'")
        if value.startswith("*") and len(value) > 1:
            aliases.add(value[1:].strip())
    text = _redact_aliases_at_references(text, aliases)

    def replace(match: re.Match[str]) -> str:
        name = _resolve_env_name(
            text, match.group("name"), match.start("name")
        )
        if not is_credential_key(name):
            return match.group(0)
        return text[match.start() : match.start("body")] + match.group("body") + _REDACTED

    text = _K8S_ENV_ENTRY.sub(replace, text)

    def replace_item(match: re.Match[str]) -> str:
        block = match.group(0)
        name_match = _K8S_ITEM_NAME.search(block)
        if name_match is not None:
            name = _resolve_env_name(
                text,
                name_match.group("name"),
                match.start() + name_match.start("name"),
            )
        else:
            merge_match = re.search(
                r"(?m)^[ \t]*(?:-[ \t]+)?<<[ \t]*:[ \t]*(?P<value>[^\r\n]+)",
                block,
            )
            if merge_match is None:
                return block
            name = ""
            for alias in _merge_aliases(merge_match.group("value")):
                merged = _anchor_mapping_name(
                    text, alias, match.start() + merge_match.start()
                )
                if merged is not None:
                    name = merged
                    break
            else:
                return block
        if not is_credential_key(name):
            return block
        value_match = _K8S_ITEM_VALUE.search(block)
        if value_match is None:
            return block
        return (
            block[: value_match.start("value")]
            + _REDACTED
            + block[value_match.end("value") :]
        )

    return _redact_kubernetes_flow_env(_K8S_ITEM.sub(replace_item, text))


_K8S_SECRET_KIND = re.compile(
    r"(?im)^[ \t]*(?:-[ \t]+)?[\"']?kind[\"']?[ \t]*:[ \t]*"
    r"(?:(?:![^\s#]+|&[^\s#]+)[ \t]+)*"
    r"[\"']?Secret[\"']?[ \t]*(?:#[^\r\n]*)?\r?$"
)
_K8S_SECRET_FLOW_KIND = re.compile(
    r"(?i)[{,][ \t]*[\"']?kind[\"']?[ \t]*:[ \t]*"
    r"(?:(?:![^\s,}]+|&[^\s,}]+)[ \t]+)*[\"']?Secret\b"
)
_K8S_SECRET_FLOW_ALIAS_KIND = re.compile(
    r"(?i)[{,][ \t]*[\"']?kind[\"']?[ \t]*:[ \t]*"
    r"\*([^\s\[\]{},]+)"
)
_K8S_SECRET_FLOW_OPEN = re.compile(
    r"(?im)(?:^|[{,])[ \t]*"
    r"(?:(?:![^\s,}]+|&[^\s,}]+)[ \t]+)?"
    r"[\"']?(?P<key>data|stringData)[\"']?[ \t]*:[ \t]*\{"
)


def _starts_yaml_quoted_scalar(text: str, index: int) -> bool:
    return index == 0 or text[index - 1] in " \t\r\n[{,:=-"


def _strip_yaml_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'" and _starts_yaml_quoted_scalar(value, index):
            quote = char
        elif char == "#" and (index == 0 or value[index - 1] in " \t"):
            return value[:index].rstrip()
    return value.strip()


def _anchor_scalar(rest: str) -> str:
    stripped = rest.lstrip(" \t")
    while stripped.startswith(("!", "&")):
        parts = stripped.split(None, 1)
        if len(parts) < 2:
            return ""
        stripped = parts[1].lstrip(" \t")
    if not stripped:
        return ""
    if stripped[0] in "\"'":
        quote = stripped[0]
        escaped = False
        for index in range(1, len(stripped)):
            char = stripped[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                return _decode_yaml_scalar(stripped[: index + 1])
        return ""
    if stripped[0] in "|>":
        body = stripped.split("\n", 1)
        lines: list[str] = []
        for line in body[1].splitlines() if len(body) > 1 else []:
            if not line.strip():
                continue
            if line[0] not in " \t":
                break
            lines.append(line.strip())
        return " ".join(lines)
    token = stripped.split("#", 1)[0].strip()
    return _decode_yaml_scalar(token.split()[0] if token else "")


def _yaml_alias_references(text: str) -> dict[str, list[int]]:
    references: dict[str, list[int]] = {}
    quote: str | None = None
    escaped = False
    in_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "#" and (
            index == 0 or text[index - 1] in " \t\n"
        ):
            in_comment = True
            index += 1
            continue
        if char in "\"'" and _starts_yaml_quoted_scalar(text, index):
            quote = char
            index += 1
            continue
        if char == "*":
            match = re.match(r"\*([^\s\[\]{},]+)", text[index:])
            if match is not None:
                references.setdefault(match.group(1), []).append(index)
                index += match.end()
                continue
        index += 1
    return references


def _yaml_anchor_positions(text: str) -> dict[str, list[int]]:
    positions: dict[str, list[int]] = {}
    quote: str | None = None
    escaped = False
    in_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "#" and (
            index == 0 or text[index - 1] in " \t\n"
        ):
            in_comment = True
            index += 1
            continue
        if char in "\"'" and _starts_yaml_quoted_scalar(text, index):
            quote = char
            index += 1
            continue
        if char == "&":
            match = re.match(r"&([^\s\[\]{},]+)[ \t]*", text[index:])
            if match is not None:
                positions.setdefault(match.group(1), []).append(index)
                index += match.end()
                continue
        index += 1
    return positions


def _anchor_position(
    text: str, anchor: str, before: int | None = None
) -> int | None:
    candidates = [
        position
        for position in _yaml_anchor_positions(text).get(anchor, [])
        if before is None or position < before
    ]
    return max(candidates) if candidates else None


def _yaml_anchor_values(text: str, before: int | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    quote: str | None = None
    escaped = False
    in_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "#" and (
            index == 0 or text[index - 1] in " \t\n"
        ):
            in_comment = True
            index += 1
            continue
        if char in "\"'" and _starts_yaml_quoted_scalar(text, index):
            quote = char
            index += 1
            continue
        if char == "&" and (before is None or index < before):
            match = re.match(r"&([^\s\[\]{},]+)[ \t]*", text[index:])
            if match is not None:
                values[match.group(1)] = _anchor_scalar(
                    text[index + match.end() :]
                )
                index += match.end()
                continue
        index += 1
    return values


def _resolve_env_name(
    text: str, value: str, position: int | None = None
) -> str:
    raw = _yaml_key_name(_strip_yaml_comment(value))
    if raw.startswith("*") and len(raw) > 1:
        return _yaml_anchor_values(text, before=position).get(
            raw[1:], "unresolved-credential"
        )
    return raw


def _anchor_mapping_name(
    text: str,
    anchor: str,
    before: int | None = None,
    seen: set[tuple[str, int]] | None = None,
) -> str | None:
    position = _anchor_position(text, anchor, before)
    if position is None:
        return None
    seen = set() if seen is None else seen
    key = (anchor, position)
    if key in seen:
        return None
    seen.add(key)
    rest_start = position + 1 + len(anchor)
    rest = text[rest_start:].lstrip(" \t")
    offset = len(text) - len(rest)
    if rest.startswith("{"):
        end = _flow_mapping_end(rest, 0)
        fields = _flow_segment_fields(rest[1 : end - 1])
        name_field = fields.get("name")
        if name_field is not None:
            return _resolve_env_name(
                text,
                rest[1 + name_field[0] : 1 + name_field[1]],
                offset + 1 + name_field[0],
            )
        merge_field = fields.get("<<")
        if merge_field is None:
            return None
        for alias in _merge_aliases(rest[1 + merge_field[0] : 1 + merge_field[1]]):
            resolved = _anchor_mapping_name(
                text, alias, offset + 1 + merge_field[0], seen
            )
            if resolved is not None:
                return resolved
        return None
    seen.discard(key)
    return _anchor_block_name(text, anchor, before, seen)


def _anchor_block_name(
    text: str,
    anchor: str,
    before: int | None = None,
    seen: set[tuple[str, int]] | None = None,
) -> str | None:
    position = _anchor_position(text, anchor, before)
    if position is None:
        return None
    seen = set() if seen is None else seen
    key = (anchor, position)
    if key in seen:
        return None
    seen.add(key)
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end < 0:
        return None
    indent_match = re.match(r"[ \t]*", text[line_start:])
    indent = indent_match.group(0) if indent_match else ""
    body_start = line_end + 1
    body_end = body_start
    while body_end < len(text):
        next_end = text.find("\n", body_end)
        if next_end < 0:
            next_end = len(text)
        line = text[body_end:next_end]
        if line.strip() and not line.startswith(indent + " "):
            break
        body_end = next_end + 1
    body = text[body_start:body_end]
    name_match = _K8S_ITEM_NAME.search(body)
    if name_match is not None:
        return _resolve_env_name(
            text, name_match.group("name"), body_start + name_match.start("name")
        )
    merge_match = re.search(
        r"(?m)^[ \t]*(?:-[ \t]+)?<<[ \t]*:[ \t]*(?P<value>[^\r\n]+)",
        body,
    )
    if merge_match is None:
        return None
    for alias in _merge_aliases(merge_match.group("value")):
        resolved = _anchor_mapping_name(
            text,
            alias,
            body_start + merge_match.start(),
            seen,
        )
        if resolved is not None:
            return resolved
    return None

def _flow_mapping_end(text: str, start: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    in_comment = False
    for index in range(start, len(text)):
        char = text[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char == "#" and (index == start or text[index - 1] in " \t\n"):
            in_comment = True
        elif char in "\"'" and _starts_yaml_quoted_scalar(text, index):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)
_K8S_SECRET_ANCHOR = re.compile(
    r"(?i)&([^\s\[\]{},]+)[ \t]+[\"']?Secret\b"
)
_K8S_SECRET_ALIAS_KIND = re.compile(
    r"(?im)^[ \t]*(?:-[ \t]+)?[\"']?kind[\"']?[ \t]*:[ \t]*"
    r"\*([^\s\[\]{},]+)"
)
_K8S_SECRET_BLOCK_KIND = re.compile(
    r"(?im)^[ \t]*(?:-[ \t]+)?[\"']?kind[\"']?[ \t]*:[ \t]*"
    r"(?:(?:![^\s#]+|&[^\s#]+)[ \t]+)*"
    r"[|>][-+0-9]*[ \t]*(?:#[^\r\n]*)?\r?\n"
    r"(?:[ \t]*\r?\n)*[ \t]+[\"']?Secret[\"']?[ \t]*\r?$"
)
_K8S_SECRET_DATA_ALIAS = re.compile(
    r"(?im)^[ \t]*(?:-[ \t]+)?[\"']?(?:data|stringData)[\"']?[ \t]*:[ \t]*"
    r"\*([^\s\[\]{},]+)"
)
_K8S_SECRET_FLOW_DATA_ALIAS = re.compile(
    r"(?i)[{,][ \t]*[\"']?(?:data|stringData)[\"']?[ \t]*:[ \t]*"
    r"\*([^\s\[\]{},]+)"
)
_ESCAPED_SECRET_KIND = re.compile(
    r"(?im)^(?P<prefix>[ \t]*(?:-[ \t]+)?[\"']?kind[\"']?[ \t]*:[ \t]*"
    r"(?:(?:![^\s]+|&[^\s]+)[ \t]+)*)"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*')"
)
_YAML_NAME_PREFIX = re.compile(r"^(?:(?:![^\s]+|&[^\s]+)[ \t]+)+")


_YAML_ESCAPE = re.compile(
    r"\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)",
    re.S,
)
_YAML_ESCAPE_CHARS = {
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "t": "\t",
    "n": "\n",
    "v": "\v",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    " ": " ",
    '"': '"',
    "/": "/",
    "\\": "\\",
    "N": "\x85",
    "_": "\xa0",
    "L": "\u2028",
    "P": "\u2029",
}


def _decode_yaml_scalar(raw: str) -> str:
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return str(json.loads(raw))
        except ValueError:
            pass
        body = raw[1:-1]

        def replace(match: re.Match[str]) -> str:
            token = match.group(1)
            if token[0] in "xuU":
                try:
                    return chr(int(token[1:], 16))
                except (ValueError, OverflowError):
                    return _REDACTED
            return _YAML_ESCAPE_CHARS.get(token, token)

        return _YAML_ESCAPE.sub(replace, body)
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return raw.strip(" \t\"'")


def _yaml_key_name(value: str) -> str:
    raw = _YAML_NAME_PREFIX.sub("", value.strip()).strip()
    return _decode_yaml_scalar(raw)


def _normalize_escaped_secret_kind(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group("value")
        value = _decode_yaml_scalar(raw) if raw else ""
        if value.casefold() == "secret":
            return f"{match.group('prefix')}\"Secret\""
        return match.group(0)

    return _ESCAPED_SECRET_KIND.sub(replace, text)
_K8S_SECRET_DATA = re.compile(
    r"(?im)^(?P<indent>[ \t]*)(?:-[ \t]+)?"
    r"(?:(?:![^\s#]+|&[^\s#]+)[ \t]+)?[\"']?"
    r"(?P<key>data|stringData)[\"']?[ \t]*:[ \t]*"
    r"[^\r\n]*(?:\r?\n|$)"
    r"(?:(?:[ \t]*\r?\n)|(?P=indent)[ \t]+[^\r\n]*(?:\r?\n|$))*"
)


_ESCAPED_SECRET_KEY = re.compile(
    r"(?m)(?P<prefix>(?:^|[{,])[ \t]*(?:-[ \t]+)?)"
    r"\"(?P<key>(?:[^\"\\]|\\.)*)\""
    r"(?P<colon>[ \t]*:[ \t]*)"
)


_ESCAPED_KIND_KEY = re.compile(
    r"(?m)(?P<prefix>(?:^|[{,])[ \t]*(?:-[ \t]+)?)"
    r"\"(?P<key>(?:[^\"\\]|\\.)*)\""
    r"(?P<colon>[ \t]*:[ \t]*)"
)
_ESCAPED_ENV_KEY = _ESCAPED_KIND_KEY


_BLOCK_ENV_NAME = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?P<dash>-[ \t]+)?"
    r"[\"']?name[\"']?[ \t]*:[ \t]*"
    r"(?:(?:![^\s#]+|&[^\s#]+)[ \t]+)*"
    r"(?P<indicator>[|>][-+0-9]*)[ \t]*(?:#[^\r\n]*)?\r?\n"
)
_BLOCK_ENV_KEY = re.compile(r"^[A-Za-z0-9_.\"'-]+[ \t]*:")


def _normalize_block_env_names(text: str) -> str:
    out: list[str] = []
    cursor = 0
    for match in _BLOCK_ENV_NAME.finditer(text):
        if match.start() < cursor:
            continue
        lines: list[str] = []
        position = match.end()
        while position < len(text):
            line_end = text.find("\n", position)
            if line_end < 0:
                line_end = len(text)
            line = text[position:line_end]
            stripped = line.strip()
            if not stripped:
                break
            if line[0] not in " \t":
                break
            if _BLOCK_ENV_KEY.match(stripped):
                break
            lines.append(stripped)
            position = line_end + 1
        if not lines:
            continue
        out.append(text[cursor : match.start()])
        out.append(
            f"{match.group('indent')}{match.group('dash') or ''}"
            f"name: {' '.join(lines)}\n"
        )
        cursor = position
    out.append(text[cursor:])
    return "".join(out)

def _normalize_escaped_env_keys(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        key = _decode_yaml_scalar(f'"{match.group("key")}"')
        if key not in ("name", "value"):
            return match.group(0)
        return f"{match.group('prefix')}{key}{match.group('colon')}"

    return _ESCAPED_ENV_KEY.sub(replace, text)


def _normalize_escaped_kind_key(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        key = _decode_yaml_scalar(f'"{match.group("key")}"')
        if key != "kind":
            return match.group(0)
        return f"{match.group('prefix')}kind{match.group('colon')}"

    return _ESCAPED_KIND_KEY.sub(replace, text)


def _normalize_escaped_secret_keys(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        key = _decode_yaml_scalar(f'"{match.group("key")}"')
        if key not in ("data", "stringData"):
            return match.group(0)
        return f"{match.group('prefix')}{key}{match.group('colon')}"

    return _ESCAPED_SECRET_KEY.sub(replace, text)


def _redact_anchored_secret_data(
    text: str, anchor: str, before: int | None = None
) -> str:
    position = _anchor_position(text, anchor, before)
    if position is None:
        return text
    start = position + 1 + len(anchor)
    while start < len(text) and text[start] in " \t":
        start += 1
    if start < len(text) and text[start] == "{":
        end = _flow_mapping_end(text, start)
        return text[:position] + f"&{anchor} {_REDACTED}" + text[end:]
    line_start = text.rfind("\n", 0, position) + 1
    indent_match = re.match(r"[ \t]*", text[line_start:])
    indent = indent_match.group(0) if indent_match else ""
    line_end = text.find("\n", start)
    if line_end < 0:
        return text[:position] + f"&{anchor} {_REDACTED}"
    end = line_end + 1
    while end < len(text):
        next_end = text.find("\n", end)
        line = text[end : next_end if next_end >= 0 else len(text)]
        if line.strip() == "":
            end = len(text) if next_end < 0 else next_end + 1
            continue
        if line.startswith(indent) and len(line) > len(indent) and line[len(indent)] in " \t":
            end = len(text) if next_end < 0 else next_end + 1
            continue
        break
    return text[:position] + f"&{anchor} {_REDACTED}\n" + text[end:]


def _redact_aliases_at_references(
    text: str, aliases: set[str]
) -> str:
    references = _yaml_alias_references(text)
    definitions: set[tuple[str, int]] = set()
    for alias in aliases:
        for reference in references.get(alias, []):
            position = _anchor_position(text, alias, reference)
            if position is not None:
                definitions.add((alias, position))
    for alias, position in sorted(
        definitions, key=lambda item: item[1], reverse=True
    ):
        text = _redact_anchored_secret_data(text, alias, position + 1)
    return text


_EXPLICIT_SECRET_KEY = re.compile(
    r"(?m)^(?P<indent>[ \t]*)\?\s*[\"']?(?P<key>data|stringData)[\"']?[ \t]*\r?\n"
    r"(?P=indent):[ \t]*"
)


def _normalize_explicit_secret_keys(text: str) -> str:
    return _EXPLICIT_SECRET_KEY.sub(
        lambda match: (
            f"{match.group('indent')}{match.group('key')}: "
        ),
        text,
    )


def _redact_kubernetes_secret_data(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(text)
        except ValueError:
            pass
        else:
            return text
    text = _normalize_explicit_secret_keys(text)
    text = _normalize_escaped_kind_key(text)
    text = _normalize_escaped_secret_kind(text)
    alias_kind = any(
        _yaml_anchor_values(text, before=match.start())
        .get(match.group(1), "")
        .casefold()
        == "secret"
        for match in _K8S_SECRET_ALIAS_KIND.finditer(text)
    )
    flow_alias_kind = any(
        _yaml_anchor_values(text, before=match.start())
        .get(match.group(1), "")
        .casefold()
        == "secret"
        for match in _K8S_SECRET_FLOW_ALIAS_KIND.finditer(text)
    )
    flow = bool(
        _K8S_SECRET_FLOW_KIND.search(text)
        or _K8S_SECRET_FLOW_OPEN.search(text)
        or flow_alias_kind
    )
    block_kind = bool(_K8S_SECRET_BLOCK_KIND.search(text))
    line_kind = bool(_K8S_SECRET_KIND.search(text))
    if not flow and not alias_kind and not block_kind and not line_kind:
        return text

    text = _normalize_escaped_secret_keys(text)
    payload_aliases = {
        match.group(1) for match in re.finditer(r"\*([^\s\[\]{},]+)", text)
    }
    text = _redact_aliases_at_references(text, payload_aliases)

    def replace(match: re.Match[str]) -> str:
        return f"{match.group('indent')}{match.group('key')}: {_REDACTED}\n"

    text = _K8S_SECRET_DATA.sub(replace, text)
    text = _redact_yaml_last_applied(text)
    if flow:
        out: list[str] = []
        cursor = 0
        for match in _K8S_SECRET_FLOW_OPEN.finditer(text):
            if match.start() < cursor:
                continue
            start = match.end() - 1
            end = _flow_mapping_end(text, start)
            out.append(text[cursor : match.start()])
            out.append(f"{match.group('key')}: {_REDACTED}")
            cursor = end
        out.append(text[cursor:])
        text = "".join(out)
    return text


_JAVA_PROPERTIES_ENTRY = re.compile(
    r"(?im)^(?P<prefix>[ \t]*)(?P<key>(?:\\\r?\n[ \t]*|\\[^\r\n]|[A-Za-z0-9_.\-])+)"
    r"(?P<sep>[ \t]*[=:][ \t]*|[ \t]+)(?P<value>[^\r\n]*)(?=\r?\n|\Z)"
)
_JAVA_UNICODE_ESCAPE = re.compile(r"\\u([0-9A-Fa-f]{4})")


def _decode_java_key(key: str) -> str:
    key = re.sub(r"\\\r?\n[ \t]*", "", key)
    key = _JAVA_UNICODE_ESCAPE.sub(
        lambda match: chr(int(match.group(1), 16)), key
    )
    return re.sub(r"\\(.)", r"\1", key)


def _redact_java_properties(text: str) -> str:
    out: list[str] = []
    cursor = 0
    for match in _JAVA_PROPERTIES_ENTRY.finditer(text):
        if match.start() < cursor:
            continue
        raw_key = match.group("key")
        key = _decode_java_key(raw_key)
        if not is_credential_key(key):
            continue
        separator = match.group("sep")
        physical_value = match.group("value").rstrip()
        if (
            ":" in separator
            and "\\u" not in raw_key.casefold()
            and not physical_value.endswith("\\")
            and match.end() < len(text)
        ):
            after = text[match.end() :]
            newline = after.find("\n")
            next_line = after[newline + 1 :] if newline >= 0 else ""
            if next_line[:1] in (" ", "\t"):
                continue
        value = match.group("value").lstrip()
        if value.startswith(('"""', "'''")):
            continue
        if value.startswith(('"', "'")):
            quote = value[0]
            if value.count(quote) < 2 and not physical_value.endswith("\\"):
                continue
        if (
            value.startswith((":", "=", "{", "[", "&", "*", "|", ">", "!"))
            and not physical_value.endswith("\\")
        ):
            continue
        end = match.end()
        physical = match.group("value").rstrip()
        while physical.endswith("\\") and end < len(text):
            if text.startswith("\r\n", end):
                start = end + 2
            elif text[end] == "\n":
                start = end + 1
            elif text[end] == "\r":
                start = end + 1
            else:
                start = end
            newline = text.find("\n", start)
            if newline < 0:
                end = len(text)
                break
            physical = text[start:newline].rstrip("\r")
            end = newline + 1
        out.append(text[cursor : match.start()])
        display_key = re.sub(r"\\\r?\n[ \t]*", "", raw_key)
        replacement = f"{match.group('prefix')}{display_key} {_REDACTED}"
        if end > match.end():
            replacement += "\n"
        out.append(replacement)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


_YAML_LAST_APPLIED = re.compile(
    r"(?im)^(?P<prefix>[ \t]*[\"']?kubectl\.kubernetes\.io/"
    r"last-applied-configuration[\"']?[ \t]*:[ \t]*)(?P<value>.*)$"
)


def _redact_yaml_last_applied(text: str) -> str:
    return _YAML_LAST_APPLIED.sub(
        lambda match: f"{match.group('prefix')}\"[REDACTED]\"", text
    )


def redact_text(value: str) -> str:
    """Remove credential-shaped substrings from free text."""
    redacted = _redact_java_properties(value)
    redacted = _redact_embedded_json_keys(redacted)
    redacted = _redact_kubernetes_secret_data(redacted)
    redacted = _redact_kubernetes_env_values(redacted)
    redacted = _redact_yaml_anchor_values(redacted)
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
