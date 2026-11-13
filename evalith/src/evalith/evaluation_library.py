"""Reusable grading standards and named project test collections."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .evaluation_assets import CheckSpec, EvaluationAssets
from .evaluation_store import EvaluationStore
from .service import WorkspaceError, WorkspaceService


class GraderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    rubric: str = Field(min_length=1, max_length=6000)
    steps: list[str] = Field(default_factory=list, max_length=16)
    check: CheckSpec
    model_config_id: str | None = None
    threshold: float = Field(default=0.8, ge=0, le=1, strict=True)
    task_kinds: list[Literal["conversation", "command", "http"]] = Field(
        default_factory=lambda: ["conversation", "command", "http"],
        min_length=1,
        max_length=3,
    )
    source_refs: list[str] = Field(default_factory=list, max_length=30)
    uncertainties: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="before")
    @classmethod
    def infer_file_scope(cls, value):
        if (
            isinstance(value, dict)
            and "task_kinds" not in value
            and str((value.get("check") or {}).get("type", "")).startswith("file_")
        ):
            return {**value, "task_kinds": ["command"]}
        return value

    @model_validator(mode="after")
    def valid_scope(self):
        if len(set(self.task_kinds)) != len(self.task_kinds):
            raise ValueError("标准适用类型不能重复")
        if self.check.type.startswith("file_") and self.task_kinds != ["command"]:
            raise ValueError("文件检查仅适用于 command 题目")
        if any(not s.strip() or len(s) > 1200 for s in self.steps):
            raise ValueError("检查步骤无效")
        return self


class SetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    task_ids: list[str] = Field(min_length=1, max_length=60)
    grader_ids: list[str] = Field(default_factory=list, max_length=16)


class EvaluationLibrary:
    def __init__(self, workspace: WorkspaceService, store: EvaluationStore):
        self.workspace, self.store = workspace, store

    def list_graders(self, pid: str):
        EvaluationAssets(self.workspace, self.store).list(pid)
        return [g for g in self.store.list(pid, "grader") if g["status"] == "active"]

    def grader(self, pid: str, identifier: str):
        record = self.store.get(pid, "grader", identifier)
        if record["status"] != "active":
            raise WorkspaceError("评价标准已归档，请重新选择", status_code=409)
        return record

    def save_grader(
        self, pid: str, payload: dict[str, Any], identifier: str | None = None
    ):
        with self.workspace._project_lock(pid):
            existing = self.list_graders(pid)
            old = self.grader(pid, identifier) if identifier else {}
            payload = {
                **{
                    k: old[k]
                    for k in ("task_kinds", "source_refs", "uncertainties")
                    if k in old
                },
                **payload,
            }
            try:
                safe = json.loads(
                    self.workspace._scrub_saved_secrets(
                        json.dumps(payload, ensure_ascii=False, allow_nan=False)
                    )
                )
                spec = GraderSpec.model_validate(safe).model_dump()
                if any(not step.strip() or len(step) > 1200 for step in spec["steps"]):
                    raise ValueError("检查步骤无效")
            except (ValidationError, ValueError, TypeError) as exc:
                raise WorkspaceError(
                    "评价标准格式无效：" + str(exc)[:300], status_code=422
                ) from exc
            if spec["model_config_id"]:
                self.workspace.gateway_for(spec["model_config_id"])
            if any(
                g["name"].casefold() == spec["name"].casefold()
                and g["id"] != identifier
                for g in existing
            ):
                raise WorkspaceError("已有同名评价标准", status_code=409)
            if identifier:
                old = self.grader(pid, identifier)
                return self.store.update(
                    pid, "grader", identifier, **spec, version=old["version"] + 1
                )
            return self.store.create(
                pid,
                "grader",
                {**spec, "version": 1, "calibration_state": "unverified"},
                status="active",
            )

    def list_sets(self, pid: str):
        tasks = EvaluationAssets(self.workspace, self.store).list(pid)
        persisted = self.store.list(pid, "test_set")
        prepared = {s.get("generation_id") for s in persisted if s.get("generation_id")}
        groups = {}
        for task in tasks:
            groups.setdefault(task.get("generation_id") or "manual", []).append(task)
        result = {}
        for group, items in groups.items():
            if group in prepared:
                continue
            identifier = "set_auto_" + hashlib.sha256(group.encode()).hexdigest()[:16]
            categories = list(dict.fromkeys(t["definition"]["category"] for t in items))
            result[identifier] = {
                "id": identifier,
                "project_id": pid,
                "name": " / ".join(categories)[:100]
                if group != "manual"
                else "手工测试集",
                "description": "由同一次生成的题目组成，可调整成员和评价标准。"
                if group != "manual"
                else "当前项目中手工建立的测试题目。",
                "task_ids": [t["id"] for t in items],
                "grader_ids": [],
                "status": "active",
                "origin": "generated" if group != "manual" else "manual",
                "created_at": items[-1]["created_at"],
            }
        for record in persisted:
            if record["status"] == "archived":
                result.pop(record["id"], None)
            else:
                result[record["id"]] = record
        return sorted(
            result.values(),
            key=lambda item: (
                item["created_at"],
                not item["id"].startswith("set_auto_"),
                item["id"],
            ),
            reverse=True,
        )

    def collection(self, pid: str, identifier: str):
        record = next((s for s in self.list_sets(pid) if s["id"] == identifier), None)
        if record is None:
            raise WorkspaceError("测试集不存在", status_code=404)
        return record

    def save_set(
        self, pid: str, payload: dict[str, Any], identifier: str | None = None
    ):
        with self.workspace._project_lock(pid):
            EvaluationAssets(self.workspace, self.store).list(pid)
            try:
                spec = SetSpec.model_validate(payload).model_dump()
            except ValidationError as exc:
                raise WorkspaceError(
                    "测试集格式无效：" + str(exc)[:300], status_code=422
                ) from exc
            if len(set(spec["task_ids"])) != len(spec["task_ids"]) or len(
                set(spec["grader_ids"])
            ) != len(spec["grader_ids"]):
                raise WorkspaceError("成员不能重复", status_code=422)
            for tid in spec["task_ids"]:
                self.store.get(pid, "task", tid)
            for gid in spec["grader_ids"]:
                self.grader(pid, gid)
            if identifier:
                self.collection(pid, identifier)
                try:
                    self.store.get(pid, "test_set", identifier)
                except WorkspaceError:
                    return self.store.create(
                        pid, "test_set", spec, status="active", record_id=identifier
                    )
                return self.store.update(pid, "test_set", identifier, **spec)
            return self.store.create(pid, "test_set", spec, status="active")


def install_library_routes(
    app: FastAPI, workspace: WorkspaceService, store: EvaluationStore
):
    library = EvaluationLibrary(workspace, store)
    app.state.evaluation_library = library

    @app.get("/api/projects/{pid}/graders")
    def graders(pid: str):
        return {"items": library.list_graders(pid)}

    @app.get("/api/projects/{pid}/graders/{gid}")
    def grader(pid: str, gid: str):
        return library.grader(pid, gid)

    @app.post("/api/projects/{pid}/graders", status_code=201)
    def add_grader(pid: str, payload: dict[str, Any]):
        return library.save_grader(pid, payload)

    @app.put("/api/projects/{pid}/graders/{gid}")
    def edit_grader(pid: str, gid: str, payload: dict[str, Any]):
        return library.save_grader(pid, payload, gid)

    @app.delete("/api/projects/{pid}/graders/{gid}", status_code=204)
    def archive_grader(pid: str, gid: str):
        library.grader(pid, gid)
        store.update(pid, "grader", gid, status="archived")
        return Response(status_code=204)

    @app.get("/api/projects/{pid}/test-sets")
    def sets(pid: str):
        return {"items": library.list_sets(pid)}

    @app.get("/api/projects/{pid}/test-sets/{sid}")
    def collection(pid: str, sid: str):
        return library.collection(pid, sid)

    @app.post("/api/projects/{pid}/test-sets", status_code=201)
    def add_set(pid: str, payload: dict[str, Any]):
        return library.save_set(pid, payload)

    @app.put("/api/projects/{pid}/test-sets/{sid}")
    def edit_set(pid: str, sid: str, payload: dict[str, Any]):
        return library.save_set(pid, payload, sid)
