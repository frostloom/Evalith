# Evalith

Evalith 是一个本地 Agent 评测工作台：从项目资料和持续会话生成版本化题目，在独立环境真实执行，并保留逐题证据与结果分析。

```bash
./scripts/start-local.sh
# http://127.0.0.1:8093
```

支持本地已登录 ChatGPT 账号与 `gpt-6-luna`。见[运行与功能说明](evalith/README.md)和[真实 aigateway 验证](docs/validation/2026-11-12-real-evaluation.md)。


## 阶段 1：项目工作区与开源底座

- [最新产品导航、会话与对话框](docs/stage1/2026-11-11-产品交互与会话.md)
- [交付说明](docs/stage1/阶段1-交付说明.md)：EE-free 构建、项目访问边界、主会话、理解门、凭据保护和验证证据。
- [本地项目访问边界](docs/stage1/project-access.md)
- [EE-free Rhesis 工作台](workbench/README.md)
- [Evalith 阶段 1 服务](evalith/README.md)
- 合成项目：[approval-agent](examples/approval-agent)、[support-agent](examples/support-agent)

```bash
# 从仓库根目录执行；Python 3.12+，Node 22+
uv sync --directory evalith
npm --prefix evalith/web ci
npm --prefix evalith/web run build
uv run --directory evalith uvicorn evalith.api:app --host 127.0.0.1 --port 8090
# 浏览器打开 http://127.0.0.1:8090

# 测试（限定 Evalith，避免收集外部实验树）
uv run --project evalith pytest -c evalith/pyproject.toml evalith/tests
npm --prefix evalith/web test

# EE-free 工作台构建、依赖与启动详见 workbench/README.md
```
