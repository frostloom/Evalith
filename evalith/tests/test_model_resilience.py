"""Review 2026-11-21 D1: transient model-service failures must not
permanently destroy paid work.

Three gates:

1. ``ModelGateway`` retries idempotent chat requests on connect errors,
   429 and 5xx with bounded exponential backoff (and honours the
   cancellation check between attempts) instead of failing on the
   first blip.
2. A failed model call no longer consumes the ``max_model_calls``
   budget: the cap counts calls that did not fail, while the ledger
   keeps every attempt for audit.
3. ``rejudge`` re-runs grading for ``review_required`` results of a
   finished run against the frozen observations — the target is never
   re-executed, so already-paid execution is recoverable.
"""

import json

import httpx
import pytest
from conftest import create_stub_model, import_project
from evalith.environments import EnvironmentManager
from evalith.evaluation_store import EvaluationStore
from evalith.model_gateway import ModelError, ModelGateway


def make_gateway():
    from evalith.model_gateway import ModelConfig

    return ModelGateway(
        ModelConfig(
            id=1,
            name="svc",
            provider="openai_compatible",
            base_url="http://127.0.0.1:9/v1",
            model_name="m",
            api_key="k",
        )
    )


def ok_response(content='{"answer": 1}'):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "usage": {}},
    )


class TestGatewayRetry:
    def test_connect_error_then_success_retries(self, monkeypatch):
        calls = []
        attempts = [httpx.ConnectError("boom"), ok_response()]

        def fake_post(*args, **kwargs):
            calls.append(1)
            step = attempts[len(calls) - 1]
            if isinstance(step, Exception):
                raise step
            return step

        monkeypatch.setattr("evalith.model_gateway.httpx.post", fake_post)
        monkeypatch.setattr("evalith.model_gateway.time.sleep", lambda s: None)
        result = make_gateway().complete_json("sys", {"q": 1})
        assert result == {"answer": 1}
        assert len(calls) == 2

    def test_429_then_success_retries(self, monkeypatch):
        calls = []
        attempts = [httpx.Response(429, text="slow down"), ok_response()]

        def fake_post(*args, **kwargs):
            calls.append(1)
            step = attempts[len(calls) - 1]
            return step

        monkeypatch.setattr("evalith.model_gateway.httpx.post", fake_post)
        monkeypatch.setattr("evalith.model_gateway.time.sleep", lambda s: None)
        assert make_gateway().complete_json("sys", {"q": 1}) == {"answer": 1}
        assert len(calls) == 2

    def test_400_does_not_retry(self, monkeypatch):
        calls = []

        def fake_post(*args, **kwargs):
            calls.append(1)
            return httpx.Response(400, text="bad request")

        monkeypatch.setattr("evalith.model_gateway.httpx.post", fake_post)
        with pytest.raises(ModelError):
            make_gateway().complete_json("sys", {"q": 1})
        assert len(calls) == 1

    def test_exhausted_retries_raise_model_error(self, monkeypatch):
        calls = []

        def fake_post(*args, **kwargs):
            calls.append(1)
            return httpx.Response(503, text="down")

        monkeypatch.setattr("evalith.model_gateway.httpx.post", fake_post)
        monkeypatch.setattr("evalith.model_gateway.time.sleep", lambda s: None)
        with pytest.raises(ModelError):
            make_gateway().complete_json("sys", {"q": 1})
        assert len(calls) == 3

    def test_cancel_check_stops_retrying(self, monkeypatch):
        calls = []

        def fake_post(*args, **kwargs):
            calls.append(1)
            return httpx.Response(503, text="down")

        gateway = make_gateway()
        gateway.cancel_check = lambda: True
        monkeypatch.setattr("evalith.model_gateway.httpx.post", fake_post)
        monkeypatch.setattr("evalith.model_gateway.time.sleep", lambda s: None)
        with pytest.raises(ModelError):
            gateway.complete_json("sys", {"q": 1})
        assert len(calls) == 1


class TestFailedCallBudgetRefund:
    def test_failed_call_does_not_consume_the_cap(self, client, project_root):
        from evalith.evaluation_runner import BudgetStop, EvaluationRunner

        model = create_stub_model(client)
        pid = import_project(
            client, project_root, model_config_id=model["id"], include=["README.md"]
        ).json()["project"]["id"]
        ws = client.app.state.service
        store = EvaluationStore(ws.db)
        run = store.create(pid, "run", {
                    "models": {},
                    "tasks": [],
                    "results": [],
                    "calls": [],
                    "budget": {"max_model_calls": 1, "budget_usd": None},
                    "usage": {},
                }, status="running")
        runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))
        first = runner.reserve_call(pid, run["id"], "judge")
        runner._finish_call(pid, run["id"], first, {}, "transient failure")
        # The failed attempt is refunded: a second reserve must fit the cap.
        second = runner.reserve_call(pid, run["id"], "judge")
        runner._finish_call(pid, run["id"], second, {}, None)
        with pytest.raises(BudgetStop):
            runner.reserve_call(pid, run["id"], "judge")

    def test_successful_calls_still_consume_the_cap(self, client, project_root):
        from evalith.evaluation_runner import BudgetStop, EvaluationRunner

        model = create_stub_model(client)
        pid = import_project(
            client, project_root, model_config_id=model["id"], include=["README.md"]
        ).json()["project"]["id"]
        ws = client.app.state.service
        store = EvaluationStore(ws.db)
        run = store.create(pid, "run", {
                    "models": {},
                    "tasks": [],
                    "results": [],
                    "calls": [],
                    "budget": {"max_model_calls": 1, "budget_usd": None},
                    "usage": {},
                }, status="running")
        runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))
        call = runner.reserve_call(pid, run["id"], "judge")
        runner._finish_call(pid, run["id"], call, {}, None)
        with pytest.raises(BudgetStop):
            runner.reserve_call(pid, run["id"], "judge")


class TestRejudge:
    def _finished_run_with_unscored_result(self, client, project_root):
        model = create_stub_model(client)
        pid = import_project(
            client, project_root, model_config_id=model["id"], include=["README.md"]
        ).json()["project"]["id"]
        ws = client.app.state.service
        store = EvaluationStore(ws.db)
        result = {
            "id": "result_a",
            "task": {"task_id": "t1", "definition": {"title": "T"}},
            "status": "review_required",
            "score": None,
            "error": "评分调用失败：upstream 503",
            "checks": [{"type": "judge", "status": "needs_judge", "model_role": "judge"}],
            "observation": {"stdout": "evidence"},
        }
        run = store.create(pid, "run", {
                    "models": {"judge": {"id": model["id"], "name": model["name"], "model": "stub"}},
                    "tasks": [],
                    "results": [result],
                    "calls": [],
                    "budget": {"max_model_calls": 5, "budget_usd": None},
                    "usage": {},
                }, status="completed")
        return pid, ws, store, run

    def test_rejudge_rescores_frozen_observation(self, client, project_root, monkeypatch):
        from evalith.evaluation_runner import EvaluationRunner

        pid, ws, store, run = self._finished_run_with_unscored_result(client, project_root)
        runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))

        def fake_judge(runner_self, run_arg, task, observation, verification, **kwargs):
            for check in verification["checks"]:
                check.update(status="passed", score=1)
            verification.update(status="passed", score=1)
            return verification

        monkeypatch.setattr(EvaluationRunner, "_judge", fake_judge)
        updated = runner.rejudge(pid, run["id"])
        stored = store.get(pid, "run", run["id"])
        assert stored["results"][0]["status"] == "passed"
        assert stored["results"][0]["score"] == 1
        assert stored["results"][0]["error"] is None
        assert updated["results"][0]["status"] == "passed"

    def test_rejudge_rejects_running_runs(self, client, project_root):
        from evalith.evaluation_runner import EvaluationRunner
        from evalith.service import WorkspaceError

        pid, ws, store, run = self._finished_run_with_unscored_result(client, project_root)
        store.update(pid, "run", run["id"], status="running")
        runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))
        with pytest.raises(WorkspaceError):
            runner.rejudge(pid, run["id"])

    def test_rejudge_without_candidates_is_rejected(self, client, project_root):
        from evalith.evaluation_runner import EvaluationRunner
        from evalith.service import WorkspaceError

        pid, ws, store, run = self._finished_run_with_unscored_result(client, project_root)
        store.mutate(
            pid,
            "run",
            run["id"],
            lambda item: {
                **item,
                "results": [{**item["results"][0], "status": "passed", "score": 1}],
            },
        )
        runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))
        with pytest.raises(WorkspaceError):
            runner.rejudge(pid, run["id"])

    def test_judge_failure_keeps_result_reviewable(self, client, project_root, monkeypatch):
        from evalith.evaluation_runner import EvaluationRunner
        from evalith.model_gateway import ModelError

        pid, ws, store, run = self._finished_run_with_unscored_result(client, project_root)
        runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))

        def failing_judge(runner_self, run_arg, task, observation, verification, **kwargs):
            raise ModelError("模型服务返回 503：still down")

        monkeypatch.setattr(EvaluationRunner, "_judge", failing_judge)
        updated = runner.rejudge(pid, run["id"])
        assert updated["results"][0]["status"] == "review_required"
        assert "still down" in (updated["results"][0]["error"] or "")
