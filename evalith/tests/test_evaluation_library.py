import pytest
from conftest import create_stub_model, import_project
from evalith.environments import EnvironmentManager
from evalith.evaluation_assets import EvaluationAssets
from evalith.evaluation_runner import EvaluationRunner
from evalith.evaluation_store import EvaluationStore
from evalith.model_gateway import ModelGateway
from evalith.service import WorkspaceError


def setup(client, root):
    model = create_stub_model(client)
    pid = import_project(
        client, root, model_config_id=model["id"], include=["README.md"]
    ).json()["project"]["id"]
    client.post(f"/api/projects/{pid}/continue")
    ws = client.app.state.service
    store = EvaluationStore(ws.db)
    task = EvaluationAssets(ws, store).add(
        pid,
        {
            "title": "Hello",
            "category": "Conversation",
            "objective": "Say hello",
            "kind": "command",
            "input": {"stdin": "hello"},
            "checks": [{"type": "contains", "expected": "hello"}],
            "rubric": "Say hello",
            "source_refs": ["README.md"],
            "uncertainties": [],
        },
    )
    return pid, model, ws, store, task


def grader(model):
    return {
        "name": "Answer correctness",
        "description": "Check evidence",
        "rubric": "Answer must match the observed facts",
        "steps": ["Read evidence", "Compare answer"],
        "check": {"type": "judge", "expected": "Match facts"},
        "model_config_id": model["id"],
        "threshold": 0.9,
    }


@pytest.mark.parametrize("malformed", ["judge", ["judge"], 42, True])
def test_malformed_check_returns_validation_error_instead_of_crashing(
    client, project_root, malformed
):
    pid, model, _ws, _store, _task = setup(client, project_root)
    response = client.post(
        f"/api/projects/{pid}/graders", json={**grader(model), "check": malformed}
    )
    assert response.status_code == 422


def test_standard_and_set_apis_validate_scope_and_persist_configuration(
    client, project_root
):
    pid, model, _ws, _store, task = setup(client, project_root)
    base = f"/api/projects/{pid}"
    response = client.post(base + "/graders", json=grader(model))
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["version"] == 1
    changed = client.put(
        base + "/graders/" + saved["id"], json={**grader(model), "threshold": 0.6}
    ).json()
    assert changed["version"] == 2
    assert client.get("/api/projects/other/graders/" + saved["id"]).status_code == 404
    assert (
        client.post(
            base + "/graders", json={**grader(model), "name": "Invalid", "threshold": 2}
        ).status_code
        == 422
    )
    collection = client.post(
        base + "/test-sets",
        json={
            "name": "Smoke",
            "description": "Small batch",
            "task_ids": [task["id"]],
            "grader_ids": [saved["id"]],
        },
    )
    assert collection.status_code == 201, collection.text
    assert client.get(base + "/test-sets").json()["items"][0]["task_ids"] == [
        task["id"]
    ]
    assert (
        client.post(
            base + "/test-sets",
            json={"name": "Foreign", "task_ids": ["outside"], "grader_ids": []},
        ).status_code
        == 404
    )
    assert client.delete(base + "/graders/" + saved["id"]).status_code == 204
    assert (
        client.post(
            base + "/test-sets",
            json={
                "name": "Archived",
                "task_ids": [task["id"]],
                "grader_ids": [saved["id"]],
            },
        ).status_code
        == 409
    )


def test_run_freezes_standard_threshold_model_and_rubric(
    client, project_root, monkeypatch
):
    pid, model, ws, store, task = setup(client, project_root)
    base = f"/api/projects/{pid}"
    standard = client.post(base + "/graders", json=grader(model)).json()
    assert "id" in standard, standard
    env = store.create(
        pid,
        "environment",
        {
            "adapter": "local_command",
            "source_digest": task["source_digest"],
            "runtime": {},
        },
        status="ready",
    )
    runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))
    captured = []

    def execute(run, task, work):
        client.put(
            base + "/graders/" + standard["id"],
            json={**grader(model), "threshold": 0.5, "rubric": "New rules"},
        )
        return {"stdout": "hello", "json": None, "exit_code": 0}

    def reply(self, system, payload):
        captured.append(payload)
        return {
            "checks": [
                {
                    "index": 0,
                    "passed": True,
                    "score": 0.8,
                    "reason": "Mostly correct",
                    "evidence": ["hello"],
                    "limitations": [],
                }
            ]
        }

    monkeypatch.setattr(runner, "execute_task", execute)
    monkeypatch.setattr(ModelGateway, "complete_json", reply)
    run = runner.start(
        pid,
        {
            "environment_id": env["id"],
            "version_ids": [task["version_id"]],
            "grader_ids": [standard["id"]],
            "max_model_calls": 1,
        },
        background=False,
    )
    assert run["status"] == "completed", run
    assert run["graders"][0]["threshold"] == 0.9 and run["graders"][0]["version"] == 1
    assert run["results"][0]["status"] == "failed"
    assert run["results"][0]["checks"][0]["grader_name"] == "Answer correctness"
    assert "observed facts" in str(captured[0]["criteria"])
    assert run["usage"]["model_calls"] == 1


def test_run_binds_set_membership_and_freezes_collection(
    client, project_root, monkeypatch
):
    pid, _model, ws, store, task = setup(client, project_root)
    base = f"/api/projects/{pid}"
    auto = client.get(base + "/test-sets").json()["items"][0]
    assert auto["task_ids"] == [task["id"]]
    collection = client.put(
        base + "/test-sets/" + auto["id"],
        json={"name": "Core regression", "task_ids": [task["id"]], "grader_ids": []},
    ).json()
    assert collection["id"] == auto["id"]
    assert len(client.get(base + "/test-sets").json()["items"]) == 1
    env = store.create(
        pid,
        "environment",
        {
            "adapter": "local_command",
            "source_digest": task["source_digest"],
            "runtime": {},
        },
        status="ready",
    )
    runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))
    payload = {
        "environment_id": env["id"],
        "version_ids": [task["version_id"]],
        "test_set_id": collection["id"],
        "max_model_calls": 0,
    }

    def execute(run, case, work):
        client.put(
            base + "/test-sets/" + auto["id"],
            json={"name": "Changed later", "task_ids": [task["id"]], "grader_ids": []},
        )
        return {"stdout": "hello", "json": None, "exit_code": 0}

    monkeypatch.setattr(runner, "execute_task", execute)
    run = runner.start(pid, payload, background=False)
    assert run["name"] == "Core regression"
    assert run["test_set_snapshot"]["name"] == "Core regression"
    assert run["test_set_snapshot"]["task_ids"] == [task["id"]]
    for invalid in [0, False, "", " " * 2]:
        with pytest.raises(WorkspaceError) as error:
            runner.start(pid, {**payload, "name": invalid}, background=False)
        assert error.value.status_code == 422
    # A real version outside the chosen collection must be rejected before execution.
    store.update(pid, "test_set", collection["id"], task_ids=[])
    with pytest.raises(WorkspaceError) as error:
        runner.start(pid, payload, background=False)
    assert error.value.status_code == 422
