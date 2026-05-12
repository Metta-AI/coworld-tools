#!/bin/bash
# Round 21: Entropy Collapse Prevention
#
# R20 finding: ALL 4 runs suffered entropy collapse (entropy=0, clipfrac=0).
# T3 hit 8.0j (new record!) before collapsing. Entropy collapse is the #1 problem.
#
# Base config: T3's winning setup (fresh + KL KS 0.3 + milestones,credit)
# Variable: entropy prevention strategy
#
# GPU 0: E1 — High constant ent_coef=0.08 (3x metta's 0.0257)
# GPU 1: E2 — Cosine schedule 0.10 -> 0.02 (starts high, anneals to metta's)
# GPU 2: E3 — Adaptive floor/ceil controller (floor=0.3, aggressive 2x boost)
# GPU 3: E4 — Very high ent_coef=0.15 + adaptive floor=0.5 (belt + suspenders)
#
# Each run: 1B steps (~10 hours per L4 GPU)
# Key diagnostic: Does entropy stay > 0.1 throughout training?

cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v22
PATCH=scripts/sweep/patch_and_train.py
MISSION=machina_1
COGS=8

mkdir -p $RESULTS

echo '========================================'
echo 'Round 21: Entropy Collapse Prevention'
echo '========================================'
date

# Apply kickstart source patch (needed for all — KL KS)
echo 'Applying kickstart patches to pufferl.py...'
python3 scripts/sweep/apply_kickstart_patches.py
echo ''

# Common config for all runs:
# - Fresh start (no warm-start — warm-start was counterproductive in R20)
# - KL kickstarting coef=0.3, anneal 30-60%
# - milestones + credit reward variants
# - metta_optimal preset + sep_lr,redo fixes

# GPU 0: E1 — High constant ent_coef=0.08
echo '[GPU 0] E1: High constant ent_coef=0.08...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export SWEEP_OVERRIDES='{"ent_coef": 0.08}'
  export KICKSTART_MODE=kl
  export KS_COEF=0.3
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.3
  export KS_ANNEAL_END=0.6
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 1000000000 --device auto \
    --checkpoints $RESULTS/E1_high_ent \
    > $RESULTS/E1_high_ent.log 2>&1
) &
PID_E1=$!

# GPU 1: E2 — Cosine schedule 0.10 -> 0.02
echo '[GPU 1] E2: Cosine schedule ent_coef 0.10 -> 0.02...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export KICKSTART_MODE=kl
  export KS_COEF=0.3
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.3
  export KS_ANNEAL_END=0.6
  export ENTROPY_MODE=cosine
  export ENT_COEF_MAX=0.10
  export ENT_COEF_MIN=0.02
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 1000000000 --device auto \
    --checkpoints $RESULTS/E2_cosine_ent \
    > $RESULTS/E2_cosine_ent.log 2>&1
) &
PID_E2=$!

# GPU 2: E3 — Adaptive floor/ceiling controller
echo '[GPU 2] E3: Adaptive entropy floor=0.3, ceil=0.8...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export KICKSTART_MODE=kl
  export KS_COEF=0.3
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.3
  export KS_ANNEAL_END=0.6
  export ENTROPY_MODE=adaptive
  export ENTROPY_FLOOR=0.3
  export ENTROPY_CEIL=0.8
  export ENT_COEF_MIN=0.01
  export ENT_COEF_MAX=0.30
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 1000000000 --device auto \
    --checkpoints $RESULTS/E3_adaptive_ent \
    > $RESULTS/E3_adaptive_ent.log 2>&1
) &
PID_E3=$!

# GPU 3: E4 — Very high ent_coef=0.15 + adaptive floor (belt + suspenders)
echo '[GPU 3] E4: High ent=0.15 + adaptive floor=0.5 (belt+suspenders)...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export SWEEP_OVERRIDES='{"ent_coef": 0.15}'
  export KICKSTART_MODE=kl
  export KS_COEF=0.3
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.3
  export KS_ANNEAL_END=0.6
  export ENTROPY_MODE=adaptive
  export ENTROPY_FLOOR=0.5
  export ENTROPY_CEIL=1.0
  export ENT_COEF_MIN=0.05
  export ENT_COEF_MAX=0.30
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 1000000000 --device auto \
    --checkpoints $RESULTS/E4_belt_suspenders \
    > $RESULTS/E4_belt_suspenders.log 2>&1
) &
PID_E4=$!

echo ""
echo "PIDs: E1=$PID_E1 E2=$PID_E2 E3=$PID_E3 E4=$PID_E4"
echo "Each ~10 hours (1B steps on L4)"
echo ""
echo "Waiting for all..."

wait $PID_E1 || echo "E1 exited with code $?"
wait $PID_E2 || echo "E2 exited with code $?"
wait $PID_E3 || echo "E3 exited with code $?"
wait $PID_E4 || echo "E4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 21 COMPLETE — Results'
echo '========================================'
date

printf '%-30s %8s %8s %8s %8s\n' 'Experiment' 'Peak_J' 'Mean_J' 'Entropy' 'Clipfrac'
printf '%-30s %8s %8s %8s %8s\n' '----------' '------' '------' '-------' '--------'

for name in E1_high_ent E2_cosine_ent E3_adaptive_ent E4_belt_suspenders; do
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

    printf '%-30s %8s %8s %8s %8s\n' "$name" "$PEAK_J" "$MEAN_J" "$LAST_ENT" "$LAST_CF"
  else
    printf '%-30s %8s\n' "$name" "NO LOG"
  fi
done

echo ''
echo '=== CRITICAL CHECK: Did entropy stay > 0.1? ==='
for name in E1_high_ent E2_cosine_ent E3_adaptive_ent E4_belt_suspenders; do
  LOG=$RESULTS/${name}.log
  MIN_ENT=$(grep -o 'entropy[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -n | head -1)
  MAX_ENT=$(grep -o 'entropy[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
  LAST_ENT=$(grep -o 'entropy[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | tail -1)
  if [ -z "$MIN_ENT" ] || [ "$MIN_ENT" = "0.000" ]; then
    echo "  $name: ENTROPY COLLAPSED (min=$MIN_ENT, max=$MAX_ENT, last=$LAST_ENT)"
  else
    echo "  $name: entropy_range=[$MIN_ENT, $MAX_ENT], last=$LAST_ENT — SURVIVED!"
  fi
done

echo ''
echo 'Generating training graphs...'
python3 scripts/sweep/plot_training.py \
  $RESULTS/E1_high_ent.log \
  $RESULTS/E2_cosine_ent.log \
  $RESULTS/E3_adaptive_ent.log \
  $RESULTS/E4_belt_suspenders.log \
  2>/dev/null || echo "Plot generation failed"

echo ''
echo "Disk: $(df -h / | tail -1 | awk '{print $4}') free"
