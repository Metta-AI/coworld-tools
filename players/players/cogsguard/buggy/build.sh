#!/usr/bin/env bash
# Build the CogsGuard buggy player image and emit Coworld manifest artifacts.
# See ``docs/coworld-player-packaging.md`` for the full contract.
set -euo pipefail

SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
POLICY_DIR="$SCRIPT_DIR"
export POLICY_DIR

source "$REPO_ROOT/tools/players_build/build_lib.sh"

PLAYER_ID="cogsguard-buggy"
PLAYER_NAME="CogsGuard Buggy"
PLAYER_DESCRIPTION="Goal-tree scripted policy (Planky fork) for the cogs_vs_clips Coworld."
PLAYER_GAMES_JSON='["cogs_vs_clips"]'
PLAYER_AUTHOR="players@softmax.com"
IMAGE_LOCAL_TAG="players-cogsguard-buggy:dev"
IMAGE_PUBLIC_URI="ghcr.io/metta-ai/players-cogsguard-buggy:latest"
DOCKERFILE="$POLICY_DIR/Dockerfile"
BUILD_CONTEXT="$REPO_ROOT"
PLAYER_ENV_JSON='{"COGAMES_POLICY_URI": "metta://policy/buggy"}'
PLAYER_RUN_JSON='null'

run_player_build "$@"
