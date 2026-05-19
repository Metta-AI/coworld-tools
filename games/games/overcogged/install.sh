#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
METTA_REPO_URL="${METTA_REPO_URL:-https://github.com/Metta-AI/metta.git}"
METTA_REF="${METTA_REF:-main}"
METTA_CLONE_DIR="${METTA_CLONE_DIR:-$REPO_ROOT/.branch-installs/metta}"

if command -v uv >/dev/null 2>&1; then
  installer=(uv pip install --upgrade)
else
  installer=(python -m pip install --upgrade)
fi

if [[ -d "$METTA_CLONE_DIR" ]]; then
  chmod -R u+w "$METTA_CLONE_DIR"
  rm -rf "$METTA_CLONE_DIR"
fi
git clone --depth 1 --branch "$METTA_REF" --single-branch "$METTA_REPO_URL" "$METTA_CLONE_DIR"

"${installer[@]}" --editable "$METTA_CLONE_DIR"
"${installer[@]}" --no-deps "$REPO_ROOT"
