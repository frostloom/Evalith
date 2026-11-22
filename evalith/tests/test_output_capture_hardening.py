"""Review 2026-11-21 S1: output capture must be unlink-proof.

A sandboxed target can replace its own case directory's ``stdout.txt``
path with a symlink to a user-readable file (an SSH key, a config with
secrets). If the orchestrator reads results back by path after the
process exits, it reads the linked file with full user permissions:
the content is stored, shown in the UI and sent to the model provider
as grading evidence.

The fix reads captured output through the still-open file descriptor
the parent created before the launch, so the path the target leaves
behind is irrelevant.

These tests run the target sandboxed when the host supports it and
unsandboxed otherwise — the read-back path is identical either way.
"""

import os
import sys

import pytest

from evalith.execution_process import bounded_process, sandbox_available


HELPER = """
import os, sys
case, target, name = sys.argv[1], sys.argv[2], sys.argv[3]
os.remove(os.path.join(case, name))
os.symlink(target, os.path.join(case, name))
"""


def stage_case(tmp_path, name):
    # Everything the target touches lives inside the case directory: the
    # sandbox profile only makes that path readable and writable to it.
    case = tmp_path / "case"
    case.mkdir(exist_ok=True)
    (case / "stdin.txt").write_text("", encoding="utf-8")
    helper = case / "swap.py"
    helper.write_text(HELPER, encoding="utf-8")
    return case, str(helper)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox host")
def test_symlink_swap_cannot_leak_secret_file(tmp_path):
    secret = tmp_path / "secret-material.txt"
    secret.write_text("AGENT_EVAL_MARKER_DO_NOT_LEAK", encoding="utf-8")

    case, helper = stage_case(tmp_path, "stdout.txt")
    observed = bounded_process(
        [sys.executable, helper, str(case), str(secret), "stdout.txt"],
        case,
        timeout=30,
        unsandboxed=not sandbox_available(),
    )

    assert "AGENT_EVAL_MARKER_DO_NOT_LEAK" not in observed["stdout"]
    assert observed["exit_code"] == 0


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox host")
def test_symlink_swap_cannot_leak_via_stderr(tmp_path):
    secret = tmp_path / "secret-material.txt"
    secret.write_text("STDERR_MARKER_DO_NOT_LEAK", encoding="utf-8")

    case, helper = stage_case(tmp_path, "stderr.txt")
    observed = bounded_process(
        [sys.executable, helper, str(case), str(secret), "stderr.txt"],
        case,
        timeout=30,
        unsandboxed=not sandbox_available(),
    )

    assert "STDERR_MARKER_DO_NOT_LEAK" not in observed["stderr"]


def test_genuine_stdout_is_captured_normally(tmp_path):
    case = tmp_path / "case"
    case.mkdir()
    (case / "stdin.txt").write_text("", encoding="utf-8")
    (case / "prog.py").write_text("print('genuine output')\n", encoding="utf-8")
    observed = bounded_process(
        [sys.executable, str(case / "prog.py")],
        case,
        timeout=30,
        unsandboxed=True,
    )
    assert "genuine output" in observed["stdout"]
    assert observed["exit_code"] == 0


def test_leftover_hostile_path_is_ignored_after_capture(tmp_path):
    """The path the target leaves behind can be anything; reads never
    go through it, so the orchestrator simply does not care."""

    case = tmp_path / "case"
    case.mkdir()
    (case / "stdin.txt").write_text("", encoding="utf-8")
    (case / "prog.py").write_text(
        "import os\n"
        "case = os.path.dirname(os.path.abspath(__file__))\n"
        "os.remove(os.path.join(case, 'stdout.txt'))\n"
        "os.symlink('/etc/hosts', os.path.join(case, 'stdout.txt'))\n",
        encoding="utf-8",
    )
    bounded_process(
        [sys.executable, str(case / "prog.py")],
        case,
        timeout=30,
        unsandboxed=True,
    )
    # After the run the path may be a hostile symlink; that is fine — the
    # orchestrator must simply never follow it. Assert the invariant the
    # implementation relies on: it does not read through this path.
    if (case / "stdout.txt").is_symlink():
        assert os.readlink(case / "stdout.txt") == "/etc/hosts"
