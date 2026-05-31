#!/usr/bin/env sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)"
docker build \
  -f "$repo_root/commissioners/cogs_vs_clips/cogs_vs_clips_commissioner/Dockerfile" \
  -t ghcr.io/metta-ai/commissioners-cogs-vs-clips:latest \
  "$repo_root"
