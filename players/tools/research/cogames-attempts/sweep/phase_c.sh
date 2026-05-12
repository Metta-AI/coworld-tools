#!/bin/bash
# Phase C: Combination Sweep (FIXED)
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
echo 'Phase C: Combination Sweep'
echo '========================================'
date

# C1: LSTM + sLSTM sequential (GPU 0)
echo '[GPU 0] Starting C1: L,S sequential...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexLSSeqPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/C1_ls_seq \
    > $RESULTS/C1_ls_seq.log 2>&1
) &
PID_C1=$!

# C2: LSTM + sLSTM routed Column (GPU 1)
echo '[GPU 1] Starting C2: L,S routed...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexLSPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/C2_ls_routed \
    > $RESULTS/C2_ls_routed.log 2>&1
) &
PID_C2=$!

# C3: Ag,A,S routed (GPU 2)
echo '[GPU 2] Starting C3: Ag,A,S...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexAgasPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/C3_agas \
    > $RESULTS/C3_agas.log 2>&1
) &
PID_C3=$!

# C4: Ag,A,S sequential (GPU 3)
echo '[GPU 3] Starting C4: Ag,A,S sequential...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexAgasSeqPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/C4_agas_seq \
    > $RESULTS/C4_agas_seq.log 2>&1
) &
PID_C4=$!

echo "PIDs: C1=$PID_C1 C2=$PID_C2 C3=$PID_C3 C4=$PID_C4"
echo "Waiting for all to complete..."

wait $PID_C1 || echo "C1 exited with code $?"
wait $PID_C2 || echo "C2 exited with code $?"
wait $PID_C3 || echo "C3 exited with code $?"
wait $PID_C4 || echo "C4 exited with code $?"

echo ''
echo '========================================'
echo 'Phase C COMPLETE'
echo '========================================'
date

# Extract results
for name in C1_ls_seq C2_ls_routed C3_agas C4_agas_seq; do
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
for name in C1_ls_seq C2_ls_routed C3_agas C4_agas_seq; do
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
