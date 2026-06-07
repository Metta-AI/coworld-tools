#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <commissioner-key> <image-tag>" >&2
  exit 2
fi

commissioner_key="$1"
image_tag="$2"
repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

docker build \
  -f "$repo_root/commissioners/Dockerfile" \
  --build-arg "COMMISSIONER_KEY=$commissioner_key" \
  -t "$image_tag" \
  "$repo_root"
