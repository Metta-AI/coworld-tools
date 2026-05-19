#!/usr/bin/env bash
set -euo pipefail

NAME="${1:-daveey.cvc_policy}"
SEASON="${2:-beta-cvc}"

cogames upload \
  -p "class=cvc_policy.cogamer_policy.CvCPolicy" \
  -n "$NAME" \
  --season "$SEASON" \
  --setup-script setup_policy.py \
  --include-files src/cvc_policy \
  --use-bedrock \
  --skip-validation
