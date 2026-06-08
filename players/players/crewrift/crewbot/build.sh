#!/usr/bin/env bash
# Build the Crewbot player image and emit Coworld manifest artifacts.
set -euo pipefail

SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
POLICY_DIR="$SCRIPT_DIR"
export POLICY_DIR

source "$REPO_ROOT/tools/players_build/build_lib.sh"

PLAYER_ID="crewbot"
PLAYER_NAME="Crewbot"
PLAYER_DESCRIPTION="Crewbot starter policy with evidence voting and a bounded Bedrock/Anthropic meeting LLM."
PLAYER_GAMES_JSON='["crewrift"]'
PLAYER_AUTHOR="relh@softmax.com"
IMAGE_LOCAL_TAG="players-crewbot:dev"
IMAGE_PUBLIC_URI="ghcr.io/metta-ai/players-crewbot:latest"
DOCKERFILE="$POLICY_DIR/Dockerfile"
BUILD_CONTEXT="$REPO_ROOT"
PLAYER_ENV_JSON='{}'
PLAYER_RUN_JSON='null'

run_player_build "$@"
