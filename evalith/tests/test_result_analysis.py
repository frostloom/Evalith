from __future__ import annotations

from copy import deepcopy
import pytest
from conftest import create_stub_model, import_project
from evalith.evaluation_store import EvaluationStore
from evalith.model_gateway import ModelGateway
from evalith.service import WorkspaceError


def setup(client, project_root):
    model = create_stub_model(client)
    pid = import_project(
        client, project_root, model_config_id=model["id"], include=["README.md"]
    ).json()["project"]["id"]
    store = EvaluationStore(client.app.state.db)
    run = store.create(
        pid,
        "run",
        {
            "results": [
                {
                    "id": "pass",
                    "status": "passed",
                    "score": 1,
                    "observation": {"text": "ok"},
                },
                {
                    "id": "fail",
                    "status": "failed",
                    "score": 0,
                    "observation": {"text": "wrong"},
                },
                {
                    "id": "missing",
                    "status": "validation_error",
                    "score": None,
                    "observation": None,
                },
            ]
        },
        status="completed",
    )
    return pid, store, run


def test_analysis_selection_requires_terminal_and_excludes_unknown_score_from_low(
    client, project_root, monkeypatch
):
    from evalith.result_analysis import ResultAnalysis

    pid, store, run = setup(client, project_root)
    service = ResultAnalysis(client.app.state.service, store)
    store.update(pid, "run", run["id"], status="running")
    with pytest.raises(WorkspaceError):
        service.start(pid, run["id"], {"selection": "all"}, background=False)
    store.update(pid, "run", run["id"], status="completed")
    seen = []

    def complete(self, system, payload):
        seen.extend(payload["results"])
        return {
            "summary": "Evidence reviewed",
            "facts": [{"text": "Failed check", "result_ids": ["fail"]}],
            "hypotheses": [],
            "recommendations": [],
            "limitations": ["Uncalibrated"],
        }

    monkeypatch.setattr(ModelGateway, "complete_json", complete)
    report = service.start(
        pid, run["id"], {"selection": "low", "max_model_calls": 1}, background=False
    )
    assert report["status"] == "completed", report
    assert [item["id"] for item in seen] == ["fail"]
    assert report["usage"]["model_calls"] == 1 and report["usage"]["cost_usd"] is None
    assert store.get(pid, "run", run["id"])["results"] == run["results"]


def test_analysis_budget_is_independent_and_false_citations_are_rejected(
    client, project_root, monkeypatch
):
    from evalith.result_analysis import ResultAnalysis

    pid, store, run = setup(client, project_root)
    service = ResultAnalysis(client.app.state.service, store)
    monkeypatch.setattr(
        ModelGateway,
        "complete_json",
        lambda *args: pytest.fail("budget must prevent call"),
    )
    report = service.start(
        pid, run["id"], {"selection": "all", "max_model_calls": 0}, background=False
    )
    assert report["status"] == "budget_stopped" and report["usage"]["model_calls"] == 0
    monkeypatch.setattr(
        ModelGateway,
        "complete_json",
        lambda *args: {
            "summary": "bad",
            "facts": [{"text": "Invented", "result_ids": ["outside"]}],
            "hypotheses": [],
            "recommendations": [],
            "limitations": [],
        },
    )
    report = service.start(
        pid, run["id"], {"selection": "failed", "max_model_calls": 1}, background=False
    )
    assert report["status"] == "failed" and report["report"] is None
    assert store.get(pid, "run", run["id"])["results"] == run["results"]
