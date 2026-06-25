#!/usr/bin/env bash
# Rebuild mettascope (Nim) AND the mettagrid C++ extension from the
# .mettagrid/ checkout and overlay them onto the installed mettagrid package.
#
# Run after editing:
#   .mettagrid/nim/mettascope/src/        (Nim UI)
#   .mettagrid/cpp/                       (engine C++)
#   .mettagrid/python/src/mettagrid/      (engine Python)
#
# First-time setup (once per clone): `nimby install` to fetch Nim deps into
# .mettagrid/nim/mettascope/; they are not committed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MS_SRC="$REPO_ROOT/.mettagrid/nim/mettascope"
VENV_MS="$REPO_ROOT/.venv/lib/python3.12/site-packages/mettagrid/nim/mettascope"

if [ ! -d "$MS_SRC" ]; then
  echo "ERROR: $MS_SRC not found. Clone with:"
  echo "  git clone --filter=blob:none https://github.com/Metta-AI/daveey-mettagrid-cogony.git .mettagrid"
  echo "  (cd .mettagrid && git checkout cogony)"
  exit 1
fi
if [ ! -d "$VENV_MS" ]; then
  echo "ERROR: $VENV_MS not found. Run 'uv sync' first."
  exit 1
fi

# Add nimby's nim bin dir to PATH if present.
if [ -d "$HOME/.nimby/nim/bin" ]; then
  export PATH="$HOME/.nimby/nim/bin:$PATH"
fi
if ! command -v nim >/dev/null 2>&1; then
  echo "ERROR: nim not on PATH. Install Nim 2.2.x."
  exit 1
fi

cd "$MS_SRC"

# Ensure deps are installed (nimby populates ./<pkg>/src dirs referenced by nim.cfg).
if [ ! -f nim.cfg ] || [ ! -d fidget2 ]; then
  echo "[build-mettascope] running 'nimby install' to populate Nim deps…"
  if ! command -v nimby >/dev/null 2>&1; then
    echo "ERROR: nimby not on PATH. Install via 'nim' setup."
    exit 1
  fi
  nimby install
fi

echo "[build-mettascope] compiling libmettascope.dylib…"
# Note: the upstream nimble task passes --tlsEmulation:off, but that produces
# a dylib that hangs on ctypes load with Nim 2.2.6 on macOS ARM64. Dropping
# the flag (letting Nim choose native TLS) produces a working dylib.
nim c -d:release --app:lib \
  --out:libmettascope.dylib \
  --outdir:bindings/generated \
  bindings/bindings.nim

# Post-process generated Python binding: cstring -> c_char_p (matches the
# nimble task's sed step).
python3 - <<'PY'
from pathlib import Path
p = Path("bindings/generated/mettascope.py")
text = p.read_text()
fixed = text.replace("cstring)", "c_char_p)")
if fixed != text:
    p.write_text(fixed)
    print("[build-mettascope] post-processed mettascope.py")
PY

overlay_mettascope() {
  echo "[build-mettascope] overlaying onto $VENV_MS/"
  mkdir -p "$VENV_MS/bindings/generated"
  cp "$MS_SRC/bindings/generated/libmettascope.dylib" "$VENV_MS/bindings/generated/"
  cp "$MS_SRC/bindings/generated/mettascope.py" "$VENV_MS/bindings/generated/"
  rsync -a --delete "$MS_SRC/src/" "$VENV_MS/src/"
  rsync -a "$MS_SRC/data/" "$VENV_MS/data/"  # No --delete: venv may have extra sprites
}

overlay_mettascope
echo "[build-mettascope] done with Nim."

# --- mettagrid: install from local source -----------------------------------
MG_SRC="$REPO_ROOT/.mettagrid"
VENV_MG="$REPO_ROOT/.venv/lib/python3.12/site-packages/mettagrid"

# Pull LFS files (sprites are stored as LFS in .mettagrid).
(cd "$MG_SRC" && git lfs pull 2>/dev/null || true)

# Install mettagrid from local source (Python + data).
echo "[build-mettagrid] installing mettagrid from $MG_SRC …"
uv pip install setuptools 2>/dev/null
uv pip install "$MG_SRC" --no-build-isolation --quiet

# Installing mettagrid refreshes the vendored mettascope package, so re-apply
# the just-built dylib and Nim sources afterwards.
overlay_mettascope

# Build and overlay the custom C++ extension.
if [ -f "$MG_SRC/BUILD.bazel" ] && command -v bazel >/dev/null 2>&1; then
  echo "[build-mettagrid] compiling cpp:mettagrid_c …"
  (cd "$MG_SRC" && bazel build //cpp:mettagrid_c)
  cp "$MG_SRC/bazel-bin/cpp/mettagrid_c.so" "$VENV_MG/"
  codesign --force --sign - "$VENV_MG/mettagrid_c.so" 2>/dev/null || true
  echo "[build-mettagrid] overlaid mettagrid_c.so into venv"
else
  echo "[build-mettagrid] skipped (bazel not found or $MG_SRC missing)"
fi

echo "[build-mettascope] done. Re-run 'uv run cogony play --render gui' to pick up the rebuild."
