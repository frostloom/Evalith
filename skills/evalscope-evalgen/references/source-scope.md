# Source and knowledge-base scope

## User-selected scope

Always start from an explicit user selection:

- `--root` — project root; must be an existing directory;
- `--include` — one or more relative files/directories; omit means the root;
- `--knowledge-dir` — one or more document directories or files under the root;
  the scanner adds them to the walk automatically and marks their files
  `knowledge: true`;
- `--knowledge-share` — share of the file/char budget reserved for knowledge
  (default 0.5 when knowledge is present);
- `--exclude` — additional fnmatch patterns.

Never scan outside `--root`. Reject absolute paths, `..`, and symlink escapes.
The project root itself must not be a symlink. External knowledge bases must be
copied or mounted under the root; they are not read directly.

## Default excludes

`.git`, `node_modules`, `.venv`, `venv`, `dist`, `build`, `.next`, `__pycache__`,
`.idea`, `.vscode`, `target`, `vendor`, `.pytest_cache`, `.mypy_cache`,
`.ruff_cache`, `coverage`, `.evalith`, `artifacts`, `outputs`.

## Hard sensitive denylist (cannot be overridden)

Directories: `.ssh`, `.aws`, `.gnupg`, `.docker`, `secrets*`.

Files: `.env`, `.env.*`, `*.env`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.kdbx`,
`id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `credentials*`, `.npmrc`, `.pypirc`,
`.netrc`.

The scanner records a rejected sensitive path and never reads it. Do not ask the
agent to read these files directly.

## Limits

| Item | Default |
|---|---|
| Files per snapshot | 400 |
| SHA-256 per file | up to 8 MB |
| File content sent as excerpt | 512 KB |
| Total excerpt budget | 120,000 chars |
| Per-file excerpt | 8,000 chars |
| Binary | fingerprint only |

For a 50-task set the default budget gives about 2,400 characters per task; raise
`--max-total-chars` for a large repository and re-scan. With a knowledge base the
budget is split 50/50 by default (`--knowledge-share`), so code and docs both get
context instead of one starving the other. The validator rejects a source
reference to a file that produced no excerpt.

Budgets are configurable; the deny list, symlink rules and read-only behavior
are not.

## Read-only and provenance

- open files read-only; never write, rename, delete or execute;
- do not follow directory symlinks; skip file symlinks;
- record relative path, SHA-256, size, mtime, binary flag, `line_count`,
  whether an excerpt was included, reason if omitted, and redaction count;
- compute a `scope_digest` over sorted `path + sha256` entries;
- redact credential patterns before emitting excerpts and count replacements.
  Redaction covers JSON-quoted keys, snake_case/camelCase keys, Authorization
  headers (any scheme), URL userinfo, AWS/GitHub-style tokens, PGP/private key
  blocks, multi-line block scalars/arrays and secret-bearing file names. A path
  that redacts is rejected rather than emitted.

## Verification (do not skip)

- `scan_sources.py --summary` shows selected files, sent chars, sensitive
  rejects and omitted reasons; show it to the user and confirm before
  generating tasks.
- `validate_eval_set.py --scan --root --strict` checks every `path:line` against
  the scanned `line_count`, every `doc#heading` against scanned headings, and
  rejects a reference to a file that produced no excerpt.
- It also re-hashes the current source files without following symlinks or
  leaving the root; if the source changed after the scan, validation fails.
  Re-scan and regenerate rather than ignoring it.
- Never cite a file, line or heading that is not present in `scan.json`.

## Knowledge base

MVP supports markdown/text under user-selected directories. Chunk by heading,
keep a `doc#heading` reference, and only use relevant chunks when drafting
tasks. A knowledge dir that yields no supported files fails the scan instead of
silently producing an empty KB. Do not index PDFs/Office files or build a vector
database in this skill.

## What the agent may see

The agent may read `scan.json` only. Do not use the coding agent's file-reading
tools on the project directly: the scanner is the enforcement boundary. If more
context is needed, re-run the scanner with a narrower include path or a larger
budget and ask the user first.
