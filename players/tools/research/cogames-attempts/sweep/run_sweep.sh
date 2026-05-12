#!/bin/bash
# Hyperparameter sweep for Cortex architectures.
#
# Uses patch_and_train.py to monkey-patch cogames train hyperparams.
# Runs experiments sequentially (single GPU), trims checkpoints between runs.
#
# Usage:
#   cd ~/projects/cogames-agents
#   bash scripts/sweep/run_sweep.sh           # run all
#   bash scripts/sweep/run_sweep.sh 2         # run only config #2
#   bash scripts/sweep/run_sweep.sh 2 4       # run configs 2-4

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PATCH_TRAIN="$SCRIPT_DIR/patch_and_train.py"
RESULTS_DIR="./sweep_results"
STEPS=50000000
MISSION="cogsguard_arena.basic"
COGS=8

# Sweep configurations: name|policy_class|overrides_json
CONFIGS=(
    # Control: LSTM with cogames defaults (ent=0.05)
    'S17_lstm_control|cortex_policy.CortexPolicy|{}'
    # Ag,A,S sequential with higher entropy
    'S18_agas_seq_ent08|cortex_policy.CortexAgasSeqPolicy|{"ent_coef":0.08}'
    # Ag,A,S sequential with higher entropy + weight decay
    'S19_agas_seq_ent08_wd|cortex_policy.CortexAgasSeqPolicy|{"ent_coef":0.08,"weight_decay":0.0001}'
    # Ag,A,S sequential with much higher entropy
    'S20_agas_seq_ent12|cortex_policy.CortexAgasSeqPolicy|{"ent_coef":0.12}'
    # LSTM with higher entropy (does it also benefit?)
    'S21_lstm_ent08|cortex_policy.CortexPolicy|{"ent_coef":0.08}'
    # Ag,A,S sequential with u=3 + higher entropy
    'S22_agas_seq_u3_ent08|cortex_policy.CortexAgasSeqPolicy|{"ent_coef":0.08,"update_epochs":3}'
)

# Parse args: optional start and end indices
START=${1:-0}
END=${2:-$((${#CONFIGS[@]} - 1))}

mkdir -p "$RESULTS_DIR"

echo "========================================"
echo "CORTEX HYPERPARAMETER SWEEP"
echo "========================================"
echo "Configs: $START to $END (of ${#CONFIGS[@]} total)"
echo "Steps: $STEPS"
echo "Mission: $MISSION"
echo "Results: $RESULTS_DIR"
echo ""

# Print all configs
for i in "${!CONFIGS[@]}"; do
    IFS='|' read -r name policy overrides <<< "${CONFIGS[$i]}"
    marker=""
    if [ "$i" -ge "$START" ] && [ "$i" -le "$END" ]; then
        marker=" <-- WILL RUN"
    fi
    echo "  [$i] $name: $overrides$marker"
done
echo ""

# Summary file
SUMMARY="$RESULTS_DIR/sweep_summary.txt"
echo "name|peak_junctions|final_entropy|final_clipfrac|elapsed_min|overrides" > "$SUMMARY"

for i in $(seq "$START" "$END"); do
    IFS='|' read -r NAME POLICY OVERRIDES <<< "${CONFIGS[$i]}"

    echo ""
    echo "========================================"
    echo "[$((i+1))/${#CONFIGS[@]}] $NAME"
    echo "  Policy: $POLICY"
    echo "  Overrides: $OVERRIDES"
    echo "========================================"

    LOG="$RESULTS_DIR/${NAME}.log"
    CKPT_DIR="$RESULTS_DIR/${NAME}"

    START_TIME=$(date +%s)

    # Run training with monkey-patched hyperparams
    export PYTHONPATH=scripts/policy
    export SWEEP_OVERRIDES="$OVERRIDES"
    python3 "$PATCH_TRAIN" train \
        -m "$MISSION" \
        -p "class=$POLICY" \
        --cogs "$COGS" \
        --steps "$STEPS" \
        --device auto \
        --checkpoints "$CKPT_DIR" \
        > "$LOG" 2>&1 || true

    END_TIME=$(date +%s)
    ELAPSED=$(( (END_TIME - START_TIME) / 60 ))

    # Extract results from log
    PEAK_J=$(grep -oP 'game/cogs/aligned\.jun.*?\s+\K[\d.]+' "$LOG" | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    FINAL_ENT=$(grep -oP 'entropy\s+\K[\d.]+' "$LOG" | tail -1)
    FINAL_ENT=${FINAL_ENT:-0}
    FINAL_CLIP=$(grep -oP 'clipfrac\s+\K[\d.]+' "$LOG" | tail -1)
    FINAL_CLIP=${FINAL_CLIP:-0}

    echo ""
    echo "  Result: peak_junctions=$PEAK_J, entropy=$FINAL_ENT, clipfrac=$FINAL_CLIP, time=${ELAPSED}m"

    # Save to summary
    echo "$NAME|$PEAK_J|$FINAL_ENT|$FINAL_CLIP|$ELAPSED|$OVERRIDES" >> "$SUMMARY"

    # Trim checkpoints: keep only final model, remove trainer_state
    for RUN_DIR in "$CKPT_DIR"/*/; do
        if [ -d "$RUN_DIR" ]; then
            # Keep only the last model file
            MODELS=($(ls -1 "$RUN_DIR"model_*.pt 2>/dev/null | sort))
            if [ ${#MODELS[@]} -gt 1 ]; then
                for m in "${MODELS[@]:0:${#MODELS[@]}-1}"; do
                    rm -f "$m"
                    echo "  Trimmed: $(basename $m)"
                done
            fi
            # Remove trainer_state
            rm -f "$RUN_DIR/trainer_state.pt"
        fi
    done

    echo "  Disk: $(df -h / | tail -1 | awk '{print $4}') free"
done

echo ""
echo "========================================"
echo "SWEEP COMPLETE"
echo "========================================"
echo ""
column -t -s '|' "$SUMMARY"
echo ""
echo "Full results in: $RESULTS_DIR/"
