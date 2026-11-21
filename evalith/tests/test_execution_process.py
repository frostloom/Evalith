import os
import signal
from evalith.execution_process import bounded_process


def test_process_cleanup_error_is_reported(tmp_path, monkeypatch):
    work = tmp_path / "case"

    def deny_cleanup(*_):
        raise PermissionError("operation not permitted")

    monkeypatch.setattr(os, "killpg", deny_cleanup)
    observed = bounded_process(
        ["/usr/bin/true"],
        work,
        timeout=2,
        unsandboxed=True,
    )

    assert observed["exit_code"] == 0
    assert observed["cleanup_status"] == "failed"
    assert "operation not permitted" in observed["cleanup_error"]


def test_successful_sigkill_fallback_is_not_reported_as_cleanup_failure(
    tmp_path, monkeypatch
):
    work = tmp_path / "case"
    real_killpg = os.killpg
    calls = []

    def deny_terminate_but_allow_kill(pid, sig):
        calls.append(sig)
        if sig == signal.SIGTERM:
            raise PermissionError("graceful termination denied")
        return real_killpg(pid, sig)

    monkeypatch.setattr(os, "killpg", deny_terminate_but_allow_kill)
    observed = bounded_process(
        ["/bin/sleep", "2"],
        work,
        timeout=0,
        unsandboxed=True,
    )

    assert calls == [signal.SIGTERM, signal.SIGKILL]
    assert observed["cleanup_status"] == "completed"
    assert observed["cleanup_error"] is None
