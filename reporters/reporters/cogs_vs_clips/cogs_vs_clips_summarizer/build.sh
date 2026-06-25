#!/usr/bin/env bash
# Build the cogs_vs_clips_summarizer Docker image.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT="$(cd "${HERE}/../.." && pwd)"
IMAGE="${IMAGE:-cogs-vs-clips-summarizer:latest}"
PLATFORM="${PLATFORM:-linux/amd64}"

exec docker build \
  --platform "${PLATFORM}" \
  -f "${HERE}/Dockerfile" \
  -t "${IMAGE}" \
  "${CONTEXT}" \
  "$@"
