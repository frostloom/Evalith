# Rhesis-style frontend implementation plan

> Execute inline in this session using the executing-plans workflow; the user asked Codex to perform the frontend changes directly.

**Goal:** Match Rhesis's product navigation, project directory, detail tabs, and right-side create/edit drawers in the existing Evalith frontend.

**Architecture:** Retain the existing API and project/session isolation. Use Material UI 7, the same design-token values and licensed Be Vietnam Pro font as the pinned MIT frontend; adapt its interaction patterns to the capabilities Evalith actually has. Do not import proprietary logos or expose unimplemented test execution as functional.

**Spec:** User request in this chat: review the frontend and use the interaction form of rhesis.ai. References: the public product tour and pinned `ce24bb1993fc545bb0ccb0d8b3951683ac14fff1` frontend components (`AppShell`, `SidebarProjectSwitcher`, `ProjectsClientWrapper`, `DetailTabNav`, `BaseDrawer`).

## Review findings

1. `Workspace.tsx`: links act as page anchors, while the reference uses real, keyboard-accessible detail tabs. All understanding, chat, and source content currently competes on one long page.
2. `App.tsx`: navigation is primarily a growing project list; the reference separates project scope from function navigation with a searchable switcher.
3. `ImportSheet.tsx`, `ModelSettings.tsx`: creation replaces context or stays permanently expanded; the reference uses explicit create actions and right-hand drawers.
4. `Workspace.tsx`: custom modal containers lack keyboard focus containment and Escape handling; use MUI's accessible Drawer primitive.
5. `styles.css`: independently invented typography, colours, density and duplicated override layers have drifted from the existing Rhesis design system.

## Tasks and verification

- [ ] Add failing interaction checks for real detail tabs preserving chat drafts, project directory filtering, creation drawer cancellation/focus, and browser navigation restoration.
- [ ] Add the same Material UI version as the reference, licensed font assets and attribution; introduce shared theme, page header, and drawer primitives.
- [ ] Replace the sidebar and project directory with project scope switching, grouped function navigation, search/status filters, and create drawer; preserve all pending-response isolation tests.
- [ ] Separate project overview, full-height conversation, and sources into true tab panels; preserve drafts across tab changes, historical-evidence warnings, and model/source edits in drawers.
- [ ] Convert model creation and project import to right-side drawers with sticky save/cancel actions and visible errors. Keep submission guards and original API payloads.
- [ ] Replace accumulated CSS with a single token-based system aligned to the reference.
- [ ] Run all frontend tests and the production build; exercise real browser flows and keyboard/axe checks at 1440/1024/768/390/320, capture screenshots, review the diff, and update PR #4.

## Review focus

Project changes during an outstanding request must not show stale data or transfer drafts. Drawer cancellation must invalidate pending imports. Back/forward and reload must restore project and active tab. Empty searches must provide a reset action. Source-change and model failures must remain visible after the visual redesign.
