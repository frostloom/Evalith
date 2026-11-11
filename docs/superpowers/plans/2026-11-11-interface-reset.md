# Desktop interface reset after full visual rejection

User rejected layout, typography, conversation and overall appearance. Function/IA constraints remain: project directory first; create a card, then open its conversation; independent executor and model configuration; light/dark; desktop priority; no frostloom2 delegation.

This pass is a visual reset. Use frontend-design and the live https://linear.app/demo workspace (actually opened projects/issues), rather than describing the earlier design as Linear-like. Its useful properties are the 240px navigation, inset content canvas, 48px toolbar, thin dividers, clear scan lines and consistent line icons. Do not copy proprietary assets, text or application code.

Design choices:
- Single 236px workspace sidebar. Global directory/executor/model destinations are separate rows. Project navigation appears only after entering a project. Theme control at the bottom. No full-width duplicate navigation bar.
- Inset content canvas with 12px corners on a quiet neutral shell. Light #f0f1f4 / #fff / #1c2333 / #606a7c; dark #101115 / #18191f / #eff0f6 / #9296a6. Restrained blue-indigo #5766dc for primary actions and selection, no decorative gradients.
- One consistent Lucide line-icon family; custom Evalith mark. Inter/native Chinese, 14px interface text, 26px page titles, 16px conversation text, 12px secondary metadata. Visible keyboard focus and stable contrast across themes.
- Project cards get identity, clear title, readable local-directory path, existing model reference and source count, and an explicit entry affordance. All data comes from existing API results; no invented progress or evaluation metrics.
- Conversation has a clear transcript region, a distinct initial understanding treatment, source chips and concise unknowns. Reading width 780px. Composer is a proper command surface with material and model controls; quiet, compact secondary metadata.
- Model/executor lists share a more compact settings layout. Forms use the same control dimensions, field rhythm and footer system. No backend changes.

Keep existing business behavior and route/async guards. This is local visual work first; screenshots are the design evidence. Test/CI status is functional verification, not visual acceptance.

- [x] Replace icon system, shell and navigation.
- [x] Rebuild visual tokens/CSS as one coherent system; restyle cards, chat, settings and forms.
- [x] Inspect real light/dark pages, keyboard behavior, accessibility and the existing frontend regression suite/build.
