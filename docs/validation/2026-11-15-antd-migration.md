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
