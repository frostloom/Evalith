#!/usr/bin/env python3
"""Build a manifest binding an eval set to its source snapshot and versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan', required=True)
    parser.add_argument('--eval-set', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    snapshot = json.loads(Path(args.scan).read_text(encoding='utf-8'))
    if not isinstance(snapshot, dict):
        print('error: scan must be a JSON object')
        return 1
    raw_files = snapshot.get('files', [])
    if not isinstance(raw_files, list):
        print('error: scan.files must be a list')
        return 1
    known = {}
    for item in raw_files:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            print('error: scan.files entries must be objects with a path')
            return 1
        known[item['path']] = item.get('sha256')

    eval_set = Path(args.eval_set)
    raw = eval_set.read_bytes()
    tasks = []
    versions = {}
    errors = []
    for line_number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            task = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f'error: line {line_number}: invalid JSON: {exc}')
            return 1
        if not isinstance(task, dict):
            print(f'error: line {line_number}: task must be a JSON object')
            return 1
        task_id = task.get('id')
        if not isinstance(task_id, str) or not task_id:
            print(f'error: line {line_number}: task id is required')
            return 1
        if task_id in versions:
            print(f'error: line {line_number}: duplicate task id {task_id!r}')
            return 1
        tasks.append(task)
        versions[task_id] = task.get('version', 1)
        materials = task.get('materials', [])
        if not isinstance(materials, list):
            errors.append(f'{task_id}: materials must be a list')
            continue
        for material in materials:
            if not isinstance(material, dict):
                errors.append(f'{task_id}: material must be an object')
                continue
            relative = material.get('path')
            expected = material.get('sha256')
            if relative not in known:
                errors.append(f'{task_id}: material not in scan: {relative}')
            elif expected != known[relative]:
                errors.append(f'{task_id}: material hash mismatch: {relative}')

    if errors:
        for error in errors:
            print(f'error: {error}')
        return 1

    manifest = {
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source_scope_digest': snapshot.get('scope_digest'),
        'source_root': snapshot.get('root'),
        'file_hashes': known,
        'task_versions': versions,
        'task_count': len(tasks),
        'eval_set_sha256': hashlib.sha256(raw).hexdigest(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"manifest: {len(tasks)} tasks, scope={str(manifest['source_scope_digest'])[:12]}")
    print(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
