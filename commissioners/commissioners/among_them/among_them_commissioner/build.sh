#!/usr/bin/env sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)"
"$repo_root/commissioners/build_image.sh" among_them ghcr.io/metta-ai/commissioners-among-them-commissioner:latest
