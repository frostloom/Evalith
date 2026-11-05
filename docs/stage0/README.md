# 阶段 0 文档索引

阶段 0 的目标是验证 Rhesis 的复用方式、许可/品牌边界，以及通用评测执行的技术边界，为阶段 1 设计和实施提供可复现的依据。

| 文档 | 内容 |
| --- | --- |
| [阶段0-验证报告](阶段0-验证报告.md) | 总结论、方法、运行时验证、已通过/失败/未验证、风险与阶段 1 建议 |
| [复用与改造清单](复用与改造清单.md) | 可直接复用 / 需修改 / 必须新建的能力，附源码位置、复用方式比较、升级策略 |
| [执行边界与后端候选](执行边界与后端候选.md) | 本地资料访问、隔离执行、独立验证、清理；Rhesis / Harbor / Compose 对比 |
| [许可与品牌](许可与品牌.md) | 许可结论、必须删除/替换的品牌与法律素材、出站连接 |
| [源码与数据依赖图](evidence/rhesis-code-map.md) | 逐项 `path:line` 的架构/数据依赖证据 |
| [许可与品牌审计](evidence/license-audit.md) | 逐文件许可、NOTICE、字体、品牌资产证据 |
| [Harbor 评估](evidence/harbor-eval.md) | Harbor 0.25.0 的安装、任务格式、真实运行、清理与缺口 |
| [源码构建尝试](evidence/source-build-attempt.md) | 固定源码的构建进度、卡点与运行时镜像替代说明 |

可复现运行说明和合成任务代码在仓库根目录的 [`stage0/`](../../stage0/README.md)。

## 版本基线

- Rhesis：`ce24bb1993fc545bb0ccb0d8b3951683ac14fff1`（`VERSION` = `0.20.1`）
- Harbor：`0.25.0`（`harbor-framework/harbor`，Apache-2.0）
- 运行环境：macOS arm64、Docker 29.8.2、Python 3.12/3.13
- 所有模型与目标均为确定性替身；不代表真实模型能力

## 证据状态

- 合成任务：已跑通（通过/失败/未验证三态、隔离、清理）。
- Rhesis 运行时：接口级验证；结果见主报告 §7 与 `stage0/evidence/rhesis-runtime/`。
- Harbor：一次真实成功运行；失败路径未运行。
- 未验证项：真实模型能力、Rhesis 前端实时刷新、运行中取消、预算守卫、EE-free 社区模式启动、Linux 权限差异。
