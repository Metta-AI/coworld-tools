#!/bin/bash
# ============================================================================
# CogsGuard A1×A2 Reward Variant Sweep — Phase 1
# Sweeps A1 (forced roles on/off) × A2 (reward variant combos)
# Fixed A3: gamma=0.999, gae_lambda=0.95, bptt=128, ent_coef=0.05
# Each run: 50M steps, ~27 min on GPU. Total: 20 runs, ~9 hours.
# ============================================================================

set -euo pipefail

COGAMES_DIR="$HOME/projects/cogames"
TRAIN_PY="$HOME/projects/cogames-env/lib64/python3.12/site-packages/cogames/train.py"
RESULTS_CSV="$COGAMES_DIR/sweep_results.csv"
LOG_DIR="$COGAMES_DIR/sweep_logs"

source ~/projects/cogames-env/bin/activate
cd "$COGAMES_DIR"
mkdir -p "$LOG_DIR"

# ── Set checkpoint_interval high to save disk ──────────────────────────────
sed -i 's/checkpoint_interval=50/checkpoint_interval=999/' "$TRAIN_PY" 2>/dev/null || true

# ── CSV header ──────────────────────────────────────────────────────────────
echo "run_id,variants,hearts_gained,heart_amount,aligned_junctions,aligner_amount,miner_amount,scout_amount,scrambler_amount,carbon_amount,expl_var,entropy,clipfrac,approx_kl,sps,epoch,duration_s" > "$RESULTS_CSV"

# ── Experiment definitions ──────────────────────────────────────────────────
# Format: "RUN_NAME|VARIANT_FLAGS"
EXPERIMENTS=(
    # --- A1 OFF (no forced roles) ---
    "noA1_credit|-v credit"
    "noA1_obj25|-v objective_mine:25"
    "noA1_obj50|-v objective_mine:50"
    "noA1_mile|-v milestones"
    "noA1_credit_obj25|-v credit -v objective_mine:25"
    "noA1_credit_obj50|-v credit -v objective_mine:50"
    "noA1_mile_obj25|-v milestones -v objective_mine:25"
    "noA1_mile_obj50|-v milestones -v objective_mine:50"
    "noA1_mile_credit|-v milestones -v credit"
    "noA1_mile_credit_obj25|-v milestones -v credit -v objective_mine:25"

    # --- A1 ON (forced roles) ---
    "A1_credit|-v forced_role_vibes -v credit"
    "A1_obj25|-v forced_role_vibes -v objective_mine:25"
    "A1_obj50|-v forced_role_vibes -v objective_mine:50"
    "A1_mile|-v forced_role_vibes -v milestones"
    "A1_credit_obj25|-v forced_role_vibes -v credit -v objective_mine:25"
    "A1_credit_obj50|-v forced_role_vibes -v credit -v objective_mine:50"
    "A1_mile_obj25|-v forced_role_vibes -v milestones -v objective_mine:25"
    "A1_mile_obj50|-v forced_role_vibes -v milestones -v objective_mine:50"
    "A1_mile_credit|-v forced_role_vibes -v milestones -v credit"
    "A1_mile_credit_obj25|-v forced_role_vibes -v milestones -v credit -v objective_mine:25"
)

# ── Extract metrics from PufferLib rich-text log ────────────────────────────
# PufferLib outputs truncated key names in a table format.
# We grep for the last occurrence of each metric pattern.
extract_metric() {
    local logfile="$1"
    local pattern="$2"
    local default="${3:-0}"
    local val
    val=$(grep -oP "${pattern}\s+[-\d.]+" "$logfile" 2>/dev/null | tail -1 | grep -oP '[-\d.]+$' || echo "$default")
    echo "$val"
}

extract_all() {
    local logfile="$1"
    local hearts_gained=$(extract_metric "$logfile" "heart\.gained")
    local heart_amount=$(extract_metric "$logfile" "cogs/heart\.amount")
    local aligned_j=$(extract_metric "$logfile" "aligned\.jun")
    local aligner=$(extract_metric "$logfile" "cogs/aligner\.amo")
    local miner=$(extract_metric "$logfile" "cogs/miner\.amo" "N/A")
    local scout=$(extract_metric "$logfile" "cogs/scout\.amo" "N/A")
    local scrambler=$(extract_metric "$logfile" "cogs/scrambler\.amo" "N/A")
    local carbon=$(extract_metric "$logfile" "cogs/carbon\.amou")
    local expl_var=$(extract_metric "$logfile" "explained_var")
    local entropy=$(extract_metric "$logfile" "entropy\s")
    local clipfrac=$(extract_metric "$logfile" "clipfrac\s")
    local approx_kl=$(extract_metric "$logfile" "approx_kl\s")
    local sps=$(extract_metric "$logfile" "SPS\s")
    local epoch=$(extract_metric "$logfile" "Epoch\s")
    echo "$hearts_gained,$heart_amount,$aligned_j,$aligner,$miner,$scout,$scrambler,$carbon,$expl_var,$entropy,$clipfrac,$approx_kl,$sps,$epoch"
}

# ── Run sweep ───────────────────────────────────────────────────────────────
TOTAL=${#EXPERIMENTS[@]}
echo "============================================"
echo "CogsGuard A1×A2 Sweep — Phase 1"
echo "Experiments: $TOTAL"
echo "Est. time: $((TOTAL * 27)) min (~$((TOTAL * 27 / 60)) hrs)"
echo "Results: $RESULTS_CSV"
echo "Started: $(date)"
echo "============================================"

for i in "${!EXPERIMENTS[@]}"; do
    IFS='|' read -r RUN_NAME VARIANT_FLAGS <<< "${EXPERIMENTS[$i]}"
    RUN_NUM=$((i + 1))
    LOGFILE="$LOG_DIR/${RUN_NAME}.log"

    echo ""
    echo "──────────────────────────────────────────"
    echo "[$RUN_NUM/$TOTAL] $RUN_NAME  $(date '+%H:%M')"
    echo "  Variants: $VARIANT_FLAGS"
    echo "──────────────────────────────────────────"

    START_TIME=$(date +%s)

    # Run training (eval expands variant flags correctly)
    eval cogames train \
        -m cogsguard_arena.basic \
        -p class=tutorial \
        --cogs 8 \
        --steps 50000000 \
        --device auto \
        $VARIANT_FLAGS \
        > "$LOGFILE" 2>&1 || true

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    # Extract metrics from the last frame
    METRICS=$(extract_all "$LOGFILE")

    # Append to CSV
    echo "\"$RUN_NAME\",\"$VARIANT_FLAGS\",$METRICS,$DURATION" >> "$RESULTS_CSV"

    # Clean up checkpoints to save disk
    LATEST_RUN_DIR=$(ls -td "$COGAMES_DIR/train_dir"/*/ 2>/dev/null | head -1)
    if [ -n "$LATEST_RUN_DIR" ]; then
        # Remove ALL intermediate checkpoints, keep only final + trainer_state
        FINAL=$(ls "$LATEST_RUN_DIR"model_*.pt 2>/dev/null | sort -V | tail -1)
        for f in "$LATEST_RUN_DIR"model_*.pt; do
            [ "$f" != "$FINAL" ] && rm -f "$f" 2>/dev/null
        done
        # Remove root .pt copy
        RUN_ID=$(basename "$LATEST_RUN_DIR" /)
        rm -f "$COGAMES_DIR/train_dir/${RUN_ID}.pt" 2>/dev/null
    fi

    echo "  Done in ${DURATION}s | hearts=$(echo $METRICS | cut -d, -f1) junctions=$(echo $METRICS | cut -d, -f3) gear=$(echo $METRICS | cut -d, -f4) expl_var=$(echo $METRICS | cut -d, -f9)"
    echo "  Disk: $(df -h / | tail -1 | awk '{print $4}') free"
done

# ── Restore checkpoint_interval ────────────────────────────────────────────
sed -i 's/checkpoint_interval=999/checkpoint_interval=50/' "$TRAIN_PY" 2>/dev/null || true

echo ""
echo "============================================"
echo "Sweep complete! $(date)"
echo "============================================"
echo ""
echo "Results:"
column -t -s',' "$RESULTS_CSV" 2>/dev/null || cat "$RESULTS_CSV"
