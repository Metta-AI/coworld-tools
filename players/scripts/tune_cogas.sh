#!/usr/bin/env bash
# tune_cogas.sh — Run eval_cogas.sh with multiple role distributions to find
# the optimal aligned.junction.held configuration.
#
# Usage:
#   ./scripts/tune_cogas.sh [OPTIONS]
#
# Examples:
#   ./scripts/tune_cogas.sh
#   ./scripts/tune_cogas.sh --episodes 20
#   ./scripts/tune_cogas.sh --policy role --configs custom_configs.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EVAL_SCRIPT="${SCRIPT_DIR}/eval_cogas.sh"

# Defaults
POLICY="cogsguard"
MISSION="arena"
EPISODES=10
STEPS=1000
SEED=42
THRESHOLD=1500
CONFIGS_FILE=""

# Default role distributions to sweep
DEFAULT_CONFIGS=(
  ""
  "miner=4&aligner=2&scrambler=2&scout=2"
  "miner=3&aligner=3&scrambler=2&scout=2"
  "miner=2&aligner=4&scrambler=2&scout=2"
  "miner=2&aligner=2&scrambler=4&scout=2"
  "miner=4&aligner=4&scrambler=1&scout=1"
  "miner=6&aligner=2&scrambler=1&scout=1"
  "miner=2&aligner=4&scrambler=3"
  "miner=4&scrambler=2&gear=1"
  "gear=10"
)

usage() {
  cat << 'USAGE'
Usage: tune_cogas.sh [OPTIONS]

Options:
  --policy POLICY       Policy short name (default: cogsguard)
  --episodes N          Number of episodes per config (default: 10)
  --steps N             Max steps per episode (default: 1000)
  --mission MISSION     Mission (default: arena)
  --threshold N         Pass threshold for aligned.junction.held (default: 1500)
  --seed SEED           RNG seed (default: 42)
  --configs FILE        File with one param string per line (overrides defaults)
  -h, --help            Show this help
USAGE
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --policy)
      POLICY="$2"
      shift 2
      ;;
    --episodes)
      EPISODES="$2"
      shift 2
      ;;
    --steps)
      STEPS="$2"
      shift 2
      ;;
    --mission)
      MISSION="$2"
      shift 2
      ;;
    --threshold)
      THRESHOLD="$2"
      shift 2
      ;;
    --seed)
      SEED="$2"
      shift 2
      ;;
    --configs)
      CONFIGS_FILE="$2"
      shift 2
      ;;
    -h | --help) usage ;;
    *)
      echo "Unknown option: $1"
      usage
      ;;
  esac
done

# Build config list
CONFIGS=()
if [[ -n "$CONFIGS_FILE" ]]; then
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    CONFIGS+=("$line")
  done < "$CONFIGS_FILE"
else
  CONFIGS=("${DEFAULT_CONFIGS[@]}")
fi

echo "=== CoGas Tuning Sweep ==="
echo "Policy:       $POLICY"
echo "Mission:      $MISSION"
echo "Episodes:     $EPISODES per config"
echo "Steps:        $STEPS"
echo "Seed:         $SEED"
echo "Configs:      ${#CONFIGS[@]}"
echo ""

# Collect results
declare -a RESULT_PARAMS=()
declare -a RESULT_SCORES=()
declare -a RESULT_STATUS=()

for i in "${!CONFIGS[@]}"; do
  params="${CONFIGS[$i]}"
  label="${params:-<default>}"
  idx=$((i + 1))
  total=${#CONFIGS[@]}

  echo "--- [$idx/$total] params: $label ---"

  EVAL_ARGS=(
    --policy "$POLICY"
    --mission "$MISSION"
    --episodes "$EPISODES"
    --steps "$STEPS"
    --seed "$SEED"
    --threshold "$THRESHOLD"
  )
  if [[ -n "$params" ]]; then
    EVAL_ARGS+=(--params "$params")
  fi

  TMPLOG=$(mktemp)
  if bash "$EVAL_SCRIPT" "${EVAL_ARGS[@]}" > "$TMPLOG" 2>&1; then
    status="PASS"
  else
    status="FAIL"
  fi

  # Extract aligned.junction.held from output
  score=$(grep -oP 'aligned\.junction\.held:\s+\K[0-9.]+' "$TMPLOG" 2> /dev/null | head -1 || true)
  if [[ -z "$score" ]]; then
    score="-"
  fi

  echo "  aligned.junction.held = $score [$status]"
  echo ""

  RESULT_PARAMS+=("$label")
  RESULT_SCORES+=("$score")
  RESULT_STATUS+=("$status")

  rm -f "$TMPLOG"
done

# Print summary table
echo ""
echo "============================================================"
echo "                    TUNING RESULTS SUMMARY"
echo "============================================================"
printf "%-50s %12s %6s\n" "params" "ajh_score" "status"
echo "------------------------------------------------------------"

best_score=""
best_idx=""
for i in "${!RESULT_PARAMS[@]}"; do
  printf "%-50s %12s %6s\n" "${RESULT_PARAMS[$i]}" "${RESULT_SCORES[$i]}" "${RESULT_STATUS[$i]}"
  if [[ "${RESULT_SCORES[$i]}" != "-" ]]; then
    if [[ -z "$best_score" ]] || python3 -c "exit(0 if float('${RESULT_SCORES[$i]}') > float('$best_score') else 1)" 2> /dev/null; then
      best_score="${RESULT_SCORES[$i]}"
      best_idx=$i
    fi
  fi
done
echo "------------------------------------------------------------"

if [[ -n "$best_idx" ]]; then
  echo ""
  echo "BEST: ${RESULT_PARAMS[$best_idx]}"
  echo "  aligned.junction.held = $best_score"
  if [[ "${RESULT_PARAMS[$best_idx]}" != "<default>" ]]; then
    echo "  URI: metta://policy/${POLICY}?${RESULT_PARAMS[$best_idx]}"
  else
    echo "  URI: metta://policy/${POLICY}"
  fi
fi
