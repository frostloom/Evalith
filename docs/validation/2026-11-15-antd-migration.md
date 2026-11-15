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
