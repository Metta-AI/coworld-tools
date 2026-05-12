#!/bin/bash
# Parallel GPU sweep for Cortex architectures on cogames 0.19.
#
# Runs up to 4 experiments in parallel, one per GPU.
# Uses patch_and_train.py for hyperparam overrides.
#
# Usage:
#   cd ~/projects/cogames-agents
#   bash scripts/sweep/run_sweep_v19.sh A       # Phase A: baseline calibration
#   bash scripts/sweep/run_sweep_v19.sh B1      # Phase B round 1: single cells
#   bash scripts/sweep/run_sweep_v19.sh B2      # Phase B round 2: axonified + depth
#   bash scripts/sweep/run_sweep_v19.sh C       # Phase C: combinations (edit configs first)
#   bash scripts/sweep/run_sweep_v19.sh D1      # Phase D round 1: entropy + bptt
#   bash scripts/sweep/run_sweep_v19.sh D2      # Phase D round 2: lr + epochs + gamma
#   bash scripts/sweep/run_sweep_v19.sh D3      # Phase D round 3: combined best
#   bash scripts/sweep/run_sweep_v19.sh E       # Phase E: scaling + advanced

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PATCH_TRAIN="$SCRIPT_DIR/patch_and_train.py"
RESULTS_DIR="./results_v19"
STEPS=50000000
MISSION="arena"
COGS=8

# 0.18 hyperparams for restoration experiments
HP_018='{"ent_coef":0.05,"bptt_horizon":128,"gamma":0.999,"gae_lambda":0.95,"vf_coef":0.5,"max_grad_norm":0.5}'

PHASE="${1:?Usage: $0 <phase> (A, B1, B2, C, D1, D2, D3, E)}"

# Define experiments per phase: "name|policy_class|preset_kw|overrides_json|reward_variant"
# preset_kw: comma-separated key=value pairs for CortexPolicy kwargs (e.g. kw.preset=slstm)
# reward_variant: empty string or "-v variant1 -v variant2"
case "$PHASE" in
    A)
        EXPERIMENTS=(
            "A1_native_lstm_019defaults|starter||{}|"
            "A2_native_lstm_018hp|starter||${HP_018}|"
            "A3_cortex_lstm_018hp|cortex_policy.CortexPolicy|kw.preset=lstm|${HP_018}|"
            "A4_cortex_lstm_milestones|cortex_policy.CortexPolicy|kw.preset=lstm|{}|-v forced_role_vibes"
        )
        ;;
    B1)
        EXPERIMENTS=(
            "B1_slstm|cortex_policy.CortexPolicy|kw.preset=slstm|${HP_018}|"
            "B2_mlstm|cortex_policy.CortexPolicy|kw.preset=mlstm|${HP_018}|"
            "B3_agalite|cortex_policy.CortexPolicy|kw.preset=agalite|${HP_018}|"
            "B4_xl|cortex_policy.CortexPolicy|kw.preset=xl|${HP_018}|"
        )
        ;;
    B2)
        EXPERIMENTS=(
            "B5_conv1d|cortex_policy.CortexPolicy|kw.preset=conv1d|${HP_018}|"
            "B6_slstm_axon|cortex_policy.CortexPolicy|kw.preset=slstm_axon|${HP_018}|"
            "B7_mlstm_axon|cortex_policy.CortexPolicy|kw.preset=mlstm_axon|${HP_018}|"
            "B8_lstm2|cortex_policy.CortexPolicy|kw.preset=lstm2|${HP_018}|"
        )
        ;;
    C)
        # Fill in based on Phase B results — these are placeholder combos
        EXPERIMENTS=(
            "C1_ls_seq|cortex_policy.CortexPolicy|kw.preset=ls_seq|${HP_018}|"
            "C2_ls_routed|cortex_policy.CortexPolicy|kw.preset=ls|${HP_018}|"
            "C3_la_seq|cortex_policy.CortexPolicy|kw.preset=la_seq|${HP_018}|"
            "C4_agas_seq|cortex_policy.CortexPolicy|kw.preset=agas_seq|${HP_018}|"
        )
        ;;
    D1)
        # Entropy + bptt sweep on best architecture from B/C
        # Replace BEST_PRESET with actual winner
        BEST_PRESET="${BEST_PRESET:-lstm}"
        EXPERIMENTS=(
            "D1_ent003|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"ent_coef\":0.03}|"
            "D2_ent005|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"ent_coef\":0.05}|"
            "D3_ent008|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"ent_coef\":0.08}|"
            "D4_bptt128|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"bptt_horizon\":128}|"
        )
        ;;
    D2)
        BEST_PRESET="${BEST_PRESET:-lstm}"
        EXPERIMENTS=(
            "D5_lr0005|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"learning_rate\":0.0005}|"
            "D6_lr002|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"learning_rate\":0.002}|"
            "D7_u3|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"update_epochs\":3}|"
            "D8_gamma999|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"gamma\":0.999}|"
        )
        ;;
    D3)
        # Combined best — edit these after D1/D2 results
        BEST_PRESET="${BEST_PRESET:-lstm}"
        EXPERIMENTS=(
            "D9_best_combo|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"ent_coef\":0.05,\"gamma\":0.999}|"
            "D10_best_wd|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"ent_coef\":0.05,\"gamma\":0.999,\"weight_decay\":0.0001}|"
            "D11_best_milestones|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"ent_coef\":0.05,\"gamma\":0.999}|-v forced_role_vibes"
            "D12_best_mile_credit|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|{\"ent_coef\":0.05,\"gamma\":0.999}|-v forced_role_vibes -v credit"
        )
        ;;
    E)
        BEST_PRESET="${BEST_PRESET:-lstm}"
        BEST_HP="${BEST_HP:-{\"ent_coef\":0.05,\"gamma\":0.999}}"
        EXPERIMENTS=(
            "E1_100M|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|${BEST_HP}|"
            "E2_200M|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|${BEST_HP}|"
            "E3_d256|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET},kw.d_hidden=256|${BEST_HP}|"
            "E4_kickstart|cortex_policy.CortexPolicy|kw.preset=${BEST_PRESET}|${BEST_HP}|"
        )
        # Override steps for E1/E2
        E_STEPS=(100000000 200000000 50000000 50000000)
        ;;
    *)
        echo "Unknown phase: $PHASE"
        echo "Valid phases: A, B1, B2, C, D1, D2, D3, E"
        exit 1
        ;;
esac

mkdir -p "$RESULTS_DIR"

echo "========================================"
echo "CORTEX v0.19 SYSTEMATIC SWEEP — Phase $PHASE"
echo "========================================"
echo "Experiments: ${#EXPERIMENTS[@]}"
echo "Steps: $STEPS (per experiment)"
echo "Mission: $MISSION"
echo "GPUs: 4 parallel"
echo "Results: $RESULTS_DIR"
echo ""

# Print experiment plan
for i in "${!EXPERIMENTS[@]}"; do
    IFS='|' read -r name policy preset overrides variant <<< "${EXPERIMENTS[$i]}"
    echo "  [GPU $i] $name"
    echo "         policy=$policy preset=$preset"
    echo "         overrides=$overrides"
    [ -n "$variant" ] && echo "         variant=$variant"
done
echo ""

# Launch all experiments in parallel
PIDS=()
START_TIME=$(date +%s)

for i in "${!EXPERIMENTS[@]}"; do
    IFS='|' read -r NAME POLICY PRESET OVERRIDES VARIANT <<< "${EXPERIMENTS[$i]}"

    LOG="$RESULTS_DIR/${NAME}.log"
    CKPT_DIR="$RESULTS_DIR/${NAME}"

    # Determine steps for this experiment (Phase E may override)
    EXP_STEPS=$STEPS
    if [ -n "${E_STEPS[$i]+x}" ]; then
        EXP_STEPS=${E_STEPS[$i]}
    fi

    # Build policy arg with kw.* kwargs
    # Built-in policies (starter, random) don't use class= prefix
    if [[ "$POLICY" == "starter" || "$POLICY" == "random" ]]; then
        POLICY_ARG="$POLICY"
    else
        POLICY_ARG="class=$POLICY"
        if [ -n "$PRESET" ]; then
            # Parse comma-separated key=value pairs
            IFS=',' read -ra KV_PAIRS <<< "$PRESET"
            for kv in "${KV_PAIRS[@]}"; do
                POLICY_ARG="$POLICY_ARG,$kv"
            done
        fi
    fi

    # Build variant args
    VARIANT_ARGS=""
    if [ -n "$VARIANT" ]; then
        VARIANT_ARGS="$VARIANT"
    fi

    echo "[GPU $i] Starting $NAME (steps=$EXP_STEPS)..."

    (
        export CUDA_VISIBLE_DEVICES=$i
        export PYTHONPATH=scripts/policy
        export SWEEP_OVERRIDES="$OVERRIDES"

        python3 "$PATCH_TRAIN" train \
            -m "$MISSION" \
            -p "$POLICY_ARG" \
            --cogs "$COGS" \
            --steps "$EXP_STEPS" \
            --device auto \
            --checkpoints "$CKPT_DIR" \
            $VARIANT_ARGS \
            > "$LOG" 2>&1
    ) &
    PIDS+=($!)
done

echo ""
echo "All ${#EXPERIMENTS[@]} experiments launched. PIDs: ${PIDS[*]}"
echo "Waiting for completion..."
echo ""

# Wait for all experiments and collect exit codes
EXIT_CODES=()
for i in "${!PIDS[@]}"; do
    wait ${PIDS[$i]} || true
    EXIT_CODES+=($?)
done

END_TIME=$(date +%s)
TOTAL_ELAPSED=$(( (END_TIME - START_TIME) / 60 ))

echo ""
echo "========================================"
echo "Phase $PHASE COMPLETE — ${TOTAL_ELAPSED}m total"
echo "========================================"
echo ""

# Summary file
SUMMARY="$RESULTS_DIR/phase_${PHASE}_summary.txt"
echo "name|peak_junctions|final_entropy|final_clipfrac|exit_code|overrides" > "$SUMMARY"

# Extract results from each log
for i in "${!EXPERIMENTS[@]}"; do
    IFS='|' read -r NAME POLICY PRESET OVERRIDES VARIANT <<< "${EXPERIMENTS[$i]}"
    LOG="$RESULTS_DIR/${NAME}.log"

    if [ -f "$LOG" ]; then
        PEAK_J=$(grep -oP 'game/cogs/aligned\.jun.*?\s+\K[\d.]+' "$LOG" 2>/dev/null | sort -rn | head -1)
        PEAK_J=${PEAK_J:-0}
        FINAL_ENT=$(grep -oP 'entropy\s+\K[\d.]+' "$LOG" 2>/dev/null | tail -1)
        FINAL_ENT=${FINAL_ENT:-0}
        FINAL_CLIP=$(grep -oP 'clipfrac\s+\K[\d.]+' "$LOG" 2>/dev/null | tail -1)
        FINAL_CLIP=${FINAL_CLIP:-0}
    else
        PEAK_J=0; FINAL_ENT=0; FINAL_CLIP=0
    fi

    echo "$NAME|$PEAK_J|$FINAL_ENT|$FINAL_CLIP|${EXIT_CODES[$i]}|$OVERRIDES" >> "$SUMMARY"
done

echo "Results:"
echo ""
column -t -s '|' "$SUMMARY"

echo ""
echo "Logs: $RESULTS_DIR/*.log"
echo "Summary: $SUMMARY"
echo ""

# Trim checkpoints to save disk
echo "Trimming checkpoints..."
for i in "${!EXPERIMENTS[@]}"; do
    IFS='|' read -r NAME _ _ _ _ <<< "${EXPERIMENTS[$i]}"
    CKPT_DIR="$RESULTS_DIR/${NAME}"
    for RUN_DIR in "$CKPT_DIR"/*/; do
        if [ -d "$RUN_DIR" ]; then
            MODELS=($(ls -1 "${RUN_DIR}"model_*.pt 2>/dev/null | sort))
            if [ ${#MODELS[@]} -gt 1 ]; then
                for m in "${MODELS[@]:0:${#MODELS[@]}-1}"; do
                    rm -f "$m"
                done
            fi
            rm -f "$RUN_DIR/trainer_state.pt"
        fi
    done
done

echo "Disk: $(df -h / | tail -1 | awk '{print $4}') free"
echo ""
echo "Next: Review results, update EXPERIMENT_LOG.md, then run next phase."
