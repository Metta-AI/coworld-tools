#!/bin/bash
# Round 3: B6 rerun (axon fix) + C1/C2 combos + D1 sLSTM ent tuning
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
mkdir -p $RESULTS

PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

echo '========================================'
echo 'Round 3: B6 fix + C1/C2 + D1'
echo '========================================'
date

# GPU 0: B6 sLSTM axonified (rerun with state-size fix)
echo '[GPU 0] Starting B6v2: sLSTM axonified...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMAxonPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/B6_slstm_axon_v2 \
    > $RESULTS/B6_slstm_axon_v2.log 2>&1
) &
PID_B6=$!

# GPU 1: C1 LSTM+sLSTM sequential
echo '[GPU 1] Starting C1: L,S sequential...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexLSSeqPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/C1_ls_seq \
    > $RESULTS/C1_ls_seq.log 2>&1
) &
PID_C1=$!

# GPU 2: C2 LSTM+sLSTM routed Column
echo '[GPU 2] Starting C2: L,S routed...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexLSPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/C2_ls_routed \
    > $RESULTS/C2_ls_routed.log 2>&1
) &
PID_C2=$!

# GPU 3: D1 sLSTM with ent=0.05 (hyperparam tuning)
echo '[GPU 3] Starting D1: sLSTM ent=0.05...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"ent_coef": 0.05}'
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/D1_slstm_ent05 \
    > $RESULTS/D1_slstm_ent05.log 2>&1
) &
PID_D1=$!

echo "PIDs: B6=$PID_B6 C1=$PID_C1 C2=$PID_C2 D1=$PID_D1"
echo "Waiting for all to complete..."

wait $PID_B6 || echo "B6 exited with code $?"
wait $PID_C1 || echo "C1 exited with code $?"
wait $PID_C2 || echo "C2 exited with code $?"
wait $PID_D1 || echo "D1 exited with code $?"

echo ''
echo '========================================'
echo 'Round 3 COMPLETE'
echo '========================================'
date

# Extract results
for name in B6_slstm_axon_v2 C1_ls_seq C2_ls_routed D1_slstm_ent05; do
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
for name in B6_slstm_axon_v2 C1_ls_seq C2_ls_routed D1_slstm_ent05; do
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
