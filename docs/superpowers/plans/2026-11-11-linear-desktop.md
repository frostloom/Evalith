# Linear desktop visual system and simplified PRD flow

User direction: use Linear's light and dark styles, simplify interaction, comply with `docs/PRD.md`; desktop is the priority. This supersedes the previous Rhesis visual direction while retaining working project/session isolation and accessible drawer/tab behavior.

Design: graphite neutral surfaces, thin dividers, compact 13px/14px body hierarchy, 20px directory titles, restrained indigo selection, Inter with native Chinese fallback, 6px controls, 8px cards, no decorative shadows or floating circular primary actions. Light: white canvas / pale grey rail. Dark: charcoal canvas / slightly deeper rail. One theme control persists the choice and is also available in drawers.

PRD flow: model services → project cards/import → project main conversation. Entering or importing opens the conversation immediately. A compact context rail shows the current understanding, source material and unknowns. Detail tabs expose full understanding and sources without overwhelming the main conversation. Keep future test-set/run entries clearly unavailable; do not pretend the subsequent phases exist.

- [x] Fail-first tests: default conversation, theme persistence, theme changes preserving chat and drawer drafts.
- [x] Central light/dark token palettes, persistent provider and local licensed Inter font.
- [x] Simplify navigation and page chrome, replace default MUI styling with a deliberate Linear-like desktop system.
- [x] Put conversation first and provide concise understanding/source context; preserve stale-evidence and readiness gates.
- [x] Run frontend suite/build, inspect real desktop screenshots in both themes, check primary flows and keyboard/contrast, update PR #4 with review and evidence.

Constraints: this pass changes the frontend only. Existing backend safety, model budget limits, snapshot provenance, error states and persistent sessions remain authoritative. Screenshots use synthetic projects and an offline model. No Linear proprietary artwork or code is copied; its official public product demonstration is a visual reference.
