#!/usr/bin/env bash
# Build the paint_arena_summarizer Docker image.
#
# Build context is `reporters/` (this script's parent's parent) so the
# Dockerfile can COPY both the shared reporter_sdk/ and this reporter's
# source from a single context.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT="$(cd "${HERE}/../.." && pwd)"
IMAGE="${IMAGE:-paint-arena-summarizer:latest}"

exec docker build \
  -f "${HERE}/Dockerfile" \
  -t "${IMAGE}" \
  "${CONTEXT}" \
  "$@"
