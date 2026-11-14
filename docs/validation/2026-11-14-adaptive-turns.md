# 自适应多轮对话任务

依据 [spec](../superpowers/specs/2026-11-14-adaptive-turns-design.md) 与 [plan](../superpowers/plans/2026-11-14-adaptive-turns.md)。按仓库惯例本人执行，无委派；原始 ai-gateway 与未跟踪 rhesis 参考只读，仅修改 Evalith 自有的 `examples/aigateway/adapter.go`。本迭代无真实模型调用（无可用 OpenAI 兼容端点），验证为离线测试、适配器真实编译与实机界面检查，如实区分。

## 变更内容

- **题目定义**（TaskSpec）：conversation 输入新增可选 `adaptive = {max_turns: 2–12, instruction ≤ 2000, simulator_model_config_id?}`，开启时 `turns` 必须恰好一条开场消息；字段与取值全部校验。
- **运行规划**：含 adaptive 题目要求 aigateway 桥接执行器（否则 422 `adaptive_executor_unsupported`）；模拟器模型按 运行显式指定 → 题目指定 → 运行评分模型 解析，多题目指定冲突 422，替身模型 422；`simulator` 角色与 target/judge 同样快照与指纹校验。
- **模拟器端点** `POST /api/projects/{pid}/runs/{run_id}/simulator/v1`：复用运行桥接令牌鉴权（错 token 403）；到达轮次上限时直接返回 `end` 且不发起模型调用；正常路径经 `model_call`（预算预留、指纹一致性、逐次用量记录）调用 `SIMULATOR_SYSTEM_PROMPT`，响应校验 `{"message ≤ 8000, "end": bool}`，格式错误 502、预算用尽 429、运行取消 409。
- **执行器接线**：adaptive 题目向适配器进程额外传入 `EVALITH_SIMULATOR_URL` 与 `EVALITH_TASK_ID`；脚本式题目不变。
- **Go 适配器**：输入接受 `adaptive`；每轮回复后（未达上限时）向模拟器端点提交当前逐轮记录并按 `{"message","end"}` 继续，HTTP 失败或格式错误以非零退出显式失败，`end` 或达上限即停——不静默截断。脚本路径行为不变；已就绪环境的二进制指纹会要求重新准备后才能用于 adaptive。
- **前端**：题目对话框对话区新增“自适应后续轮次”开关（开启时锁定单条开场消息）、最多轮次、场景指令与模拟器模型选择，附诚实说明；对话记录证据视图沿用现有逐轮渲染。

## 边界与不承诺

- 模拟器消息是模型生成的用户行为，不代表真实用户；判定与证据口径不变。
- 自适应仅支持对话桥接执行器；非对话题目、Harbor 执行不在本迭代。
- 适配器交互循环无 Python 单测覆盖（与既有适配器一致），由真实编译与端到端环境流程保障；本机已用真实 ai-gateway 模块按环境构建流程完整编译通过（SDK 探测后 BUILD-OK）。

## 验证

- 后端新增 `test_adaptive_turns.py` 4 例先失败后通过：定义校验（含开场唯一性、字段与边界）、预检解析与拒绝（替身模拟器、多题目模拟器冲突）及 payload 优先级、端点契约（403 / 上限不发调用 / 正常路径记录 usage 与 purpose / 格式错误 502 / 未知题目 422 / 预算 429）、执行器仅对 adaptive 题目注入模拟器环境变量。非桥接执行器的 adaptive 拒绝逻辑在代码路径上，通常先被既有的题目类型/执行器匹配检查拦截，未单独设例。全量回归结果见交付说明。
- 前端 **56 passed**（新增 TaskDialog 自适应编辑测例）+ Vite 生产构建通过；gofmt 后适配器重编译通过。
- 改动模块 Ruff 无新增告警（evaluation_api 新增路由沿用全仓既有 `Body(...)` 写法，属披露基线）。
- 实机验证（`./scripts/start-local.sh`，127.0.0.1:8093，真实数据库）：题目编辑对话框出现“自适应后续轮次”开关，开启后展示最多轮次（默认 3）、场景指令与模拟器模型选择并锁定单条开场消息；仅切换未保存，未改动真实题目版本。截图：[adaptive-editor.png](evidence/adaptive-2026-11-14/adaptive-editor.png)。

## 合并前双轴复评与修复

两轴并行复评。Spec 轴结论：无缺失、无范围蔓延、无错误实现——解析顺序与快照/摘要一致性、端点鉴权/上限/预算/指纹/双重脱敏、适配器循环失败可见性、TaskSpec 边界、前端无保存副作用均逐条核实。Standards 轴批准但指出一处真实重复：simulator 路由逐字复制了 model 桥接路由的令牌提取与异常映射链，runner 内令牌门重复两份。

修复（行为等价重构）：`evaluation_api` 抽出共享 `_bridge_response`（BudgetStop→429 / RunCancelled→409 / ModelError→502 脱敏）与 `_bearer` 提取，两条桥接路由共用；runner 抽出 `_require_bridge_token` 供 bridge 与 simulator 复用。聚焦回归 19 passed（含桥接契约旧测），Ruff 无新增类别（余量均为披露基线）。评审判定可接受未改：TaskSpec 校验器内联风格（与文件一致，建议下次新增字段时再拆）、前端 `update({adaptive: undefined})` 依赖 stringify 丢弃 undefined（等价于 delete）、适配器 60 秒模拟器客户端独立超时（有意为之）。
