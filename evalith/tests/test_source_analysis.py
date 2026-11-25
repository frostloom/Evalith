import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_SET = ROOT / 'examples/aigateway/evalscope/eval_set.v1.jsonl'
ANALYSIS = ROOT / 'examples/aigateway/evalscope/source_analysis.json'


def test_source_analysis_has_citations():
    data = json.loads(ANALYSIS.read_text(encoding='utf-8'))
    assert 'get_balance' in data['tools']
    assert 'refund_recharge' in data['tools']
    assert any(ref['path'] == 'internal/agent/tools.go' for ref in data['code_refs'])
    assert any('customer-service-evaluation-contract' in ref['path'] for ref in data['doc_refs'])
    assert data['scope']['read_only'] is True


def test_curated_eval_set_has_reference_and_sources():
    rows = [json.loads(line) for line in EVAL_SET.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(rows) >= 10
    for row in rows:
        assert row['reference_answer']
        assert row['expected_facts']
        assert row['source_refs']
        analysis = row['metadata']['source_analysis']
        assert analysis['code_refs']
        assert analysis['doc_refs']
        assert analysis['facts']
