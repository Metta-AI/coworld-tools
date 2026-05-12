#!/usr/bin/env bash
# ci_eval.sh — Continuous eval pipeline for the cogas agent.
# Runs the full eval suite, checks for regressions against the stored baseline,
# and appends results to the eval-results log.
#
# Usage:
#   ./scripts/ci_eval.sh [OPTIONS]
#
# Examples:
#   ./scripts/ci_eval.sh
#   ./scripts/ci_eval.sh --episodes 20
#   ./scripts/ci_eval.sh --params 'miner=2&aligner=4&scrambler=3'
#   ./scripts/ci_eval.sh --skip-log   # don't append to eval-results-log.md

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="${AGENTS_ROOT}/docs/eval-results-log.md"
BASELINE_FILE="${AGENTS_ROOT}/scripts/.eval_baseline.json"
RESULTS_DIR="${AGENTS_ROOT}/.eval_results"
UV_PROJECT=(uv run --project "$AGENTS_ROOT")

# Defaults
POLICY="cogsguard"
MISSION="arena"
EPISODES=10
STEPS=1000
SEED=42
PARAMS=""
SKIP_LOG=false
LABEL=""

usage() {
  cat << 'USAGE'
Usage: ci_eval.sh [OPTIONS]

Options:
  --policy POLICY     Policy short name (default: cogsguard)
  --episodes N        Number of episodes (default: 10)
  --steps N           Max steps per episode (default: 1000)
  --mission MISSION   Mission to evaluate (default: arena)
  --params PARAMS     URI params (e.g. 'miner=2&aligner=4&scrambler=3')
  --seed SEED         RNG seed (default: 42)
  --label LABEL       Optional label for the log entry (e.g. git SHA, branch)
  --skip-log          Don't append results to eval-results-log.md
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
    --seed)
      SEED="$2"
      shift 2
      ;;
    --label)
      LABEL="$2"
      shift 2
      ;;
    --skip-log)
      SKIP_LOG=true
      shift
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

# Auto-detect label from git if not provided
if [[ -z "$LABEL" ]]; then
  LABEL="$(git -C "$AGENTS_ROOT" rev-parse --short HEAD 2> /dev/null || echo 'unknown')"
fi

TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S)
RUN_TAG="${TIMESTAMP}_${LABEL}"

echo "=== CI Eval Pipeline ==="
echo "Policy:    $POLICY_URI"
echo "Mission:   $MISSION"
echo "Episodes:  $EPISODES"
echo "Steps:     $STEPS"
echo "Seed:      $SEED"
echo "Label:     $LABEL"
echo "Timestamp: $TIMESTAMP"
echo ""

# --- Step 1: Run eval ---
mkdir -p "$RESULTS_DIR"
RESULT_FILE="${RESULTS_DIR}/${RUN_TAG}.json"
TMPOUT=$(mktemp)
trap 'rm -f "$TMPOUT"' EXIT

echo "Running cogames scrimmage..."
if ! "${UV_PROJECT[@]}" cogames scrimmage \
  -m "$MISSION" \
  -p "$POLICY_URI" \
  -e "$EPISODES" \
  -s "$STEPS" \
  --seed "$SEED" \
  --format json \
  > "$TMPOUT" 2>&1; then
  echo "ERROR: cogames scrimmage failed"
  cat "$TMPOUT"
  exit 1
fi

cp "$TMPOUT" "$RESULT_FILE"
echo "Results saved to $RESULT_FILE"
echo ""

# --- Step 2: Extract metrics and check regression ---
PYTHONPATH="${AGENTS_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" "${UV_PROJECT[@]}" python "$SCRIPT_DIR/regression_check.py" \
  --result "$RESULT_FILE" \
  --baseline "$BASELINE_FILE" \
  --label "$LABEL" \
  --timestamp "$TIMESTAMP" \
  --params "$PARAMS" \
  --policy "$POLICY_URI"
RC=$?

# --- Step 3: Append to log ---
if [[ "$SKIP_LOG" != true ]]; then
  PYTHONPATH="${AGENTS_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" "${UV_PROJECT[@]}" python - "$RESULT_FILE" "$LOG_FILE" "$LABEL" "$TIMESTAMP" "$POLICY_URI" "$PARAMS" << 'PYEOF'
import json, sys
from pathlib import Path

from cogames_agents.eval_result_metrics import extract_cogsguard_eval_metrics, parse_eval_result_text

result_path, log_path, label, timestamp, policy_uri, params = sys.argv[1:7]

with open(result_path) as f:
    data = parse_eval_result_text(f.read())

missions = data.get("missions", [])
if not missions:
    print("WARN: No missions in result, skipping log")
    sys.exit(0)

metrics = extract_cogsguard_eval_metrics(data)
reward = metrics.get("reward")

def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)

ajh = metrics.get("aligned.junction.held")
ajg = metrics.get("aligned.junction.gained")
hg = metrics.get("heart.gained")
hl = metrics.get("heart.lost")
timeouts = metrics.get("action_timeouts")

log = Path(log_path)
entry = (
    f"| {timestamp} | {label} | {policy_uri} "
    f"| {fmt(ajh)} | {fmt(ajg)} | {fmt(reward)} "
    f"| {fmt(hg)} | {fmt(hl)} | {fmt(timeouts)} |\n"
)

if not log.exists():
    # Should already exist, but create header if missing
    header = (
        "# Eval Results Log\n\n"
        "| Date | Version | Policy | AJH | AJG | Reward | H+ | H- | Timeouts |\n"
        "|------|---------|--------|-----|-----|--------|----|----|----------|\n"
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(header + entry)
else:
    with open(log, "a") as f:
        f.write(entry)

print(f"Logged results to {log_path}")
PYEOF
fi

echo ""
if [[ $RC -eq 0 ]]; then
  echo "=== CI Eval PASSED ==="
else
  echo "=== CI Eval FAILED (regression detected) ==="
fi

exit $RC
