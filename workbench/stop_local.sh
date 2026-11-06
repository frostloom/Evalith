#!/usr/bin/env bash
# Stop the local EE-free workbench started by run_local.sh.
# Leaves the PostgreSQL/Redis containers in place unless --volumes is passed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$ROOT/.workbench/pids"

for name in frontend backend worker beat; do
  pid_file="$PID_DIR/$name.pid"
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "[workbench] stopped $name ($pid)"
    fi
    rm -f "$pid_file"
  fi
done

if [[ "${1:-}" == "--volumes" ]]; then
  docker compose -f "$ROOT/compose.deps.yaml" down -v
  echo "[workbench] removed local database/redis volumes"
fi
