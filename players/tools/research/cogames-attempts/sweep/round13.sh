#!/bin/bash
# Round 13: Bug-fix rerun of R11+R12 bugged experiments
# R11 K1/K2/K3 had wrong PufferLib attribute names (reward_buffer instead of rewards)
# R12 L1 dual-gamma silently skipped (advantages not on self in PufferLib 3.0)
# R12 L4b target_net eval hook shape mismatch (called full policy without LSTM state)
# All fixed: attribute names, compute_puff_advantage patch, value_head hook approach
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
echo 'Round 13: Bug-fix rerun (no_clips + aligner base)'
echo '========================================'
date

# GPU 0: M1 — Chain rewards (was K1, fixed reward_buffer -> rewards)
echo '[GPU 0] M1: chain_rewards scale=0.5...'
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
    --checkpoints $RESULTS/M1_chain_05 \
    > $RESULTS/M1_chain_05.log 2>&1
) &
PID_M1=$!

# GPU 1: M2 — Curiosity (was K3, fixed reward_buffer -> rewards)
echo '[GPU 1] M2: curiosity beta=0.1...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  export REWARD_MODE=curiosity
  export REWARD_SCALE=0.1
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/M2_curiosity_01 \
    > $RESULTS/M2_curiosity_01.log 2>&1
) &
PID_M2=$!

# GPU 2: M3 — Dual-gamma (was L1, fixed: now patches compute_puff_advantage)
echo '[GPU 2] M3: dual-gamma alpha=0.5...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  export ADVANTAGE_MODE=dual_gamma
  export DUAL_GAMMA_ALPHA=0.5
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/M3_dual_gamma \
    > $RESULTS/M3_dual_gamma.log 2>&1
) &
PID_M3=$!

# GPU 3: M4 — Target net (was L4b, fixed: value_head hook instead of full policy)
echo '[GPU 3] M4: target net tau=0.005...'
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
    --checkpoints $RESULTS/M4_target_net \
    > $RESULTS/M4_target_net.log 2>&1
) &
PID_M4=$!

echo "PIDs: M1=$PID_M1 M2=$PID_M2 M3=$PID_M3 M4=$PID_M4"
echo "All 50M steps (~25 min each)"
echo "Waiting for all..."

wait $PID_M1 || echo "M1 exited with code $?"
wait $PID_M2 || echo "M2 exited with code $?"
wait $PID_M3 || echo "M3 exited with code $?"
wait $PID_M4 || echo "M4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 13 COMPLETE'
echo '========================================'
date

for name in M1_chain_05 M2_curiosity_01 M3_dual_gamma M4_target_net; do
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
for name in M1_chain_05 M2_curiosity_01 M3_dual_gamma M4_target_net; do
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
