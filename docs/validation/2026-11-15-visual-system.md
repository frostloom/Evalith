# 前端视觉系统升级 — 实施与验证记录

依据 [spec](../superpowers/specs/2026-11-15-visual-system-design.md)。用户方向：样式太丑，要优秀网页水准含交互组件。本人执行，无委派；不改功能与信息架构。

## 改动

- `theme.tsx` 重写：色板（浅色 rail #f7f7f5 微暖中性、强调 #3b5bdb/#2f4cc0 悬停阶；深色 #0f1115/#161920 底、按钮 #a7b9ff/#10131a）、MUI 默认值（Button/Input/Dialog/Drawer/Menu/Tab/Chip/Tooltip/MenuItem/Alert/ListItemButton）、动效 140ms、按压与焦点反馈、`--button-hover` 新变量。
- 新增 `system.css`（约 240 行，最后加载）：动效/焦点/海拔层、卡片上浮、行悬停与等宽数字、`.pill-*` 状态药丸族、侧栏激活态与分组标签、统一标题阶、空状态、滚动条、选区、reduced-motion。
- 旧 CSS 热点就地改：`.directory-body .page-heading h1`（27→24px）、`.page .page-heading h1`（26→24px）、`product.css .page-heading h1`（对齐 650/-0.02em）、`.nav-group` 两处（11px/620/0.05em）、搜索框圆角 6→8px。
- `main.tsx` 引入 system.css。

## 验证

- 生产构建通过；前端 **56 passed**（无 UI 行为回归）。
- 计算样式核对（agent-browser，深浅两模式）：页面标题 24px/650/-0.48px ✓、导航分组 11px/0.55px/620 ✓、按钮过渡 140ms ✓（旧值为 none）、输入/图标按钮圆角 8px ✓、新色板变量命中 ✓、侧栏 1px 描边 ✓。
- axe-core（4.12.1）：首页 **0 违规**（36 通过，1 处搜索占位符对比度标记需人工复核——#676f7e 于 #f7f7f5 上 ≈4.6:1，达标）；工作区视图 **0 违规**（43 通过，1 处 #panel-sources aria-allowed-role 次级提示，既有标记模式）。
- 截图存档（重拍版，每张拍摄前以 `data-theme` 与页面状态校验，6 张 6 个唯一哈希；本环境工具不可渲染像素，供人工复核）：[home-light](evidence/ui-redesign-2026-11-15/home-light.png)、[home-dark](evidence/ui-redesign-2026-11-15/home-dark.png)、[workspace-light](evidence/ui-redesign-2026-11-15/workspace-light.png)、[workspace-dark](evidence/ui-redesign-2026-11-15/workspace-dark.png)、[standards-light](evidence/ui-redesign-2026-11-15/standards-light.png)、[standards-dark](evidence/ui-redesign-2026-11-15/standards-dark.png)、[runs-dark](evidence/ui-redesign-2026-11-15/runs-dark.png)。

## 合并前双轴复评与修复

两轴复评发现首批实现的多处问题，全部修复（见修复提交）：状态药丸 `.pill-*` 族是无消费者的死 CSS——删除并行类族，改为把真实状态面（`.eval-state` StateBadge 全部运行视图、`.service-status` 模型配置、标准卡页脚）直接升级为药丸语言并逐项语义映射（通过/失败/待复核/进行中），实测计算样式 999px/21px 命中；system.css 的 22px 标题块与旧层 24px `!important` 竞争——删除竞争块，全站唯一 24px 展示阶；全局 `:focus-visible` 会把焦点元素圆角改为 4px 且与 MUI 焦点环叠加——删除该规则（旧层基础描边 + 主题双环已覆盖）；`prefers-reduced-motion` 的 `transform: none !important` 会破坏 Popper 定位——限定到本层动效选择器；`.btn-primary` 旧 `filter: brightness` 悬停未真正替换——就地替换为 `--button-hover`，深色悬停方向修正为一致变深（#9bb0ff）；`.standard-card` 被新旧两层矛盾修饰（10/12px 圆角、悬停边框与背景冲突、重复过渡）——就地统一为 12px + 上浮阴影、删除重复；旧 `:root` 静态值与新色板漂移造成挂载闪变——对齐为新浅色板；浅色警告文本对比度 4.5 边缘——加深至 #8a5e08；文档措辞修正（动效为 120–240ms 分档而非单值 140ms）；无效截图（深浅字节相同）按验证流程重拍。未改动并披露：两套按钮代码路径（.btn 镜像 MuiButton，历史并存）、约 40 处低频面圆角未入阶（spec 已声明热点边界）、`.nav-group` 三处定义（值已一致）。修复后构建 + 56 测试通过。

## 边界与未做

- 无像素级目检通道（截图工具在本环境返回不可渲染图像）；已用计算样式 + axe + 结构快照三路验证，最终视觉请以浏览器为准，不满意处可继续调。
- 旧 CSS（styles.css 3135 行 + product.css 1304 行）未整体迁移；本迭代为令牌统一 + 主题接管 + 精修层，页面级深改留待后续按需推进。
- 未做：骨架屏/加载态动画、图表类组件、动效编排（抽屉弹簧曲线）、新字体引入（保留 Inter 变量字重，中文回退 PingFang）。
