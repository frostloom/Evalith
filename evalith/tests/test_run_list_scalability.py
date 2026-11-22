"""Review 2026-11-21 R2/D7 (lightweight lane): run lists must not ship
every observation ever captured, and cancellation must not re-decode
the whole record.

The list endpoint returns full run records — embedded task
definitions, graders, grading plans and complete observations (Harbor
stdout alone can reach millions of characters). A few batches in, each
3-second poll drags megabytes. Lists now project each run to a summary
(result rows shrink to id/status/score/task id) and accept a ``limit``
so history is not silently capped at 200. ``cancelled`` reads one
status column instead of decoding the record the poller re-reads
twenty times a second.
"""

from conftest import create_stub_model, import_project
from evalith.evaluation_store import EvaluationStore


def seeded_run(client, project_root, results):
    model = create_stub_model(client)
    pid = import_project(
        client, project_root, model_config_id=model["id"], include=["README.md"]
    ).json()["project"]["id"]
    ws = client.app.state.service
    store = EvaluationStore(ws.db)
    store.create(
        pid,
        "run",
        {
            "models": {},
            "tasks": [],
            "results": results,
            "calls": [],
            "budget": {"max_model_calls": 0, "budget_usd": None},
            "usage": {},
        },
        status="completed",
    )
    return pid


BIG_OBSERVATION = {"stdout": "x" * 100_000, "evidence_directory": "/tmp/x"}


class TestRunListSummaries:
    def test_list_strips_observations_but_keeps_identity(self, client, project_root):
        pid = seeded_run(
            client,
            project_root,
            [
                {
                    "id": "result_a",
                    "task": {"task_id": "t1", "definition": {"title": "T"}},
                    "status": "passed",
                    "score": 1,
                    "checks": [],
                    "observation": BIG_OBSERVATION,
                }
            ],
        )
        response = client.get(f"/api/projects/{pid}/runs")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["results"][0]["status"] == "passed"
        assert item["results"][0]["task_id"] == "t1"
        assert "observation" not in item["results"][0]
        assert "definition" not in item["results"][0]
        # The full record stays available on the single-run endpoint.
        detail = client.get(f"/api/projects/{pid}/runs/{item['id']}")
        assert detail.json()["results"][0]["observation"] == BIG_OBSERVATION

    def test_list_payload_is_small(self, client, project_root):
        pid = seeded_run(
            client,
            project_root,
            [
                {
                    "id": f"result_{i}",
                    "task": {"task_id": f"t{i}", "definition": {"title": "T"}},
                    "status": "passed",
                    "score": 1,
                    "checks": [],
                    "observation": BIG_OBSERVATION,
                }
                for i in range(5)
            ],
        )
        body = client.get(f"/api/projects/{pid}/runs").content
        assert len(body) < 20_000  # 500KB of stdout must not survive into it

    def test_limit_parameter_controls_history_depth(self, client, project_root):
        pid = seeded_run(client, project_root, [])
        for index in range(4):
            client.get(f"/api/projects/{pid}/runs")
            from evalith.evaluation_store import new_id

            ws = client.app.state.service
            store = EvaluationStore(ws.db)
            store.create(
                pid,
                "run",
                {
                    "models": {},
                    "tasks": [],
                    "results": [],
                    "calls": [],
                    "budget": {"max_model_calls": 0, "budget_usd": None},
                    "usage": {},
                },
                status="completed",
                record_id=f"run_l{index}",
            )
        assert len(client.get(f"/api/projects/{pid}/runs").json()["items"]) == 5
        assert len(client.get(f"/api/projects/{pid}/runs?limit=2").json()["items"]) == 2
        assert client.get(f"/api/projects/{pid}/runs?limit=5000").status_code == 422


class TestCancelledIsLightweight:
    def test_cancelled_does_not_decode_the_record(self, client, project_root, monkeypatch):
        from evalith.environments import EnvironmentManager
        from evalith.evaluation_runner import EvaluationRunner

        pid = seeded_run(client, project_root, [])
        ws = client.app.state.service
        store = EvaluationStore(ws.db)
        record = store.list(pid, "run")[0]
        store.update(pid, "run", record["id"], status="cancelling")

        decoded = {"n": 0}
        original_get = store.get

        def counting_get(self, *args, **kwargs):
            decoded["n"] += 1
            return original_get(self, *args, **kwargs)

        monkeypatch.setattr(EvaluationStore, "get", counting_get)
        runner = EvaluationRunner(ws, store, EnvironmentManager(ws, store))
        assert runner.cancelled(pid, record["id"]) is True
        assert decoded["n"] == 0  # the status check decoded nothing
