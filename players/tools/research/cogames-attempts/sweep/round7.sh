#!/bin/bash
# Round 7: Tier 1 PPO Fixes (PFO + Sep LR + Asym Clip + ReDo)
# Based on: Moalla et al. NeurIPS 2024, Sokar et al. ICML 2023, DAPO ByteDance 2025
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
PATCH=scripts/sweep/patch_and_train.py
STEPS=50000000
MISSION=arena
COGS=8

echo '========================================'
echo 'Round 7: Tier 1 PPO Fixes'
echo '========================================'
date

# First: apply source patches to pufferl.py (idempotent)
echo '[SETUP] Applying pufferl.py source patches...'
python3 scripts/sweep/apply_tier1_patches.py

echo ''

# GPU 0: ALL Tier 1 fixes combined on sLSTM + vf=0.5
echo '[GPU 0] G1: sLSTM + ALL fixes (PFO+SepLR+AsymClip+ReDo+NoVfClip) + vf=0.5...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES='pfo,sep_lr,asym_clip,redo,no_vf_clip'
  export PFO_COEF=1.0
  export CRITIC_LR_RATIO=0.2
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/G1_slstm_all_tier1 \
    > $RESULTS/G1_slstm_all_tier1.log 2>&1
) &
PID_G1=$!

# GPU 1: ALL Tier 1 fixes on native LSTM + vf=0.5
echo '[GPU 1] G2: Native LSTM + ALL fixes + vf=0.5...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES='pfo,sep_lr,asym_clip,redo,no_vf_clip'
  export PFO_COEF=1.0
  export CRITIC_LR_RATIO=0.2
  python3 $PATCH train -m $MISSION \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/G2_lstm_all_tier1 \
    > $RESULTS/G2_lstm_all_tier1.log 2>&1
) &
PID_G2=$!

# GPU 2: Just PFO + Sep LR (isolate the two most impactful fixes) on sLSTM + vf=0.5
echo '[GPU 2] G3: sLSTM + PFO + SepLR + vf=0.5...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES='pfo,sep_lr'
  export PFO_COEF=1.0
  export CRITIC_LR_RATIO=0.2
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/G3_slstm_pfo_seplr \
    > $RESULTS/G3_slstm_pfo_seplr.log 2>&1
) &
PID_G3=$!

# GPU 3: Just Sep LR + ReDo (no source patches needed) on sLSTM + vf=0.5
echo '[GPU 3] G4: sLSTM + SepLR + ReDo + vf=0.5...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES='sep_lr,redo'
  export CRITIC_LR_RATIO=0.2
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/G4_slstm_seplr_redo \
    > $RESULTS/G4_slstm_seplr_redo.log 2>&1
) &
PID_G4=$!

echo "PIDs: G1=$PID_G1 G2=$PID_G2 G3=$PID_G3 G4=$PID_G4"
echo "Waiting for all..."

wait $PID_G1 || echo "G1 exited with code $?"
wait $PID_G2 || echo "G2 exited with code $?"
wait $PID_G3 || echo "G3 exited with code $?"
wait $PID_G4 || echo "G4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 7 COMPLETE'
echo '========================================'
date

for name in G1_slstm_all_tier1 G2_lstm_all_tier1 G3_slstm_pfo_seplr G4_slstm_seplr_redo; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    LAST_ENT=$(grep -o 'entropy[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | tail -1)
    LAST_CF=$(grep 'clipfrac' "$LOG" 2>/dev/null | tail -5 | grep -o 'clipfrac[^0-9]*[0-9.]*' | grep -o '[0-9.]*$' | tail -1)
    REDO_COUNT=$(grep -c '\[REDO\]' "$LOG" 2>/dev/null)
    echo "$name: peak_j=$PEAK_J entropy=$LAST_ENT clipfrac=$LAST_CF redo_events=$REDO_COUNT"
  else
    echo "$name: NO LOG"
  fi
done

# Cleanup: keep only last checkpoint
for name in G1_slstm_all_tier1 G2_lstm_all_tier1 G3_slstm_pfo_seplr G4_slstm_seplr_redo; do
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
