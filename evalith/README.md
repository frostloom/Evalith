# Evalith local evaluation workspace

项目优先的本地 Agent 评测工作区。React 深浅色界面与 FastAPI/SQLite 后端共同提供：项目导入与持续会话、来源理解、版本化题目、隔离环境、逐题执行证据、独立结果分析。

## 启动

从仓库根目录执行：

```bash
./scripts/start-local.sh
```

打开 <http://127.0.0.1:8093>。需要 Python 3.12+、uv、Node 22+。脚本安装 Python 依赖、按需安装前端依赖并构建前端，数据库、缓存和临时文件默认位于仓库 `.evalith/`，前台运行服务，Ctrl+C 停止。

可用 `EVALITH_API_PORT` 修改端口，`EVALITH_DATA_DIR` 修改数据位置。本机路径与非敏感构建选项可保存在 git 忽略的 `.evalith/local.env`。该文件由本地用户维护，不从导入项目加载。

## 本地 ChatGPT 账号

模型配置中选择“本地 ChatGPT 账号”，填写模型 `gpt-6-luna`。CLI 负责复用已有 ChatGPT 登录；Evalith 不复制账号凭据，也不把凭据交给被测项目或前端。

CLI 不在 PATH 时设置 `EVALITH_CODEX_BIN=/绝对路径/codex`。可用 `GET /api/local-model/status` 查看登录可用性，配置中的“连接测试”会真实调用一次模型。推理请求为临时会话、禁用工具、只读、无项目规则；超时、取消、网络错误都可见，不自动替换模型或重试。

输入/输出 tokens 仅在服务返回时记录。账号用量不能换算为金额，费用显示未知。运行调用上限包括 Agent 的每次推理和评分；金额上限在费用未知时阻止模型请求。分析有独立预算。外部 API-key 模型仍需显式开启 `EVALITH_ALLOW_PAID_MODELS=1`。

## 使用流程

1. 建立项目，选择只读资料范围和模型。从项目卡片进入主会话，检查模型理解与未知项；表示继续不等于确认未知业务规则。
2. 在主会话点击“生成评测资产”，或从“测试题目”生成。一轮模型请求会同时编写题目、Rubric、Grader 的证据检查步骤与阈值，并自动绑定成真实测试集；校验完整后一起保存，失败不会留下半套资产。生成不等于执行或校准。
3. “评价标准”也支持输入自然语言评分要求，生成可修改的 Grader 草稿，确认后保存；可继续从现有 Rubric 导入或手工配置。标准保留模型、适用任务类型、来源、未知项、版本和归档。项目待确认项由服务保留并传给实际评分模型，生成不会自动确认它们。
4. 选择题目和执行环境后预检评分方案，查看每题实际使用的标准、版本、模型和阈值，再确认启动。默认按“本次显式覆盖 → 测试集标准 → 题目绑定的 Grader → 题目内置检查”解析；可显式选择只用内置检查。不适用的标准列出原因，无适用检查时阻止执行。预检不调用模型，配置在预检后变化会要求重新确认。运行冻结整份评分计划，后续编辑不改写历史结果。
5. 在“评测运行”打开批次，切换概览、测试结果和运行配置。点击结果或矩阵单元格，查看对话、评分及原始证据。停止后保留已完成结果，业务失败、执行错误、缺失证据、待复核、预算停止和跳过分别呈现。
6. 结束后分析全部、失败、低分或指定结果。未知分数不归入低分；分析不改写原始结果。模型和执行器配置在独立导航中管理。

编辑题目的 Rubric 或 checks 后，新版本解除原题目默认 Grader 绑定，内置 judge 会使用新 Rubric；标题或输入等修改仍保留绑定。共享 Grader、旧版本和历史结果不变。测试集或本次显式覆盖仍然优先，请在预检中核对。

## 执行器与限制

- **本地命令 / 文件**：命令由独立执行器配置提供。模型只生成声明式输入与检查，不生成可执行程序。每题复制源文件，写操作限制在单题目录，网络禁止，用户配置和其他项目不供目标读取。
- **本机 HTTP API**：仅支持 loopback、专用测试数据，需在方案中明确确认。Evalith 不负责启动或清理该用户服务。
- **AI Gateway Go 适配器**：在 Evalith 内复制并编译真实 `internal/agent.Handler`；每题使用独立 SQLite、内存 Redis 和合成账务后端，模型经私有通道调用本地账号。需要 Go 与可用 C 工具链。`EVALITH_GO_PROXY` 可指定模块镜像，`EVALITH_GO_SDKROOT` 可指定本机已安装 SDK，均不更改全局配置。
- **Harbor**：仅保存定义，尚未实现运行协议；不能选择为真实执行器。

命令执行目前依赖 macOS `sandbox-exec`，其他主机明确拒绝执行。这里使用操作系统文件和网络限制，不提供容器/虚拟机级隔离。安装的系统与语言运行库可读；目标不能读取无关用户文件。仅可信本地单用户使用，不对外开放；Host/Origin 检查保留。

服务重启把未结束操作标为中断并保留记录，无法确认的遗留清理状态显示未知。证据文件保留在 `.evalith/app/runs`，环境副本在 `.evalith/app/environments`，不自动删除。模型判分与小样本结果尚未人工校准，不代表生产质量或真实账务集成。

## 验证

从仓库根目录：

```bash
UV_CACHE_DIR="$PWD/.evalith/cache/uv" uv run --project evalith pytest -c evalith/pyproject.toml evalith/tests --basetemp .evalith/tmp/pytest
npm --prefix evalith/web test
npm --prefix evalith/web run build
```

[真实 aigateway 与文件执行验证](../docs/validation/2026-11-12-real-evaluation.md)。原有 EE-free Rhesis 实验工作台保留在 `workbench/`，与此服务独立。

[Rhesis 工作流迭代与真实评分验证](../docs/validation/2026-11-13-rhesis-workflow.md)。

[Rhesis 功能实现：自动资产准备与评分编排](../docs/validation/2026-11-13-rhesis-functional.md)。API：`POST /api/projects/{id}/preparations` 后通过 `/jobs/{job_id}` 查询结果；`POST /graders/synthesize` 传 `description` 生成草稿；`POST /runs/preview` 使用与 `/runs` 相同的请求解析评分计划，确认启动时带回 `plan_digest`。原 `/generate` 保留题目生成兼容行为。
