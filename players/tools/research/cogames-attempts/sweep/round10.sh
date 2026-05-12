#!/bin/bash
# Round 10: Curriculum + Combined Variants Sweep
# Testing approaches: #7 (Curriculum), #1+#4+#7 (combined), population
# Base config: H4 (SepLR+ReDo, ent=0.03, vf=0.5) — best stable optimization
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
echo 'Round 10: Curriculum + Combined Variants'
echo '========================================'
date

# GPU 0: No enemies + forced roles (#7 + #4)
echo '[GPU 0] J1: no_clips + forced_role_vibes...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  python3 $PATCH train -m $MISSION -v no_clips -v forced_role_vibes \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/J1_noclips_roles \
    > $RESULTS/J1_noclips_roles.log 2>&1
) &
PID_J1=$!

# GPU 1: Kitchen sink — all simplifications + dense reward (#1+#4+#7)
echo '[GPU 1] J2: no_clips + credit + forced_role_vibes...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  python3 $PATCH train -m $MISSION -v no_clips -v credit -v forced_role_vibes \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/J2_noclips_credit_roles \
    > $RESULTS/J2_noclips_credit_roles.log 2>&1
) &
PID_J2=$!

# GPU 2: Max hearts + forced roles — remove survival pressure (#7 variant)
echo '[GPU 2] J3: braveheart + forced_role_vibes...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  python3 $PATCH train -m $MISSION -v braveheart -v forced_role_vibes \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/J3_braveheart_roles \
    > $RESULTS/J3_braveheart_roles.log 2>&1
) &
PID_J3=$!

# GPU 3: Mining objective + forced roles + no clips (#1 variant + #4 + #7)
echo '[GPU 3] J4: no_clips + objective_mine + forced_role_vibes...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  python3 $PATCH train -m $MISSION -v no_clips -v objective_mine -v forced_role_vibes \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/J4_noclips_objmine_roles \
    > $RESULTS/J4_noclips_objmine_roles.log 2>&1
) &
PID_J4=$!

echo "PIDs: J1=$PID_J1 J2=$PID_J2 J3=$PID_J3 J4=$PID_J4"
echo "All 50M steps (~25 min each)"
echo "Waiting for all..."

wait $PID_J1 || echo "J1 exited with code $?"
wait $PID_J2 || echo "J2 exited with code $?"
wait $PID_J3 || echo "J3 exited with code $?"
wait $PID_J4 || echo "J4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 10 COMPLETE'
echo '========================================'
date

for name in J1_noclips_roles J2_noclips_credit_roles J3_braveheart_roles J4_noclips_objmine_roles; do
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
for name in J1_noclips_roles J2_noclips_credit_roles J3_braveheart_roles J4_noclips_objmine_roles; do
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
