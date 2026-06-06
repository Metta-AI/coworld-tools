#!/usr/bin/env bash
# Build the RichardNotsus player image and emit Coworld manifest artifacts.
set -euo pipefail

SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
POLICY_DIR="$SCRIPT_DIR"
export POLICY_DIR

source "$REPO_ROOT/tools/players_build/build_lib.sh"

PLAYER_ID="richardnotsus"
PLAYER_NAME="RichardNotsus"
PLAYER_DESCRIPTION="Notsus Crewrift baseline with a bounded Bedrock/Anthropic meeting LLM."
PLAYER_GAMES_JSON='["crewrift"]'
PLAYER_AUTHOR="relh@softmax.com"
IMAGE_LOCAL_TAG="players-richardnotsus:dev"
IMAGE_PUBLIC_URI="ghcr.io/metta-ai/players-richardnotsus:latest"
DOCKERFILE="$POLICY_DIR/Dockerfile"
BUILD_CONTEXT="$REPO_ROOT"
PLAYER_ENV_JSON='{}'
PLAYER_RUN_JSON='null'

run_player_build "$@"
