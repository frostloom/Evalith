"""SQLite persistence for the phase-1 workspace.

SQLite is deliberate for phase 1: the workspace is a single-user local tool
and the data model is small.  The session uniqueness guarantee lives in the
database (``UNIQUE(project_id, kind)``), not in application locking, so two
concurrent "enter project" requests cannot create two main sessions.  The
schema has no cross-project foreign key shortcuts: every query that returns
project-scoped data also filters by ``project_id``.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_configs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    base_url TEXT,
    model_name TEXT NOT NULL,
    api_key_encrypted TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_test_ok INTEGER,
    last_test_message TEXT,
    last_test_at TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    root_dev INTEGER,
    root_ino INTEGER,
    include_paths TEXT NOT NULL DEFAULT '[]',
    exclude_patterns TEXT NOT NULL DEFAULT '[]',
    supplemental TEXT NOT NULL DEFAULT '[]',
    model_config_id TEXT,
    snapshot_id TEXT,
    analysis_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'main',
    created_at TEXT NOT NULL,
    UNIQUE (project_id, kind)
);

CREATE TABLE IF NOT EXISTS messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    payload TEXT,
    model TEXT,
    sent_scope TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);

CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    root TEXT NOT NULL,
    manifest TEXT NOT NULL,
    excluded TEXT NOT NULL,
    read_errors TEXT NOT NULL,
    selected_scope TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS understandings (
    project_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    agent_or_flow TEXT NOT NULL DEFAULT '',
    known TEXT NOT NULL DEFAULT '[]',
    inferred TEXT NOT NULL DEFAULT '[]',
    unknowns TEXT NOT NULL DEFAULT '[]',
    sources TEXT NOT NULL DEFAULT '[]',
    sufficient INTEGER NOT NULL DEFAULT 0,
    sufficient_reason TEXT NOT NULL DEFAULT '',
    user_continued INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    error TEXT,
    updated_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def init(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            # Minimal in-place migration for databases created by an earlier
            # phase-1 build; new databases already have these columns.
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(projects)").fetchall()
            }
            for name in ("root_dev", "root_ino"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE projects ADD COLUMN {name} INTEGER")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # model configs
    # ------------------------------------------------------------------
    def create_model_config(self, row: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO model_configs
                (id, name, provider, base_url, model_name, api_key_encrypted,
                 created_at, updated_at)
                VALUES (:id, :name, :provider, :base_url, :model_name, :api_key_encrypted,
                        :created_at, :updated_at)""",
                row,
            )

    def list_model_configs(self) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM model_configs ORDER BY created_at ASC"
                )
            )

    def get_model_config(self, model_config_id: str | None) -> sqlite3.Row | None:
        if not model_config_id:
            return None
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM model_configs WHERE id = ?", (model_config_id,)
            ).fetchone()

    def update_model_test(
        self, model_config_id: str, ok: bool, message: str, at: str
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """UPDATE model_configs
                   SET last_test_ok = ?, last_test_message = ?, last_test_at = ?, updated_at = ?
                   WHERE id = ?""",
                (1 if ok else 0, message, at, at, model_config_id),
            )

    # ------------------------------------------------------------------
    # projects / snapshots
    # ------------------------------------------------------------------
    def create_project(self, row: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO projects
                (id, name, root_path, root_dev, root_ino, include_paths,
                 exclude_patterns, supplemental, model_config_id, snapshot_id,
                 analysis_error, created_at, updated_at)
                VALUES (:id, :name, :root_path, :root_dev, :root_ino, :include_paths,
                        :exclude_patterns, :supplemental, :model_config_id,
                        :snapshot_id, :analysis_error, :created_at, :updated_at)""",
                row,
            )

    def list_projects(self) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return list(
                connection.execute("SELECT * FROM projects ORDER BY created_at DESC")
            )

    def get_project(self, project_id: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()

    def update_project_snapshot(
        self, project_id: str, snapshot_id: str, analysis_error: str | None
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """UPDATE projects SET snapshot_id = ?, analysis_error = ?, updated_at = ?
                   WHERE id = ?""",
                (snapshot_id, analysis_error, utc_now(), project_id),
            )

    def update_project_model(self, project_id: str, model_config_id: str | None) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE projects SET model_config_id = ?, updated_at = ? WHERE id = ?",
                (model_config_id, utc_now(), project_id),
            )

    def create_snapshot(self, row: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO snapshots
                (id, project_id, digest, root, manifest, excluded, read_errors,
                 selected_scope, created_at)
                VALUES (:id, :project_id, :digest, :root, :manifest, :excluded,
                        :read_errors, :selected_scope, :created_at)""",
                row,
            )

    def get_snapshot(self, snapshot_id: str | None) -> sqlite3.Row | None:
        if not snapshot_id:
            return None
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()

    # ------------------------------------------------------------------
    # sessions / messages
    # ------------------------------------------------------------------
    def ensure_main_session(self, project_id: str) -> sqlite3.Row:
        """Return the project's single main session, creating it atomically."""
        session_id = f"ses_{project_id}"
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO sessions (id, project_id, kind, created_at)
                   VALUES (?, ?, 'main', ?)
                   ON CONFLICT(project_id, kind) DO NOTHING""",
                (session_id, project_id, utc_now()),
            )
            row = connection.execute(
                "SELECT * FROM sessions WHERE project_id = ? AND kind = 'main'",
                (project_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - would mean the unique index is broken
            raise RuntimeError("main session could not be resolved")
        return row

    def get_main_session(self, project_id: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM sessions WHERE project_id = ? AND kind = 'main'",
                (project_id,),
            ).fetchone()

    def count_sessions(self, project_id: str) -> int:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM sessions WHERE project_id = ?", (project_id,)
            ).fetchone()
        return int(row["n"])

    def add_message(self, row: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO messages
                (id, session_id, project_id, role, content, payload, model, sent_scope, created_at)
                VALUES (:id, :session_id, :project_id, :role, :content, :payload,
                        :model, :sent_scope, :created_at)""",
                row,
            )

    def list_messages(self, project_id: str, session_id: str) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return list(
                connection.execute(
                    """SELECT * FROM messages
                       WHERE project_id = ? AND session_id = ?
                       ORDER BY seq ASC""",
                    (project_id, session_id),
                )
            )

    # ------------------------------------------------------------------
    # understanding
    # ------------------------------------------------------------------
    def upsert_understanding(self, row: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO understandings
                (project_id, snapshot_id, summary, agent_or_flow, known, inferred,
                 unknowns, sources, sufficient, sufficient_reason, user_continued,
                 model, error, updated_at)
                VALUES (:project_id, :snapshot_id, :summary, :agent_or_flow, :known,
                        :inferred, :unknowns, :sources, :sufficient, :sufficient_reason,
                        :user_continued, :model, :error, :updated_at)
                ON CONFLICT(project_id) DO UPDATE SET
                    snapshot_id = excluded.snapshot_id,
                    summary = excluded.summary,
                    agent_or_flow = excluded.agent_or_flow,
                    known = excluded.known,
                    inferred = excluded.inferred,
                    unknowns = excluded.unknowns,
                    sources = excluded.sources,
                    sufficient = excluded.sufficient,
                    sufficient_reason = excluded.sufficient_reason,
                    user_continued = excluded.user_continued,
                    model = excluded.model,
                    error = excluded.error,
                    updated_at = excluded.updated_at""",
                row,
            )

    def get_understanding(self, project_id: str) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM understandings WHERE project_id = ?", (project_id,)
            ).fetchone()

    def clear_understanding(self, project_id: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM understandings WHERE project_id = ?", (project_id,)
            )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def loads(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
