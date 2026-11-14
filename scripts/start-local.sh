#!/usr/bin/env bash
# Single host process; data, dependency caches and logs stay in this checkout.
set -euo pipefail
EVALITH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$EVALITH_ROOT"
if [[ -f "$EVALITH_ROOT/.evalith/local.env" ]]; then
  # Optional, user-owned local paths and non-secret build settings.
  source "$EVALITH_ROOT/.evalith/local.env"
fi
export EVALITH_DATA_DIR="${EVALITH_DATA_DIR:-$EVALITH_ROOT/.evalith/app}"
export EVALITH_API_PORT="${EVALITH_API_PORT:-8093}"
export UV_CACHE_DIR="$EVALITH_ROOT/.evalith/cache/uv"
export npm_config_cache="$EVALITH_ROOT/.evalith/cache/npm"
export TMPDIR="$EVALITH_ROOT/.evalith/tmp/startup"
mkdir -p "$TMPDIR" "$EVALITH_DATA_DIR"
# Pick a locally installed compatible SDK without changing xcode-select or Go's
# global configuration. Some hosts have a newer SDK than the system linker.
if [[ "$(uname -s)" == Darwin && -z "${EVALITH_GO_SDKROOT:-}" ]] && command -v clang >/dev/null; then
  printf 'int main(void) { return 0; }\n' > "$TMPDIR/sdk-probe.c"
  while IFS= read -r EVALITH_SDK; do
    if SDKROOT="$EVALITH_SDK" clang "$TMPDIR/sdk-probe.c" -o "$TMPDIR/sdk-probe" > "$TMPDIR/sdk-probe.log" 2>&1; then
      export EVALITH_GO_SDKROOT="$EVALITH_SDK"
      break
    fi
  done < <(python3 - <<'PY'
from pathlib import Path
import re
paths=Path('/Library/Developer/CommandLineTools/SDKs').glob('MacOSX[0-9]*.sdk')
for p in sorted(paths,key=lambda p:tuple(int(n) for n in re.findall(r'\d+',p.name)),reverse=True):
    if not p.is_symlink():print(p)
PY
)
fi
uv sync --project evalith --frozen
if [[ ! -d evalith/web/node_modules ]]; then npm --prefix evalith/web ci; fi
npm --prefix evalith/web run build
printf 'Evalith: http://127.0.0.1:%s\n' "$EVALITH_API_PORT"
exec uv run --project evalith python -m evalith --port "$EVALITH_API_PORT"
