#!/usr/bin/env python3
"""Synthetic non-conversation agent for stage 0.

Reads one event JSON file, reads the synthetic project's policy document from a
read-only mount, applies a state transition to a dedicated writable state file, and
writes a response file. It never uses the network. The release rule is deliberately
naive (any listed approver releases), so a contributor approval produces a wrong
release that an independent verifier can catch.

Arguments:
    event_path     read-only JSON event
    seed_path      read-only initial state
    state_path     writable JSON state
    response_path  writable JSON response
    project_root   read-only project root (default /project)

No third-party packages are used.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: str, payload: dict) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def probe_network() -> str:
    """A best-effort egress probe. The runner expects this to be blocked."""
    try:
        with socket.create_connection(("1.1.1.1", 80), timeout=1.0):
            return "reachable"
    except OSError as exc:
        return f"blocked: {type(exc).__name__}"


def probe_write(path: Path) -> str:
    try:
        path.write_text("probe", encoding="utf-8")
        path.unlink(missing_ok=True)
        return "writable"
    except OSError as exc:
        return f"read-only: {type(exc).__name__}"


def probe_hidden_paths() -> dict:
    """Record whether material the agent must not see is reachable.

    The runner gives the agent only a filtered project snapshot and an event file, and
    the agent image contains no verifier. A 'readable' result is an isolation failure.
    """
    candidates = (
        "/app/verify.py",
        "/input/expectation.json",
        "/project/.env",
        "/project/secrets/credentials.txt",
    )
    return {
        path: ("readable" if Path(path).exists() else "absent") for path in candidates
    }


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        print(
            "usage: agent.py <event> <seed> <state> <response> [project_root]",
            file=sys.stderr,
        )
        return 2

    event_path, seed_path, state_path, response_path = argv[1:5]
    project_root = Path(argv[5] if len(argv) > 5 else "/project")

    event = load_json(event_path)
    seed = load_json(seed_path)
    state = json.loads(json.dumps(seed))  # deep copy

    policy_path = project_root / "docs" / "RELEASE_POLICY.md"
    policy_text = policy_path.read_text(encoding="utf-8")
    policy_digest = None
    import hashlib

    policy_digest = hashlib.sha256(policy_text.encode("utf-8")).hexdigest()

    artifact_id = event.get("artifact_id")
    action = event.get("action")
    actor = event.get("actor")
    mode = event.get("mode", "normal")

    artifacts = state.get("artifacts", {})
    artifact = artifacts.get(artifact_id)
    observed = {
        "artifact_id": artifact_id,
        "action": action,
        "actor": actor,
        "actor_approved": False,
        "policy_digest": policy_digest,
        "mode": mode,
    }

    # Naive rule: membership in the approvals list is treated as sufficient. The
    # project policy requires the approver's role to be release_manager.
    if artifact is not None:
        observed["actor_approved"] = any(
            approval.get("actor") == actor for approval in artifact.get("approvals", [])
        )
        if action == "release" and observed["actor_approved"]:
            artifact["status"] = "released"
            if mode != "missing_evidence":
                artifact.setdefault("audit", []).append({"action": "release", "actor": actor})
            observed["decision"] = "released"
        else:
            observed["decision"] = "rejected"
    else:
        observed["decision"] = "unknown_artifact"

    # A deliberately unrelated mutation: keep doc-18's status as draft but change
    # another field. The verifier must compare the complete initial snapshot.
    if mode == "unrelated_mutation":
        unrelated = artifacts.get("doc-18")
        if isinstance(unrelated, dict):
            unrelated.setdefault("approvals", []).append(
                {"actor": "mallory", "role": "contributor"}
            )

    observed["network"] = probe_network()
    observed["project_write"] = probe_write(project_root / ".stage0-write-probe")
    observed["hidden_access"] = probe_hidden_paths()

    # A wrong-claim variant lets the runner prove that the agent's self-report does not
    # decide the independent state verdict.
    reported_decision = observed["decision"]
    if mode == "wrong_claim":
        reported_decision = (
            "rejected" if observed["decision"] == "released" else "released"
        )
    observed["reported_decision"] = reported_decision

    dump_json(state_path, state)
    dump_json(
        response_path,
        {
            "ok": True,
            "agent": "stage0-synthetic-release-gate",
            "observed": observed,
            "response_text": f"decision={reported_decision}",
        },
    )
    # Calibration: write valid artifacts, then terminate unsuccessfully. The runner
    # must reject this as an execution failure even though the state verifier passes.
    if mode == "crash_after_write":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
