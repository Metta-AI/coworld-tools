#!/usr/bin/env bash
# Wrapper around tools/bake_assets.nim. Sets the --path: flags Nim
# needs to import the upstream bitworld modules, and forwards
# BITWORLD_DIR (default: ~/coding/bitworld) into the tool.
#
# Run from anywhere — paths are resolved from this script's own
# location, not cwd.

set -euo pipefail

BITWORLD_DIR="${BITWORLD_DIR:-$HOME/coding/bitworld}"

if [[ ! -d "$BITWORLD_DIR" ]]; then
  echo "FATAL: BITWORLD_DIR=$BITWORLD_DIR does not exist." >&2
  echo "Set BITWORLD_DIR to your bitworld checkout root." >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Honor a nimby checkout if present. The upstream bitworld checkout
# uses nimby (see ~/.nimby/pkgs and bitworld/nim.cfg); we forward the
# minimum set of --path:s our imports need (pixie + zippy transitively
# through bitworld/aseprite and bitworld/common/pixelfonts).
NIMBY_PKGS="${NIMBY_PKGS:-$HOME/.nimby/pkgs}"
NIMBY_PATHS=()
for pkg in pixie chroma zippy bumpy vmath nimsimd flatty crunchy supersnappy; do
  if [[ -d "$NIMBY_PKGS/$pkg/src" ]]; then
    NIMBY_PATHS+=(--path:"$NIMBY_PKGS/$pkg/src")
  fi
done
if [[ ${#NIMBY_PATHS[@]} -eq 0 ]]; then
  echo "FATAL: no nimby packages found at $NIMBY_PKGS." >&2
  echo "Install nimby and run 'nimby install' inside $BITWORLD_DIR first." >&2
  exit 2
fi

export BITWORLD_DIR

exec nim r \
  --threads:on --mm:orc -d:release \
  --path:"$BITWORLD_DIR/src" \
  --path:"$BITWORLD_DIR" \
  --path:"$BITWORLD_DIR/common" \
  "${NIMBY_PATHS[@]}" \
  "$HERE/bake_assets.nim"
