#!/bin/bash
# Round 12: Advantage + Architecture (Subhojeet suggestions)
# Testing: #2 (Dual-gamma), #6 (PRD), #11 (Separate AC), #12 (Target net)
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
echo 'Round 12: Advantage + Architecture (no_clips + aligner base)'
echo '========================================'
date

# GPU 0: L1 — Dual-gamma, equal weighting
echo '[GPU 0] L1: dual-gamma alpha=0.5...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  export ADVANTAGE_MODE=dual_gamma
  export DUAL_GAMMA_ALPHA=0.5
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/L1_dual_gamma_05 \
    > $RESULTS/L1_dual_gamma_05.log 2>&1
) &
PID_L1=$!

# GPU 1: L2 — PRD advantage decomposition, alpha=0.5
echo '[GPU 1] L2: PRD alpha=0.5...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  export ADVANTAGE_MODE=prd
  export PRD_ALPHA=0.5
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/L2_prd_05 \
    > $RESULTS/L2_prd_05.log 2>&1
) &
PID_L2=$!

# GPU 2: L3b — Separate actor/critic networks (Subhojeet suggestion)
# Two independent LSTM backbones, no shared features. ~450K params (2x baseline).
echo '[GPU 2] L3b: separate actor/critic LSTM...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.SeparateACLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/L3b_separate_ac \
    > $RESULTS/L3b_separate_ac.log 2>&1
) &
PID_L3=$!

# GPU 3: L4b — Target network for value stabilization (Subhojeet suggestion)
# Polyak-averaged critic copy (tau=0.005) provides stable GAE targets.
echo '[GPU 3] L4b: target network tau=0.005...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="sep_lr,redo,target_net"
  export CRITIC_LR_RATIO=$BASE_CLR
  export TARGET_NET_TAU=0.005
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/L4b_target_net \
    > $RESULTS/L4b_target_net.log 2>&1
) &
PID_L4=$!

echo "PIDs: L1=$PID_L1 L2=$PID_L2 L3b=$PID_L3 L4b=$PID_L4"
echo "All 50M steps (~25 min each)"
echo "Waiting for all..."

wait $PID_L1 || echo "L1 exited with code $?"
wait $PID_L2 || echo "L2 exited with code $?"
wait $PID_L3 || echo "L3b exited with code $?"
wait $PID_L4 || echo "L4b exited with code $?"

echo ''
echo '========================================'
echo 'Round 12 COMPLETE'
echo '========================================'
date

for name in L1_dual_gamma_05 L2_prd_05 L3b_separate_ac L4b_target_net; do
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
for name in L1_dual_gamma_05 L2_prd_05 L3b_separate_ac L4b_target_net; do
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
