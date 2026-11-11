# Project-first workspace and readable conversation

User correction: start with establishing a project; only enter its conversation by opening a project card. The previous Linear-inspired palette is retained, but the global shell and conversation composition need replacing. Desktop remains the priority. This supersedes the previous default-import-to-conversation decision.

References inspected on 2026-11-11:
- https://support.claude.com/en/articles/9519177-how-can-i-create-and-manage-projects : project knowledge and chat belong to a project; separate workspace management from conversation.
- https://v0.app/docs/projects : project-level scope, contextual settings rather than all controls permanently visible.
- https://www.assistant-ui.com/demos/chatgpt and /examples/chatgpt : readable centered column, generous 16px conversation type, quiet assistant turns and a distinct composer.
- https://rhesis.ai/platform/verifiable : actual Architect product screenshot; use agent-project context and test workflow, not landing-page decoration.

Implementation choices: retain React/MUI and backend APIs. Global project home uses a horizontal header and project cards, no empty project sidebar. Primary action “建立项目” opens the local-project form. Creation returns to the card directory with the new project visible, without automatically opening a conversation. Clicking a card opens the persistent conversation. A project-only sidebar has back-to-projects, current project switcher and three context destinations; future test stages remain disabled. Light/dark modes remain available.

Conversation: one centered 760px reading column, 15–16px type, clear prose hierarchy, user bubbles, assistant text with one restrained identity mark, compact source/unknown metadata under the initial understanding. Remove the fixed right context rail and duplicate navigation. Sources and full understanding are available through project detail navigation, keeping drafts mounted. Composer stays aligned to the reading column, with project-materials and model controls. Non-error system history is folded into a disclosure; failures stay visible. Unknowns, stale provenance, continue gate, source details and per-project isolation remain authoritative.

Palette: light #fff/#f6f6f8/#24252b/#6b6d79/#626bd2; dark #191a1e/#15161a/#ebebef/#999ba8/#8189e4. Inter with native Chinese fallback, 30px directory title, 18px project titles, 15–16px conversation text, 13px metadata. Cards 14px radius, inputs 8px, composer 20px. No background gradients or decorative hero sections.

Review: the earlier design copied compact data-app density into conversation and exposed project navigation before project selection. This pass changes those two underlying decisions, rather than making another palette-only adjustment. No multi-chat/thread management or fake stage 2 behavior is added.

User clarification: executor means evaluation backends (local command, HTTP API, Harbor). Add a third independent global destination and persistent encrypted definition CRUD. Actual execution, project binding, credentials injection, budget control and connection verification remain unavailable and explicitly labelled.

- [x] Failing behavior tests: root shows project establishment with no workspace sidebar, creation stays in directory until a card opens, conversation no fixed context rail.
- [x] Global header, project-only navigation, simpler cards and create-project flow.
- [x] Readable conversation and composer; sources/understanding one level away.
- [x] Browser review of empty home, populated cards, light/dark conversations and creation round-trip; frontend tests/build, update screenshots and PR.
