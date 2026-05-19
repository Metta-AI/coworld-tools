#!/usr/bin/env bash
# CI gate for nim check - ensures dependencies are synced before checking
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Ensure nimby is available
if ! command -v nimby >/dev/null 2>&1; then
    echo "Error: nimby not found. Install via: python -c 'from tribal_village_env.build import _ensure_nim_toolchain; _ensure_nim_toolchain()'"
    exit 1
fi

# Ensure nim is available
if ! command -v nim >/dev/null 2>&1; then
    echo "Error: nim not found. Run: nimby use 2.2.6"
    exit 1
fi

# Sync dependencies from lockfile
echo "==> Syncing Nim dependencies..."
nimby sync -g nimby.lock

# Run nim check on the main entry point
echo "==> Running nim check..."
nim check src/agent_control.nim

echo "==> nim check passed"
