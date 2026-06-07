#!/usr/bin/env sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)"
"$repo_root/commissioners/build_image.sh" cogs_vs_clips ghcr.io/metta-ai/commissioners-cogs-vs-clips:latest
