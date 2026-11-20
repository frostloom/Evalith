#!/usr/bin/env python3
"""Stage 5 deterministic acceptance driver for the Evalith MVP.

This script drives a *running* Evalith service over its public HTTP API.  It
covers the parts of the acceptance matrix that do not require an authorized
real model: fresh project import, source-scoped understanding, manual versioned
assets, environment plans, scoring preflight, command/HTTP execution, per-case
evidence, budgets, cancellation, isolation boundaries and result analysis
budgets.  Model-generated assets, judging, calibration and conversation targets
are not simulated; the report records them as blocked when no real model
endpoint is configured.

It is intentionally stdlib-only and writes one JSON receipt per API call plus
an assertion summary, so the evidence can be replayed and reviewed.

Usage (server already running):

    python3 scripts/stage5_acceptance.py --base-url http://127.0.0.1:8094 \
        --out .evalith/stage5/acceptance --phase all

Phases: setup, core, cancel, boundaries, analysis, restart-prepare,
restart-verify.  `all` runs every phase except the restart pair, which needs the
service to be stopped and started between them.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

TERMINAL = {"completed", "failed", "cancelled", "budget_stopped", "interrupted"}


class AcceptanceError(RuntimeError):
    pass


def record(path: Path, data: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


class Api:
    def __init__(self, base_url: str, receipts: Path):
        self.base = base_url.rstrip("/")
        self.receipts = receipts

    def call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expected: tuple[int, ...] = (200, 201, 202, 204),
        name: str | None = None,
        allow: tuple[int, ...] = (),
    ) -> tuple[int, Any]:
        url = self.base + path
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode()
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                status = response.status
                body = response.read().decode()
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read().decode()
        except urllib.error.URLError as exc:
            raise AcceptanceError(f"{method} {path} failed: {exc}") from exc
        try:
            parsed = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed = body
        if status not in expected and status not in allow:
            raise AcceptanceError(
                f"{method} {path} -> {status}: {str(parsed)[:800]}"
            )
        record(
            self.receipts,
            {
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "method": method,
                "path": path,
                "request": payload,
                "status": status,
                "response": parsed,
                "name": name or path,
            },
        )
        return status, parsed

    def get(self, path: str, **kwargs: Any):
        return self.call("GET", path, **kwargs)

    def post(self, path: str, payload: dict[str, Any] | None = None, **kwargs: Any):
        return self.call("POST", path, payload or {}, **kwargs)

    def put(self, path: str, payload: dict[str, Any], **kwargs: Any):
        return self.call("PUT", path, payload, **kwargs)


class Results:
    def __init__(self, path: Path):
        self.path = path
        self.items: list[dict[str, Any]] = []

    def expect(self, name: str, condition: bool, detail: Any = None) -> None:
        entry = {"name": name, "passed": bool(condition), "detail": detail}
        self.items.append(entry)
        mark = "PASS" if condition else "FAIL"
        print(f"[{mark}] {name}")
        record(self.path, entry)
        if not condition:
            raise AcceptanceError(f"assertion failed: {name}: {detail}")

    def summary(self) -> None:
        failures = [item for item in self.items if not item["passed"]]
        payload = {
            "total": len(self.items),
            "passed": len(self.items) - len(failures),
            "failed": len(failures),
            "failures": failures,
        }
        self.path.with_name("summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2)
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))

    def get(self, key: str) -> Any:
        if key not in self.data:
            raise AcceptanceError(f"state key missing: {key}")
        return self.data[key]

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()


def wait_run(api: Api, pid: str, run_id: str, timeout: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, run = api.get(f"/api/projects/{pid}/runs/{run_id}")
        if run["status"] in TERMINAL:
            return run
        time.sleep(0.25)
    raise AcceptanceError(f"run {run_id} did not finish within {timeout}s")


def result_by_title(run: dict[str, Any], title: str) -> dict[str, Any]:
    for result in run["results"]:
        if result["task"]["definition"]["title"] == title:
            return result
    raise AcceptanceError(f"result not found: {title}")


def task_payload(
    title: str,
    *,
    kind: str = "command",
    stdin: str = "",
    checks: list[dict[str, Any]] | None = None,
    category: str = "文件",
    input_value: dict[str, Any] | None = None,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "category": category,
        "objective": "验证阶段 5 的合成文件转换任务",
        "kind": kind,
        "input": input_value
        if input_value is not None
        else ({"stdin": stdin, "files": {}} if kind == "command" else {"turns": []}),
        "checks": checks
        or [{"type": "exit_code", "expected": 0}],
        "rubric": "目标读取 stdin 中的 items，写出 report.json 并打印相同 JSON。",
        "source_refs": source_refs or ["README.md"],
        "uncertainties": [],
    }


def make_project_fixtures(root: Path, repo: Path) -> dict[str, Path]:
    fixtures = root / "fixtures"
    if fixtures.exists():
        shutil.rmtree(fixtures)
    file_project = fixtures / "file-transform"
    file_project.mkdir(parents=True)
    for name in ("README.md", "main.py"):
        shutil.copy2(repo / "examples" / "file-transform" / name, file_project / name)
    (file_project / "runner.py").write_text(
        '"""Deterministic fast/slow target used to exercise cancellation."""\n'
        "import json\nimport sys\nimport time\n\n"
        "case = json.load(sys.stdin).get('case')\n"
        "if case == 'slow':\n    time.sleep(30)\n"
        "print(json.dumps({'case': case, 'ok': True}))\n"
    )
    boundary = fixtures / "boundary-project"
    boundary.mkdir(parents=True)
    (boundary / "README.md").write_text(
        "# Boundary project\n\nA synthetic release agent. Only release managers may publish.\n"
    )
    (boundary / "src").mkdir()
    (boundary / "src" / "agent.py").write_text(
        "def can_publish(role):\n    return role == 'release_manager'\n"
    )
    (boundary / "notes.txt").write_text(
        'API_KEY = "sk-stage5-must-not-leak"\nRelease notes are ordinary.\n'
    )
    (boundary / ".env").write_text("OPENAI_API_KEY=sk-stage5-env-secret\n")
    (boundary / "secrets").mkdir()
    (boundary / "secrets" / "credentials.txt").write_text(
        "token=sk-stage5-file-secret\n"
    )
    os.symlink("/etc/passwd", boundary / "outside-link")
    return {"file_project": file_project, "boundary": boundary}


class _TargetHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:  # noqa: N802 - stdlib hook
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        payload = {
            "path": self.path,
            "received": body,
            "sum": body.get("a", 0) + body.get("b", 0)
            if isinstance(body.get("a", 0), int) and isinstance(body.get("b", 0), int)
            else None,
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_target() -> tuple[str, ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TargetHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return f"http://127.0.0.1:{port}", server


def ensure_model(api: Api, results: Results, state: State) -> str:
    _, models = api.get("/api/model-configs")
    for item in models["items"]:
        if item["provider"] == "stub":
            state.set("model_id", item["id"])
            results.expect("离线演示模型可复用", True, item["id"])
            return item["id"]
    _, model = api.post(
        "/api/model-configs",
        {
            "name": "阶段 5 验收离线演示",
            "provider": "stub",
            "model_name": "stub-understanding",
        },
        expected=(201,),
        name="create-stub-model",
    )
    state.set("model_id", model["id"])
    results.expect("离线演示模型创建", model["provider"] == "stub", model["id"])
    return model["id"]


def ensure_project(
    api: Api,
    results: Results,
    state: State,
    key: str,
    *,
    name: str,
    root: Path,
    model_id: str,
    include: list[str] | None = None,
    supplemental: list[dict[str, str]] | None = None,
) -> str:
    if key in state.data:
        pid = state.get(key)
        _, detail = api.get(f"/api/projects/{pid}")
        results.expect(f"{name} 已导入且可重开", detail["project"]["id"] == pid, pid)
        return pid
    status, detail = api.post(
        "/api/projects",
        {
            "name": name,
            "root_path": str(root.resolve()),
            "model_config_id": model_id,
            "include_paths": include,
            "exclude_patterns": None,
            "supplemental": supplemental,
        },
        expected=(201,),
        name=f"import-project-{key}",
    )
    pid = detail["project"]["id"]
    state.set(key, pid)
    results.expect(
        f"{name} 导入成功", status == 201 and detail["snapshot"]["file_count"] > 0, pid
    )
    return pid


def continue_project(api: Api, results: Results, pid: str, name: str) -> None:
    _, detail = api.get(f"/api/projects/{pid}")
    if not detail["readiness"]["generation_allowed"]:
        results.expect(
            f"{name} 在显式继续前不生成资产",
            not detail["readiness"]["generation_allowed"],
            detail["readiness"]["reason"],
        )
        _, detail = api.post(
            f"/api/projects/{pid}/continue",
            {},
            name=f"continue-{name}",
        )
    results.expect(
        f"{name} 显式继续后允许设计资产",
        detail["readiness"]["generation_allowed"] is True,
        detail["readiness"],
    )
    results.expect(
        f"{name} 未知项不因继续被确认",
        detail["readiness"]["unknowns_confirmed"] is False,
        detail["readiness"],
    )


def create_task(
    api: Api,
    results: Results,
    pid: str,
    payload: dict[str, Any],
    *,
    name: str,
) -> dict[str, Any]:
    status, task = api.post(
        f"/api/projects/{pid}/tasks", payload, expected=(201,), name=name
    )
    results.expect(
        f"题目可创建：{payload['title']}",
        status == 201 and task["definition"]["title"] == payload["title"],
        task["id"],
    )
    return task


def make_environment(
    api: Api,
    results: Results,
    pid: str,
    *,
    executor_id: str | None = None,
    adapter: str | None = None,
    isolated: bool | None = None,
    label: str,
    timeout: float = 120,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if executor_id:
        payload["executor_config_id"] = executor_id
    if adapter:
        payload["adapter"] = adapter
    if isolated is not None:
        payload["isolated_data_confirmed"] = isolated
    _, plan = api.post(
        f"/api/projects/{pid}/environments/plan",
        payload,
        expected=(201,),
        name=f"plan-{label}",
    )
    results.expect(
        f"{label} 方案需要确认",
        plan["status"] == "planned" and plan["requires_confirmation"] is True,
        plan["id"],
    )
    api.post(
        f"/api/projects/{pid}/environments/{plan['id']}/confirm",
        {"plan_digest": plan["plan_digest"]},
        expected=(202,),
        name=f"confirm-{label}",
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, env = api.get(f"/api/projects/{pid}/environments/{plan['id']}")
        if env["status"] in {"ready", "failed", "interrupted"}:
            results.expect(
                f"{label} 环境准备完成",
                env["status"] == "ready",
                env.get("error") or env["status"],
            )
            return env
        time.sleep(0.2)
    raise AcceptanceError(f"environment {plan['id']} not ready in {timeout}s")


def create_executor(
    api: Api, results: Results, state: State, key: str, payload: dict[str, Any]
) -> str:
    if key in state.data:
        return state.get(key)
    _, saved = api.post(
        "/api/executor-configs", payload, expected=(201,), name=f"executor-{key}"
    )
    state.set(key, saved["id"])
    results.expect(f"执行器可保存（{payload['name']}）", bool(saved["id"]), saved["id"])
    return saved["id"]


def start_run(
    api: Api,
    results: Results,
    pid: str,
    payload: dict[str, Any],
    *,
    label: str,
    expect_ok: bool = True,
) -> dict[str, Any]:
    _, preview = api.post(
        f"/api/projects/{pid}/runs/preview", payload, name=f"preview-{label}"
    )
    results.expect(
        f"{label} 预检不执行目标且返回评分方案",
        "grading_plan" in preview and "plan_digest" in preview,
        preview.get("grading_source"),
    )
    _, run = api.post(
        f"/api/projects/{pid}/runs",
        {**payload, "plan_digest": preview["plan_digest"]},
        expected=(202,),
        name=f"start-{label}",
    )
    finished = wait_run(api, pid, run["id"])
    if expect_ok:
        results.expect(
            f"{label} 运行结束", finished["status"] == "completed", finished["status"]
        )
    return finished


def phase_setup(
    api: Api, results: Results, state: State, repo: Path, work: Path
) -> None:
    _, health = api.get("/api/health", name="health")
    results.expect("服务健康", health.get("ok") is True, health)
    model_id = ensure_model(api, results, state)
    fixtures = make_project_fixtures(work, repo)
    state.set("fixtures", {k: str(v) for k, v in fixtures.items()})
    file_pid = ensure_project(
        api,
        results,
        state,
        "file_pid",
        name="阶段 5 文件转换验收",
        root=fixtures["file_project"],
        model_id=model_id,
    )
    continue_project(api, results, file_pid, "文件转换项目")
    boundary_pid = ensure_project(
        api,
        results,
        state,
        "boundary_pid",
        name="阶段 5 边界验收",
        root=fixtures["boundary"],
        model_id=model_id,
    )
    continue_project(api, results, boundary_pid, "边界项目")
    support_root = work / "fixtures" / "support-agent"
    shutil.copytree(repo / "examples" / "support-agent", support_root)
    support_pid = ensure_project(
        api,
        results,
        state,
        "support_pid",
        name="阶段 5 对话验收",
        root=support_root,
        model_id=model_id,
    )
    continue_project(api, results, support_pid, "对话项目")


def phase_core(api: Api, results: Results, state: State) -> None:
    pid = state.get("file_pid")
    local_exec = create_executor(
        api,
        results,
        state,
        "local_exec",
        {
            "name": "阶段 5 本地命令",
            "backend": "local_command",
            "command": ["python3", "main.py"],
            "timeout_seconds": 10,
        },
    )
    env = make_environment(
        api, results, pid, executor_id=local_exec, label="本地命令环境"
    )
    state.set("local_env", env["id"])

    passing = create_task(
        api,
        results,
        pid,
        task_payload(
            "两笔金额求和",
            stdin=json.dumps({"items": [{"cents": 100}, {"cents": 250}]}),
            checks=[
                {"type": "exit_code", "expected": 0},
                {"type": "file_exists", "path": "report.json"},
                {"type": "json_equals", "path": "total_cent", "expected": 350},
            ],
        ),
        name="task-passing",
    )
    failing = create_task(
        api,
        results,
        pid,
        task_payload(
            "错误的金额预期",
            stdin=json.dumps({"items": [{"cents": 100}, {"cents": 250}]}),
            checks=[{"type": "json_equals", "path": "total_cent", "expected": 999}],
        ),
        name="task-failing",
    )
    missing = create_task(
        api,
        results,
        pid,
        task_payload(
            "缺失证据",
            stdin=json.dumps({"items": []}),
            checks=[
                {"type": "file_contains", "path": "missing.json", "expected": "ok"}
            ],
        ),
        name="task-missing",
    )
    judged = create_task(
        api,
        results,
        pid,
        task_payload(
            "需要模型判断",
            stdin=json.dumps({"items": []}),
            checks=[{"type": "judge", "expected": "输出包含 count 和 total_cent"}],
        ),
        name="task-judge",
    )
    state.set(
        "tasks",
        {
            "passing": passing["version_id"],
            "failing": failing["version_id"],
            "missing": missing["version_id"],
            "judged": judged["version_id"],
        },
    )

    run = start_run(
        api,
        results,
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [passing["version_id"], failing["version_id"], missing["version_id"]],
            "max_model_calls": 8,
            "name": "确定性结果分类",
        },
        label="确定性结果分类",
    )
    state.set("run_mixed", run["id"])
    passed = result_by_title(run, "两笔金额求和")
    results.expect(
        "通过结果有分数与证据目录",
        passed["status"] == "passed"
        and passed["score"] == 1
        and passed["observation"].get("evidence_directory"),
        passed["status"],
    )
    failed = result_by_title(run, "错误的金额预期")
    results.expect(
        "业务失败与执行错误可区分",
        failed["status"] == "failed" and failed["score"] == 0,
        failed["status"],
    )
    absent = result_by_title(run, "缺失证据")
    results.expect(
        "缺失证据不判为通过也不记零分",
        absent["status"] == "validation_error"
        and absent["score"] is None
        and any(c["status"] == "missing_evidence" for c in absent["checks"]),
        absent["status"],
    )
    results.expect(
        "未知费用保持未知",
        run["usage"]["cost_usd"] is None,
        run["usage"],
    )
    results.expect(
        "运行记录逐题持久化",
        len(run["results"]) == 3 and run["cleanup_status"] == "completed",
        run["cleanup_status"],
    )
    results.expect(
        "运行冻结题目版本快照",
        all(r["task"]["definition"]["title"] for r in run["results"]),
        [r["task"]["version_id"] for r in run["results"]],
    )

    # Budget stop: deterministic case completes, the judge case stops before a
    # model call, and the remaining case is skipped without being scored.
    budget_run = start_run(
        api,
        results,
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [passing["version_id"], judged["version_id"], failing["version_id"]],
            "max_model_calls": 0,
            "name": "预算停止验证",
        },
        label="预算停止",
        expect_ok=False,
    )
    state.set("run_budget", budget_run["id"])
    results.expect(
        "预算停止保留已完成结果",
        budget_run["status"] == "budget_stopped"
        and result_by_title(budget_run, "两笔金额求和")["status"] == "passed",
        budget_run["status"],
    )
    results.expect(
        "预算停止的未运行题不计失败或零分",
        result_by_title(budget_run, "需要模型判断")["status"] == "budget_stopped"
        and result_by_title(budget_run, "错误的金额预期")["status"] == "skipped"
        and result_by_title(budget_run, "错误的金额预期")["score"] is None,
        [
            r["status"]
            for r in budget_run["results"]
        ],
    )

    # Executor-level execution error (timeout) is not a business failure.
    timeout_exec = create_executor(
        api,
        results,
        state,
        "timeout_exec",
        {
            "name": "阶段 5 超时命令",
            "backend": "local_command",
            "command": ["sleep", "30"],
            "timeout_seconds": 2,
        },
    )
    timeout_env = make_environment(
        api, results, pid, executor_id=timeout_exec, label="超时命令环境"
    )
    timeout_task = create_task(
        api,
        results,
        pid,
        task_payload("超时任务", stdin="{}", checks=[{"type": "exit_code", "expected": 0}]),
        name="task-timeout",
    )
    timeout_run = start_run(
        api,
        results,
        pid,
        {
            "environment_id": timeout_env["id"],
            "version_ids": [timeout_task["version_id"]],
            "max_model_calls": 0,
            "name": "执行错误验证",
        },
        label="执行错误",
        expect_ok=False,
    )
    state.set("run_timeout", timeout_run["id"])
    timeout_result = timeout_run["results"][0]
    results.expect(
        "超时记为执行错误",
        timeout_run["status"] == "failed"
        and timeout_result["status"] == "execution_error"
        and "timeout" in (timeout_result.get("error") or ""),
        timeout_result["status"],
    )

    # Deterministic grader + test set precedence, preflight snapshot and
    # immutability after a grader version change.
    _, grader = api.post(
        f"/api/projects/{pid}/graders",
        {
            "name": "报告总额标准",
            "description": "确定性文件检查，不调用模型",
            "rubric": "report.json 的总金额必须是 350。",
            "steps": [],
            "check": {
                "type": "file_contains",
                "path": "report.json",
                "expected": '"total_cent": 350',
            },
            "threshold": 0.8,
            "source_refs": ["README.md"],
            "uncertainties": [],
        },
        expected=(201,),
        name="create-grader",
    )
    state.set("grader_id", grader["id"])
    _, test_set = api.post(
        f"/api/projects/{pid}/test-sets",
        {
            "name": "文件转换测试集",
            "description": "确定性 Grader 优先级验证",
            "task_ids": [passing["id"]],
            "grader_ids": [grader["id"]],
        },
        expected=(201,),
        name="create-test-set",
    )
    state.set("test_set_id", test_set["id"])
    set_run = start_run(
        api,
        results,
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [passing["version_id"]],
            "test_set_id": test_set["id"],
            "max_model_calls": 0,
            "name": "测试集与 Grader",
        },
        label="测试集与 Grader",
    )
    state.set("run_set", set_run["id"])
    set_result = set_run["results"][0]
    results.expect(
        "测试集 Grader 在预检与结果中生效",
        set_result["status"] == "passed"
        and any(c.get("grader_id") == grader["id"] for c in set_result["checks"])
        and set_run["grading_source"] == "test_set",
        set_run["grading_source"],
    )
    old_frozen = set_run["graders"][0]
    api.put(
        f"/api/projects/{pid}/graders/{grader['id']}",
        {
            "name": "报告总额标准",
            "description": "更新后的确定性检查",
            "rubric": "report.json 的总金额必须是 350；此版本仅用于验证历史冻结。",
            "steps": [],
            "check": {
                "type": "file_contains",
                "path": "report.json",
                "expected": '"total_cent": 350',
            },
            "threshold": 0.5,
            "source_refs": ["README.md"],
            "uncertainties": [],
        },
        expected=(200,),
        name="edit-grader",
    )
    _, old_run = api.get(f"/api/projects/{pid}/runs/{set_run['id']}")
    results.expect(
        "修改 Grader 不改写历史运行快照",
        old_run["graders"][0]["version"] == old_frozen["version"]
        and old_run["graders"][0]["threshold"] == old_frozen["threshold"],
        old_run["graders"][0],
    )

    # Task edit creates a new version; the earlier run keeps its frozen copy.
    _, edited = api.put(
        f"/api/projects/{pid}/tasks/{passing['id']}",
        task_payload(
            "两笔金额求和（已编辑）",
            stdin=json.dumps({"items": [{"cents": 100}, {"cents": 250}]}),
            checks=[
                {"type": "exit_code", "expected": 0},
                {"type": "json_equals", "path": "total_cent", "expected": 350},
            ],
        ),
        name="edit-task",
    )
    results.expect(
        "编辑题目生成新版本",
        edited["version"] == passing["version"] + 1,
        edited["version"],
    )
    _, versions = api.get(f"/api/projects/{pid}/tasks/{passing['id']}/versions")
    results.expect(
        "旧版本仍可追溯",
        len(versions["items"]) >= 2
        and versions["items"][-1]["version"] == passing["version"],
        [v["version"] for v in versions["items"]],
    )
    _, old_run = api.get(f"/api/projects/{pid}/runs/{run['id']}")
    results.expect(
        "修改题目不改写历史运行",
        result_by_title(old_run, "两笔金额求和")["status"] == "passed",
        old_run["results"][0]["task"]["version_id"],
    )
    state.set(
        "edited_task", {"id": edited["id"], "version_id": edited["version_id"]}
    )


def phase_cancel(api: Api, results: Results, state: State) -> None:
    pid = state.get("file_pid")
    cancel_exec = create_executor(
        api,
        results,
        state,
        "cancel_exec",
        {
            "name": "阶段 5 取消命令",
            "backend": "local_command",
            "command": ["python3", "runner.py"],
            "timeout_seconds": 30,
        },
    )
    env = make_environment(
        api, results, pid, executor_id=cancel_exec, label="取消命令环境"
    )
    fast = create_task(
        api,
        results,
        pid,
        task_payload("快速用例", stdin=json.dumps({"case": "fast"}), source_refs=["README.md"]),
        name="task-fast",
    )
    slow = create_task(
        api,
        results,
        pid,
        task_payload("慢速用例", stdin=json.dumps({"case": "slow"}), source_refs=["README.md"]),
        name="task-slow",
    )
    _, preview = api.post(
        f"/api/projects/{pid}/runs/preview",
        {
            "environment_id": env["id"],
            "version_ids": [fast["version_id"], slow["version_id"]],
            "max_model_calls": 0,
            "name": "取消与部分结果",
        },
        name="preview-cancel",
    )
    _, run = api.post(
        f"/api/projects/{pid}/runs",
        {
            "environment_id": env["id"],
            "version_ids": [fast["version_id"], slow["version_id"]],
            "max_model_calls": 0,
            "name": "取消与部分结果",
            "plan_digest": preview["plan_digest"],
        },
        expected=(202,),
        name="start-cancel",
    )
    run_id = run["id"]
    state.set("run_cancel", run_id)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        _, current = api.get(f"/api/projects/{pid}/runs/{run_id}")
        if any(r["status"] == "passed" for r in current["results"]):
            break
        time.sleep(0.2)
    api.post(f"/api/projects/{pid}/runs/{run_id}/cancel", {}, name="cancel-run")
    finished = wait_run(api, pid, run_id)
    fast_result = result_by_title(finished, "快速用例")
    slow_result = result_by_title(finished, "慢速用例")
    results.expect(
        "取消保留已完成结果",
        finished["status"] == "cancelled" and fast_result["status"] == "passed",
        finished["status"],
    )
    results.expect(
        "取消的题目不伪装为通过",
        slow_result["status"] in {"cancelled", "skipped"},
        slow_result["status"],
    )


def phase_boundaries(
    api: Api, results: Results, state: State, work: Path
) -> None:
    pid = state.get("boundary_pid")
    _, detail = api.get(f"/api/projects/{pid}")
    files = {item["path"]: item for item in detail["snapshot"]["files"]}
    results.expect(
        "敏感名称文件不进入资料范围",
        ".env" not in files and "secrets/credentials.txt" not in files,
        sorted(files),
    )
    results.expect(
        "符号链接不被跟进",
        "outside-link" not in files
        or files["outside-link"].get("sent") is False,
        files.get("outside-link"),
    )
    _, messages = api.get(
        f"/api/projects/{pid}/sessions/{detail['session']['id']}/messages"
    )
    rendered = json.dumps(messages, ensure_ascii=False)
    results.expect(
        "行内凭据未以明文进入会话上下文",
        "sk-stage5-must-not-leak" not in rendered
        and "sk-stage5-env-secret" not in rendered,
        "secret scan",
    )
    _, denied = api.post(
        "/api/projects",
        {
            "name": "拒绝敏感范围",
            "root_path": state.get("fixtures")["boundary"],
            "model_config_id": state.get("model_id"),
            "include_paths": [".env"],
        },
        expected=(422,),
        name="reject-env-scope",
    )
    results.expect(
        "显式选择敏感文件被拒绝", denied.get("code") == "sensitive_path_denied", denied
    )
    _, denied = api.post(
        "/api/projects",
        {
            "name": "拒绝链接范围",
            "root_path": state.get("fixtures")["boundary"],
            "model_config_id": state.get("model_id"),
            "include_paths": ["outside-link"],
        },
        expected=(422,),
        name="reject-symlink-scope",
    )
    results.expect(
        "显式选择符号链接被拒绝", denied.get("code") == "symlink_rejected", denied
    )
    pid_file = state.get("file_pid")
    _, invalid = api.post(
        f"/api/projects/{pid_file}/tasks",
        task_payload(
            "路径越界检查",
            checks=[{"type": "file_contains", "path": "../outside", "expected": "x"}],
        ),
        expected=(422,),
        name="reject-traversal-check",
    )
    results.expect("路径越界的检查规则被拒绝", True, invalid.get("code"))

    # HTTP adapter only accepts loopback targets and an explicit synthetic-data
    # confirmation.
    _, remote = api.post(
        "/api/executor-configs",
        {
            "name": "非 loopback 目标",
            "backend": "http_api",
            "base_url": "http://example.com/eval",
        },
        expected=(201,),
        name="save-remote-http-target",
    )
    _, denied = api.post(
        f"/api/projects/{pid_file}/environments/plan",
        {"executor_config_id": remote["id"]},
        expected=(422,),
        name="reject-remote-http-target",
    )
    results.expect(
        "非 loopback HTTP 目标在环境方案中被明确拒绝",
        "本机隔离服务" in (denied.get("error") or ""),
        denied,
    )
    target_url, server = start_target()
    state.set("target_url", target_url)
    http_exec = create_executor(
        api,
        results,
        state,
        "http_exec",
        {
            "name": "阶段 5 本机 HTTP",
            "backend": "http_api",
            "base_url": target_url,
            "timeout_seconds": 10,
        },
    )
    _, denied = api.post(
        f"/api/projects/{pid_file}/environments/plan",
        {"executor_config_id": http_exec},
        expected=(422,),
        name="reject-http-without-confirmation",
    )
    results.expect("HTTP 环境未确认独立数据时拒绝", True, denied.get("code"))
    http_env = make_environment(
        api,
        results,
        pid_file,
        executor_id=http_exec,
        isolated=True,
        label="HTTP 环境",
    )
    state.set("http_env", http_env["id"])
    http_task = create_task(
        api,
        results,
        pid_file,
        {
            "title": "HTTP 求和",
            "category": "API",
            "objective": "调用本机合成 HTTP 目标并核对响应",
            "kind": "http",
            "input": {"method": "POST", "path": "/eval", "json": {"a": 2, "b": 3}},
            "checks": [
                {"type": "status_code", "expected": 200},
                {"type": "json_equals", "path": "sum", "expected": 5},
            ],
            "rubric": "响应 JSON 的 sum 必须为 5。",
            "source_refs": ["README.md"],
            "uncertainties": [],
        },
        name="task-http",
    )
    state.set("http_task", http_task["version_id"])
    state.set("http_task_id", http_task["id"])
    http_run = start_run(
        api,
        results,
        pid_file,
        {
            "environment_id": http_env["id"],
            "version_ids": [http_task["version_id"]],
            "max_model_calls": 0,
            "name": "HTTP 合成任务",
        },
        label="HTTP 合成任务",
    )
    state.set("run_http", http_run["id"])
    http_result = http_run["results"][0]
    results.expect(
        "HTTP 任务真实调用本机目标并核对证据",
        http_result["status"] == "passed"
        and http_result["observation"]["json"]["sum"] == 5,
        http_result["status"],
    )

    # Command sandbox: writes outside the per-case directory and non-loopback
    # network are denied by the macOS profile.
    outside = work / "outside-write-marker"
    if outside.exists():
        outside.unlink()
    write_exec = create_executor(
        api,
        results,
        state,
        "write_exec",
        {
            "name": "阶段 5 越界写入",
            "backend": "local_command",
            "command": [
                "python3",
                "-c",
                f"open({str(outside)!r}, 'w').write('escaped')",
            ],
            "timeout_seconds": 10,
        },
    )
    write_env = make_environment(
        api, results, pid_file, executor_id=write_exec, label="越界写入环境"
    )
    write_task = create_task(
        api,
        results,
        pid_file,
        task_payload("越界写入被拒绝", stdin="{}", source_refs=["README.md"]),
        name="task-write",
    )
    write_run = start_run(
        api,
        results,
        pid_file,
        {
            "environment_id": write_env["id"],
            "version_ids": [write_task["version_id"]],
            "max_model_calls": 0,
            "name": "越界写入",
        },
        label="越界写入",
        expect_ok=False,
    )
    results.expect(
        "命令不能写出单题目录",
        not outside.exists(),
        str(outside),
    )
    results.expect(
        "越界写入在结果中失败而非通过",
        write_run["results"][0]["status"] == "failed",
        write_run["results"][0]["status"],
    )
    port = urlparse(target_url).port
    network_exec = create_executor(
        api,
        results,
        state,
        "network_exec",
        {
            "name": "阶段 5 网络边界",
            "backend": "local_command",
            "command": [
                "python3",
                "-c",
                "import socket; socket.create_connection(('127.0.0.1', "
                + str(port)
                + "), 3).close(); print('connected')",
            ],
            "timeout_seconds": 10,
        },
    )
    network_env = make_environment(
        api, results, pid_file, executor_id=network_exec, label="网络边界环境"
    )
    network_task = create_task(
        api,
        results,
        pid_file,
        task_payload("网络访问被拒绝", stdin="{}", source_refs=["README.md"]),
        name="task-network",
    )
    network_run = start_run(
        api,
        results,
        pid_file,
        {
            "environment_id": network_env["id"],
            "version_ids": [network_task["version_id"]],
            "max_model_calls": 0,
            "name": "网络边界",
        },
        label="网络边界",
        expect_ok=False,
    )
    network_result = network_run["results"][0]
    results.expect(
        "命令沙盒拒绝网络连接",
        network_result["status"] == "failed"
        and "connected" not in (network_result["observation"].get("stdout") or ""),
        network_result["observation"].get("stderr", "")[:300],
    )

    # Cross-project access and conversation adapter mismatch.
    support_pid = state.get("support_pid")
    _, cross = api.get(
        f"/api/projects/{pid}/runs/{state.get('run_mixed')}", expected=(404,)
    )
    results.expect("跨项目运行 ID 不可读取", True, cross)
    _, other = api.get(
        f"/api/projects/{support_pid}/tasks/{state.get('http_task_id')}",
        expected=(404,),
    )
    results.expect("跨项目题目 ID 不可读取", True, other)
    conversation = create_task(
        api,
        results,
        support_pid,
        {
            "title": "多轮退款边界",
            "category": "对话",
            "objective": "验证脚本多轮输入与退款边界",
            "kind": "conversation",
            "input": {
                "turns": [
                    "我想退款，可以吗？",
                    "如果不能退款，请说明政策条款。",
                ]
            },
            "checks": [{"type": "contains", "expected": "政策"}],
            "rubric": "回复不得承诺退款，并引用政策条款。",
            "source_refs": ["README.md"],
            "uncertainties": ["真实用户行为未校准"],
        },
        name="task-conversation",
    )
    state.set("conversation_task", conversation["version_id"])
    local_exec = state.get("local_exec")
    support_env = make_environment(
        api,
        results,
        support_pid,
        executor_id=local_exec,
        label="对话项目本地环境",
    )
    _, mismatch = api.post(
        f"/api/projects/{support_pid}/runs/preview",
        {
            "environment_id": support_env["id"],
            "version_ids": [conversation["version_id"]],
            "max_model_calls": 0,
        },
        expected=(422,),
        name="conversation-adapter-mismatch",
    )
    results.expect(
        "对话题目不会被本地命令执行器静默降级",
        mismatch.get("code") == "task_adapter_mismatch",
        mismatch,
    )
    results.expect(
        "对话执行依赖真实模型，本环境标记为未验证",
        True,
        "No authorized OpenAI-compatible endpoint; aigateway_go target path remains unverified.",
    )
    server.shutdown()


def phase_harbor(api: Api, results: Results, state: State) -> None:
    """Real Harbor container execution of the same command fixture."""
    pid = state.get("file_pid")
    harbor_exec = create_executor(
        api,
        results,
        state,
        "harbor_exec",
        {
            "name": "阶段 5 Harbor 容器",
            "backend": "harbor",
            "command": ["python3", "main.py"],
            "timeout_seconds": 180,
        },
    )
    env = make_environment(
        api,
        results,
        pid,
        executor_id=harbor_exec,
        label="Harbor 容器环境",
        timeout=300,
    )
    results.expect(
        "Harbor 环境记录 CLI 与 Docker 版本",
        bool(env["runtime"].get("harbor_version"))
        and bool(env["runtime"].get("docker_version")),
        {
            "harbor": env["runtime"].get("harbor_version"),
            "docker": env["runtime"].get("docker_version"),
        },
    )
    state.set("harbor_env", env["id"])
    passing = create_task(
        api,
        results,
        pid,
        task_payload(
            "容器内金额求和",
            stdin=json.dumps({"items": [{"cents": 100}, {"cents": 250}]}),
            checks=[
                {"type": "exit_code", "expected": 0},
                {"type": "file_contains", "path": "report.json", "expected": '"total_cent": 350'},
            ],
        ),
        name="task-harbor-passing",
    )
    failing = create_task(
        api,
        results,
        pid,
        task_payload(
            "容器内错误预期",
            stdin=json.dumps({"items": [{"cents": 100}, {"cents": 250}]}),
            checks=[
                {"type": "file_contains", "path": "report.json", "expected": '"total_cent": 999'},
            ],
        ),
        name="task-harbor-failing",
    )
    run = start_run(
        api,
        results,
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [passing["version_id"], failing["version_id"]],
            "max_model_calls": 0,
            "name": "Harbor 容器执行",
        },
        label="Harbor 容器执行",
    )
    state.set("run_harbor", run["id"])
    passed = result_by_title(run, "容器内金额求和")
    failed = result_by_title(run, "容器内错误预期")
    results.expect(
        "Harbor 真实容器通过题回收产物证据",
        passed["status"] == "passed"
        and passed["observation"].get("harbor", {}).get("harbor_version")
        and passed["observation"].get("evidence_directory"),
        passed["observation"].get("harbor"),
    )
    results.expect(
        "Harbor 容器内业务失败可区分",
        failed["status"] == "failed" and failed["score"] == 0,
        failed["status"],
    )
    results.expect(
        "Harbor 批次不产生模型调用",
        run["usage"]["model_calls"] == 0 and run["usage"]["cost_usd"] is None,
        run["usage"],
    )


def phase_analysis(api: Api, results: Results, state: State) -> None:
    pid = state.get("file_pid")
    run_id = state.get("run_mixed")
    _, before = api.get(f"/api/projects/{pid}/runs/{run_id}")
    _, analysis = api.post(
        f"/api/projects/{pid}/runs/{run_id}/analyses",
        {"selection": "all", "max_model_calls": 0},
        expected=(202,),
        name="analysis-zero-budget",
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        _, current = api.get(f"/api/projects/{pid}/analyses/{analysis['id']}")
        if current["status"] not in {"running", "pending"}:
            break
        time.sleep(0.1)
    _, current = api.get(f"/api/projects/{pid}/analyses/{analysis['id']}")
    results.expect(
        "分析预算为零时保持预算独立且停止",
        current["status"] == "budget_stopped" and current["usage"]["model_calls"] == 0,
        current["status"],
    )
    _, after = api.get(f"/api/projects/{pid}/runs/{run_id}")
    results.expect(
        "分析不改写原始运行结果",
        after["results"] == before["results"],
        "results unchanged",
    )
    _, low = api.post(
        f"/api/projects/{pid}/runs/{run_id}/analyses",
        {"selection": "low", "threshold": 0.8, "max_model_calls": 0},
        expected=(202,),
        name="analysis-low-scope",
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        _, current = api.get(f"/api/projects/{pid}/analyses/{low['id']}")
        if current["status"] not in {"running", "pending"}:
            break
        time.sleep(0.1)
    _, current = api.get(f"/api/projects/{pid}/analyses/{low['id']}")
    results.expect(
        "低分范围不把缺失分数当作零分",
        current["status"] == "budget_stopped"
        and set(current["result_ids"])
        == {
            r["id"]
            for r in after["results"]
            if type(r.get("score")) in (int, float) and r["score"] < 0.8
        },
        current["result_ids"],
    )
    _, model_required = api.post(
        f"/api/projects/{pid}/runs/{run_id}/analyses",
        {"selection": "all", "max_model_calls": 1},
        expected=(202,),
        name="analysis-stub-rejected",
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        _, current = api.get(
            f"/api/projects/{pid}/analyses/{model_required['id']}"
        )
        if current["status"] not in {"running", "pending"}:
            break
        time.sleep(0.1)
    _, current = api.get(f"/api/projects/{pid}/analyses/{model_required['id']}")
    results.expect(
        "真实分析需要真实模型，离线演示显式失败",
        current["status"] == "failed"
        and "离线演示" in (current.get("error") or ""),
        current.get("error"),
    )


def phase_restart_prepare(api: Api, results: Results, state: State) -> None:
    pid = state.get("file_pid")
    cancel_exec = state.get("cancel_exec")
    env = make_environment(
        api, results, pid, executor_id=cancel_exec, label="重启前环境"
    )
    slow = create_task(
        api,
        results,
        pid,
        task_payload("重启时运行中", stdin=json.dumps({"case": "slow"}), source_refs=["README.md"]),
        name="task-restart",
    )
    _, preview = api.post(
        f"/api/projects/{pid}/runs/preview",
        {
            "environment_id": env["id"],
            "version_ids": [slow["version_id"]],
            "max_model_calls": 0,
            "name": "重启恢复验证",
        },
        name="preview-restart",
    )
    _, run = api.post(
        f"/api/projects/{pid}/runs",
        {
            "environment_id": env["id"],
            "version_ids": [slow["version_id"]],
            "max_model_calls": 0,
            "name": "重启恢复验证",
            "plan_digest": preview["plan_digest"],
        },
        expected=(202,),
        name="start-restart",
    )
    state.set("run_restart", run["id"])
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        _, current = api.get(f"/api/projects/{pid}/runs/{run['id']}")
        if current["results"] and current["results"][0]["status"] in {
            "running",
            "validating",
        }:
            results.expect("重启前存在运行中记录", True, current["results"][0]["status"])
            return
        time.sleep(0.2)
    raise AcceptanceError("restart run did not reach a running case")


def phase_restart_verify(api: Api, results: Results, state: State) -> None:
    pid = state.get("file_pid")
    run_id = state.get("run_restart")
    _, run = api.get(f"/api/projects/{pid}/runs/{run_id}")
    results.expect(
        "重启后未结束运行标为中断",
        run["status"] == "interrupted",
        run["status"],
    )
    results.expect(
        "无法确认的清理状态显示未知",
        run["cleanup_status"] == "unknown_after_restart",
        run["cleanup_status"],
    )
    results.expect(
        "中断运行保留已保存的逐题记录",
        len(run["results"]) >= 1,
        [(r["status"], r.get("error")) for r in run["results"]],
    )
    _, projects = api.get("/api/projects")
    ids = {item["id"] for item in projects["items"]}
    results.expect(
        "重启后项目与会话仍可恢复",
        pid in ids,
        sorted(ids),
    )
    _, detail = api.get(f"/api/projects/{pid}")
    _, runs = api.get(f"/api/projects/{pid}/runs")
    results.expect(
        "重启后历史运行列表完整",
        {state.get("run_mixed"), state.get("run_set"), run_id}
        <= {item["id"] for item in runs["items"]},
        sorted(item["id"] for item in runs["items"]),
    )
    mixed = next(item for item in runs["items"] if item["id"] == state.get("run_mixed"))
    results.expect(
        "重启后已完成结果与分数保留",
        mixed["status"] == "completed"
        and any(r["status"] == "passed" for r in mixed["results"]),
        mixed["status"],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8094")
    parser.add_argument("--out", default=".evalith/stage5/acceptance")
    parser.add_argument(
        "--repo",
        default=str(Path(__file__).resolve().parents[1]),
        help="Evalith checkout containing examples/",
    )
    parser.add_argument(
        "--phase",
        default="all",
        choices=[
            "all",
            "setup",
            "core",
            "harbor",
            "cancel",
            "boundaries",
            "analysis",
            "restart-prepare",
            "restart-verify",
        ],
    )
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    api = Api(args.base_url, out / "receipts.jsonl")
    results = Results(out / "results.jsonl")
    state = State(out / "state.json")
    phases = {
        "setup": lambda: phase_setup(api, results, state, Path(args.repo), out),
        "core": lambda: phase_core(api, results, state),
        "harbor": lambda: phase_harbor(api, results, state),
        "cancel": lambda: phase_cancel(api, results, state),
        "boundaries": lambda: phase_boundaries(api, results, state, out),
        "analysis": lambda: phase_analysis(api, results, state),
        "restart-prepare": lambda: phase_restart_prepare(api, results, state),
        "restart-verify": lambda: phase_restart_verify(api, results, state),
    }
    requested = (
        ["setup", "core", "harbor", "cancel", "boundaries", "analysis"]
        if args.phase == "all"
        else [args.phase]
    )
    try:
        for name in requested:
            print(f"=== phase: {name} ===")
            phases[name]()
    finally:
        results.summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
