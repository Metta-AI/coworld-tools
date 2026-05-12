#!/bin/bash
# ============================================================================
# CogsGuard Phase 2a: A3 Hyperparameter Sweep (Arena)
# Top 3 configs from Phase 1 × A3 hyperparams (ent_coef × update_epochs)
# Each run: 50M steps, ~27 min on GPU. Total: 18 runs, ~8 hours.
# ============================================================================

set -euo pipefail

COGAMES_DIR="$HOME/projects/cogames"
TRAIN_PY="$HOME/projects/cogames-env/lib64/python3.12/site-packages/cogames/train.py"
TRAIN_BAK="$TRAIN_PY.phase2bak"
RESULTS_CSV="$COGAMES_DIR/sweep_phase2_results.csv"
LOG_DIR="$COGAMES_DIR/sweep_phase2_logs"

source ~/projects/cogames-env/bin/activate
cd "$COGAMES_DIR"
mkdir -p "$LOG_DIR"

# Backup train.py
cp "$TRAIN_PY" "$TRAIN_BAK"

# Set checkpoint_interval high to save disk
sed -i 's/checkpoint_interval=50/checkpoint_interval=999/' "$TRAIN_PY" 2>/dev/null || true

# ── CSV header ──────────────────────────────────────────────────────────────
echo "run_id,config,ent_coef,update_epochs,hearts_gained,aligned_junctions,expl_var,entropy,clipfrac,approx_kl,aligner_amt,carbon_amt,heart_amt,duration_s" > "$RESULTS_CSV"

# ── Top 3 configs from Phase 1 ──────────────────────────────────────────────
# 1. A1_credit_obj50: forced_role_vibes + credit + objective_mine:50 (2.500 junctions)
# 2. A1_mile_credit: forced_role_vibes + milestones + credit (2.450 junctions)
# 3. noA1_mile: milestones (2.417 junctions)

CONFIGS=(
    "A1_credit_obj50|-v forced_role_vibes -v credit -v objective_mine:50"
    "A1_mile_credit|-v forced_role_vibes -v milestones -v credit"
    "noA1_mile|-v milestones"
)

# ── A3 hyperparams to sweep ────────────────────────────────────────────────
ENT_COEFS=(0.03 0.05 0.07)
UPDATE_EPOCHS=(1 3)

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

# ── Patch train.py hyperparams ─────────────────────────────────────────────
patch_hparams() {
    local ent="$1"
    local epochs="$2"
    sed -i "s/ent_coef=0\.[0-9]*/ent_coef=$ent/" "$TRAIN_PY"
    sed -i "s/update_epochs=[0-9]*/update_epochs=$epochs/" "$TRAIN_PY"
}

# ── Count experiments ──────────────────────────────────────────────────────
TOTAL=$(( ${#CONFIGS[@]} * ${#ENT_COEFS[@]} * ${#UPDATE_EPOCHS[@]} ))
echo "============================================"
echo "CogsGuard Phase 2a: A3 Hyperparameter Sweep"
echo "Configs: ${#CONFIGS[@]} | ent_coefs: ${#ENT_COEFS[@]} | update_epochs: ${#UPDATE_EPOCHS[@]}"
echo "Total experiments: $TOTAL"
echo "Est. time: $((TOTAL * 27)) min (~$((TOTAL * 27 / 60)) hrs)"
echo "Results: $RESULTS_CSV"
echo "Started: $(date)"
echo "============================================"

RUN_NUM=0
for config_entry in "${CONFIGS[@]}"; do
    IFS='|' read -r CONFIG_NAME VARIANT_FLAGS <<< "$config_entry"

    for ent in "${ENT_COEFS[@]}"; do
        for epochs in "${UPDATE_EPOCHS[@]}"; do
            RUN_NUM=$((RUN_NUM + 1))
            RUN_ID="${CONFIG_NAME}_e${ent}_u${epochs}"
            LOGFILE="$LOG_DIR/${RUN_ID}.log"

            echo ""
            echo "──────────────────────────────────────────"
            echo "[$RUN_NUM/$TOTAL] $RUN_ID  $(date '+%H:%M')"
            echo "  Config: $VARIANT_FLAGS"
            echo "  ent_coef=$ent  update_epochs=$epochs"
            echo "──────────────────────────────────────────"

            # Patch hyperparams
            patch_hparams "$ent" "$epochs"

            START_TIME=$(date +%s)

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

            METRICS=$(extract_all "$LOGFILE")
            echo "\"$RUN_ID\",\"$CONFIG_NAME\",$ent,$epochs,$METRICS,$DURATION" >> "$RESULTS_CSV"

            # Clean checkpoints
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
    done
done

# ── Restore train.py ──────────────────────────────────────────────────────
cp "$TRAIN_BAK" "$TRAIN_PY"

echo ""
echo "============================================"
echo "Phase 2a complete! $(date)"
echo "============================================"
echo ""
column -t -s',' "$RESULTS_CSV" 2>/dev/null || cat "$RESULTS_CSV"

# ── Identify top 3 for Phase 2b ───────────────────────────────────────────
echo ""
echo "=== TOP 3 by aligned_junctions ==="
tail -n +2 "$RESULTS_CSV" | sort -t, -k6 -rn | head -3
