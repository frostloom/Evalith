# Evalith

这个仓库交给 Superagent 改。每个工单会从这里拉出一个 `agent/` 开头的分支。

## 阶段 1：项目工作区与开源底座

- [交付说明](docs/stage1/阶段1-交付说明.md)：EE-free 构建、项目访问边界、主会话、理解门、凭据保护和验证证据。
- [本地项目访问边界](docs/stage1/project-access.md)
- [EE-free Rhesis 工作台](workbench/README.md)
- [Evalith 阶段 1 服务](evalith/README.md)
- 合成项目：[approval-agent](examples/approval-agent)、[support-agent](examples/support-agent)

```bash
# Evalith 服务与测试
cd evalith && uv sync && uv run pytest -q

# 构建并验证 EE-free Rhesis 工作台
python3 workbench/build.py --source /absolute/path/to/rhesis
workbench/run_local.sh
python3 workbench/smoke.py
```
