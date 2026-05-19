#!/usr/bin/env bash
# Build the Among Them ``ivotewell`` starter player image and emit Coworld
# manifest artifacts. See ``docs/coworld-player-packaging.md`` for the full
# contract.
#
# This leaf is special: the Nim source imports framework modules
# (``../../sim``, ``../../texts``, ``../../votereader``,
# ``../../../common/server``) plus assets and ``nimby.lock``/``nim.cfg``
# from the BitWorld monorepo. The build context therefore has to be a
# BitWorld checkout, with this repo's ``ivotewell.nim`` overlaid on top so
# the image always contains the freshest in-repo player source.
#
# Resolution order for the BitWorld checkout:
#   1. ``$BITWORLD_ROOT`` env var (highest priority).
#   2. Sibling ``../bitworld`` next to this players repo.
#   3. ``$HOME/coding/bitworld``.
set -euo pipefail

SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
POLICY_DIR="$SCRIPT_DIR"
export POLICY_DIR

# Resolve a BitWorld checkout before sourcing the lib so we can short-circuit
# on a clear error rather than letting docker fail downstream.
_resolve_bitworld_root() {
    if [[ -n "${BITWORLD_ROOT:-}" ]]; then
        printf "%s" "$BITWORLD_ROOT"
        return 0
    fi
    for cand in "$REPO_ROOT/../bitworld" "$HOME/coding/bitworld"; do
        if [[ -f "$cand/nimby.lock" && -d "$cand/among_them" ]]; then
            (cd "$cand" && pwd)
            return 0
        fi
    done
    return 1
}

if ! BITWORLD_ROOT="$(_resolve_bitworld_root)"; then
    cat <<EOF >&2
players/among_them/starter/build.sh: BitWorld checkout not found.

The ivotewell starter is a Nim policy that imports framework modules from
the BitWorld monorepo (../../sim, ../../texts, ../../votereader,
../../../common/server) and depends on its nimby.lock and nim.cfg. To build
the player image, point BITWORLD_ROOT at a BitWorld checkout:

    BITWORLD_ROOT=/path/to/bitworld $0 [...]

or clone BitWorld next to this players repo (../bitworld) or to
~/coding/bitworld.

This script overlays this repo's players/among_them/starter/ivotewell.nim
on top of the BitWorld build context, so the image always contains the
freshest in-repo player source.
EOF
    exit 1
fi

source "$REPO_ROOT/tools/players_build/build_lib.sh"

# Override _build_image so we can pass --build-context player=<leaf dir>;
# the Dockerfile uses ``COPY --from=player ivotewell.nim ...`` to overlay
# the in-repo Nim source on top of the BitWorld build context.
_build_image() {
    local tag="$1"
    _have docker || _die "docker not found on PATH"
    docker buildx build \
        --platform=linux/amd64 \
        --load \
        -f "$DOCKERFILE" \
        --build-context "player=$POLICY_DIR" \
        -t "$tag" \
        "$BUILD_CONTEXT"
}

PLAYER_ID="among-them-starter"
PLAYER_NAME="Among Them Starter (ivotewell)"
PLAYER_DESCRIPTION="Nim screen-reading starter policy for the BitWorld Among Them Coworld."
PLAYER_GAMES_JSON='["among_them"]'
PLAYER_AUTHOR="treeform@softmax.com"
IMAGE_LOCAL_TAG="among-them-starter:dev"
IMAGE_PUBLIC_URI="ghcr.io/treeform/bitworld-ivotewell:latest"
DOCKERFILE="$POLICY_DIR/Dockerfile"
BUILD_CONTEXT="$BITWORLD_ROOT"
PLAYER_ENV_JSON='{}'
PLAYER_RUN_JSON='null'

run_player_build "$@"
