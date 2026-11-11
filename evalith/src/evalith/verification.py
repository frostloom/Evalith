"""Declarative checks with explicit missing-evidence semantics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .service import WorkspaceError

MISSING = object()


def resolve_path(value: Any, path: str) -> Any:
    if not path:
        return value
    for part in path.removeprefix("$.").split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return MISSING
    return value


def evidence_path(root: Path, path: str) -> Path:
    relative = Path(path)
    if not path or relative.is_absolute() or ".." in relative.parts:
        raise WorkspaceError("证据路径必须在单题目录内", status_code=422)
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()) or any(
        parent.is_symlink()
        for parent in [target, *target.parents]
        if parent != root.parent
    ):
        raise WorkspaceError("证据不能通过符号链接访问目录之外", status_code=422)
    return target


def evaluate_checks(
    checks: list[dict[str, Any]], observation: dict[str, Any], work: Path
) -> dict[str, Any]:
    results = []
    document = observation.get("json", MISSING)
    default = observation.get("text", MISSING)
    if default is MISSING and isinstance(document, dict):
        default = document.get("reply", MISSING)
    if default is MISSING:
        default = observation.get("stdout", MISSING)
    for check in checks:
        kind = check["type"]
        path = check.get("path", "")
        expected = check.get("expected")
        item = {**check, "status": "pending", "actual": None, "reason": ""}
        if kind == "judge":
            item["status"] = "needs_judge"
            results.append(item)
            continue
        actual = MISSING
        if kind in {"file_exists", "file_contains"}:
            target = evidence_path(work, path)
            if kind == "file_exists":
                actual = target.is_file()
                expected = True if expected is None else expected
            elif target.is_file() and target.stat().st_size <= 1_000_000:
                actual = target.read_text(errors="replace")
        elif kind == "json_equals":
            actual = resolve_path(document, path)
        elif kind == "exit_code":
            actual = observation.get("exit_code", MISSING)
        elif kind == "status_code":
            actual = observation.get("status_code", MISSING)
            if (
                actual is MISSING
                and isinstance(document, dict)
                and document.get("turns")
            ):
                actual = document["turns"][-1].get("http_status", MISSING)
        else:
            actual = resolve_path(document, path) if path else default
        if actual is MISSING:
            item.update(
                status="missing_evidence", reason="所需输出或文件不存在，不能判为通过"
            )
        else:
            item["actual"] = actual[:20000] if isinstance(actual, str) else actual
            if kind in {"contains", "file_contains"}:
                passed = isinstance(actual, str) and expected in actual
            elif kind == "not_contains":
                passed = isinstance(actual, str) and expected not in actual
            else:
                passed = json.dumps(
                    actual, sort_keys=True, ensure_ascii=False
                ) == json.dumps(expected, sort_keys=True, ensure_ascii=False)
            item.update(
                status="passed" if passed else "failed",
                reason="检查通过" if passed else "实际输出不满足评分规则",
            )
        results.append(item)
    if not results:
        return {
            "status": "validation_error",
            "score": None,
            "checks": [],
            "reason": "没有验证规则",
        }
    if any(item["status"] == "missing_evidence" for item in results):
        status, score = "validation_error", None
    elif any(item["status"] == "failed" for item in results):
        status, score = "failed", 0
    elif any(item["status"] == "needs_judge" for item in results):
        status, score = "review_required", None
    else:
        status, score = "passed", 1
    return {"status": status, "score": score, "checks": results}
