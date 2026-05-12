#!/bin/bash
# ============================================================================
# CogsGuard Phase 2b: Machina_1 Training (Tournament Map)
# Top 3 configs from Phase 2a, trained on machina_1 (88x88, 10K steps/ep)
# Each run: 50M steps, ~4-5 hrs on GPU. Total: 3 runs, ~15 hours.
# ============================================================================

set -euo pipefail

COGAMES_DIR="$HOME/projects/cogames"
TRAIN_PY="$HOME/projects/cogames-env/lib64/python3.12/site-packages/cogames/train.py"
TRAIN_BAK="$TRAIN_PY.phase2bbak"
RESULTS_CSV="$COGAMES_DIR/sweep_phase2b_results.csv"
LOG_DIR="$COGAMES_DIR/sweep_phase2b_logs"

source ~/projects/cogames-env/bin/activate
cd "$COGAMES_DIR"
mkdir -p "$LOG_DIR"

# Backup train.py
cp "$TRAIN_PY" "$TRAIN_BAK"

# Set checkpoint_interval high
sed -i 's/checkpoint_interval=50/checkpoint_interval=999/' "$TRAIN_PY" 2>/dev/null || true

# ── CSV header ──────────────────────────────────────────────────────────────
echo "run_id,config,ent_coef,update_epochs,hearts_gained,aligned_junctions,expl_var,entropy,clipfrac,approx_kl,aligner_amt,carbon_amt,heart_amt,duration_s" > "$RESULTS_CSV"

# ── Metric extraction (fixed for PufferLib Unicode ellipsis) ───────────────
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
    local aligner=$(extract_metric "$logfile" "cogs/aligner\.amo")
    local carbon=$(extract_metric "$logfile" "cogs/carbon\.amou")
    local heart_amt=$(extract_metric "$logfile" "cogs/heart\.amount")
    echo "$hearts,$junctions,$expl_var,$entropy,$clipfrac,$approx_kl,$aligner,$carbon,$heart_amt"
}

patch_hparams() {
    local ent="$1"
    local epochs="$2"
    sed -i "s/ent_coef=0\.[0-9]*/ent_coef=$ent/" "$TRAIN_PY"
    sed -i "s/update_epochs=[0-9]*/update_epochs=$epochs/" "$TRAIN_PY"
}

# ── Experiments ─────────────────────────────────────────────────────────────
# Updated with Phase 2a winners (2026-03-11).
# Top 3 configs by aligned_junctions on arena:
#   1. milestones alone, ent=0.03, u=3 → 3.214 junctions
#   2. milestones alone, ent=0.05, u=3 → 3.125 junctions
#   3. A1+milestones+credit, ent=0.05, u=3 → 1.857 junctions

EXPERIMENTS=(
    "m1_mile_e003_u3|0.03|3|-v milestones"
    "m1_mile_e005_u3|0.05|3|-v milestones"
    "m1_A1_mile_credit_e005_u3|0.05|3|-v forced_role_vibes -v milestones -v credit"
)

TOTAL=${#EXPERIMENTS[@]}
echo "============================================"
echo "CogsGuard Phase 2b: Machina_1 Training"
echo "Map: cogsguard_machina_1.basic (88x88, 10K steps/ep)"
echo "Experiments: $TOTAL"
echo "Est. time: $((TOTAL * 270)) min (~$((TOTAL * 270 / 60)) hrs)"
echo "Results: $RESULTS_CSV"
echo "Started: $(date)"
echo "============================================"

for i in "${!EXPERIMENTS[@]}"; do
    IFS='|' read -r RUN_ID ENT EPOCHS VARIANT_FLAGS <<< "${EXPERIMENTS[$i]}"
    RUN_NUM=$((i + 1))
    LOGFILE="$LOG_DIR/${RUN_ID}.log"

    echo ""
    echo "──────────────────────────────────────────"
    echo "[$RUN_NUM/$TOTAL] $RUN_ID  $(date '+%H:%M')"
    echo "  Config: $VARIANT_FLAGS"
    echo "  ent_coef=$ENT  update_epochs=$EPOCHS"
    echo "  Map: cogsguard_machina_1.basic"
    echo "──────────────────────────────────────────"

    patch_hparams "$ENT" "$EPOCHS"

    START_TIME=$(date +%s)

    eval cogames train \
        -m cogsguard_machina_1.basic \
        -p class=tutorial \
        --cogs 8 \
        --steps 50000000 \
        --device auto \
        $VARIANT_FLAGS \
        > "$LOGFILE" 2>&1 || true

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    METRICS=$(extract_all "$LOGFILE")
    echo "\"$RUN_ID\",\"${RUN_ID#m1_}\",$ENT,$EPOCHS,$METRICS,$DURATION" >> "$RESULTS_CSV"

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

# ── Restore train.py ──────────────────────────────────────────────────────
cp "$TRAIN_BAK" "$TRAIN_PY"

echo ""
echo "============================================"
echo "Phase 2b complete! $(date)"
echo "============================================"
echo ""
echo "=== MACHINA_1 RESULTS ==="
column -t -s',' "$RESULTS_CSV" 2>/dev/null || cat "$RESULTS_CSV"
echo ""
echo "Next: Submit best policy with"
echo "  cogames upload -p class=tutorial,data=train_dir/<BEST>/model_000191.pt -n 'mahault.<name>' --season beta-cvc"
