#!/usr/bin/env sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
"$repo_root/commissioners/build_image.sh" ruleset_strategy ghcr.io/metta-ai/commissioners-ruleset-strategy:latest "${1:-default}"
