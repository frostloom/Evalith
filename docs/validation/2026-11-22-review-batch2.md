# 2026-11-22 · 审查修复批次 2：安全收口

对应 [2026-11-21 全面代码审查](2026-11-21-全面代码审查.md) §12 第一批（安全收口）。分支 `agent/review-batch2`，单提交。

## S1【高】输出回收的符号链接逃逸 —— 已修（实测验证）

- 位置：`execution_process.py`。原实现进程结束后按路径 `read_text()` 读 `stdout.txt`/`stderr.txt`，被测目标可用符号链接借完整用户权限读出任意可读文件。
- 修复：两个输出文件以 `w+b` 打开；进程组收割移入 open 块内；**回读一律 `seek(0)+read()` 走仍打开的描述符**——目标对路径做任何替换都不再影响读到什么。
- RED→GREEN：`tests/test_output_capture_hardening.py`。旧代码上 stdout/stderr 两个符号链接测试**真实泄露标记串而失败**（攻击复现）；新代码 4/4 通过（泄露断言通过 + 正常输出捕获不变 + 退出码 0）。

## S2【中偏高】mach IPC 未限制 —— 已修（过程曲折，如实记录）

- 初版提交实际**漏掉了本项**（一次字符串替换静默未命中），且首个测试用 `defaults read` 做探针是**假阳性**：cfprefd 会代行调用者的文件读沙箱，与 mach 无关。两轴审查（Standards/Spec 双子代理）抓住了这两点，合并被正确阻止。
- 补修与勘误：
  1. profile 追加 `(deny mach-lookup)` + `(deny mach-register)`（注意：`mach-lookup*` 通配符是**非法语法**，sandbox-exec 报 unbound variable）。
  2. 初版同时加了 `(deny process-info*)`——真实 profile 二分证明它才是破坏合法目标的元凶（python/sqlite 因 dispatch 运行时被杀，exit 133）；mach 拒绝单独存在时 sqlite/python 全部正常。已去掉 process-info 拒绝，只保留 mach 两项。
  3. 行为探针勘误：本机 macOS 上 launchd 经**继承 bootstrap 端口**向每个进程提供服务，`launchctl` 在有无拒绝下都成功；审查报告的 cfprefd PoC 在本机**不复现**（`defaults read` 在旧 profile 下同样失败）。因此测试改为钉 **profile 内容**（生成的 sandbox.sb 必含两项拒绝），并保留"合法目标不受影响"的行为测试。
- 立场：mach-lookup 拒绝在语义上关闭"按需服务查找"通道（在执行该语义的 OS 构建上生效），实测零误伤成本，保留为纵深防御；无法在本机构造可复现的行为击杀不冒充可以。

## S3【中】loopback 全端口放行 —— 已修（实测验证）

- 修复：`localhost:*` 全端口改为 `(allow network* (remote tcp "localhost:<bridge_port>"))`；`loopback=True` 而无 `bridge_port` 时**直接抛错拒绝执行**（fail-closed）。调用方 `_execute_local` 传入 `settings.api_port`。
- 语法验证：seatbelt 的 `ip` 过滤器只接受 `*`/`localhost` 主机字面量（裸 IP 报 `port missing`/`host must be *`），实测确认 `tcp` 过滤器 + `localhost:port` 是唯一可精确限端口的形式，且对连接 `127.0.0.1` 的目标生效（Go 适配器 URL 即 127.0.0.1）。
- 验证：`test_loopback_connects_only_to_the_bridge_port`（双监听器：允许端口 CONNECT_OK、另一端口 PermissionError）；`test_loopback_without_port_fails_closed`。

## S4【中】口令派生无盐单次 SHA-256 —— 已修

- 修复：`security.py CredentialCipher`：口令路径改为 PBKDF2-HMAC-SHA256（600k 迭代）+ 每安装 32 字节随机盐（`kdf.salt`，O_CREAT|O_EXCL 0600）；Fernet key 直传与随机 key 文件路径不变。
- 兼容：旧派生密文经**只解密不加密**的 legacy 回退仍可读（存量安装不损坏）；新写入一律走加盐密钥。
- 验证：`tests/test_kdf_hardening.py` 6 项——两安装同口令派生不同密钥（跨安装不可读）、盐文件 0600 且创建后不变、Fernet key 直传不经派生、legacy 密文可解、新密文在 legacy 密钥下必解不开。凭据回归 `test_credentials.py` 63 项全过。

## 审查反馈的其余小项

- `kdf.salt` 损坏（<16 字节）路径：改为截断重建（原 O_EXCL 会裸抛 FileExistsError）。
- 测试命名与 pytest 导入清理（两轴审查指出）。
- R6 的 8MB 上限按 Spec 审查意见记录为**有意全局**（不只是桥接），当前无端点合法超限；未来如有上传需求需同步调整。

## R6【中】桥接请求体无上限 + 非 ASCII 头 500 —— 已修

- 修复：`api.py` 新增 `BodySizeLimitMiddleware`（8MB，超限在解析前 413，覆盖全部 POST 路径）；`_require_bridge_token` 改为字节比较（`compare_digest(bytes, bytes)`，str 参数遇非 ASCII 会自身抛 TypeError）。
- 验证：`tests/test_bridge_hardening.py` 5 项——12MB 体 413 + error JSON、正常体不受影响、非 ASCII 令牌 403 而非 500（单元层直接打比较函数：httpx 拒绝把非 ASCII 头放上网络，说明该攻击面在真实 HTTP 层已被传输层挡住，比较函数的健壮性是纵深防御）、错误令牌 403、正确令牌放行。

## 回归与门禁

- 全量 `uv run pytest`：**327 passed**（300 存量 + 27 新增；无回归；mach 拒绝真实在位后复跑全量确认）。
- `uv run ruff check src/evalith`：通过（CI 门禁范围）。
- 两轴审查（Standards/Spec 并行子代理）结果见仓库执行记录；合并前完成。
