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


def test_negative_continuation_and_insufficient_evidence_keep_gate_closed(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]

    refused = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "先不要继续，我还需要补充资料。"},
    )
    assert refused.status_code == 200, refused.text
    refused_detail = refused.json()
    assert refused_detail["readiness"]["generation_allowed"] is False
    assert refused_detail["understanding"]["user_continued"] is False
    assert refused_detail["understanding"]["sufficient"] is False

    insufficient = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "现在还不能说依据足够，未知规则还没有确认。"},
    )
    assert insufficient.status_code == 200, insufficient.text
    insufficient_detail = insufficient.json()
    assert insufficient_detail["readiness"]["generation_allowed"] is False
    assert insufficient_detail["understanding"]["sufficient"] is False
    assert insufficient_detail["understanding"]["unknowns"]


def test_sufficiency_retraction_closes_an_open_gate(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]

    opened = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "现有资料依据足够。"}
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["readiness"]["generation_allowed"] is True

    retracted = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "刚才说错了，依据不足。"}
    )
    assert retracted.status_code == 200, retracted.text
    assert retracted.json()["understanding"]["sufficient"] is False
    assert retracted.json()["readiness"]["generation_allowed"] is False


def test_malformed_understanding_items_are_a_visible_error(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "summary": "malformed items",
        "agent_or_flow": "",
        "known": [None],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "not enough",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "malformed-items",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert detail["project"]["analysis_error"]
    assert "known[0]" in detail["project"]["analysis_error"]
    assert detail["readiness"]["generation_allowed"] is False


def test_non_boolean_sufficiency_is_a_visible_error(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "summary": "malformed understanding",
        "agent_or_flow": "",
        "known": [],
        "inferred": [],
        "unknowns": [{"text": "unknown", "why": "unknown"}],
        "sufficient": "false",
        "sufficient_reason": "string is not a boolean",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "malformed",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert detail["readiness"]["generation_allowed"] is False
    assert detail["project"]["analysis_error"]
    assert "必须是布尔值" in detail["project"]["analysis_error"]
    assert any(
        item["payload"]["kind"] == "error" for item in detail["messages"]
    )


def test_non_boolean_continue_is_a_visible_error(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "malformed-chat",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": "false",
        "understanding": {
            "summary": "valid summary",
            "agent_or_flow": "",
            "known": [],
            "inferred": [],
            "unknowns": [{"text": "unknown", "why": "unknown"}],
            "sufficient": False,
            "sufficient_reason": "not enough",
        },
    }
    response = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "继续"},
    )
    assert response.status_code == 502
    assert "必须是布尔值" in response.json()["error"]
    refreshed = client.get(f"/api/projects/{detail['project']['id']}").json()
    assert refreshed["readiness"]["generation_allowed"] is False


def test_sufficiency_can_open_gate_without_confirming_unknowns(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    response = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "现有资料依据足够。"},
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


def test_reanalysis_keeps_session_correction_for_real_provider(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "correction-model",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]

    _RecordingHandler.body_override = {
        "reply": "已记录纠正。",
        "continue_requested": False,
        "understanding": {
            "summary": "人工复核流程",
            "agent_or_flow": "approval",
            "known": [],
            "inferred": [],
            "unknowns": [{"text": "验收标准未知", "why": "资料未写明"}],
            "sufficient": False,
            "sufficient_reason": "仍需确认验收标准。",
        },
    }
    corrected = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "纠正：这是人工复核流程，评测重点是审计记录。"},
    )
    assert corrected.status_code == 200, corrected.text

    _RecordingHandler.body_override = None
    reanalysed = client.post(f"/api/projects/{project_id}/reanalyse")
    assert reanalysed.status_code == 200, reanalysed.text
    assert any(
        "人工复核" in str(item)
        for item in reanalysed.json()["understanding"]["known"]
    )
    analysis_request = _RecordingHandler.requests[-1]["body"]
    assert "人工复核" in analysis_request
    assert "当前理解" in analysis_request


def test_existing_project_can_acquire_a_model_without_new_session(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=None).json()
    project_id = detail["project"]["id"]
    session_id = detail["session"]["id"]
    assert detail["project"]["analysis_error"]

    repaired = client.put(
        f"/api/projects/{project_id}/model", json={"model_config_id": model["id"]}
    )
    assert repaired.status_code == 200, repaired.text
    refreshed = repaired.json()
    assert refreshed["project"]["model_config_id"] == model["id"]
    assert refreshed["project"]["analysis_error"] is None
    assert refreshed["session"]["id"] == session_id
    assert refreshed["understanding"]["model"] == "stub"
    assert refreshed["understanding"]["known"]
    assert "项目理解失败" not in refreshed["understanding"]["summary"]


def test_existing_project_rejects_unknown_model(
    client: TestClient, project_root: Path
) -> None:
    detail = import_project(client, project_root, model_config_id=None).json()
    response = client.put(
        f"/api/projects/{detail['project']['id']}/model",
        json={"model_config_id": "mdl_missing"},
    )
    assert response.status_code == 422


def test_valid_provider_sufficiency_survives_ordinary_discussion(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "model-sufficient",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "现在可以判断了。",
        "continue_requested": False,
        "understanding": {
            "summary": "补充后的理解",
            "agent_or_flow": "sync http",
            "known": [{"text": "后端是 FastAPI", "source": "会话"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": True,
            "sufficient_reason": "关键事实已补齐",
        },
    }
    for text in ("补充：项目后端是 FastAPI。", "补充：这是等待事件的流程。"):
        response = client.post(
            f"/api/projects/{detail['project']['id']}/messages",
            json={"content": text},
        )
        assert response.status_code == 200, response.text
        assert response.json()["understanding"]["sufficient"] is True
        assert response.json()["readiness"]["generation_allowed"] is True


def test_provider_accepts_explicit_continuation_phrases(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "explicit-phrases",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": True,
        "understanding": {
            "summary": "explicit continuation",
            "agent_or_flow": "",
            "known": [{"text": "policy", "source": "README.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": "still unknown",
        },
    }
    for phrase in ("进入下一步", "开始出题"):
        response = client.post(
            f"/api/projects/{detail['project']['id']}/messages",
            json={"content": phrase},
        )
        assert response.status_code == 200, response.text
        assert response.json()["readiness"]["generation_allowed"] is True
        assert response.json()["understanding"]["user_continued"] is True


def test_continue_consent_can_be_withdrawn(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    for refusal in ("我拒绝继续。", "我不同意继续。"):
        continued = client.post(
            f"/api/projects/{project_id}/messages", json={"content": "继续"}
        )
        assert continued.status_code == 200, continued.text
        assert continued.json()["understanding"]["user_continued"] is True

        withdrawn = client.post(
            f"/api/projects/{project_id}/messages", json={"content": refusal}
        )
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json()["understanding"]["user_continued"] is False
        assert withdrawn.json()["readiness"]["generation_allowed"] is False


def test_sufficiency_withdrawal_survives_provider_failure(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "sufficiency-withdrawal-failure",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "sufficient",
        "continue_requested": False,
        "understanding": {
            "summary": "sufficient",
            "agent_or_flow": "",
            "known": [{"text": "policy", "source": "README.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": True,
            "sufficient_reason": "model says enough",
        },
    }
    ready = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "我确认依据足够。"},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["understanding"]["sufficient"] is True

    _RecordingHandler.fail = True
    refused = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "刚才说错了，依据不足。"},
    )
    assert refused.status_code == 502, refused.text
    refreshed = client.get(f"/api/projects/{detail['project']['id']}").json()
    assert refreshed["understanding"]["sufficient"] is False
    assert refreshed["readiness"]["generation_allowed"] is False


def test_unchanged_rescan_preserves_sufficiency(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "summary": "sufficient",
        "agent_or_flow": "",
        "known": [{"text": "policy", "source": "README.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": True,
        "sufficient_reason": "enough",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "unchanged-rescan",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    rescanned = client.post(f"/api/projects/{detail['project']['id']}/rescan")
    assert rescanned.status_code == 200, rescanned.text
    assert rescanned.json()["understanding"]["sufficient"] is True
    assert rescanned.json()["readiness"]["generation_allowed"] is True
    assert rescanned.json()["snapshot"]["id"] == detail["snapshot"]["id"]


def test_stub_changed_file_continuation_rebuilds_understanding(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    assert detail["understanding"]["unknowns"]
    (project_root / "README.md").write_text("changed evidence\n", encoding="utf-8")
    response = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "继续"},
    )
    assert response.status_code == 200, response.text
    understanding = response.json()["understanding"]
    assert understanding["summary"]
    assert understanding["unknowns"]
    assert understanding["known"]


def test_rescan_invalidates_sufficiency_before_failure(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "summary": "sufficient",
        "agent_or_flow": "",
        "known": [{"text": "policy", "source": "README.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": True,
        "sufficient_reason": "enough",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "rescan-invalidation",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    assert detail["understanding"]["sufficient"] is True
    (project_root / "README.md").write_text("changed evidence\n", encoding="utf-8")
    rescanned = client.post(f"/api/projects/{project_id}/rescan")
    assert rescanned.status_code == 200, rescanned.text
    assert rescanned.json()["understanding"]["sufficient"] is False
    assert rescanned.json()["readiness"]["generation_allowed"] is False

    _RecordingHandler.fail = True
    failed = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "补充"}
    )
    assert failed.status_code == 502, failed.text
    refreshed = client.get(f"/api/projects/{project_id}").json()
    assert refreshed["understanding"]["sufficient"] is False
    assert refreshed["readiness"]["generation_allowed"] is False


def test_insufficiency_wording_closes_gate(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    opened = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "现有资料依据足够。"},
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["readiness"]["generation_allowed"] is True

    closed = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "资料还不够。"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["understanding"]["sufficient"] is False
    assert closed.json()["readiness"]["generation_allowed"] is False


def test_changed_evidence_invalidates_sufficiency_before_failure(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "summary": "sufficient",
        "agent_or_flow": "",
        "known": [{"text": "policy", "source": "README.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": True,
        "sufficient_reason": "enough",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "changed-evidence-failure",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    assert detail["understanding"]["sufficient"] is True
    (project_root / "README.md").unlink()
    _RecordingHandler.fail = True
    failed = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "补充"},
    )
    assert failed.status_code == 502, failed.text
    refreshed = client.get(f"/api/projects/{detail['project']['id']}").json()
    assert refreshed["understanding"]["sufficient"] is False
    assert refreshed["readiness"]["generation_allowed"] is False


def test_withdrawal_survives_provider_failure(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "withdrawal-failure",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "continue",
        "continue_requested": True,
        "understanding": {
            "summary": "continue",
            "agent_or_flow": "",
            "known": [{"text": "policy", "source": "README.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": "still unknown",
        },
    }
    continued = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "继续"},
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["understanding"]["user_continued"] is True

    _RecordingHandler.fail = True
    refused = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "我拒绝继续。"},
    )
    assert refused.status_code == 502, refused.text
    refreshed = client.get(f"/api/projects/{detail['project']['id']}").json()
    assert refreshed["understanding"]["user_continued"] is False
    assert refreshed["readiness"]["generation_allowed"] is False


def test_provider_uncertain_sufficiency_is_rejected(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "uncertain-sufficiency",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "understanding": {
            "summary": "uncertain",
            "agent_or_flow": "",
            "known": [{"text": "policy", "source": "README.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": True,
            "sufficient_reason": "model says enough",
        },
    }
    for text in (
        "依据足够与否尚不清楚。",
        "我不认为依据足够。",
    ):
        response = client.post(
            f"/api/projects/{detail['project']['id']}/messages",
            json={"content": text},
        )
        assert response.status_code == 200, response.text
        assert response.json()["understanding"]["sufficient"] is False
        assert response.json()["readiness"]["generation_allowed"] is False


def test_provider_rejects_conditional_intent(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "conditional-provider",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": True,
        "understanding": {
            "summary": "conditional",
            "agent_or_flow": "",
            "known": [{"text": "policy", "source": "README.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": "still unknown",
        },
    }
    for text in (
        "请先等我确认再继续。",
        "现在不应该继续。",
        "等补充材料到齐后才算依据足够。",
        "请勿继续。",
        "切勿继续。",
        "我会考虑继续。",
        "请检查继续读取文件的逻辑。",
        "我会不会继续。",
        "请在材料齐全后继续。",
        "请翻译成英文：继续。",
        "请将依据足够翻译成英文。",
        "现在没有必要继续。",
        "请在审批通过时继续。",
        "请判断可否继续。",
        "依据足够与否尚不清楚。",
        "我不认为依据足够。",
    ):
        response = client.post(
            f"/api/projects/{detail['project']['id']}/messages",
            json={"content": text},
        )
        assert response.status_code == 200, response.text
        assert response.json()["readiness"]["generation_allowed"] is False
        assert response.json()["understanding"]["user_continued"] is False

    _RecordingHandler.body_override["understanding"]["sufficient"] = True
    conditional = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "等补充材料到齐后才算依据足够。"},
    )
    assert conditional.status_code == 200, conditional.text
    assert conditional.json()["understanding"]["sufficient"] is False
    assert conditional.json()["readiness"]["generation_allowed"] is False


def test_provider_refusal_does_not_open_gate(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "refusal-provider",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": True,
        "understanding": {
            "summary": "refusal",
            "agent_or_flow": "",
            "known": [{"text": "policy", "source": "README.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": "still unknown",
        },
    }
    for text in ("我拒绝继续。", "机器人会继续处理请求。"):
        response = client.post(
            f"/api/projects/{detail['project']['id']}/messages",
            json={"content": text},
        )
        assert response.status_code == 200, response.text
        assert response.json()["readiness"]["generation_allowed"] is False
        assert response.json()["understanding"]["user_continued"] is False


def test_descriptive_sufficiency_cannot_override_provider(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "descriptive-sufficiency",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "understanding": {
            "summary": "descriptive",
            "agent_or_flow": "",
            "known": [{"text": "policy", "source": "README.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": True,
            "sufficient_reason": "model says enough",
        },
    }
    response = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "纠正：依据足够是一个状态名称。"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["understanding"]["sufficient"] is False
    assert response.json()["readiness"]["generation_allowed"] is False


def test_quoted_continuation_cannot_override_provider_intent(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "summary": "quoted intent",
        "agent_or_flow": "",
        "known": [{"text": "policy", "source": "README.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "not enough",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "quoted",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "noted",
        "continue_requested": True,
        "understanding": {
            "summary": "quoted intent",
            "agent_or_flow": "",
            "known": [{"text": "policy", "source": "README.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": "still not enough",
        },
    }
    response = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "纠正：按钮文案应为“可以继续”。"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["readiness"]["generation_allowed"] is False
    assert response.json()["understanding"]["sufficient"] is False
    assert response.json()["understanding"]["user_continued"] is False


def test_failed_understanding_is_not_cleared_by_reply_only_response(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.fail = True
    model = client.post(
        "/api/model-configs",
        json={
            "name": "recover",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    assert detail["understanding"]["error"]

    _RecordingHandler.fail = False
    _RecordingHandler.body_override = {
        "reply": "OK",
        "continue_requested": False,
    }
    response = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "继续"}
    )
    assert response.status_code == 502, response.text
    refreshed = client.get(f"/api/projects/{project_id}").json()
    assert refreshed["understanding"]["error"]
    assert client.post(f"/api/projects/{project_id}/continue").status_code == 409

    _RecordingHandler.body_override = {
        "reply": "recovered",
        "continue_requested": False,
        "understanding": {
            "summary": "恢复后的项目理解",
            "agent_or_flow": "",
            "known": [{"text": "恢复的已知项", "source": "会话"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": "still unknown",
        },
    }
    recovered = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "再试一次"}
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["understanding"]["error"] is None
    assert recovered.json()["project"]["analysis_error"] is None


def test_supplemental_update_keeps_chat_correction(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    corrected = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "纠正：评测重点是审计记录。"},
    )
    assert corrected.status_code == 200, corrected.text
    updated = client.put(
        f"/api/projects/{project_id}/sources",
        json={
            "include_paths": ["README.md"],
            "exclude_patterns": [],
            "supplemental": [{"title": "补充", "content": "新增验收口径。"}],
        },
    )
    assert updated.status_code == 200, updated.text
    assert any(
        "审计记录" in str(item) for item in updated.json()["understanding"]["known"]
    )


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


def test_reanalysis_retires_facts_from_changed_files(
    client: TestClient, tmp_path: Path, recording_server
) -> None:
    root = tmp_path / "changing-policy"
    root.mkdir()
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    (root / "policy.md").write_text("Approval optional.\n", encoding="utf-8")
    _RecordingHandler.body_override = {
        "summary": "old policy",
        "agent_or_flow": "",
        "known": [{"text": "approval optional", "source": "policy.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "changing-policy",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, root, model_config_id=model["id"]).json()
    assert {item["text"] for item in detail["understanding"]["known"]} == {
        "approval optional"
    }

    (root / "policy.md").write_text("Approval required.\n", encoding="utf-8")
    _RecordingHandler.body_override = {
        "summary": "new policy",
        "agent_or_flow": "",
        "known": [{"text": "approval required", "source": "policy.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    updated = client.post(f"/api/projects/{detail['project']['id']}/reanalyse")
    assert updated.status_code == 200, updated.text
    assert "approval optional" not in _RecordingHandler.requests[-1]["body"]
    texts = {item["text"] for item in updated.json()["understanding"]["known"]}
    assert "approval required" in texts
    assert "approval optional" not in texts

    _RecordingHandler.body_override = {
        "summary": "echoed",
        "agent_or_flow": "",
        "known": [
            {"text": "approval optional", "source": "policy.md"},
            {"text": "approval required", "source": "policy.md"},
        ],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    echoed = client.post(f"/api/projects/{detail['project']['id']}/reanalyse")
    assert echoed.status_code == 200, echoed.text
    echoed_texts = {
        item["text"] for item in echoed.json()["understanding"]["known"]
    }
    assert "approval required" in echoed_texts
    assert "approval optional" not in echoed_texts


def test_correction_survives_long_conversation_reanalysis(
    client: TestClient, project_root: Path, recording_server
) -> None:
    clean = {
        "summary": "kept",
        "agent_or_flow": "",
        "known": [],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "understanding": clean,
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "long-correction",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    correction = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "纠正：评测重点是审计记录。"},
    )
    assert correction.status_code == 200, correction.text

    for index in range(11):
        _RecordingHandler.body_override = {
            "reply": f"ok {index}",
            "continue_requested": False,
            "understanding": clean,
        }
        response = client.post(
            f"/api/projects/{project_id}/messages",
            json={"content": f"补充 {index}"},
        )
        assert response.status_code == 200, response.text

    _RecordingHandler.fail = True
    failed_reanalysis = client.post(f"/api/projects/{project_id}/reanalyse")
    assert failed_reanalysis.status_code == 200, failed_reanalysis.text
    assert failed_reanalysis.json()["project"]["analysis_error"]
    assert any(
        "评测重点是审计记录" in item.get("text", "")
        for item in failed_reanalysis.json()["understanding"]["known"]
    )

    _RecordingHandler.fail = False
    _RecordingHandler.body_override = clean
    reanalysed = client.post(f"/api/projects/{project_id}/reanalyse")
    assert reanalysed.status_code == 200, reanalysed.text
    assert "评测重点是审计记录" in _RecordingHandler.requests[-1]["body"]
    texts = {
        item["text"] for item in reanalysed.json()["understanding"]["known"]
    }
    assert any("评测重点是审计记录" in text for text in texts)


def test_chat_unknown_source_is_a_visible_error(
    client: TestClient, project_root: Path, recording_server
) -> None:
    model = client.post(
        "/api/model-configs",
        json={
            "name": "unknown-source",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "understanding": {
            "summary": "invented",
            "agent_or_flow": "",
            "known": [{"text": "invented fact", "source": "not-in-snapshot.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": True,
            "sufficient_reason": "invented",
        },
    }
    response = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "补充"},
    )
    assert response.status_code == 502, response.text
    refreshed = client.get(f"/api/projects/{detail['project']['id']}").json()
    assert any(
        (message.get("payload") or {}).get("kind") == "error"
        for message in refreshed["messages"]
    )
    assert refreshed["readiness"]["generation_allowed"] is False


def test_narrowed_reanalysis_does_not_send_removed_facts(
    client: TestClient, project_root: Path, recording_server
) -> None:
    _RecordingHandler.body_override = {
        "summary": "approval optional is the rule",
        "agent_or_flow": "approval optional flow",
        "known": [
            {"text": "approval optional", "source": "docs/RELEASE_POLICY.md"}
        ],
        "inferred": [],
        "unknowns": [{"text": "approval optional exception", "why": "old scope"}],
        "sufficient": False,
        "sufficient_reason": "approval optional pending",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "narrowed-input",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    updated = client.put(
        f"/api/projects/{project_id}/sources",
        json={
            "include_paths": ["README.md"],
            "exclude_patterns": [],
            "supplemental": [],
        },
    )
    assert updated.status_code == 200, updated.text
    body = _RecordingHandler.requests[-1]["body"]
    assert "approval optional" not in body
    assert "RELEASE_POLICY" not in body

    clean = {
        "summary": "README only",
        "agent_or_flow": "",
        "known": [{"text": "readme present", "source": "README.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    _RecordingHandler.body_override = clean
    again = client.post(f"/api/projects/{project_id}/reanalyse")
    assert again.status_code == 200, again.text
    assert "approval optional" not in _RecordingHandler.requests[-1]["body"]

    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "understanding": clean,
    }
    chat = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "补充"}
    )
    assert chat.status_code == 200, chat.text
    assert "approval optional" not in _RecordingHandler.requests[-1]["body"]

    _RecordingHandler.fail = True
    failed = client.post(f"/api/projects/{project_id}/reanalyse")
    assert failed.status_code == 200, failed.text
    assert failed.json()["project"]["analysis_error"]
    _RecordingHandler.fail = False
    _RecordingHandler.body_override = {
        "reply": "recovered",
        "continue_requested": False,
        "understanding": clean,
    }
    recovered = client.post(
        f"/api/projects/{project_id}/messages", json={"content": "补充"}
    )
    assert recovered.status_code == 200, recovered.text
    assert "approval optional" not in _RecordingHandler.requests[-1]["body"]


def test_chat_hides_newly_ignored_file(
    client: TestClient, tmp_path: Path, recording_server
) -> None:
    root = tmp_path / "chat-new-ignore"
    root.mkdir()
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    (root / "policy.md").write_text("policy secret\n", encoding="utf-8")
    _RecordingHandler.body_override = {
        "summary": "policy secret summary",
        "agent_or_flow": "",
        "known": [{"text": "policy secret", "source": "policy.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "chat-new-ignore",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, root, model_config_id=model["id"]).json()
    (root / ".gitignore").write_text("policy.md\n", encoding="utf-8")
    _RecordingHandler.body_override = {
        "reply": "ok",
        "continue_requested": False,
        "understanding": {
            "summary": "readme only",
            "agent_or_flow": "",
            "known": [],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": "pending",
        },
    }
    response = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "补充"},
    )
    assert response.status_code == 200, response.text
    body = _RecordingHandler.requests[-1]["body"]
    assert "policy secret" not in body


def test_chat_retires_facts_from_changed_file(
    client: TestClient, tmp_path: Path, recording_server
) -> None:
    root = tmp_path / "chat-changing-policy"
    root.mkdir()
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    (root / "policy.md").write_text("Approval optional.\n", encoding="utf-8")
    _RecordingHandler.body_override = {
        "summary": "old policy",
        "agent_or_flow": "",
        "known": [{"text": "approval optional", "source": "policy.md"}],
        "inferred": [],
        "unknowns": [],
        "sufficient": False,
        "sufficient_reason": "pending",
    }
    model = client.post(
        "/api/model-configs",
        json={
            "name": "chat-changing-policy",
            "provider": "openai_compatible",
            "base_url": f"http://127.0.0.1:{recording_server.server_port}/v1",
            "model_name": "fake",
        },
    ).json()
    detail = import_project(client, root, model_config_id=model["id"]).json()
    (root / "policy.md").write_text("Approval required.\n", encoding="utf-8")
    _RecordingHandler.body_override = {
        "reply": "noted",
        "continue_requested": False,
        "understanding": {
            "summary": "new policy",
            "agent_or_flow": "",
            "known": [{"text": "approval required", "source": "policy.md"}],
            "inferred": [],
            "unknowns": [],
            "sufficient": False,
            "sufficient_reason": "pending",
        },
    }
    response = client.post(
        f"/api/projects/{detail['project']['id']}/messages",
        json={"content": "补充"},
    )
    assert response.status_code == 200, response.text
    texts = {item["text"] for item in response.json()["understanding"]["known"]}
    assert "approval required" in texts
    assert "approval optional" not in texts


def test_chat_retires_facts_when_source_is_deleted(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    (project_root / "README.md").unlink()
    response = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "继续"},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert "README.md" not in {
        item.get("source") for item in updated["understanding"]["known"]
    }
    assert "README.md" not in {
        item["path"] for item in updated["snapshot"]["files"]
    }
    reanalysed = client.post(f"/api/projects/{project_id}/reanalyse")
    assert reanalysed.status_code == 200, reanalysed.text


def test_narrowed_scope_keeps_discussion_and_reanalysis_working(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    updated = client.put(
        f"/api/projects/{project_id}/sources",
        json={
            "include_paths": ["README.md"],
            "exclude_patterns": [],
            "supplemental": [],
        },
    )
    assert updated.status_code == 200, updated.text
    known = updated.json()["understanding"]["known"]
    assert "docs/RELEASE_POLICY.md" not in {
        item.get("source") for item in known
    }

    chat = client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "继续"},
    )
    assert chat.status_code == 200, chat.text

    reanalysed = client.post(f"/api/projects/{project_id}/reanalyse")
    assert reanalysed.status_code == 200, reanalysed.text
