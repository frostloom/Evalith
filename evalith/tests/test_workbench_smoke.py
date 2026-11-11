from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_smoke() -> Any:
    path = Path(__file__).resolve().parents[2] / "workbench" / "smoke.py"
    spec = importlib.util.spec_from_file_location("workbench_smoke", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _passing_checks() -> dict[str, bool | int]:
    return {
        "community_edition": True,
        "rhesis_platform_key_disabled": True,
        "project_created": True,
        "project_read": True,
        "model_connection_ok": True,
        "architect_session_detail": True,
        "architect_session_messages_visible": True,
        "architect_session_user_message": True,
        "architect_session_worker_reply": True,
        "frontend_http_status": 200,
        "all_artifact_checks": True,
    }


def test_architect_worker_reply_is_part_of_smoke_success() -> None:
    smoke = _load_smoke()
    checks = _passing_checks()
    assert smoke.checks_succeeded(checks) is True
    checks["architect_session_worker_reply"] = False
    assert smoke.checks_succeeded(checks) is False
