#!/bin/bash
# ============================================================================
# CogsGuard A1.5: Individual Role Training
# Train each role separately using tutorial missions.
# PI priority: this should be the first step, before kickstarting.
# ============================================================================

set -euo pipefail

COGAMES_DIR="$HOME/projects/cogames"
LOG_DIR="$COGAMES_DIR/a15_logs"
RESULTS_CSV="$COGAMES_DIR/a15_results.csv"

source ~/projects/cogames-env/bin/activate
cd "$COGAMES_DIR"
mkdir -p "$LOG_DIR"

# CSV header
echo "run_id,mission,steps,hearts_gained,aligned_junctions,expl_var,entropy,clipfrac,approx_kl,duration_s" > "$RESULTS_CSV"

# Metric extraction
extract_metric() {
    local logfile="$1"
    local pattern="$2"
    local default="${3:-0}"
    grep -oP "${pattern}[^\d]*[\d.]+" "$logfile" 2>/dev/null | tail -1 | grep -oP '[\d.]+$' || echo "$default"
}

extract_all() {
    local logfile="$1"
    local hearts=$(extract_metric "$logfile" "heart\.gained")
    local junctions=$(extract_metric "$logfile" "aligned\.jun")
    local expl_var=$(extract_metric "$logfile" "explained_var")
    local entropy=$(extract_metric "$logfile" "entropy\s")
    local clipfrac=$(extract_metric "$logfile" "clipfrac\s")
    local approx_kl=$(extract_metric "$logfile" "approx_kl\s")
    echo "$hearts,$junctions,$expl_var,$entropy,$clipfrac,$approx_kl"
}

# ── Experiments ─────────────────────────────────────────────────────────────
# Each tutorial mission has built-in role forcing + reward shaping.
# Training on machina_1 (50x50) which is what the tutorials use.
# 50M steps each, ~27 min on GPU.

EXPERIMENTS=(
    "miner_50M|miner_tutorial|50000000"
    "aligner_50M|aligner_tutorial|50000000"
    "scout_50M|scout_tutorial|50000000"
    "scrambler_50M|scrambler_tutorial|50000000"
)

TOTAL=${#EXPERIMENTS[@]}
echo "============================================"
echo "CogsGuard A1.5: Individual Role Training"
echo "Experiments: $TOTAL"
echo "Each: 50M steps on tutorial missions (machina_1 50x50)"
echo "Results: $RESULTS_CSV"
echo "Started: $(date)"
echo "============================================"

for i in "${!EXPERIMENTS[@]}"; do
    IFS='|' read -r RUN_ID MISSION STEPS <<< "${EXPERIMENTS[$i]}"
    RUN_NUM=$((i + 1))
    LOGFILE="$LOG_DIR/${RUN_ID}.log"

    echo ""
    echo "──────────────────────────────────────────"
    echo "[$RUN_NUM/$TOTAL] $RUN_ID  $(date '+%H:%M')"
    echo "  Mission: $MISSION"
    echo "  Steps: $STEPS"
    echo "──────────────────────────────────────────"

    START_TIME=$(date +%s)

    cogames train \
        -m "$MISSION" \
        -p class=tutorial \
        --steps "$STEPS" \
        --device auto \
        > "$LOGFILE" 2>&1 || true

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    METRICS=$(extract_all "$LOGFILE")
    echo "\"$RUN_ID\",\"$MISSION\",$STEPS,$METRICS,$DURATION" >> "$RESULTS_CSV"

    # Clean checkpoints (keep only final)
    LATEST_RUN_DIR=$(ls -td "$COGAMES_DIR/train_dir"/*/ 2>/dev/null | head -1)
    if [ -n "$LATEST_RUN_DIR" ]; then
        FINAL=$(ls "$LATEST_RUN_DIR"model_*.pt 2>/dev/null | sort -V | tail -1)
        for f in "$LATEST_RUN_DIR"model_*.pt; do
            [ "$f" != "$FINAL" ] && rm -f "$f" 2>/dev/null
        done
        RUN_DIR_ID=$(basename "$LATEST_RUN_DIR" /)
        rm -f "$COGAMES_DIR/train_dir/${RUN_DIR_ID}.pt" 2>/dev/null
    fi

    echo "  Done in ${DURATION}s | junctions=$(echo $METRICS | cut -d, -f2) expl_var=$(echo $METRICS | cut -d, -f3)"
    echo "  Disk: $(df -h / | tail -1 | awk '{print $4}') free"
done

echo ""
echo "============================================"
echo "A1.5 complete! $(date)"
echo "============================================"
echo ""
echo "=== RESULTS ==="
column -t -s',' "$RESULTS_CSV" 2>/dev/null || cat "$RESULTS_CSV"
echo ""
echo "Next steps:"
echo "  1. Upload best role checkpoints:"
echo "     cogames upload -p class=tutorial,data=train_dir/<DIR>/model_*.pt -n 'mahault.miner_v1' --skip-validation"
echo "  2. Check if aligner learned gear acquisition (key diagnostic)"
echo "  3. If yes: combine 4 miners + 4 aligners for submission"
