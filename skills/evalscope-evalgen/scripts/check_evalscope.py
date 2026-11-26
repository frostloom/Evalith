#!/usr/bin/env python3
"""Smoke-test an eval set with EvalScope's own loader and project_eval adapter.

This does not call a model or the business Agent. It verifies that EvalScope's
schema accepts the file, that the project_eval adapter can convert every task
into a Sample, and that check paths/URLs resolve against the project root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _common import assert_under_root, is_allowed_http, is_sensitive_path


def preflight_checks(
    tasks: Any,
    project_root: str | Path,
    source_root: str | Path | None = None,
) -> list[str]:
    """Resolve check paths and URLs against the project root without running them."""
    root = Path(project_root)
    if not root.is_dir():
        raise ValueError(f'project root is not a directory: {root}')
    root = root.resolve()
    sources = Path(source_root).resolve() if source_root is not None else None
    if sources is not None and not sources.is_dir():
        raise ValueError(f'source root is not a directory: {sources}')
    warnings: list[str] = []
    for task in tasks:
        task_id = getattr(task, 'id', '?')
        for material in getattr(task, 'materials', []):
            if is_sensitive_path(material.path):
                raise ValueError(f'{task_id}: sensitive material path denied: {material.path}')
            if sources is not None:
                assert_under_root(material.path, sources)
                if not (sources / material.path).is_file():
                    raise ValueError(f'{task_id}: material not found under source_root: {material.path}')
        for check in getattr(task, 'checks', []):
            ctype = getattr(check, 'type', '')
            check_id = getattr(check, 'id', '?')
            if ctype in {'file_exists', 'file_content', 'json_path'}:
                if is_sensitive_path(check.path):
                    raise ValueError(f'{task_id}/{check_id}: sensitive path denied: {check.path}')
                assert_under_root(check.path, root)
                if ctype in {'file_content', 'json_path'} and not (root / check.path).is_file():
                    warnings.append(f'{task_id}/{check_id}: path not present yet: {check.path}')
            elif ctype == 'sqlite':
                if is_sensitive_path(check.dsn):
                    raise ValueError(f'{task_id}/{check_id}: sensitive path denied: {check.dsn}')
                assert_under_root(check.dsn, root)
                if not (root / check.dsn).is_file():
                    warnings.append(f'{task_id}/{check_id}: sqlite file not present yet: {check.dsn}')
            elif ctype in {'http', 'http_json'}:
                if not is_allowed_http(check.url):
                    raise ValueError(
                        f'{task_id}/{check_id}: URL must use '
                        'http://127.0.0.1 or http://localhost'
                    )
        exec_spec = getattr(task, 'exec', None)
        reset_url = getattr(exec_spec, 'reset_url', '') if exec_spec is not None else ''
        if reset_url and not is_allowed_http(reset_url):
            raise ValueError(
                f'{task_id}: reset_url must use http://127.0.0.1 or http://localhost'
            )
    return warnings


def _index_warning(evalscope_module: Any) -> str | None:
    index_path = Path(evalscope_module.__file__).parent / 'benchmarks' / '_index.json'
    if not index_path.is_file():
        return 'benchmarks/_index.json is missing; adapter discovery may import every adapter'
    try:
        index = json.loads(index_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return f'could not read {index_path}; adapter discovery may be slow'
    entry = index.get('project_eval') if isinstance(index, dict) else None
    if not isinstance(entry, str) or not entry.endswith('.project_eval_adapter'):
        return (
            'project_eval is missing or stale in benchmarks/_index.json; adapter discovery '
            'will import every adapter (run make docs-update-index in EvalScope)'
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--eval-set', required=True)
    parser.add_argument('--project-root', required=True,
                        help='root for check paths (runtime state directory)')
    parser.add_argument('--source-root',
                        help='root for materials/source files when it differs from --project-root')
    args = parser.parse_args()

    path = Path(args.eval_set)
    if not path.is_file():
        print(f'error: eval set not found: {path}')
        return 1
    project_root = Path(args.project_root).resolve()
    source_root = Path(args.source_root).resolve() if args.source_root else None

    try:
        import evalscope
    except ImportError as exc:
        print(f'error: EvalScope is not installed in this Python ({exc}); install the '
              'project_eval-enabled EvalScope build and re-run')
        return 2

    try:
        from evalscope.api.registry import get_benchmark
        from evalscope.config import TaskConfig
    except ImportError as exc:
        print(f'error: EvalScope at {evalscope.__file__} is missing required modules: {exc}')
        return 2

    try:
        from evalscope.project_eval.schema import load_eval_set
    except ImportError as exc:
        name = getattr(exc, 'name', '') or ''
        if name.startswith('evalscope.project_eval'):
            print(f'error: EvalScope is installed at {evalscope.__file__} but this build has no '
                  f'evalscope.project_eval ({exc}); use the feat/project-eval branch or apply '
                  'the project_eval patch, then re-run')
        else:
            print(f'error: evalscope.project_eval could not be imported due to a dependency '
                  f'error ({exc}); fix the environment and re-run')
        return 2

    try:
        tasks = load_eval_set(path)
    except Exception as exc:  # noqa: BLE001 - schema errors are the diagnostic
        print(f'error: eval set failed EvalScope schema validation: {type(exc).__name__}: {exc}')
        return 1

    try:
        warnings = preflight_checks(tasks, project_root, source_root)
    except Exception as exc:  # noqa: BLE001 - path/URL diagnostics
        print(f'error: project_root/check preflight failed: {exc}')
        return 1

    index_warning = _index_warning(evalscope)
    if index_warning:
        warnings.append(index_warning)
    for warning in warnings:
        print(f'warning: {warning}')

    config = TaskConfig(
        model='evalgen-smoke',
        eval_type='mock_llm',
        datasets=['project_eval'],
        dataset_args={'project_eval': {
            'local_path': str(path),
            'project_root': str(project_root),
        }},
        eval_batch_size=1,
    )
    try:
        adapter = get_benchmark('project_eval', config)
    except Exception as exc:  # noqa: BLE001 - registry/import diagnostics
        print(f'error: EvalScope could not resolve the project_eval adapter: '
              f'{type(exc).__name__}: {exc}')
        return 1

    try:
        dataset, _fewshot = adapter.load_from_disk()
        subsets = list(dataset.keys())
        samples = [sample for subset in subsets for sample in dataset[subset]]
        sample_ids = {sample.metadata.get('id') for sample in samples}
        expected_ids = {task.id for task in tasks}
        if len(samples) != len(tasks):
            print(f'error: adapter produced {len(samples)} samples for {len(tasks)} tasks')
            return 1
        if sample_ids != expected_ids:
            missing = sorted(expected_ids - sample_ids)
            extra = sorted(sample_ids - expected_ids)
            print(f'error: task ids mismatch; missing={missing}, extra={extra}')
            return 1
    except Exception as exc:  # noqa: BLE001 - adapter diagnostics
        print(f'error: project_eval adapter could not load the eval set: '
              f'{type(exc).__name__}: {exc}')
        return 1

    print(f'OK: EvalScope project_eval loaded {len(tasks)} task(s) in subset(s) {subsets} '
          f'from project_root={project_root}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
