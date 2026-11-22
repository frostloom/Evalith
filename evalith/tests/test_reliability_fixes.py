"""Review 2026-11-21 D6/D8: persistence honesty in the library.

D6: a generation and its tasks commit as one transaction — a failure
half-way can no longer leave a "completed" generation with a partial
task set.

D8: editing a grader without touching its model binding keeps the
binding (same policy as task_kinds/source_refs); only an explicit null
clears it, and a changed binding still revalidates.
"""

import pytest
from test_evaluation_assets import setup_assets, task_spec
from evalith.evaluation_store import EvaluationStore
from evalith.model_gateway import ModelGateway
from evalith.service import WorkspaceError


class TestGenerationIsAtomic:
    def test_failure_persists_no_generation_and_no_tasks(
        self, client, project_root, monkeypatch
    ):
        assets, project_id = setup_assets(client, project_root)
        client.post(f"/api/projects/{project_id}/continue")
        monkeypatch.setattr(
            ModelGateway, "complete_json", lambda *_: {"tasks": [task_spec()]}
        )
        before_tasks = len(assets.list(project_id))

        def failing_bundle(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(EvaluationStore, "create_bundle", failing_bundle)
        with pytest.raises(RuntimeError):
            assets.generate(project_id, count=1)

        generations = [
            r for r in assets.store.list(project_id, "generation")
        ]
        assert generations == []
        assert len(assets.list(project_id)) == before_tasks

    def test_success_wires_generation_into_every_task(
        self, client, project_root, monkeypatch
    ):
        assets, project_id = setup_assets(client, project_root)
        client.post(f"/api/projects/{project_id}/continue")
        monkeypatch.setattr(
            ModelGateway, "complete_json", lambda *_: {"tasks": [task_spec()]}
        )
        result = assets.generate(project_id, count=1)
        stored_generation = assets.store.get(
            project_id, "generation", result["generation_id"]
        )
        assert stored_generation["status"] == "completed"
        for item in result["items"]:
            assert item["generation_id"] == result["generation_id"]
            assert item["version"] == 1


class TestGraderEditKeepsModelBinding:
    def _grader(self, library, pid, model_id):
        return library.save_grader(
            pid,
            {
                "name": "绑定判分模型",
                "description": "d",
                "rubric": "r",
                "steps": ["step"],
                "check": {"type": "judge", "expected": "正确"},
                "threshold": 0.9,
                "model_config_id": model_id,
            },
        )

    def test_edit_without_model_key_preserves_binding(self, client, project_root):
        from evalith.evaluation_library import EvaluationLibrary
        from test_evaluation_library import setup as library_setup

        pid, model, ws, store, task = library_setup(client, project_root)
        library = EvaluationLibrary(ws, store)
        created = self._grader(library, pid, model["id"])
        assert created["model_config_id"] == model["id"]

        edited = library.save_grader(
            pid,
            {
                "name": created["name"],
                "description": "new description",
                "rubric": "new rubric",
                "steps": ["new step"],
                "check": created["check"],
                "threshold": created["threshold"],
            },
            created["id"],
        )
        assert edited["model_config_id"] == model["id"]
        assert edited["version"] == created["version"] + 1

    def test_explicit_null_clears_binding(self, client, project_root):
        from evalith.evaluation_library import EvaluationLibrary
        from test_evaluation_library import setup as library_setup

        pid, model, ws, store, task = library_setup(client, project_root)
        library = EvaluationLibrary(ws, store)
        created = self._grader(library, pid, model["id"])
        cleared = library.save_grader(
            pid,
            {
                "name": created["name"],
                "description": "d",
                "rubric": "r",
                "steps": ["s"],
                "check": created["check"],
                "threshold": created["threshold"],
                "model_config_id": None,
            },
            created["id"],
        )
        assert cleared["model_config_id"] is None
