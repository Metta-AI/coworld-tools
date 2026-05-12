#!/usr/bin/env bash
set -euo pipefail

# CvC Policy Optimizer -- Main Loop
# Drives OpenCode agent through analyze->edit->eval->checkpoint cycles
# until the robot policy reaches 75+ average score.

WORKDIR="/app"
POLICIES_DIR="${WORKDIR}/policies"
RESULTS_FILE="${WORKDIR}/results/results.jsonl"
SNAPSHOTS_DIR="${WORKDIR}/snapshots"
LOG_FILE="${WORKDIR}/optimizer.log"

TARGET_SCORE=75
REGRESSION_THRESHOLD=2.0
MILESTONE_SCORES=(40 50 60 75)

FULL_SEEDS="42,100,200,300,500,1000,2000,3000,5000,9999"
QUICK_SEEDS="42,500,5000"

ITERATION=0
BEST_SCORE=0
BASELINE_SCORE=0

log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" | tee -a "$LOG_FILE"
}

die() {
  log "FATAL: $*"
  exit 1
}

# Initialize workspace
init_workspace() {
  log "Initializing workspace..."

  mkdir -p "$SNAPSHOTS_DIR"
  touch "$RESULTS_FILE"

  cd "$POLICIES_DIR"

  if [ ! -d .git ]; then
    git init
    git add -A
    git commit -m "initial: baseline policy"
  fi

  log "Workspace initialized at $WORKDIR"
}

# Run eval and capture score
run_eval() {
  local seeds="${1:-$FULL_SEEDS}"
  local extra_args="${2:-}"

  log "Running eval with seeds: $seeds"

  local output
  output=$(python "$WORKDIR/eval_harness.py" \
    --seeds "$seeds" \
    --json \
    --policy "class=robot.RobotPolicy" \
    $extra_args 2>&1) || true

  # Extract the JSON report (last JSON object in output)
  local json_report
  json_report=$(echo "$output" | python3 -c "
import sys, json
lines = sys.stdin.read()
# Find the JSON report block
start = lines.rfind('{\"timestamp\"')
if start >= 0:
    try:
        obj = json.loads(lines[start:lines.index('}', start) + 1])
    except:
        # Try to find complete JSON
        depth = 0
        for i, c in enumerate(lines[start:]):
            if c == '{': depth += 1
            elif c == '}': depth -= 1
            if depth == 0:
                print(lines[start:start+i+1])
                break
else:
    print('{}')
" 2>/dev/null || echo '{}')

  # Also print the human-readable output
  echo "$output" | grep -v '^{' | head -30

  # Extract mean score
  local score
  score=$(echo "$json_report" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    print(data.get('mean', 0))
except:
    print(0)
" 2>/dev/null || echo "0")

  echo "$score"
}

# Run a quick validation eval (3 seeds)
quick_eval() {
  run_eval "$QUICK_SEEDS" "$@"
}

# Run a full eval (10 seeds)
full_eval() {
  run_eval "$FULL_SEEDS" "$@"
}

# Get the last score from results
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

# Save a snapshot of the current policy
save_snapshot() {
  local version="$1"
  local score="$2"
  local dest="$SNAPSHOTS_DIR/robot-v${version}-score-${score}"

  if [ -d "$dest" ]; then
    log "Snapshot already exists: $dest"
    return
  fi

  mkdir -p "$dest"
  cp -r "$POLICIES_DIR/robot/" "$dest/"
  log "Snapshot saved: $dest"
}

# Git checkpoint
checkpoint() {
  local msg="$1"
  cd "$POLICIES_DIR"
  git add -A robot/
  if git diff --cached --quiet; then
    log "No changes to commit"
    return
  fi
  git commit -m "$msg"
  log "Committed: $msg"
}

# Check and handle milestones
check_milestones() {
  local score="$1"

  for milestone in "${MILESTONE_SCORES[@]}"; do
    local score_int=${score%.*}
    if [ "$score_int" -ge "$milestone" ]; then
      local branch="robot-v${ITERATION}-score-${milestone}plus"
      cd "$POLICIES_DIR"
      if ! git branch --list "$branch" | grep -q "$branch"; then
        git branch "$branch"
        log "MILESTONE: Created branch $branch (score=$score)"
        save_snapshot "$ITERATION" "${milestone}plus"
      fi
    fi
  done
}

# Build the prompt for OpenCode
build_iteration_prompt() {
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
1. Read the current robot policy code in policies/robot/
2. Read the competing Softy policy in policies/Softy:v77/softy.py for ideas
3. Identify the single highest-impact improvement you can make right now
4. Implement that improvement
5. Run a quick eval to verify: python /app/eval_harness.py --quick --json
6. If the score improved, run a full eval: python /app/eval_harness.py --json
7. If the score regressed, revert with: cd /app/policies && git checkout -- robot/

Focus on ONE change per iteration. Make it count.

After you're done with your changes and have verified they work with at least a quick eval,
report back with what you changed and the eval results.
PROMPT
}

# Main optimization loop
main_loop() {
  log "=== CvC Policy Optimizer Started ==="
  log "Target score: $TARGET_SCORE"

  init_workspace

  # Baseline eval
  log "Running baseline eval..."
  BASELINE_SCORE=$(python "$WORKDIR/eval_harness.py" \
    --seeds "$FULL_SEEDS" \
    --policy "class=robot.RobotPolicy" 2>&1 | tail -1 || echo "0")

  # Parse actual score from eval_harness output
  BASELINE_SCORE=$(get_last_score)
  BEST_SCORE="$BASELINE_SCORE"

  log "Baseline score: $BASELINE_SCORE"

  if (( $(echo "$BASELINE_SCORE >= $TARGET_SCORE" | bc -l 2>/dev/null || echo 0) )); then
    log "Already at target! Score: $BASELINE_SCORE >= $TARGET_SCORE"
    exit 0
  fi

  # Main loop -- run OpenCode iterations
  while true; do
    ITERATION=$((ITERATION + 1))
    local current_score
    current_score=$(get_last_score)

    log "=== Iteration $ITERATION (current: $current_score, best: $BEST_SCORE, target: $TARGET_SCORE) ==="

    # Check if we've reached the target
    if (( $(echo "$current_score >= $TARGET_SCORE" | bc -l 2>/dev/null || echo 0) )); then
      log "TARGET REACHED! Score: $current_score >= $TARGET_SCORE"
      checkpoint "robot: target score reached (avg: $current_score)"
      check_milestones "$current_score"
      save_snapshot "$ITERATION" "final-${current_score}"
      log "=== Optimization Complete ==="
      break
    fi

    # Build the prompt for this iteration
    local prompt
    prompt=$(build_iteration_prompt "$current_score" "$ITERATION")

    # Run OpenCode agent in non-interactive mode
    log "Launching OpenCode agent for iteration $ITERATION..."

    cd "$WORKDIR"

    # OpenCode runs in the workspace, reads AGENT_INSTRUCTIONS.md, and makes changes
    export OPENCODE_CONFIG="$WORKDIR/opencode.json"
    opencode run -m "amazon-bedrock/anthropic.claude-sonnet-4-6" "$prompt" 2>&1 | tee -a "$LOG_FILE" || {
      log "OpenCode exited with error, continuing..."
    }

    # Run a full eval after the agent's changes (agent may have run quick evals)
    log "Running post-iteration full eval..."
    python "$WORKDIR/eval_harness.py" \
      --seeds "$FULL_SEEDS" \
      --policy "class=robot.RobotPolicy" 2>&1 | tee -a "$LOG_FILE" || {
      log "Post-iteration eval failed"
    }

    # After OpenCode finishes, check results
    local new_score
    new_score=$(get_last_score)

    log "Post-iteration score: $new_score (was: $current_score)"

    # Check for regression
    local delta
    delta=$(echo "$new_score - $current_score" | bc -l 2>/dev/null || echo "0")

    if (( $(echo "$delta < -$REGRESSION_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
      log "REGRESSION detected ($delta). Reverting..."
      cd "$POLICIES_DIR"
      git checkout -- robot/
      log "Reverted to last good state"
      continue
    fi

    # Check for improvement
    if (( $(echo "$delta > 0.5" | bc -l 2>/dev/null || echo 0) )); then
      checkpoint "robot: iteration $ITERATION improvement (avg: $current_score -> $new_score)"
      log "Improvement committed: $current_score -> $new_score"
    fi

    # Update best score
    if (( $(echo "$new_score > $BEST_SCORE" | bc -l 2>/dev/null || echo 0) )); then
      BEST_SCORE="$new_score"
      check_milestones "$new_score"
      log "New best score: $BEST_SCORE"
    fi

    # Safety: prevent infinite loops (max 200 iterations)
    if [ "$ITERATION" -ge 200 ]; then
      log "Max iterations (200) reached. Best score: $BEST_SCORE"
      break
    fi

    log "Iteration $ITERATION complete. Sleeping 5s before next..."
    sleep 5
  done

  log "Final best score: $BEST_SCORE (target was $TARGET_SCORE)"
  log "Results history: $RESULTS_FILE"
  log "Snapshots: $SNAPSHOTS_DIR"
}

# Entry point
main_loop
