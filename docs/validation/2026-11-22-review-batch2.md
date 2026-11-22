# 2026-11-22 · 审查修复批次 2：安全收口

对应 [2026-11-21 全面代码审查](2026-11-21-全面代码审查.md) §12 第一批（安全收口）。分支 `agent/review-batch2`，单提交。

## S1【高】输出回收的符号链接逃逸 —— 已修（实测验证）

- 位置：`execution_process.py`。原实现进程结束后按路径 `read_text()` 读 `stdout.txt`/`stderr.txt`，被测目标可用符号链接借完整用户权限读出任意可读文件。
- 修复：两个输出文件以 `w+b` 打开；进程组收割移入 open 块内；**回读一律 `seek(0)+read()` 走仍打开的描述符**——目标对路径做任何替换都不再影响读到什么。
- RED→GREEN：`tests/test_output_capture_hardening.py`。旧代码上 stdout/stderr 两个符号链接测试**真实泄露标记串而失败**（攻击复现）；新代码 4/4 通过（泄露断言通过 + 正常输出捕获不变 + 退出码 0）。

## S2【中偏高】mach IPC 未限制 —— 已修（实测验证）

- 修复：profile 在 `(allow default)` 基础上追加 `(deny mach-lookup*)`、`(deny mach-register)`、`(deny process-info*)`——cfprefd/SecurityServer 等 launchd 服务的 IPC 通道整体关闭。
- 验证：`tests/test_sandbox_hardening.py::test_defaults_read_cannot_reach_cfprefd`（审查 PoC 同路径：`defaults read` 经 cfprefd 必须失败）；`test_hardened_profile_still_runs_plain_targets`（收紧不误伤正常目标）。

## S3【中】loopback 全端口放行 —— 已修（实测验证）

- 修复：`localhost:*` 全端口改为 `(allow network* (remote tcp "localhost:<bridge_port>"))`；`loopback=True` 而无 `bridge_port` 时**直接抛错拒绝执行**（fail-closed）。调用方 `_execute_local` 传入 `settings.api_port`。
- 语法验证：seatbelt 的 `ip` 过滤器只接受 `*`/`localhost` 主机字面量（裸 IP 报 `port missing`/`host must be *`），实测确认 `tcp` 过滤器 + `localhost:port` 是唯一可精确限端口的形式，且对连接 `127.0.0.1` 的目标生效（Go 适配器 URL 即 127.0.0.1）。
- 验证：`test_loopback_connects_only_to_the_bridge_port`（双监听器：允许端口 CONNECT_OK、另一端口 PermissionError）；`test_loopback_without_port_fails_closed`。

## S4【中】口令派生无盐单次 SHA-256 —— 已修

- 修复：`security.py CredentialCipher`：口令路径改为 PBKDF2-HMAC-SHA256（600k 迭代）+ 每安装 32 字节随机盐（`kdf.salt`，O_CREAT|O_EXCL 0600）；Fernet key 直传与随机 key 文件路径不变。
- 兼容：旧派生密文经**只解密不加密**的 legacy 回退仍可读（存量安装不损坏）；新写入一律走加盐密钥。
- 验证：`tests/test_kdf_hardening.py` 6 项——两安装同口令派生不同密钥（跨安装不可读）、盐文件 0600 且创建后不变、Fernet key 直传不经派生、legacy 密文可解、新密文在 legacy 密钥下必解不开。凭据回归 `test_credentials.py` 63 项全过。

## R6【中】桥接请求体无上限 + 非 ASCII 头 500 —— 已修

- 修复：`api.py` 新增 `BodySizeLimitMiddleware`（8MB，超限在解析前 413，覆盖全部 POST 路径）；`_require_bridge_token` 改为字节比较（`compare_digest(bytes, bytes)`，str 参数遇非 ASCII 会自身抛 TypeError）。
- 验证：`tests/test_bridge_hardening.py` 5 项——12MB 体 413 + error JSON、正常体不受影响、非 ASCII 令牌 403 而非 500（单元层直接打比较函数：httpx 拒绝把非 ASCII 头放上网络，说明该攻击面在真实 HTTP 层已被传输层挡住，比较函数的健壮性是纵深防御）、错误令牌 403、正确令牌放行。

## 回归与门禁

- 全量 `uv run pytest`：**327 passed**（300 存量 + 27 新增；无回归）。
- `uv run ruff check src/evalith`：通过（CI 门禁范围）。
- 两轴审查（Standards/Spec 并行子代理）结果见仓库执行记录；合并前完成。
