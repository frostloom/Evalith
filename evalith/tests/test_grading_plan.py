import pytest
from evalith.environments import EnvironmentManager
from evalith.evaluation_assets import EvaluationAssets
from evalith.evaluation_library import EvaluationLibrary
from evalith.evaluation_runner import EvaluationRunner
from evalith.service import WorkspaceError
from test_evaluation_library import setup


def configured(client, root):
    pid, _model, ws, store, task = setup(client, root)
    library = EvaluationLibrary(ws, store)
    first = library.save_grader(
        pid,
        {
            "name": "Greeting",
            "rubric": "Say hello",
            "check": {"type": "contains", "expected": "hello"},
            "task_kinds": ["command"],
        },
    )
    other = library.save_grader(
        pid,
        {
            "name": "No forbidden content",
            "rubric": "Do not emit forbidden",
            "check": {"type": "not_contains", "expected": "forbidden"},
            "task_kinds": ["command"],
        },
    )
    task = store.save_task(
        pid, {**task, "default_grader_ids": [first["id"]]}, task_id=task["id"]
    )
    task2 = EvaluationAssets(ws, store).add(
        pid, {**task["definition"], "title": "Other case"}
    )
    task2 = store.save_task(
        pid, {**task2, "default_grader_ids": [other["id"]]}, task_id=task2["id"]
    )
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
        "version_ids": [task["version_id"], task2["version_id"]],
        "max_model_calls": 0,
    }
    return pid, store, library, runner, payload, first, other


def test_each_task_executes_its_own_frozen_default_grader(
    client, project_root, monkeypatch
):
    pid, _store, library, runner, payload, first, other = configured(
        client, project_root
    )

    def execute(run, task, work):
        library.save_grader(
            pid,
            {
                "name": "Greeting",
                "rubric": "New rubric",
                "check": {"type": "contains", "expected": "changed"},
            },
            first["id"],
        )
        return {"stdout": "hello", "exit_code": 0}

    monkeypatch.setattr(runner, "execute_task", execute)
    run = runner.start(pid, payload, background=False)
    assert run["status"] == "completed"
    assert [[c.get("grader_id") for c in r["checks"]] for r in run["results"]] == [
        [first["id"]],
        [other["id"]],
    ]
    assert all(r["status"] == "passed" for r in run["results"])
    assert run["graders"][0]["rubric"] == "Say hello"
    assert len(run["grading_plan"]["tasks"]) == 2


def test_preview_is_read_only_and_resolution_obeys_override_precedence(
    client, project_root
):
    pid, store, library, runner, payload, first, other = configured(
        client, project_root
    )
    tids = [store.task_version(pid, v)["task_id"] for v in payload["version_ids"]]
    collection = library.save_set(
        pid, {"name": "Override", "task_ids": tids, "grader_ids": [other["id"]]}
    )
    preview = runner.preview(pid, {**payload, "test_set_id": collection["id"]})
    assert [p["source"] for p in preview["grading_plan"]["tasks"]] == [
        "test_set",
        "test_set",
    ]
    assert [g["id"] for g in preview["graders"]] == [other["id"]]
    embedded = runner.preview(
        pid, {**payload, "test_set_id": collection["id"], "grader_ids": []}
    )
    assert all(p["source"] == "embedded" for p in embedded["grading_plan"]["tasks"])
    assert not embedded["graders"] and not store.list(pid, "run")
    explicit = runner.preview(
        pid, {**payload, "test_set_id": collection["id"], "grader_ids": [first["id"]]}
    )
    assert all(p["source"] == "run" for p in explicit["grading_plan"]["tasks"])


def test_no_applicable_and_archived_default_are_rejected_before_run(
    client, project_root
):
    pid, store, library, runner, payload, first, _other = configured(
        client, project_root
    )
    conversation = library.save_grader(
        pid,
        {
            "name": "Conversation only",
            "rubric": "Check conversation",
            "check": {"type": "judge", "expected": "Read transcript"},
            "task_kinds": ["conversation"],
        },
    )
    with pytest.raises(WorkspaceError) as error:
        runner.start(
            pid, {**payload, "grader_ids": [conversation["id"]]}, background=False
        )
    assert error.value.status_code == 422 and not store.list(pid, "run")
    store.update(pid, "grader", first["id"], status="archived")
    with pytest.raises(WorkspaceError) as error:
        runner.start(pid, payload, background=False)
    assert error.value.status_code == 409 and not store.list(pid, "run")


def test_incompatible_grader_is_visible_in_plan_but_not_applied(client, project_root):
    pid, _store, library, runner, payload, first, _other = configured(
        client, project_root
    )
    conversation = library.save_grader(
        pid,
        {
            "name": "Transcript only",
            "rubric": "Check conversation",
            "check": {"type": "judge", "expected": "Read transcript"},
            "task_kinds": ["conversation"],
        },
    )
    preview = runner.preview(
        pid, {**payload, "grader_ids": [first["id"], conversation["id"]]}
    )
    for task in preview["grading_plan"]["tasks"]:
        assert [c["grader_id"] for c in task["checks"]] == [first["id"]]
        assert task["not_applicable"][0]["grader_id"] == conversation["id"]


def test_reviewed_plan_digest_rejects_changed_grader_configuration(
    client, project_root
):
    pid, store, library, runner, payload, first, _ = configured(client, project_root)
    preview = runner.preview(pid, payload)
    library.save_grader(
        pid,
        {
            "name": "Greeting",
            "rubric": "Changed criteria",
            "check": {"type": "contains", "expected": "new"},
        },
        first["id"],
    )
    with pytest.raises(WorkspaceError) as error:
        runner.start(
            pid, {**payload, "plan_digest": preview["plan_digest"]}, background=False
        )
    assert error.value.code == "grading_plan_changed" and not store.list(pid, "run")
