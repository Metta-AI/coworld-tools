#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
METTA_REPO_URL="${METTA_REPO_URL:-https://github.com/Metta-AI/metta.git}"
METTA_REF="${METTA_REF:-relh/werewolf-single-pr}"
METTA_CLONE_PARENT="${METTA_CLONE_PARENT:-$REPO_ROOT/.branch-installs}"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to install Werecog" >&2
  exit 1
fi

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  uv venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

mkdir -p "$METTA_CLONE_PARENT"
if [[ -n "${METTA_CLONE_DIR:-}" ]]; then
  rm -rf "$METTA_CLONE_DIR"
else
  METTA_CLONE_DIR="$(mktemp -d "$METTA_CLONE_PARENT/metta.XXXXXX")"
fi

git clone --depth 1 --branch "$METTA_REF" --single-branch "$METTA_REPO_URL" "$METTA_CLONE_DIR"

UV_TORCH_BACKEND="${UV_TORCH_BACKEND:-cpu}" \
  uv sync --active --project "$METTA_CLONE_DIR" --extra werecog --no-group interactive --no-group dev --frozen
uv pip install --python "$VIRTUAL_ENV/bin/python" --no-deps --editable "$REPO_ROOT"
