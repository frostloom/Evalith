#!/usr/bin/env python3
"""Drive the stage 0 runtime check against a running Rhesis stack.

The script only uses the public HTTP API and the local stub services. It creates a
synthetic project, model connection, endpoint, test set, test and metric, runs the test
against a deterministic target, then compares Rhesis' own verdict with an independent
state verifier.

Nothing here calls a real model: the model endpoint is the deterministic stub in
``stub_services.py``. The target is also a stub. The run proves interface behaviour, not
model capability.

Usage:
    python3 stage0/rhesis-flow/seed.py --base-url http://127.0.0.1:8080

The stack must already be running (see stage0/rhesis-flow/README.md), and the stub
container must be attached to the stack network so the backend can resolve
``stage0-stub``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
EVIDENCE = REPO / "stage0" / "evidence" / "rhesis-runtime"
STUB_DATA = EVIDENCE
SAMPLE_STATE = REPO / "stage0" / "harness" / "fixtures" / "project" / "data" / "sample_state.json"
VERIFIER = REPO / "stage0" / "harness" / "verifier" / "verify.py"
SAMPLE_STATE_DATA = json.loads(SAMPLE_STATE.read_text(encoding="utf-8"))
UNTOUCHED_SNAPSHOT = SAMPLE_STATE_DATA["artifacts"]["doc-18"]
TOKEN: Optional[str] = None
BASE_URL = "http://127.0.0.1:8080"
STAMP = str(int(time.time()))


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: str):
        super().__init__(f"{method} {path} -> HTTP {status}: {body[:1000]}")
        self.status = status
        self.body = body


def api(method: str, path: str, payload: Any = None, project_id: Optional[str] = None) -> Any:
    url = BASE_URL.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if project_id:
        headers["X-Project-Id"] = project_id
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        raise ApiError(method, path, error.code, body) from error


def login() -> str:
    payload = api("POST", "/auth/local-login", {})
    auth_code = payload.get("auth_code")
    if not auth_code:
        raise RuntimeError(f"local-login did not return auth_code: {payload}")
    tokens = api("POST", "/auth/exchange-code", {"code": auth_code})
    access_token = tokens.get("access_token") or tokens.get("session_token")
    if not access_token:
        raise RuntimeError(f"exchange-code did not return a token: {tokens}")
    return access_token


def type_lookups() -> list[dict]:
    return api("GET", "/type_lookups?limit=100")


def find_type(items: list[dict], type_name: str, type_value: str) -> dict:
    for item in items:
        if item.get("type_name") == type_name and item.get("type_value") == type_value:
            return item
    raise RuntimeError(f"type lookup not found: {type_name}/{type_value}")


def reset_target_state() -> None:
    STUB_DATA.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SAMPLE_STATE, STUB_DATA / "target-state.json")
    # Keep a seed copy so the stub can reset itself if asked.
    shutil.copyfile(SAMPLE_STATE, STUB_DATA / "target-seed.json")


def last_target_response() -> dict:
    log = STUB_DATA / "target-requests.jsonl"
    if not log.exists():
        return {}
    lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return {}
    try:
        return json.loads(lines[-1]).get("response", {})
    except json.JSONDecodeError:
        return {}


def run_verifier(expectation: dict) -> dict:
    response = last_target_response()
    response_path = STUB_DATA / "last-target-response.json"
    response_path.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")
    expectation_path = STUB_DATA / "last-expectation.json"
    expectation_path.write_text(json.dumps(expectation, indent=2) + "\n", encoding="utf-8")
    # A fresh path per invocation prevents a crashed verifier from leaving an older
    # verdict for this run to reuse.
    verdict_path = STUB_DATA / f"external-verdict-{uuid.uuid4().hex}.json"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                str(STUB_DATA / "target-state.json"),
                str(response_path),
                str(expectation_path),
                str(verdict_path),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        verdict = {}
        if verdict_path.exists():
            try:
                verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                verdict = {}
        verdict_text = verdict.get("verdict")
        expected_exit = {"passed": 0, "failed": 2, "unverified": 3}.get(verdict_text)
        execution_ok = bool(verdict_text) and result.returncode == expected_exit
        execution_error = None
        if not execution_ok:
            execution_error = (
                f"verifier exit={result.returncode}, verdict={verdict_text!r}"
                + (f"; stderr={result.stderr.strip()}" if result.stderr.strip() else "")
            )
        return {
            "exit_code": result.returncode,
            "stderr": result.stderr.strip(),
            "verdict": verdict,
            "execution_ok": execution_ok,
            "execution_error": execution_error,
        }
    finally:
        verdict_path.unlink(missing_ok=True)


def poll_run(run_id: str, timeout_seconds: int = 120) -> dict:
    terminal = {"Completed", "Partial", "Failed", "Cancelled"}
    deadline = time.time() + timeout_seconds
    last = {}
    while time.time() < deadline:
        last = api("GET", f"/test_runs/{run_id}", project_id=PROJECT_ID)
        status = (last.get("status") or {}).get("name") or (last.get("attributes") or {}).get(
            "task_state"
        )
        if status in terminal:
            return last
        time.sleep(2)
    return last


def get_results(run_id: str) -> list[dict]:
    try:
        return api(
            "GET",
            "/test_results?$filter=" + urllib.parse.quote(f"test_run_id eq '{run_id}'"),
            project_id=PROJECT_ID,
        )
    except ApiError:
        rows = api("GET", "/test_results?limit=100", project_id=PROJECT_ID)
        return [row for row in rows if row.get("test_run_id") == run_id]


def create_common() -> dict:
    lookups = type_lookups()
    provider_type = find_type(lookups, "ProviderType", "litellm_proxy")
    single_turn_test_set_type = find_type(lookups, "TestSetType", "Single-Turn")

    project = api(
        "POST",
        "/projects/",
        {
            "name": f"Stage 0 synthetic project {STAMP}",
            "description": "Synthetic stage 0 validation project; no business data.",
        },
    )
    project_id = project["id"]

    model = api(
        "POST",
        "/models/",
        {
            "name": f"stage0-stub-model-{STAMP}",
            "description": "Deterministic stub for stage 0; not a real model.",
            "model_name": "stage0-stub-model",
            "model_type": "language",
            "endpoint": "http://stage0-stub:18081",
            "key": "stage0-fake-key",
            "provider_type_id": provider_type["id"],
        },
    )
    model_id = model["id"]

    connection = api(
        "POST",
        "/models/test-connection",
        {
            "provider": "litellm_proxy",
            "model_name": "stage0-stub-model",
            "api_key": "stage0-fake-key",
            "endpoint": "http://stage0-stub:18081",
            "model_type": "language",
        },
    )

    api(
        "PATCH",
        "/users/settings",
        {
            "models": {
                "generation": {"model_id": model_id},
                "evaluation": {"model_id": model_id},
                "execution": {"model_id": model_id},
            }
        },
    )

    endpoint = api(
        "POST",
        "/endpoints/",
        {
            "name": f"stage0-synthetic-target-{STAMP}",
            "description": "Synthetic non-conversation target; deterministic stub.",
            "connection_type": "REST",
            "url": "http://stage0-stub:18082",
            "method": "POST",
            "endpoint_path": "/invoke",
            "project_id": project_id,
            "request_headers": {"Content-Type": "application/json"},
            "request_mapping": {
                "__body__": (
                    '{'
                    '"input": {{ input | tojson }},'
                    '"test_parameters": {{ (test_parameters or {}) | tojson }},'
                    '"files": {{ (files or []) | tojson }}'
                    '}'
                )
            },
            "response_mapping": {
                "output": "$.output",
                "observed": "$.observed",
                "status": "$.status",
            },
            "disable_tracing": True,
        },
        project_id=project_id,
    )

    # Exercise the Architect session path (REST create -> Celery task -> model stub
    # -> persisted assistant message). This is interface validation only.
    architect = {"session_id": None, "assistant_messages": 0, "error": None}
    try:
        session = api(
            "POST",
            "/architect/sessions/",
            {"initial_message": "Summarize the synthetic project in one sentence."},
            project_id=project_id,
        )
        architect["session_id"] = session.get("id")
        deadline = time.time() + 45
        while time.time() < deadline:
            messages = api(
                "GET",
                f"/architect/sessions/{architect['session_id']}/messages?limit=50",
                project_id=project_id,
            )
            assistants = [
                message for message in messages
                if message.get("role") == "assistant" and (message.get("content") or "").strip()
            ]
            if assistants:
                architect["assistant_messages"] = len(assistants)
                architect["last_assistant_excerpt"] = assistants[-1]["content"][:200]
                break
            time.sleep(2)
    except Exception as error:  # record and continue with the execution check
        architect["error"] = str(error)

    return {
        "project_id": project_id,
        "model_id": model_id,
        "connection": connection,
        "endpoint_id": endpoint["id"],
        "test_set_type_id": single_turn_test_set_type["id"],
        "architect": architect,
    }


def create_scenario(common: dict, name: str, parameters: dict, expected: dict) -> dict:
    suffix = f"{int(time.time())}-{name}"
    endpoint_id = common["endpoint_id"]
    project_id = common["project_id"]

    test_set = api(
        "POST",
        "/test_sets/",
        {
            "name": f"stage0-set-{suffix}",
            "description": "Synthetic stage 0 scenario.",
            "test_set_type_id": common["test_set_type_id"],
        },
        project_id=project_id,
    )
    test_set_id = test_set["id"]

    test = api(
        "POST",
        "/tests/",
        {
            "prompt": {
                "content": "Apply the release request encoded in test_parameters.",
                "language_code": "en",
                "expected_response": "The synthetic target applies the documented transition.",
            },
            "test_type": "Single-Turn",
            "test_parameters": parameters,
        },
        project_id=project_id,
    )
    test_id = test["id"]

    api(
        "POST",
        f"/test_sets/{test_set_id}/associate",
        {"test_ids": [test_id]},
        project_id=project_id,
    )

    metric = api(
        "POST",
        "/metrics/",
        {
            "name": f"stage0-stub-judge-{suffix}",
            "description": "Deterministic stub judge; it always returns 1.0.",
            "evaluation_prompt": "Return 1.0 for the stage 0 interface check.",
            "evaluation_steps": "Always return 1.0.",
            "score_type": "numeric",
            "metric_type": "custom-prompt",
            "backend_type": "rhesis",
            "class_name": "NumericJudge",
            "metric_scope": ["Single-Turn"],
            "min_score": 0.0,
            "max_score": 1.0,
            "threshold": 0.5,
            "threshold_operator": ">=",
        },
        project_id=project_id,
    )
    metric_id = metric["id"]

    api(
        "POST",
        f"/test_sets/{test_set_id}/metrics/{metric_id}",
        project_id=project_id,
    )

    reset_target_state()
    execution = api(
        "POST",
        f"/test_sets/{test_set_id}/execute/{endpoint_id}",
        {"execution_options": {"execution_mode": "Sequential"}},
        project_id=project_id,
    )
    run_id = execution.get("test_run_id")
    if not run_id:
        raise RuntimeError(f"execute did not return test_run_id: {execution}")

    run_detail = poll_run(run_id)
    results = get_results(run_id)
    external = run_verifier(expected)

    status = (run_detail.get("status") or {}).get("name") or (run_detail.get("attributes") or {}).get(
        "task_state"
    )
    rhesis_verdicts = [row.get("verdict") for row in results]
    return {
        "scenario": name,
        "test_set_id": test_set_id,
        "test_id": test_id,
        "metric_id": metric_id,
        "run_id": run_id,
        "rhesis_run_status": status,
        "rhesis_run_stats": run_detail.get("stats"),
        "rhesis_verdicts": rhesis_verdicts,
        "rhesis_result_count": len(results),
        "rhesis_results": [
            {
                "test_id": row.get("test_id"),
                "verdict": row.get("verdict"),
                "execution": row.get("execution"),
                "test_metrics": row.get("test_metrics"),
                "test_output": row.get("test_output"),
            }
            for row in results
        ],
        "external_verifier": external,
        "external_execution_ok": external.get("execution_ok", False),
        "target_request": last_target_response(),
        "expected_external_verdict": expected["expected_verdict"],
    }


PROJECT_ID: Optional[str] = None


def main() -> int:
    global BASE_URL, TOKEN, PROJECT_ID
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()
    BASE_URL = args.base_url

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    TOKEN = login()

    common = create_common()
    PROJECT_ID = common["project_id"]
    summary: dict = {"base_url": BASE_URL, "common": common, "scenarios": []}

    scenarios = [
        (
            "pass",
            {"artifact_id": "doc-17", "action": "release", "actor": "alice", "mode": "normal"},
            {
                "artifact_id": "doc-17",
                "expected_status": "released",
                "expected_audit_entries": 1,
                "expected_decision": "released",
                "untouched_artifact": "doc-18",
                "expected_verdict": "passed",
            },
        ),
        (
            "fail",
            {"artifact_id": "doc-17", "action": "release", "actor": "bob", "mode": "normal"},
            {
                "artifact_id": "doc-17",
                "expected_status": "draft",
                "expected_audit_entries": 0,
                "expected_decision": "rejected",
                "untouched_artifact": "doc-18",
                "expected_verdict": "failed",
            },
        ),
        (
            "missing_evidence",
            {
                "artifact_id": "doc-17",
                "action": "release",
                "actor": "alice",
                "mode": "missing_evidence",
            },
            {
                "artifact_id": "doc-17",
                "expected_status": "released",
                "expected_audit_entries": 1,
                "expected_decision": "released",
                "untouched_artifact": "doc-18",
                "expected_verdict": "unverified",
            },
        ),
    ]

    for name, parameters, expected in scenarios:
        try:
            expected = {**expected, "untouched_artifact_snapshot": UNTOUCHED_SNAPSHOT}
            result = create_scenario(common, name, parameters, expected)
        except Exception as error:  # keep going, record the failure
            result = {"scenario": name, "error": str(error)}
        summary["scenarios"].append(result)
        status = (
            (result.get("external_verifier") or {}).get("verdict", {}).get("verdict")
            if isinstance(result.get("external_verifier"), dict)
            else None
        )
        print(
            f"{name}: rhesis_run={result.get('rhesis_run_status')} "
            f"rhesis_verdicts={result.get('rhesis_verdicts')} "
            f"external={status}"
        )

    def external_ok(scenario: dict) -> bool:
        external = scenario.get("external_verifier") or {}
        return bool(external.get("execution_ok")) and (
            (external.get("verdict") or {}).get("verdict")
            == scenario.get("expected_external_verdict")
        )

    summary["all_external_ok"] = (
        all(
            external_ok(scenario)
            for scenario in summary["scenarios"]
            if "error" not in scenario
        )
        and all("error" not in scenario for scenario in summary["scenarios"])
    )

    output = EVIDENCE / f"rhesis-flow-{int(time.time())}.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"evidence: {output}")
    print(f"all_external_ok: {summary['all_external_ok']}")
    return 0 if summary["all_external_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
