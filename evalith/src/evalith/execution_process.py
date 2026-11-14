"""Owned, bounded subprocesses with filesystem/network restrictions on macOS."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .service import WorkspaceError


def sandbox_available() -> bool:
    return sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file()


def bounded_process(
    command: list[str],
    directory: Path,
    *,
    timeout: float,
    env: dict[str, str] | None = None,
    cancel: Callable[[], bool] | None = None,
    loopback: bool = False,
    unsandboxed: bool = False,
) -> dict:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    (directory / "tmp").mkdir(exist_ok=True)
    if unsandboxed:
        # The process still belongs to this case — fresh env, owned process
        # group, timeout, cancellation and output caps — but runs without the
        # sandbox-exec profile. Reserved for orchestrators whose isolation
        # boundary is elsewhere (e.g. the Harbor backend's containers, whose
        # CLI needs the Docker socket and image pulls).
        arguments = list(command)
    else:
        if not sandbox_available():
            raise WorkspaceError(
                "此主机缺少受支持的命令隔离器，未执行程序",
                status_code=422,
                code="sandbox_unavailable",
            )
        profile = (
            "(version 1)\n(allow default)\n(deny file-write*)\n(allow file-write* (subpath "
            + json.dumps(str(directory), ensure_ascii=False)
            + '))\n(allow file-write* (literal "/dev/null"))\n(deny network*)\n'
        )
        # The copied target may read its own inputs and installed runtimes, never
        # unrelated projects or the user's login/configuration directories.
        profile += '(deny file-read*)\n(allow file-read-metadata)\n(allow file-read* (literal "/"))\n'
        readable = [
            directory,
            Path("/System"),
            Path("/usr"),
            Path("/dev"),
            Path("/opt/homebrew"),
            Path("/Library/Developer/CommandLineTools"),
            Path("/Library/Frameworks"),
            Path("/private/var/db/timezone"),
            Path("/private/preboot"),
        ]
        executable = shutil.which(command[0])
        if executable:
            binary = Path(executable).resolve()
            profile += (
                "(allow file-read* (literal "
                + json.dumps(str(binary), ensure_ascii=False)
                + "))\n"
            )
            if binary.name.startswith("python") and binary.parent.name == "bin":
                readable.append(binary.parent.parent)
                # A venv symlink resolves to the base interpreter, but Python also
                # reads pyvenv.cfg and packages through the original launch path.
                launch = Path(executable).absolute()
                if (
                    launch.parent.name == "bin"
                    and (launch.parent.parent / "pyvenv.cfg").is_file()
                ):
                    readable.append(launch.parent.parent)
        for root in readable:
            profile += (
                "(allow file-read* (subpath "
                + json.dumps(str(root), ensure_ascii=False)
                + "))\n"
            )
        for path in (
            "/private/etc/localtime",
            "/private/etc/resolv.conf",
            "/private/etc/hosts",
        ):
            profile += "(allow file-read* (literal " + json.dumps(path) + "))\n"
        if loopback:
            profile += (
                '(allow network* (local ip "localhost:*") (remote ip "localhost:*"))\n'
            )
        policy = directory / "sandbox.sb"
        policy.write_text(profile)
        arguments = ["/usr/bin/sandbox-exec", "-f", str(policy), *command]
    allowed_env = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT"}
    if unsandboxed:
        allowed_env |= {"HOME", "DOCKER_HOST", "DOCKER_CONTEXT"}
    safe_env = {
        key: value
        for key, value in os.environ.items()
        if key in allowed_env
    }
    safe_env.update(
        {
            "TMPDIR": str(directory / "tmp"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    safe_env.update(env or {})
    started = time.monotonic()
    stdin_file = directory / "stdin.txt"
    if unsandboxed and not stdin_file.exists():
        # Sandbox callers always stage stdin.txt themselves; only the
        # orchestrator mode may start without one.
        stdin_file.touch()
    with (
        (directory / "stdout.txt").open("wb") as out,
        (directory / "stderr.txt").open("wb") as err,
        stdin_file.open("rb") as inp,
    ):
        process = subprocess.Popen(
            arguments,
            cwd=directory,
            stdin=inp,
            stdout=out,
            stderr=err,
            env=safe_env,
            start_new_session=True,
        )
        reason = None
        try:
            while process.poll() is None:
                if cancel and cancel():
                    reason = "cancelled"
                    break
                if time.monotonic() - started > timeout:
                    reason = "timeout"
                    break
                if (
                    os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size
                    > 4_000_000
                ):
                    reason = "output_limit"
                    break
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
                except ProcessLookupError:
                    pass
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
    # A target can exit while its own children are still alive. The process
    # group belongs to this case, so reap those descendants as well.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return {
        "stdout": (directory / "stdout.txt").read_text(errors="replace")[:2_000_000],
        "stderr": (directory / "stderr.txt").read_text(errors="replace")[:200_000],
        "exit_code": process.returncode,
        "process_error": reason,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "cleanup_status": "completed",
    }
