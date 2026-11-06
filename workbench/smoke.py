#!/usr/bin/env python3
"""API-level smoke test for the EE-free workbench.

Exercises the paths this phase must keep working: authentication, project
create/list/read, model configuration and connection test, and the Architect
session REST path. Model responses come from a deterministic local stub, not a
real model. The full Celery/Architect tool loop remains a recorded stage-0
limit unless a worker is started separately.

Writes ``docs/stage1/evidence/workbench-smoke-<timestamp>.json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TREE = ROOT / "workbench" / ".workbench" / "ee-free"
BACKEND_URL = "http://127.0.0.1:8080"
FRONTEND_URL = "http://127.0.0.1:3000"
EVIDENCE = ROOT / "docs" / "stage1" / "evidence"
TOKEN: str | None = None


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__(f"{method} {path} -> HTTP {status}: {body[:800]}")
        self.status = status
        self.body = body


def api(method: str, path: str, payload: Any = None, project_id: str | None = None) -> Any:
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if project_id:
        headers["X-Project-Id"] = project_id
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BACKEND_URL + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raise ApiError(method, path, error.code, error.read().decode("utf-8", "replace")) from error


class StubModelHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("", "/health"):
            self._json({"ok": True})
        elif self.path.endswith("/models"):
            self._json({"data": [{"id": "smoke-model", "object": "model"}]})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self._json(
            {
                "id": "chatcmpl-smoke",
                "object": "chat.completion",
                "model": "smoke-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args: Any) -> None:
        return


def wait_for(url: str, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return
        except Exception:  # noqa: BLE001 - retry loop
            time.sleep(1)
    raise RuntimeError(f"{url} did not become ready within {timeout}s")


def login() -> str:
    payload = api("POST", "/auth/local-login", {})
    code = payload.get("auth_code")
    if not code:
        raise RuntimeError(f"local-login returned no auth_code: {payload}")
    tokens = api("POST", "/auth/exchange-code", {"code": code})
    token = tokens.get("access_token") or tokens.get("session_token")
    if not token:
        raise RuntimeError(f"exchange-code returned no token: {tokens}")
    return str(token)


def find_type(items: list[dict[str, Any]], type_name: str, type_value: str) -> dict[str, Any]:
    for item in items:
        if item.get("type_name") == type_name and item.get("type_value") == type_value:
            return item
    raise RuntimeError(f"type lookup missing: {type_name}/{type_value}")


def check_artifact() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    checks["ee_directory_absent"] = not (TREE / "ee").exists()
    checks["frontend_ee_bootstrap_noop"] = "bootstrapEE" not in (
        TREE / "apps/frontend/src/ee_bootstrap.ts"
    ).read_text()
    checks["backend_pyproject_no_ee"] = "rhesis-backend-ee" not in (
        TREE / "apps/backend/pyproject.toml"
    ).read_text()
    checks["frontend_package_no_ee"] = "@rhesis/ee-frontend" not in (
        TREE / "apps/frontend/package.json"
    ).read_text()
    checks["brand_logo_dir_absent"] = not (TREE / "apps/frontend/public/logos").exists()
    checks["unlicensed_font_families_absent"] = not any(
        (TREE / "apps/frontend/public/fonts" / name).exists()
        for name in ("sora", "sometype-mono", "geist")
    )
    fonts_css = TREE / "apps/frontend/src/styles/fonts.css"
    checks["fonts_css_only_licensed_family"] = fonts_css.exists() and not any(
        f"font-family: '{family}'" in fonts_css.read_text()
        for family in ("Sora", "Sometype Mono", "Geist", "Geist Mono")
    )
    python = TREE / "apps/backend/.venv/bin/python"
    if python.exists():
        result = subprocess.run(
            [str(python), "-c", "import rhesis.backend.ee"],
            cwd=TREE / "apps/backend",
            text=True,
            capture_output=True,
        )
        checks["ee_package_not_importable"] = result.returncode != 0
        listing = subprocess.run(
            ["uv", "pip", "list"],
            cwd=TREE / "apps/backend",
            text=True,
            capture_output=True,
        )
        checks["ee_package_not_installed"] = (
            "rhesis-backend-ee" not in listing.stdout.lower()
        )
    info = TREE / "BUILD_INFO.json"
    checks["build_info_pinned"] = (
        info.exists()
        and json.loads(info.read_text())["upstream_commit"]
        == "ce24bb1993fc545bb0ccb0d8b3951683ac14fff1"
    )
    return checks


def main() -> int:
    global TOKEN
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    stub = ThreadingHTTPServer(("127.0.0.1", 18081), StubModelHandler)
    threading.Thread(target=stub.serve_forever, daemon=True).start()

    checks: dict[str, Any] = {}
    errors: list[str] = []
    ids: dict[str, str] = {}
    try:
        wait_for(BACKEND_URL + "/health")
        checks["backend_health"] = api("GET", "/health")

        TOKEN = login()
        checks["auth_quick_start"] = True

        features = api("GET", "/features")
        checks["features"] = features
        checks["community_edition"] = (
            (features.get("license") or {}).get("edition") == "community"
        )
        checks["rhesis_platform_key_disabled"] = not features.get("rhesis_key_enabled", True)

        project = api(
            "POST",
            "/projects/",
            {"name": f"EE-free smoke {int(time.time())}", "description": "synthetic"},
        )
        ids["project_id"] = project["id"]
        projects = api("GET", "/projects/")
        checks["project_created"] = project["id"] in {item["id"] for item in projects}
        checks["project_read"] = api("GET", f"/projects/{project['id']}")["id"] == project["id"]

        lookups = api("GET", "/type_lookups?limit=100")
        provider = find_type(lookups, "ProviderType", "litellm_proxy")
        model = api(
            "POST",
            "/models/",
            {
                "name": f"smoke-model-{int(time.time())}",
                "description": "deterministic smoke model",
                "model_name": "smoke-model",
                "model_type": "language",
                "endpoint": "http://127.0.0.1:18081",
                "key": "smoke-fake-key",
                "provider_type_id": provider["id"],
            },
        )
        ids["model_id"] = model["id"]
        connection = api(
            "POST",
            "/models/test-connection",
            {
                "provider": "litellm_proxy",
                "model_name": "smoke-model",
                "api_key": "smoke-fake-key",
                "endpoint": "http://127.0.0.1:18081",
                "model_type": "language",
            },
        )
        checks["model_connection"] = connection
        checks["model_connection_ok"] = bool(connection.get("success"))

        session = api(
            "POST",
            "/architect/sessions/",
            {"title": "Smoke discovery session", "mode": "discovery"},
            project_id=project["id"],
        )
        ids["architect_session_id"] = session["id"]
        detail = api(
            "GET",
            f"/architect/sessions/{session['id']}",
            project_id=project["id"],
        )
        checks["architect_session_detail"] = detail.get("id") == session["id"]
        checks["architect_session_messages_visible"] = "messages" in detail

        wait_for(FRONTEND_URL + "/api/health")
        with urllib.request.urlopen(FRONTEND_URL + "/", timeout=30) as response:
            html = response.read().decode("utf-8", "replace")
        checks["frontend_http_status"] = response.status
        checks["frontend_title"] = "Evalith" in html
        checks["frontend_uses_evalith_mark"] = "evalith-mark" in html or "Evalith" in html

        checks["artifact"] = check_artifact()
        checks["all_artifact_checks"] = all(checks["artifact"].values())
        checks["passed"] = all(
            [
                checks["community_edition"],
                checks["rhesis_platform_key_disabled"],
                checks["project_created"],
                checks["project_read"],
                checks["model_connection_ok"],
                checks["architect_session_detail"],
                checks["architect_session_messages_visible"],
                checks["frontend_http_status"] == 200,
                checks["all_artifact_checks"],
            ]
        )
    except Exception as error:  # noqa: BLE001 - record and fail
        errors.append(str(error))
        checks["passed"] = False
    finally:
        stub.shutdown()
        stub.server_close()

    report = {
        "generated_at": started.isoformat(),
        "backend_url": BACKEND_URL,
        "frontend_url": FRONTEND_URL,
        "source_build": "uv sync from workbench/.workbench/ee-free (no published image)",
        "upstream_commit": "ce24bb1993fc545bb0ccb0d8b3951683ac14fff1",
        "model": "deterministic local OpenAI-compatible stub; not a real model",
        "checks": checks,
        "ids": ids,
        "errors": errors,
        "limitations": [
            "No real model or real business data is used.",
            "The Architect Celery/model tool loop is not exercised unless a worker is started.",
            "Frontend verification is HTTP/HTML level in this script; screenshots are in docs/stage1/evidence.",
        ],
    }
    output = EVIDENCE / f"workbench-smoke-{int(started.timestamp())}.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": checks.get("passed"), "evidence": str(output)}, ensure_ascii=False))
    return 0 if checks.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
