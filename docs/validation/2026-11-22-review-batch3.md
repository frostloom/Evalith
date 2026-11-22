# 2026-11-22 · 审查修复批次 3：可靠性（D1/D2/D6/D8/R3/R4）

对应 [2026-11-21 全面代码审查](2026-11-21-全面代码审查.md) §12 第二批（可靠性）。分支 `agent/review-batch3-d1`（D1）+ `agent/review-batch3`（其余），逐项 RED→GREEN。

## D1【高】模型调用韧性 —— 三部分全部落地

1. **有界重试**（`model_gateway._request_chat`）：幂等聊天请求对连接错误/429/5xx 指数退避重试（上限 3 次、单次退避 ≤4s），重试间检查取消（`cancel_check` 由此获得真实读取点，D5 一并消除）；4xx 不重试；取消即时中止。
2. **失败退还预算**（`reserve_call`）：`max_model_calls` 上限只计入**非失败**调用；失败尝试保留在 calls 台账供审计。
3. **补判分**（`runner.rejudge` + `POST /runs/{id}/re-judge`）：对已完成 run 的 `review_required` 结果按**冻结的 observation** 重新判分（目标永不重跑，已花执行成本可回收）；逐结果独立尝试，仍失败者保持可补状态；`reserve_call(allow_ended=True)` 允许在 completed run 上记账。
- 测试：`test_model_resilience.py` 11 项（重试四情形+取消、退还、re-judge 四情形）。教训记录：monkeypatch 到类上的函数会先吃 `self`。

## D2【高】Grader 版本谱系 —— 与题目对称

- `evaluation_store`：新增 `evaluation_grader_versions` 表（`CREATE TABLE IF NOT EXISTS`，旧库自动迁移）+ `save_grader_versioned`（记录与版本行同事务）/`grader_version`/`grader_versions`。
- `save_grader` 编辑路径改走版本化写入：每次编辑落一行**不可变全文版本**；"校准用的 v3 判定标准是什么"从此可审计。
- 附带 D18：`GET /graders/{gid}` 改为只读路径（归档后仍可看）；列表支持 `?include_archived=1`；编辑/归档仍拒绝非 active。
- 测试：`test_grader_lineage.py` 4 项（版本行不可变、内容在后续编辑后可取、归档可读、归档列表）。

## D6【中】生成持久化原子化

- `assets.generate` 的 generation 记录 + 全部题目改走 `create_bundle` 单事务（复用 preparation 的原语）：中途失败不再留下"completed 的残缺 generation"。
- 测试：`test_reliability_fixes.py`（注入 create_bundle 失败 → 零残留；成功 → 每题挂 generation_id 且版本 1）。

## D8【中】编辑 Grader 不再静默清除判分模型

- `save_grader` 的字段保留白名单加入 `model_config_id`（与 task_kinds 同策略）：payload 未提及时保留绑定；显式 `null` 才清除。
- 测试：保留/显式清除两情形。

## R3【中】后台线程顶层兜底

- `_run` 拆为守卫壳 + `_run_tasks`：任务级处理器之下的任何异常（尾部落盘、终态写入）都以 `finalize_run(failed, "内部错误：…")` 收口，不再静默死亡把 run 永久留在 running（存储本身损坏时守卫也无法落盘——如实记录为剩余限制）。
- 测试：尾部 `_save_result` 注入失败 → run 终态 failed 且错误含"内部错误"。

## R4【中】终态写入 CAS 化

- `finalize_run`：终态只在非终态上写入（重启恢复的 `interrupted` 不会被另一实例"复活"为 completed）；`cancelling` 状态下任何非 cancelled 终态一律让位给 `cancelled`（用户取消永远赢）。
- 测试：completed/cancelled/interrupted/failed 四种竞态情形。

## 回归

- 后端全量：**350 passed**（327 存量 + 23 新增；一次已知 flaky 复跑通过）。前端 58 passed（未触碰，确认无波及）。`ruff check src/evalith` 通过。
