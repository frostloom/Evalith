import time
from copy import deepcopy

import pytest
from conftest import create_stub_model, import_project
from evalith.evaluation_assets import EvaluationAssets
from evalith.evaluation_library import EvaluationLibrary
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
    return pid, model, EvaluationAssets(ws, store)


def bundle():
    return {
        "name": "余额证据回归",
        "description": "Synthetic evidence only",
        "graders": [
            {
                "key": "facts",
                "name": "事实核对",
                "description": "Check the observed evidence",
                "rubric": "Pass only when the answer cites the actual balance",
                "steps": [
                    "Read the actual tool evidence",
                    "Compare the answer",
                    "Score from 0 to 1",
                ],
                "check": {"type": "judge", "expected": "Match the tool facts"},
                "threshold": 0.9,
                "task_kinds": ["conversation"],
                "source_refs": ["README.md"],
                "uncertainties": ["Synthetic balance only"],
            }
        ],
        "tasks": [
            {
                "definition": {
                    "title": "Query balance",
                    "category": "Account",
                    "objective": "Read the fixture balance",
                    "kind": "conversation",
                    "input": {"turns": ["查余额"], "fixture": {"balance_cent": 200000}},
                    "checks": [{"type": "contains", "expected": "2000"}],
                    "rubric": "Use the fixture evidence",
                    "source_refs": ["README.md"],
                    "uncertainties": [],
                },
                "grader_keys": ["facts"],
            }
        ],
    }


def test_preparation_saves_linked_graders_tasks_and_one_real_collection(
    client, project_root, monkeypatch
):
    pid, model, assets = setup(client, project_root)
    monkeypatch.setattr(ModelGateway, "complete_json", lambda *_: bundle())
    result = assets.prepare(pid, count=1, direction="Evaluate balance tool evidence")
    task, grader = result["items"][0], result["graders"][0]
    assert task["default_grader_ids"] == [grader["id"]]
    assert grader["model_config_id"] == model["id"] and grader["threshold"] == 0.9
    assert grader["calibration_state"] == "unverified"
    assert grader["source_refs"] == ["README.md"]
    assert result["test_set"]["task_ids"] == [task["id"]]
    assert result["test_set"]["grader_ids"] == []  # inherits each task's own defaults
    assert len(EvaluationLibrary(assets.workspace, assets.store).list_sets(pid)) == 1
    changed = assets.edit(
        pid, task["id"], {**task["definition"], "title": "Revised query"}
    )
    assert changed["default_grader_ids"] == [grader["id"]]
    assert (
        assets.store.task_version(pid, task["version_id"])["definition"]["title"]
        == "Query balance"
    )


def test_preparation_cannot_drop_unconfirmed_project_rules(
    client, project_root, monkeypatch
):
    pid, _model, assets = setup(client, project_root)
    detail = assets.workspace.get_project_detail(pid)
    understanding = {
        **detail["understanding"],
        "unknowns": [{"text": "是否允许透支尚未确认", "why": "不能臆定财务规则"}],
    }
    assets.workspace._store_understanding(
        assets.workspace.db.get_project(pid), understanding, error=None
    )
    monkeypatch.setattr(ModelGateway, "complete_json", lambda *_: bundle())
    result = assets.prepare(pid, count=1)
    for item in [*result["graders"], *[t["definition"] for t in result["items"]]]:
        assert any("是否允许透支尚未确认" in text for text in item["uncertainties"])


def test_editing_generated_scoring_rules_detaches_defaults_but_preserves_old_version(
    client, project_root, monkeypatch
):
    pid, _model, assets = setup(client, project_root)
    monkeypatch.setattr(ModelGateway, "complete_json", lambda *_: bundle())
    task = assets.prepare(pid, count=1)["items"][0]
    revised = {
        **task["definition"],
        "rubric": "New stricter criteria",
        "checks": [{"type": "judge", "expected": "Require a signed tool trace"}],
    }
    changed = assets.edit(pid, task["id"], revised)
    assert changed["default_grader_ids"] == []
    assert (
        assets.store.task_version(pid, task["version_id"])["default_grader_ids"]
        == task["default_grader_ids"]
    )


def test_retaining_project_unknowns_keeps_all_model_notes_at_schema_limit(
    client, project_root, monkeypatch
):
    pid, _model, assets = setup(client, project_root)
    value = bundle()
    notes = [f"Model limitation {i}" for i in range(30)]
    value["graders"][0]["uncertainties"] = notes[:]
    value["tasks"][0]["definition"]["uncertainties"] = notes[:]
    monkeypatch.setattr(ModelGateway, "complete_json", lambda *_: value)
    result = assets.prepare(pid, count=1)
    for item in [*result["graders"], *[t["definition"] for t in result["items"]]]:
        assert len(item["uncertainties"]) <= 30
        assert all(note in "\n".join(item["uncertainties"]) for note in notes)
        assert "项目待确认" in "\n".join(item["uncertainties"])


@pytest.mark.parametrize(
    "invalid", ["reference", "source", "threshold", "scope", "model"]
)
def test_invalid_generated_bundle_leaves_no_partial_assets(
    client, project_root, monkeypatch, invalid
):
    pid, _model, assets = setup(client, project_root)
    value = deepcopy(bundle())
    if invalid == "reference":
        value["tasks"][0]["grader_keys"] = ["invented"]
    if invalid == "source":
        value["graders"][0]["source_refs"] = ["outside.md"]
    if invalid == "threshold":
        value["graders"][0]["threshold"] = True
    if invalid == "scope":
        value["graders"][0]["task_kinds"] = ["command"]
    if invalid == "model":
        value["graders"][0]["model_config_id"] = "unrequested-model"
    monkeypatch.setattr(ModelGateway, "complete_json", lambda *_: value)
    with pytest.raises(WorkspaceError):
        assets.prepare(pid, count=1)
    for kind in ["task", "grader", "generation", "test_set"]:
        assert assets.store.list(pid, kind) == []


def test_preparation_rechecks_sources_after_inference(
    client, project_root, monkeypatch
):
    pid, _model, assets = setup(client, project_root)

    def changed(*_):
        (project_root / "README.md").write_text("New business rules")
        return bundle()

    monkeypatch.setattr(ModelGateway, "complete_json", changed)
    with pytest.raises(WorkspaceError) as error:
        assets.prepare(pid, count=1)
    assert error.value.code == "source_changed"
    assert not assets.list(pid) and not assets.store.list(pid, "grader")


def test_preparation_database_failure_rolls_back_every_asset(
    client, project_root, monkeypatch
):
    pid, _model, assets = setup(client, project_root)
    monkeypatch.setattr(ModelGateway, "complete_json", lambda *_: bundle())
    with assets.workspace.db.connection() as c:
        c.execute(
            "CREATE TRIGGER reject_set BEFORE INSERT ON evaluation_records WHEN NEW.kind='test_set' BEGIN SELECT RAISE(ABORT, 'disk failed'); END"
        )
    with pytest.raises(Exception, match="disk failed"):
        assets.prepare(pid, count=1)
    for kind in ["task", "grader", "generation", "test_set"]:
        assert not assets.store.list(pid, kind)
    with assets.workspace.db.connection() as c:
        assert (
            c.execute("SELECT COUNT(*) FROM evaluation_task_versions").fetchone()[0]
            == 0
        )


def test_preparation_job_returns_real_asset_links_and_grader_draft_stays_unsaved(
    client, project_root, monkeypatch
):
    pid, _model, assets = setup(client, project_root)
    with assets.workspace.db.connection() as c:
        c.execute("UPDATE model_configs SET provider='openai_compatible', base_url='http://127.0.0.1:9/v1'")
    monkeypatch.setattr(ModelGateway, "complete_json", lambda *_: bundle())
    response = client.post(
        f"/api/projects/{pid}/preparations",
        json={"count": 1, "direction": "Use actual tool facts"},
    )
    assert response.status_code == 202, response.text
    for _ in range(100):
        job = client.get(f"/api/projects/{pid}/jobs/{response.json()['id']}").json()
        if job["status"] in {"failed", "completed"}:
            break
        time.sleep(0.01)
    assert job["status"] == "completed", job
    assert job["operation"] == "preparation" and job["result"]["grader_ids"]
    assert (
        client.get(
            f"/api/projects/{pid}/test-sets/{job['result']['test_set_id']}"
        ).status_code
        == 200
    )
    monkeypatch.setattr(
        ModelGateway, "complete_json", lambda *_: {"grader": bundle()["graders"][0]}
    )
    draft = client.post(
        f"/api/projects/{pid}/graders/synthesize",
        json={"description": "Judge tool evidence"},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["draft"]["rubric"] and draft.json()["draft"]["steps"]
    assert (
        len(assets.store.list(pid, "grader")) == 1
    )  # synthesis does not save another standard
