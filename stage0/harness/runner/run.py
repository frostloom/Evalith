#!/usr/bin/env python3
"""Run the synthetic stage 0 validation cases.

This runner builds three role-scoped images, creates a unique volume per case, runs the
synthetic agent under a restrictive container configuration, runs an independent
verifier against the resulting state, and removes every resource. It records the
evidence as JSON under ``stage0/evidence/runs`` and prints a summary.

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
SAMPLE_STATE = json.loads((FIXTURES / "data" / "sample_state.json").read_text(encoding="utf-8"))
UNTOUCHED_SNAPSHOT = SAMPLE_STATE["artifacts"]["doc-18"]
EVIDENCE = REPO / "stage0" / "evidence" / "runs"
AGENT_IMAGE = "stage0-agent:local"
VERIFIER_IMAGE = "stage0-verifier:local"
READER_IMAGE = "stage0-reader:local"
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


def build_images() -> None:
    for target, image in (
        ("agent", AGENT_IMAGE),
        ("verifier", VERIFIER_IMAGE),
        ("reader", READER_IMAGE),
    ):
        docker(
            "build",
            "--target",
            target,
            "-t",
            image,
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


def make_agent_project(project: Path, destination: Path) -> Path:
    """Copy only material the agent may see.

    ``.env``, the synthetic ``secrets/`` directory, the escaping symlink and caches are
    excluded before the mount exists. The scanner's exclusion list is therefore also the
    mount's content list, not just a report about it.
    """
    shutil.copytree(
        project,
        destination,
        ignore=shutil.ignore_patterns(".env*", "secrets", "leak-outside", "__pycache__"),
    )
    for path in destination.rglob("*"):
        if path.is_symlink():
            path.unlink()
    return destination


def relative_files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def seed_state(root: Path) -> Path:
    source = FIXTURES / "data" / "sample_state.json"
    seed = root / "seed.json"
    shutil.copyfile(source, seed)
    return seed


def event_for(case: str) -> dict:
    if case in {"pass", "missing_evidence", "claim_mismatch", "unrelated_mutation"}:
        actor = "alice"
    else:
        actor = "bob"  # contributor; the naive agent will still release
    mode = "normal"
    if case == "missing_evidence":
        mode = "missing_evidence"
    elif case == "claim_mismatch":
        mode = "wrong_claim"
    elif case == "unrelated_mutation":
        mode = "unrelated_mutation"
    return {
        "artifact_id": "doc-17",
        "action": "release",
        "actor": actor,
        "mode": mode,
    }


def expectation_for(case: str) -> dict:
    base = {
        "artifact_id": "doc-17",
        "untouched_artifact": "doc-18",
        "untouched_artifact_snapshot": UNTOUCHED_SNAPSHOT,
    }
    if case in {"pass", "missing_evidence", "claim_mismatch", "unrelated_mutation"}:
        return {
            **base,
            "expected_status": "released",
            "expected_audit_entries": 1,
            "expected_decision": "released",
        }
    if case == "fail":
        return {
            **base,
            "expected_status": "draft",
            "expected_audit_entries": 0,
            "expected_decision": "rejected",
        }
    raise ValueError(f"unknown case {case}")

EXPECTED_VERDICT = {
    "pass": "passed",
    "fail": "failed",
    "missing_evidence": "unverified",
    "claim_mismatch": "passed",
    "unrelated_mutation": "failed",
}


def container_run(
    *,
    image: str,
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
    cmd.extend([image, *entrypoint])
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
        READER_IMAGE,
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


def resource_exists(kind: str, name: str) -> tuple[bool, str | None]:
    """Return (exists, error). A missing resource is not a Docker error."""
    if kind == "container":
        result = docker("inspect", name, check=False)
    else:
        result = docker("volume", "inspect", name, check=False)
    if result.returncode == 0:
        return True, None
    stderr = (result.stderr or "").strip()
    lowered = stderr.lower()
    if "no such" in lowered or "not found" in lowered:
        return False, None
    return False, stderr or f"docker inspect exited {result.returncode}"


def cleanup(run_id: str, names: list[str], volumes: list[str]) -> dict:
    """Remove this run's resources and verify they are actually gone.

    Only resources named by this run are checked, so a concurrent unrelated container
    cannot make the check fail and a surviving resource cannot be hidden by filtering it
    out. A nonzero ``rm`` exit is recorded; the authoritative result is whether the
    resource still exists afterwards.
    """
    actions = []
    for name in names:
        result = docker("rm", "-f", name, check=False)
        actions.append(
            {
                "resource": name,
                "kind": "container",
                "rm_exit": result.returncode,
                "stderr": result.stderr.strip(),
            }
        )
    for volume in volumes:
        result = docker("volume", "rm", "-f", volume, check=False)
        actions.append(
            {
                "resource": volume,
                "kind": "volume",
                "rm_exit": result.returncode,
                "stderr": result.stderr.strip(),
            }
        )

    inspection_errors = []
    leftover_containers = []
    for name in names:
        exists, error = resource_exists("container", name)
        if exists:
            leftover_containers.append(name)
        if error:
            inspection_errors.append({"resource": name, "kind": "container", "error": error})
    leftover_volumes = []
    for volume in volumes:
        exists, error = resource_exists("volume", volume)
        if exists:
            leftover_volumes.append(volume)
        if error:
            inspection_errors.append({"resource": volume, "kind": "volume", "error": error})
    command_failures = [
        action
        for action in actions
        if action["rm_exit"] != 0
        and (
            action["resource"] in leftover_containers
            or action["resource"] in leftover_volumes
        )
    ]
    return {
        "run_id": run_id,
        "checked_containers": names,
        "checked_volumes": volumes,
        "actions": actions,
        "leftover_containers": leftover_containers,
        "leftover_volumes": leftover_volumes,
        "command_failures": command_failures,
        "inspection_errors": inspection_errors,
        "clean": not leftover_containers
        and not leftover_volumes
        and not command_failures
        and not inspection_errors,
    }


def run_access(root: Path, run_id: str, negative: bool = False) -> dict:
    out_volume = f"{RUN_PREFIX}access-{run_id}"
    reader_name = f"{RUN_PREFIX}reader-{run_id}"
    result: dict = {
        "scenario": "local_project_access_negative" if negative else "local_project_access",
        "run_id": run_id,
        "checks": {},
        "passed": False,
        "manifest": None,
    }
    try:
        project = make_project_copy(root)
        if negative:
            (project / "src" / "release_gate.py").chmod(0o000)
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
            READER_IMAGE,
            "65534:65534",
            "/out",
            check=True,
        )
        reader_result, _ = container_run(
            image=READER_IMAGE,
            name=reader_name,
            volumes=[f"{project}:/project:ro", f"{out_volume}:/out"],
            entrypoint=[
                "python",
                "/app/read_project.py",
                "--root",
                "/project",
                "--output",
                "/out/manifest.json",
            ],
        )
        raw = volume_read(out_volume, "/out/manifest.json")
        manifest = json.loads(raw) if raw else None
        paths = {entry["path"] for entry in (manifest or {}).get("files", [])}
        skipped = {
            entry["path"]: entry["reason"] for entry in (manifest or {}).get("skipped", [])
        }
        entries = {entry["path"]: entry for entry in (manifest or {}).get("files", [])}
        required = [
            "README.md",
            "docs/RELEASE_POLICY.md",
            "src/release_gate.py",
            "data/sample_state.json",
        ]
        unreadable = [
            path
            for path in required
            if not entries.get(path, {}).get("sha256")
            or entries.get(path, {}).get("read_error")
        ]
        read_errors = [
            entry["path"]
            for entry in (manifest or {}).get("files", [])
            if entry.get("read_error")
        ]
        checks = {
            "reader_exit_ok": reader_result.returncode == 0,
            "required_files_hashed": not unreadable and not read_errors,
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
        result.update(
            {
                "checks": checks,
                "passed": all(checks.values()),
                "unreadable_required_files": unreadable,
                "read_errors": read_errors,
                "manifest": manifest,
                "reader_exit": reader_result.returncode,
                "reader_stderr": reader_result.stderr.strip(),
            }
        )
        result["negative_ok"] = (not result["passed"]) if negative else None
    except Exception as error:  # keep the failure in evidence, then still clean up
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        result["cleanup"] = cleanup(run_id, [reader_name], [out_volume])
    return result


def isolation_assessment(
    agent_inspect: dict, verifier_inspect: dict, observed: dict
) -> dict:
    def container_checks(inspect: dict) -> dict:
        security = [str(item) for item in (inspect.get("security_opt") or [])]
        binds = [str(item) for item in (inspect.get("binds") or [])]
        return {
            "inspection_present": bool(inspect),
            "network_mode_none": inspect.get("network_mode") == "none",
            "readonly_rootfs": inspect.get("readonly_rootfs") is True,
            "cap_drop_all": "ALL" in (inspect.get("cap_drop") or []),
            "non_root_user": inspect.get("user") == "65534:65534",
            "no_new_privileges": any("no-new-privileges" in item for item in security),
            "memory_limit": inspect.get("memory") == 134217728,
            "pids_limit": inspect.get("pids_limit") == 64,
            "has_binds": bool(binds),
        }

    agent_binds = [str(item) for item in (agent_inspect.get("binds") or [])]
    hidden = observed.get("hidden_access")
    probes = {
        "network_blocked": str(observed.get("network", "")).startswith("blocked"),
        "project_read_only": str(observed.get("project_write", "")).startswith("read-only"),
        "hidden_paths_absent": isinstance(hidden, dict)
        and bool(hidden)
        and all(value == "absent" for value in hidden.values()),
        "expectation_not_agent_mounted": not any("expectation" in item for item in agent_binds),
        "secrets_not_agent_mounted": not any(
            "secrets" in item or ".env" in item for item in agent_binds
        ),
    }
    assessment = {
        "agent": container_checks(agent_inspect),
        "verifier": container_checks(verifier_inspect),
        "probes": probes,
    }
    assessment["ok"] = (
        all(assessment["agent"].values())
        and all(assessment["verifier"].values())
        and all(probes.values())
    )
    return assessment


def run_case(case: str, root: Path, run_id: str) -> dict:
    state_volume = f"{RUN_PREFIX}state-{run_id}"
    out_volume = f"{RUN_PREFIX}out-{run_id}"
    agent_name = f"{RUN_PREFIX}agent-{run_id}"
    verify_name = f"{RUN_PREFIX}verify-{run_id}"
    expected_verdict = EXPECTED_VERDICT[case]
    result: dict = {
        "scenario": "synthetic_release_gate",
        "case": case,
        "run_id": run_id,
        "expected_verdict": expected_verdict,
        "observed_verdict": None,
        "case_ok": False,
        "agent_input_files": [],
        "agent_project_files": [],
    }

    try:
        project = make_project_copy(root)
        agent_project = make_agent_project(project, root / "agent-project")
        seed = seed_state(root)
        agent_input = root / "agent-input"
        verifier_input = root / "verifier-input"
        agent_input.mkdir()
        verifier_input.mkdir()
        (agent_input / "event.json").write_text(
            json.dumps(event_for(case), indent=2) + "\n", encoding="utf-8"
        )
        (verifier_input / "expectation.json").write_text(
            json.dumps(expectation_for(case), indent=2) + "\n", encoding="utf-8"
        )
        result["agent_input_files"] = relative_files(agent_input)
        result["agent_project_files"] = relative_files(agent_project)

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
            AGENT_IMAGE,
            "65534:65534",
            "/state",
            "/out",
            check=True,
        )

        agent_result, agent_inspect = container_run(
            image=AGENT_IMAGE,
            name=agent_name,
            volumes=[
                f"{agent_project}:/project:ro",
                f"{agent_input}:/input:ro",
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
        verifier_result, verifier_inspect = container_run(
            image=VERIFIER_IMAGE,
            name=verify_name,
            volumes=[
                f"{state_volume}:/state:ro",
                f"{out_volume}:/out",
                f"{verifier_input}:/input:ro",
            ],
            entrypoint=[
                "python",
                "/app/verify.py",
                "--require-hidden-access",
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
        agent_observations = (response or {}).get("observed") or {}

        image_probe = docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--user",
            "65534:65534",
            "--entrypoint",
            "sh",
            AGENT_IMAGE,
            "-c",
            "test ! -e /app/verify.py",
            check=False,
        )
        # Exit 0 means the image is verifier-free; exit 1 means the file is present.
        # Anything else is a Docker/probe failure, not evidence of absence.
        image_probe_ok = image_probe.returncode == 0
        image_probe_error = (
            None
            if image_probe.returncode in (0, 1)
            else (image_probe.stderr.strip() or f"probe exited {image_probe.returncode}")
        )
        agent_image_has_verifier = image_probe.returncode == 1
        isolation = isolation_assessment(agent_inspect, verifier_inspect, agent_observations)
        project_files = relative_files(agent_project)
        input_files = relative_files(agent_input)
        project_filtered = not any(
            path == ".env"
            or path.startswith(".env")
            or path == "secrets"
            or path.startswith("secrets/")
            for path in project_files
        )
        only_event = input_files == ["event.json"]
        case_ok = (
            observed_verdict == expected_verdict
            and verifier_result.returncode
            == {"passed": 0, "failed": 2, "unverified": 3}[expected_verdict]
            and image_probe_ok
            and not agent_image_has_verifier
            and isolation["ok"]
            and project_filtered
            and only_event
        )
        result.update(
            {
                "observed_verdict": observed_verdict,
                "case_ok": case_ok,
                "agent_exit": agent_result.returncode,
                "verifier_exit": verifier_result.returncode,
                "agent_observed": agent_observations,
                "hidden_material": agent_observations.get("hidden_access"),
                "agent_image_has_verifier": agent_image_has_verifier,
                "agent_image_probe_ok": image_probe_ok,
                "agent_image_probe_exit": image_probe.returncode,
                "agent_image_probe_error": image_probe_error,
                "agent_project_filtered": project_filtered,
                "agent_input_only_event": only_event,
                "isolation_checks": isolation,
                "isolation_ok": isolation["ok"],
                "verdict": verdict,
                "isolation": {
                    "network_mode": agent_inspect.get("network_mode"),
                    "readonly_rootfs": agent_inspect.get("readonly_rootfs"),
                    "cap_drop": agent_inspect.get("cap_drop"),
                    "user": agent_inspect.get("user"),
                    "binds": agent_inspect.get("binds"),
                },
                "agent_isolation": agent_inspect,
                "verifier_isolation": verifier_inspect,
                "agent_stderr": agent_result.stderr.strip(),
                "verifier_stderr": verifier_result.stderr.strip(),
            }
        )
    except Exception as error:  # record the failure, then always attempt cleanup
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        result["cleanup"] = cleanup(run_id, [agent_name, verify_name], [state_volume, out_volume])
    return result

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default="pass,fail,missing_evidence,claim_mismatch,unrelated_mutation",
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
    summary = {
        "started_at": stamp,
        "images": {
            "agent": AGENT_IMAGE,
            "verifier": VERIFIER_IMAGE,
            "reader": READER_IMAGE,
        },
        "access": None,
        "cases": [],
    }

    if not args.skip_build:
        build_images()

    with tempfile.TemporaryDirectory(prefix="stage0-run-") as tmp:
        root = Path(tmp)
        access_id = f"{stamp}-access"
        access = run_access(root / "access", access_id)
        summary["access"] = access
        print(f"local_project_access: {'PASS' if access['passed'] else 'FAIL'}")

        access_negative = run_access(root / "access-negative", f"{stamp}-access-negative", negative=True)
        summary["access_negative"] = access_negative
        print(
            "local_project_access_negative: "
            f"{'PASS' if access_negative['negative_ok'] else 'FAIL'} "
            f"(passed={access_negative['passed']}, "
            f"unreadable={access_negative.get('unreadable_required_files')})"
        )

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
                + (f", error={result['error']}" if result.get("error") else "")
            )

    summary["finished_at"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary["all_ok"] = bool(
        summary["access"]
        and summary["access"]["passed"]
        and summary["access"]["cleanup"]["clean"]
        and summary["access_negative"]["negative_ok"]
        and summary["access_negative"]["cleanup"]["clean"]
        and all(case["case_ok"] for case in summary["cases"])
        and all(not case.get("error") for case in summary["cases"])
        and all(case["cleanup"]["clean"] for case in summary["cases"])
    )
    output = EVIDENCE / f"{stamp}-summary.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"evidence: {output}")
    print(f"all_ok: {summary['all_ok']}")
    return 0 if summary["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
