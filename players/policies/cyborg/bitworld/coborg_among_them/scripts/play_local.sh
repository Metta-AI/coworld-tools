#!/usr/bin/env bash
# Convenience wrapper around `uv run coworld play` for local development.
#
# Usage:
#   ./scripts/play_local.sh [IMAGE_TAG]
#
# The script:
#   1. Ensures the Coworld package is downloaded under ${COBORG_AMONG_THEM_COWORLD_DIR}
#      (default: <agent-policies repo>/coworld/among_them/).
#   2. Builds the player image if it doesn't already exist locally.
#   3. Runs `uv run coworld play` with the P0-default flags (120s timeout, no
#      browser, default variant, one image filling all 8 player slots).
#
# Requires: docker (with linux/amd64 support), uv, and a checkout of
# Metta-AI/metta at $METTA_REPO (default: ~/coding/metta).

set -euo pipefail

IMAGE_TAG="${1:-coborg_among_them:dev}"
METTA_REPO="${METTA_REPO:-$HOME/coding/metta}"

repo_root() {
  git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel
}

AGENT_POLICIES_REPO="$(repo_root)"
COBORG_AMONG_THEM_DIR="${AGENT_POLICIES_REPO}/policies/cyborg/bitworld/coborg_among_them"
COWORLD_DIR="${COBORG_AMONG_THEM_COWORLD_DIR:-${AGENT_POLICIES_REPO}/coworld/among_them}"
MANIFEST="${COWORLD_DIR}/coworld_manifest.json"

if [[ ! -f "${MANIFEST}" ]]; then
  mkdir -p "${COWORLD_DIR}"
  (cd "${METTA_REPO}" && uv run coworld download among_them --output-dir "${COWORLD_DIR}")
fi

if ! docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
  docker build --platform linux/amd64 \
    -t "${IMAGE_TAG}" \
    -f "${COBORG_AMONG_THEM_DIR}/coworld/Dockerfile" \
    "${AGENT_POLICIES_REPO}"
fi

cd "${METTA_REPO}"
exec uv run coworld play "${MANIFEST}" \
  --variant default \
  --timeout-seconds 120 \
  --no-open-browser \
  "${IMAGE_TAG}"
