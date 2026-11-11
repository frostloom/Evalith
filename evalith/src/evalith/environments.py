"""Explicitly confirmed, Evalith-owned environment preparation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .db import utc_now
from .evaluation_store import EvaluationStore, new_id
from .execution_process import sandbox_available
from .executor_configs import ExecutorConfigs
from .service import WorkspaceError, WorkspaceService
from .source_copy import copy_project


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class EnvironmentManager:
    def __init__(self, workspace: WorkspaceService, store: EvaluationStore):
        self.workspace, self.store = workspace, store
        self.root = workspace.settings.data_dir / "environments"
        self.executors = ExecutorConfigs(workspace.db, workspace.cipher)

    def directory(self, environment_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,80}", environment_id):
            raise WorkspaceError("无效环境编号", status_code=422)
        result = (self.root / environment_id).resolve()
        if not result.is_relative_to(self.root.resolve()):
            raise WorkspaceError("环境路径越界", status_code=422)
        return result

    @staticmethod
    def public(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if not key.startswith("_")}

    def plan(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) - {"adapter", "executor_config_id", "isolated_data_confirmed"}:
            raise WorkspaceError("环境方案包含未知字段", status_code=422)
        detail = self.workspace.get_project_detail(project_id)
        adapter = payload.get("adapter")
        definition = None
        if payload.get("executor_config_id"):
            definition = next(
                (
                    item
                    for item in self.executors.list()
                    if item["id"] == payload["executor_config_id"]
                ),
                None,
            )
            if definition is None:
                raise WorkspaceError("执行器配置不存在", status_code=404)
            adapter = definition["backend"]
        if adapter not in {"aigateway_go", "local_command", "http_api"}:
            raise WorkspaceError(
                "请选择可用执行器；Harbor 尚未接入实际运行协议",
                status_code=422,
                code="unsupported_adapter",
            )
        if adapter in {"local_command", "http_api"} and definition is None:
            raise WorkspaceError("需要选择执行器配置", status_code=422)
        if adapter in {"aigateway_go", "local_command"} and not sandbox_available():
            raise WorkspaceError(
                "本机缺少受支持的命令隔离器，不能准备命令执行环境",
                status_code=422,
                code="sandbox_unavailable",
            )
        if adapter == "http_api":
            parsed = urlsplit(definition["base_url"])
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise WorkspaceError(
                    "当前 HTTP 执行器仅支持明确确认的本机隔离服务", status_code=422
                )
            if payload.get("isolated_data_confirmed") is not True:
                raise WorkspaceError(
                    "请先确认 HTTP 目标使用独立测试数据", status_code=422
                )
        environment_id = new_id("env")
        directory = self.directory(environment_id)
        plan = {
            "adapter": adapter,
            "source_directory": detail["project"]["root_path"],
            "source_access": "read_only_copy",
            "write_directory": str(directory),
            "copy_scope": "Go module and runtime source only; no old campaigns, credentials or existing databases"
            if adapter == "aigateway_go"
            else "Non-sensitive ordinary source files; no symlinks or dependency/runtime directories",
            "services": [
                "Each case: actual ai-gateway Handler, private SQLite audit/session DB, in-memory Redis, synthetic loopback billing"
            ]
            if adapter == "aigateway_go"
            else ["Explicitly configured local executable"]
            if adapter == "local_command"
            else [
                "Existing isolated loopback HTTP target (owned by user; not started or stopped by Evalith)"
            ],
            "credential_sources": [
                "Existing ChatGPT login, used only by Evalith model transport; never copied to target"
            ]
            if adapter == "aigateway_go"
            else [],
            "network": [
                "Build: public Go modules via " + self.workspace.settings.go_proxy,
                "Execution: loopback-only model bridge and synthetic services",
            ]
            if adapter == "aigateway_go"
            else ["No network inside command sandbox"]
            if adapter == "local_command"
            else [definition["base_url"]],
            "executor": definition,
            "estimated_cost_usd": None,
            "cost_note": "真实模型使用账号额度，金额费用未知；运行前另设调用次数上限。",
            "cleanup": "Per-case child processes and local services are reaped; evidence files retained in Evalith",
            "limitations": [
                "Synthetic billing is an isolated substitute, not the production financial service. The imported Agent handler is real."
            ]
            if adapter == "aigateway_go"
            else [],
        }
        digest = fingerprint(
            {"plan": plan, "source_digest": detail["snapshot"]["digest"]}
        )
        return self.store.create(
            project_id,
            "environment",
            {
                "adapter": adapter,
                "source_snapshot_id": detail["project"]["snapshot_id"],
                "source_digest": detail["snapshot"]["digest"],
                "plan": plan,
                "plan_digest": digest,
                "requires_confirmation": True,
                "events": [],
                "runtime": None,
                "error": None,
                "cleanup_status": "not_started",
            },
            status="planned",
            record_id=environment_id,
        )

    def confirm(
        self,
        project_id: str,
        environment_id: str,
        digest: str,
        *,
        background: bool = True,
    ) -> dict[str, Any]:
        with self.workspace._project_lock(project_id):
            current = self.store.get(project_id, "environment", environment_id)
            if current["status"] != "planned" or digest != current["plan_digest"]:
                raise WorkspaceError(
                    "环境方案已变化或已确认，请重新查看方案",
                    status_code=409,
                    code="plan_changed",
                )
            detail = self.workspace.get_project_detail(project_id)
            if detail["snapshot"]["digest"] != current["source_digest"]:
                raise WorkspaceError(
                    "源资料已变化，请创建新环境方案",
                    status_code=409,
                    code="source_changed",
                )
            self.store.update(
                project_id,
                "environment",
                environment_id,
                status="preparing",
                requires_confirmation=False,
                confirmed_at=utc_now(),
            )
        if background:
            threading.Thread(
                target=self._prepare,
                args=(project_id, environment_id),
                name="evalith-prepare-" + environment_id,
                daemon=True,
            ).start()
            return self.public(
                self.store.get(project_id, "environment", environment_id)
            )
        self._prepare(project_id, environment_id)
        return self.public(self.store.get(project_id, "environment", environment_id))

    def _event(self, project_id: str, environment_id: str, message: str):
        self.store.mutate(
            project_id,
            "environment",
            environment_id,
            lambda item: {
                **item,
                "events": [*item["events"], {"at": utc_now(), "message": message}],
            },
        )

    def _prepare(self, project_id: str, environment_id: str):
        directory = self.directory(environment_id)
        try:
            current = self.store.get(project_id, "environment", environment_id)
            directory.mkdir(parents=True, exist_ok=False, mode=0o700)
            project = self.workspace.db.get_project(project_id)
            if current["adapter"] == "http_api":
                runtime = {
                    "base_url": current["plan"]["executor"]["base_url"],
                    "timeout_seconds": current["plan"]["executor"]["timeout_seconds"],
                }
            else:
                self._event(
                    project_id, environment_id, "正在建立经过文件指纹校验的只读源副本"
                )
                manifest = copy_project(
                    project,
                    directory / "source",
                    go_adapter=current["adapter"] == "aigateway_go",
                )
                self._event(
                    project_id,
                    environment_id,
                    f"已复制 {len(manifest['files'])} 个源文件；原目录未写入",
                )
                if current["adapter"] == "aigateway_go":
                    runtime = self._build_gateway(project_id, environment_id, directory)
                else:
                    command = []
                    original = Path(project["root_path"])
                    for index, arg in enumerate(current["plan"]["executor"]["command"]):
                        if Path(arg).is_absolute() and Path(arg).is_relative_to(
                            original
                        ):
                            arg = "{source}/" + str(Path(arg).relative_to(original))
                        elif index > 0 and Path(arg).is_absolute():
                            raise WorkspaceError(
                                "命令参数的绝对路径必须在项目内；请使用相对路径或 {workdir}",
                                status_code=422,
                            )
                        command.append(arg)
                    working = current["plan"]["executor"].get("working_directory")
                    if working and not Path(working).is_relative_to(original):
                        raise WorkspaceError(
                            "工作目录必须位于导入项目内", status_code=422
                        )
                    runtime = {
                        "command": command,
                        "timeout_seconds": current["plan"]["executor"][
                            "timeout_seconds"
                        ],
                        "source_copy": str(directory / "source"),
                        "working_relative": str(Path(working).relative_to(original))
                        if working
                        else ".",
                    }
                runtime["source_manifest_digest"] = manifest["digest"]
            self.store.update(
                project_id,
                "environment",
                environment_id,
                status="ready",
                runtime=runtime,
                cleanup_status="ready",
            )
            self._event(
                project_id,
                environment_id,
                "运行依赖已准备；每题使用独立目录和数据，尚未执行评测",
            )
        except Exception as exc:  # noqa: BLE001 - persist background failures for the UI
            self.store.update(
                project_id,
                "environment",
                environment_id,
                status="failed",
                error=self.workspace._scrub_saved_secrets(str(exc))[:1600],
                cleanup_status="no_services_started",
            )

    def _build_gateway(
        self, project_id: str, environment_id: str, directory: Path
    ) -> dict[str, Any]:
        source = directory / "source"
        module = source / "go.mod"
        if (
            not module.is_file()
            or "module github.com/frostloom/ai-gateway" not in module.read_text()
        ):
            raise WorkspaceError("该适配器需要 ai-gateway Go 模块", status_code=422)
        template = (
            Path(__file__).resolve().parents[3]
            / "examples"
            / "aigateway"
            / "adapter.go"
        )
        target = source / "cmd" / "evalith-adapter" / "main.go"
        target.parent.mkdir(parents=True)
        shutil.copyfile(template, target)
        with module.open("a") as handle:
            handle.write("\nrequire gorm.io/driver/sqlite v1.6.0\n")
        cache = self.workspace.settings.data_dir / "cache" / "go"
        for sub in ("build", "mod", "tmp", "clang"):
            (cache / sub).mkdir(parents=True, exist_ok=True)
        build_env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "LC_CTYPE"}
        }
        build_env.update(
            {
                "GOCACHE": str(cache / "build"),
                "GOMODCACHE": str(cache / "mod"),
                "GOPATH": str(cache / "path"),
                "GOTMPDIR": str(cache / "tmp"),
                "TMPDIR": str(cache / "tmp"),
                "CLANG_MODULE_CACHE_PATH": str(cache / "clang"),
                "GOTOOLCHAIN": "local",
                "CGO_ENABLED": "1",
                "GOTELEMETRY": "off",
                "GOENV": "off",
                "GOPROXY": self.workspace.settings.go_proxy,
            }
        )
        binary = directory / "aigateway-adapter"
        if self.workspace.settings.go_sdkroot:
            build_env["SDKROOT"] = self.workspace.settings.go_sdkroot
        self._event(
            project_id,
            environment_id,
            "正在编译原项目 Handler 与 Evalith 隔离适配器；首次需要下载 Go 依赖",
        )
        with (directory / "build.log").open("wb") as log:
            process = subprocess.Popen(
                ["go", "build", "-mod=mod", "-o", str(binary), "./cmd/evalith-adapter"],
                cwd=source,
                env=build_env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
                raise WorkspaceError(
                    "Go 环境准备超时；编译进程已清理", status_code=422
                ) from None
        if code != 0:
            detail = (directory / "build.log").read_text(errors="replace")[-1200:]
            raise WorkspaceError("Go 适配器编译失败：" + detail, status_code=422)
        binary.chmod(0o700)
        return {
            "binary": str(binary),
            "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "timeout_seconds": 600,
            "handler": "github.com/frostloom/ai-gateway/internal/agent.Handler",
            "transport": "Codex JSON tool-call adapter",
            "storage": "isolated SQLite + miniredis",
            "fixture": "synthetic billing only",
        }
