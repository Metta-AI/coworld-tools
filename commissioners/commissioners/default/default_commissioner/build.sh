#!/usr/bin/env sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)"
docker build \
  -f "$repo_root/commissioners/default/default_commissioner/Dockerfile" \
  -t ghcr.io/metta-ai/commissioners-default:latest \
  "$repo_root"
