#!/usr/bin/env python3
"""Validate an EvalScope eval_set.v1.jsonl for the EvalGen skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from _common import is_allowed_http, is_relative_path, is_sensitive_path

CHECK_TYPES = {'file_exists', 'file_content', 'http', 'http_json', 'sqlite', 'json_path'}
EVIDENCE = {'answer', 'outcome', 'process'}
EXEC_TYPES = {'agent_api', 'http'}
PROTOCOLS = {'rest_steps', 'otel', 'openai_compat'}
DIFFICULTIES = {'easy', 'medium', 'hard'}
ORIGINS = {'fact', 'inference'}
TRACE_MODES = {'auto', 'inline', 'fetch', 'none'}
METHODS = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH'}
TASK_FIELDS = {
    'id', 'version', 'question', 'system', 'messages', 'reference_answer',
    'expected_facts', 'forbidden_facts', 'rubric', 'checks', 'exec',
    'pass_threshold', 'source_refs', 'origin', 'materials', 'metadata',
}
RUBRIC_FIELDS = {'id', 'criterion', 'weight', 'must_pass', 'evidence_requirement'}
CHECK_FIELDS = {
    'id', 'type', 'path', 'contains', 'method', 'url', 'expect_status',
    'dsn', 'query', 'json_path', 'expect',
}
EXEC_FIELDS = {
    'type', 'protocol', 'agent_url_env', 'base_url_env', 'reset_url',
    'request', 'trace', 'session',
}
TRACE_FIELDS = {'mode', 'endpoint', 'header'}
MATERIAL_FIELDS = {'path', 'sha256'}


def _unknown_fields(item: dict, allowed: set[str], where: str, errors: list[str]) -> None:
    extra = sorted(set(item) - allowed)
    if extra:
        errors.append(f'{where}: unknown field(s): {", ".join(extra)}')


def _sha256(path: Path, limit: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    remaining = limit
    with path.open('rb') as handle:
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _known_ref(path: str, known: dict[str, dict]) -> dict | None:
    return known.get(path)


def _require_excerpt(item: dict, path: str, where: str, errors: list[str]) -> bool:
    if item.get('sent') is False:
        errors.append(f'{where}: source reference cites a file without an excerpt: {path}')
        return False
    return True


def _check_ref(ref: str, known: dict[str, dict], where: str, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(ref, str) or not ref.strip():
        errors.append(f'{where}: empty source reference')
        return
    if '#' in ref:
        path, heading = ref.split('#', 1)
        item = _known_ref(path, known)
        if item is None:
            errors.append(f'{where}: source file not in scan: {path}')
        elif not _require_excerpt(item, path, where, errors):
            return
        elif heading not in (item.get('headings') or []):
            errors.append(f'{where}: heading not in scan: {ref}')
        return
    if ':' in ref:
        path, line = ref.rsplit(':', 1)
        item = _known_ref(path, known)
        if item is None:
            errors.append(f'{where}: source file not in scan: {path}')
            return
        if not _require_excerpt(item, path, where, errors):
            return
        try:
            line_number = int(line)
        except ValueError:
            errors.append(f'{where}: invalid line reference: {ref}')
            return
        line_count = item.get('line_count') or 0
        if line_count and not 1 <= line_number <= line_count:
            errors.append(f'{where}: line out of range: {ref}')
        elif not line_count:
            warnings.append(f'{where}: line reference to a file without scanned text: {ref}')
        return
    item = _known_ref(ref, known)
    if item is None:
        errors.append(f'{where}: source file not in scan: {ref}')
    else:
        _require_excerpt(item, ref, where, errors)


def validate_task(task: Any, index: int, errors: list[str], warnings: list[str]) -> None:
    where = f'line {index}'
    if not isinstance(task, dict):
        errors.append(f'{where}: task must be a JSON object')
        return
    _unknown_fields(task, TASK_FIELDS, where, errors)
    task_id = task.get('id')
    if not isinstance(task_id, str) or not task_id.strip():
        errors.append(f'{where}: id is required')
    version = task.get('version', 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        errors.append(f'{where}: version must be an integer >= 1')
    question = task.get('question')
    if not isinstance(question, str) or not question.strip():
        errors.append(f'{where}: question is required')
    system = task.get('system', '')
    if not isinstance(system, str):
        errors.append(f'{where}: system must be a string')
    messages = task.get('messages', [])
    if not isinstance(messages, list) or any(not isinstance(message, dict) for message in messages):
        errors.append(f'{where}: messages must be a list of objects')
    reference_answer = task.get('reference_answer')
    if not isinstance(reference_answer, str) or not reference_answer.strip():
        errors.append(f'{where}: reference_answer is required')
    expected_facts = task.get('expected_facts')
    if (
        not isinstance(expected_facts, list)
        or not expected_facts
        or any(not isinstance(fact, str) or not fact.strip() for fact in expected_facts)
    ):
        errors.append(f'{where}: expected_facts must be a non-empty list of strings')
    forbidden_facts = task.get('forbidden_facts', [])
    if not isinstance(forbidden_facts, list) or any(
        not isinstance(fact, str) or not fact.strip() for fact in forbidden_facts
    ):
        errors.append(f'{where}: forbidden_facts must be a list of strings')
    origin = task.get('origin', 'fact')
    if not isinstance(origin, str) or origin not in ORIGINS:
        errors.append(f'{where}: origin must be fact or inference')
    threshold = task.get('pass_threshold', 0.6)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        errors.append(f'{where}: pass_threshold must be between 0 and 1')

    metadata = task.get('metadata', {})
    if not isinstance(metadata, dict):
        errors.append(f'{where}: metadata must be an object')
        metadata = {}
    expect_failure = metadata.get('expect_failure')
    if expect_failure is not None and not isinstance(expect_failure, bool):
        errors.append(f'{where}: metadata.expect_failure must be boolean')
    if expect_failure is True and not task.get('forbidden_facts'):
        errors.append(f'{where}: expected-failure task requires forbidden_facts')
    difficulty = metadata.get('difficulty')
    if 'difficulty' in metadata and (not isinstance(difficulty, str) or difficulty not in DIFFICULTIES):
        errors.append(f'{where}: metadata.difficulty must be easy/medium/hard')
    if 'plan_id' in metadata and not isinstance(metadata.get('plan_id'), str):
        errors.append(f'{where}: metadata.plan_id must be a string')
    analysis = metadata.get('source_analysis')
    if not isinstance(analysis, dict):
        errors.append(f'{where}: metadata.source_analysis is required')
    else:
        code_refs = analysis.get('code_refs', [])
        doc_refs = analysis.get('doc_refs', [])
        if not isinstance(code_refs, list) or not isinstance(doc_refs, list):
            errors.append(f'{where}: source_analysis code_refs/doc_refs must be lists')
        elif not code_refs and not doc_refs:
            errors.append(f'{where}: source_analysis requires code_refs or doc_refs')
        facts = analysis.get('facts')
        if (
            not isinstance(facts, list)
            or not facts
            or any(not isinstance(fact, str) or not fact.strip() for fact in facts)
        ):
            errors.append(f'{where}: source_analysis.facts must be a non-empty list of strings')

    rubric = task.get('rubric')
    if not isinstance(rubric, list) or not rubric:
        errors.append(f'{where}: rubric must be a non-empty list')
    else:
        rubric_ids = set()
        total_weight = 0.0
        for criterion in rubric:
            if not isinstance(criterion, dict):
                errors.append(f'{where}: rubric entry must be an object')
                continue
            _unknown_fields(criterion, RUBRIC_FIELDS, f'{where} rubric', errors)
            cid = criterion.get('id')
            if not isinstance(cid, str) or not cid or cid in rubric_ids:
                errors.append(f'{where}: rubric id missing or duplicated: {cid!r}')
            else:
                rubric_ids.add(cid)
            if not isinstance(criterion.get('criterion'), str) or not criterion.get('criterion', '').strip():
                errors.append(f'{where}: rubric {cid} has no criterion')
            evidence = criterion.get('evidence_requirement', 'answer')
            if not isinstance(evidence, str) or evidence not in EVIDENCE:
                errors.append(f'{where}: rubric {cid} has invalid evidence_requirement')
            weight = criterion.get('weight', 1)
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
                errors.append(f'{where}: rubric {cid} has invalid weight')
            else:
                total_weight += weight
            if not isinstance(criterion.get('must_pass', False), bool):
                errors.append(f'{where}: rubric {cid} must_pass must be boolean')
        if total_weight <= 0:
            errors.append(f'{where}: rubric total weight must be > 0')
        outcome_must_pass = [
            criterion for criterion in rubric
            if criterion.get('evidence_requirement', 'answer') == 'outcome'
            and criterion.get('must_pass') is True
        ]
        if not outcome_must_pass:
            errors.append(f'{where}: rubric requires at least one must_pass outcome criterion')
        if not any(criterion.get('evidence_requirement', 'answer') == 'answer' for criterion in rubric):
            errors.append(f'{where}: rubric requires at least one answer criterion')

    checks = task.get('checks')
    if not isinstance(checks, list):
        errors.append(f'{where}: checks must be a list')
        checks = []
    check_ids = set()
    outcome_checks = 0
    for check in checks:
        if not isinstance(check, dict):
            errors.append(f'{where}: check entry must be an object')
            continue
        _unknown_fields(check, CHECK_FIELDS, f'{where} check', errors)
        cid = check.get('id')
        if not isinstance(cid, str) or not cid or cid in check_ids:
            errors.append(f'{where}: check id missing or duplicated: {cid!r}')
        else:
            check_ids.add(cid)
        ctype = check.get('type')
        if not isinstance(ctype, str) or ctype not in CHECK_TYPES:
            errors.append(f'{where}: check {cid} has unsupported type {ctype!r}')
            continue
        if ctype in {'file_exists', 'file_content', 'json_path'}:
            path = check.get('path')
            if not is_relative_path(path):
                errors.append(f'{where}: check {cid} path must be relative to project root')
            elif is_sensitive_path(path):
                errors.append(f'{where}: check {cid} path is sensitive and will be denied')
        if ctype == 'file_content' and not isinstance(check.get('contains'), str):
            errors.append(f'{where}: check {cid} requires contains')
        if ctype == 'json_path':
            if not check.get('json_path'):
                errors.append(f'{where}: check {cid} requires json_path')
            if 'expect' not in check:
                errors.append(f'{where}: check {cid} requires expect')
        if ctype == 'sqlite':
            dsn = check.get('dsn')
            if not is_relative_path(dsn):
                errors.append(f'{where}: check {cid} dsn must be relative to project root')
            elif is_sensitive_path(dsn):
                errors.append(f'{where}: check {cid} dsn is sensitive and will be denied')
            if not check.get('query'):
                errors.append(f'{where}: check {cid} requires query')
            if 'expect' not in check:
                errors.append(f'{where}: check {cid} requires expect')
        if ctype in {'http', 'http_json'}:
            url = check.get('url')
            if not isinstance(url, str) or not url:
                errors.append(f'{where}: check {cid} requires url')
            elif not is_allowed_http(url):
                errors.append(
                    f'{where}: check {cid} URL must use http://127.0.0.1 or http://localhost'
                )
            method = check.get('method')
            if 'method' in check and (not isinstance(method, str) or method not in METHODS):
                errors.append(f'{where}: check {cid} has invalid method')
            if ctype == 'http_json' and method not in (None, 'GET'):
                errors.append(f'{where}: check {cid} http_json only supports GET')
            if 'expect_status' in check and (
                isinstance(check.get('expect_status'), bool)
                or not isinstance(check.get('expect_status'), int)
            ):
                errors.append(f'{where}: check {cid} expect_status must be an integer')
            if ctype == 'http_json':
                if not check.get('json_path'):
                    errors.append(f'{where}: check {cid} requires json_path')
                if 'expect' not in check:
                    errors.append(f'{where}: check {cid} requires expect')
        outcome_checks += 1
    if not outcome_checks:
        errors.append(f'{where}: at least one final-state check is required')

    exec_spec = task.get('exec')
    if not isinstance(exec_spec, dict):
        errors.append(f'{where}: exec must be an object')
    else:
        _unknown_fields(exec_spec, EXEC_FIELDS, f'{where} exec', errors)
        exec_type = exec_spec.get('type', 'agent_api')
        if not isinstance(exec_type, str) or exec_type not in EXEC_TYPES:
            errors.append(f'{where}: exec.type must be agent_api or http')
        protocol = exec_spec.get('protocol', 'rest_steps')
        if not isinstance(protocol, str) or protocol not in PROTOCOLS:
            errors.append(f'{where}: exec.protocol is invalid')
        for key in ('agent_url_env', 'base_url_env'):
            if key in exec_spec and (not isinstance(exec_spec.get(key), str) or not exec_spec.get(key)):
                errors.append(f'{where}: exec.{key} must be a non-empty string')
        request = exec_spec.get('request', {})
        if not isinstance(request, dict):
            errors.append(f'{where}: exec.request must be an object')
        elif exec_type == 'http' and not request.get('path'):
            errors.append(f'{where}: http exec requires request.path')
        reset_url = exec_spec.get('reset_url', '')
        if reset_url and (not isinstance(reset_url, str) or not is_allowed_http(reset_url)):
            errors.append(f'{where}: reset_url must use http://127.0.0.1 or http://localhost')
        trace = exec_spec.get('trace', {})
        if not isinstance(trace, dict):
            errors.append(f'{where}: exec.trace must be an object')
        else:
            _unknown_fields(trace, TRACE_FIELDS, f'{where} trace', errors)
            mode = trace.get('mode', 'auto')
            if not isinstance(mode, str) or mode not in TRACE_MODES:
                errors.append(f'{where}: exec.trace.mode must be auto/inline/fetch/none')
            for key in ('endpoint', 'header'):
                if key in trace and not isinstance(trace.get(key), str):
                    errors.append(f'{where}: exec.trace.{key} must be a string')
        session = exec_spec.get('session', {})
        if not isinstance(session, dict):
            errors.append(f'{where}: exec.session must be an object')
        elif session.get('id_from', 'sample_id') != 'sample_id':
            errors.append(f'{where}: exec.session.id_from must be sample_id')

    if 'source_refs' not in task:
        warnings.append(f'{where}: source_refs is empty')
    else:
        source_refs = task.get('source_refs')
        if not isinstance(source_refs, list) or any(not isinstance(ref, str) for ref in source_refs):
            errors.append(f'{where}: source_refs must be a list of strings')
        elif not source_refs:
            warnings.append(f'{where}: source_refs is empty')
    materials = task.get('materials', [])
    if not isinstance(materials, list):
        errors.append(f'{where}: materials must be a list')
    else:
        for material in materials:
            if not isinstance(material, dict):
                errors.append(f'{where}: material must be an object')
                continue
            _unknown_fields(material, MATERIAL_FIELDS, f'{where} material', errors)
            if not is_relative_path(material.get('path')):
                errors.append(f'{where}: material path must be relative to project root')
            elif is_sensitive_path(material.get('path')):
                errors.append(f'{where}: material path is sensitive')
            sha256 = material.get('sha256')
            if not isinstance(sha256, str) or len(sha256) != 64 or any(c not in '0123456789abcdef' for c in sha256):
                errors.append(f'{where}: material requires a 64-char hex sha256')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--eval-set', required=True)
    parser.add_argument('--scan')
    parser.add_argument('--plan')
    parser.add_argument('--root')
    parser.add_argument('--no-verify-source', action='store_true')
    parser.add_argument('--strict', action='store_true', help='treat warnings as errors')
    args = parser.parse_args()

    path = Path(args.eval_set)
    if not path.is_file():
        print(f'error: eval set not found: {path}')
        return 2

    tasks = []
    errors: list[str] = []
    warnings: list[str] = []
    seen = set()
    for index, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            task = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f'line {index}: invalid JSON: {exc}')
            continue
        validate_task(task, index, errors, warnings)
        if not isinstance(task, dict):
            continue
        tid = task.get('id')
        if isinstance(tid, str):
            if tid in seen:
                errors.append(f'line {index}: duplicate task id {tid!r}')
            seen.add(tid)
        tasks.append(task)

    if not tasks:
        errors.append('eval set is empty')

    if args.scan:
        scan_path = Path(args.scan)
        if not scan_path.is_file():
            print(f'error: scan file not found: {scan_path}')
            return 2
        snapshot = json.loads(scan_path.read_text(encoding='utf-8'))
        if not isinstance(snapshot, dict):
            errors.append('scan must be a JSON object')
            snapshot = {}
        raw_files = snapshot.get('files', [])
        if not isinstance(raw_files, list):
            errors.append('scan.files must be a list')
            raw_files = []
        known: dict[str, dict] = {}
        for item in raw_files:
            if not isinstance(item, dict):
                errors.append('scan.files entries must be objects')
                continue
            relative = item.get('path')
            if not is_relative_path(relative):
                errors.append(f'scan entry must stay under root: {relative!r}')
                continue
            known[relative] = item
        if not args.no_verify_source:
            root = Path(args.root or snapshot.get('root') or '.').resolve()
            for relative, item in known.items():
                source = root / relative
                if source.is_symlink():
                    errors.append(f'source must not be a symlink: {relative}')
                    continue
                try:
                    resolved = source.resolve()
                    if os.path.commonpath([str(root), str(resolved)]) != str(root):
                        errors.append(f'source escapes root: {relative}')
                        continue
                except (OSError, ValueError) as exc:
                    errors.append(f'cannot resolve source {relative}: {exc}')
                    continue
                if not source.is_file():
                    errors.append(f'source file missing: {relative}')
                    continue
                if item.get('hash_truncated'):
                    warnings.append(f'source hash was truncated; not re-verified: {relative}')
                    continue
                try:
                    current = _sha256(source)
                except OSError as exc:
                    errors.append(f'cannot read source {relative}: {exc}')
                    continue
                if current != item.get('sha256'):
                    errors.append(f'source changed since scan: {relative}')
        for index, task in enumerate(tasks, 1):
            materials = task.get('materials', [])
            if not isinstance(materials, list):
                materials = []
            for material in materials:
                if not isinstance(material, dict):
                    continue
                relative = material.get('path')
                expected = material.get('sha256')
                if relative not in known:
                    errors.append(f'task {task.get("id")}: material not in scan: {relative}')
                elif expected != known[relative].get('sha256'):
                    errors.append(f'task {task.get("id")}: material hash mismatch: {relative}')
            source_refs = task.get('source_refs', [])
            if not isinstance(source_refs, list):
                source_refs = []
            for ref in source_refs:
                _check_ref(ref, known, f'task {task.get("id")}', errors, warnings)
            metadata = task.get('metadata')
            analysis = metadata.get('source_analysis') if isinstance(metadata, dict) else {}
            if not isinstance(analysis, dict):
                analysis = {}
            code_refs = analysis.get('code_refs', [])
            doc_refs = analysis.get('doc_refs', [])
            if not isinstance(code_refs, list):
                errors.append(f'task {task.get("id")}: source_analysis.code_refs must be a list')
                code_refs = []
            if not isinstance(doc_refs, list):
                errors.append(f'task {task.get("id")}: source_analysis.doc_refs must be a list')
                doc_refs = []
            task_where = f'task {task.get("id")}'
            for ref in code_refs:
                if isinstance(ref, dict):
                    code_ref = f"{ref.get('path')}:{ref.get('line')}"
                    _check_ref(code_ref, known, task_where, errors, warnings)
            for ref in doc_refs:
                if isinstance(ref, dict):
                    doc_ref = f"{ref.get('path')}#{ref.get('heading')}"
                    _check_ref(doc_ref, known, task_where, errors, warnings)
        if not snapshot.get('scope_digest'):
            warnings.append('scan has no scope_digest')

    if args.plan:
        plan_path = Path(args.plan)
        if not plan_path.is_file():
            print(f'error: plan file not found: {plan_path}')
            return 2
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        if not isinstance(plan, dict):
            errors.append('plan must be a JSON object')
            plan = {}
        if plan.get('approved_by_user') is not True:
            errors.append('plan is not approved by the user (approved_by_user=false)')
        if not isinstance(plan.get('plan_id'), str) or not plan.get('plan_id'):
            errors.append('plan must define plan_id')
        difficulty_counts = plan.get('difficulty_counts')
        if not isinstance(difficulty_counts, dict) or set(difficulty_counts) != DIFFICULTIES:
            errors.append('plan must define difficulty_counts for easy/medium/hard')
            difficulty_counts = {name: 0 for name in DIFFICULTIES}
        elif any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in difficulty_counts.values()
        ):
            errors.append('plan difficulty_counts must be non-negative integers')
        failure_count = plan.get('failure_count')
        if (
            isinstance(failure_count, bool)
            or not isinstance(failure_count, int)
            or failure_count < 0
        ):
            errors.append('plan must define a non-negative failure_count')
            failure_count = 0
        count = plan.get('count')
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            errors.append('plan must define a positive integer count')
        elif sum(difficulty_counts.values()) != count:
            errors.append('plan difficulty_counts must sum to count')
        if len(tasks) != count:
            errors.append(f'plan expects {count} task(s), got {len(tasks)}')
        actual_difficulty: dict[str, int] = {name: 0 for name in DIFFICULTIES}
        actual_failure = 0
        for task in tasks:
            metadata = task.get('metadata')
            if not isinstance(metadata, dict):
                metadata = {}
            if metadata.get('plan_id') != plan.get('plan_id'):
                errors.append(f'task {task.get("id")}: metadata.plan_id does not match plan')
            difficulty = metadata.get('difficulty')
            if not isinstance(difficulty, str) or difficulty not in DIFFICULTIES:
                errors.append(f'task {task.get("id")}: metadata.difficulty must be easy/medium/hard')
            else:
                actual_difficulty[difficulty] += 1
            if metadata.get('expect_failure') is True:
                actual_failure += 1
        for name in DIFFICULTIES:
            expected = difficulty_counts.get(name, 0)
            if actual_difficulty[name] != expected:
                errors.append(
                    f'plan difficulty {name}: expected {expected} task(s), got {actual_difficulty[name]}'
                )
        if actual_failure != failure_count:
            errors.append(f'plan failure_count: expected {failure_count}, got {actual_failure}')

    for warning in warnings:
        print(f'warning: {warning}')
    for error in errors:
        print(f'error: {error}')
    if errors or (args.strict and warnings):
        print(f'FAILED: {len(errors)} error(s), {len(warnings)} warning(s) in {len(tasks)} task(s)')
        return 1
    print(f'OK: {len(tasks)} task(s), {len(warnings)} warning(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
