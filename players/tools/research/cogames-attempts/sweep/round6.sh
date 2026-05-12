#!/bin/bash
# Round 6: Phase A — Full 0.18 hyperparam restoration
# The REAL test: are 0.19's changed hyperparams the root cause of the performance drop?
# 0.18 had: ent=0.05, bptt=128, gamma=0.999, gae=0.95, vf=0.5, grad_norm=0.5
# 0.19 changed: ent=0.01, bptt=64, gamma=0.995, gae=0.90, vf=2.0, grad_norm=1.5
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

# Full 0.18 hyperparam set
HP_018='{"ent_coef":0.05,"bptt_horizon":128,"gamma":0.999,"gae_lambda":0.95,"vf_coef":0.5,"max_grad_norm":0.5}'

echo '========================================'
echo 'Round 6: 0.18 Hyperparam Restoration'
echo '========================================'
date

# GPU 0: sLSTM + full 0.18 hyperparams (the decisive test)
echo '[GPU 0] F1: sLSTM + 0.18 hyperparams...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$HP_018"
  export SWEEP_FIXES=''
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/F1_slstm_018hp \
    > $RESULTS/F1_slstm_018hp.log 2>&1
) &
PID_F1=$!

# GPU 1: Native LSTM + full 0.18 hyperparams (control — architecture comparison)
echo '[GPU 1] F2: Native LSTM + 0.18 hyperparams...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$HP_018"
  export SWEEP_FIXES=''
  python3 $PATCH train -m $MISSION \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/F2_lstm_018hp \
    > $RESULTS/F2_lstm_018hp.log 2>&1
) &
PID_F2=$!

# GPU 2: sLSTM + just ent=0.05 + vf=0.5 (isolate entropy effect)
echo '[GPU 2] F3: sLSTM + ent=0.05 + vf=0.5...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"ent_coef":0.05,"vf_coef":0.5}'
  export SWEEP_FIXES=''
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/F3_slstm_ent05_vf05 \
    > $RESULTS/F3_slstm_ent05_vf05.log 2>&1
) &
PID_F3=$!

# GPU 3: sLSTM + 0.18 hp + milestones (best possible combo)
echo '[GPU 3] F4: sLSTM + 0.18 hp + milestones...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$HP_018"
  export SWEEP_FIXES=''
  python3 $PATCH train -m $MISSION -v milestones -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/F4_slstm_018hp_milestones \
    > $RESULTS/F4_slstm_018hp_milestones.log 2>&1
) &
PID_F4=$!

echo "PIDs: F1=$PID_F1 F2=$PID_F2 F3=$PID_F3 F4=$PID_F4"
echo "Waiting for all..."

wait $PID_F1 || echo "F1 exited with code $?"
wait $PID_F2 || echo "F2 exited with code $?"
wait $PID_F3 || echo "F3 exited with code $?"
wait $PID_F4 || echo "F4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 6 COMPLETE'
echo '========================================'
date

for name in F1_slstm_018hp F2_lstm_018hp F3_slstm_ent05_vf05 F4_slstm_018hp_milestones; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    LAST_ENT=$(grep -o 'entropy[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | tail -1)
    LAST_CF=$(grep 'clipfrac' "$LOG" 2>/dev/null | tail -5 | grep -o 'clipfrac[^0-9]*[0-9.]*' | grep -o '[0-9.]*$' | tail -1)
    echo "$name: peak_j=$PEAK_J entropy=$LAST_ENT clipfrac=$LAST_CF"
  else
    echo "$name: NO LOG"
  fi
done

# Cleanup: keep only last checkpoint
for name in F1_slstm_018hp F2_lstm_018hp F3_slstm_ent05_vf05 F4_slstm_018hp_milestones; do
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
