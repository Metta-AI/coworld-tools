#!/bin/bash
# Phase B Round 1: Single-Cell Architecture Sweep (FIXED)
# cogames train drops kw.* init_kwargs! Must use dedicated class per preset.
# Tests sLSTM, mLSTM, AGaLiTe, XL on all 4 GPUs
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
mkdir -p $RESULTS

PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

echo '========================================'
echo 'Phase B1: Single-Cell Architecture Sweep'
echo '========================================'
date

# B1: sLSTM (GPU 0) — uses CortexSLSTMPolicy class
echo '[GPU 0] Starting B1: sLSTM...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/B1_slstm \
    > $RESULTS/B1_slstm.log 2>&1
) &
PID_B1=$!

# B2: mLSTM (GPU 1)
echo '[GPU 1] Starting B2: mLSTM...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexMLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/B2_mlstm \
    > $RESULTS/B2_mlstm.log 2>&1
) &
PID_B2=$!

# B3: AGaLiTe (GPU 2)
echo '[GPU 2] Starting B3: AGaLiTe...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexAGaLiTePolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/B3_agalite \
    > $RESULTS/B3_agalite.log 2>&1
) &
PID_B3=$!

# B4: XL (GPU 3)
echo '[GPU 3] Starting B4: XL...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexXLPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/B4_xl \
    > $RESULTS/B4_xl.log 2>&1
) &
PID_B4=$!

echo "PIDs: B1=$PID_B1 B2=$PID_B2 B3=$PID_B3 B4=$PID_B4"
echo "Waiting for all to complete..."

wait $PID_B1 || echo "B1 exited with code $?"
wait $PID_B2 || echo "B2 exited with code $?"
wait $PID_B3 || echo "B3 exited with code $?"
wait $PID_B4 || echo "B4 exited with code $?"

echo ''
echo '========================================'
echo 'Phase B1 COMPLETE'
echo '========================================'
date

# Extract results
for name in B1_slstm B2_mlstm B3_agalite B4_xl; do
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
for name in B1_slstm B2_mlstm B3_agalite B4_xl; do
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
