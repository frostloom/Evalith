# Evalith

Evalith 是一个本地 Agent 评测工作台：读取选定的项目资料，核对项目理解，并保留可追溯的主会话。

## 阶段 1：项目工作区与开源底座

- [最新桌面界面方案与实际截图](docs/stage1/2026-11-11-界面整体重做.md)
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

# 测试
uv run --directory evalith pytest -q
npm --prefix evalith/web test

# EE-free 工作台构建、依赖与启动详见 workbench/README.md
```
