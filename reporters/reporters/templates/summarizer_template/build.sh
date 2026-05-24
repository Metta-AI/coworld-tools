#!/usr/bin/env bash
# Build the summarizer_template Docker image.
#
# Build context is `reporters/` (this script's parent's parent's parent) so
# the Dockerfile can COPY both the shared reporter_sdk/ and the template's
# source from a single context.
#
# Defaults to --platform linux/amd64 to match the concrete reporters' build
# pattern (their images run on amd64 in production). The template is not
# published to a registry; the smoke test consumes the local image tag
# directly.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT="$(cd "${HERE}/../.." && pwd)"
IMAGE="${IMAGE:-summarizer-template:latest}"
PLATFORM="${PLATFORM:-linux/amd64}"

exec docker build \
  --platform "${PLATFORM}" \
  -f "${HERE}/Dockerfile" \
  -t "${IMAGE}" \
  "${CONTEXT}" \
  "$@"
