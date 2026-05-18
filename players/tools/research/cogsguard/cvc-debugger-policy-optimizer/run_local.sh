#!/usr/bin/env bash
set -euo pipefail

# CvC Policy Optimizer -- Local Runner (no Docker)
# Runs the optimization loop directly on the host machine.
#
# Usage:
#   ./run_local.sh                    # Full optimization loop
#   ./run_local.sh --baseline         # Just run baseline eval
#   ./run_local.sh --once             # Single iteration then exit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
POLICY_PATH="policies/cyborg/cogsguard/cvc_debugger_robot/robot"
POLICY_SPEC="class=policies.cyborg.cogsguard.cvc_debugger_robot.robot.RobotPolicy"
RESULTS_DIR="$SCRIPT_DIR/results"
RESULTS_FILE="$RESULTS_DIR/results.jsonl"
SNAPSHOTS_DIR="$SCRIPT_DIR/snapshots"
LOG_FILE="$SCRIPT_DIR/optimizer.log"

export REPO_ROOT="$PROJECT_ROOT"
export RESULTS_FILE
export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH:-}"

TARGET_SCORE=75
REGRESSION_THRESHOLD=2.0
MILESTONE_SCORES=(40 50 60 75)

FULL_SEEDS="42,100,200,300,500,1000,2000,3000,5000,9999"
QUICK_SEEDS="42,500,5000"

ITERATION=0
BEST_SCORE=0

MODE="${1:-}"

log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" | tee -a "$LOG_FILE"
}

init() {
  mkdir -p "$RESULTS_DIR" "$SNAPSHOTS_DIR"

  cd "$PROJECT_ROOT"
  if [ ! -d .git ]; then
    git init
    git add -A
    git commit -m "initial: baseline policy" --allow-empty
  fi

  log "Workspace: $PROJECT_ROOT"
  log "Policy path: $POLICY_PATH"
  log "Results: $RESULTS_FILE"
}

run_eval() {
  local seeds="${1:-$FULL_SEEDS}"
  python3 "$SCRIPT_DIR/eval_harness.py" --seeds "$seeds" --policy "$POLICY_SPEC" --workers 4 2>&1
}

get_last_score() {
  if [ ! -s "$RESULTS_FILE" ]; then
    echo "0"
    return
  fi
  tail -1 "$RESULTS_FILE" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    print(data.get('mean', 0))
except:
    print(0)
" 2>/dev/null || echo "0"
}

checkpoint() {
  local msg="$1"
  cd "$PROJECT_ROOT"
  git add -A "$POLICY_PATH"
  if git diff --cached --quiet; then
    log "No changes to commit"
    return
  fi
  git commit -m "$msg"
  log "Committed: $msg"
}

save_snapshot() {
  local version="$1"
  local score="$2"
  local dest="$SNAPSHOTS_DIR/robot-v${version}-score-${score}"
  [ -d "$dest" ] && return
  mkdir -p "$dest"
  cp -r "$PROJECT_ROOT/$POLICY_PATH/" "$dest/robot/"
  log "Snapshot saved: $dest"
}

check_milestones() {
  local score="$1"
  for milestone in "${MILESTONE_SCORES[@]}"; do
    local score_int=${score%.*}
    if [ "$score_int" -ge "$milestone" ] 2>/dev/null; then
      local branch="robot-v${ITERATION}-score-${milestone}plus"
      cd "$PROJECT_ROOT"
      if ! git branch --list "$branch" | grep -q "$branch" 2>/dev/null; then
        git branch "$branch" 2>/dev/null || true
        log "MILESTONE: Created branch $branch (score=$score)"
        save_snapshot "$ITERATION" "${milestone}plus"
      fi
    fi
  done
}

build_prompt() {
  local current_score="$1"
  local iteration="$2"

  local history=""
  if [ -s "$RESULTS_FILE" ]; then
    history=$(tail -5 "$RESULTS_FILE" | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line.strip())
        ts = d.get('timestamp', '?')
        mean = d.get('mean', 0)
        stdev = d.get('stdev', 0)
        seeds = d.get('n_success', 0)
        print(f'  {ts}: mean={mean:.2f} stdev={stdev:.2f} ({seeds} seeds)')
    except:
        pass
" 2>/dev/null || echo "  (no history)")
  fi

  cat <<PROMPT
## Iteration $iteration -- Current avg score: $current_score (target: $TARGET_SCORE)

### Recent eval history:
$history

### Your task:
1. Read the current robot policy code in $PROJECT_ROOT/$POLICY_PATH/
2. If present, read competing policy snapshots under $PROJECT_ROOT/policies/ for transferable ideas
3. Identify the single highest-impact improvement you can make right now
4. Implement that improvement
5. Run a quick eval to verify: python3 $SCRIPT_DIR/eval_harness.py --quick
6. If the score improved, run a full eval: python3 $SCRIPT_DIR/eval_harness.py
7. If the score regressed, revert with: cd $PROJECT_ROOT && git checkout -- $POLICY_PATH

Focus on ONE change per iteration. Make it count.

After you're done with your changes and have verified they work with at least a quick eval,
report back with what you changed and the eval results.
PROMPT
}

# ── Main ──────────────────────────────────────────────────────────────────────

init

if [ "$MODE" = "--baseline" ]; then
  log "Running baseline eval only..."
  run_eval "$FULL_SEEDS"
  log "Baseline score: $(get_last_score)"
  exit 0
fi

# Baseline
log "=== CvC Policy Optimizer Started (local) ==="
log "Running baseline eval..."
run_eval "$FULL_SEEDS"
BEST_SCORE=$(get_last_score)
log "Baseline score: $BEST_SCORE"

if [ "$MODE" = "--once" ]; then
  log "Single iteration mode"
fi

while true; do
  ITERATION=$((ITERATION + 1))
  current_score=$(get_last_score)

  log "=== Iteration $ITERATION (current: $current_score, best: $BEST_SCORE, target: $TARGET_SCORE) ==="

  # Target check
  score_int=${current_score%.*}
  if [ "${score_int:-0}" -ge "$TARGET_SCORE" ] 2>/dev/null; then
    log "TARGET REACHED! Score: $current_score >= $TARGET_SCORE"
    checkpoint "robot: target score reached (avg: $current_score)"
    check_milestones "$current_score"
    break
  fi

  # Build prompt and run OpenCode
  prompt=$(build_prompt "$current_score" "$ITERATION")

  log "Launching OpenCode agent for iteration $ITERATION..."
  cd "$PROJECT_ROOT"

  # Point OpenCode to our config and Bedrock model
  export OPENCODE_CONFIG="$SCRIPT_DIR/opencode.json"
  opencode run -m "amazon-bedrock/anthropic.claude-sonnet-4-6" "$prompt" 2>&1 | tee -a "$LOG_FILE" || {
    log "OpenCode exited with error, continuing..."
  }

  # Post-iteration eval
  log "Running post-iteration full eval..."
  cd "$PROJECT_ROOT"
  run_eval "$FULL_SEEDS" 2>&1 | tee -a "$LOG_FILE" || {
    log "Post-iteration eval failed"
  }

  new_score=$(get_last_score)
  log "Post-iteration score: $new_score (was: $current_score)"

  # Regression check
  delta=$(python3 -c "print(round($new_score - $current_score, 3))" 2>/dev/null || echo "0")

  if python3 -c "exit(0 if $delta < -$REGRESSION_THRESHOLD else 1)" 2>/dev/null; then
    log "REGRESSION detected ($delta). Reverting..."
    cd "$PROJECT_ROOT"
    git checkout -- "$POLICY_PATH"
    log "Reverted to last good state"
  elif python3 -c "exit(0 if $delta > 0.5 else 1)" 2>/dev/null; then
    checkpoint "robot: iteration $ITERATION improvement (avg: $current_score -> $new_score)"
    log "Improvement committed: $current_score -> $new_score"
  fi

  # Best score tracking
  if python3 -c "exit(0 if $new_score > $BEST_SCORE else 1)" 2>/dev/null; then
    BEST_SCORE="$new_score"
    check_milestones "$new_score"
    log "New best score: $BEST_SCORE"
  fi

  [ "$MODE" = "--once" ] && break

  if [ "$ITERATION" -ge 200 ]; then
    log "Max iterations (200) reached. Best score: $BEST_SCORE"
    break
  fi

  log "Iteration $ITERATION complete. Sleeping 5s..."
  sleep 5
done

log "Final best score: $BEST_SCORE (target was $TARGET_SCORE)"
