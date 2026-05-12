#!/bin/bash
# Round 14: Combinations — Best Approaches from R11-R13
# UPDATE THIS SCRIPT after R11-R13 results are available.
# Placeholder configs use best approach + architecture combinations.
# Base config: H4 (SepLR+ReDo, ent=0.03, vf=0.5) on best env (no_clips + aligner)
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

# H4 base config
BASE_OVERRIDES='{"vf_coef": 0.5, "ent_coef": 0.03}'
BASE_FIXES='sep_lr,redo'
BASE_CLR=0.2

echo '========================================'
echo 'Round 14: Combinations (update after R11-R13)'
echo '========================================'
echo 'NOTE: Update N1-N4 configs based on R11-R13 results before running!'
date

# GPU 0: N1 — Best approach from R11 + sLSTM
echo '[GPU 0] N1: [PLACEHOLDER] best_approach + sLSTM...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  # TODO: Add REWARD_MODE/ADVANTAGE_MODE from best R11 result
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/N1_best_slstm \
    > $RESULTS/N1_best_slstm.log 2>&1
) &
PID_N1=$!

# GPU 1: N2 — Best approach from R11 + native LSTM (control)
echo '[GPU 1] N2: [PLACEHOLDER] best_approach + LSTM...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  # TODO: Add REWARD_MODE/ADVANTAGE_MODE from best R11 result
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/N2_best_lstm \
    > $RESULTS/N2_best_lstm.log 2>&1
) &
PID_N2=$!

# GPU 2: N3 — 2nd best approach + sLSTM
echo '[GPU 2] N3: [PLACEHOLDER] 2nd_best + sLSTM...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  # TODO: Add REWARD_MODE/ADVANTAGE_MODE from 2nd best R11/R12 result
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/N3_second_slstm \
    > $RESULTS/N3_second_slstm.log 2>&1
) &
PID_N3=$!

# GPU 3: N4 — Top 2 approaches combined + sLSTM
echo '[GPU 3] N4: [PLACEHOLDER] top2_combined + sLSTM...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  # TODO: Add REWARD_MODE + ADVANTAGE_MODE from top 2 R11/R12 results
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/N4_combined_slstm \
    > $RESULTS/N4_combined_slstm.log 2>&1
) &
PID_N4=$!

echo "PIDs: N1=$PID_N1 N2=$PID_N2 N3=$PID_N3 N4=$PID_N4"
echo "All 50M steps (~25 min each)"
echo "Waiting for all..."

wait $PID_N1 || echo "N1 exited with code $?"
wait $PID_N2 || echo "N2 exited with code $?"
wait $PID_N3 || echo "N3 exited with code $?"
wait $PID_N4 || echo "N4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 14 COMPLETE'
echo '========================================'
date

for name in N1_best_slstm N2_best_lstm N3_second_slstm N4_combined_slstm; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    LAST_ENT=$(grep -o 'entropy[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | tail -1)
    LAST_CF=$(grep 'clipfrac' "$LOG" 2>/dev/null | tail -5 | grep -o 'clipfrac[^0-9]*[0-9.]*' | grep -o '[0-9.]*$' | tail -1)
    JUNC=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | tr '\n' ' ')
    echo "$name: peak_j=$PEAK_J entropy=$LAST_ENT clipfrac=$LAST_CF junctions=[$JUNC]"
  else
    echo "$name: NO LOG"
  fi
done

# Cleanup: keep only last checkpoint
for name in N1_best_slstm N2_best_lstm N3_second_slstm N4_combined_slstm; do
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
