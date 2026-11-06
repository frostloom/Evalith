"""Application service: project import, sessions, understanding and chat."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .config import Settings
from .db import Database, loads, utc_now
from .model_gateway import ModelConfig, ModelError, ModelGateway
from .project_access import (
    AccessError,
    ScanResult,
    build_model_context,
    resolve_root,
    scan_project,
)
from .security import CredentialCipher


class WorkspaceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "workspace_error") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class WorkspaceService:
    def __init__(self, db: Database, settings: Settings, cipher: CredentialCipher) -> None:
        self.db = db
        self.settings = settings
        self.cipher = cipher

    # ------------------------------------------------------------------
    # model configs
    # ------------------------------------------------------------------
    def create_model_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        provider = str(payload.get("provider", "stub")).strip()
        model_name = str(payload.get("model_name", "")).strip()
        base_url = str(payload.get("base_url", "") or "").strip() or None
        if not name:
            raise WorkspaceError("模型配置名称不能为空")
        if provider not in ("stub", "openai_compatible"):
            raise WorkspaceError("不支持的模型提供方")
        if provider != "stub" and not base_url:
            raise WorkspaceError("非替身模型必须填写 OpenAI 兼容服务地址")
        if not model_name:
            raise WorkspaceError("模型名称不能为空")
        now = utc_now()
        row = {
            "id": _id("mdl"),
            "name": name,
            "provider": provider,
            "base_url": base_url,
            "model_name": model_name,
            "api_key_encrypted": self.cipher.encrypt(
                str(payload.get("api_key", "") or "").strip() or None
            ),
            "created_at": now,
            "updated_at": now,
        }
        try:
            self.db.create_model_config(row)
        except Exception as exc:  # sqlite IntegrityError on duplicate name
            if "UNIQUE" in str(exc):
                raise WorkspaceError("模型配置名称已存在", status_code=409) from exc
            raise
        return self.serialize_model_config(self.db.get_model_config(row["id"]))

    def serialize_model_config(self, row: Any) -> dict[str, Any]:
        if row is None:
            raise WorkspaceError("模型配置不存在", status_code=404)
        data = dict(row)
        return {
            "id": data["id"],
            "name": data["name"],
            "provider": data["provider"],
            "base_url": data["base_url"],
            "model_name": data["model_name"],
            "has_api_key": bool(data["api_key_encrypted"]),
            "last_test_ok": data["last_test_ok"],
            "last_test_message": data["last_test_message"],
            "last_test_at": data["last_test_at"],
            "created_at": data["created_at"],
        }

    def gateway_for(self, model_config_id: str | None) -> ModelGateway:
        row = self.db.get_model_config(model_config_id)
        if row is None:
            return ModelGateway(None, timeout=self.settings.model_timeout_seconds)
        config = ModelConfig(
            id=row["id"],
            name=row["name"],
            provider=row["provider"],
            base_url=row["base_url"],
            model_name=row["model_name"],
            api_key=self.cipher.decrypt(row["api_key_encrypted"]),
        )
        return ModelGateway(config, timeout=self.settings.model_timeout_seconds)

    def test_model_config(self, model_config_id: str) -> dict[str, Any]:
        gateway = self.gateway_for(model_config_id)
        ok, message = gateway.test_connection()
        self.db.update_model_test(model_config_id, ok, message, utc_now())
        return {"ok": ok, "message": message}

    # ------------------------------------------------------------------
    # project import
    # ------------------------------------------------------------------
    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise WorkspaceError("项目名称不能为空")
        root_raw = str(payload.get("root_path", "")).strip()
        try:
            root = resolve_root(root_raw, access_mode=self.settings.access_mode)
        except (AccessError, OSError) as exc:
            raise WorkspaceError(str(exc), status_code=422, code=getattr(exc, "code", "root_error")) from exc
        model_config_id = payload.get("model_config_id") or None
        if model_config_id and self.db.get_model_config(model_config_id) is None:
            raise WorkspaceError("选择的模型配置不存在", status_code=422)
        include_paths = self._string_list(payload.get("include_paths"))
        exclude_patterns = self._string_list(payload.get("exclude_patterns"))
        supplemental = self._supplemental(payload.get("supplemental"))
        try:
            scan = scan_project(
                root,
                include_paths,
                exclude_patterns,
                max_files=self.settings.max_files,
                max_file_bytes=self.settings.max_file_bytes,
            )
        except AccessError as exc:
            raise WorkspaceError(
                str(exc), status_code=422, code=exc.code
            ) from exc
        project_id = _id("prj")
        snapshot_id = self._store_snapshot(project_id, scan)
        now = utc_now()
        self.db.create_project(
            {
                "id": project_id,
                "name": name,
                "root_path": str(root),
                "include_paths": json.dumps(include_paths, ensure_ascii=False),
                "exclude_patterns": json.dumps(exclude_patterns, ensure_ascii=False),
                "supplemental": json.dumps(supplemental, ensure_ascii=False),
                "model_config_id": model_config_id,
                "snapshot_id": snapshot_id,
                "analysis_error": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        self.db.ensure_main_session(project_id)
        project = self.db.get_project(project_id)
        assert project is not None
        self._append_message(
            project,
            role="system",
            content=(
                f"项目已导入。扫描到 {len(scan.files)} 个可读文件，"
                f"排除 {len(scan.excluded)} 项，读取失败 {len(scan.read_errors)} 项。"
            ),
            payload={
                "kind": "import",
                "snapshot_digest": scan.digest,
                "files": len(scan.files),
                "excluded": len(scan.excluded),
                "read_errors": len(scan.read_errors),
            },
        )
        self._analyse(project, scan=scan)
        return self.get_project_detail(project_id)

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.splitlines() if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raise WorkspaceError("范围字段必须是字符串数组")

    def _supplemental(self, value: Any) -> list[dict[str, str]]:
        if value is None:
            return []
        if isinstance(value, str):
            return [{"title": "补充资料", "content": value}] if value.strip() else []
        if not isinstance(value, list):
            raise WorkspaceError("补充资料必须是数组")
        docs: list[dict[str, str]] = []
        for index, item in enumerate(value):
            if isinstance(item, str):
                docs.append({"title": f"补充资料 {index + 1}", "content": item})
            elif isinstance(item, dict) and str(item.get("content", "")).strip():
                docs.append(
                    {
                        "title": str(item.get("title") or f"补充资料 {index + 1}"),
                        "content": str(item["content"]),
                    }
                )
        return docs

    def _store_snapshot(self, project_id: str, scan: ScanResult) -> str:
        snapshot_id = _id("snp")
        self.db.create_snapshot(
            {
                "id": snapshot_id,
                "project_id": project_id,
                "digest": scan.digest,
                "root": scan.root,
                "manifest": json.dumps(scan.manifest(), ensure_ascii=False),
                "excluded": json.dumps(scan.excluded, ensure_ascii=False),
                "read_errors": json.dumps(scan.read_errors, ensure_ascii=False),
                "selected_scope": json.dumps(scan.selected_scope, ensure_ascii=False),
                "created_at": utc_now(),
            }
        )
        return snapshot_id

    # ------------------------------------------------------------------
    # workspace entry / serialization
    # ------------------------------------------------------------------
    def get_project_detail(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        if project is None:
            raise WorkspaceError("项目不存在", status_code=404, code="project_not_found")
        session = self.db.ensure_main_session(project_id)
        messages = [
            self.serialize_message(row)
            for row in self.db.list_messages(project_id, session["id"])
        ]
        snapshot = self.db.get_snapshot(project["snapshot_id"])
        understanding_row = self.db.get_understanding(project_id)
        understanding = self.parse_understanding(understanding_row)
        return {
            "project": self.serialize_project(project),
            "session": dict(session),
            "messages": messages,
            "snapshot": self.serialize_snapshot(snapshot),
            "understanding": understanding,
            "readiness": self.readiness(understanding),
        }

    def enter_project(self, project_id: str) -> dict[str, Any]:
        return self.get_project_detail(project_id)

    def ensure_session(self, project_id: str) -> str:
        return str(self.db.ensure_main_session(project_id)["id"])

    def serialize_project(self, row: Any) -> dict[str, Any]:
        data = dict(row)
        snapshot = self.db.get_snapshot(data["snapshot_id"])
        manifest = loads(snapshot["manifest"], []) if snapshot else []
        return {
            "id": data["id"],
            "name": data["name"],
            "root_path": data["root_path"],
            "include_paths": loads(data["include_paths"], []),
            "exclude_patterns": loads(data["exclude_patterns"], []),
            "supplemental": loads(data["supplemental"], []),
            "model_config_id": data["model_config_id"],
            "snapshot_id": data["snapshot_id"],
            "analysis_error": data["analysis_error"],
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "file_count": len(manifest),
            "snapshot_digest": snapshot["digest"] if snapshot else None,
        }

    def serialize_snapshot(self, snapshot: Any) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        data = dict(snapshot)
        manifest = loads(data["manifest"], [])
        return {
            "id": data["id"],
            "digest": data["digest"],
            "root": data["root"],
            "created_at": data["created_at"],
            "files": manifest,
            "excluded": loads(data["excluded"], []),
            "read_errors": loads(data["read_errors"], []),
            "selected_scope": loads(data["selected_scope"], []),
            "file_count": len(manifest),
            "excluded_count": len(loads(data["excluded"], [])),
            "read_error_count": len(loads(data["read_errors"], [])),
        }

    def session_messages(self, project_id: str, session_id: str) -> dict[str, Any]:
        """Return messages only when the session belongs to *project_id*.

        This is the explicit cross-project guard: knowing another project's
        session id is not enough to read its messages.
        """
        session = self.db.get_main_session(project_id)
        if session is None or session["id"] != session_id:
            raise WorkspaceError(
                "会话不属于该项目或不存在", status_code=404, code="session_not_found"
            )
        return {
            "session": dict(session),
            "messages": [
                self.serialize_message(row)
                for row in self.db.list_messages(project_id, session_id)
            ],
        }

    def list_projects(self) -> list[dict[str, Any]]:
        return [self.serialize_project(row) for row in self.db.list_projects()]

    def serialize_message(self, row: Any) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": data["id"],
            "role": data["role"],
            "content": data["content"],
            "payload": loads(data["payload"], None),
            "model": data["model"],
            "sent_scope": loads(data["sent_scope"], None),
            "created_at": data["created_at"],
        }

    def parse_understanding(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        return {
            "summary": data["summary"],
            "agent_or_flow": data["agent_or_flow"],
            "known": loads(data["known"], []),
            "inferred": loads(data["inferred"], []),
            "unknowns": loads(data["unknowns"], []),
            "sources": loads(data["sources"], []),
            "sufficient": bool(data["sufficient"]),
            "user_continued": bool(data["user_continued"]),
            "sufficient_reason": data.get("sufficient_reason", ""),
            "model": data["model"],
            "error": data["error"],
            "updated_at": data["updated_at"],
            "snapshot_id": data["snapshot_id"],
        }

    def readiness(self, understanding: dict[str, Any] | None) -> dict[str, Any]:
        if understanding is None:
            return {
                "generation_allowed": False,
                "generation_implemented": False,
                "unknowns_confirmed": False,
                "reason": "尚未形成项目理解；请先完成分析或补充资料。",
            }
        allowed = bool(understanding.get("sufficient") or understanding.get("user_continued"))
        if allowed:
            reason = (
                "可以进入后续题目设计阶段（本工单不生成题目）。"
                "用户继续或模型判断足够都不等于未知业务规则已确认。"
            )
        elif understanding.get("error"):
            reason = "项目理解失败，请检查模型或资料后重试。"
        else:
            reason = "尚未满足继续条件：请补充资料、纠正理解，或明确表示继续。"
        return {
            "generation_allowed": allowed,
            "generation_implemented": False,
            "unknowns_confirmed": False,
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # analysis / chat
    # ------------------------------------------------------------------
    def _append_message(
        self,
        project: Any,
        *,
        role: str,
        content: str,
        payload: dict[str, Any] | None = None,
        model: str | None = None,
        sent_scope: dict[str, Any] | None = None,
    ) -> None:
        session = self.db.ensure_main_session(project["id"])
        self.db.add_message(
            {
                "id": _id("msg"),
                "session_id": session["id"],
                "project_id": project["id"],
                "role": role,
                "content": content,
                "payload": json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                "model": model,
                "sent_scope": json.dumps(sent_scope, ensure_ascii=False)
                if sent_scope is not None
                else None,
                "created_at": utc_now(),
            }
        )

    def _context_for(self, project: Any, scan: ScanResult) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        return build_model_context(
            scan,
            loads(project["supplemental"], []),
            budget_chars=self.settings.context_budget_chars,
        )

    def _analyse(self, project: Any, *, scan: ScanResult | None = None) -> None:
        try:
            if scan is None:
                scan = self._rescan(project, store_new_snapshot=False)
            sources, context_text, scope = self._context_for(project, scan)
            gateway = self.gateway_for(project["model_config_id"])
            current_row = self.db.get_understanding(project["id"])
            current = self.parse_understanding(current_row)
            result = gateway.analyze(
                project_name=project["name"],
                context_text=context_text,
                sources=sources,
                supplemental=loads(project["supplemental"], []),
                current=current,
            )
            result["sources"] = sources
            result["snapshot_id"] = project["snapshot_id"]
            result["user_continued"] = bool(current and current.get("user_continued"))
            self._store_understanding(project, result, error=None)
            readable = (
                f"{result['summary']}\n\n"
                f"已知：{len(result['known'])} 项；推断：{len(result['inferred'])} 项；"
                f"未知：{len(result['unknowns'])} 项。"
            )
            self._append_message(
                project,
                role="assistant",
                content=readable,
                payload={
                    "kind": "understanding",
                    "understanding": result,
                    "sent_scope": scope,
                },
                model=result.get("model"),
                sent_scope=scope,
            )
            self.db.update_project_snapshot(project["id"], project["snapshot_id"], None)
        except (ModelError, AccessError, OSError) as exc:
            message = str(exc)
            self._store_understanding(
                project,
                {
                    "summary": "项目理解失败。",
                    "agent_or_flow": "",
                    "known": [],
                    "inferred": [],
                    "unknowns": [],
                    "sources": [],
                    "sufficient": False,
                    "sufficient_reason": "",
                    "model": "error",
                    "snapshot_id": project["snapshot_id"],
                    "user_continued": False,
                },
                error=message,
            )
            self.db.update_project_snapshot(project["id"], project["snapshot_id"], message)
            self._append_message(
                project,
                role="system",
                content=f"项目理解失败：{message}",
                payload={"kind": "error", "stage": "analysis", "message": message},
            )

    def _store_understanding(
        self, project: Any, result: dict[str, Any], *, error: str | None
    ) -> None:
        now = utc_now()
        self.db.upsert_understanding(
            {
                "project_id": project["id"],
                "snapshot_id": result.get("snapshot_id") or project["snapshot_id"],
                "summary": result.get("summary", ""),
                "agent_or_flow": result.get("agent_or_flow", ""),
                "known": json.dumps(result.get("known", []), ensure_ascii=False),
                "inferred": json.dumps(result.get("inferred", []), ensure_ascii=False),
                "unknowns": json.dumps(result.get("unknowns", []), ensure_ascii=False),
                "sources": json.dumps(result.get("sources", []), ensure_ascii=False),
                "sufficient": 1 if result.get("sufficient") else 0,
                "sufficient_reason": result.get("sufficient_reason", ""),
                "user_continued": 1 if result.get("user_continued") else 0,
                "model": result.get("model"),
                "error": error,
                "updated_at": now,
            }
        )

    def _rescan(self, project: Any, *, store_new_snapshot: bool = True) -> ScanResult:
        root = Path(project["root_path"])
        try:
            scan = scan_project(
                root,
                loads(project["include_paths"], []),
                loads(project["exclude_patterns"], []),
                max_files=self.settings.max_files,
                max_file_bytes=self.settings.max_file_bytes,
            )
        except AccessError as exc:
            raise WorkspaceError(str(exc), status_code=422, code=exc.code) from exc
        if store_new_snapshot:
            snapshot_id = self._store_snapshot(project["id"], scan)
            self.db.update_project_snapshot(project["id"], snapshot_id, None)
            project = self.db.get_project(project["id"])
            assert project is not None
        return scan

    def post_message(self, project_id: str, content: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        if project is None:
            raise WorkspaceError("项目不存在", status_code=404, code="project_not_found")
        text = (content or "").strip()
        if not text:
            raise WorkspaceError("消息不能为空")
        if len(text) > 8_000:
            raise WorkspaceError("消息过长")
        self._append_message(project, role="user", content=text, payload={"kind": "chat"})
        try:
            current_snapshot = self.db.get_snapshot(project["snapshot_id"])
            scan = self._rescan(project, store_new_snapshot=False)
            if current_snapshot is None or scan.digest != current_snapshot["digest"]:
                # Files changed while the session was open: record a new
                # snapshot so the sources shown afterwards match what was sent.
                snapshot_id = self._store_snapshot(project["id"], scan)
                self.db.update_project_snapshot(project["id"], snapshot_id, None)
                project = self.db.get_project(project["id"])
                assert project is not None
            sources, context_text, scope = self._context_for(project, scan)
            gateway = self.gateway_for(project["model_config_id"])
            current_row = self.db.get_understanding(project_id)
            current = self.parse_understanding(current_row)
            if current is None:
                raise ModelError("项目尚未完成初步分析，无法继续会话")
            history = [
                {"role": row["role"], "content": row["content"]}
                for row in self.db.list_messages(project_id, self.db.ensure_main_session(project_id)["id"])
                if row["role"] in ("user", "assistant")
            ][-8:]
            result = gateway.discuss(
                project_name=project["name"],
                context_text=context_text,
                current={
                    key: current[key]
                    for key in (
                        "summary",
                        "agent_or_flow",
                        "known",
                        "inferred",
                        "unknowns",
                        "sufficient",
                        "sufficient_reason",
                    )
                },
                history=history,
                user_message=text,
            )
            understanding = result["understanding"]
            understanding["model"] = result.get("model")
            understanding["sources"] = sources
            understanding["snapshot_id"] = project["snapshot_id"]
            understanding["user_continued"] = bool(
                current.get("user_continued") or result.get("continue_requested")
            )
            self._store_understanding(project, understanding, error=None)
            self._append_message(
                project,
                role="assistant",
                content=result["reply"],
                payload={
                    "kind": "chat",
                    "reply": result["reply"],
                    "understanding": understanding,
                    "continue_requested": result.get("continue_requested", False),
                    "direction_update": result.get("direction_update", ""),
                    "sent_scope": scope,
                },
                model=result.get("model"),
                sent_scope=scope,
            )
        except (ModelError, AccessError, OSError) as exc:
            message = str(exc)
            self._append_message(
                project,
                role="system",
                content=f"模型调用失败：{message}",
                payload={"kind": "error", "stage": "chat", "message": message},
            )
            raise WorkspaceError(
                message, status_code=502, code="model_error"
            ) from exc
        return self.get_project_detail(project_id)

    def request_continue(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        if project is None:
            raise WorkspaceError("项目不存在", status_code=404, code="project_not_found")
        current_row = self.db.get_understanding(project_id)
        current = self.parse_understanding(current_row)
        if current is None:
            raise WorkspaceError("尚未形成项目理解，不能进入下一步", status_code=409)
        result = dict(current)
        result["user_continued"] = True
        self._store_understanding(project, result, error=current.get("error"))
        self._append_message(
            project,
            role="system",
            content="用户表示可以继续进入后续题目设计；未知项仍保持未确认。",
            payload={
                "kind": "continue",
                "unknowns_confirmed": False,
                "generation_implemented": False,
            },
        )
        return self.get_project_detail(project_id)

    def rescan(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        if project is None:
            raise WorkspaceError("项目不存在", status_code=404, code="project_not_found")
        try:
            scan = self._rescan(project)
        except (AccessError, OSError) as exc:
            message = str(exc)
            self._append_message(
                project,
                role="system",
                content=f"资料重新扫描失败：{message}",
                payload={"kind": "error", "stage": "rescan", "message": message},
            )
            raise WorkspaceError(message, status_code=422, code="scan_error") from exc
        self._append_message(
            project,
            role="system",
            content=(
                f"资料范围已重新扫描：{len(scan.files)} 个可读文件，"
                f"排除 {len(scan.excluded)} 项，读取失败 {len(scan.read_errors)} 项。"
            ),
            payload={
                "kind": "rescan",
                "snapshot_digest": scan.digest,
                "files": len(scan.files),
                "excluded": len(scan.excluded),
                "read_errors": len(scan.read_errors),
            },
        )
        return self.get_project_detail(project_id)

    def reanalyse(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        if project is None:
            raise WorkspaceError("项目不存在", status_code=404, code="project_not_found")
        scan = self._rescan(project)
        project = self.db.get_project(project_id)
        assert project is not None
        self._analyse(project, scan=scan)
        return self.get_project_detail(project_id)

    def update_sources(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        if project is None:
            raise WorkspaceError("项目不存在", status_code=404, code="project_not_found")
        supplemental = self._supplemental(payload.get("supplemental"))
        include_paths = self._string_list(payload.get("include_paths"))
        exclude_patterns = self._string_list(payload.get("exclude_patterns"))
        try:
            scan = scan_project(
                Path(project["root_path"]),
                include_paths,
                exclude_patterns,
                max_files=self.settings.max_files,
                max_file_bytes=self.settings.max_file_bytes,
            )
        except AccessError as exc:
            raise WorkspaceError(str(exc), status_code=422, code=exc.code) from exc
        snapshot_id = self._store_snapshot(project_id, scan)
        with self.db.connection() as connection:
            connection.execute(
                """UPDATE projects SET include_paths = ?, exclude_patterns = ?,
                   supplemental = ?, snapshot_id = ?, updated_at = ? WHERE id = ?""",
                (
                    json.dumps(include_paths, ensure_ascii=False),
                    json.dumps(exclude_patterns, ensure_ascii=False),
                    json.dumps(supplemental, ensure_ascii=False),
                    snapshot_id,
                    utc_now(),
                    project_id,
                ),
            )
        project = self.db.get_project(project_id)
        assert project is not None
        self._analyse(project, scan=scan)
        return self.get_project_detail(project_id)

    def delete_model_config(self, model_config_id: str) -> None:
        with self.db.connection() as connection:
            used = connection.execute(
                "SELECT COUNT(*) AS n FROM projects WHERE model_config_id = ?",
                (model_config_id,),
            ).fetchone()
            if used and used["n"]:
                raise WorkspaceError("该模型配置仍被项目使用，不能删除", status_code=409)
            connection.execute("DELETE FROM model_configs WHERE id = ?", (model_config_id,))
