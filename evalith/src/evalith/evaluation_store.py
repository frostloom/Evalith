"""Project-scoped evaluation records and immutable task revisions."""
from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from .db import Database, utc_now
from .service import WorkspaceError


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class EvaluationStore:
    def __init__(self, db: Database):
        self.db = db
        with db.connection() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS evaluation_records (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    kind TEXT NOT NULL, status TEXT NOT NULL,
                    data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS evaluation_records_project
                    ON evaluation_records(project_id, kind, created_at);
                CREATE TABLE IF NOT EXISTS evaluation_task_versions (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    version INTEGER NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(task_id, version)
                );
            ''')

    @staticmethod
    def _record(row: Any) -> dict[str, Any]:
        return {**json.loads(row['data']), **{key: row[key] for key in ('id','project_id','kind','status','created_at','updated_at')}}

    def create(self, project_id: str, kind: str, data: dict[str, Any], *, status: str = 'pending', record_id: str | None = None) -> dict[str, Any]:
        record_id = record_id or new_id(kind)
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute('INSERT INTO evaluation_records VALUES (?,?,?,?,?,?,?)', (record_id, project_id, kind, status, json.dumps(data, ensure_ascii=False), now, now))
        return self.get(project_id, kind, record_id)

    def get(self, project_id: str, kind: str, record_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute('SELECT * FROM evaluation_records WHERE id=? AND project_id=? AND kind=?', (record_id, project_id, kind)).fetchone()
        if row is None:
            raise WorkspaceError('评测记录不存在', status_code=404, code='evaluation_not_found')
        return self._record(row)

    def create_bundle(self, project_id: str, records: list[dict[str, Any]]) -> None:
        """Commit a validated preparation and its initial task revisions together."""
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for record in records:
                encoded = json.dumps(
                    record["data"], ensure_ascii=False, allow_nan=False
                )
                connection.execute(
                    "INSERT INTO evaluation_records VALUES (?,?,?,?,?,?,?)",
                    (
                        record["id"],
                        project_id,
                        record["kind"],
                        record["status"],
                        encoded,
                        now,
                        now,
                    ),
                )
                if record["kind"] == "task":
                    data = record["data"]
                    connection.execute(
                        "INSERT INTO evaluation_task_versions VALUES (?,?,?,?,?,?)",
                        (data["version_id"], record["id"], project_id, 1, encoded, now),
                    )

    def list(self, project_id: str, kind: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            rows = connection.execute('SELECT * FROM evaluation_records WHERE project_id=? AND kind=? ORDER BY rowid DESC LIMIT 200', (project_id, kind)).fetchall()
        return [self._record(row) for row in rows]

    def mutate(self, project_id: str, kind: str, record_id: str, change: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM evaluation_records WHERE id=? AND project_id=? AND kind=?', (record_id, project_id, kind)).fetchone()
            if row is None:
                raise WorkspaceError('评测记录不存在', status_code=404)
            current = self._record(row)
            changed = change(current)
            data = {k:v for k,v in changed.items() if k not in ('id','project_id','kind','status','created_at','updated_at')}
            connection.execute('UPDATE evaluation_records SET status=?, data=?, updated_at=? WHERE id=? AND project_id=? AND kind=?', (changed['status'], json.dumps(data, ensure_ascii=False), utc_now(), record_id, project_id, kind))
        return self.get(project_id, kind, record_id)

    def update(self, project_id: str, kind: str, record_id: str, **values: Any) -> dict[str, Any]:
        return self.mutate(project_id, kind, record_id, lambda current: {**current, **values})

    def save_task(self, project_id: str, data: dict[str, Any], *, task_id: str | None = None) -> dict[str, Any]:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if task_id:
                row = connection.execute("SELECT * FROM evaluation_records WHERE project_id=? AND kind='task' AND id=?", (project_id,task_id)).fetchone()
                if row is None:
                    raise WorkspaceError('题目不存在', status_code=404)
                version = json.loads(row['data'])['version'] + 1
            else:
                task_id, version = new_id('task'), 1
            version_id = new_id('ver')
            saved = {**data, 'version':version, 'version_id':version_id, 'task_id':task_id}
            connection.execute('INSERT INTO evaluation_task_versions VALUES (?,?,?,?,?,?)', (version_id,task_id,project_id,version,json.dumps(saved,ensure_ascii=False),now))
            encoded = json.dumps(saved,ensure_ascii=False)
            if version == 1:
                connection.execute('INSERT INTO evaluation_records VALUES (?,?,?,?,?,?,?)', (task_id,project_id,'task','active',encoded,now,now))
            else:
                connection.execute("UPDATE evaluation_records SET data=?, updated_at=? WHERE id=? AND project_id=? AND kind='task'", (encoded,now,task_id,project_id))
        return self.get(project_id,'task',task_id)

    def task_version(self, project_id: str, version_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute('SELECT * FROM evaluation_task_versions WHERE id=? AND project_id=?', (version_id,project_id)).fetchone()
        if row is None:
            raise WorkspaceError('题目版本不存在',status_code=404)
        return {**json.loads(row['data']),'id':version_id,'project_id':project_id,'created_at':row['created_at']}

    def versions(self, project_id: str, task_id: str) -> list[dict[str, Any]]:
        self.get(project_id,'task',task_id)
        with self.db.connection() as connection:
            rows=connection.execute('SELECT id FROM evaluation_task_versions WHERE project_id=? AND task_id=? ORDER BY version DESC', (project_id,task_id)).fetchall()
        return [self.task_version(project_id,row['id']) for row in rows]
