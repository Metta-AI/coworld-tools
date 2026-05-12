#!/usr/bin/env bash
# quick_eval.sh — Fast single-agent eval for development iteration.
#
# Usage:
#   ./scripts/quick_eval.sh AGENT [OPTIONS]
#
# Examples:
#   ./scripts/quick_eval.sh role
#   ./scripts/quick_eval.sh nlanky -e 5 -s 500
#   ./scripts/quick_eval.sh baseline --json
#   ./scripts/quick_eval.sh role -m arena --seed 99

set -euo pipefail

if [[ $# -lt 1 ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
  echo "Usage: $0 AGENT [OPTIONS]"
  echo ""
  echo "Arguments:"
  echo "  AGENT              Scripted agent name (e.g. role, nlanky, baseline)"
  echo ""
  echo "Options:"
  echo "  -e EPISODES        Number of episodes (default: 3)"
  echo "  -s STEPS           Max steps per episode (default: 500)"
  echo "  -m MISSION         Mission (default: arena)"
  echo "  --seed SEED        RNG seed (default: 42)"
  echo "  --json             Output JSON instead of table"
  echo "  --gui              Launch MettaScope GUI viewer"
  exit 0
fi

AGENT="$1"
shift

# Defaults (small for fast iteration)
EPISODES=3
STEPS=500
MISSION="arena"
SEED=42
FORMAT_FLAG=""
RENDER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -e)
      EPISODES="$2"
      shift 2
      ;;
    -s)
      STEPS="$2"
      shift 2
      ;;
    -m)
      MISSION="$2"
      shift 2
      ;;
    --seed)
      SEED="$2"
      shift 2
      ;;
    --json)
      FORMAT_FLAG="--format json"
      shift
      ;;
    --gui)
      RENDER="gui"
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "Quick eval: $AGENT on $MISSION ($EPISODES eps, $STEPS steps)"
echo ""

if [[ -n "$RENDER" ]]; then
  exec uv run cogames play \
    -m "$MISSION" \
    -p "$AGENT" \
    -r "$RENDER" \
    -s "$STEPS" \
    --seed "$SEED"
else
  exec uv run cogames scrimmage \
    -m "$MISSION" \
    -p "$AGENT" \
    -e "$EPISODES" \
    -s "$STEPS" \
    --seed "$SEED" \
    $FORMAT_FLAG
fi
