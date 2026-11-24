"""Review 2026-11-21 batch 5: R5, R7, D3, D4.

R5: the Harbor watchdog must outlive the image build it declares, and
a killed CLI must not silently claim container cleanup completed —
containers are Docker-managed and the error says so.

R7: a run configured with ``budget_usd`` carries an explicit warning
through preview/start: with unknown real costs, the first model call
already stops the batch, so the user sees the trap before starting.

D3: calibration reports state their evidence base — sample count,
expected-outcome mix and a sufficiency verdict — so "calibrated" on a
single missing_evidence sample can no longer masquerade as solid.

D4: runs whose scoring structurally requires a real model (judge
checks, bridged targets, simulators) refuse to start with the offline
stub model at plan time instead of failing after the target ran.
"""

import pytest
from conftest import create_stub_model, import_project
from evalith.evaluation_store import EvaluationStore
from evalith.service import WorkspaceError


def seeded(client, project_root):
    model = create_stub_model(client)
    pid = import_project(
        client, project_root, model_config_id=model["id"], include=["README.md"]
    ).json()["project"]["id"]
    client.post(f"/api/projects/{pid}/continue")
    return pid, model


class TestHarborWatchdog:
    def test_watchdog_covers_the_declared_build_window(self, monkeypatch, tmp_path):
        from evalith import evaluation_runner as runner_module
        from evalith.evaluation_runner import EvaluationRunner

        captured = {}

        def fake_bounded(arguments, directory, *, timeout, **kwargs):
            captured["timeout"] = timeout
            raise WorkspaceError("stop here", status_code=422)

        monkeypatch.setattr(runner_module, "bounded_process", fake_bounded)
        runner = EvaluationRunner.__new__(EvaluationRunner)
        seed = tmp_path / "seed"
        seed.mkdir()
        runtime = {
            "source_copy": str(seed),
            "harbor_command": ["harbor"],
            "working_relative": ".",
            "command": ["true"],
            "timeout_seconds": 30,
        }
        task = {
            "task_id": "t1",
            "definition": {
                "objective": "o",
                "rubric": "r",
                "input": {"files": {}, "stdin": ""},
            },
        }
        with pytest.raises(WorkspaceError):
            EvaluationRunner._execute_harbor(
                runner,
                {"project_id": "p", "environment_snapshot": {"runtime": runtime}},
                task,
                tmp_path,
                None,
            )
        # build_timeout 900 + agent 30 + verifier 30 + slack must fit
        assert captured["timeout"] >= 900 + 2 * 30 + 60


class TestBudgetWarning:
    def test_preview_warns_when_budget_usd_is_set(
        self, client, project_root, monkeypatch
    ):
        monkeypatch.setattr(
            "evalith.environments.sandbox_available", lambda: True
        )
        pid, model = seeded(client, project_root)
        env = client.post(
            "/api/executor-configs",
            json={
                "name": "echo",
                "backend": "local_command",
                "command": ["python3", "-c", "print(input())"],
                "timeout_seconds": 3,
            },
        ).json()
        plan = client.post(
            f"/api/projects/{pid}/environments/plan",
            json={"executor_config_id": env["id"]},
        ).json()
        client.post(
            f"/api/projects/{pid}/environments/{plan['id']}/confirm",
            json={"plan_digest": plan["plan_digest"]},
        )
        import time

        for _ in range(100):
            state = client.get(f"/api/projects/{pid}/environments/{plan['id']}").json()
            if state["status"] in {"ready", "failed"}:
                break
            time.sleep(0.02)
        task = client.post(
            f"/api/projects/{pid}/tasks",
            json={
                "title": "T",
                "category": "C",
                "objective": "O",
                "kind": "command",
                "input": {"stdin": ""},
                "checks": [{"type": "contains", "expected": "2000"}],
                "rubric": "r",
                "source_refs": ["README.md"],
                "uncertainties": [],
            },
        ).json()
        version_ids = [
            item["version_id"]
            for item in client.get(f"/api/projects/{pid}/tasks/{task['id']}/versions").json()["items"]
        ]
        preview = client.post(
            f"/api/projects/{pid}/runs/preview",
            json={
                "environment_id": plan["id"],
                "version_ids": version_ids,
                "budget_usd": 10,
            },
        )
        assert preview.status_code == 200
        assert any(
            "金额费用未知" in warning for warning in preview.json().get("warnings", [])
        )


class TestCalibrationEvidenceBase:
    def test_summary_carries_mix_and_sufficiency(self):
        from evalith.evaluation_calibration import build_summary

        thin = build_summary(
            [
                {"expected": "missing_evidence", "matched": True},
                {"expected": "missing_evidence", "matched": True},
            ]
        )
        assert thin["total"] == 2
        assert thin["expected_mix"] == {"missing_evidence": 2}
        assert thin["sufficient"] is False  # tiny + single-outcome

        solid = build_summary(
            [
                {"expected": "pass", "matched": True},
                {"expected": "pass", "matched": True},
                {"expected": "fail", "matched": False},
                {"expected": "missing_evidence", "matched": True},
            ]
        )
        assert solid["total"] == 4
        assert solid["sufficient"] is True  # enough + mixed outcomes


class TestPlanRejectsStubScoring:
    def test_stub_judge_with_judge_checks_refused(
        self, client, project_root, monkeypatch
    ):
        monkeypatch.setattr(
            "evalith.environments.sandbox_available", lambda: True
        )
        pid, model = seeded(client, project_root)
        store = EvaluationStore(client.app.state.db)
        task = client.post(
            f"/api/projects/{pid}/tasks",
            json={
                "title": "T",
                "category": "C",
                "objective": "O",
                "kind": "command",
                "input": {"stdin": ""},
                "checks": [{"type": "contains", "expected": "2000"}],
                "rubric": "r",
                "source_refs": ["README.md"],
                "uncertainties": [],
            },
        ).json()
        env = client.post(
            "/api/executor-configs",
            json={
                "name": "echo",
                "backend": "local_command",
                "command": ["python3", "-c", "print(input())"],
                "timeout_seconds": 3,
            },
        ).json()
        plan = client.post(
            f"/api/projects/{pid}/environments/plan",
            json={"executor_config_id": env["id"]},
        ).json()
        client.post(
            f"/api/projects/{pid}/environments/{plan['id']}/confirm",
            json={"plan_digest": plan["plan_digest"]},
        )
        import time

        for _ in range(100):
            state = client.get(f"/api/projects/{pid}/environments/{plan['id']}").json()
            if state["status"] in {"ready", "failed"}:
                break
            time.sleep(0.02)
        # A judge-typed grader bound to the offline stub must not start.
        store.create(
            pid,
            "grader",
            {
                "name": "J",
                "description": "d",
                "rubric": "r",
                "steps": ["s"],
                "check": {"type": "judge", "expected": "对"},
                "threshold": 0.9,
                "model_config_id": model["id"],  # stub
                "version": 1,
                "calibration_state": "unverified",
            },
            status="active",
        )
        graders = client.get(f"/api/projects/{pid}/graders").json()["items"]
        version_ids = [
            item["version_id"]
            for item in client.get(f"/api/projects/{pid}/tasks/{task['id']}/versions").json()["items"]
        ]
        body = {
            "environment_id": plan["id"],
            "version_ids": version_ids,
            "grader_ids": [g["id"] for g in graders],
        }
        preview = client.post(f"/api/projects/{pid}/runs/preview", json=body)
        assert preview.status_code == 200
        assert any("离线演示" in w for w in preview.json()["warnings"])
        # Preview warns; start refuses before the target ever executes.
        started = client.post(f"/api/projects/{pid}/runs", json=body)
        assert started.status_code == 422
        assert "离线演示" in started.json()["error"]
