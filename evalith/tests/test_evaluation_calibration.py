"""Grader calibration against user-supplied known-outcome samples.

Calibration must reuse the exact runtime judge semantics; these tests run
without any real model call (the gateway is monkeypatched) except the
explicit synchronous rejections.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from evalith.model_gateway import ModelGateway
from fastapi.testclient import TestClient


def setup_project(client: TestClient, project_root: Path):
    from conftest import create_stub_model, import_project

    model = create_stub_model(client)
    pid = (
        import_project(
            client, project_root, model_config_id=model["id"], include=["README.md"]
        )
        .json()["project"]["id"]
    )
    client.post(f"/api/projects/{pid}/continue")
    real = client.post(
        "/api/model-configs",
        json={
            "name": "calibration target",
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "model_name": "gpt-test",
        },
    ).json()
    return pid, model, real


def judge_grader(model_id: str | None) -> dict:
    return {
        "name": "Answer correctness",
        "description": "Check evidence",
        "rubric": "Answer must match the observed facts",
        "steps": ["Read evidence", "Compare answer"],
        "check": {"type": "judge", "expected": "Match facts"},
        "model_config_id": model_id,
        "threshold": 0.8,
        "task_kinds": ["conversation"],
    }


def verdict(passed: bool, document: str) -> dict:
    return {
        "checks": [
            {
                "index": 0,
                "passed": passed,
                "score": 0.95 if passed else 0.2,
                "reason": "证据与判断要求一致" if passed else "证据不足",
                "evidence": [document[:12]],
            }
        ]
    }


def wait_job(client: TestClient, pid: str, job_id: str) -> dict:
    deadline = time.monotonic() + 5
    job = None
    while time.monotonic() < deadline:
        job = client.get(f"/api/projects/{pid}/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"calibration job did not finish: {job}")


def start(client: TestClient, pid: str, gid: str, samples: list[dict]):
    return client.post(
        f"/api/projects/{pid}/graders/{gid}/calibrations", json={"samples": samples}
    )


SAMPLES = [
    {
        "name": "known good",
        "document": "balance query answered 100 with audit row present",
        "expected": "pass",
    },
    {
        "name": "known wrong",
        "document": "reply without supporting evidence, facts missing",
        "expected": "fail",
    },
]


def test_matched_samples_mark_grader_calibrated_and_edit_resets(
    client: TestClient, project_root: Path, monkeypatch
):
    pid, _stub, model = setup_project(client, project_root)
    gid = client.post(
        f"/api/projects/{pid}/graders", json=judge_grader(model["id"])
    ).json()["id"]
    monkeypatch.setattr(
        ModelGateway,
        "complete_json",
        lambda self, system, payload: verdict(
            "audit row" in payload["observed"], payload["observed"]
        ),
    )
    started = start(client, pid, gid, SAMPLES)
    assert started.status_code == 202, started.text
    job = wait_job(client, pid, started.json()["id"])
    assert job["status"] == "completed", job
    assert job["result"]["state"] == "calibrated"

    graders = client.get(f"/api/projects/{pid}/graders").json()["items"]
    grader = next(g for g in graders if g["id"] == gid)
    assert grader["calibration_state"] == "calibrated"
    assert grader["last_calibration_id"] == job["result"]["calibration_id"]

    report = client.get(
        f"/api/projects/{pid}/calibrations/{job['result']['calibration_id']}"
    ).json()
    assert report["grader_version"] == grader["version"]
    assert report["summary"] == {"total": 2, "matched": 2}
    assert all(sample["matched"] for sample in report["samples"])
    assert report["model_config_id"] == model["id"]

    listing = client.get(f"/api/projects/{pid}/graders/{gid}/calibrations").json()
    assert [item["id"] for item in listing["items"]] == [report["id"]]

    edited = client.put(
        f"/api/projects/{pid}/graders/{gid}",
        json={**judge_grader(model["id"]), "rubric": "Stricter rubric"},
    ).json()
    assert edited["version"] == grader["version"] + 1
    assert edited["calibration_state"] == "unverified"
    assert edited["last_calibration_id"] is None


def test_disagreement_records_mismatched_samples(
    client: TestClient, project_root: Path, monkeypatch
):
    pid, _stub, model = setup_project(client, project_root)
    gid = client.post(
        f"/api/projects/{pid}/graders", json=judge_grader(model["id"])
    ).json()["id"]
    monkeypatch.setattr(
        ModelGateway,
        "complete_json",
        lambda self, system, payload: verdict(True, payload["observed"]),
    )
    job = wait_job(client, pid, start(client, pid, gid, SAMPLES).json()["id"])
    assert job["result"]["state"] == "disagreement"
    report = client.get(
        f"/api/projects/{pid}/calibrations/{job['result']['calibration_id']}"
    ).json()
    mismatched = [s for s in report["samples"] if not s["matched"]]
    assert [s["name"] for s in mismatched] == ["known wrong"]
    assert mismatched[0]["expected"] == "fail"
    assert mismatched[0]["actual"] == "pass"
    grader = client.get(f"/api/projects/{pid}/graders/{gid}").json()
    assert grader["calibration_state"] == "disagreement"


def test_unquoted_evidence_becomes_missing_evidence(
    client: TestClient, project_root: Path, monkeypatch
):
    pid, _stub, model = setup_project(client, project_root)
    gid = client.post(
        f"/api/projects/{pid}/graders", json=judge_grader(model["id"])
    ).json()["id"]

    def fabricated(self, system, payload):
        reply = verdict(True, payload["observed"])
        reply["checks"][0]["evidence"] = ["quote that appears nowhere in the document"]
        return reply

    monkeypatch.setattr(ModelGateway, "complete_json", fabricated)
    samples = [{**SAMPLES[0], "expected": "missing_evidence"}]
    job = wait_job(client, pid, start(client, pid, gid, samples).json()["id"])
    report = client.get(
        f"/api/projects/{pid}/calibrations/{job['result']['calibration_id']}"
    ).json()
    assert report["samples"][0]["actual"] == "missing_evidence"
    assert report["samples"][0]["matched"] is True


def test_calibration_rejects_unusable_graders_synchronously(
    client: TestClient, project_root: Path
):
    pid, _stub, _model = setup_project(client, project_root)
    deterministic = client.post(
        f"/api/projects/{pid}/graders",
        json={
            **judge_grader(None),
            "name": "Deterministic standard",
            "check": {"type": "contains", "expected": "hello"},
        },
    ).json()["id"]
    rejected = start(client, pid, deterministic, SAMPLES)
    assert rejected.status_code == 422, rejected.text
    assert "judge" in rejected.json()["error"]

    modelless = client.post(
        f"/api/projects/{pid}/graders",
        json={**judge_grader(None), "name": "Modelless standard"},
    ).json()["id"]
    rejected = start(client, pid, modelless, SAMPLES)
    assert rejected.status_code == 422, rejected.text
    assert "模型" in rejected.json()["error"]

    stub_bound = client.post(
        f"/api/projects/{pid}/graders",
        json={**judge_grader(_stub["id"]), "name": "Stub-bound standard"},
    ).json()["id"]
    rejected = start(client, pid, stub_bound, SAMPLES)
    assert rejected.status_code == 422, rejected.text
    assert "离线" in rejected.json()["error"]

    empty = start(client, pid, stub_bound, [])
    assert empty.status_code == 422


def test_midjob_edit_marks_report_stale_without_state_change(
    client: TestClient, project_root: Path, monkeypatch
):
    pid, _stub, model = setup_project(client, project_root)
    gid = client.post(
        f"/api/projects/{pid}/graders", json=judge_grader(model["id"])
    ).json()["id"]

    def editing(self, system, payload):
        edited = client.put(
            f"/api/projects/{pid}/graders/{gid}",
            json={**judge_grader(model["id"]), "rubric": "Changed mid-job"},
        )
        assert edited.status_code == 200, edited.text
        return verdict("audit row" in payload["observed"], payload["observed"])

    monkeypatch.setattr(ModelGateway, "complete_json", editing)
    job = wait_job(client, pid, start(client, pid, gid, SAMPLES).json()["id"])
    assert job["status"] == "completed", job
    assert job["result"]["stale"] is True
    assert job["result"]["state"] is None
    report = client.get(
        f"/api/projects/{pid}/calibrations/{job['result']['calibration_id']}"
    ).json()
    assert report["stale"] is True
    grader = client.get(f"/api/projects/{pid}/graders/{gid}").json()
    assert grader["calibration_state"] == "unverified"


def test_second_calibration_for_same_grader_is_rejected_while_running(
    client: TestClient, project_root: Path, monkeypatch
):
    pid, _stub, model = setup_project(client, project_root)
    gid = client.post(
        f"/api/projects/{pid}/graders", json=judge_grader(model["id"])
    ).json()["id"]
    release = threading.Event()

    def slow(self, system, payload):
        release.wait(timeout=5)
        return verdict("audit row" in payload["observed"], payload["observed"])

    monkeypatch.setattr(ModelGateway, "complete_json", slow)
    first = start(client, pid, gid, SAMPLES)
    assert first.status_code == 202, first.text
    second = start(client, pid, gid, SAMPLES)
    assert second.status_code == 409, second.text
    release.set()
    job = wait_job(client, pid, first.json()["id"])
    assert job["status"] == "completed", job


def test_malformed_judge_response_fails_the_job_visibly(
    client: TestClient, project_root: Path, monkeypatch
):
    pid, _stub, model = setup_project(client, project_root)
    gid = client.post(
        f"/api/projects/{pid}/graders", json=judge_grader(model["id"])
    ).json()["id"]
    monkeypatch.setattr(
        ModelGateway,
        "complete_json",
        lambda self, system, payload: {"checks": "garbage"},
    )
    started = start(client, pid, gid, SAMPLES[:1])
    job = wait_job(client, pid, started.json()["id"])
    assert job["status"] == "failed", job
    assert "没有返回检查列表" in (job["error"] or "")
    grader = client.get(f"/api/projects/{pid}/graders/{gid}").json()
    assert grader["calibration_state"] == "unverified"
    assert (
        client.get(f"/api/projects/{pid}/graders/{gid}/calibrations").json()["items"]
        == []
    )
