from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import create_stub_model, import_project


def test_reenter_returns_the_same_main_session(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    session_id = detail["session"]["id"]

    first = client.post(f"/api/projects/{project_id}/enter")
    second = client.post(f"/api/projects/{project_id}/enter")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["session"]["id"] == session_id
    assert second.json()["session"]["id"] == session_id
    assert len(first.json()["messages"]) >= 2
    assert first.json()["understanding"]["summary"] == second.json()["understanding"]["summary"]


def test_concurrent_entry_does_not_duplicate_main_session(
    client: TestClient, project_root: Path
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    service = client.app.state.service  # type: ignore[attr-defined]

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(
            executor.map(lambda _: service.ensure_session(project_id), range(24))
        )
    assert len(set(results)) == 1
    assert results[0] == detail["session"]["id"]
    assert client.app.state.db.count_sessions(project_id) == 1  # type: ignore[attr-defined]


def test_reopening_the_service_restores_session_and_context(
    client: TestClient, project_root: Path, settings
) -> None:
    model = create_stub_model(client)
    detail = import_project(client, project_root, model_config_id=model["id"]).json()
    project_id = detail["project"]["id"]
    session_id = detail["session"]["id"]
    client.post(
        f"/api/projects/{project_id}/messages",
        json={"content": "补充：审批失败需要人工处理。"},
    )
    message_count = len(client.get(f"/api/projects/{project_id}").json()["messages"])

    from evalith.api import create_app

    with TestClient(create_app(settings)) as reopened:
        restored = reopened.post(f"/api/projects/{project_id}/enter").json()
        assert restored["session"]["id"] == session_id
        assert restored["project"]["id"] == project_id
        assert len(restored["messages"]) == message_count
        assert restored["understanding"]["summary"]


def test_projects_are_isolated(client: TestClient, tmp_path: Path) -> None:
    root_a = tmp_path / "project-a"
    root_b = tmp_path / "project-b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "README.md").write_text("# Project A\nOnly A lives here.\n", encoding="utf-8")
    (root_b / "README.md").write_text("# Project B\nOnly B lives here.\n", encoding="utf-8")
    model = create_stub_model(client)
    a = import_project(client, root_a, model_config_id=model["id"], name="Project A").json()
    b = import_project(client, root_b, model_config_id=model["id"], name="Project B").json()

    assert a["session"]["id"] != b["session"]["id"]
    assert a["understanding"]["summary"] != b["understanding"]["summary"]
    a_text = str(a)
    b_text = str(b)
    assert "Only B lives here" not in a_text
    assert "Only A lives here" not in b_text

    a_messages = client.get(f"/api/projects/{a['project']['id']}").json()["messages"]
    assert all(item["id"] for item in a_messages)
    b_snapshot = b["snapshot"]
    assert {item["path"] for item in b_snapshot["files"]} == {"README.md"}

    # Knowing B's session id must not unlock A's session messages.
    cross = client.get(
        f"/api/projects/{a['project']['id']}/sessions/{b['session']['id']}/messages"
    )
    assert cross.status_code == 404
    own = client.get(
        f"/api/projects/{a['project']['id']}/sessions/{a['session']['id']}/messages"
    )
    assert own.status_code == 200
    assert all(item["content"] for item in own.json()["messages"])


def test_missing_or_unknown_project_is_refused(client: TestClient) -> None:
    assert client.get("/api/projects/prj_missing").status_code == 404
    assert client.post("/api/projects/prj_missing/enter").status_code == 404
