#!/usr/bin/env bash
# Build the synthetic ai-gateway evaluation wrapper without modifying the
# ai-gateway checkout. The wrapper source is copied into a throwaway module
# copy under .evalith/ (gitignored).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
SRC="${AI_GATEWAY_SRC:-$(cd "$ROOT/.." && pwd)/ai-gateway}"
BUILD="${EVALITH_AIGW_BUILD:-$ROOT/.evalith/build/ai-gateway}"
BIN="${EVALITH_AIGW_BIN:-$ROOT/.evalith/bin/ai-gateway-adapter}"

if [[ ! -d "$SRC" ]]; then
  echo "ai-gateway source not found: $SRC" >&2
  exit 1
fi

rm -rf "$BUILD"
mkdir -p "$(dirname "$BUILD")" "$(dirname "$BIN")"
cp -R "$SRC" "$BUILD"
rm -rf "$BUILD/.git"
mkdir -p "$BUILD/cmd/eval-adapter"
cp "$HERE/main.go" "$BUILD/cmd/eval-adapter/main.go"

cd "$BUILD"
go get gorm.io/driver/sqlite@v1.6.0 >/dev/null
go build -o "$BIN" ./cmd/eval-adapter
echo "$BIN"
