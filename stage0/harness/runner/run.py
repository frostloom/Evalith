#!/usr/bin/env python3
"""Run the synthetic stage 0 validation cases.

This runner builds a tiny image, creates a unique volume per case, runs the synthetic
agent under a restrictive container configuration, runs an independent verifier against
the resulting state, and removes every resource. It records the evidence as JSON under
``stage0/evidence/runs`` and prints a summary.

It is intentionally stdlib-only and drives the Docker CLI. Run from the repository root:

    python3 stage0/harness/runner/run.py

Exit status is 0 only when every case produced the expected verdict and cleanup left no
containers, volumes or networks behind.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent
REPO = HARNESS.parent.parent
FIXTURES = HARNESS / "fixtures" / "project"
EVIDENCE = REPO / "stage0" / "evidence" / "runs"
IMAGE = "stage0-harness:local"
RUN_PREFIX = "stage0-"


def run(cmd: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=capture,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run(["docker", *args], check=check)


def build_image() -> None:
    docker(
        "build",
        "-t",
        IMAGE,
        "-f",
        str(HARNESS / "Dockerfile"),
        str(HARNESS),
        check=True,
    )


def make_project_copy(root: Path) -> Path:
    project = root / "project"
    shutil.copytree(FIXTURES, project)
    # A symlink that points outside the project root must be rejected, not followed.
    outside = root / "outside-secret.txt"
    outside.write_text("STAGE0_FAKE_OUTSIDE_SECRET=do-not-read\n", encoding="utf-8")
    os.symlink(outside, project / "leak-outside")
    return project


def seed_state(root: Path) -> Path:
    source = FIXTURES / "data" / "sample_state.json"
    seed = root / "seed.json"
    shutil.copyfile(source, seed)
    return seed


def event_for(case: str) -> dict:
    if case in {"pass", "missing_evidence"}:
        actor = "alice"
    else:
        actor = "bob"  # contributor; the naive agent will still release
    return {
        "artifact_id": "doc-17",
        "action": "release",
        "actor": actor,
        "mode": "missing_evidence" if case == "missing_evidence" else "normal",
    }


def expectation_for(case: str) -> dict:
    if case == "pass":
        return {
            "artifact_id": "doc-17",
            "expected_status": "released",
            "expected_audit_entries": 1,
            "expected_decision": "released",
            "untouched_artifact": "doc-18",
        }
    if case == "fail":
        return {
            "artifact_id": "doc-17",
            "expected_status": "draft",
            "expected_audit_entries": 0,
            "expected_decision": "rejected",
            "untouched_artifact": "doc-18",
        }
    if case == "missing_evidence":
        return {
            "artifact_id": "doc-17",
            "expected_status": "released",
            "expected_audit_entries": 1,
            "expected_decision": "released",
            "untouched_artifact": "doc-18",
        }
    raise ValueError(f"unknown case {case}")


EXPECTED_VERDICT = {"pass": "passed", "fail": "failed", "missing_evidence": "unverified"}


def container_run(
    *,
    name: str,
    volumes: list[str],
    entrypoint: list[str],
    network_none: bool = True,
    read_only: bool = True,
    user: str = "65534:65534",
) -> tuple[subprocess.CompletedProcess, dict]:
    cmd = [
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none" if network_none else "bridge",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        user,
        "--pids-limit",
        "64",
        "--memory",
        "128m",
        "--cpus",
        "0.5",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
    ]
    for volume in volumes:
        cmd.extend(["-v", volume])
    cmd.extend([IMAGE, *entrypoint])
    started = docker(*cmd, check=False)
    if started.returncode != 0:
        return (
            subprocess.CompletedProcess(cmd, started.returncode, started.stdout, started.stderr),
            {},
        )
    inspection = container_inspect(name) or {}
    waited = docker("wait", name, check=False)
    logs = docker("logs", name, check=False)
    docker("rm", "-f", name, check=False)
    try:
        exit_code = int((waited.stdout or "1").strip().splitlines()[-1])
    except (ValueError, IndexError):
        exit_code = 1
    return subprocess.CompletedProcess(cmd, exit_code, logs.stdout, logs.stderr), inspection


def volume_read(volume: str, path: str) -> str | None:
    result = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--user",
        "65534:65534",
        "-v",
        f"{volume}:{path.rsplit('/', 1)[0]}:ro",
        "--entrypoint",
        "python",
        IMAGE,
        "-c",
        (
            "import sys;"
            f"p={path!r};"
            "print(open(p, encoding='utf-8').read(), end='')"
        ),
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def container_inspect(name: str) -> dict | None:
    result = docker("inspect", name, check=False)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError, KeyError):
        return None
    host = data.get("HostConfig", {})
    return {
        "name": name,
        "image": data.get("Config", {}).get("Image"),
        "network_mode": host.get("NetworkMode"),
        "readonly_rootfs": host.get("ReadonlyRootfs"),
        "cap_drop": host.get("CapDrop"),
        "user": data.get("Config", {}).get("User"),
        "security_opt": host.get("SecurityOpt"),
        "memory": host.get("Memory"),
        "pids_limit": host.get("PidsLimit"),
        "binds": host.get("Binds"),
    }


def cleanup(run_id: str, volumes: list[str]) -> dict:
    names = [f"{RUN_PREFIX}agent-{run_id}", f"{RUN_PREFIX}verify-{run_id}"]
    for name in names:
        docker("rm", "-f", name, check=False)
    for volume in volumes:
        docker("volume", "rm", "-f", volume, check=False)
    leftover_containers = docker(
        "ps", "-a", "--filter", f"name={RUN_PREFIX}", "--format", "{{.Names}}", check=False
    ).stdout.split()
    leftover_volumes = docker(
        "volume", "ls", "--filter", f"name={RUN_PREFIX}", "--format", "{{.Name}}", check=False
    ).stdout.split()
    return {
        "removed_containers": names,
        "removed_volumes": volumes,
        "leftover_containers": [n for n in leftover_containers if n not in names],
        "leftover_volumes": [v for v in leftover_volumes if v not in volumes],
        "clean": not [n for n in leftover_containers if n not in names]
        and not [v for v in leftover_volumes if v not in volumes],
    }


def run_access(root: Path, run_id: str) -> dict:
    project = make_project_copy(root)
    out_volume = f"{RUN_PREFIX}access-{run_id}"
    docker("volume", "create", out_volume, check=True)
    docker(
        "run",
        "--rm",
        "--user",
        "0:0",
        "-v",
        f"{out_volume}:/out",
        "--entrypoint",
        "chown",
        IMAGE,
        "65534:65534",
        "/out",
        check=True,
    )
    reader_result = docker(
        "run",
        "--rm",
        "--name",
        f"{RUN_PREFIX}reader-{run_id}",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "-v",
        f"{project}:/project:ro",
        "-v",
        f"{out_volume}:/out",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--entrypoint",
        "python",
        IMAGE,
        "/app/read_project.py",
        "--root",
        "/project",
        "--output",
        "/out/manifest.json",
        check=False,
    )
    raw = volume_read(out_volume, "/out/manifest.json")
    manifest = json.loads(raw) if raw else None
    docker("volume", "rm", "-f", out_volume, check=False)

    paths = {entry["path"] for entry in (manifest or {}).get("files", [])}
    skipped = {entry["path"]: entry["reason"] for entry in (manifest or {}).get("skipped", [])}
    checks = {
        "readme_included": "README.md" in paths,
        "policy_included": "docs/RELEASE_POLICY.md" in paths,
        "source_included": "src/release_gate.py" in paths,
        "env_excluded": ".env" not in paths and skipped.get(".env") == "excluded_name",
        "secrets_dir_excluded": "secrets/credentials.txt" not in paths,
        "symlink_escape_rejected": "leak-outside" not in paths
        and skipped.get("leak-outside") == "symlink_escape",
        "project_mount_read_only": (manifest or {}).get("project_mount_writable") is False,
        "no_secret_markers": not (manifest or {}).get("secret_markers_found"),
    }
    return {
        "scenario": "local_project_access",
        "run_id": run_id,
        "checks": checks,
        "passed": all(checks.values()),
        "manifest": manifest,
        "reader_exit": reader_result.returncode,
        "reader_stderr": reader_result.stderr.strip(),
        "cleanup": cleanup(run_id, []),
    }


def run_case(case: str, root: Path, run_id: str) -> dict:
    project = make_project_copy(root)
    seed = seed_state(root)
    input_dir = root / "input"
    input_dir.mkdir()
    event_path = input_dir / "event.json"
    expectation_path = input_dir / "expectation.json"
    event_path.write_text(json.dumps(event_for(case), indent=2) + "\n", encoding="utf-8")
    expectation_path.write_text(
        json.dumps(expectation_for(case), indent=2) + "\n", encoding="utf-8"
    )

    state_volume = f"{RUN_PREFIX}state-{run_id}"
    out_volume = f"{RUN_PREFIX}out-{run_id}"
    docker("volume", "create", state_volume, check=True)
    docker("volume", "create", out_volume, check=True)
    # Give the non-root user ownership of the two writable volumes only.
    docker(
        "run",
        "--rm",
        "--user",
        "0:0",
        "-v",
        f"{state_volume}:/state",
        "-v",
        f"{out_volume}:/out",
        "--entrypoint",
        "chown",
        IMAGE,
        "65534:65534",
        "/state",
        "/out",
        check=True,
    )

    agent_name = f"{RUN_PREFIX}agent-{run_id}"
    agent_result, agent_inspect = container_run(
        name=agent_name,
        volumes=[
            f"{project}:/project:ro",
            f"{input_dir}:/input:ro",
            f"{seed}:/seed/initial.json:ro",
            f"{state_volume}:/state",
            f"{out_volume}:/out",
        ],
        entrypoint=[
            "python",
            "/app/agent.py",
            "/input/event.json",
            "/seed/initial.json",
            "/state/state.json",
            "/out/response.json",
            "/project",
        ],
    )
    verify_name = f"{RUN_PREFIX}verify-{run_id}"
    verifier_result, verifier_inspect = container_run(
        name=verify_name,
        volumes=[
            f"{state_volume}:/state:ro",
            f"{out_volume}:/out",
            f"{input_dir}:/input:ro",
        ],
        entrypoint=[
            "python",
            "/app/verify.py",
            "/state/state.json",
            "/out/response.json",
            "/input/expectation.json",
            "/out/verdict.json",
        ],
    )

    verdict_raw = volume_read(out_volume, "/out/verdict.json")
    verdict = json.loads(verdict_raw) if verdict_raw else None
    response_raw = volume_read(out_volume, "/out/response.json")
    response = json.loads(response_raw) if response_raw else None

    observed_verdict = (verdict or {}).get("verdict")
    expected_verdict = EXPECTED_VERDICT[case]
    case_ok = observed_verdict == expected_verdict and verifier_result.returncode == {
        "passed": 0,
        "failed": 2,
        "unverified": 3,
    }[expected_verdict]

    cleanup_info = cleanup(run_id, [state_volume, out_volume])

    return {
        "scenario": "synthetic_release_gate",
        "case": case,
        "run_id": run_id,
        "expected_verdict": expected_verdict,
        "observed_verdict": observed_verdict,
        "case_ok": case_ok,
        "agent_exit": agent_result.returncode,
        "verifier_exit": verifier_result.returncode,
        "agent_observed": (response or {}).get("observed"),
        "verdict": verdict,
        "isolation": {
            "network_mode": agent_inspect.get("network_mode"),
            "readonly_rootfs": agent_inspect.get("readonly_rootfs"),
            "cap_drop": agent_inspect.get("cap_drop"),
            "user": agent_inspect.get("user"),
            "binds": agent_inspect.get("binds"),
        },
        "cleanup": cleanup_info,
        "agent_isolation": agent_inspect,
        "verifier_isolation": verifier_inspect,
        "agent_stderr": agent_result.stderr.strip(),
        "verifier_stderr": verifier_result.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default="pass,fail,missing_evidence",
        help="comma-separated cases to run",
    )
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    cases = [case.strip() for case in args.cases.split(",") if case.strip()]
    unknown = set(cases) - set(EXPECTED_VERDICT)
    if unknown:
        raise SystemExit(f"unknown cases: {sorted(unknown)}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    summary = {"started_at": stamp, "image": IMAGE, "access": None, "cases": []}

    if not args.skip_build:
        build_image()

    with tempfile.TemporaryDirectory(prefix="stage0-run-") as tmp:
        root = Path(tmp)
        access_id = f"{stamp}-access"
        access = run_access(root / "access", access_id)
        summary["access"] = access
        print(f"local_project_access: {'PASS' if access['passed'] else 'FAIL'}")

        for index, case in enumerate(cases):
            case_root = root / f"case-{index}"
            case_root.mkdir()
            run_id = f"{stamp}-{case}"
            result = run_case(case, case_root, run_id)
            summary["cases"].append(result)
            status = "PASS" if result["case_ok"] else "FAIL"
            print(
                f"case {case}: expected={result['expected_verdict']} "
                f"observed={result['observed_verdict']} ({status}), "
                f"cleanup={'clean' if result['cleanup']['clean'] else 'LEFTOVER'}"
            )

    summary["finished_at"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary["all_ok"] = bool(
        summary["access"]
        and summary["access"]["passed"]
        and all(case["case_ok"] for case in summary["cases"])
        and all(case["cleanup"]["clean"] for case in summary["cases"])
    )
    output = EVIDENCE / f"{stamp}-summary.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"evidence: {output}")
    print(f"all_ok: {summary['all_ok']}")
    return 0 if summary["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
