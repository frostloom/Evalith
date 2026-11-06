from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conftest import _RecordingHandler, create_stub_model, import_project


def _detail(client: TestClient, project_id: str) -> dict:
    response = client.get(f"/api/projects/{project_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_initial_understanding_distinguishes_known_inferred_unknown(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    understanding = detail["understanding"]
    assert understanding["summary"]
    assert understanding["known"]
    assert understanding["inferred"]
    assert understanding["unknowns"]
    assert understanding["sufficient"] is False
    assert understanding["sources"]
    assert detail["readiness"]["generation_allowed"] is False
    assistant = [item for item in detail["messages"] if item["role"] == "assistant"]
    assert assistant[-1]["payload"]["kind"] == "understanding"
    assert assistant[-1]["payload"]["understanding"]["unknowns"]


def test_question_generation_gate_stays_closed_until_ready(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]

    blocked = client.post(f"/api/projects/{project_id}/generate")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "generation_not_ready"

    continued = client.post(f"/api/projects/{project_id}/continue")
    assert continued.status_code == 200, continued.text
    refreshed = continued.json()
    assert refreshed["readiness"]["generation_allowed"] is True
    assert refreshed["readiness"]["unknowns_confirmed"] is False
    assert refreshed["understanding"]["unknowns"]  # continuing does not confirm unknowns

    still_not_implemented = client.post(f"/api/projects/{project_id}/generate")
    assert still_not_implemented.status_code == 501
    assert still_not_implemented.json()["code"] == "generation_not_implemented"


def test_user_correction_updates_summary_but_keeps_unknowns(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    original_unknowns = detail["understanding"]["unknowns"]

    response = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "纠正：这是一个需要人工复核的发布审批流程。"},
    )
    assert response.status_code == 200, response.text
    refreshed = response.json()
    assert "人工复核" in refreshed["understanding"]["summary"]
    assert refreshed["understanding"]["unknowns"] == original_unknowns
    assert any("用户纠正" in str(item) for item in refreshed["understanding"]["known"])


def test_sufficiency_can_open_gate_without_confirming_unknowns(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    response = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "现有资料依据足够，可以继续，但未知的验收标准仍未确认。"},
    )
    assert response.status_code == 200, response.text
    refreshed = response.json()
    assert refreshed["understanding"]["sufficient"] is True
    assert refreshed["readiness"]["generation_allowed"] is True
    assert refreshed["readiness"]["unknowns_confirmed"] is False
    assert refreshed["understanding"]["unknowns"]


def test_model_failure_is_visible_not_silent(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.fail = True
    model = client.post(
        "/api/model-configs",
        json={
            "name": "failing-model",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
            "api_key": "sk-model-secret",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert detail["project"]["analysis_error"]
    assert detail["understanding"]["error"]
    assert detail["readiness"]["generation_allowed"] is False
    errors = [item for item in detail["messages"] if item["payload"]["kind"] == "error"]
    assert errors and "模型服务返回 500" in errors[-1]["content"]
    assert "sk-model-secret" not in str(detail)

    continue_attempt = client.post(f"/api/projects/{detail['project']['id']}/continue")
    assert continue_attempt.status_code == 409
    assert continue_attempt.json()["code"] == "understanding_failed"

    chat = client.post(
        f"/api/projects/{detail['project']['id']}/messages", json={"content": "继续"}
    )
    assert chat.status_code == 502
    assert "模型服务返回 500" in chat.json()["error"]
    assert "sk-model-secret" not in str(chat.json())


def test_rescan_records_new_snapshot_and_reanalyse(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    first_snapshot = detail["snapshot"]["id"]

    (project_root / "docs" / "NEW.md").write_text("# New rule\nBe careful.\n", encoding="utf-8")
    rescanned = client.post(f"/api/projects/{project_id}/rescan")
    assert rescanned.status_code == 200, rescanned.text
    assert rescanned.json()["snapshot"]["id"] != first_snapshot
    assert "docs/NEW.md" in {
        item["path"] for item in rescanned.json()["snapshot"]["files"]
    }

    analysed = client.post(f"/api/projects/{project_id}/reanalyse")
    assert analysed.status_code == 200, analysed.text
    assert analysed.json()["understanding"]["snapshot_id"] == analysed.json()["snapshot"]["id"]


def test_supplemental_update_is_in_scope(client: TestClient, project_root: Path) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    updated = client.put(
        f"/api/projects/{project_id}/sources",
        json={
            "include_paths": ["README.md"],
            "exclude_patterns": [],
            "supplemental": [{"title": "评审补充", "content": "发布失败必须通知值班人。"}],
        },
    )
    assert updated.status_code == 200, updated.text
    files = {item["path"] for item in updated.json()["snapshot"]["files"]}
    assert files == {"README.md"}
    scope = updated.json()["messages"][-1]["sent_scope"]
    assert "supplement:评审补充" in {item["path"] for item in scope["sources"]}
