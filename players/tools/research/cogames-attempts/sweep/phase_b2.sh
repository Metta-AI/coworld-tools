#!/bin/bash
# Phase B Round 2: Axonified + Depth + Conv1d (FIXED)
# Uses dedicated class per preset (cogames train drops kw.* init_kwargs)
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
mkdir -p $RESULTS

PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

echo '========================================'
echo 'Phase B2: Axonified + Depth + Conv1d'
echo '========================================'
date

# B5: CausalConv1d (GPU 0)
echo '[GPU 0] Starting B5: CausalConv1d...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexConv1dPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/B5_conv1d \
    > $RESULTS/B5_conv1d.log 2>&1
) &
PID_B5=$!

# B6: sLSTM axonified (GPU 1)
echo '[GPU 1] Starting B6: sLSTM axonified...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMAxonPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/B6_slstm_axon \
    > $RESULTS/B6_slstm_axon.log 2>&1
) &
PID_B6=$!

# B7: mLSTM axonified (GPU 2)
echo '[GPU 2] Starting B7: mLSTM axonified...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexMLSTMAxonPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/B7_mlstm_axon \
    > $RESULTS/B7_mlstm_axon.log 2>&1
) &
PID_B7=$!

# B8: Two LSTM layers (GPU 3)
echo '[GPU 3] Starting B8: LSTM x2 layers...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexLSTM2Policy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/B8_lstm2 \
    > $RESULTS/B8_lstm2.log 2>&1
) &
PID_B8=$!

echo "PIDs: B5=$PID_B5 B6=$PID_B6 B7=$PID_B7 B8=$PID_B8"
echo "Waiting for all to complete..."

wait $PID_B5 || echo "B5 exited with code $?"
wait $PID_B6 || echo "B6 exited with code $?"
wait $PID_B7 || echo "B7 exited with code $?"
wait $PID_B8 || echo "B8 exited with code $?"

echo ''
echo '========================================'
echo 'Phase B2 COMPLETE'
echo '========================================'
date

# Extract results
for name in B5_conv1d B6_slstm_axon B7_mlstm_axon B8_lstm2; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep "cogs/aligned" "$LOG" 2>/dev/null | sed -n 's/.*cogs\/aligned[^0-9]*\([0-9.]*\).*/\1/p' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    FINAL_ENT=$(grep "entropy" "$LOG" 2>/dev/null | sed -n 's/.*entropy[^0-9]*\([0-9.]*\).*/\1/p' | tail -1)
    echo "$name: peak_junctions=$PEAK_J entropy=$FINAL_ENT"
  else
    echo "$name: NO LOG"
  fi
done

# Trim checkpoints
for name in B5_conv1d B6_slstm_axon B7_mlstm_axon B8_lstm2; do
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
