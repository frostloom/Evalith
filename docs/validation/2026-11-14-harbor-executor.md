# Harbor 执行后端：命令题目的容器隔离执行

依据 [spec](../superpowers/specs/2026-11-14-harbor-executor-design.md) 与 [plan](../superpowers/plans/2026-11-14-harbor-executor.md)。按仓库惯例本人执行，无委派；原始 ai-gateway 与未跟踪 rhesis 参考只读。本机 Harbor CLI 0.24.0（阶段 0 探针用的 0.25.0 任务格式经离线 schema 校验后按 0.24 适配）与 Docker 29.8.2 均为真实版本；无凭据、无模型调用。

## 变更内容

- **环境方案/准备**（environments.py）：harbor 成为可选执行器（需执行器配置）；准备期解析 Harbor CLI（`EVALITH_HARBOR_BIN` 可覆盖，`shutil.which` 兜底）、探测 `--version` 与 Docker 守护进程并记录版本、复制只读源。命令重写与工作目录校验抽出共享助手（local_command 同用）。
- **执行**（evaluation_runner.py）：每题物化一个 Harbor 任务——项目源放进 `environment/`（构建上下文所在）并 `COPY` 进镜像、`task.toml`（`org/name` 任务名、`network_mode = "no-network"`、artifacts 覆盖工作目录与 `/app/out`）、`solution/solve.sh`（base64 写入题目输入文件、以 stdin 运行被测命令、记录 stdout/退出码）、极简 verifier（reward 仅元数据；与 agent 镜像同基础镜像，避免额外拉取）。oracle 代理执行被测命令；产物回收为观察（`evidence_directory`/`stdout`/`exit_code`），既有 checks 与 judge 机制不变。harbor CLI 失败或产物缺失为显式执行错误，缺失时附试录异常尾部；试录目录按任务目录名匹配。
- **进程模式**（execution_process.py）：`bounded_process` 新增 `unsandboxed=` 模式——保留进程组所有权、超时、取消与输出上限、清洁环境（增 HOME/DOCKER_HOST），不套 sandbox-exec；供编排型 CLI 使用，隔离边界在容器。
- **执行器语义**：配置 `command` = 容器内被测命令（与 local_command 一致）；Harbor CLI 独立解析，不占配置字段。
- **前端**：执行器设置文案更新（协议已接入）；运行对话框对命令题目提供 Harbor 配置。
- 预检：harbor 环境仅接受 command 题目（类型不匹配 422）。

## 边界与不承诺

- 容器即隔离边界：harbor CLI 以受监管的非沙箱进程编排 Docker（需要 Docker socket 与基础镜像拉取）。首次构建需数分钟；任务镜像保留在本地 Docker 缓存。
- 基础镜像固定 python:3.13-slim；其他运行时、compose 服务、云沙箱、Harbor 内 LLM 代理不在本迭代。评分与检查语义始终是 Evalith 单源；Harbor reward 仅元数据。
- 对话/自适应题目仍在 Go 桥接执行器。

## 验证

- 后端新增 `test_harbor_executor.py` 5 例先失败后通过：环境方案与准备（含 CLI/Docker 版本记录、执行器配置必需）、假 CLI 按真实产物契约回放的观察映射（stdout/exit_code/evidence/harbor 元数据）与任务物化内容（task.toml 字段、Dockerfile COPY、solve.sh 的 stdin/文件 base64 与目标命令）、CLI 失败显式报错、预检仅收 command 题目、非沙箱模式的超时与正常执行。全量回归结果见下。
- **真实运行**（本机 harbor 0.24.0 + Docker 29.8.2，合成项目 file-transform，零模型调用）：环境准备事件记录 CLI/Docker 版本与 2 个源文件副本；最终 run（66 秒，镜像已缓存）包含一过一败两题——通过题在无网络容器内真实执行 `python3 main.py`（stdin 喂入 JSON），stdout 为真实目标输出 `{"count": 2, "total_cent": 350}`，file_contains 与 exit_code 检查通过（score 1）；失败题为刻意错误预期（score 0）——**同时关闭了阶段 0 调研遗留的失败路径未执行缺口**。verifier 以 separate 容器真实运行（reward.txt=1、test-stdout.txt 存在，作为元数据记录）；产物（report.json、stdout、exit_code、stderr、源文件）完整回收为证据。回执：[real-run-receipt.json](evidence/harbor-2026-11-14/real-run-receipt.json)、[environment.json](evidence/harbor-2026-11-14/environment.json)。首次全量构建约 150–250 秒/批。
- 调试过程中真实暴露并修复的三类问题（均有留痕）：0.24 要求任务名为 `org/name`；Harbor 构建上下文是 `environment/` 目录（项目副本需置于其内）；verifier 镜像独立拉取遇注册表超时（已统一基础镜像）。
