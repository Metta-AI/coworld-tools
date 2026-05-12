#!/bin/bash
# Round 8: Extend best config (G1) to 100M steps + tune PFO/SepLR
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
PATCH=scripts/sweep/patch_and_train.py
MISSION=arena
COGS=8

echo '========================================'
echo 'Round 8: G1 extension + PFO/SepLR tuning'
echo '========================================'
date

# GPU 0: G1 config extended to 100M steps (2x training)
echo '[GPU 0] H1: ALL fixes, 100M steps...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES='pfo,sep_lr,asym_clip,redo,no_vf_clip'
  export PFO_COEF=1.0
  export CRITIC_LR_RATIO=0.2
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 100000000 --device auto \
    --checkpoints $RESULTS/H1_slstm_all_100M \
    > $RESULTS/H1_slstm_all_100M.log 2>&1
) &
PID_H1=$!

# GPU 1: Lower PFO coefficient (0.1 instead of 1.0) — less aggressive regularization
echo '[GPU 1] H2: ALL fixes, PFO=0.1...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES='pfo,sep_lr,asym_clip,redo,no_vf_clip'
  export PFO_COEF=0.1
  export CRITIC_LR_RATIO=0.2
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 50000000 --device auto \
    --checkpoints $RESULTS/H2_slstm_pfo01 \
    > $RESULTS/H2_slstm_pfo01.log 2>&1
) &
PID_H2=$!

# GPU 2: Higher critic LR ratio (0.5 instead of 0.2) — less asymmetry
echo '[GPU 2] H3: ALL fixes, critic_lr_ratio=0.5...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5}'
  export SWEEP_FIXES='pfo,sep_lr,asym_clip,redo,no_vf_clip'
  export PFO_COEF=1.0
  export CRITIC_LR_RATIO=0.5
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 50000000 --device auto \
    --checkpoints $RESULTS/H3_slstm_critic05 \
    > $RESULTS/H3_slstm_critic05.log 2>&1
) &
PID_H3=$!

# GPU 3: G4's winning combo (SepLR+ReDo) PLUS higher entropy to fix low exploration
echo '[GPU 3] H4: SepLR+ReDo+ent=0.03 (fix G4 low entropy)...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES='{"vf_coef": 0.5, "ent_coef": 0.03}'
  export SWEEP_FIXES='sep_lr,redo'
  export CRITIC_LR_RATIO=0.2
  python3 $PATCH train -m $MISSION -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 50000000 --device auto \
    --checkpoints $RESULTS/H4_slstm_seplr_ent03 \
    > $RESULTS/H4_slstm_seplr_ent03.log 2>&1
) &
PID_H4=$!

echo "PIDs: H1=$PID_H1 H2=$PID_H2 H3=$PID_H3 H4=$PID_H4"
echo "H1=100M (~50min), H2-H4=50M (~25min)"
echo "Waiting for all..."

wait $PID_H2 || echo "H2 exited with code $?"
wait $PID_H3 || echo "H3 exited with code $?"
wait $PID_H4 || echo "H4 exited with code $?"

echo ''
echo '========================================'
echo 'H2-H4 COMPLETE (H1 still running)'
echo '========================================'
date

for name in H2_slstm_pfo01 H3_slstm_critic05 H4_slstm_seplr_ent03; do
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

# Cleanup H2-H4: keep only last checkpoint
for name in H2_slstm_pfo01 H3_slstm_critic05 H4_slstm_seplr_ent03; do
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

echo "Waiting for H1 (100M steps)..."
wait $PID_H1 || echo "H1 exited with code $?"

echo ''
echo '========================================'
echo 'Round 8 FULLY COMPLETE'
echo '========================================'
date

LOG=$RESULTS/H1_slstm_all_100M.log
if [ -f "$LOG" ]; then
  PEAK_J=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
  LAST_ENT=$(grep -o 'entropy[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | tail -1)
  LAST_CF=$(grep 'clipfrac' "$LOG" 2>/dev/null | tail -5 | grep -o 'clipfrac[^0-9]*[0-9.]*' | grep -o '[0-9.]*$' | tail -1)
  JUNC=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | tr '\n' ' ')
  echo "H1_slstm_all_100M: peak_j=${PEAK_J:-0} entropy=$LAST_ENT clipfrac=$LAST_CF junctions=[$JUNC]"
fi

# Cleanup H1
CKPT=$RESULTS/H1_slstm_all_100M
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
echo "Disk: $(df -h / | tail -1 | awk '{print $4}') free"
