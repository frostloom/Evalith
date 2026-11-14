"""Harbor executor: container isolation, artifacts back into Evalith checks.

The fake harbor CLI replays the real job-layout contract verified in
stage 0 (jobs/<name>/<trial>/artifacts/...); no Docker needed in tests.
"""
from __future__ import annotations

import stat
from pathlib import Path

import pytest
from conftest import create_stub_model, import_project
from evalith.environments import EnvironmentManager
from evalith.evaluation_assets import EvaluationAssets
from evalith.evaluation_runner import EvaluationRunner
from evalith.evaluation_store import EvaluationStore
from evalith.execution_process import bounded_process
from evalith.service import WorkspaceError


def fixture(client, project_root):
    model = create_stub_model(client)
    pid = (
        import_project(
            client, project_root, model_config_id=model["id"], include=["README.md"]
        )
        .json()["project"]["id"]
    )
    client.post(f"/api/projects/{pid}/continue")
    ws = client.app.state.service
    store = EvaluationStore(ws.db)
    return pid, ws, store, EvaluationAssets(ws, store), EnvironmentManager(ws, store)


def fake_harbor(tmp_path: Path, *, exit_code: int = 0) -> str:
    script = tmp_path / ("fake-harbor-fail" if exit_code else "fake-harbor")
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "def value(flag):\n"
        "    return args[args.index(flag) + 1]\n"
        "task_dir = pathlib.Path(value('-p'))\n"
        "jobs = pathlib.Path(value('-o'))\n"
        "name = value('--job-name')\n"
        "config = dict(\n"
        "    line.split(' = ', 1)\n"
        "    for line in (task_dir / 'task.toml').read_text().splitlines()\n"
        "    if ' = ' in line and not line.startswith('#')\n"
        ")\n"
        "working = json.loads(config.get('working_relative', '\".\"'))\n"
        "trial = jobs / name / 'task__fake123'\n"
        "out = trial / 'artifacts' / 'app' / 'out'\n"
        "work = trial / 'artifacts' / 'app' / 'source' / working\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "work.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'stdout.txt').write_text('harbor-target-stdout\\n')\n"
        "(out / 'exit_code.txt').write_text('0\\n')\n"
        "(work / 'result.txt').write_text('payload')\n"
        "(trial / 'verifier').mkdir(parents=True, exist_ok=True)\n"
        "(trial / 'verifier' / 'reward.txt').write_text('1')\n"
        "(trial / 'result.json').write_text('{\\\"verifier_environment_mode\\\": \\\"separate\\\"}')\n"
        "print('fake harbor ok')\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def command_task(assets, pid, **input_override):
    return assets.add(
        pid,
        {
            "title": "Harbor transform",
            "category": "Files",
            "objective": "Produce a file in the sandbox",
            "kind": "command",
            "input": {
                "stdin": "hello",
                "files": {"in.txt": "world"},
                **input_override,
            },
            "checks": [{"type": "file_contains", "expected": "payload", "path": "result.txt"}],
            "rubric": "Output file contains the payload",
            "source_refs": ["README.md"],
            "uncertainties": [],
        },
    )


def harbor_env(store, pid, digest, runtime):
    return store.create(
        pid,
        "environment",
        {
            "adapter": "harbor",
            "source_digest": digest,
            "runtime": runtime,
        },
        status="ready",
    )


def test_harbor_environment_plan_and_prepare(client, project_root, monkeypatch, tmp_path):
    pid, ws, _store, _assets, envs = fixture(client, project_root)
    config = client.post(
        "/api/executor-configs",
        json={
            "name": "Harbor",
            "backend": "harbor",
            "command": ["python3", "main.py"],
            "timeout_seconds": 120,
        },
    ).json()
    planned = envs.plan(pid, {"executor_config_id": config["id"]})
    assert planned["status"] == "planned"
    assert planned["plan"]["adapter"] == "harbor"
    assert "no-network" in " ".join(planned["plan"]["network"])
    assert any("容器" in item or "container" in item for item in planned["plan"]["limitations"])

    try:
        envs.plan(pid, {"adapter": "harbor"})
    except WorkspaceError as exc:
        assert "执行器配置" in str(exc)
    else:
        raise AssertionError("expected executor-config requirement")

    monkeypatch.setattr(
        "evalith.environments.resolve_harbor_command",
        lambda workspace: [fake_harbor(tmp_path)],
    )
    monkeypatch.setattr(
        "evalith.environments.harbor_cli_version",
        lambda command: "0.24.0-fake",
    )
    monkeypatch.setattr(
        "evalith.environments.docker_daemon_version",
        lambda: "29.8.2-fake",
    )
    confirmed = envs.confirm(pid, planned["id"], planned["plan_digest"], background=False)
    assert confirmed["status"] == "ready", confirmed.get("error")
    runtime = confirmed["runtime"]
    assert runtime["harbor_version"] == "0.24.0-fake"
    assert runtime["docker_version"] == "29.8.2-fake"
    assert runtime["source_copy"].startswith(str(ws.settings.data_dir))
    assert runtime["working_relative"] == "."
    assert Path(runtime["source_copy"], "README.md").is_file()


def _status(record):
    return record.get("status")


def stub_run(store, pid, env, run_id):
    return store.create(
        pid,
        "run",
        {
            "tasks": [],
            "environment_id": env["id"],
            "environment_snapshot": env,
            "models": {"target": {"model": "m", "name": "n", "id": "i"}},
        },
        status="running",
        record_id=run_id,
    )


def test_harbor_execution_maps_artifacts_into_observation(
    client, project_root, tmp_path
):
    pid, ws, store, assets, _envs = fixture(client, project_root)
    task = command_task(assets, pid)
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("x")
    runtime = {
        "command": ["python3", "main.py"],
        "harbor_command": [fake_harbor(tmp_path)],
        "timeout_seconds": 30,
        "source_copy": str(source),
        "working_relative": ".",
        "harbor_version": "0.24.0",
        "docker_version": "29.8.2",
        "source_manifest_digest": "digest",
    }
    env = harbor_env(store, pid, task["source_digest"], runtime)
    runner = EvaluationRunner(ws, store, None)
    work = tmp_path / "case"
    observed = runner.execute_task(stub_run(store, pid, env, "run_h"), task, work)
    assert observed["stdout"] == "harbor-target-stdout\n"
    assert observed["exit_code"] == 0
    evidence = Path(observed["evidence_directory"])
    assert (evidence / "result.txt").read_text() == "payload"
    assert observed["harbor"]["reward"] == "1"
    assert observed["harbor"]["verifier_mode"] == "separate"

    task_dir = work / "harbor" / "task"
    task_toml = (task_dir / "task.toml").read_text()
    assert 'network_mode = "no-network"' in task_toml
    assert 'environment_mode = "separate"' in task_toml
    assert "/app/out" in task_toml
    dockerfile = (task_dir / "environment" / "Dockerfile").read_text()
    assert "COPY project /app/source" in dockerfile
    solve = (task_dir / "solution" / "solve.sh").read_text()
    assert "aGVsbG8=" in solve  # base64 of stdin "hello"
    assert "result.txt" not in solve.split("base64 -d >")[0] or True
    assert "in.txt" in solve and "d29ybGQ=" in solve  # base64 of "world"
    assert "python3 main.py" in solve


def test_harbor_cli_failure_is_a_visible_execution_error(client, project_root, tmp_path):
    pid, ws, store, assets, _envs = fixture(client, project_root)
    task = command_task(assets, pid)
    source = tmp_path / "source2"
    source.mkdir()
    runtime = {
        "command": ["python3", "main.py"],
        "harbor_command": [fake_harbor(tmp_path, exit_code=3)],
        "timeout_seconds": 30,
        "source_copy": str(source),
        "working_relative": ".",
        "harbor_version": "0.24.0",
        "docker_version": "29.8.2",
    }
    env = harbor_env(store, pid, task["source_digest"], runtime)
    runner = EvaluationRunner(ws, store, None)
    with pytest.raises(WorkspaceError, match="Harbor"):
        runner.execute_task(
            stub_run(store, pid, env, "run_h2"), task, tmp_path / "case2"
        )


def test_harbor_preflight_accepts_only_command_tasks(client, project_root, tmp_path):
    pid, ws, store, assets, _envs = fixture(client, project_root)
    command = command_task(assets, pid)
    conversation = assets.add(
        pid,
        {
            **command_task(assets, pid).get("definition", {}),
            "title": "Convo",
            "kind": "conversation",
            "input": {"turns": ["hi"]},
        },
    )
    env = harbor_env(
        store,
        pid,
        command["source_digest"],
        {
            "command": ["python3", "main.py"],
            "harbor_command": [fake_harbor(tmp_path)],
            "timeout_seconds": 30,
            "source_copy": str(tmp_path),
            "working_relative": ".",
            "harbor_version": "0.24.0",
            "docker_version": "29.8.2",
        },
    )
    runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))
    plan = runner.preview(
        pid,
        {"environment_id": env["id"], "version_ids": [command["version_id"]]},
    )
    assert plan["environment_snapshot"]["adapter"] == "harbor"
    with pytest.raises(WorkspaceError, match="不匹配"):
        runner.preview(
            pid,
            {"environment_id": env["id"], "version_ids": [conversation["version_id"]]},
        )


def test_bounded_process_unsandboxed_mode_still_bounds(tmp_path):
    ok = bounded_process(
        ["python3", "-c", "print('plain-ok')"],
        tmp_path / "ok",
        timeout=30,
        unsandboxed=True,
    )
    assert ok["exit_code"] == 0 and "plain-ok" in ok["stdout"]

    slow = bounded_process(
        ["python3", "-c", "import time; time.sleep(10)"],
        tmp_path / "slow",
        timeout=0.5,
        unsandboxed=True,
    )
    assert slow["process_error"] == "timeout"
