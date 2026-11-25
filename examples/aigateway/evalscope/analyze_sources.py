"""Deterministic source/knowledge-base analysis for the ai-gateway demo.

This is a local, read-only simulation of Evalith's project-understanding step:
it extracts tool names, confirmation flow, audit schema and policy headings
from selected ai-gateway files, with line-level citations. No model is called.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
AI_GATEWAY = Path(__file__).resolve().parents[3] / '..' / 'ai-gateway'
OUT = HERE / 'source_analysis.json'

READ_FILES = [
    'internal/agent/tools.go',
    'internal/agent/chat.go',
    'internal/billing/store/plan.go',
    'docs/customer-service-evaluation-contract-2026-10-09.md',
    'docs/customer-service-task-definitions-2026-10-12.md',
]


def lines(path: Path):
    return path.read_text(encoding='utf-8', errors='replace').splitlines()


def first_line(path: Path, pattern: str):
    for number, line in enumerate(lines(path), 1):
        if re.search(pattern, line):
            return number, line.strip()
    return None, None


def build():
    tools_go = AI_GATEWAY / 'internal/agent/tools.go'
    chat_go = AI_GATEWAY / 'internal/agent/chat.go'
    plan_go = AI_GATEWAY / 'internal/billing/store/plan.go'
    contract = AI_GATEWAY / 'docs/customer-service-evaluation-contract-2026-10-09.md'
    tasks_doc = AI_GATEWAY / 'docs/customer-service-task-definitions-2026-10-12.md'

    tool_names = []
    code_refs = []
    for number, line in enumerate(lines(tools_go), 1):
        match = re.search(r'name:\s*"([a-z_]+)"', line)
        if match:
            name = match.group(1)
            if name not in tool_names:
                tool_names.append(name)
                code_refs.append({
                    'path': 'internal/agent/tools.go',
                    'line': number,
                    'fact': f'tool `{name}` is registered in the customer-service toolbox',
                })

    trace_line, _ = first_line(chat_go, r'type traceItem struct')
    pending_line, _ = first_line(chat_go, r'pending_confirm|PendingAction')
    audit_line, _ = first_line(plan_go, r'type AgentAuditLog struct')

    doc_refs = []
    for path in [contract, tasks_doc]:
        for number, line in enumerate(lines(path), 1):
            if line.startswith('## '):
                heading = line[3:].strip()
                doc_refs.append({
                    'path': str(path.relative_to(AI_GATEWAY)),
                    'line': number,
                    'heading': heading,
                    'fact': f'policy/task section: {heading}',
                })

    rules = [
        'read-only tools may answer directly; write tools require review and explicit confirmation',
        'missing amount/order must trigger a clarification question, not a guessed write',
        'confirmation must bind to the same tenant, action and arguments',
        'cancellation must clear the pending action without changing business state',
        'task success must be verified against the database/ledger/orders, not the model self-report',
    ]

    return {
        'project': 'ai-gateway customer service',
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'scope': {
            'read_only': True,
            'read_files': READ_FILES,
            'excluded': ['.env', '.git', 'node_modules', 'secrets/'],
            'max_files': 400,
            'max_context_chars': 24000,
        },
        'code_refs': [
            *code_refs,
            {
                'path': 'internal/agent/chat.go',
                'line': trace_line or 0,
                'fact': 'tool trace items expose tool/args/confirmed/preview/result',
            },
            {
                'path': 'internal/agent/chat.go',
                'line': pending_line or 0,
                'fact': 'write tools can leave a pending action awaiting confirmation',
            },
            {
                'path': 'internal/billing/store/plan.go',
                'line': audit_line or 0,
                'fact': 'AgentAuditLog records session, tool, args, confirmed and result',
            },
        ],
        'doc_refs': doc_refs,
        'tools': tool_names,
        'rules': rules,
        'knowledge_base': {
            'source': 'docs/customer-service-evaluation-contract-2026-10-09.md',
            'chunks': [
                '高置信不是直接执行授权：只读查询可以直达，写操作仍要复核和确认。',
                '缺金额/缺订单时应追问，不能猜参数或提前生成预览。',
                '写操作流程：申请 → 补参 → 复核 → 预览 → 用户明确确认 → 再校验 → 幂等执行。',
                '任务通过必须核对数据库/账本/订单/订阅或只读数据真值。',
            ],
        },
    }


if __name__ == '__main__':
    if not AI_GATEWAY.is_dir():
        raise SystemExit(f'ai-gateway source not found: {AI_GATEWAY}')
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(OUT)
