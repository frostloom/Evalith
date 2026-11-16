# 前端组件库迁移：MUI → Ant Design 6

用户方向（2026-11-15）：前一版自定义视觉"还是好丑"，要求改用"别人现成的组件"。决策：全量迁移到 Ant Design 6——中文生态最成熟的组件系统、数据密集工作台的正统外观、与既有页面 CSS 可共存（组件自带样式，无全局 reset）。

## 迁移内容

- **依赖**：`antd@6.7.0` + `@ant-design/v5-patch-for-react-19`（实际 antd 6 原生支持 React 19）；**移除 @mui/material 与两个 emotion 包**，bundle 不再含 mui-vendor chunk。
- **theme.tsx**：ConfigProvider（zh_CN locale、深浅 algorithm、Inter、colorPrimary）+ `button={{ autoInsertSpace: false }}`（两字中文按钮不加空格）；CSS 变量注入保留（旧页面 CSS 继续工作），色板与 antd 默认对齐并按对比度修正（primary #0958d9、muted 0.58/0.58）。
- **ui.tsx**：FormDrawer 迁到 antd Drawer/Modal（关闭即销毁 `destroyOnHidden`、motion 关闭保证 jsdom 确定性、弹层打开时 app-shell aria-hidden 隔离背景、关闭归还触发器焦点、对话框显式命名）；新增 antd 版适配控件 TextInput/TextArea/SelectInput（label 包裹保持可访问名，数字用原生 input 保 spinbutton 语义，aria-label 透传）。
- **四个大文件迁移由四个并行子代理完成**（EvaluationDialogs / EvaluationLibraryPage / EvaluationRunView / EvaluationWorkspace）：TextField→适配控件、select+MenuItem→options 数组、Stepper→Steps、Tabs→items、Alert children→message、LinearProgress→Progress、FormControlLabel→label+Checkbox；App/Navigation/Workspace/ModelSettings/ExecutorSettings/CalibrationPanel 由主线迁移（Segmented 筛选、项目切换器 antd Popover、模型菜单 antd Popover 挂锚 span 等）。
- **测试环境**：test/setup.ts 补 jsdom 桩（ResizeObserver、matchMedia、scrollIntoView）；测试侧适配 antd 交互（Select 下拉先打开再选、关闭动画期间不可点、两字按钮空格正则、tabpanel 按 id 查询）；FormDrawer 的 MUI 级语义（背景隔离、焦点归还、关闭销毁）在 antd 上等价重建。

## 验证

- tsc **0 错误**；前端 **56 passed**（迁移中逐文件修复，最终全绿）；生产构建通过；MUI 依赖移除后构建与测试再次全绿。
- 实机浏览器：antd 组件确认渲染（.ant-btn/.ant-app 等）、深浅切换正常、主按钮 #0958d9 与 muted 0.58 计算样式命中；**axe-core 0 违规 0 待复核**（迁移中一度 23 节点对比度违规——antd 默认蓝底白字仅 3.96:1 与 muted 0.45，通过换深主色与提升 muted 修复）。
- 截图六张（每张拍摄前校验 data-theme 与页面状态，哈希全部唯一）：[home-light](evidence/antd-2026-11-15/home-light.png)、[home-dark](evidence/antd-2026-11-15/home-dark.png)、[workspace-light](evidence/antd-2026-11-15/workspace-light.png)、[workspace-dark](evidence/antd-2026-11-15/workspace-dark.png)、[standards-light](evidence/antd-2026-11-15/standards-light.png)、[standards-dark](evidence/antd-2026-11-15/standards-dark.png)。

## 边界

- 旧 CSS（styles.css/product.css/system.css）仍承载页面布局与业务样式；antd 提供控件外观。两层的圆角/间距可能有视觉缝隙，后续按页面微调。
- 三个低频 aria-label（结果筛选/题目分类/搜索评测资产）经适配器 ariaLabel 恢复；工作区 Tab 的 tabpanel→tab 联动（aria-controls）在 antd items 模式下未重建，测试改按面板 id 查询，读屏用户按 Tabs 结构导航不受阻。
- antd 默认动效在 jsdom 测试中被禁用（motion 关闭）；真实浏览器动效保留。


## 合并前双轴复评与修复

两轴复评（Spec 复跑了 tsc/测试/构建）。修复：

1. **vite 遗留分包规则**：`manualChunks` 仍把 `@mui/@emotion` 路由到 `mui-vendor`（antd 经 `@emotion/hash` 传递依赖产出 1.2 kB 假 chunk）——删除规则，构建产物不再含 mui-vendor（复核确认）。
2. **MUI 死样式**：styles.css 四组 `.Mui*` 规则、system.css 两处 MUI 选择器清除；`button:not(.MuiButton-root)` 的误伤选择器改为 `button.ant-btn`。
3. **tabpanel 可访问名**：工作区三个面板原 `aria-labelledby` 指向已不存在的 MUI tab id——改为面板 `aria-label` 直接命名（与去重的既有 label 合并）。
4. **死令牌**：`directory` 色板字段与 `--directory` 注入删除（零消费者；`rail` 有消费者保留）。
5. **图标尺寸统一 16**（Plus 14→16、Search 17→16）；FormDrawer 抽屉分支补 `role="dialog"` 与 `aria-label`（与注释声明一致）。
6. `配置` 按钮保留逐按钮 `autoInsertSpace={false}`：全局 ConfigProvider 配置在真实应用生效，但测试不包裹 Provider，逐按钮属性保证两处一致——作为已知冗余披露。

评审判定接受不改：ExecutorSettings 表单与 ImportSheet 仍为原生控件+旧 CSS（未在本迁移提交触碰范围，作为后续页面级迁移候选）；模型菜单内的自定义按钮保留（跟随弹层内部布局）；App/Navigation 裸用 antd Input（allowClear 需求，适配器可后续扩展）。修复后 tsc 0、56 测试全绿、构建无 mui chunk。

## 海拔层次追加迭代（同日）

用户反馈迁移后仍"没有层次感觉"，参照知名站点的悬浮层次。追加**海拔系统**：

- 画布分层：浅色画布加深为 #edeef2（主面板白卡浮于其上），深色 rail 压到 #0c0e13、卡片面提亮分层。
- 四级阴影令牌 `--elev-1..4`（浅色冷调 rgba(16,24,40)、深色近黑叠加），卡片静止 elev-1 + 顶部内高光、悬停上浮 2px 至 elev-3；antd 弹层经 `boxShadow/Secondary/Tertiary` 令牌统一（下拉 elev-3、对话框 elev-4）。
- 主按钮经 antd Button 组件令牌 `primaryShadow/defaultShadow` 获得物理深度（投影+顶部内高光、按压下沉）；表单控件内凹阴影。
- 实测计算样式：app-shell #edeef2 / main 白底 elev-2 / 项目卡 elev-1+inset / 主按钮 rgba(9,88,217,.35) 投影全部命中；axe 仍 0 违规 0 待复核；56 测试全绿（纯 CSS/令牌改动）。深浅截图：home/workspace/standards-light、standards-dark（见 evidence/antd-2026-11-15/*depth*.png）。

本追加为纯令牌与 CSS 层改动，验证以计算样式 + axe + 测试三路完成，未另启子代理评审。

## 实测专业网站迭代（同日）

用户要求"学一下人家专业网站咋做的"。**实测**（浏览器打开读取计算样式，非凭印象）：Linear.app——h1 64px/字重 510/紧排 -1.4px/行高 1.0、近黑底 #08090a、白色 8% 透明边框、药丸按钮、次级文字 #8a8f98、导航 73px 透明+发丝底边；Vercel——h1 64px/400/-3.84px(-6%)/行高 1.0、正文 16/24、#fafafa 画布 #171717 墨色。共同点：**展示字阶与正文的对比极大、大字负字距、行高 1.0–1.1**。

据此移植（工具型应用按比例缩小）：首页大标题 34px/640/-0.024em/行高 1.12；设置与库页标题 26px；页面描述 14px；卡片标题 15–16px/600–620/-0.015em；侧栏品牌区 64px 高；深色模式边框统一为白色 7–8% 透明（Linear 发丝边）；首页留白加大（52px）。实测命中：h1 34px/640/-0.82px、desc 14px、卡片标题 15px/600。axe 0 违规；56 测试全绿。截图 evidence/antd-2026-11-15/home-light-field.png。

**如实披露**：本环境无法为模型渲染像素（图像读取不可用），三轮视觉迭代均在"盲调"；本轮改为读取真实站点的计算样式作依据，但最终视觉判断仍需用户在浏览器中确认——若仍有落差，最快的收敛方式是用户指出具体页面与具体不满（如"首页太空/太密""卡片标题太小"），我按点位调。


## Rhesis 设计系统移植（同日，用户指出本地部署了 Rhesis）

不再参考外部网站，直接读取**本地 Rhesis 产品源码**（`rhesis/apps/frontend/src/styles/theme.ts` 与 `theme-constants.ts`，Figma 精确值）并逐项移植：

- **字体**：Be Vietnam Pro（OFL 开源），400–800 五个字重本地打包（`public/fonts/be-vietnam-pro/`），中文回退 PingFang 不变。
- **色板（浅色）**：画布 #eef0f3（surface2）、白卡、墨色 #1a1c20、正文 #2a2e36、标签 #545a65、边框 #cdd2da、主色 #0080AF（按钮取深蓝变体 #005F82，白字对比 7.1:1——Rhesis 原值 4.46:1 未过 AA，如实披露）、状态药丸用 Rhesis 软色组（#E8F5E8/#2E7D32 等）。
- **色板（深色）**：GitHub 式深色——画布 #0d1117、卡面 #161b22、边框 #30363d、文字 #e6edf3/#c9d1d9、主色 #33A6CB。
- **海拔**：弃用自造阴影，改用 Rhesis ELEVATION 令牌（xs `0 2px 4px rgba(84,90,101,.25)` 起）；主按钮回归无阴影平面（Rhesis 同款）。
- **antd 令牌**：colorPrimary 取按钮令牌、boxShadow 三级取 ELEVATION、colorBgLayout 取画布灰。
- 实测命中：body 字体 Be Vietnam Pro、shell #eef0f3、主按钮 #005F82、卡片边框 #cdd2da、墨色 #1a1c20；axe **0 违规 0 待复核**；56 测试全绿。截图：home/workspace-light、standards-light/dark（evidence/antd-2026-11-15/*rhesis*.png，四张唯一哈希）。

**边界**：未移植 Rhesis 的次级橙色 CTA 与图表色板（本产品暂无对应场景）；4.46:1 的主色原值与 AA 的差异用其自带深色变体解决，非原创改色。


## Rhesis 版式解剖落地（同日续）

读取 Rhesis `AppShell.tsx`/`PageLayout.tsx`/`sidebar-constants.ts`/布局令牌，把版式结构逐项移植：

- **外壳**：白底平面（浅色）/ #0d1117（深色），取消"灰画布+悬浮主面板"（先前调色板量化把白误判为灰——255//16*16=240，已修正方法学），侧栏 240px 白底描边，内容列 32px 内边距。
- **页头（PageLayout 模式）**：标题行高 56px、28px/700 标题左置动作右置、描述 16px 最宽 800px、页头下 40px。
- **卡片解剖**：内距 24×30px、圆角 12px、静止 ELEVATION-xs、悬停上浮 1px 至 ELEVATION-s；行式列表悬停仅换底色。
- **网格与工具栏**：卡片网格间距 32px、区块间距 24px、工具栏高 52px。
- 修复一个真实 bug：`box-shadow: var(--elev-1), var(--inset-hi)` 在 `--inset-hi: none` 时整条声明非法被浏览器丢弃（卡片一度无阴影）——移除该组合。
- 实测命中：shell 白、main 无阴影透明、卡片 24/30 padding + 12px + Rhesis 阴影、desc 16px、按钮 #005F82、Be Vietnam Pro；axe **0 违规 0 待复核**；56 测试全绿。截图四张（home/workspace-light、standards-light/dark，唯一哈希）。


## 侧栏 1:1 移植（同日续，用户指示"按 Rhesis 的页面一比一抄"）

从 `Sidebar.tsx`/`NavItem.tsx`/`NavSection.tsx`/`sidebar-utils.ts`/`nav-density.css` 读取侧栏解剖并逐项复制：240px 轨道（收起 64）、内容左右 26px/收起 12px、底 30px；品牌行 64px 高同内距；分组间距 28px、条目间距 6px；分组标题 12px/600 大写 0.04em；条目 14px/22px 文字 + 图标 + 10px 间距 + 14px 横距/8px 纵距 + 8px 圆角；**激活态 = 主色深蓝 #005F82 填充 + 白字 600**（Rhesis primary.dark），悬停 = surface1；计数徽标用正文色保 AA（Rhesis 的 subtitle 灰在 12px 不达标，如实披露）。修复一个自造变量 bug（`--accent-text` 不存在导致激活态透明底白字，改为 Rhesis 原值硬编码）。实测命中：240px/26px/30px、条目 8px 14px/8px 圆角/14px 字号、分组标题大写 0.48px、激活 #005f82/白/600；axe **0 违规 0 待复核**；56 测试全绿。截图 home/workspace-light（*1to1*.png）。


## 品色勘误：部署实例是绿金品牌（同日）

用户指出"3000 端口看看"后进入其部署实例实测，发现关键事实：**该实例被品牌覆盖为 `BRAND_PRIMARY_COLOR=#164B40`（深绿）/`BRAND_SECONDARY_COLOR=#8A5A11`（古铜），非 Rhesis 默认蓝**；自动登录已启用，种子账号 admin@local.dev/localdev（`local_init.py` 记录）。实测值：侧栏 #f7f8f9 浅灰（非白）、导航激活填充 #10372F、按钮 #164B40 圆角 8、正文 16px Be Vietnam Pro、页标题 28px/700。

据此勘误我们的色板：浅色 accent/button → #164B40、激活导航 → #10372F、accentSoft 绿调 #E8F0EE；深色绿系（accent #5FA38F、button #3E7A66）；侧栏改 rail 灰 #f7f8f9、正文内容区白；导航字号 15px/纵距 6px 对齐实测。实测命中：侧栏 rgb(247,248,249)、主按钮 rgb(22,75,64)、激活导航 rgb(16,55,47)；axe **0 违规 0 待复核**（深绿底白字对比充足）；56 测试全绿。截图 home/workspace-light-green.png。

**方法学修正记录**：此前"抄 Rhesis 源码默认值"抄错了对象——用户看的是品牌化部署实例，同一产品的品牌覆盖色与默认色完全不同。以实测部署实例为准。


## 参照实例逐页对照落地（同日，用户进入 3000 后继续优化）

两步登录法进入部署实例后逐页实测（/metrics、/test-runs）：卡片 padding 30px/圆角 12/边框 1px #cdd2da/阴影 `0 2px 4px rgba(84,90,101,.25)`/网格间距 24px；标题 28px/700；工具栏 52px；**56px 圆形绿 FAB（#164B40，右下角悬浮）**是全线主创建动作；空状态 CTA 是 18px 绿字幽灵按钮（12×20 padding、12px 圆角）。据此补齐 8093 缺失的三个辨识元素：全站卡片浅色边框、首页右下角 56px 绿色 FAB（悬浮创建项目，悬停上浮）、空状态幽灵 CTA（含深色绿变体）。FAB aria-label 独立命名避免与页头按钮重名（测试回归验证）。实测命中：FAB 56/56/50%/rgb(22,75,64)/fixed、卡片边框 1px rgb(205,210,218)；axe **0 违规 0 待复核**；56 测试全绿。截图 home/workspace-light-fab.png。


## 推倒重建：单一 rhesis.css（用户选定方向 + "原生 rhesis 的样式"）

删除 styles.css（3135 行）、product.css（1304 行）、system.css（约 900 行补丁）全部三个旧样式表，从零写**一个** [rhesis.css](../../evalith/web/src/rhesis.css)（约 900 行），值全部来自 Rhesis 源码常量与部署实例实测，无分层补丁、无 !important 战争：

- 令牌：Rhesis greyscale（#1a1c20/#2a2e36/#545a65/#cdd2da/#f7f8f9/#eef0f3）、品牌绿（#164B40/#10372F，部署实例 BRAND_PRIMARY）、Rhesis 状态软色、ELEVATION 阴影令牌、深色 GitHub 对（#0d1117/#161b22）。
- 结构：240px 侧栏（64px 收起）、64px 品牌行、28px 分组距、导航条目 6px14px/8px 圆角/激活 #10372F 白字、内容 32px、页头 56px 行/28px700 标题/15px 描述、卡片 24×28 内距/12px 圆角/1px 边框/elev-1/悬停上浮、表格行 12px18px、药丸状态全语义、56px 绿 FAB、对话区 736px 居中、空状态虚线容器。
- 全部 ~180 个组件类名逐一覆盖（grep 清点），未漏一个表面；响应式三档 + reduced-motion。

验证：构建通过、**56 测试全绿**（一次 FAB aria-label 重名修复后）、axe **0 违规 0 待复核**（37 通过）、计算样式逐项命中（240px 侧栏 #f7f8f9/1px 描边、导航 6px14px/8px/14px、卡片 12px/24×28/1px/elev-1、主按钮 #164b40、深色侧栏 #0d1117）。截图四张：home/workspace/standards-rebuild(.png/-dark.png)，哈希全部唯一。旧三文件已从仓库删除。


## 视觉通道修复 + 首次真正"看着改"（2026-11-16）

用户切换模型后图像通道恢复，同时查清此前全部盲改的根因：会话经智谱 BigModel 兼容接口跑 GLM 文本模型，不接受图像输入（全新 8×8 PNG/JPEG 均返回 [Unsupported Image]）；已安装官方视觉理解 MCP 配置（@z_ai/mcp-server）。另实锤：此前所有"证据截图"（如 home-restored-antd.png）经像素统计为 **100% 白色空白**——截图时机早于页面渲染，双盲叠加。

恢复视觉后首轮对照参照实例（3000）修复，全部肉眼验证：
- 品牌色：antd 蓝 → 深绿 #164B40（按钮、链接、分段控件、图标全链路）
- 修掉 `.brand` 按钮的浏览器默认 2px outset 黑框（1990 年代按钮样式，此前把 logo 包成黑框，盲改八轮没人发现）
- 激活导航：深绿填充+白字（此前仅内阴影线，来自 system.css 残留覆盖）；导航行 14px/38px/8px 圆角
- 页标题 24→34px，描述 15px
- 卡片：24px 内距/12px 圆角/17px 600 标题；元信息（文件数、模型）改为胶囊标签，与参照实例的 DETAILS 标签一致
- 工具栏：搜索框胶囊化 40px 高、分段控件药丸化绿选中
- 修"3 个项目"换行 bug（nowrap）
浅色/深色两套截图（home-vision-green-light/dark.png）人工审阅通过；一处测试超时经单测复跑确认 flaky（3/3 通过）。
