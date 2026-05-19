#!/usr/bin/env bash
# Build mettascope to WebAssembly.
# Requires: emsdk (emscripten), nim
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MS_SRC="$REPO_ROOT/.mettagrid/nim/mettascope"

if [ ! -d "$MS_SRC" ]; then
  echo "ERROR: $MS_SRC not found."
  exit 1
fi

# Activate emsdk if available.
EMSDK="${EMSDK:-$HOME/code/emsdk}"
if [ -f "$EMSDK/emsdk_env.sh" ]; then
  source "$EMSDK/emsdk_env.sh" 2>/dev/null
fi

if ! command -v emcc >/dev/null 2>&1; then
  echo "ERROR: emcc not found. Install emsdk and source emsdk_env.sh"
  exit 1
fi

if [ -d "$HOME/.nimby/nim/bin" ]; then
  export PATH="$HOME/.nimby/nim/bin:$PATH"
fi

echo "[build-wasm] compiling mettascope to WASM..."
cd "$MS_SRC"
nim c -d:emscripten -d:release src/mettascope.nim

echo "[build-wasm] output:"
ls -lh dist/
echo "[build-wasm] done. Serve with: cogony play --web"
