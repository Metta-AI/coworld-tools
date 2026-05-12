#!/bin/bash
# Round 4: sLSTM hyperparam tuning + replication
# B1 replication + ent sweep + bptt + gamma
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
mkdir -p $RESULTS

PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

echo '========================================'
echo 'Round 4: sLSTM Tuning'
echo '========================================'
date

# GPU 0: B1 replication (verify 5.0j is reproducible)
echo '[GPU 0] Starting D2: sLSTM replication...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/D2_slstm_replicate \
    > $RESULTS/D2_slstm_replicate.log 2>&1
) &
PID_D2=$!

# GPU 1: sLSTM with bptt=128 (longer temporal window)
echo '[GPU 1] Starting D3: sLSTM bptt=128...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"bptt_horizon": 128}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/D3_slstm_bptt128 \
    > $RESULTS/D3_slstm_bptt128.log 2>&1
) &
PID_D3=$!

# GPU 2: sLSTM with gamma=0.999 (longer effective horizon)
echo '[GPU 2] Starting D4: sLSTM gamma=0.999...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"gamma": 0.999}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/D4_slstm_gamma999 \
    > $RESULTS/D4_slstm_gamma999.log 2>&1
) &
PID_D4=$!

# GPU 3: sLSTM with lr=0.0005 (lower learning rate, more stable)
echo '[GPU 3] Starting D5: sLSTM lr=0.0005...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"learning_rate": 0.0005}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/D5_slstm_lr0005 \
    > $RESULTS/D5_slstm_lr0005.log 2>&1
) &
PID_D5=$!

echo "PIDs: D2=$PID_D2 D3=$PID_D3 D4=$PID_D4 D5=$PID_D5"
echo "Waiting for all to complete..."

wait $PID_D2 || echo "D2 exited with code $?"
wait $PID_D3 || echo "D3 exited with code $?"
wait $PID_D4 || echo "D4 exited with code $?"
wait $PID_D5 || echo "D5 exited with code $?"

echo ''
echo '========================================'
echo 'Round 4 COMPLETE'
echo '========================================'
date

# Extract results
for name in D2_slstm_replicate D3_slstm_bptt128 D4_slstm_gamma999 D5_slstm_lr0005; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    FINAL_ENT=$(grep 'entropy' "$LOG" 2>/dev/null | tail -1 | grep -o 'entropy[^0-9]*[0-9.]*' | grep -o '[0-9.]*$')
    echo "$name: peak_junctions=$PEAK_J entropy=$FINAL_ENT"
  else
    echo "$name: NO LOG"
  fi
done

# Trim checkpoints
for name in D2_slstm_replicate D3_slstm_bptt128 D4_slstm_gamma999 D5_slstm_lr0005; do
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
