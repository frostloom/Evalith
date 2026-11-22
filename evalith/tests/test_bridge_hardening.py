"""Review 2026-11-21 R6: the model bridge must bound request bodies and
survive hostile Authorization headers.

The bridge is called by sandboxed target code holding a bearer token.
Without a request-size cap, a defective target can stream hundreds of
megabytes and exhaust orchestrator memory during parsing — the budget
check only runs after the body is read. And a non-ASCII Authorization
header reached ``secrets.compare_digest(str, str)``, which raises
TypeError and turns into a 500.
"""

from test_evaluation_runs import definition, fixture


def _ready_run(client, project_root, monkeypatch, task=None):
    import time

    monkeypatch.setattr("evalith.environments.sandbox_available", lambda: True)
    pid, ws, store, assets, envs = fixture(client, project_root)
    task = task or assets.add(pid, definition())
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
    response = client.post(
        f"/api/projects/{pid}/runs",
        json={
            "environment_id": env["id"],
            "version_ids": [task["version_id"]],
            "max_model_calls": 0,
        },
    )
    assert response.status_code == 202, response.text
    return pid, response.json()


class TestBridgeBodyLimit:
    def test_oversized_body_is_rejected_not_buffered(self, client, project_root, monkeypatch):
        pid, run = _ready_run(client, project_root, monkeypatch)
        huge = {"messages": [{"role": "user", "content": "x" * (12 * 1024 * 1024)}]}
        response = client.post(
            f"/api/projects/{pid}/runs/{run['id']}/model/v1/chat/completions",
            json=huge,
        )
        assert response.status_code == 413, response.status_code
        assert "error" in response.json()

    def test_normal_bodies_are_unaffected(self, client, project_root, monkeypatch):
        pid, run = _ready_run(client, project_root, monkeypatch)
        response = client.post(
            f"/api/projects/{pid}/runs/{run['id']}/model/v1/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 403, response.status_code


class TestAuthorizationRobustness:
    """httpx refuses to put non-ASCII bytes on the wire as a header, so the
    hostile-header path is pinned at the comparison itself, where the 500
    used to originate (compare_digest(str, str) raises TypeError)."""

    def test_non_ascii_token_is_rejected_not_raised(self, client, project_root):
        import pytest
        from evalith.evaluation_runner import EvaluationRunner
        from evalith.service import WorkspaceError

        pid, ws, store, assets, envs = fixture(client, project_root)
        runner = EvaluationRunner(ws, store, envs)
        run = {"_bridge_token": ws.cipher.encrypt("real-token")}

        with pytest.raises(WorkspaceError) as raised:
            runner._require_bridge_token(run, "令牌不是ASCII")
        assert raised.value.status_code == 403

    def test_ascii_wrong_token_still_403(self, client, project_root):
        import pytest
        from evalith.evaluation_runner import EvaluationRunner
        from evalith.service import WorkspaceError

        pid, ws, store, assets, envs = fixture(client, project_root)
        runner = EvaluationRunner(ws, store, envs)
        run = {"_bridge_token": ws.cipher.encrypt("real-token")}

        with pytest.raises(WorkspaceError) as raised:
            runner._require_bridge_token(run, "wrong-token")
        assert raised.value.status_code == 403

    def test_correct_token_passes(self, client, project_root):
        from evalith.evaluation_runner import EvaluationRunner

        pid, ws, store, assets, envs = fixture(client, project_root)
        runner = EvaluationRunner(ws, store, envs)
        run = {"_bridge_token": ws.cipher.encrypt("real-token")}
        runner._require_bridge_token(run, "real-token")
