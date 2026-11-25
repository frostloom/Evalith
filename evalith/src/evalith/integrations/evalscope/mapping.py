"""Map Evalith task records to the EvalScope eval-set contract."""

from __future__ import annotations

import re
from typing import Any


def _split_rubric(rubric: str) -> list[str]:
    lines = []
    for line in (rubric or '').splitlines():
        text = re.sub(r'^\s*(?:\d+[.)、]|[-*])\s*', '', line).strip()
        if text:
            lines.append(text)
    return lines or ([rubric.strip()] if rubric and rubric.strip() else ['回答满足任务目标'])


def _check_id(existing: int) -> str:
    return f'chk-{existing + 1}'


def map_task(
    record: dict[str, Any],
    *,
    project_root: str,
    executor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition = record['definition']
    kind = definition['kind']
    task_input = definition.get('input') or {}
    executor = executor or {}

    messages: list[dict[str, str]] = []
    if kind == 'conversation':
        messages = [{'role': 'user', 'content': str(turn)} for turn in task_input.get('turns', [])]

    question = messages[0]['content'] if messages else str(
        task_input.get('json', {}).get('message')
        or definition.get('objective')
        or definition.get('title', '')
    )

    rubric: list[dict[str, Any]] = []
    unsupported: list[dict[str, str]] = []

    def add_rubric(text: str, evidence: str = 'answer', must_pass: bool = False) -> None:
        rubric.append({
            'id': f'c{len(rubric) + 1}',
            'criterion': text,
            'weight': 1.0,
            'must_pass': must_pass,
            'evidence_requirement': evidence,
        })

    for line in _split_rubric(definition.get('rubric', '')):
        add_rubric(line)

    checks: list[dict[str, Any]] = []
    base_url = str(executor.get('base_url') or '').rstrip('/')
    for check in definition.get('checks', []):
        check_type = check.get('type')
        expected = check.get('expected')
        path = str(check.get('path') or '')
        description = str(check.get('description') or check_type or 'check')
        if check_type == 'file_exists':
            checks.append({'id': _check_id(len(checks)), 'type': 'file_exists', 'path': path})
            add_rubric(f'{description}: 文件 {path} 存在', 'outcome', True)
        elif check_type == 'file_contains':
            checks.append({
                'id': _check_id(len(checks)),
                'type': 'file_content',
                'path': path,
                'contains': str(expected),
            })
            add_rubric(f'{description}: {path} 包含 {expected}', 'outcome', True)
        elif check_type == 'status_code':
            request_path = str(task_input.get('path') or '')
            checks.append({
                'id': _check_id(len(checks)),
                'type': 'http',
                'method': str(task_input.get('method') or 'GET').upper(),
                'url': f'{base_url}{request_path}',
                'expect_status': int(expected),
            })
            add_rubric(f'{description}: HTTP 状态码为 {expected}', 'outcome', True)
        elif check_type in ('contains', 'not_contains'):
            verb = '包含' if check_type == 'contains' else '不包含'
            add_rubric(f'{description}: 回答{verb} {expected}', 'answer', False)
        elif check_type == 'judge':
            add_rubric(str(expected or description), 'answer', False)
        elif check_type == 'json_equals':
            unsupported.append({
                'type': check_type,
                'reason': 'EvalScope json_equals needs a file path; use a curated json_path check',
            })
        elif check_type == 'exit_code':
            unsupported.append({
                'type': check_type,
                'reason': 'Command execution is not enabled in EvalScope MVP',
            })
        else:
            unsupported.append({'type': str(check_type), 'reason': 'unsupported check type'})

    if kind == 'conversation':
        exec_spec = {
            'type': 'agent_api',
            'protocol': 'rest_steps',
            'agent_url_env': 'EVAL_AGENT_URL',
            'trace': {'mode': 'auto'},
            'session': {'id_from': 'sample_id'},
        }
    elif kind == 'http':
        exec_spec = {
            'type': 'http',
            'base_url_env': 'EVAL_AGENT_URL',
            'request': {
                'method': str(task_input.get('method') or 'POST').upper(),
                'path': str(task_input.get('path') or ''),
                'json': task_input.get('json') or {},
            },
            'trace': {'mode': 'none'},
            'session': {'id_from': 'sample_id'},
        }
    else:
        raise ValueError(f'unsupported Evalith task kind: {kind}')

    uncertainties = list(definition.get('uncertainties') or [])
    materials = [
        {'path': item.get('path', ''), 'sha256': item.get('sha256', '')}
        for item in (record.get('_snapshot_files') or [])
        if item.get('path')
    ]

    return {
        'id': record['id'],
        'version': int(record.get('version', 1)),
        'question': question,
        'system': '',
        'messages': messages,
        'rubric': rubric,
        'checks': checks,
        'exec': exec_spec,
        'source_refs': list(definition.get('source_refs') or []),
        'origin': 'inference' if uncertainties else 'fact',
        'materials': materials,
        'metadata': {
            'uncertainties': uncertainties,
            'unsupported_checks': unsupported,
            'evalith': {
                'project_id': record.get('_project_id'),
                'task_id': record['id'],
                'version_id': record.get('version_id'),
                'source_digest': record.get('source_digest'),
                'source_snapshot_id': record.get('source_snapshot_id'),
                'project_root': project_root,
            },
        },
    }
