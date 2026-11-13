"""Resolve grader inheritance and applicability before target execution."""

from __future__ import annotations

from typing import Any

from .evaluation_library import EvaluationLibrary
from .service import WorkspaceError


def grader_check(grader: dict[str, Any]) -> dict[str, Any]:
    check = {
        **grader["check"],
        "grader_id": grader["id"],
        "grader_name": grader["name"],
        "grader_version": grader["version"],
        "threshold": grader["threshold"],
    }
    if check["type"] == "judge":
        check["expected"] = (
            grader["rubric"]
            + "\n检查步骤：\n"
            + "\n".join(grader["steps"])
            + "\n判断要求："
            + str(check["expected"])
        )
        check["model_role"] = "grader_" + grader["id"]
    return check


def build_grading_plan(
    workspace,
    store,
    pid: str,
    tasks: list[dict],
    collection: dict | None,
    override: list[str] | None,
) -> tuple[list[dict], dict]:
    library = EvaluationLibrary(workspace, store)
    frozen = {}
    plans = []
    for task in tasks:
        if override is not None:
            ids, source = override, "run" if override else "embedded"
        elif collection and collection.get("grader_ids"):
            ids, source = collection["grader_ids"], "test_set"
        else:
            ids = task.get("default_grader_ids", [])
            source = "task" if ids else "embedded"
        checks, excluded = [], []
        for gid in ids:
            if gid not in frozen:
                frozen[gid] = library.grader(pid, gid)
            grader = frozen[gid]
            kinds = grader.get("task_kinds", ["conversation", "command", "http"])
            file_mismatch = (
                grader["check"]["type"].startswith("file_")
                and task["definition"]["kind"] != "command"
            )
            if task["definition"]["kind"] not in kinds or file_mismatch:
                excluded.append(
                    {
                        "grader_id": gid,
                        "grader_name": grader["name"],
                        "reason": "标准不适用于该题目类型",
                    }
                )
            else:
                checks.append(grader_check(grader))
        if not ids:
            checks = task["definition"]["checks"]
        if not checks:
            raise WorkspaceError(
                "题目“"
                + task["definition"]["title"]
                + "”没有适用的评分标准，请调整选择",
                status_code=422,
                code="no_applicable_grader",
            )
        plans.append(
            {
                "task_id": task["task_id"],
                "version_id": task["version_id"],
                "title": task["definition"]["title"],
                "source": source,
                "checks": checks,
                "not_applicable": excluded,
            }
        )
    sources = {p["source"] for p in plans}
    return list(frozen.values()), {
        "source": next(iter(sources)) if len(sources) == 1 else "mixed",
        "tasks": plans,
    }
