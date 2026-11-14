"""Calibrate judge graders against user-supplied known-outcome samples.

A calibration runs the exact runtime judge path — the same ``grader_check``
criteria compilation, judge system prompt, verbatim-evidence validation and
threshold semantics — against fixed sample documents, records an immutable
report, and only then updates the grader version's calibration state.
Agreement on supplied samples is evidence about the grader, never proof of
business truth.
"""

from __future__ import annotations

import threading
from typing import Any, Literal

from fastapi import Body, FastAPI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .evaluation_library import EvaluationLibrary
from .evaluation_runner import JUDGE_SYSTEM_PROMPT
from .evaluation_store import EvaluationStore
from .grading_plan import grader_check
from .service import WorkspaceError, WorkspaceService


class CalibrationSample(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    document: str = Field(min_length=1, max_length=40000)
    expected: Literal["pass", "fail", "missing_evidence"]


class CalibrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    samples: list[CalibrationSample] = Field(min_length=1, max_length=20)
    model_config_id: str | None = None

    @model_validator(mode="after")
    def unique_names(self):
        names = [sample.name.casefold() for sample in self.samples]
        if len(set(names)) != len(names):
            raise ValueError("样本名称不能重复")
        return self


class EvaluationCalibration:
    def __init__(self, workspace: WorkspaceService, store: EvaluationStore):
        self.workspace, self.store = workspace, store

    # ------------------------------------------------------------------
    # synchronous validation and job creation
    # ------------------------------------------------------------------
    def start(self, pid: str, gid: str, payload: dict[str, Any]) -> dict[str, Any]:
        grader = EvaluationLibrary(self.workspace, self.store).grader(pid, gid)
        if grader["check"]["type"] != "judge":
            raise WorkspaceError(
                "仅 judge 评价标准支持校准；确定性检查按固定规则执行，无需模型校准",
                status_code=422,
                code="calibration_not_judge",
            )
        try:
            request = CalibrationRequest.model_validate(payload)
        except ValidationError as exc:
            raise WorkspaceError(
                "校准请求无效：" + str(exc)[:300], status_code=422
            ) from exc
        model_id = request.model_config_id or grader.get("model_config_id")
        if not model_id:
            raise WorkspaceError(
                "校准需要明确的评分模型：标准未绑定模型时请在请求中指定",
                status_code=422,
                code="calibration_model_required",
            )
        self.workspace.require_supported_model_config(model_id)
        row = self.workspace.db.get_model_config(model_id)
        if row is not None and row["provider"] == "stub":
            raise WorkspaceError(
                "离线演示模型不能校准真实评分行为，请选择 OpenAI 兼容服务模型",
                status_code=422,
                code="calibration_stub_model",
            )
        gateway = self.workspace.gateway_for(model_id)
        with self.workspace._project_lock(pid):
            if any(
                job["status"] in ("pending", "running")
                and job.get("operation") == "calibration"
                and job.get("grader_id") == gid
                for job in self.store.list(pid, "job")
            ):
                raise WorkspaceError(
                    "该标准已有校准任务在运行",
                    status_code=409,
                    code="calibration_busy",
                )
            record = self.store.create(
                pid,
                "job",
                {
                    "operation": "calibration",
                    "grader_id": gid,
                    "grader_version": grader["version"],
                    "grader_name": grader["name"],
                    "model": gateway.name,
                    "model_config_id": model_id,
                    "count": len(request.samples),
                    "usage": None,
                    "result": None,
                    "error": None,
                },
            )

        def execute() -> None:
            self.store.update(pid, "job", record["id"], status="running")
            try:
                result = self._execute(pid, gid, grader, request, model_id, gateway)
                self.store.update(
                    pid,
                    "job",
                    record["id"],
                    status="completed",
                    usage=result.pop("usage"),
                    result=result,
                )
            except Exception as exc:  # job records must fail visibly, not silently
                self.store.update(
                    pid,
                    "job",
                    record["id"],
                    status="failed",
                    error=self.workspace._scrub_saved_secrets(str(exc))[:1500],
                )

        threading.Thread(
            target=execute, name="evalith-calibration-" + record["id"], daemon=True
        ).start()
        return record

    # ------------------------------------------------------------------
    # background execution
    # ------------------------------------------------------------------
    def _execute(
        self,
        pid: str,
        gid: str,
        grader: dict[str, Any],
        request: CalibrationRequest,
        model_id: str,
        gateway,
    ) -> dict[str, Any]:
        check = grader_check(grader)
        samples = []
        usage_total = {"input_tokens": 0, "output_tokens": 0}
        for sample in request.samples:
            document = sample.document
            value = gateway.complete_json(
                JUDGE_SYSTEM_PROMPT,
                {
                    "task": {
                        "title": f"校准样本：{sample.name}",
                        "rubric": grader["rubric"],
                    },
                    "criteria": [{"index": 0, **check}],
                    "observed": document,
                },
            )
            for key in usage_total:
                number = (gateway.last_usage or {}).get(key)
                if isinstance(number, int) and not isinstance(number, bool):
                    usage_total[key] += number
            provided = value.get("checks")
            judged = next(
                (
                    item
                    for item in (provided if isinstance(provided, list) else [])
                    if isinstance(item, dict) and item.get("index") == 0
                ),
                None,
            )
            actual, score, reason, evidence = self._verdict(judged, check, document)
            samples.append(
                {
                    "name": sample.name,
                    "expected": sample.expected,
                    "actual": actual,
                    "matched": actual == sample.expected,
                    "score": score,
                    "reason": self.workspace._scrub_saved_secrets(reason)[:2000],
                    "evidence": evidence,
                }
            )
        matched = sum(1 for item in samples if item["matched"])
        stale = self.store.get(pid, "grader", gid)["version"] != grader["version"]
        state = (
            None
            if stale
            else ("calibrated" if matched == len(samples) else "disagreement")
        )
        report = self.store.create(
            pid,
            "calibration",
            {
                "grader_id": gid,
                "grader_version": grader["version"],
                "grader_name": grader["name"],
                "model_config_id": model_id,
                "model": gateway.name,
                "samples": samples,
                "summary": {"total": len(samples), "matched": matched},
                "state": state,
                "stale": stale,
                "usage": {
                    "input_tokens": usage_total["input_tokens"] or None,
                    "output_tokens": usage_total["output_tokens"] or None,
                    "cost_usd": None,
                },
            },
        )
        if not stale:
            self.store.update(
                pid,
                "grader",
                gid,
                calibration_state=state,
                last_calibration_id=report["id"],
            )
        return {
            "calibration_id": report["id"],
            "state": state,
            "stale": stale,
            "usage": report["usage"],
        }

    @staticmethod
    def _verdict(judged, check, document):
        """Apply the runtime judge validation to one sample."""
        if (
            not isinstance(judged, dict)
            or type(judged.get("passed")) is not bool
            or type(judged.get("score")) not in (int, float)
            or not 0 <= judged["score"] <= 1
        ):
            return "missing_evidence", None, "评分模型缺少有效判断", []
        evidence = judged.get("evidence")
        if (
            not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(q, str) or not q or q not in document for q in evidence)
        ):
            return "missing_evidence", None, "评分没有引用可核对的实际证据", []
        status = (
            "pass"
            if judged["passed"] and judged["score"] >= check.get("threshold", 0.8)
            else "fail"
        )
        reason = judged.get("reason", "")
        return status, judged["score"], str(reason)[:2000], evidence

    # ------------------------------------------------------------------
    # read paths
    # ------------------------------------------------------------------
    def reports(self, pid: str, gid: str) -> list[dict[str, Any]]:
        self.store.get(pid, "grader", gid)
        items = [
            record
            for record in self.store.list(pid, "calibration")
            if record.get("grader_id") == gid
        ]
        return sorted(items, key=lambda item: item["created_at"], reverse=True)

    def report(self, pid: str, cid: str) -> dict[str, Any]:
        return self.store.get(pid, "calibration", cid)


def install_calibration_routes(
    app: FastAPI, workspace: WorkspaceService, store: EvaluationStore
):
    calibration = EvaluationCalibration(workspace, store)
    app.state.evaluation_calibration = calibration

    @app.post("/api/projects/{pid}/graders/{gid}/calibrations", status_code=202)
    def start_calibration(
        pid: str, gid: str, payload: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        return calibration.start(pid, gid, payload)

    @app.get("/api/projects/{pid}/graders/{gid}/calibrations")
    def list_calibrations(pid: str, gid: str) -> dict[str, Any]:
        return {"items": calibration.reports(pid, gid)}

    @app.get("/api/projects/{pid}/calibrations/{cid}")
    def calibration_report(pid: str, cid: str) -> dict[str, Any]:
        return calibration.report(pid, cid)
