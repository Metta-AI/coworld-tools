#!/bin/bash
set -uo pipefail

# Cyborg Policy Framework — Continuous Evolution Loop
#
# Template for running the play → analyze → evolve → repeat cycle.
# Customize the GAME ENGINE section below for your specific game.
#
# Usage:
#   ./scripts/continuous_loop.sh <game_name>
#   ./scripts/continuous_loop.sh settlers

GAME="${1:?Usage: $0 <game_name>}"
SEED=42
STEPS=2500
EVOLUTION_INTERVAL=1
GAME_COUNT=0
EVOLUTION_COUNT=0
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNS_DIR="$PROJECT_ROOT/runs/$GAME"
SCORE_FILE="$RUNS_DIR/score_history.json"
LOG_FILE="$RUNS_DIR/continuous_log.txt"

# PID of background post-game work
BG_POST_GAME_PID=""

cd "$PROJECT_ROOT"

mkdir -p "$RUNS_DIR"

# Init score history if missing
if [ ! -f "$SCORE_FILE" ]; then
  echo '{"games":[],"current_steps":2500}' > "$SCORE_FILE"
fi

# Load state from previous run if exists
if [ -f "$SCORE_FILE" ]; then
  STEPS=$(python3 -c "import json; print(json.load(open('$SCORE_FILE')).get('current_steps', 2500))")
  GAME_COUNT=$(python3 -c "import json; print(len(json.load(open('$SCORE_FILE')).get('games', [])))")
  EVOLUTION_COUNT=$((GAME_COUNT / EVOLUTION_INTERVAL))
fi

wait_for_post_game() {
  if [ -n "$BG_POST_GAME_PID" ]; then
    if kill -0 "$BG_POST_GAME_PID" 2>/dev/null; then
      echo "  Waiting for background post-game analysis to finish..." | tee -a "$LOG_FILE"
      wait "$BG_POST_GAME_PID" 2>/dev/null || true
    fi
    BG_POST_GAME_PID=""
  fi
}

run_post_game_background() {
  local steps="$1"
  local retries=0
  while [ $retries -lt 30 ]; do
    local latest_learnings
    latest_learnings=$(ls -t "$RUNS_DIR"/*_learnings.json 2>/dev/null | head -1)
    if [ -n "$latest_learnings" ]; then
      local latest_memory
      latest_memory=$(ls -t "$RUNS_DIR"/*_memory.json 2>/dev/null | head -1)
      if [ -n "$latest_memory" ] && [ "$latest_learnings" -nt "$latest_memory" ] || [ "$retries" -ge 5 ]; then
        break
      fi
    fi
    sleep 2
    retries=$((retries + 1))
  done

  python3 "$PROJECT_ROOT/scripts/record_score.py" --record --steps "$steps" --game "$GAME" 2>&1 | tee -a "$LOG_FILE"

  local new_steps
  new_steps=$(python3 "$PROJECT_ROOT/scripts/record_score.py" --check-escalation --current-steps "$steps" --game "$GAME" 2>/dev/null || echo "$steps")
  echo "$new_steps" > "$RUNS_DIR/.pending_steps"
}

echo "=== CONTINUOUS LOOP STARTING ===" | tee -a "$LOG_FILE"
echo "  Game: $GAME | Seed: $SEED | Steps: $STEPS | Games played: $GAME_COUNT" | tee -a "$LOG_FILE"
echo "  Evolution interval: every $EVOLUTION_INTERVAL games" | tee -a "$LOG_FILE"
echo "  Mode: pipelined (post-game analysis runs in background)" | tee -a "$LOG_FILE"
echo "  Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "  Started: $(date)" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

while true; do
  GAME_COUNT=$((GAME_COUNT + 1))

  # Pick up escalation result from previous background post-game
  if [ -f "$RUNS_DIR/.pending_steps" ]; then
    NEW_STEPS=$(cat "$RUNS_DIR/.pending_steps")
    rm -f "$RUNS_DIR/.pending_steps"
    if [ -n "$NEW_STEPS" ] && [ "$NEW_STEPS" != "$STEPS" ]; then
      echo ">>> STEP ESCALATION: $STEPS -> $NEW_STEPS <<<" | tee -a "$LOG_FILE"
      STEPS=$NEW_STEPS
    fi
  fi

  echo "" | tee -a "$LOG_FILE"
  echo "=== GAME $GAME_COUNT | seed=$SEED steps=$STEPS | $(date) ===" | tee -a "$LOG_FILE"

  # ╔══════════════════════════════════════════════════════════════════╗
  # ║  GAME ENGINE — Replace this section with your game's run cmd   ║
  # ║                                                                ║
  # ║  Requirements:                                                 ║
  # ║  1. Run one game episode                                       ║
  # ║  2. Output a memory dump to runs/{game}/*_memory.json          ║
  # ║  3. Output a learnings file to runs/{game}/*_learnings.json    ║
  # ║     (from post-game analysis)                                  ║
  # ╚══════════════════════════════════════════════════════════════════╝
  echo "  TODO: Add your game engine run command here" | tee -a "$LOG_FILE"
  echo "  Example:" | tee -a "$LOG_FILE"
  echo "    SKIP_EVOLUTION=1 your_engine run --seed \$SEED --steps \$STEPS --game \$GAME" | tee -a "$LOG_FILE"
  echo "  Exiting — implement the game engine section in continuous_loop.sh" | tee -a "$LOG_FILE"
  exit 1
  # ╔══════════════════════════════════════════════════════════════════╝

  # Post-game score recording runs in background
  run_post_game_background "$STEPS" &
  BG_POST_GAME_PID=$!
  echo "  Post-game recording started in background (PID=$BG_POST_GAME_PID)" | tee -a "$LOG_FILE"

  # Every Nth game: wait for post-game, then run evolution
  if [ $((GAME_COUNT % EVOLUTION_INTERVAL)) -eq 0 ]; then
    wait_for_post_game
    EVOLUTION_COUNT=$((EVOLUTION_COUNT + 1))
    AVG_SCORE=$(python3 "$PROJECT_ROOT/scripts/record_score.py" --avg 5 --game "$GAME" 2>/dev/null || echo "?.?")

    echo "" | tee -a "$LOG_FILE"
    echo "--- EVOLUTION #$EVOLUTION_COUNT (avg $AVG_SCORE/10, $STEPS steps) ---" | tee -a "$LOG_FILE"

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  EVOLUTION — Replace with your game's evolution entry point   ║
    # ║  See base_evolution.py for the framework's evolution tools    ║
    # ╚════════════════════════════════════════════════════════════════╝
    echo "  TODO: Add your evolution command here" | tee -a "$LOG_FILE"
    # Example:
    # python3 -c "
    # from games.${GAME}.evolve import run_evolution
    # run_evolution(max_budget_usd=5.0)
    # " 2>&1 | tee -a "$LOG_FILE" || true

    echo "--- EVOLUTION #$EVOLUTION_COUNT COMPLETE ---" | tee -a "$LOG_FILE"
  fi

  echo "=== GAME $GAME_COUNT COMPLETE ===" | tee -a "$LOG_FILE"
  sleep 1
done
