#!/usr/bin/env bash
# eval_cogas.sh — Run cogas agent through local evaluation and report
# aligned.junction.held score.
#
# Usage:
#   ./scripts/eval_cogas.sh [OPTIONS]
#
# Examples:
#   ./scripts/eval_cogas.sh
#   ./scripts/eval_cogas.sh --episodes 20
#   ./scripts/eval_cogas.sh --params 'miner=2&aligner=4&scrambler=3'
#   ./scripts/eval_cogas.sh --policy role --episodes 10 --threshold 1000

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UV_PROJECT=(uv run --project "$AGENTS_ROOT")

# Defaults
POLICY="cogsguard"
MISSION="arena"
EPISODES=10
STEPS=1000
SEED=42
PARAMS=""
THRESHOLD=1500
FORMAT_FLAG="--format json"

usage() {
  cat << 'USAGE'
Usage: eval_cogas.sh [OPTIONS]

Options:
  --policy POLICY     Policy short name (default: cogsguard)
  --episodes N        Number of episodes (default: 10)
  --steps N           Max steps per episode (default: 1000)
  --mission MISSION   Mission to evaluate (default: arena)
  --params PARAMS     URI params (e.g. 'miner=2&aligner=4&scrambler=3')
  --threshold N       aligned.junction.held threshold (default: 1500)
  --seed SEED         RNG seed (default: 42)
  -h, --help          Show this help
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
    --params)
      PARAMS="$2"
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
    -h | --help) usage ;;
    *)
      echo "Unknown option: $1"
      usage
      ;;
  esac
done

# Build policy URI
POLICY_URI="metta://policy/${POLICY}"
if [[ -n "$PARAMS" ]]; then
  POLICY_URI="${POLICY_URI}?${PARAMS}"
fi

echo "=== CoGas Eval ==="
echo "Policy:    $POLICY_URI"
echo "Mission:   $MISSION"
echo "Episodes:  $EPISODES"
echo "Steps:     $STEPS"
echo "Seed:      $SEED"
echo "Threshold: $THRESHOLD (aligned.junction.held)"
echo ""

# Run cogames scrimmage and capture JSON output
TMPOUT=$(mktemp)
trap 'rm -f "$TMPOUT"' EXIT

if ! "${UV_PROJECT[@]}" cogames scrimmage \
  -m "$MISSION" \
  -p "$POLICY_URI" \
  -e "$EPISODES" \
  -s "$STEPS" \
  --seed "$SEED" \
  $FORMAT_FLAG \
  > "$TMPOUT" 2>&1; then
  echo "ERROR: cogames scrimmage failed"
  cat "$TMPOUT"
  exit 1
fi

# Parse metrics from JSON output
PYTHONPATH="${AGENTS_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" "${UV_PROJECT[@]}" python - "$TMPOUT" "$THRESHOLD" << 'PYEOF'
import json, sys

from cogames_agents.eval_result_metrics import extract_cogsguard_eval_metrics, parse_eval_result_text

tmpout = sys.argv[1]
threshold = float(sys.argv[2])

with open(tmpout) as f:
    data = parse_eval_result_text(f.read())

missions = data.get("missions", [])
if not missions:
    print("ERROR: No mission results in output")
    sys.exit(1)

metrics = extract_cogsguard_eval_metrics(data)
ajh = metrics.get("aligned.junction.held")
ajg = metrics.get("aligned.junction.gained")
hg = metrics.get("heart.gained")
hl = metrics.get("heart.lost")
reward = metrics.get("reward")
timeouts = metrics.get("action_timeouts")

def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)

# Print summary table
print("=== Results ===")
print(f"  aligned.junction.held:   {fmt(ajh)}")
print(f"  aligned.junction.gained: {fmt(ajg)}")
print(f"  heart.gained:            {fmt(hg)}")
print(f"  heart.lost:              {fmt(hl)}")
print(f"  reward:                  {fmt(reward)}")
print(f"  action_timeouts:         {fmt(timeouts)}")
print()

# Threshold check
if ajh is not None and ajh < threshold:
    print(f"FAIL: aligned.junction.held ({fmt(ajh)}) < threshold ({threshold})")
    sys.exit(1)
elif ajh is None:
    print("WARN: aligned.junction.held not found in output")
    sys.exit(1)
else:
    print(f"PASS: aligned.junction.held ({fmt(ajh)}) >= threshold ({threshold})")
PYEOF
