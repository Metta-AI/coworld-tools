#!/bin/bash
# Round 19: Kickstarting Calibration
# Tests KL and EER kickstarting with scripted teacher.
# Uses best hyperparams from R17 (metta_optimal preset).
# 500M steps (~5 hrs each on L4), sLSTM d=128, machina_1, no_clips.
#
# CRITICAL DIAGNOSTIC: Check aligner_gained > 0 (gear acquisition).
# This was ZERO in all 70+ previous experiments.
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v22
PATCH=scripts/sweep/patch_and_train.py
MISSION=machina_1
COGS=8
STEPS=500000000  # 500M

mkdir -p $RESULTS

echo '========================================'
echo 'Round 19: Kickstarting Calibration (500M steps)'
echo '========================================'
date

# Apply kickstart source patch to pufferl.py (idempotent)
echo 'Applying kickstart patches to pufferl.py...'
python3 scripts/sweep/apply_kickstart_patches.py
echo ''

# GPU 0: S1 — KL kickstart, coef=0.6, temp=2.0, anneal 50-100%
echo '[GPU 0] S1: KL kickstart...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export KICKSTART_MODE=kl
  export KS_COEF=0.6
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.5
  export KS_ANNEAL_END=1.0
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/S1_kl_kickstart \
    > $RESULTS/S1_kl_kickstart.log 2>&1
) &
PID_S1=$!

# GPU 1: S2 — EER kickstart (KL loss + reward shaping)
echo '[GPU 1] S2: EER kickstart...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export KICKSTART_MODE=eer
  export KS_COEF=0.6
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.5
  export KS_ANNEAL_END=1.0
  export EER_LAMBDA=0.01
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/S2_eer_kickstart \
    > $RESULTS/S2_eer_kickstart.log 2>&1
) &
PID_S2=$!

# GPU 2: S3 — EER + 50% teacher-led rollouts (full metta recipe)
echo '[GPU 2] S3: EER + 50% teacher-led...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export KICKSTART_MODE=eer
  export KS_COEF=0.6
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.5
  export KS_ANNEAL_END=1.0
  export EER_LAMBDA=0.01
  export KS_TEACHER_LED=0.5
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/S3_eer_teacher_led \
    > $RESULTS/S3_eer_teacher_led.log 2>&1
) &
PID_S3=$!

# GPU 3: S4 — KL kickstart, coef=1.0, NO anneal (constant KL throughout)
echo '[GPU 3] S4: KL constant (no anneal)...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export KICKSTART_MODE=kl
  export KS_COEF=1.0
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=1.0
  export KS_ANNEAL_END=1.0
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/S4_kl_constant \
    > $RESULTS/S4_kl_constant.log 2>&1
) &
PID_S4=$!

echo "PIDs: S1=$PID_S1 S2=$PID_S2 S3=$PID_S3 S4=$PID_S4"
echo "Each ~5 hours (500M steps on L4)"
echo "Waiting for all..."

wait $PID_S1 || echo "S1 exited with code $?"
wait $PID_S2 || echo "S2 exited with code $?"
wait $PID_S3 || echo "S3 exited with code $?"
wait $PID_S4 || echo "S4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 19 COMPLETE — Results'
echo '========================================'
date

printf '%-30s %8s %8s %8s %8s %s\n' 'Experiment' 'Peak_J' 'Mean_J' 'Entropy' 'Clipfrac' 'Aligner_Gained'
printf '%-30s %8s %8s %8s %8s %s\n' '----------' '------' '------' '-------' '--------' '--------------'

for name in S1_kl_kickstart S2_eer_kickstart S3_eer_teacher_led S4_kl_constant; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -o 'aligned\.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    JUNC_VALS=$(grep -o 'aligned\.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$')
    if [ -n "$JUNC_VALS" ]; then
      MEAN_J=$(echo "$JUNC_VALS" | awk '{s+=$1; n++} END {if(n>0) printf "%.2f", s/n; else print "0"}')
    else
      MEAN_J="0"
    fi
    LAST_ENT=$(grep -o 'entropy[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | tail -1)
    LAST_ENT=${LAST_ENT:-'?'}
    LAST_CF=$(grep 'clipfrac' "$LOG" 2>/dev/null | tail -5 | grep -o 'clipfrac[^0-9]*[0-9.]*' | grep -o '[0-9.]*$' | tail -1)
    LAST_CF=${LAST_CF:-'?'}
    AG=$(grep -o 'aligner\.gained[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    AG=${AG:-0}

    # Also check for kickstart-specific metrics
    KS_LOSS=$(grep 'KICKSTART.*loss=' "$LOG" 2>/dev/null | tail -1 | grep -o 'loss=[0-9.]*' | grep -o '[0-9.]*')
    KS_LOSS=${KS_LOSS:-'?'}

    printf '%-30s %8s %8s %8s %8s %s (ks_loss=%s)\n' "$name" "$PEAK_J" "$MEAN_J" "$LAST_ENT" "$LAST_CF" "$AG" "$KS_LOSS"
  else
    printf '%-30s %8s\n' "$name" "NO LOG"
  fi
done

echo ''
echo 'Generating training graphs...'
python3 scripts/sweep/plot_training.py $RESULTS/S1_kl_kickstart.log $RESULTS/S2_eer_kickstart.log $RESULTS/S3_eer_teacher_led.log $RESULTS/S4_kl_constant.log 2>/dev/null || echo "Plot generation failed"

echo ''
echo '=== CRITICAL CHECK: aligner_gained > 0 ? ==='
for name in S1_kl_kickstart S2_eer_kickstart S3_eer_teacher_led S4_kl_constant; do
  LOG=$RESULTS/${name}.log
  AG_MAX=$(grep -o 'aligner\.gained[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
  if [ -z "$AG_MAX" ] || [ "$AG_MAX" = "0" ]; then
    echo "  $name: aligner_gained = 0 — STILL BROKEN"
  else
    echo "  $name: aligner_gained = $AG_MAX — BREAKTHROUGH!"
  fi
done

echo ''
echo "Disk: $(df -h / | tail -1 | awk '{print $4}') free"
