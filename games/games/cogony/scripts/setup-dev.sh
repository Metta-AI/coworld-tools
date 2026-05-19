#!/usr/bin/env bash
# Set up the cogony dev environment from the local .mettagrid checkout.
# This installs mettagrid from source, rebuilds C++ and mettascope.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MG="$REPO_ROOT/.mettagrid"

if [ ! -d "$MG" ]; then
  echo "ERROR: $MG not found."
  exit 1
fi

# Pull LFS (sprites are stored as LFS).
echo "[setup] pulling LFS files..."
(cd "$MG" && git lfs pull 2>/dev/null || true)

# Install mettagrid as editable from source.
echo "[setup] installing mettagrid from $MG (editable)..."
uv pip install setuptools 2>/dev/null || true
uv pip install -e "$MG" --no-build-isolation

# Build C++ extension.
if command -v bazel >/dev/null 2>&1; then
  echo "[setup] building mettagrid_c.so..."
  (cd "$MG" && bazel build //cpp:mettagrid_c)
  VENV_MG="$REPO_ROOT/.venv/lib/python3.12/site-packages/mettagrid"
  cp "$MG/bazel-bin/cpp/mettagrid_c.so" "$VENV_MG/mettagrid_c.so"
  codesign --force --sign - "$VENV_MG/mettagrid_c.so" 2>/dev/null || true
fi

# Build mettascope.
MS="$MG/nim/mettascope"
VENV_MS="$REPO_ROOT/.venv/lib/python3.12/site-packages/mettagrid/nim/mettascope"

if [ -d "$HOME/.nimby/nim/bin" ]; then
  export PATH="$HOME/.nimby/nim/bin:$PATH"
fi

if command -v nim >/dev/null 2>&1; then
  # Ensure nim.cfg exists.
  if [ ! -f "$MS/nim.cfg" ]; then
    echo "# nimby paths" > "$MS/nim.cfg"
    for pkg in "$HOME"/.nimby/pkgs/*/src; do
      echo "--path:\"$pkg\"" >> "$MS/nim.cfg"
    done
    for pkg in "$HOME"/.nimby/pkgs/cligen "$HOME"/.nimby/pkgs/libcurl; do
      [ -d "$pkg" ] && echo "--path:\"$pkg\"" >> "$MS/nim.cfg"
    done
  fi

  echo "[setup] building libmettascope.dylib..."
  (cd "$MS" && nim c -d:release --app:lib \
    --out:libmettascope.dylib \
    --outdir:bindings/generated \
    bindings/bindings.nim)

  # Post-process cstring -> c_char_p.
  python3 -c "
from pathlib import Path
p = Path('$MS/bindings/generated/mettascope.py')
t = p.read_text()
f = t.replace('cstring)', 'c_char_p)')
if f != t: p.write_text(f)
"

  cp "$MS/bindings/generated/libmettascope.dylib" "$VENV_MS/bindings/generated/"
  cp "$MS/bindings/generated/mettascope.py" "$VENV_MS/bindings/generated/"
  rsync -a --delete "$MS/src/" "$VENV_MS/src/"
  rsync -a "$MS/data/" "$VENV_MS/data/"
  echo "[setup] mettascope deployed."
fi

# Reinstall cogony + cogony-policy.
uv pip install -e "$REPO_ROOT" --no-build-isolation 2>/dev/null || true
uv pip install -e "$REPO_ROOT/policies/baseline" --no-build-isolation 2>/dev/null || true

echo "[setup] done. Run: uv run --no-sync cogony play --policy baseline"
