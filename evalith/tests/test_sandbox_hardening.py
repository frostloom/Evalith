"""Review 2026-11-21 S2/S3: the sandbox profile must deny mach IPC and
narrow loopback to the bridge port.

S2: with ``(allow default)`` the profile left mach-lookup open, so a
sandboxed target could talk to launchd services (cfprefsd,
SecurityServer) and read preferences or keychain items that the
file-read denials were meant to protect. The profile now denies
``mach-lookup*``, ``mach-register`` and ``process-info*``.

S3: the loopback allowance covered ``localhost:*`` — every local
port, not just the model bridge. It now allows exactly
``127.0.0.1:<bridge_port>``.

All probes run through the real ``bounded_process`` sandbox.
"""

import socket
import sys
import threading

import pytest

from evalith.execution_process import bounded_process, sandbox_available

NETPROBE = """
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
try:
    socket.create_connection((host, port), timeout=3).close()
    print("CONNECT_OK")
except Exception as exc:
    print("CONNECT_FAIL", type(exc).__name__)
"""


def stage(tmp_path, script, name="probe.py"):
    case = tmp_path / "case"
    case.mkdir(exist_ok=True)
    (case / "stdin.txt").write_text("", encoding="utf-8")
    (case / name).write_text(script, encoding="utf-8")
    return case, case / name


def listener():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    return server, server.getsockname()[1]


def accept_quietly(server):
    def run():
        try:
            server.settimeout(10)
            server.accept()
        except OSError:
            pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")
def test_profile_denies_on_demand_mach_lookups(tmp_path):
    """S2: the generated profile must deny on-demand mach service lookups.

    Behavioral note: on this OS build launchd hands every process an
    inherited bootstrap port, so already-bootstrapped services stay
    reachable regardless (an earlier probe asserting launchctl dies
    under the deny did not hold). The deny gates the *lookup* class on
    builds that enforce it and costs legitimate targets nothing — the
    bisect in the validation doc shows sqlite/python run unaffected —
    so the profile text is pinned instead of an unreproducible kill.
    """

    case, probe = stage(tmp_path, "print('mach profile probe')\n")
    observed = bounded_process([sys.executable, str(probe)], case, timeout=30)
    assert observed["exit_code"] == 0
    policy = (case / "sandbox.sb").read_text(encoding="utf-8")
    assert "(deny mach-lookup)" in policy
    assert "(deny mach-register)" in policy


@pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")
def test_loopback_connects_only_to_the_bridge_port(tmp_path):
    """S3: the allowed port works, every other local port is refused."""

    bridge, bridge_port = listener()
    other, other_port = listener()
    assert bridge_port != other_port
    accept_quietly(bridge)
    accept_quietly(other)
    try:
        case, probe = stage(tmp_path, NETPROBE)

        allowed = bounded_process(
            [sys.executable, str(probe), "127.0.0.1", str(bridge_port)],
            case,
            timeout=30,
            loopback=True,
            bridge_port=bridge_port,
        )
        assert "CONNECT_OK" in allowed["stdout"], allowed["stdout"]

        blocked = bounded_process(
            [sys.executable, str(probe), "127.0.0.1", str(other_port)],
            case,
            timeout=30,
            loopback=True,
            bridge_port=bridge_port,
        )
        assert "CONNECT_OK" not in blocked["stdout"], blocked["stdout"]
    finally:
        bridge.close()
        other.close()


@pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")
def test_loopback_without_port_fails_closed(tmp_path):
    case, probe = stage(tmp_path, NETPROBE)
    from evalith.service import WorkspaceError

    with pytest.raises(WorkspaceError):
        bounded_process(
            [sys.executable, str(probe), "127.0.0.1", "1"],
            case,
            timeout=30,
            loopback=True,
        )


@pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")
def test_hardened_profile_still_runs_plain_targets(tmp_path):
    case, probe = stage(tmp_path, "print('plain target ok')\n")
    observed = bounded_process(
        [sys.executable, str(probe)],
        case,
        timeout=30,
    )
    assert observed["exit_code"] == 0
    assert "plain target ok" in observed["stdout"]
