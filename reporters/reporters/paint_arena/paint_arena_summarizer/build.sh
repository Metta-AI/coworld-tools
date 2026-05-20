#!/usr/bin/env bash
# Build the paint_arena_summarizer Docker image.
#
# Build context is `reporters/` (this script's parent's parent) so the
# Dockerfile can COPY both the shared reporter_sdk/ and this reporter's
# source from a single context.
#
# Defaults to --platform linux/amd64 because that's what `coworld upload`
# requires (hosted episodes run on amd64); building for the host arch on
# Apple Silicon would produce an arm64 image that the upload pipeline
# rejects. Override with PLATFORM=linux/arm64 ./build.sh for local-only
# experimentation.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT="$(cd "${HERE}/../.." && pwd)"
IMAGE="${IMAGE:-paint-arena-summarizer:latest}"
PLATFORM="${PLATFORM:-linux/amd64}"

exec docker build \
  --platform "${PLATFORM}" \
  -f "${HERE}/Dockerfile" \
  -t "${IMAGE}" \
  "${CONTEXT}" \
  "$@"
