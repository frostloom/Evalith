#!/usr/bin/env python3
"""Deterministic stand-in services for the Rhesis stage 0 runtime check.

Two HTTP servers run in one container:

* port 18081: an OpenAI-compatible model endpoint. It is a stub, not a model.
  It answers the connection test and returns schema-shaped JSON for the two
  structured outputs stage 0 uses (AgentAction and NumericScoreResponse).
* port 18082: a synthetic "target agent" endpoint. It accepts the JSON body
  Rhesis builds from a test's prompt plus ``test_parameters`` and applies a
  deliberately naive release transition to a state file.

Everything is deterministic and local. No real model is called, no external
network is used, and no business data is involved. Request bodies and responses
are logged under /data so the run can be inspected afterwards.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA_DIR = Path(os.environ.get("STUB_DATA_DIR", "/data"))
LLM_LOG = DATA_DIR / "llm-requests.jsonl"
TARGET_LOG = DATA_DIR / "target-requests.jsonl"
TARGET_STATE = DATA_DIR / "target-state.json"
TARGET_SEED = DATA_DIR / "target-seed.json"

DEFAULT_SEED = {
    "artifacts": {
        "doc-17": {
            "status": "draft",
            "approvals": [
                {"actor": "alice", "role": "release_manager"},
                {"actor": "bob", "role": "contributor"},
            ],
            "audit": [],
        },
        "doc-18": {
            "status": "draft",
            "approvals": [{"actor": "carol", "role": "contributor"}],
            "audit": [],
        },
    }
}


def append_jsonl(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        pass


def load_json(path: Path, default: dict) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(default))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def schema_name(body: dict) -> str:
    response_format = body.get("response_format") or {}
    if isinstance(response_format, dict):
        schema = response_format.get("json_schema") or {}
        if isinstance(schema, dict) and schema.get("name"):
            return str(schema["name"])
    text = json.dumps(body)[:20000]
    for candidate in ("AgentAction", "NumericScoreResponse", "CategoricalScoreResponse"):
        if candidate in text:
            return candidate
    return ""


def completion_content(body: dict) -> str:
    name = schema_name(body)
    if name == "AgentAction":
        return json.dumps(
            {
                "reasoning": "Stage 0 deterministic stub: answer without calling tools.",
                "action": "finish",
                "tool_calls": [],
                "final_answer": (
                    "Stage 0 stub model: I read the synthetic project context. "
                    "No tools were called because this run verifies the interface only."
                ),
                "needs_confirmation": False,
            }
        )
    if name == "NumericScoreResponse":
        return json.dumps(
            {
                "score": 1.0,
                "reason": "Stage 0 stub judge: always returns 1.0 so the harness can show "
                "that a metric is not an independent state check.",
            }
        )
    if name == "CategoricalScoreResponse":
        return json.dumps({"category": "pass", "reason": "Stage 0 stub judge."})
    return "OK"


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class LLMHandler(BaseHTTPRequestHandler):
    server_version = "stage0-stub-llm/1.0"

    def log_message(self, fmt: str, *args) -> None:  # keep container logs quiet
        return

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            send_json(
                self,
                200,
                {"object": "list", "data": [{"id": "stage0-stub-model", "object": "model"}]},
            )
        else:
            send_json(self, 200, {"status": "ok", "role": "stage0-stub-llm"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        content = completion_content(body)
        model = body.get("model") or "stage0-stub-model"
        append_jsonl(
            LLM_LOG,
            {
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "path": self.path,
                "model": model,
                "schema": schema_name(body),
                "message_count": len(body.get("messages") or []),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            },
        )
        send_json(
            self,
            200,
            {
                "id": "chatcmpl-stage0-stub",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )


class TargetHandler(BaseHTTPRequestHandler):
    server_version = "stage0-target/1.0"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        send_json(self, 200, {"status": "ok", "role": "stage0-target"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {"input": raw.decode("utf-8", "replace")}

        if self.path.rstrip("/").endswith("/reset"):
            seed = load_json(TARGET_SEED, DEFAULT_SEED)
            write_json(TARGET_STATE, seed)
            send_json(self, 200, {"status": "reset"})
            return

        parameters = body.get("test_parameters") or {}
        if not isinstance(parameters, dict):
            parameters = {}
        artifact_id = parameters.get("artifact_id")
        action = parameters.get("action")
        actor = parameters.get("actor")
        mode = parameters.get("mode", "normal")

        state = load_json(TARGET_STATE, DEFAULT_SEED)
        artifacts = state.setdefault("artifacts", {})
        artifact = artifacts.get(artifact_id)
        observed = {
            "artifact_id": artifact_id,
            "action": action,
            "actor": actor,
            "actor_approved": False,
            "mode": mode,
        }
        if artifact is None:
            observed["decision"] = "unknown_artifact"
        else:
            observed["actor_approved"] = any(
                approval.get("actor") == actor for approval in artifact.get("approvals", [])
            )
            # Deliberately naive: role is ignored, so a contributor approval releases.
            if action == "release" and observed["actor_approved"]:
                artifact["status"] = "released"
                if mode != "missing_evidence":
                    artifact.setdefault("audit", []).append({"action": "release", "actor": actor})
                observed["decision"] = "released"
            else:
                observed["decision"] = "rejected"
        write_json(TARGET_STATE, state)

        response = {
            "output": {
                "observed": observed,
                "response_text": f"decision={observed['decision']}",
            },
            "observed": observed,
            "status": "ok",
        }
        append_jsonl(
            TARGET_LOG,
            {
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "path": self.path,
                "request": {
                    "input": body.get("input"),
                    "test_parameters": parameters,
                    "files": body.get("files"),
                },
                "response": response,
            },
        )
        send_json(self, 200, response)


def serve(handler, port: int) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    server.serve_forever()


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not TARGET_STATE.exists():
        write_json(TARGET_STATE, load_json(TARGET_SEED, DEFAULT_SEED))
    threads = [
        threading.Thread(target=serve, args=(LLMHandler, 18081), daemon=True),
        threading.Thread(target=serve, args=(TargetHandler, 18082), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()
