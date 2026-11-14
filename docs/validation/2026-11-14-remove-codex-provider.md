# 移除本地 ChatGPT 账号推理通道

依据 [spec](../superpowers/specs/2026-11-14-remove-codex-provider-design.md) 与 [plan](../superpowers/plans/2026-11-14-remove-codex-provider.md)。用户方向：继续开发，不再使用 codex 相关配置。按仓库惯例本人执行，无委派；不触碰原始 ai-gateway 与未跟踪的 rhesis 参考。

## 变更内容

- 删除 `codex_provider.py`（Codex CLI 进程、临时 ChatGPT 通道、`gpt-6-luna` 默认值）与 `test_codex_provider.py`。
- 模型提供方白名单收敛为 `stub` / `openai_compatible`；创建 `codex_local` 返回 422 `provider_removed`，消息明确说明通道已移除。
- `ModelGateway` 移除 codex 分支与构造参数；遗留 `codex_local` 行在所有请求路径抛出明确的 ModelError，连接测试返回失败并附同一消息，不启动任何 CLI 进程。
- 移除 `EVALITH_CODEX_BIN` / `EVALITH_CODEX_TIMEOUT` 设置、`GET /api/local-model/status` 端点、`start-local.sh` 对 ChatGPT.app 内置 CLI 的自动探测；runner 的目标推理时限改用统一 `gateway.timeout`。
- 前端“添加模型”不再提供本地 ChatGPT 账号选项；遗留配置显示“ChatGPT 账号（已移除）”。`types.ts` 保留 `codex_local` 联合成员仅为渲染遗留行。
- README（根目录与 evalith/）改写为 OpenAI 兼容服务接入说明；付费模型默认禁用（`EVALITH_ALLOW_PAID_MODELS`）语义不变。
- Go aigateway 适配器无协议改动：模型桥接本就经工作区网关，随运行所选模型配置走 OpenAI 兼容通道。

## 历史与边界

- 数据库中的遗留 `codex_local` 配置（本机为 `mdl_2c2223925a324ddb`）保留可见，历史运行与用量记录未改写。
- `.evalith/local.env` 中的 `EVALITH_CODEX_BIN` 导出自此失效，文件属用户维护，未改动。
- 本次迭代没有发起任何真实模型调用；不含模型质量结论。Harbor、自适应多轮、Grader 校准/调优仍是未实现能力。

## 验证

- 后端 **277 passed**（`uv run --project evalith pytest -c evalith/pyproject.toml evalith/tests`）；新增 `test_model_provider_removal.py` 3 例先失败后通过，原以 `codex_local` 模拟真实模型的 2 处测试改用 loopback `openai_compatible`。
- 前端 **54 passed**（新增 `ModelSettings.test.tsx`）+ Vite 生产构建通过。
- 改动模块 Ruff 无新增告警（存量 UP032/PIE810/B008 等为基线，未触碰）。
- 实机服务（`./scripts/start-local.sh`，127.0.0.1:8093）：`/api/health` 正常；真实数据库列表仍显示遗留配置；`GET /api/local-model/status` 返回 404；创建 `codex_local` 返回 422 与移除消息；对遗留配置“测试连接”返回 `ok=false` 与移除消息，未启动 CLI。
- 浏览器实测（agent-browser）：模型配置页遗留配置标注“已移除”，添加对话框提供方仅剩 离线演示 与 OpenAI 兼容服务。截图：[model-settings-legacy-removed.png](evidence/codex-removal-2026-11-14/model-settings-legacy-removed.png)、[add-model-options.png](evidence/codex-removal-2026-11-14/add-model-options.png)。

## 合并前双轴复评与修复

用户要求审核后合并。按两轴并行复评（Standards：仓库无成文规范，按坏味道基线；Spec：对照本 spec 全树核对）。评审确认：无残留 codex 进程路径或模块引用；遗留行所有请求路径失败关闭；历史数据、付费门控语义未变。

依据评审修复四项：

1. **选择时拒绝**（spec "Creating or **selecting**…" 原实现缺失）：新增 `require_supported_model_config`，在项目创建、项目模型指派与 Grader 保存三条绑定路径上以 422 `provider_removed` 拒绝遗留 `codex_local` 配置；模型选择下拉（导入、Grader 评分模型、会话模型菜单）对遗留项显示“已移除”。回归测试 `test_binding_legacy_codex_model_is_rejected_at_selection_time` 先失败后通过。
2. **环境方案文案失实**：aigateway 环境计划的 `credential_sources` 由“Existing ChatGPT login…”改为所选 OpenAI 兼容模型配置的 API 密钥说明，`cost_note` 同步改写。
3. **范围外行为变化**：删除原 codex 专属、上一提交误推广到所有提供方的目标推理 80 秒上限；恢复由 `EVALITH_MODEL_TIMEOUT` 统一约束。
4. **文案合一**：`service.py` 与 `model_gateway.py` 的移除提示统一为共享常量 `REMOVED_PROVIDER_MESSAGE`。

评审中判定为可接受、未改动：`source_copy.py` 的 `.codex` 目录排除（保护性）、测试夹具中三处模拟遗留行的 SQL 重复（夹具实践）、前端标签三元表达式风格。修复后聚焦回归 22 passed、前端 54 passed + 构建、改动模块 Ruff 无新增告警。
