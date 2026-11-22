# 2026-11-23 · 审查修复批次 5：打磨（R5/R7/D3/D4 + 文档对账）

对应 [2026-11-21 全面代码审查](2026-11-21-全面代码审查.md) §12 第四批。分支 `agent/review-batch5`。

## R5 Harbor 清理语义与看门狗时长

- 看门狗从 `300 + 3×timeout` 改为 `max(300 + 3×timeout, 900 + 2×timeout + 120)`：task.toml 自己声明 `build_timeout_sec = 900`，冷缓存首次拉镜像+构建可能吃满 900s，原公式在短任务（如 30s）下 390s 就杀 CLI，把冷构建误判为执行失败。
- 清理语义：CLI 被强制终止（cancel/timeout/output_limit）时，错误信息明示"容器由 Docker 托管可能仍在运行，请用 docker ps 检查清理"——killpg 只到 CLI，容器状态对编排器不可见，不再隐含"清理已完成"。
- 测试：`TestHarborWatchdog`（捕获 bounded_process 收到的 timeout，30s 任务下 ≥ 1020s）。

## R7 budget_usd 陷阱显式化

- `preview` 响应新增 `warnings` 数组：`budget_usd` 非空时返回"金额费用未知……第一次模型调用前停止，全部结果不可评分"。用户在预览阶段看到陷阱，而不是目标跑完后才发现。语义本身（refuse-to-start）不变——诚实但不再沉默。

## D3 校准证据基

- `build_summary(samples)`：报告摘要从 `{total, matched}` 扩展为 `{total, matched, expected_mix, sufficient}`（≥3 样本且 ≥2 种预期结果才算 sufficient）。**状态机不变**（calibrated/disagreement 照旧）——中途试过加 `calibrated_thin` 状态，破坏既有契约，按报告"提示"而非"新状态"的本意回退。
- 测试：薄基（2×missing_evidence）与厚基（4 样本 3 类）两侧钉死。

## D4 结构性不可评分提前失败

- `_plan` 收集 stub 拒绝项：被应用的 judge 检查（无 grader 绑定的默认判分模型 + grader 绑定模型）若为离线演示模型，**preview 以 warnings 呈现、start 直接 422 拒绝**——目标执行（最贵的时刻）之前就失败。
- 范围裁量：只查判分侧；被测目标角色不查（离线测试套件的通用 stub 脚手架依赖目标可为 stub，且桥接路径已有运行时防护）。judge 角色仅在存在无 grader 绑定的 judge 检查时检查；未应用的 grader 不在运行模型表内（首版 KeyError 被既有测试抓住后修正）。
- 测试：preview 警告 + start 422 双断言；三个既有测试的判分模型脚手架升级为 openai_compatible 假端点（网关调用本就被 monkeypatch）。

## 文档对账

- `docs/开发阶段路线.md` 追加"阶段后状态对账"：阶段 0–5 交付状态、原未决项逐项现状（许可证已 MIT、预算语义已显式警告、谱系已可审计等）、修复后剩余已知限制（观察值行存储、双实例属主检测、远程认证、Harbor 容器清理依赖 Docker 侧）、MVP 后候选方向。

## 回归

- 后端全量 **358 passed**（354 存量 + 4 新增；grading_plan 三处失败为首版实现缺陷，被既有测试抓住后修正）。前端 **63 passed**（未触碰）。ruff 干净。
