#!/usr/bin/env sh
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: $0 <commissioner-key> <image-tag> [config-driven-config-name]" >&2
  exit 2
fi

commissioner_key="$1"
image_tag="$2"
config_driven_config_name="${3:-default}"
repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

docker build \
  -f "$repo_root/commissioners/Dockerfile" \
  --build-arg "COMMISSIONER_KEY=$commissioner_key" \
  --build-arg "CONFIG_DRIVEN_CONFIG_NAME=$config_driven_config_name" \
  -t "$image_tag" \
  "$repo_root"
