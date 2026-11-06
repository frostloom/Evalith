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
    #: Preview budget handed to the model for a single project analysis.
    context_budget_chars: int = 24_000
    #: Hard cap per selected file; larger files are fingerprinted but not read
    #: into the model context.
    max_file_bytes: int = 512_000
    #: Hard cap on files per snapshot.
    max_files: int = 400
    #: Model request timeout in seconds.
    model_timeout_seconds: float = 60.0
    #: ``host`` reads paths as-is.  ``container`` maps host roots through
    #: ``project_mount_map`` and refuses paths outside a configured mount.
    access_mode: str = "host"
    project_mount_map: dict[str, str] = field(default_factory=dict)
    static_dir: Path | None = None

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
    raw_map: dict[str, str] = {}
    for item in os.environ.get("EVALITH_PROJECT_MOUNT_MAP", "").split(";"):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(
                "EVALITH_PROJECT_MOUNT_MAP entries must be host_root=container_root"
            )
        host, container = item.split("=", 1)
        raw_map[host.strip()] = container.strip()
    return Settings(
        data_dir=_default_data_dir(),
        database_path=os.environ.get("EVALITH_DB_PATH") or None,
        secret_key=os.environ.get("EVALITH_SECRET_KEY") or None,
        api_host=os.environ.get("EVALITH_API_HOST", "127.0.0.1"),
        api_port=int(os.environ.get("EVALITH_API_PORT", "8090")),
        context_budget_chars=int(os.environ.get("EVALITH_CONTEXT_BUDGET", "24000")),
        max_file_bytes=int(os.environ.get("EVALITH_MAX_FILE_BYTES", "512000")),
        max_files=int(os.environ.get("EVALITH_MAX_FILES", "400")),
        model_timeout_seconds=float(os.environ.get("EVALITH_MODEL_TIMEOUT", "60")),
        access_mode=os.environ.get("EVALITH_ACCESS_MODE", "host"),
        project_mount_map=raw_map,
    )
