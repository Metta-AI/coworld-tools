#!/usr/bin/env bash
# Build the mettagrid_replay_atlas Docker image.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT="$(cd "${HERE}/../.." && pwd)"
IMAGE="${IMAGE:-mettagrid-replay-atlas:latest}"
PLATFORM="${PLATFORM:-linux/amd64}"

exec docker build \
  --platform "${PLATFORM}" \
  -f "${HERE}/Dockerfile" \
  -t "${IMAGE}" \
  "${CONTEXT}" \
  "$@"
