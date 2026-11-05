#!/usr/bin/env python3
"""Independent verifier for the synthetic stage 0 task.

Reads the final state produced by the agent, the expected outcome supplied by the
runner, and the agent's self-reported response. It never trusts the response when the
state disagrees. It writes a machine-readable verdict and uses distinct exit codes:

    0  passed
    2  failed (state contradicts the documented expectation)
    3  unverified (a required piece of evidence is missing)

Arguments:
    state_path       writable state written by the agent
    response_path    agent response
    expectation_path expected outcome supplied by the runner
    verdict_path     where to write the verdict JSON
"""

from __future__ import annotations

import json
import os
import sys


def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def write_json(path: str, payload: dict) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        print(
            "usage: verify.py <state> <response> <expectation> <verdict>",
            file=sys.stderr,
        )
        return 2

    state_path, response_path, expectation_path, verdict_path = argv[1:5]
    state = load_json(state_path)
    response = load_json(response_path)
    expectation = load_json(expectation_path)

    checks = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    observed = (response or {}).get("observed") or {}
    agent_claim = observed.get("reported_decision", observed.get("decision"))
    expected_claim = (expectation or {}).get("expected_decision")
    claim_diagnostics = {
        "reported": agent_claim,
        "expected": expected_claim,
        "matches": (
            None
            if expected_claim is None or agent_claim is None
            else agent_claim == expected_claim
        ),
    }

    if state is None:
        add("state_readable", "unverified", f"state file missing or invalid: {state_path}")
        verdict = "unverified"
    else:
        add("state_readable", "passed", "state file parsed")
        artifact_id = expectation["artifact_id"]
        artifact = (state.get("artifacts") or {}).get(artifact_id)
        if artifact is None:
            add("artifact_present", "unverified", f"artifact {artifact_id} missing from state")
            verdict = "unverified"
        else:
            add("artifact_present", "passed", f"artifact {artifact_id} present")
            expected_status = expectation["expected_status"]
            if artifact.get("status") == expected_status:
                add(
                    "final_status",
                    "passed",
                    f"status is {expected_status}",
                )
            else:
                add(
                    "final_status",
                    "failed",
                    f"expected {expected_status}, found {artifact.get('status')}",
                )

            expected_audit = expectation["expected_audit_entries"]
            audit = artifact.get("audit") or []
            if expected_audit == 0:
                if len(audit) == 0:
                    add("audit_entries", "passed", "no release audit entry, as expected")
                else:
                    add("audit_entries", "failed", f"expected no audit entry, found {len(audit)}")
            else:
                if len(audit) == 0:
                    add(
                        "audit_entries",
                        "unverified",
                        "release audit entry is missing; cannot confirm the side effect",
                    )
                elif len(audit) == expected_audit:
                    add("audit_entries", "passed", f"{expected_audit} audit entry")
                else:
                    add(
                        "audit_entries",
                        "failed",
                        f"expected {expected_audit} audit entries, found {len(audit)}",
                    )

            untouched_id = expectation.get("untouched_artifact")
            if untouched_id:
                untouched = (state.get("artifacts") or {}).get(untouched_id)
                if untouched is None:
                    add("untouched_artifact", "unverified", f"{untouched_id} missing from state")
                elif untouched.get("status") == "draft":
                    add("untouched_artifact", "passed", f"{untouched_id} still draft")
                else:
                    add(
                        "untouched_artifact",
                        "failed",
                        f"{untouched_id} changed to {untouched.get('status')}",
                    )

        hidden = observed.get("hidden_access")
        if not isinstance(hidden, dict) or not hidden:
            add(
                "hidden_material",
                "unverified",
                "agent did not report whether verifier/expectation/secret paths were reachable",
            )
        else:
            readable = sorted(path for path, state in hidden.items() if state == "readable")
            if readable:
                add(
                    "hidden_material",
                    "failed",
                    "agent could read material it must not see: " + ", ".join(readable),
                )
            else:
                add("hidden_material", "passed", "verifier, expectation and secret paths absent")

        # The agent's own claim is diagnostic only: it must never change the state
        # verdict. A correct state with missing evidence stays 'unverified' even when
        # the agent reports a different decision.
        failed = [c for c in checks if c["status"] == "failed"]
        unverified = [c for c in checks if c["status"] == "unverified"]
        if failed:
            verdict = "failed"
        elif unverified:
            verdict = "unverified"
        else:
            verdict = "passed"

    write_json(
        verdict_path,
        {
            "verdict": verdict,
            "checks": checks,
            "expectation": expectation,
            "claim_diagnostics": claim_diagnostics,
        },
    )
    return {"passed": 0, "failed": 2, "unverified": 3}[verdict]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
