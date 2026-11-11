"""Persistent executor definitions. Saving a definition never starts a process or request."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .db import Database, utc_now
from .security import CredentialCipher, is_credential_key, redact_text
from .service import WorkspaceError


def _invalid(message: str) -> None:
    raise WorkspaceError(message, status_code=422, code="invalid_executor_config")


def validate_definition(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "name",
        "backend",
        "command",
        "working_directory",
        "base_url",
        "timeout_seconds",
    }
    if set(payload) - allowed:
        _invalid("执行器配置包含不支持的字段。")
    name = payload.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        _invalid("请填写不超过 80 字的执行器名称。")
    backend = payload.get("backend")
    if not isinstance(backend, str) or backend not in {
        "local_command",
        "http_api",
        "harbor",
    }:
        _invalid("请选择本地命令、HTTP API 或 Harbor。")
    timeout = payload.get("timeout_seconds", 60)
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        _invalid("超时应为 1–3600 秒的整数。")
    command = payload.get("command", [])
    if (
        not isinstance(command, list)
        or len(command) > 64
        or any(
            not isinstance(arg, str)
            or not arg.strip()
            or len(arg) > 2048
            or "\x00" in arg
            or "\n" in arg
            for arg in command
        )
    ):
        _invalid("命令应为程序与参数组成的字符串数组。")
    if sum(map(len, command)) > 16384:
        _invalid("命令与参数过长。")
    directory = payload.get("working_directory") or None
    if directory is not None and (
        not isinstance(directory, str)
        or len(directory) > 4096
        or not Path(directory).is_absolute()
        or "\x00" in directory
    ):
        _invalid("工作目录应为绝对路径。")
    base_url = payload.get("base_url") or None
    if backend == "http_api":
        if command or directory:
            _invalid("HTTP API 不使用本地命令或工作目录。")
        if not isinstance(base_url, str) or len(base_url) > 2048:
            _invalid("请填写 HTTP API 地址。")
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
            valid = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and not parsed.fragment
                and (port is None or 1 <= port <= 65535)
            )
            credentials = (
                parsed.username is not None
                or parsed.password is not None
                or any(is_credential_key(key) for key, _ in parse_qsl(parsed.query))
            )
        except ValueError:
            valid, credentials = False, False
        if not valid:
            _invalid("API 地址应为有效的 HTTP 或 HTTPS URL。")
        if credentials:
            _invalid("API 地址不能包含凭据。")
    elif not command or base_url:
        _invalid("本地命令与 Harbor 需要程序和参数，不使用 HTTP 地址。")
    if any(
        is_credential_key(arg.lstrip("-").split("=")[0])
        for arg in command[1:]
        if arg.startswith("-")
    ):
        _invalid("请通过执行后端的凭据机制配置密钥，不要将密钥放在参数中。")
    definition = {
        "name": name.strip(),
        "backend": backend,
        "command": command,
        "working_directory": directory,
        "base_url": base_url,
        "timeout_seconds": timeout,
    }
    if any(
        redact_text(value) != value
        for value in [name, *command, directory or "", base_url or ""]
    ):
        _invalid("执行器定义不能包含明文凭据。")
    return definition


class ExecutorConfigs:
    def __init__(self, database: Database, cipher: CredentialCipher) -> None:
        self.database = database
        self.cipher = cipher

    def _serialize(self, row: Any) -> dict[str, Any]:
        definition = json.loads(
            self.cipher.decrypt(row["definition_encrypted"]) or "{}"
        )
        return {
            **definition,
            "id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "verified": False,
            "execution_available": False,
        }

    def list(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM executor_configs ORDER BY created_at, id"
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def save(
        self, payload: dict[str, Any], config_id: str | None = None
    ) -> dict[str, Any]:
        definition = validate_definition(payload)
        encrypted = self.cipher.encrypt(json.dumps(definition, ensure_ascii=False))
        now = utc_now()
        try:
            with self.database.connection() as connection:
                if config_id:
                    result = connection.execute(
                        "UPDATE executor_configs SET name=?, definition_encrypted=?, updated_at=? WHERE id=?",
                        (definition["name"], encrypted, now, config_id),
                    )
                    if result.rowcount == 0:
                        raise WorkspaceError("执行器配置不存在。", status_code=404)
                else:
                    config_id = "exe_" + uuid.uuid4().hex[:16]
                    connection.execute(
                        "INSERT INTO executor_configs (id,name,definition_encrypted,created_at,updated_at) VALUES (?,?,?,?,?)",
                        (config_id, definition["name"], encrypted, now, now),
                    )
                row = connection.execute(
                    "SELECT * FROM executor_configs WHERE id=?", (config_id,)
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise WorkspaceError("执行器配置名称已存在。", status_code=409) from exc
        return self._serialize(row)

    def delete(self, config_id: str) -> None:
        with self.database.connection() as connection:
            if (
                connection.execute(
                    "DELETE FROM executor_configs WHERE id=?", (config_id,)
                ).rowcount
                == 0
            ):
                raise WorkspaceError("执行器配置不存在。", status_code=404)
