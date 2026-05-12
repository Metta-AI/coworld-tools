#!/bin/bash
# Round 9: Reward Shaping + Role Forcing Sweep
# Testing approaches: #1 (Reward Machines), #4/#9 (Role Discovery), combinations
# Base config: H4 (SepLR+ReDo, ent=0.03, vf=0.5) — best stable optimization
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

# H4 base config (stable clipfrac, 2.0j peak, no source patches needed)
BASE_OVERRIDES='{"vf_coef": 0.5, "ent_coef": 0.03}'
BASE_FIXES='sep_lr,redo'
BASE_CLR=0.2

echo '========================================'
echo 'Round 9: Reward Shaping + Role Forcing'
echo '========================================'
date

# GPU 0: Dense chain rewards (credit variant — approach #1 Reward Machines)
echo '[GPU 0] I1: credit variant (dense chain rewards)...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  python3 $PATCH train -m $MISSION -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/I1_credit \
    > $RESULTS/I1_credit.log 2>&1
) &
PID_I1=$!

# GPU 1: Forced role assignment (approach #4/#9 Role Discovery)
echo '[GPU 1] I2: forced_role_vibes (forced roles)...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  python3 $PATCH train -m $MISSION -v forced_role_vibes \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/I2_forced_roles \
    > $RESULTS/I2_forced_roles.log 2>&1
) &
PID_I2=$!

# GPU 2: Dense rewards + forced roles combined (#1 + #4)
echo '[GPU 2] I3: credit + forced_role_vibes...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  python3 $PATCH train -m $MISSION -v credit -v forced_role_vibes \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/I3_credit_roles \
    > $RESULTS/I3_credit_roles.log 2>&1
) &
PID_I3=$!

# GPU 3: No enemy pressure (approach #7 Curriculum)
echo '[GPU 3] I4: no_clips (remove enemies)...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/I4_no_clips \
    > $RESULTS/I4_no_clips.log 2>&1
) &
PID_I4=$!

echo "PIDs: I1=$PID_I1 I2=$PID_I2 I3=$PID_I3 I4=$PID_I4"
echo "All 50M steps (~25 min each)"
echo "Waiting for all..."

wait $PID_I1 || echo "I1 exited with code $?"
wait $PID_I2 || echo "I2 exited with code $?"
wait $PID_I3 || echo "I3 exited with code $?"
wait $PID_I4 || echo "I4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 9 COMPLETE'
echo '========================================'
date

for name in I1_credit I2_forced_roles I3_credit_roles I4_no_clips; do
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
for name in I1_credit I2_forced_roles I3_credit_roles I4_no_clips; do
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
