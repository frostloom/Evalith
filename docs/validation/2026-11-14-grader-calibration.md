# Grader 校准：已知结果样本核对评分行为

依据 [spec](../superpowers/specs/2026-11-14-grader-calibration-design.md) 与 [plan](../superpowers/plans/2026-11-14-grader-calibration.md)。按仓库惯例本人执行，无委派；不触碰原始 ai-gateway 与未跟踪的 rhesis 参考。本迭代不含真实模型调用（无可用 OpenAI 兼容端点），全部验证为离线测试与实机界面检查，并如实区分。

## 变更内容

- 新增 `evaluation_calibration.py`：judge 评价标准的已知结果样本校准。样本含名称、观察文档与预期（应通过 / 应失败 / 应缺证据），1–20 个；校准按与真实运行完全相同的路径执行——复用 `grader_check` 编译判定标准、共享常量 `JUDGE_SYSTEM_PROMPT`（自 runner 提取）、逐字证据校验、阈值与 missing_evidence 语义——每样本一次评分模型调用。
- 异步任务与报告：复用现有 job 记录与线程模式；报告（kind `calibration`）不可变，记录逐样本预期/实际/分数/理由/证据引用、汇总、用量与模型。全部一致 → 该版本 `calibration_state=calibrated`；存在不一致 → `disagreement`。校准期间标准被修改 → 报告标记 `stale` 且不改写状态。同一标准同时只允许一个校准任务（409）。
- 同步拒绝：非 judge 标准（422 `calibration_not_judge`）、无模型且未显式指定（422）、替身模型（422）、样本非法（422）。
- 编辑标准生成新版本并将 `calibration_state` 重置为 `unverified`、清除 `last_calibration_id`（原实现静默携带旧状态，属缺陷一并修复）。
- 前端：标准卡片徽章按状态显示（已校准 / 校准不一致 / 未校准，替换原硬编码“未校准”）；judge 标准详情确认页新增校准面板——样本编辑器、模型选择（仅列 OpenAI 兼容）、任务进度轮询、最新报告逐样本对照与历史选择。
- 附带：`model_gateway` 离线提示文案更新（不再提及已移除的登录账号通道）。

## 边界与不承诺

- 校准一致是关于评分标准的证据，不是业务真值；UI 与文档明示。校准不执行被测目标、不触碰环境、不确认项目未知项、不改写历史运行与判定结果。
- 确定性检查（contains/file_* 等）不支持校准并明确拒绝；题目级嵌入式检查的校准不在本迭代。
- Harbor 执行、自适应多轮仍未实现。

## 验证

- 后端新增 `test_evaluation_calibration.py` 6 例先失败后通过：全一致 → calibrated、不一致样本明细 → disagreement、伪造证据 → missing_evidence、三类同步拒绝、中途编辑 → stale 且状态不变、并发校准 → 409。全量回归 **284 passed**（278 旧 + 6 新）；期间一次后台运行出现过 1 例偶发失败，随后两次完整重跑均全绿，判定为时序敏感偶发并如实记录。
- 前端 **55 passed**（新增校准状态与发起点测例）+ Vite 生产构建通过。
- 改动模块 Ruff：新模块仅余 BLE001/B008 两处，与现有 generation 任务和路由的既有约定一致（job 线程必须捕获全部异常以落盘失败；`Body(...)` 默认值为 FastAPI 全仓既有写法），作为基线披露；其余清零。
- 实机验证（`./scripts/start-local.sh`，127.0.0.1:8093，真实数据库）：judge 标准绑定遗留 codex 模型时发起校准返回 422 `provider_removed`（守卫链贯通）；确定性标准返回 422 `calibration_not_judge`；报告列表为空、不存在报告 404。浏览器实测 judge 标准详情确认页出现“评分标准校准”面板（状态徽章、样本编辑器、满足前禁用的开始按钮），截图：[calibration-panel.png](evidence/calibration-2026-11-14/calibration-panel.png)。本迭代未配置 OpenAI 兼容端点，未发起真实校准调用。

## 合并前双轴复评与修复

两轴并行复评（Standards 坏味道基线 / Spec 对照逐条核验）。Spec 确认：每样本单次调用与用量累计、报告只建不改、全一致才 calibrated、编辑重置状态、同步拒绝与并发 409、无目标执行与历史改写。据评审修复四项：

1. **判定校验合一**：`grading_plan.validate_judge_verdict` 成为运行与校准共用的唯一判定校验（含逐字证据、阈值与 missing_evidence 语义）；runner `_judge` 改为调用它，行为等价（含 runner 回归 11 例通过）。校准中文档改为与真实运行相同的 JSON 序列化形式，证据引用口径一致；`limitations` 随样本记录。模型返回非检查列表时校准任务显式失败（新增测例：任务 failed、无报告、状态不变），不得以协议错误凑成“缺证据”匹配。
2. **完成段竞态关闭**：过期检测、报告落盘与状态写回移入 `_project_lock(pid)`，与 `save_grader` 互斥；并发编辑要么被判为 stale，要么在其后自行重置状态。
3. **前端轮询终止条件**：任务记录从列表消失时停止轮询并显式报错，不再无限等待。
4. **结构整理**：`CalibrationPanel` 拆为独立组件文件；`startCalibration` 改用专用 `CalibrationJob` 类型（回退对 `GenerationJob` 的临时拓宽）；样本更新回调合一。

评审判定可接受、未改动：job 线程模式与既有 generation 任务同构（第三份，作为基线披露）、stub 排除规则分层各司其职、状态字符串联合类型暂不收紧、`model_gateway` 提示文案更新为上轮移除的连带修正（已在提交说明披露）。修复后聚焦回归 18 passed、前端 55 passed + 构建、Ruff 仅余披露基线两处；全量回归结果见交付提交。
