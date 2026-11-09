"""FastAPI application for the Evalith phase-1 project workspace."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import Settings, settings_from_env
from .db import Database
from .model_gateway import ModelError
from .security import CredentialCipher, install_log_redaction
from .service import WorkspaceError, WorkspaceService

logger = logging.getLogger("evalith.api")


_TRUSTED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8090",
    "http://localhost:8090",
)


class LocalHostMiddleware(BaseHTTPMiddleware):
    """Reject non-loopback Host/Origin values before any project API runs.

    CORS does not protect same-origin DNS-rebinding requests: a page served
    from an attacker-controlled hostname can resolve it to 127.0.0.1 and send
    a matching Host/Origin.  This unauthenticated local service therefore
    accepts only its configured loopback hostnames.
    """

    def __init__(
        self,
        app,
        allowed_hosts: tuple[str, ...],
        allow_remote: bool = False,
        allowed_origins: tuple[str, ...] = _TRUSTED_ORIGINS,
    ) -> None:
        super().__init__(app)
        self.allowed_hosts = {host.lower() for host in allowed_hosts}
        self.allow_remote = allow_remote
        self.allowed_origins = {
            self._normalize_origin(origin) for origin in allowed_origins
        }

    @staticmethod
    def _normalize_origin(value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            return ""
        if not parsed.hostname:
            return ""
        if port is None:
            port = 443 if parsed.scheme.lower() == "https" else 80
        return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}:{port}"

    @staticmethod
    def _hostname(value: str | None) -> str:
        if not value:
            return ""
        try:
            parsed = urlsplit(value if "://" in value else f"//{value}")
            return (parsed.hostname or "").lower()
        except ValueError:
            return ""

    async def dispatch(self, request, call_next):
        if self.allow_remote:
            return await call_next(request)
        client = getattr(request, "client", None)
        client_host = getattr(client, "host", None)
        if client_host not in {
            None,
            "testclient",
            "testserver",
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "remote access is disabled",
                    "code": "remote_access_disabled",
                },
            )
        host = self._hostname(request.headers.get("host"))
        if host not in self.allowed_hosts:
            return JSONResponse(
                status_code=403,
                content={"error": "untrusted request host", "code": "untrusted_host"},
            )
        origin = request.headers.get("origin")
        if origin:
            normalized_origin = self._normalize_origin(origin)
            host_header = request.headers.get("host") or ""
            same_origin = self._normalize_origin(
                f"{request.url.scheme}://{host_header}"
            )
            if normalized_origin not in self.allowed_origins and not (
                normalized_origin == same_origin and host in self.allowed_hosts
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "untrusted request origin",
                        "code": "untrusted_origin",
                    },
                )
        return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or settings_from_env()
    settings.ensure_dirs()
    install_log_redaction()
    database = Database(settings.database_path)  # type: ignore[arg-type]
    cipher = CredentialCipher(settings.secret_key, settings.data_dir)
    service = WorkspaceService(database, settings, cipher)

    app = FastAPI(title="Evalith", version="0.1.0")

    async def model_error_handler(_request: Request, exc: ModelError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"error": str(exc), "code": "model_error"},
        )

    app.add_exception_handler(ModelError, model_error_handler)
    app.state.settings = settings
    app.state.db = database
    app.state.service = service

    app.add_middleware(
        LocalHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
        allow_remote=settings.allow_remote,
        allowed_origins=_TRUSTED_ORIGINS,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_TRUSTED_ORIGINS),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(WorkspaceError)
    async def workspace_error_handler(_: Request, exc: WorkspaceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": str(exc), "code": exc.code},
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "evalith",
            "version": "0.1.0",
            "access_mode": settings.access_mode,
        }

    # ------------------------------------------------------------------
    # model configurations
    # ------------------------------------------------------------------
    @app.get("/api/model-configs")
    def list_model_configs() -> dict[str, Any]:
        return {
            "items": [service.serialize_model_config(row) for row in database.list_model_configs()]
        }

    @app.post("/api/model-configs", status_code=201)
    def create_model_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return service.create_model_config(payload)

    @app.post("/api/model-configs/{model_config_id}/test")
    def test_model_config(model_config_id: str) -> dict[str, Any]:
        if database.get_model_config(model_config_id) is None:
            raise WorkspaceError("模型配置不存在", status_code=404)
        return service.test_model_config(model_config_id)

    @app.delete("/api/model-configs/{model_config_id}", status_code=204)
    def delete_model_config(model_config_id: str) -> None:
        service.delete_model_config(model_config_id)

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    @app.get("/api/projects")
    def list_projects() -> dict[str, Any]:
        return {"items": service.list_projects()}

    @app.post("/api/projects", status_code=201)
    def create_project(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return service.create_project(payload)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return service.get_project_detail(project_id)

    @app.post("/api/projects/{project_id}/enter")
    def enter_project(project_id: str) -> dict[str, Any]:
        return service.enter_project(project_id)

    @app.get("/api/projects/{project_id}/sessions/{session_id}/messages")
    def session_messages(project_id: str, session_id: str) -> dict[str, Any]:
        return service.session_messages(project_id, session_id)

    @app.post("/api/projects/{project_id}/messages")
    def post_message(project_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return service.post_message(project_id, str(payload.get("content", "")))

    @app.post("/api/projects/{project_id}/continue")
    def request_continue(project_id: str) -> dict[str, Any]:
        return service.request_continue(project_id)

    @app.post("/api/projects/{project_id}/rescan")
    def rescan(project_id: str) -> dict[str, Any]:
        return service.rescan(project_id)

    @app.put("/api/projects/{project_id}/model")
    def assign_project_model(
        project_id: str, payload: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        model_config_id = payload.get("model_config_id") or None
        return service.assign_model(project_id, model_config_id)

    @app.post("/api/projects/{project_id}/reanalyse")
    def reanalyse(project_id: str) -> dict[str, Any]:
        return service.reanalyse(project_id)

    @app.put("/api/projects/{project_id}/sources")
    def update_sources(project_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return service.update_sources(project_id, payload)

    @app.post("/api/projects/{project_id}/generate")
    def generate(project_id: str) -> dict[str, Any]:
        """Phase-1 gate: no question generation is implemented yet.

        Kept as an endpoint so the boundary is testable: the service refuses
        with 409 until the understanding gate opens, and reports that
        generation itself belongs to a later phase even when it opens.
        """
        detail = service.get_project_detail(project_id)
        readiness = detail["readiness"]
        if not readiness["generation_allowed"]:
            return JSONResponse(
                status_code=409,
                content={
                    "error": readiness["reason"],
                    "code": "generation_not_ready",
                    "readiness": readiness,
                },
            )
        return JSONResponse(
            status_code=501,
            content={
                "error": "题目生成属于阶段 2；本工单只验证推进状态与边界。",
                "code": "generation_not_implemented",
                "readiness": readiness,
            },
        )

    # ------------------------------------------------------------------
    # static UI
    # ------------------------------------------------------------------
    static_dir: Path | None = settings.static_dir
    if static_dir and (static_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", response_model=None)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                return JSONResponse(status_code=404, content={"error": "not found"})
            candidate = (static_dir / path).resolve()
            if not candidate.is_relative_to(static_dir.resolve()):
                return JSONResponse(status_code=404, content={"error": "not found"})
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
