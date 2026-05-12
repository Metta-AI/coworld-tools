#!/bin/bash
# Round 5: Advantage Collapse Fixes
# Targeting the root cause: value function overfitting + stale optimizer
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
mkdir -p $RESULTS

PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

echo '========================================'
echo 'Round 5: Advantage Collapse Fixes'
echo '========================================'
date

# GPU 0: vf_coef=0.5 (standard, vs current 2.0 = 4x too high)
echo '[GPU 0] Starting E1: vf_coef=0.5...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES=''
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/E1_slstm_vf05 \
    > $RESULTS/E1_slstm_vf05.log 2>&1
) &
PID_E1=$!

# GPU 1: Adam-Rel (reset optimizer timestep each epoch)
echo '[GPU 1] Starting E2: Adam-Rel...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  export SWEEP_FIXES='adam_rel'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/E2_slstm_adamrel \
    > $RESULTS/E2_slstm_adamrel.log 2>&1
) &
PID_E2=$!

# GPU 2: Combined: vf_coef=0.5 + Adam-Rel + Soft S+P
echo '[GPU 2] Starting E3: Combined fix...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES='adam_rel,shrink_perturb'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/E3_slstm_combined \
    > $RESULTS/E3_slstm_combined.log 2>&1
) &
PID_E3=$!

# GPU 3: Native LSTM with vf_coef=0.5 (baseline comparison)
echo '[GPU 3] Starting E4: Native LSTM vf_coef=0.5...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES=''
  python3 $PATCH train -m $MISSION -p starter \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/E4_lstm_vf05 \
    > $RESULTS/E4_lstm_vf05.log 2>&1
) &
PID_E4=$!

echo "PIDs: E1=$PID_E1 E2=$PID_E2 E3=$PID_E3 E4=$PID_E4"
echo "Waiting for all to complete..."

wait $PID_E1 || echo "E1 exited with code $?"
wait $PID_E2 || echo "E2 exited with code $?"
wait $PID_E3 || echo "E3 exited with code $?"
wait $PID_E4 || echo "E4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 5 COMPLETE'
echo '========================================'
date

# Extract results
for name in E1_slstm_vf05 E2_slstm_adamrel E3_slstm_combined E4_lstm_vf05; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    FINAL_ENT=$(grep 'entropy' "$LOG" 2>/dev/null | tail -1 | grep -o 'entropy[^0-9]*[0-9.]*' | grep -o '[0-9.]*$')
    # Check if clipfrac collapses
    LAST_CF=$(grep 'clipfrac' "$LOG" 2>/dev/null | tail -n 5 | grep -o 'clipfrac[^0-9]*[0-9.]*' | grep -o '[0-9.]*$' | tail -1)
    echo "$name: peak_j=$PEAK_J entropy=$FINAL_ENT final_clipfrac=$LAST_CF"
  else
    echo "$name: NO LOG"
  fi
done

# Trim checkpoints
for name in E1_slstm_vf05 E2_slstm_adamrel E3_slstm_combined E4_lstm_vf05; do
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
