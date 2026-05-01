#!/usr/bin/env bash
#
# Convenience wrapper for validating and shipping guided_bot to a
# cogames Among Them season.
#
# Usage:
#   SEASON=among-them POLICY_NAME=$USER-guided-bot ./ship.sh dry-run
#   SEASON=among-them POLICY_NAME=$USER-guided-bot ./ship.sh ship
#
# Phase 0 note: the LLM requires an API key. Pass it via `--secret-env`
# when uploading for real. For dry-runs you can leave it off; the
# in-Nim LLM stub returns `LlmNoKey` and the bot runs on defaults.
#
# Always runs from the repo root (personal_cogs/) so relative -f paths
# resolve against the workshop layout.

set -euo pipefail

CMD="${1:-dry-run}"
SEASON="${SEASON:-}"
POLICY_NAME="${POLICY_NAME:-$USER-guided-bot-$(date +%Y%m%d-%H%M%S)}"
ANTHROPIC_KEY="${ANTHROPIC_API_KEY:-}"

if [[ -z "$SEASON" ]]; then
    echo "ERROR: SEASON is required. Run 'cogames season list' to find an active Among Them season." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# cogames/ -> guided_bot/ -> among_them/ -> personal_cogs/
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

cd "$REPO_ROOT"

INCLUDES=(
    -f among_them/guided_bot/cogames/amongthem_policy.py
    -f among_them/guided_bot
)

SECRETS=()
if [[ -n "$ANTHROPIC_KEY" ]]; then
    SECRETS+=(--secret-env "ANTHROPIC_API_KEY=$ANTHROPIC_KEY")
fi

case "$CMD" in
    dry-run)
        exec cogames upload \
            -p class=amongthem_policy.AmongThemPolicy \
            "${INCLUDES[@]}" \
            "${SECRETS[@]}" \
            -n "$POLICY_NAME" \
            --season "$SEASON" \
            --dry-run
        ;;
    upload)
        exec cogames upload \
            -p class=amongthem_policy.AmongThemPolicy \
            "${INCLUDES[@]}" \
            "${SECRETS[@]}" \
            -n "$POLICY_NAME" \
            --season "$SEASON"
        ;;
    ship)
        exec cogames ship \
            -p class=amongthem_policy.AmongThemPolicy \
            "${INCLUDES[@]}" \
            "${SECRETS[@]}" \
            -n "$POLICY_NAME" \
            --season "$SEASON"
        ;;
    ship-skip-validation)
        # Only for the "Policy took no actions" failure mode of
        # perception-heavy bots. See COGAMES.md § validation gate.
        exec cogames ship \
            -p class=amongthem_policy.AmongThemPolicy \
            "${INCLUDES[@]}" \
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
