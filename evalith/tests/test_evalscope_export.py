import json

from evalith.integrations.evalscope.exporter import export_eval_set
from evalith.integrations.evalscope.mapping import map_task


def record(kind='conversation'):
    definition = {
        'title': '查余额',
        'category': '查询',
        'objective': '返回真实余额',
        'kind': kind,
        'input': {'turns': ['查一下余额', '谢谢']} if kind == 'conversation' else {
            'path': '/chat',
            'method': 'POST',
            'json': {'message': '查余额'},
        },
        'checks': [
            {'type': 'file_contains', 'path': 'state.json', 'expected': '200000', 'description': '余额'},
            {'type': 'status_code', 'expected': 200, 'description': 'HTTP'},
            {'type': 'judge', 'expected': '回答引用真实余额', 'description': '回答'},
            {'type': 'exit_code', 'expected': 0, 'description': '退出码'},
        ],
        'rubric': '1. 余额与工具结果一致\n2. 不编造',
        'source_refs': ['internal/agent/chat.go:123'],
        'uncertainties': ['余额单位未确认'],
    }
    return {
        'id': 'task-1',
        'version': 2,
        'version_id': 'ver-2',
        'source_digest': 'abc',
        'source_snapshot_id': 'snap-1',
        'definition': definition,
        '_project_id': 'proj-1',
    }


def test_maps_conversation_task():
    out = map_task(record(), project_root='/repo', executor={'base_url': 'http://127.0.0.1:9105'})
    assert out['id'] == 'task-1'
    assert out['version'] == 2
    assert len(out['messages']) == 2
    assert out['exec']['type'] == 'agent_api'
    assert out['exec']['agent_url_env'] == 'EVAL_AGENT_URL'
    assert any(check['type'] == 'file_content' for check in out['checks'])
    assert any(check['type'] == 'http' for check in out['checks'])
    assert len(out['rubric']) >= 2
    assert out['origin'] == 'inference'
    assert out['metadata']['evalith']['version_id'] == 'ver-2'
    assert out['metadata']['unsupported_checks']


def test_http_task_maps_to_http_exec():
    out = map_task(record('http'), project_root='/repo', executor={'base_url': 'http://127.0.0.1:9105'})
    assert out['exec']['type'] == 'http'
    assert out['exec']['request'] == {'method': 'POST', 'path': '/chat', 'json': {'message': '查余额'}}
    assert out['question'] == '查余额'


def test_export_writes_jsonl(tmp_path):
    out_path = tmp_path / 'eval_set.v1.jsonl'
    export_eval_set(
        [record()],
        snapshot={'root': '/repo', 'files': [{'path': 'internal/agent/chat.go', 'sha256': 'abc'}]},
        executor={'base_url': 'http://127.0.0.1:9105'},
        out_path=out_path,
    )
    rows = [json.loads(line) for line in out_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]['materials'] == [{'path': 'internal/agent/chat.go', 'sha256': 'abc'}]
