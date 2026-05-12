#!/bin/bash
# Phase A: Baseline Calibration
# Run on GPUs 1-3 (GPU 0 has active AIF eval)
# A1 already done: 3.0j native LSTM with 0.19 defaults
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
mkdir -p $RESULTS

PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8
HP_018='{"ent_coef":0.05,"bptt_horizon":128,"gamma":0.999,"gae_lambda":0.95,"vf_coef":0.5,"max_grad_norm":0.5}'

echo '========================================'
echo 'Phase A: Baseline Calibration (GPUs 1-3)'
echo '========================================'
echo 'A1: Already done (3.0j native LSTM 0.19 defaults)'
date

# A2: Native LSTM with 0.18 hyperparams (GPU 1)
echo '[GPU 1] Starting A2: Native LSTM + 0.18 hyperparams...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$HP_018"
  python3 $PATCH train -m $MISSION --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/A2_native_lstm_018hp \
    > $RESULTS/A2_native_lstm_018hp.log 2>&1
) &
PID_A2=$!

# A3: Cortex-LSTM with 0.18 hyperparams (GPU 2)
echo '[GPU 2] Starting A3: Cortex-LSTM + 0.18 hyperparams...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$HP_018"
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexPolicy,kw.preset=lstm' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/A3_cortex_lstm_018hp \
    > $RESULTS/A3_cortex_lstm_018hp.log 2>&1
) &
PID_A3=$!

# A4: Cortex-LSTM with 0.19 defaults (GPU 3)
# Tests whether Cortex wrapper adds overhead vs native LSTM
echo '[GPU 3] Starting A4: Cortex-LSTM + 0.19 defaults...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexPolicy,kw.preset=lstm' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/A4_cortex_lstm_019defaults \
    > $RESULTS/A4_cortex_lstm_019defaults.log 2>&1
) &
PID_A4=$!

echo "PIDs: A2=$PID_A2 A3=$PID_A3 A4=$PID_A4"
echo "Waiting for all to complete..."

wait $PID_A2 || echo "A2 exited with code $?"
wait $PID_A3 || echo "A3 exited with code $?"
wait $PID_A4 || echo "A4 exited with code $?"

echo ''
echo '========================================'
echo 'Phase A COMPLETE'
echo '========================================'
date

# Extract results
for name in A2_native_lstm_018hp A3_cortex_lstm_018hp A4_cortex_lstm_019defaults; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -oP 'game/cogs/aligned\.jun.*?\s+\K[\d.]+' "$LOG" 2>/dev/null | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    FINAL_ENT=$(grep -oP 'entropy\s+\K[\d.]+' "$LOG" 2>/dev/null | tail -1)
    FINAL_CLIP=$(grep -oP 'clipfrac\s+\K[\d.]+' "$LOG" 2>/dev/null | tail -1)
    echo "$name: peak_junctions=$PEAK_J entropy=$FINAL_ENT clipfrac=$FINAL_CLIP"
  else
    echo "$name: NO LOG"
  fi
done

# Trim checkpoints
for name in A2_native_lstm_018hp A3_cortex_lstm_018hp A4_cortex_lstm_019defaults; do
  CKPT=$RESULTS/$name
  for RUN_DIR in "$CKPT"/*/; do
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
