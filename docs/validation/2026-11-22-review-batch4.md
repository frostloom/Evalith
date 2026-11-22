# 2026-11-22 · 审查修复批次 4：可扩展性与体验（R2 轻量线 + D7 + F1/F2/F3/F4/F13）

对应 [2026-11-21 全面代码审查](2026-11-21-全面代码审查.md) §12 第三批。分支 `agent/review-batch4`。

## R2+F1 同根治理（取报告给出的轻量路线）

报告修复方向为"observation 拆行存储（**或至少** cancel 检查走轻量状态列）+ 列表瘦身 + 按需轮询"。本批落地轻量三件，行存储重构留待有真实规模压力时再做：

1. **取消检查轻量化**（`store.status_of`）：`cancelled()` 从"每 50ms 全量解码整条记录"改为读单个状态列（取消轮询 20Hz 的解码开销归零）。
2. **run 列表瘦身**（`runner.summary`）：`GET /runs` 返回摘要投影——results 压缩为 `id/task_id/status/score/error`，剥掉 observation 与任务定义全文；单 run 详情端点不变。500KB stdout × 5 结果的夹具下，列表响应 <20KB。
3. **按需轮询**（F1）：评测工作区 3 秒全量轮询改为——有进行中的 run/job/分析时 3 秒；空闲时 15 秒；`document.hidden` 时暂停、切回立即拉一次；加重入保护（慢响应不得乱序回写旧数据，兼修 F5 前半）。

## D7 列表深度

`store.list` 支持 `limit`（1–1000，默认 200）；`GET /runs?limit=` 透传。摘要化后更大深度不再昂贵。

## F2 校准任务误展示

`jobs.find(active)` 未按 `operation` 过滤：校准进行中切到题目页会看到"正在生成题目"横幅且按钮被禁。现在生成相关 UI 只看 `operation !== "calibration"` 的任务（进行中横幅、失败提示、完成提示三处）。

## F3 跨测试集选择残留

切换测试集（或离开测试集）时清空题目选择——跨集组合提交从此不可能（后端 409 兜底保留）。

## F4 校准完成关掉宿主对话框

`CalibrationPanel` 的完成回调从 `onSaved`（关闭+刷新）改为新 prop `onCalibrationDone`（仅刷新）——刚生成的校准报告留在当前对话框里可见。类型接线由 tsc 钉死；行为面由既有套件回归（CalibrationPanel 独立轮询机制未变）。

## F13 全局 ErrorBoundary

`ui.tsx` 新增 `ErrorBoundary`（渲染崩溃降级为可读错误卡 + 重新加载按钮），挂在 `App` 根。脏数据白屏面收敛为单卡。

## 验证

- 新测试：后端 `test_run_list_scalability.py` 4 项（摘要保身份/负载 <20KB/limit 控制+422/取消零解码）；前端 F2 两项、F3 一项、ErrorBoundary 两项。
- 后端全量 **354 passed**；前端 **63 passed**（含新增 5 项）；构建通过；ruff 干净。
