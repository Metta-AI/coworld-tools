#!/bin/bash
# Round 15: Scaling + PBT
# Testing: 100M steps, larger model, curriculum transfer, PBT-lite
# UPDATE O1-O3 configs after R14 results.
# Base config: H4 (SepLR+ReDo, ent=0.03, vf=0.5) on best env (no_clips + aligner)
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v19
PATCH=scripts/sweep/patch_and_train.py
MISSION=arena
COGS=8

# H4 base config
BASE_OVERRIDES='{"vf_coef": 0.5, "ent_coef": 0.03}'
BASE_FIXES='sep_lr,redo'
BASE_CLR=0.2

echo '========================================'
echo 'Round 15: Scaling + PBT'
echo '========================================'
date

# GPU 0: O1 — Best overall config, 100M steps (2x training)
echo '[GPU 0] O1: best config, 100M steps...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  # TODO: Add best REWARD_MODE/ADVANTAGE_MODE from R14
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 100000000 --device auto \
    --checkpoints $RESULTS/O1_best_100M \
    > $RESULTS/O1_best_100M.log 2>&1
) &
PID_O1=$!

# GPU 1: O2 — Best config, d_hidden=256 (larger model)
# NOTE: Requires CortexSLSTM256Policy class or kw.d_hidden=256 support
echo '[GPU 1] O2: best config, d_hidden=256...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR
  # TODO: Need CortexSLSTM256Policy class for d_hidden=256
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 50000000 --device auto \
    --checkpoints $RESULTS/O2_best_d256 \
    > $RESULTS/O2_best_d256.log 2>&1
) &
PID_O2=$!

# GPU 2: O3 — Sequential curriculum: train on no_clips, finetune on full arena
echo '[GPU 2] O3: curriculum no_clips -> arena...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_OVERRIDES="$BASE_OVERRIDES"
  export SWEEP_FIXES="$BASE_FIXES"
  export CRITIC_LR_RATIO=$BASE_CLR

  # Stage 1: Train on no_clips + aligner for 25M steps
  echo '[O3] Stage 1: no_clips + aligner, 25M steps...'
  python3 $PATCH train -m $MISSION -v no_clips -v aligner \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 25000000 --device auto \
    --checkpoints $RESULTS/O3_curriculum_stage1 \
    > $RESULTS/O3_curriculum_stage1.log 2>&1

  # Find last checkpoint from stage 1
  STAGE1_CKPT=$(ls -1t $RESULTS/O3_curriculum_stage1/*/model_*.pt 2>/dev/null | head -1)
  if [ -z "$STAGE1_CKPT" ]; then
    echo '[O3] ERROR: No stage 1 checkpoint found'
    exit 1
  fi
  echo "[O3] Stage 1 checkpoint: $STAGE1_CKPT"

  # Stage 2: Finetune on full arena for 25M steps
  echo '[O3] Stage 2: full arena (with clips), 25M steps...'
  python3 $PATCH train -m $MISSION \
    -p "class=cortex_policy.CortexSLSTMPolicy,data=$STAGE1_CKPT" \
    --cogs $COGS --steps 25000000 --device auto \
    --checkpoints $RESULTS/O3_curriculum_stage2 \
    > $RESULTS/O3_curriculum_stage2.log 2>&1
) &
PID_O3=$!

# GPU 3: O4 — PBT-lite (4 policies x 5 generations, 10M steps each)
echo '[GPU 3] O4: PBT-lite (sequential on 1 GPU)...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export CRITIC_LR_RATIO=$BASE_CLR

  BEST_CKPT=""
  BEST_SCORE=0

  for GEN in 1 2 3 4 5; do
    echo "[O4] Generation $GEN..."

    for POP in 1 2 3 4; do
      # Perturb hyperparams ±20% from base
      ENT=$(python3 -c "import random; print(round(0.03 * random.uniform(0.8, 1.2), 4))")
      VF=$(python3 -c "import random; print(round(0.5 * random.uniform(0.8, 1.2), 2))")
      SEED=$((GEN * 100 + POP))

      echo "  [O4] Gen=$GEN Pop=$POP: ent=$ENT vf=$VF seed=$SEED"
      export SWEEP_OVERRIDES="{\"vf_coef\": $VF, \"ent_coef\": $ENT, \"seed\": $SEED}"
      export SWEEP_FIXES="$BASE_FIXES"

      CKPT_DIR=$RESULTS/O4_pbt_g${GEN}_p${POP}

      # If we have a best checkpoint from prev gen, use it for top-half policies
      if [ -n "$BEST_CKPT" ] && [ $POP -le 2 ]; then
        python3 $PATCH train -m $MISSION -v no_clips -v aligner \
          -p "class=cortex_policy.CortexSLSTMPolicy,data=$BEST_CKPT" \
          --cogs $COGS --steps 10000000 --device auto \
          --checkpoints $CKPT_DIR \
          > $CKPT_DIR.log 2>&1
      else
        python3 $PATCH train -m $MISSION -v no_clips -v aligner \
          -p 'class=cortex_policy.CortexSLSTMPolicy' \
          --cogs $COGS --steps 10000000 --device auto \
          --checkpoints $CKPT_DIR \
          > $CKPT_DIR.log 2>&1
      fi

      # Extract peak junction score
      SCORE=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$CKPT_DIR.log" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
      SCORE=${SCORE:-0}
      echo "  [O4] Gen=$GEN Pop=$POP: score=$SCORE"

      # Track best
      BETTER=$(python3 -c "print(1 if float('$SCORE') > float('$BEST_SCORE') else 0)")
      if [ "$BETTER" = "1" ]; then
        BEST_SCORE=$SCORE
        BEST_CKPT=$(ls -1t $CKPT_DIR/*/model_*.pt 2>/dev/null | head -1)
        echo "  [O4] New best: score=$BEST_SCORE ckpt=$BEST_CKPT"
      fi

      # Cleanup non-best checkpoints
      for RUN_DIR in "$CKPT_DIR"/*/; do
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
  done

  echo "[O4] PBT complete. Best score: $BEST_SCORE"
) &
PID_O4=$!

echo "PIDs: O1=$PID_O1 O2=$PID_O2 O3=$PID_O3 O4=$PID_O4"
echo "O1: ~50 min, O2: ~25 min, O3: ~50 min, O4: ~100+ min"
echo "Waiting for all..."

wait $PID_O1 || echo "O1 exited with code $?"
wait $PID_O2 || echo "O2 exited with code $?"
wait $PID_O3 || echo "O3 exited with code $?"
wait $PID_O4 || echo "O4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 15 COMPLETE'
echo '========================================'
date

for name in O1_best_100M O2_best_d256; do
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

# O3 has two stages
for stage in stage1 stage2; do
  LOG=$RESULTS/O3_curriculum_${stage}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -o 'aligned.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    echo "O3_curriculum_${stage}: peak_j=$PEAK_J"
  fi
done

echo "Disk: $(df -h / | tail -1 | awk '{print $4}') free"
