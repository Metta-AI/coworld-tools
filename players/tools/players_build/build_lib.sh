# Shared helpers for per-player ``build.sh`` scripts.
#
# Sourced by ``players/<game>/<policy>/build.sh``. Implements the contract in
# ``docs/coworld-player-packaging.md`` §5 so each leaf script can stay short
# and focused on its policy-specific values (image tag, env vars, run argv).
#
# Each consuming script sets these variables before calling ``run_player_build``:
#
#   PLAYER_ID              # unique-within-manifest id, kebab-case
#   PLAYER_NAME            # human-readable name
#   PLAYER_DESCRIPTION     # one-line description
#   PLAYER_GAMES_JSON      # JSON array literal, e.g. '["cogs_vs_clips"]'
#   PLAYER_AUTHOR          # email/handle for the coplayer_manifest.json
#   IMAGE_LOCAL_TAG        # default local image tag (e.g. players-cogsguard-baseline:dev)
#   IMAGE_PUBLIC_URI       # canonical public URI for documentation purposes
#   DOCKERFILE             # absolute path to the Dockerfile
#   BUILD_CONTEXT          # absolute path to the build context (typically repo root)
#   PLAYER_ENV_JSON        # JSON object literal for player[].env; '{}' if none
#   PLAYER_RUN_JSON        # JSON array literal for player[].run, or 'null' to omit
#
# Optional CLI flags accepted by run_player_build:
#
#   --tag <image-ref>      # override IMAGE_LOCAL_TAG
#   --manifest-out <path>  # also write the player[] snippet to <path>
#   --push <registry-ref>  # re-tag image as <registry-ref> and ``docker push``
#   --no-build             # skip ``docker build``; only emit manifests (useful in tests)

set -euo pipefail

_die() { printf "build.sh: %s\n" "$*" >&2; exit 1; }

run_player_build() {
    local image_tag="${IMAGE_LOCAL_TAG:?IMAGE_LOCAL_TAG must be set}"
    local manifest_out=""
    local push_ref=""
    local skip_build=0

    while (( $# )); do
        case "$1" in
            --tag)            image_tag="$2"; shift 2 ;;
            --manifest-out)   manifest_out="$2"; shift 2 ;;
            --push)           push_ref="$2"; shift 2 ;;
            --no-build)       skip_build=1; shift ;;
            -h|--help)        _print_help; return 0 ;;
            *)                _die "unknown argument: $1" ;;
        esac
    done

    : "${PLAYER_ID:?PLAYER_ID must be set}"
    : "${PLAYER_NAME:?PLAYER_NAME must be set}"
    : "${PLAYER_DESCRIPTION:?PLAYER_DESCRIPTION must be set}"
    : "${PLAYER_GAMES_JSON:?PLAYER_GAMES_JSON must be set}"
    : "${PLAYER_AUTHOR:?PLAYER_AUTHOR must be set}"
    : "${IMAGE_PUBLIC_URI:?IMAGE_PUBLIC_URI must be set}"
    : "${DOCKERFILE:?DOCKERFILE must be set}"
    : "${BUILD_CONTEXT:?BUILD_CONTEXT must be set}"
    : "${PLAYER_ENV_JSON:?PLAYER_ENV_JSON must be set}"
    : "${PLAYER_RUN_JSON:?PLAYER_RUN_JSON must be set}"

    if (( ! skip_build )); then
        _build_image "$image_tag"
    fi

    if [[ -n "$push_ref" ]]; then
        _push_image "$image_tag" "$push_ref"
        # When pushed, the manifest snippet should reference the pushed ref.
        image_tag="$push_ref"
    fi

    local dist_dir
    dist_dir="$(_policy_dir)/dist"
    mkdir -p "$dist_dir"

    local snippet
    snippet="$(_render_player_snippet "$image_tag")"
    printf "%s\n" "$snippet"

    if [[ -n "$manifest_out" ]]; then
        printf "%s\n" "$snippet" >"$manifest_out"
    fi

    _render_coplayer_manifest >"$dist_dir/coplayer_manifest.json"
}

_build_image() {
    local tag="$1"
    _have docker || _die "docker not found on PATH"
    docker buildx build \
        --platform=linux/amd64 \
        --load \
        -f "$DOCKERFILE" \
        -t "$tag" \
        "$BUILD_CONTEXT"
}

_push_image() {
    local local_tag="$1" remote_ref="$2"
    docker tag "$local_tag" "$remote_ref"
    docker push "$remote_ref"
}

_render_player_snippet() {
    local image_tag="$1"
    local run_field="$PLAYER_RUN_JSON"
    if [[ "$run_field" == "null" ]]; then
        run_field=""
    fi
    python3 - "$PLAYER_ID" "$PLAYER_NAME" "$PLAYER_DESCRIPTION" "$image_tag" \
            "$PLAYER_ENV_JSON" "$run_field" <<'PY'
import json, sys
player_id, name, description, image, env_json, run_json = sys.argv[1:7]
snippet = {
    "id": player_id,
    "name": name,
    "type": "player",
    "description": description,
    "image": image,
    "env": json.loads(env_json),
}
if run_json:
    snippet["run"] = json.loads(run_json)
print(json.dumps(snippet, indent=2))
PY
}

_render_coplayer_manifest() {
    python3 - "$PLAYER_AUTHOR" "$PLAYER_ID" "$IMAGE_PUBLIC_URI" "$PLAYER_GAMES_JSON" <<'PY'
import json, sys
author, name, image_uri, games_json = sys.argv[1:5]
print(json.dumps({
    "author": author,
    "name": name,
    "image_uri": image_uri,
    "games": json.loads(games_json),
}, indent=2))
PY
}

_policy_dir() {
    # Caller's build.sh must export POLICY_DIR before sourcing; fall back to
    # the directory of BUILD_CONTEXT's caller frame for safety.
    if [[ -n "${POLICY_DIR:-}" ]]; then
        printf "%s" "$POLICY_DIR"
    else
        _die "POLICY_DIR not set; consuming build.sh must export it"
    fi
}

_have() { command -v "$1" >/dev/null 2>&1; }

_print_help() {
    cat <<'EOF'
Usage: build.sh [--tag IMAGE_REF] [--manifest-out PATH] [--push REGISTRY_REF] [--no-build]

Builds a Linux/amd64 Docker image for this player, then emits the
coworld_manifest.json player[] snippet to stdout (and optionally to PATH) and
writes a coplayer_manifest.json into dist/.

  --tag           Override the default local image tag.
  --manifest-out  Also write the player[] JSON snippet to this file.
  --push          Re-tag the built image as this registry reference and push it.
  --no-build      Skip docker build; only render manifests (useful for testing).
EOF
}
