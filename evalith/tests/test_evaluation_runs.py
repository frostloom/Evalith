from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import create_stub_model, import_project
from evalith.evaluation_assets import EvaluationAssets
from evalith.evaluation_store import EvaluationStore
from evalith.environments import EnvironmentManager
from evalith.evaluation_runner import EvaluationRunner, evaluate_checks
from evalith.service import WorkspaceError


def fixture(client, project_root):
    model = create_stub_model(client)
    project = import_project(
        client, project_root, model_config_id=model["id"], include=["README.md"]
    ).json()["project"]
    pid = project["id"]
    client.post(f"/api/projects/{pid}/continue")
    ws = client.app.state.service
    store = EvaluationStore(ws.db)
    assets = EvaluationAssets(ws, store)
    envs = EnvironmentManager(ws, store)
    return pid, ws, store, assets, envs


def definition():
    return {
        "title": "File transform",
        "category": "Files",
        "objective": "Produce a file",
        "kind": "command",
        "input": {"stdin": "hello", "files": {}},
        "checks": [{"type": "contains", "expected": "hello"}],
        "rubric": "Echo the input",
        "source_refs": ["README.md"],
        "uncertainties": [],
    }


def test_environment_plan_is_bound_to_source_and_requires_confirmation(
    client, project_root, monkeypatch
):
    monkeypatch.setattr("evalith.environments.sandbox_available", lambda: True)
    pid, ws, store, assets, envs = fixture(client, project_root)
    config = client.post(
        "/api/executor-configs",
        json={
            "name": "Python",
            "backend": "local_command",
            "command": ["python3", "-c", "print(input())"],
            "timeout_seconds": 3,
        },
    ).json()
    plan = envs.plan(pid, {"executor_config_id": config["id"]})
    assert plan["status"] == "planned" and plan["requires_confirmation"] is True
    assert plan["plan"]["write_directory"].startswith(str(ws.settings.data_dir))
    assert not envs.directory(plan["id"]).exists()
    with pytest.raises(WorkspaceError):
        envs.confirm(pid, plan["id"], "wrong", background=False)
    (project_root / "README.md").write_text("changed")
    with pytest.raises(WorkspaceError) as stale:
        envs.confirm(pid, plan["id"], plan["plan_digest"], background=False)
    assert stale.value.status_code == 409


def test_missing_evidence_is_never_a_pass_or_a_zero_score(tmp_path):
    checks = [{"type": "file_contains", "path": "missing.json", "expected": "ok"}]
    result = evaluate_checks(checks, {"stdout": "ok", "json": None}, tmp_path)
    assert result["status"] == "validation_error" and result["score"] is None
    assert result["checks"][0]["status"] == "missing_evidence"
    with pytest.raises(WorkspaceError):
        evaluate_checks(
            [{"type": "file_contains", "path": "../outside", "expected": "x"}],
            {"stdout": "x"},
            tmp_path,
        )


def test_run_freezes_versions_and_preserves_results_when_budget_stops(
    client, project_root, monkeypatch
):
    pid, ws, store, assets, envs = fixture(client, project_root)
    first = assets.add(pid, definition())
    second = assets.add(pid, {**definition(), "title": "Second case"})
    env = store.create(
        pid,
        "environment",
        {
            "adapter": "local_command",
            "source_digest": first["source_digest"],
            "plan_digest": "confirmed",
            "requires_confirmation": False,
            "plan": {},
            "runtime": {},
        },
        status="ready",
    )
    runner = EvaluationRunner(ws, store, envs)

    def execute(run, task, work):
        runner.reserve_call(pid, run["id"], "target")
        return {"stdout": "hello", "json": None, "exit_code": 0}

    monkeypatch.setattr(runner, "execute_task", execute)
    changed = deepcopy(first["definition"])
    changed["title"] = "new title"
    assets.edit(pid, first["id"], changed)
    run = runner.start(
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [first["version_id"], second["version_id"]],
            "max_model_calls": 1,
        },
        background=False,
    )
    assert run["status"] == "budget_stopped"
    assert run["results"][0]["status"] == "passed"
    assert run["results"][0]["task"]["definition"]["title"] == "File transform"
    assert run["results"][1]["status"] == "budget_stopped"
    assert run["results"][1]["score"] is None
    assert run["usage"]["cost_usd"] is None
    assert store.get(pid, "run", run["id"])["results"][0]["score"] == 1


def test_cross_project_selection_and_unconfirmed_environment_are_rejected(
    client, project_root
):
    pid, ws, store, assets, envs = fixture(client, project_root)
    task = assets.add(pid, definition())
    runner = EvaluationRunner(ws, store, envs)
    env = store.create(
        pid,
        "environment",
        {
            "adapter": "local_command",
            "source_digest": task["source_digest"],
            "runtime": {},
        },
        status="planned",
    )
    with pytest.raises(WorkspaceError):
        runner.start(
            pid,
            {"environment_id": env["id"], "version_ids": [task["version_id"]]},
            background=False,
        )
    store.update(pid, "environment", env["id"], status="ready")
    with pytest.raises(WorkspaceError) as wrong:
        runner.start(
            "other",
            {"environment_id": env["id"], "version_ids": [task["version_id"]]},
            background=False,
        )
    assert wrong.value.status_code == 404


def test_agent_http_error_cannot_pass_negative_check(client, project_root, monkeypatch):
    pid, ws, store, assets, envs = fixture(client, project_root)
    task = assets.add(
        pid,
        {
            **definition(),
            "kind": "conversation",
            "input": {"turns": ["hello"]},
            "checks": [{"type": "not_contains", "expected": "forbidden"}],
        },
    )
    env = store.create(
        pid,
        "environment",
        {
            "adapter": "aigateway_go",
            "source_digest": task["source_digest"],
            "runtime": {},
        },
        status="ready",
    )
    runner = EvaluationRunner(ws, store, envs)
    monkeypatch.setattr(
        runner,
        "execute_task",
        lambda *args: {
            "stdout": "error",
            "exit_code": 0,
            "json": {"turns": [{"http_status": 500}]},
        },
    )
    run = runner.start(
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [task["version_id"]],
            "max_model_calls": 0,
        },
        background=False,
    )
    assert run["status"] == "failed"
    assert run["results"][0]["score"] is None
    assert run["results"][0]["status"] == "execution_error"
    assert run["results"][0]["observation"]["json"]["turns"][0]["http_status"] == 500


def test_environment_run_and_private_bridge_apis(client, project_root, monkeypatch):
    import time

    monkeypatch.setattr("evalith.environments.sandbox_available", lambda: True)
    pid, ws, store, assets, envs = fixture(client, project_root)
    task = assets.add(pid, definition())
    config = client.post(
        "/api/executor-configs",
        json={
            "name": "Echo",
            "backend": "local_command",
            "command": ["python3", "-c", "print(input())"],
            "timeout_seconds": 3,
        },
    ).json()
    plan = client.post(
        f"/api/projects/{pid}/environments/plan",
        json={"executor_config_id": config["id"]},
    )
    assert plan.status_code == 201, plan.text
    env = plan.json()
    assert (
        client.get(f"/api/projects/other/environments/{env['id']}").status_code == 404
    )
    prepared = client.post(
        f"/api/projects/{pid}/environments/{env['id']}/confirm",
        json={"plan_digest": env["plan_digest"]},
    )
    assert prepared.status_code == 202
    for _ in range(100):
        state = client.get(f"/api/projects/{pid}/environments/{env['id']}").json()
        if state["status"] in {"ready", "failed"}:
            break
        time.sleep(0.02)
    assert state["status"] == "ready", state
    monkeypatch.setattr(
        EvaluationRunner,
        "execute_task",
        lambda *args: {"stdout": "hello", "exit_code": 0, "json": None},
    )
    response = client.post(
        f"/api/projects/{pid}/runs",
        json={
            "environment_id": env["id"],
            "version_ids": [task["version_id"]],
            "max_model_calls": 0,
        },
    )
    assert response.status_code == 202, response.text
    run = response.json()
    assert "_bridge_token" not in run
    for _ in range(100):
        run = client.get(f"/api/projects/{pid}/runs/{run['id']}").json()
        if run["status"] == "completed":
            break
        time.sleep(0.02)
    assert run["results"][0]["status"] == "passed"
    assert client.get(f"/api/projects/{pid}/runs").json()["items"][0]["id"] == run["id"]
    assert (
        client.post(
            f"/api/projects/{pid}/runs/{run['id']}/model/v1/chat/completions", json={}
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/projects/{pid}/runs/{run['id']}/cancel").status_code == 409
    )


def test_command_sandbox_supports_unicode_paths_and_denies_outside_writes(tmp_path):
    from evalith.execution_process import bounded_process, sandbox_available

    if not sandbox_available():
        pytest.skip("macOS sandbox required")
    work = tmp_path / "中文目录"
    work.mkdir()
    (work / "stdin.txt").write_text("")
    outside = tmp_path / "outside.txt"
    program = 'import sqlite3,pathlib;sqlite3.connect("test.db").execute("create table x(a)");pathlib.Path("../outside.txt").write_text("bad")'
    result = bounded_process(["/usr/bin/python3", "-c", program], work, timeout=5)
    assert (work / "test.db").is_file()
    assert not outside.exists()
    assert result["exit_code"] != 0


def test_configured_api_port_accepts_same_origin_and_access_logs_keep_structure(
    settings,
):
    import logging
    from uvicorn.logging import AccessFormatter
    from evalith.security import RedactionFilter
    from evalith.api import create_app
    from fastapi.testclient import TestClient

    settings.api_port = 8093
    with TestClient(create_app(settings)) as alternate:
        assert (
            alternate.get(
                "/api/health", headers={"Origin": "http://127.0.0.1:8093"}
            ).status_code
            == 200
        )
        assert (
            alternate.get(
                "/api/health", headers={"Origin": "http://evil.example:8093"}
            ).status_code
            == 403
        )
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/?api_key=sk-log-abcdef1234", "1.1", 200),
        None,
    )
    RedactionFilter().filter(record)
    rendered = AccessFormatter("%(request_line)s %(status_code)s").format(record)
    assert "200" in rendered and "sk-log-abcdef1234" not in rendered


def test_scoring_failure_preserves_checks_and_does_not_erase_later_cases(
    client, project_root, monkeypatch
):
    from evalith.model_gateway import ModelError

    pid, ws, store, assets, envs = fixture(client, project_root)
    one = assets.add(
        pid,
        {
            **definition(),
            "checks": [
                {"type": "contains", "expected": "hello"},
                {"type": "judge", "expected": "Say hello"},
            ],
        },
    )
    two = assets.add(pid, definition())
    env = store.create(
        pid,
        "environment",
        {
            "adapter": "local_command",
            "source_digest": one["source_digest"],
            "runtime": {},
        },
        status="ready",
    )
    runner = EvaluationRunner(ws, store, envs)
    monkeypatch.setattr(
        runner,
        "execute_task",
        lambda *args: {"stdout": "hello", "json": None, "exit_code": 0},
    )
    original = runner._judge

    def judge(run, task, observation, checks):
        if task["task_id"] == one["id"]:
            raise ModelError("judge unavailable")
        return original(run, task, observation, checks)

    monkeypatch.setattr(runner, "_judge", judge)
    run = runner.start(
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [one["version_id"], two["version_id"]],
        },
        background=False,
    )
    assert run["status"] == "completed"
    assert (
        run["results"][0]["status"] == "review_required"
        and run["results"][0]["score"] is None
    )
    assert run["results"][0]["checks"][0]["status"] == "passed"
    assert run["results"][0]["observation"]["stdout"] == "hello"
    assert run["results"][1]["status"] == "passed"


def test_sandbox_cannot_read_unrelated_user_files(tmp_path):
    from evalith.execution_process import bounded_process, sandbox_available

    if not sandbox_available():
        pytest.skip("macOS sandbox required")
    work = tmp_path / "case"
    work.mkdir()
    (work / "stdin.txt").write_text("")
    secret = tmp_path / "unrelated.txt"
    secret.write_text("not-for-the-target")
    result = bounded_process(
        [
            "/usr/bin/python3",
            "-c",
            'from pathlib import Path;print(Path("../unrelated.txt").read_text())',
        ],
        work,
        timeout=5,
    )
    assert result["exit_code"] != 0 and "not-for-the-target" not in result["stdout"]


def test_actual_cancel_keeps_first_result_and_partial_output(client, project_root):
    import time
    from evalith.execution_process import sandbox_available

    if not sandbox_available():
        pytest.skip("macOS sandbox required")
    pid, ws, store, assets, envs = fixture(client, project_root)
    first = assets.add(pid, definition())
    second = assets.add(
        pid,
        {**definition(), "title": "Slow case", "input": {"stdin": "slow", "files": {}}},
    )
    config = client.post(
        "/api/executor-configs",
        json={
            "name": "Cancellable",
            "backend": "local_command",
            "command": [
                "/usr/bin/python3",
                "-c",
                'import sys,time;v=input();print(v,flush=True);time.sleep(10 if v=="slow" else 0)',
            ],
            "timeout_seconds": 15,
        },
    ).json()
    env = envs.plan(pid, {"executor_config_id": config["id"]})
    env = envs.confirm(pid, env["id"], env["plan_digest"], background=False)
    runner = EvaluationRunner(ws, store, envs)
    run = runner.start(
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [first["version_id"], second["version_id"]],
            "max_model_calls": 0,
        },
    )
    for _ in range(120):
        current = store.get(pid, "run", run["id"])
        if len(current["results"]) == 2:
            break
        time.sleep(0.02)
    time.sleep(0.15)
    runner.cancel(pid, run["id"])
    for _ in range(120):
        current = store.get(pid, "run", run["id"])
        if current["status"] == "cancelled":
            break
        time.sleep(0.02)
    assert current["status"] == "cancelled", current
    assert current["results"][0]["status"] == "passed"
    assert current["results"][1]["status"] == "cancelled"
    assert "slow" in current["results"][1]["observation"]["stdout"]
    assert current["results"][1]["observation"]["cleanup_status"] == "completed"
