#!/bin/bash
# Round 17: Metta Hyperparameters
# Testing whether fixing hyperparams alone (8x higher LR, weight_decay=0.3,
# gamma=0.9986, larger clip, higher ent) breaks the 5j ceiling.
# All use: sLSTM d=128, machina_1, no_clips
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v22
PATCH=scripts/sweep/patch_and_train.py
MISSION=machina_1
COGS=8
STEPS=50000000

mkdir -p $RESULTS

echo '========================================'
echo 'Round 17: Metta Hyperparameters'
echo '========================================'
date

# GPU 0: Q1 — Full metta optimal preset (all params from cogsguard.py sweep)
echo '[GPU 0] Q1: Full metta optimal preset...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/Q1_metta_optimal \
    > $RESULTS/Q1_metta_optimal.log 2>&1
) &
PID_Q1=$!

# GPU 1: Q2 — Metta optimal + our H4 fixes (sep_lr, redo) — do they stack?
echo '[GPU 1] Q2: Metta optimal + H4 fixes...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES='sep_lr,redo'
  export CRITIC_LR_RATIO=0.2
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/Q2_metta_h4_fixes \
    > $RESULTS/Q2_metta_h4_fixes.log 2>&1
) &
PID_Q2=$!

# GPU 2: Q3 — Metta optimal + arena (not machina_1) — map comparison
echo '[GPU 2] Q3: Metta optimal + arena...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  python3 $PATCH train -m arena -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/Q3_metta_arena \
    > $RESULTS/Q3_metta_arena.log 2>&1
) &
PID_Q3=$!

# GPU 3: Q4 — cogames defaults control (reproduce N3's 5.0j baseline)
echo '[GPU 3] Q4: cogames defaults control...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/Q4_defaults_control \
    > $RESULTS/Q4_defaults_control.log 2>&1
) &
PID_Q4=$!

echo "PIDs: Q1=$PID_Q1 Q2=$PID_Q2 Q3=$PID_Q3 Q4=$PID_Q4"
echo "Each ~30 min on L4 GPU"
echo "Waiting for all..."

wait $PID_Q1 || echo "Q1 exited with code $?"
wait $PID_Q2 || echo "Q2 exited with code $?"
wait $PID_Q3 || echo "Q3 exited with code $?"
wait $PID_Q4 || echo "Q4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 17 COMPLETE — Results'
echo '========================================'
date

# Summary table
printf '%-30s %8s %8s %8s %8s %s\n' 'Experiment' 'Peak_J' 'Mean_J' 'Entropy' 'Clipfrac' 'Aligner_Gained'
printf '%-30s %8s %8s %8s %8s %s\n' '----------' '------' '------' '-------' '--------' '--------------'

for name in Q1_metta_optimal Q2_metta_h4_fixes Q3_metta_arena Q4_defaults_control; do
  LOG=$RESULTS/${name}.log
  if [ -f "$LOG" ]; then
    PEAK_J=$(grep -o 'aligned\.jun[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
    PEAK_J=${PEAK_J:-0}
    # Mean of all junction readings
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
    printf '%-30s %8s %8s %8s %8s %s\n' "$name" "$PEAK_J" "$MEAN_J" "$LAST_ENT" "$LAST_CF" "$AG"
  else
    printf '%-30s %8s\n' "$name" "NO LOG"
  fi
done

# Generate training graphs
echo ''
echo 'Generating training graphs...'
python3 scripts/sweep/plot_training.py $RESULTS/Q1_metta_optimal.log $RESULTS/Q2_metta_h4_fixes.log $RESULTS/Q3_metta_arena.log $RESULTS/Q4_defaults_control.log 2>/dev/null || echo "Plot generation failed (matplotlib may not be installed)"

echo ''
echo "Disk: $(df -h / | tail -1 | awk '{print $4}') free"
