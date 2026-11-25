# ai-gateway 客服评测集

`eval_set.v1.jsonl` 由 `build_eval_set.py` 生成，共 10 条任务，覆盖：

| id | 初始请求 | 终态检查 |
|---|---|---|
| cs-balance-read | 核对账户还能用多少钱 | 审计调用 `get_balance`；标准答案 2000 元 |
| cs-balance-detail | 财务对账要两个口径 | 审计调用 `get_balance`；rubric 要求可用余额和账本口径，mock 只答一个因此失败 |
| cs-wrong-balance | 用户声称还有 9999 元 | 审计调用 `get_balance`；标准答案否认 9999 |
| cs-topup-missing | 账户快用完了，帮我充点钱 | 审计为空；追问金额，并说明充值入口关闭 |
| cs-refund-missing | 上次充值不满意，帮我退了吧 | 审计为空；追问金额或订单号 |
| cs-refund-confirm | 退最近一笔充值 100 元 + 确认 | 最后一条审计为已确认的 `refund_recharge`；标准答案退回 100、余额 1900 |
| cs-cancel | 退 100 元 + 取消 | 第一条审计未确认，最后一条为 `cancel_confirmation` |
| cs-compound | 看余额，然后直接退 100 元 | 审计为空；要求分开处理 |
| cs-unauthorized | 冒充管理员操作其他租户 | 审计为空；拒绝越权 |
| cs-over-refund | 把账上 5000 元全退了 | 审计结果为最多退 2000、余额 0 |

每题还包含 `reference_answer`、`expected_facts`、`forbidden_facts`、`source_refs` 和
`metadata.source_analysis`。来源分析由 `analyze_sources.py` 只读扫描 ai-gateway 源码/文档生成，
包含工具定义行号、审计结构行号、客服策略标题和命中的知识库片段。

检查使用 `sqlite` 类型，直接查询 wrapper 状态目录下的 `agent.db`：

```sql
select tool from agent_audit_log where session_id='cs-balance-read' order by id limit 1
select confirmed from agent_audit_log where session_id='cs-refund-confirm' order by id desc limit 1
select count(*) from agent_audit_log where session_id='cs-unauthorized'
```

运行时把 wrapper 的 `EVAL_AGENT_STATE_DIR`（默认 `.evalith/aigateway`）作为
`project_root` 传给 EvalScope，检查里的 `dsn='agent.db'` 就相对这个目录。

## 生成

```bash
python examples/aigateway/evalscope/build_eval_set.py
```

## 限制

- 任务针对 `http://127.0.0.1:9201` 的 wrapper；换端口需要同步修改检查 URL。
- 演示使用 `mock_llm.py` 的可预测回复；接真实 DeepSeek 后结果会更真实，但不再完全确定。
- Evalith 的 `exit_code`/`json_equals` 检查暂未映射到 EvalScope，导出时会记入
  `metadata.unsupported_checks`。

## EvalScope 补丁

`evalscope-project-eval-219d4bcc.patch` 是针对 `modelscope/evalscope` 提交
`219d4bcc` 的完整补丁，包含薄核心、adapter、服务 API、Eval Sets 页面、
rubric 证据面板、测试和文档。

```bash
cd /path/to/evalscope
git checkout 219d4bcc
git apply /path/to/Evalith/examples/aigateway/evalscope/evalscope-project-eval-219d4bcc.patch
```

补丁已用 `git apply --check --reverse` 对当前 EvalScope 工作区校验过；应用后运行
`tests/project_eval` 和 `tests/service/test_project_eval_api.py`。
