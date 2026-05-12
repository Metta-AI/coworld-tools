#!/usr/bin/env bash
# benchmark_agents.sh — Run each registered scripted agent through cogames run
# on machina1/cogsguard_arena maps and collect results.
#
# Usage:
#   ./scripts/benchmark_agents.sh [OPTIONS]
#
# Options:
#   -e EPISODES   Number of episodes per agent (default: 10)
#   -s STEPS      Max steps per episode (default: 1000)
#   -m MISSION    Mission to evaluate (default: arena)
#   -o OUTDIR     Output directory for results (default: ./benchmark_results)
#   -a AGENTS     Comma-separated agent list (default: all registered agents)
#   --seed SEED   Base RNG seed (default: 42)

set -euo pipefail

# Defaults
EPISODES=10
STEPS=1000
MISSION="arena"
OUTDIR="./benchmark_results"
SEED=42
AGENTS=""

# All registered scripted agents (from short_names scan)
ALL_AGENTS=(
  role
  role_nim
  nlanky
  wombo
  baseline
  tiny_baseline
  cogsguard_v2
  cogsguard_control
  cogsguard_targeted
  teacher
  ladybug_py
  thinky
  nim_random
  race_car
  ladybug
  alignall
)

usage() {
  sed -n '2,/^$/s/^# //p' "$0"
  exit 1
}

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
    -o)
      OUTDIR="$2"
      shift 2
      ;;
    -a)
      AGENTS="$2"
      shift 2
      ;;
    --seed)
      SEED="$2"
      shift 2
      ;;
    -h | --help) usage ;;
    *)
      echo "Unknown option: $1"
      usage
      ;;
  esac
done

# Resolve agent list
if [[ -n "$AGENTS" ]]; then
  IFS=',' read -ra AGENT_LIST <<< "$AGENTS"
else
  AGENT_LIST=("${ALL_AGENTS[@]}")
fi

# Prepare output directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RUN_DIR="${OUTDIR}/${TIMESTAMP}"
mkdir -p "$RUN_DIR"

echo "=== CoGames Benchmark ==="
echo "Mission:  $MISSION"
echo "Episodes: $EPISODES"
echo "Steps:    $STEPS"
echo "Seed:     $SEED"
echo "Agents:   ${AGENT_LIST[*]}"
echo "Output:   $RUN_DIR"
echo ""

SUMMARY_FILE="${RUN_DIR}/summary.txt"
echo "mission=$MISSION episodes=$EPISODES steps=$STEPS seed=$SEED" > "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"

PASS_COUNT=0
FAIL_COUNT=0

for agent in "${AGENT_LIST[@]}"; do
  AGENT_OUT="${RUN_DIR}/${agent}.json"
  echo "--- Evaluating: $agent ---"

  if uv run cogames scrimmage \
    -m "$MISSION" \
    -p "$agent" \
    -e "$EPISODES" \
    -s "$STEPS" \
    --seed "$SEED" \
    --format json \
    > "$AGENT_OUT" 2> "${RUN_DIR}/${agent}.stderr"; then
    echo "  OK -> $AGENT_OUT"
    echo "PASS $agent" >> "$SUMMARY_FILE"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "  FAIL (exit $?) — see ${RUN_DIR}/${agent}.stderr"
    echo "FAIL $agent" >> "$SUMMARY_FILE"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
done

echo ""
echo "=== Benchmark Complete ==="
echo "Passed: $PASS_COUNT / $((PASS_COUNT + FAIL_COUNT))"
echo "Results: $RUN_DIR"
echo ""

# Generate comparison table if compare_agents.py is available
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "${SCRIPT_DIR}/compare_agents.py" ]]; then
  echo "Generating comparison table..."
  uv run python "${SCRIPT_DIR}/compare_agents.py" "$RUN_DIR"
fi
