#!/usr/bin/env bash
# Build the CogsGuard role player image and emit Coworld manifest artifacts.
# See ``docs/coworld-player-packaging.md`` for the full contract.
#
# This leaf hosts multiple registered short_names (role, teacher, wombo,
# cogsguard_v2, cogsguard_control, cogsguard_targeted). The default policy
# URI ``metta://policy/role`` is baked into the image via the Dockerfile
# ENV; the manifest emitted here intentionally leaves env empty so a
# deploy-time misconfiguration cannot silently swap the policy. To deploy
# a non-default short_name, hand-author a manifest entry with
# ``env.COGAMES_POLICY_URI`` set (see README.md "Selecting which
# short_name to deploy").
set -euo pipefail

SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
POLICY_DIR="$SCRIPT_DIR"
export POLICY_DIR

source "$REPO_ROOT/tools/players_build/build_lib.sh"

PLAYER_ID="cogsguard-role"
PLAYER_NAME="CogsGuard Role"
PLAYER_DESCRIPTION="Vibe-based multi-role scripted policy for the cogs_vs_clips Coworld."
PLAYER_GAMES_JSON='["cogs_vs_clips"]'
PLAYER_AUTHOR="players@softmax.com"
IMAGE_LOCAL_TAG="players-cogsguard-role:dev"
IMAGE_PUBLIC_URI="ghcr.io/metta-ai/players-cogsguard-role:latest"
DOCKERFILE="$POLICY_DIR/Dockerfile"
BUILD_CONTEXT="$REPO_ROOT"
PLAYER_ENV_JSON='{}'
PLAYER_RUN_JSON='null'

run_player_build "$@"
