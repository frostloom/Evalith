import os
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
