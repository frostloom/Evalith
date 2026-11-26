# ai-gateway 客服 50 题评测集

由 `evalscope-evalgen` Skill 生成，面向 ai-gateway 客服的余额、用量、账单、套餐、订阅、退款、确认/取消和越权场景。

## 规模

- 50 题：easy 20 / medium 20 / hard 10
- 预期失败/对抗题：10 题（20%）
- 每题包含 `reference_answer`、`expected_facts`、`forbidden_facts`、标准 rubric、SQLite 终态检查、`source_refs` 和 `metadata.source_analysis`

## 文件

| 文件 | 用途 |
|---|---|
| `scan.json` | Skill 只读扫描快照（7 个 Go 源文件 + 3 份客服文档） |
| `eval_plan.json` | 已批准的 50 题计划（4:4:2，10 道预期失败） |
| `eval_set.v1.jsonl` | 50 题任务集 |
| `manifest.json` | 来源摘要、文件哈希、任务版本 |
| `build_eval_set.py` | 可重复生成 JSONL 的构建脚本 |

## 校验结果

```text
validate_eval_set.py --strict: OK: 50 task(s), 0 warning(s)
check_evalscope.py:           OK: EvalScope project_eval loaded 50 task(s)
```

EvalScope 加载时需要区分两个目录：

- `--project-root /Users/bytedance/项目/Evalith/.evalith/aigateway`：运行时状态目录，`agent.db` 在这里，SQLite 检查相对此目录。
- `--source-root /Users/bytedance/项目/ai-gateway`：源码目录，用于校验 `materials`/来源文件。

```bash
export EVAL_AGENT_URL=http://127.0.0.1:9201
python scripts/check_evalscope.py \
  --eval-set examples/aigateway/evalscope/evalgen-50/eval_set.v1.jsonl \
  --project-root /Users/bytedance/项目/Evalith/.evalith/aigateway \
  --source-root /Users/bytedance/项目/ai-gateway
```

## 运行

在 EvalScope 服务（9000）的 **Eval Sets** 中导入 `eval_set.v1.jsonl`，或使用 `project_eval` benchmark：

```python
from evalscope import TaskConfig, run_task

run_task(TaskConfig(
    model='deepseek-chat',                 # 评测/裁判模型
    eval_type='openai_api',
    api_url='https://api.deepseek.com/v1',
    api_key='<key>',
    datasets=['project_eval'],
    dataset_args={'project_eval': {
        'local_path': '/Users/bytedance/项目/Evalith/examples/aigateway/evalscope/evalgen-50/eval_set.v1.jsonl',
        'project_root': '/Users/bytedance/项目/Evalith/.evalith/aigateway',
    }},
))
```

`project_eval` 使用 `JUDGE_ONLY` 评分；请配置真实裁判模型（此前 demo 使用 `deepseek-flash`）。

## 注意

- 当前 demo wrapper 的 `mock_llm.py` 只识别原有 10 题的话术；直接用它跑 50 题会有大量任务停在“请说明业务”。wrapper 的 Handler 已支持这些工具，接真实模型即可覆盖完整集合。
- 10 道预期失败题包含越权、提示注入、跳过确认、重复确认、先取消后确认、负金额、复合请求等；评分仍按正确行为（rubric）判断，不因标记为预期失败而放宽。
- 来源扫描摘要：`scope_digest=5120268ba15ac1475d96d803abe968c4765f2c66712fdc15c7a4b084aca3e41c`。
