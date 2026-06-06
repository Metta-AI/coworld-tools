#!/usr/bin/env bash
# Build the Richardborg player image and emit Coworld manifest artifacts.
# Mirrors players/cogsguard/baseline/build.sh; see
# docs/coworld-player-packaging.md for the full contract.
set -euo pipefail

SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
POLICY_DIR="$SCRIPT_DIR"
export POLICY_DIR

source "$REPO_ROOT/tools/players_build/build_lib.sh"

PLAYER_ID="richardborg"
PLAYER_NAME="Richard Borg"
PLAYER_DESCRIPTION="Crewrift LLM meeting agent with canonical observation memory."
PLAYER_GAMES_JSON='["crewrift"]'
PLAYER_AUTHOR="players@softmax.com"
IMAGE_LOCAL_TAG="players-richardborg:dev"
IMAGE_PUBLIC_URI="ghcr.io/metta-ai/players-richardborg:latest"
DOCKERFILE="$POLICY_DIR/coworld/Dockerfile"
BUILD_CONTEXT="$REPO_ROOT"
PLAYER_ENV_JSON='{"RICHARDBORG_LLM_SYSTEM_PROMPT_PATH":"/srv/players/players/crewrift/richardborg/memory/system.md"}'
PLAYER_RUN_JSON='null'

run_player_build "$@"
