#!/bin/bash
# Round 5b: Relaunch E2/E3/E4 with fixes
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

echo '========================================'
echo 'Round 5b: Relaunch E2/E3/E4'
echo '========================================'
date

# GPU 1: Adam-Rel (fixed in-place step reset)
echo '[GPU 1] Starting E2v2: Adam-Rel...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  export SWEEP_FIXES='adam_rel'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/E2_slstm_adamrel_v2 \
    > $RESULTS/E2_slstm_adamrel_v2.log 2>&1
) &
PID_E2=$!

# GPU 2: Combined: vf_coef=0.5 + Adam-Rel + Soft S+P
echo '[GPU 2] Starting E3v2: Combined...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES='adam_rel,shrink_perturb'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/E3_slstm_combined_v2 \
    > $RESULTS/E3_slstm_combined_v2.log 2>&1
) &
PID_E3=$!

# GPU 3: Native LSTM with vf_coef=0.5 (use default trainable, not starter)
echo '[GPU 3] Starting E4v2: LSTM vf=0.5...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES=''
  python3 $PATCH train -m $MISSION \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/E4_lstm_vf05_v2 \
    > $RESULTS/E4_lstm_vf05_v2.log 2>&1
) &
PID_E4=$!

echo "PIDs: E2=$PID_E2 E3=$PID_E3 E4=$PID_E4"
echo "E1 still running on GPU 0"
echo "Waiting for E2/E3/E4..."

wait $PID_E2 || echo "E2 exited with code $?"
wait $PID_E3 || echo "E3 exited with code $?"
wait $PID_E4 || echo "E4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 5b COMPLETE'
echo '========================================'
date

for name in E2_slstm_adamrel_v2 E3_slstm_combined_v2 E4_lstm_vf05_v2; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    LAST_CF=$(grep 'clipfrac' "$LOG" 2>/dev/null | tail -n 5 | grep -o 'clipfrac[^0-9]*[0-9.]*' | grep -o '[0-9.]*$' | tail -1)
    echo "$name: peak_j=${PEAK_J:-0} final_clipfrac=$LAST_CF"
  else
    echo "$name: NO LOG"
  fi
done

for name in E2_slstm_adamrel_v2 E3_slstm_combined_v2 E4_lstm_vf05_v2; do
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
