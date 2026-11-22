# 2026-11-22 · 审查修复批次 1：立即项

对应 [2026-11-21 全面代码审查](2026-11-21-全面代码审查.md) §12 第 1 批。分支 `agent/review-batch1`。

## 项 1：根许可证

- 问题（§8 高·非代码）：公开仓库无 LICENSE，默认"保留所有权利"，使用者无授权依据。
- 修复：根目录新增 `LICENSE`（MIT，Copyright 2026 frostloom）。选择依据：前端集成的 MIT 授权组件归因（`RHESIS-LICENSE`/`NOTICE.md`）已就位，MIT 与其兼容且为同类本地开发者工具的常见选择。维护者可随时更换。

## 项 2：`rhesis/` 参考检出未忽略

- 问题（§8 中）：142MB 未跟踪目录使 `git status` 长期脏，且曾发生从仓库根误收集其 pytest 的运行。
- 修复：`.gitignore` 新增 `rhesis/`。`git status` 复核：目录不再出现。

## 项 3：R1 严格 JSON 边界（高）

- 问题：被测程序输出 `{"score": NaN}` 这类 Python 风格字面量时，默认 `json.loads` 把 `NaN` 转成 float 值，随 observation 落库时序列化为裸 `NaN`——任何严格解析器（浏览器 `JSON.parse`、jq、导出脚本）解析该 run 的记录整体失败，一道题的输出毒化整批历史。
- 修复（双层门）：
  1. `evaluation_runner.parse_observed_json()`：stdout JSON 解析统一走 `parse_constant` 拒绝器——`NaN`/`Infinity`/`-Infinity` 字面量按无效处理（`observed["json"] = None`），原文仍作为字符串证据保留（字符串值本身合法）。
  2. `evaluation_store.encode_record()`：新增统一序列化助手（`ensure_ascii=False, allow_nan=False`），`create`/`mutate`/`save_task`/版本行四条写入路径全部改走该助手；非有限浮点在写入边界抛 `ValueError` 而不是污染记录（`create_bundle` 原有 `allow_nan=False` 一并并入助手，消除 D13 的不一致）。
- RED→GREEN：`evalith/tests/test_json_poisoning.py` 先行提交为 RED（`ImportError: parse_observed_json`/`encode_record` 不存在，1 error），实现后 GREEN（9/9 通过：三种非有限字面量拒绝、正常 JSON/纯文本/空串语义不变、写入边界拒绝 NaN/Infinity、存库 round-trip 为严格 JSON）。
- 全量回归：`uv run pytest` **309 passed**（300 存量 + 9 新增），无回归。
