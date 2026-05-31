#!/usr/bin/env sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)"
docker build \
  -f "$repo_root/commissioners/among_them/among_them_commissioner/Dockerfile" \
  -t ghcr.io/metta-ai/commissioners-among-them-commissioner:latest \
  "$repo_root"
