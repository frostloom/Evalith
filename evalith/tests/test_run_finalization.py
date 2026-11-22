"""Review 2026-11-21 R3/R4: run finalization must be crash-proof and
race-proof.

R3: an unexpected failure below the per-task handlers settles the run
as failed instead of leaving it stuck in ``running`` forever.

R4: the terminal write is compare-and-swap — an already-terminal run
(a restart-recovered ``interrupted`` run, or another instance's
verdict) is never overwritten, and a cancellation that lands mid-flight
wins over whatever the worker was about to report.
"""

import pytest
from conftest import create_stub_model, import_project
from evalith.environments import EnvironmentManager
from evalith.evaluation_runner import EvaluationRunner
from evalith.evaluation_store import EvaluationStore


def make_run(client, project_root, *, status="running", tasks=None):
    model = create_stub_model(client)
    pid = import_project(
        client, project_root, model_config_id=model["id"], include=["README.md"]
    ).json()["project"]["id"]
    ws = client.app.state.service
    store = EvaluationStore(ws.db)
    run = store.create(
        pid,
        "run",
        {
            "models": {},
            "tasks": tasks or [],
            "results": [],
            "calls": [],
            "budget": {"max_model_calls": 0, "budget_usd": None},
            "usage": {},
        },
        status=status,
    )
    runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))
    return pid, store, runner, run


class TestFinalizeIsCas:
    def test_completed_over_running(self, client, project_root):
        pid, store, runner, run = make_run(client, project_root)
        final = runner.finalize_run(pid, run["id"], "completed", None, "completed")
        assert final["status"] == "completed"

    def test_cancel_wins_over_completed(self, client, project_root):
        pid, store, runner, run = make_run(client, project_root, status="cancelling")
        final = runner.finalize_run(pid, run["id"], "completed", None, "completed")
        assert final["status"] == "cancelled"

    def test_terminal_states_are_never_overwritten(self, client, project_root):
        pid, store, runner, run = make_run(client, project_root, status="interrupted")
        final = runner.finalize_run(pid, run["id"], "completed", None, "completed")
        assert final["status"] == "interrupted"

    def test_failure_still_records_over_running(self, client, project_root):
        pid, store, runner, run = make_run(client, project_root)
        final = runner.finalize_run(pid, run["id"], "failed", "boom", "completed")
        assert final["status"] == "failed"
        assert final["error"] == "boom"


class TestThreadGuard:
    TASK = {
        "task_id": "t1",
        "definition": {
            "title": "T",
            "category": "C",
            "objective": "O",
            "kind": "command",
            "input": {},
            "checks": [],
            "rubric": "",
            "source_refs": [],
            "uncertainties": [],
        },
    }

    def test_unexpected_tail_failure_settles_the_run(
        self, client, project_root, monkeypatch
    ):
        pid, store, runner, run = make_run(client, project_root, tasks=[dict(self.TASK)])
        monkeypatch.setattr(
            EvaluationRunner,
            "execute_task",
            lambda *a, **k: {
                "stdout": "ok",
                "exit_code": 0,
                "json": None,
                "cleanup_status": "completed",
                "duration_ms": 1,
            },
        )
        calls = {"n": 0}

        def flaky_save(self_, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:  # the tail write, outside per-task handlers
                raise RuntimeError("sqlite disk full")
            return {}

        monkeypatch.setattr(EvaluationRunner, "_save_result", flaky_save)
        runner._run(pid, run["id"])  # must not raise
        final = store.get(pid, "run", run["id"])
        assert final["status"] == "failed"
        assert "内部错误" in (final["error"] or "")
