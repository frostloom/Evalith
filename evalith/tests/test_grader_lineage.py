"""Review 2026-11-21 D2/D18: grader lineage must be auditable and
archived graders must stay readable.

Tasks have always kept an immutable version row per edit; graders only
bumped a counter, so "calibration used grader v3" became unauditable
the moment v4 was saved. Graders now version symmetrically, archived
graders keep a read-only path, and version contents are retrievable.
"""

import pytest
from test_evaluation_library import grader, setup


def create(client, pid, model, name="标准A"):
    response = client.post(
        f"/api/projects/{pid}/graders",
        json={**grader(model), "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestGraderVersioning:
    def test_edit_writes_immutable_version_rows(self, client, project_root):
        pid, model, ws, store, task = setup(client, project_root)
        created = create(client, pid, model)
        gid = created["id"]

        v1 = client.get(f"/api/projects/{pid}/graders/{gid}/versions").json()
        assert [item["version"] for item in v1["items"]] == [1]
        assert v1["items"][0]["rubric"] == created["rubric"]

        edited = client.put(
            f"/api/projects/{pid}/graders/{gid}",
            json={**grader(model), "name": created["name"], "rubric": "新判定标准"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["version"] == 2

        v2 = client.get(f"/api/projects/{pid}/graders/{gid}/versions").json()
        assert [item["version"] for item in v2["items"]] == [2, 1]
        rubrics = {item["version"]: item["rubric"] for item in v2["items"]}
        assert rubrics[1] == grader(model)["rubric"]
        assert rubrics[2] == "新判定标准"

    def test_version_content_survives_later_edits(self, client, project_root):
        pid, model, ws, store, task = setup(client, project_root)
        created = create(client, pid, model)
        gid = created["id"]
        first_version_id = created.get("version_id") or client.get(
            f"/api/projects/{pid}/graders/{gid}/versions"
        ).json()["items"][-1]["id"]

        client.put(
            f"/api/projects/{pid}/graders/{gid}",
            json={**grader(model), "name": created["name"], "steps": ["完全不同的步骤"]},
        )
        stored = store.grader_version(pid, first_version_id)
        assert stored["steps"] == grader(model)["steps"]


class TestArchivedGradersStayReadable:
    def test_archive_keeps_read_access(self, client, project_root):
        pid, model, ws, store, task = setup(client, project_root)
        created = create(client, pid, model)
        gid = created["id"]
        assert (
            client.delete(f"/api/projects/{pid}/graders/{gid}").status_code == 204
        )
        # Read-only access survives archiving.
        fetched = client.get(f"/api/projects/{pid}/graders/{gid}")
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "archived"
        # The active list filters it; the archived list still shows it.
        active = client.get(f"/api/projects/{pid}/graders").json()["items"]
        assert all(item["id"] != gid for item in active)
        archived = client.get(
            f"/api/projects/{pid}/graders?include_archived=1"
        ).json()["items"]
        assert any(item["id"] == gid and item["status"] == "archived" for item in archived)
        # Editing stays refused.
        assert (
            client.put(
                f"/api/projects/{pid}/graders/{gid}", json=grader(model)
            ).status_code
            == 409
        )
