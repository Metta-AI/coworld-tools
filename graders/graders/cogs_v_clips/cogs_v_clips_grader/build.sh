#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-cogs-v-clips-grader:latest}"
PLATFORM="${PLATFORM:-linux/amd64}"

exec docker build \
  --platform "${PLATFORM}" \
  -f "${HERE}/Dockerfile" \
  -t "${IMAGE}" \
  "${HERE}" \
  "$@"
