"""Adaptive multi-turn conversation tasks.

Follow-up user turns are generated during execution from the live
transcript, through the run's simulator model with full call accounting.
"""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

from conftest import create_stub_model, import_project
from evalith.environments import EnvironmentManager
from evalith.evaluation_assets import EvaluationAssets
from evalith.evaluation_runner import EvaluationRunner
from evalith.evaluation_store import EvaluationStore
from evalith.model_gateway import ModelGateway
from evalith.service import WorkspaceError
from fastapi.testclient import TestClient


def fixture(client: TestClient, project_root: Path):
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
    real = client.post(
        "/api/model-configs",
        json={
            "name": "simulator",
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "model_name": "gpt-test",
        },
    ).json()
    return pid, ws, store, EvaluationAssets(ws, store), real


def adaptive_definition(title="Adaptive balance talk", **adaptive):
    return {
        "title": "Adaptive balance talk",
        "category": "Conversation",
        "objective": "Multi-turn balance inquiry",
        "kind": "conversation",
        "input": {
            "turns": ["你好，帮我查一下余额"],
            "adaptive": {
                "max_turns": 3,
                "instruction": "用户先查余额，得到金额后追问币种，然后结束",
                **adaptive,
            },
        },
        "checks": [{"type": "not_contains", "expected": "forbidden"}],
        "rubric": "Agent answers with tool-backed facts",
        "source_refs": ["README.md"],
        "uncertainties": [],
    }


def aigateway_env(store, pid, digest):
    return store.create(
        pid,
        "environment",
        {
            "adapter": "aigateway_go",
            "source_digest": digest,
            "runtime": {"timeout_seconds": 60},
        },
        status="ready",
    )


def test_adaptive_definition_validation(client, project_root):
    pid, _ws, _store, assets, _real = fixture(client, project_root)
    added = assets.add(pid, adaptive_definition())
    assert added["definition"]["input"]["adaptive"]["max_turns"] == 3

    two_openings = adaptive_definition()
    two_openings["input"]["turns"] = ["a", "b"]
    for index, bad_input in enumerate((two_openings["input"], None)):
        candidate = adaptive_definition(title=f"Bad shape {index}")
        if bad_input is None:
            candidate["input"].pop("turns")
        else:
            candidate["input"] = bad_input
        try:
            assets.add(pid, candidate)
            raise AssertionError("expected rejection")
        except WorkspaceError:
            pass
    for bad in (
        {"max_turns": 1},
        {"max_turns": 13},
        {"instruction": " "},
        {"instruction": "x" * 2001},
        {"simulator_model_config_id": 5},
        {"unknown": 1},
    ):
        try:
            assets.add(pid, adaptive_definition(title="Bad field", **bad))
            raise AssertionError("expected rejection")
        except WorkspaceError:
            pass


def test_preflight_resolves_and_rejects_simulator_setups(client, project_root):
    pid, ws, store, assets, real = fixture(client, project_root)
    task = assets.add(pid, adaptive_definition())
    env = aigateway_env(store, pid, task["source_digest"])
    runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))

    plan = runner.preview(
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [task["version_id"]],
            "simulator_model_config_id": real["id"],
        },
    )
    assert plan["models"]["simulator"]["id"] == real["id"]

    task_sim = assets.add(
        pid, adaptive_definition(simulator_model_config_id=real["id"])
    )
    plan = runner.preview(
        pid,
        {
            "environment_id": aigateway_env(store, pid, task_sim["source_digest"])["id"],
            "version_ids": [task_sim["version_id"]],
        },
    )
    assert plan["models"]["simulator"]["id"] == real["id"]

    stub_plan_error = None
    try:
        runner.preview(
            pid,
            {"environment_id": env["id"], "version_ids": [task["version_id"]]},
        )
    except WorkspaceError as exc:
        stub_plan_error = exc
    assert stub_plan_error is not None and "离线" in str(stub_plan_error)

    other_real = client.post(
        "/api/model-configs",
        json={
            "name": "other",
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "model_name": "gpt-other",
        },
    ).json()
    task_other = assets.add(
        pid,
        adaptive_definition(simulator_model_config_id=other_real["id"], title="Second task"),
    )
    try:
        runner.preview(
            pid,
            {
                "environment_id": aigateway_env(store, pid, task_other["source_digest"])[
                    "id"
                ],
                "version_ids": [task_sim["version_id"], task_other["version_id"]],
            },
        )
        raise AssertionError("expected conflict rejection")
    except WorkspaceError as exc:
        assert "不同" in str(exc) or "冲突" in str(exc)


def _running_run(ws, store, pid, task, simulator_id, *, max_calls=5):
    gateway = ws.gateway_for(simulator_id)
    plan = {
        "tasks": [task],
        "models": {
            "simulator": {
                "id": simulator_id,
                "name": gateway.name,
                "model": gateway.config.model_name,
            }
        },
        "_model_fingerprints": {"simulator": EvaluationRunner.model_fingerprint(gateway)},
        "budget": {"max_model_calls": max_calls, "budget_usd": None},
        "usage": {"model_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": None},
        "_bridge_token": ws.cipher.encrypt(secrets.token_urlsafe(32)),
        "calls": [],
        "results": [],
    }
    return store.create(pid, "run", plan, status="running")


def test_simulator_endpoint_contract(client, project_root, monkeypatch):
    pid, ws, store, assets, real = fixture(client, project_root)
    task = assets.add(pid, adaptive_definition())
    run = _running_run(ws, store, pid, task, real["id"])
    token = ws.cipher.decrypt(run["_bridge_token"])
    url = f"/api/projects/{pid}/runs/{run['id']}/simulator/v1"
    body = {
        "task_id": task["task_id"],
        "turns_executed": 1,
        "transcript": [{"input": "你好", "reply": "余额是 100"}],
    }

    denied = client.post(url, json=body, headers={"Authorization": "Bearer wrong"})
    assert denied.status_code == 403

    capped = client.post(
        url,
        json={**body, "turns_executed": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert capped.status_code == 200 and capped.json() == {"message": "", "end": True}
    assert store.get(pid, "run", run["id"])["calls"] == []

    def fake(self, system, payload):
        assert "instruction" in payload and payload["transcript"]
        return {"message": "是人民币吗？", "end": False}

    monkeypatch.setattr(ModelGateway, "complete_json", fake)
    ok = client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"message": "是人民币吗？", "end": False}
    refreshed = store.get(pid, "run", run["id"])
    assert len(refreshed["calls"]) == 1
    assert refreshed["calls"][0]["purpose"] == "simulator"

    def malformed(self, system, payload):
        return {"message": "", "end": False}

    monkeypatch.setattr(ModelGateway, "complete_json", malformed)
    bad = client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
    assert bad.status_code == 502
    assert "模拟器" in bad.json()["error"]["message"]

    unknown = client.post(
        url,
        json={**body, "task_id": "missing"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unknown.status_code == 422

    broke = _running_run(ws, store, pid, task, real["id"], max_calls=0)
    stopped = client.post(
        f"/api/projects/{pid}/runs/{broke['id']}/simulator/v1",
        json=body,
        headers={"Authorization": f"Bearer {ws.cipher.decrypt(broke['_bridge_token'])}"},
    )
    assert stopped.status_code == 429


def test_execute_task_passes_simulator_env_only_for_adaptive(
    client, project_root, monkeypatch, tmp_path
):
    pid, ws, store, assets, _real = fixture(client, project_root)
    adaptive = assets.add(pid, adaptive_definition())
    scripted = assets.add(
        pid,
        {
            **adaptive_definition(),
            "title": "Scripted",
            "input": {"turns": ["a", "b"]},
        },
    )
    binary = tmp_path / "adapter"
    binary.write_bytes(b"fake")
    runtime = {
        "binary": str(binary),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "timeout_seconds": 5,
    }
    captured = {}

    def fake_process(command, cwd, **kwargs):
        captured.update(kwargs.get("env") or {})
        return {"stdout": "{}", "exit_code": 0}

    monkeypatch.setattr(
        "evalith.evaluation_runner.bounded_process", fake_process
    )
    run = {
        "project_id": pid,
        "id": "run_test",
        "environment_snapshot": {"adapter": "aigateway_go", "runtime": runtime},
        "models": {"target": {"model": "gpt-test", "name": "x", "id": "m"}},
        "_bridge_token": ws.cipher.encrypt(secrets.token_urlsafe(16)),
    }
    runner = EvaluationRunner(ws, store, None)
    runner.execute_task(run, adaptive, tmp_path)
    assert "EVALITH_SIMULATOR_URL" in captured
    assert captured["EVALITH_TASK_ID"] == adaptive["task_id"]
    assert captured["EVALITH_SIMULATOR_URL"].endswith(
        "/runs/run_test/simulator/v1"
    )

    captured.clear()
    runner.execute_task(run, scripted, tmp_path)
    assert "EVALITH_SIMULATOR_URL" not in captured
    assert "EVALITH_TASK_ID" not in captured
