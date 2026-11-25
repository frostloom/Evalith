"""Write Evalith tasks as an EvalScope eval_set.v1.jsonl file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .mapping import map_task


def export_eval_set(
    records: list[dict[str, Any]],
    *,
    snapshot: dict[str, Any],
    executor: dict[str, Any] | None,
    out_path: Path,
) -> Path:
    project_root = str(snapshot.get('root', ''))
    snapshot_files = list(snapshot.get('files') or [])
    tasks = []
    for record in records:
        enriched = {**record, '_snapshot_files': snapshot_files}
        tasks.append(map_task(enriched, project_root=project_root, executor=executor))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as handle:
        for task in tasks:
            handle.write(json.dumps(task, ensure_ascii=False) + '\n')
    return out_path
