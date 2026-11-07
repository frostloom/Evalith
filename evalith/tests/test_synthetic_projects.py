from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conftest import create_stub_model, import_project

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_two_synthetic_project_shapes_are_isolated(client: TestClient) -> None:
    """A stateful approval flow and a conversational support agent both import.

    They use different interaction shapes and must produce separate snapshots,
    sessions and understandings with no cross-project content.
    """
    model = create_stub_model(client)
    approval = import_project(
        client,
        EXAMPLES / "approval-agent",
        model_config_id=model["id"],
        name="Approval Agent (synthetic)",
    )
    support = import_project(
        client,
        EXAMPLES / "support-agent",
        model_config_id=model["id"],
        name="Support Agent (synthetic)",
    )
    assert approval.status_code == 201, approval.text
    assert support.status_code == 201, support.text
    approval_detail = approval.json()
    support_detail = support.json()

    assert approval_detail["session"]["id"] != support_detail["session"]["id"]
    assert approval_detail["snapshot"]["digest"] != support_detail["snapshot"]["digest"]
    assert approval_detail["understanding"]["summary"] != support_detail["understanding"]["summary"]

    approval_files = {item["path"] for item in approval_detail["snapshot"]["files"]}
    support_files = {item["path"] for item in support_detail["snapshot"]["files"]}
    assert "src/approval.py" in approval_files
    assert "src/reply.py" in support_files
    assert "src/reply.py" not in approval_files
    assert "src/approval.py" not in support_files

    assert approval_detail["readiness"]["generation_allowed"] is False
    assert support_detail["readiness"]["generation_allowed"] is False

    cross = client.get(
        f"/api/projects/{approval_detail['project']['id']}/sessions/"
        f"{support_detail['session']['id']}/messages"
    )
    assert cross.status_code == 404
