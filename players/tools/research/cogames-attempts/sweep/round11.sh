#!/bin/bash
# Round 11: Reward Shaping Sweep
# Testing approaches: #1 (Dense chain rewards), #8 (Curiosity), #5 (Adaptive entropy)
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
echo 'Round 11: Reward Shaping (no_clips + aligner base)'
echo '========================================'
date

# GPU 0: K1 — Dense chain rewards, conservative scale
echo '[GPU 0] K1: chain_rewards scale=0.5...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  export REWARD_MODE=chain_rewards
  export REWARD_SCALE=0.5
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/K1_chain_05 \
    > $RESULTS/K1_chain_05.log 2>&1
) &
PID_K1=$!

# GPU 1: K2 — Dense chain rewards, aggressive scale
echo '[GPU 1] K2: chain_rewards scale=1.0...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  export REWARD_MODE=chain_rewards
  export REWARD_SCALE=1.0
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/K2_chain_10 \
    > $RESULTS/K2_chain_10.log 2>&1
) &
PID_K2=$!

# GPU 2: K3 — Curiosity (count-based intrinsic motivation)
echo '[GPU 2] K3: curiosity beta=0.1...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  export REWARD_MODE=curiosity
  export REWARD_SCALE=0.1
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/K3_curiosity \
    > $RESULTS/K3_curiosity.log 2>&1
) &
PID_K3=$!

# GPU 3: K4 — Adaptive entropy (SAEIR)
echo '[GPU 3] K4: adaptive entropy target=0.5...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  export ENTROPY_MODE=adaptive
  export ENTROPY_TARGET=0.5
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/K4_adaptive_ent \
    > $RESULTS/K4_adaptive_ent.log 2>&1
) &
PID_K4=$!

echo "PIDs: K1=$PID_K1 K2=$PID_K2 K3=$PID_K3 K4=$PID_K4"
echo "All 50M steps (~25 min each)"
echo "Waiting for all..."

wait $PID_K1 || echo "K1 exited with code $?"
wait $PID_K2 || echo "K2 exited with code $?"
wait $PID_K3 || echo "K3 exited with code $?"
wait $PID_K4 || echo "K4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 11 COMPLETE'
echo '========================================'
date

for name in K1_chain_05 K2_chain_10 K3_curiosity K4_adaptive_ent; do
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
for name in K1_chain_05 K2_chain_10 K3_curiosity K4_adaptive_ent; do
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
