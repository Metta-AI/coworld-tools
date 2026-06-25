#!/usr/bin/env bash
# Build the coborg Among Them player image and emit Coworld manifest artifacts.
# See ``docs/coworld-player-packaging.md`` for the full contract.
#
# Among Them speaks the binary ``bitscreen_v1`` wire protocol (NOT
# ``coworld.player.v1``); this leaf therefore does not use the SDK's
# coworld_json_bridge. Its websocket bridge lives in
# ``coworld/policy_player.py`` and the image's CMD invokes it directly.
set -euo pipefail

SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
POLICY_DIR="$SCRIPT_DIR"
export POLICY_DIR

source "$REPO_ROOT/tools/players_build/build_lib.sh"

PLAYER_ID="among-them-coborg"
PLAYER_NAME="Coborg Among Them"
PLAYER_DESCRIPTION="Pixel-perception coborg agent for the BitWorld Among Them Coworld."
PLAYER_GAMES_JSON='["among_them"]'
PLAYER_AUTHOR="players@softmax.com"
IMAGE_LOCAL_TAG="coborg-among-them:dev"
IMAGE_PUBLIC_URI="ghcr.io/metta-ai/coborg-among-them:latest"
DOCKERFILE="$POLICY_DIR/coworld/Dockerfile"
BUILD_CONTEXT="$REPO_ROOT"
PLAYER_ENV_JSON='{}'
PLAYER_RUN_JSON='null'

run_player_build "$@"
