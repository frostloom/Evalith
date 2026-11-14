"""Runtime configuration for the Evalith phase-1 service.

The service is intentionally host-first: local project directories are read
through the host filesystem, never through a container path translation.  A
container deployment must mount the selected project read-only and translate
the path with ``EVALITH_PROJECT_MOUNT_MAP`` (documented in
``docs/stage1/project-access.md``); the same allowlist and secret rules apply.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    return Path(os.environ.get("EVALITH_DATA_DIR", ".evalith")).expanduser()


@dataclass
class Settings:
    """Configuration resolved once per application instance."""

    data_dir: Path = field(default_factory=_default_data_dir)
    database_path: Path | None = None
    secret_key: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8090
    #: Remote (non-loopback) access is opt-in; the API additionally rejects
    #: non-loopback clients unless this is true.
    allow_remote: bool = False
    #: Preview budget handed to the model for a single project analysis.
    context_budget_chars: int = 24_000
    #: Hard cap per selected file; larger files are fingerprinted but not read
    #: into the model context.
    max_file_bytes: int = 512_000
    #: Hard cap on files per snapshot.
    max_files: int = 400
    #: Model request timeout in seconds.
    model_timeout_seconds: float = 60.0
    go_proxy: str = "https://proxy.golang.org,direct"
    go_sdkroot: str | None = None
    #: Paid OpenAI-compatible calls stay disabled unless an operator explicitly
    #: opts in; no monetary budget control exists in phase 1.
    allow_paid_models: bool = False
    #: Phase 1 supports only ``host``. Any other value fails closed; container
    #: mount translation is a later-phase deliverable, not a configured path.
    access_mode: str = "host"
    static_dir: Path | None = None
    #: Host header allowlist for the loopback-only local service.  DNS
    #: rebinding sends the attacker hostname as Host/Origin, so rejecting
    #: non-loopback hosts is required even without authentication.
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "::1", "testserver")

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        if self.database_path is None:
            self.database_path = self.data_dir / "evalith.db"
        self.database_path = Path(self.database_path).expanduser().resolve()
        if self.static_dir is None:
            candidate = Path(__file__).resolve().parent / "web" / "dist"
            if not candidate.exists():
                candidate = Path(__file__).resolve().parents[2] / "web" / "dist"
            self.static_dir = candidate

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)


def settings_from_env() -> Settings:
    return Settings(
        data_dir=_default_data_dir(),
        database_path=os.environ.get("EVALITH_DB_PATH") or None,
        secret_key=os.environ.get("EVALITH_SECRET_KEY") or None,
        api_host=os.environ.get("EVALITH_API_HOST", "127.0.0.1"),
        api_port=int(os.environ.get("EVALITH_API_PORT", "8090")),
        allow_remote=os.environ.get("EVALITH_ALLOW_REMOTE", "").strip().lower()
        in ("1", "true", "yes"),
        context_budget_chars=int(os.environ.get("EVALITH_CONTEXT_BUDGET", "24000")),
        max_file_bytes=int(os.environ.get("EVALITH_MAX_FILE_BYTES", "512000")),
        max_files=int(os.environ.get("EVALITH_MAX_FILES", "400")),
        model_timeout_seconds=float(os.environ.get("EVALITH_MODEL_TIMEOUT", "60")),
        go_proxy=os.environ.get("EVALITH_GO_PROXY", "https://proxy.golang.org,direct"),
        go_sdkroot=os.environ.get("EVALITH_GO_SDKROOT") or None,
        allow_paid_models=os.environ.get(
            "EVALITH_ALLOW_PAID_MODELS", ""
        ).strip().lower()
        in ("1", "true", "yes"),
        access_mode=os.environ.get("EVALITH_ACCESS_MODE", "host"),
        allowed_hosts=tuple(
            item.strip().lower()
            for item in os.environ.get("EVALITH_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        )
        or ("127.0.0.1", "localhost", "::1", "testserver"),
    )
