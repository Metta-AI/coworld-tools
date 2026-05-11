#!/usr/bin/env bash
#
# Convenience wrapper for validating and shipping guided_bot to a
# cogames Among Them season.
#
# Usage:
#   export SEASON=among-them
#   export POLICY_NAME=$USER-guided-bot-$(date +%Y%m%d-%H%M%S)
#   ./ship.sh dry-run
#   ./ship.sh ship                  # if dry-run passes
#   ./ship.sh ship-skip-validation  # if dry-run only hits the no-op gate
#
# LLM note: guided_bot prefers AWS Bedrock when available. `cogames upload`
# supports `--use-bedrock`; current `cogames ship` does not expose the LLM
# credential flags, so this wrapper uses `upload --season` for real ships.
# `ANTHROPIC_API_KEY` remains a direct Anthropic fallback when Bedrock is
# explicitly disabled.
#
# Always runs from the repo root (personal_cogs/) so relative -f paths
# resolve against the workshop layout.

set -euo pipefail

CMD="${1:-dry-run}"
SEASON="${SEASON:-}"
POLICY_NAME="${POLICY_NAME:-$USER-guided-bot-$(date +%Y%m%d-%H%M%S)}"
ANTHROPIC_KEY="${ANTHROPIC_API_KEY:-}"
USE_BEDROCK_FLAG="${USE_BEDROCK:-${CLAUDE_CODE_USE_BEDROCK:-1}}"
DEFAULT_BEDROCK_MODEL="global.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_ANTHROPIC_MODEL="claude-sonnet-4-20250514"

if [[ -z "$SEASON" ]]; then
    echo "ERROR: SEASON is required. Run 'cogames season list' to find an active Among Them season." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# cogames/ -> guided_bot/ -> among_them/ -> personal_cogs/
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

cd "$REPO_ROOT"

if [[ -x "$REPO_ROOT/.venv/bin/cogames" ]]; then
    COGAMES_BIN="${COGAMES_BIN:-$REPO_ROOT/.venv/bin/cogames}"
else
    COGAMES_BIN="${COGAMES_BIN:-cogames}"
fi

INCLUDES=(
    -f among_them/guided_bot/cogames/amongthem_policy.py
    -f among_them/guided_bot
    -f among_them/common/perception_kernels
)

SECRETS=()
LLM_ARGS=()
case "${USE_BEDROCK_FLAG,,}" in
    0|false|no|off)
        if [[ -n "$ANTHROPIC_KEY" ]]; then
            ANTHROPIC_MODEL="${GUIDED_BOT_LLM_MODEL:-${GUIDED_BOT_ANTHROPIC_MODEL:-${ANTHROPIC_MODEL:-$DEFAULT_ANTHROPIC_MODEL}}}"
            LLM_ARGS+=(--llm-provider anthropic --llm-credentials user --llm-model "$ANTHROPIC_MODEL")
            SECRETS+=(--secret-env "ANTHROPIC_API_KEY=$ANTHROPIC_KEY")
        fi
        ;;
    *)
        BEDROCK_MODEL="${COGAMES_LLM_MODEL:-${GUIDED_BOT_LLM_MODEL:-${GUIDED_BOT_BEDROCK_MODEL:-$DEFAULT_BEDROCK_MODEL}}}"
        LLM_ARGS+=(--use-bedrock --llm-model "$BEDROCK_MODEL")
        if [[ -z "${GUIDED_BOT_LLM_MODEL:-}" && -z "${GUIDED_BOT_BEDROCK_MODEL:-}" ]]; then
            SECRETS+=(--secret-env "GUIDED_BOT_BEDROCK_MODEL=$BEDROCK_MODEL")
        fi
        ;;
esac
for key in GUIDED_BOT_LLM_MODEL GUIDED_BOT_BEDROCK_MODEL GUIDED_BOT_ANTHROPIC_MODEL; do
    if [[ -n "${!key:-}" ]]; then
        SECRETS+=(--secret-env "$key=${!key}")
    fi
done

case "$CMD" in
    dry-run)
        exec "$COGAMES_BIN" upload \
            -p class=amongthem_policy.AmongThemPolicy \
            "${INCLUDES[@]}" \
            "${LLM_ARGS[@]}" \
            "${SECRETS[@]}" \
            -n "$POLICY_NAME" \
            --season "$SEASON" \
            --dry-run
        ;;
    upload)
        exec "$COGAMES_BIN" upload \
            -p class=amongthem_policy.AmongThemPolicy \
            "${INCLUDES[@]}" \
            "${LLM_ARGS[@]}" \
            "${SECRETS[@]}" \
            -n "$POLICY_NAME" \
            --season "$SEASON"
        ;;
    ship)
        exec "$COGAMES_BIN" upload \
            -p class=amongthem_policy.AmongThemPolicy \
            "${INCLUDES[@]}" \
            "${LLM_ARGS[@]}" \
            "${SECRETS[@]}" \
            -n "$POLICY_NAME" \
            --season "$SEASON"
        ;;
    ship-skip-validation)
        # Only for the "Policy took no actions" failure mode of
        # perception-heavy bots. See COGAMES.md § validation gate.
        exec "$COGAMES_BIN" upload \
            -p class=amongthem_policy.AmongThemPolicy \
            "${INCLUDES[@]}" \
            "${LLM_ARGS[@]}" \
            "${SECRETS[@]}" \
            -n "$POLICY_NAME" \
            --season "$SEASON" \
            --skip-validation
        ;;
    *)
        echo "Usage: $0 {dry-run|upload|ship|ship-skip-validation}" >&2
        exit 2
        ;;
esac
