#!/usr/bin/env bash
# Build the CogsGuard Nim-bindings player image and emit Coworld manifest
# artifacts. See ``docs/coworld-player-packaging.md`` for the full contract.
#
# This leaf hosts multiple registered short_names (thinky, nim_random,
# race_car, role_nim, alignall, nlanky). The default policy URI is
# ``metta://policy/thinky``; override per-deployment via the manifest's
# ``env.COGAMES_POLICY_URI``.
#
# Image build downloads the Nim toolchain (~120MB) and compiles the FFI
# bindings; expect a multi-minute first build. Subsequent builds re-use
# Docker's layer cache.
set -euo pipefail

SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
POLICY_DIR="$SCRIPT_DIR"
export POLICY_DIR

source "$REPO_ROOT/tools/players_build/build_lib.sh"

PLAYER_ID="cogsguard-nim"
PLAYER_NAME="CogsGuard Nim"
PLAYER_DESCRIPTION="Nim-bindings scripted policy (Thinky/Nlanky/RaceCar/Cogsguard-nim) for cogs_vs_clips."
PLAYER_GAMES_JSON='["cogs_vs_clips"]'
PLAYER_AUTHOR="players@softmax.com"
IMAGE_LOCAL_TAG="players-cogsguard-nim:dev"
IMAGE_PUBLIC_URI="ghcr.io/metta-ai/players-cogsguard-nim:latest"
DOCKERFILE="$POLICY_DIR/Dockerfile"
BUILD_CONTEXT="$REPO_ROOT"
PLAYER_ENV_JSON='{"COGAMES_POLICY_URI": "metta://policy/thinky"}'
PLAYER_RUN_JSON='null'

run_player_build "$@"
