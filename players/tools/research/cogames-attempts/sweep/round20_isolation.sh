#!/bin/bash
# Round 20: Isolation Experiments — What closes the gap?
#
# S1 hit 7.0j (new best!) at the END of 500M steps.
# The policy was just starting autonomous learning when training ended.
# This round tests: (1) more training, (2) credit rewards, (3) credit + KS, (4) credit + role_conditional.
#
# GPU 0: T1 — Warm-start from S1 weights, NO kickstarting, 1.5B more steps (2B total effective)
# GPU 1: T2 — Warm-start from S1 weights, NO kickstarting, + milestones,credit rewards, 1B steps
# GPU 2: T3 — FRESH start, KL KS coef=0.3 anneal 30-60%, milestones,credit, 1B steps
# GPU 3: T4 — FRESH start, KL KS coef=0.3 anneal 30-60%, milestones,credit,role_conditional, 1B steps
#
# Questions answered:
#   T1: Does pure PPO with S1's warm weights scale to 2B?
#   T2: Does adding dense credit rewards to a warm policy accelerate learning?
#   T3: Does fresh KL kickstarting + credit rewards outperform warm-start?
#   T4: Does role_conditional add value on top of T3?
#
# CRITICAL DIAGNOSTIC: aligner_gained > 0 (T2/T3/T4 use credit variant — this WILL be tracked)

cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v22
PATCH=scripts/sweep/patch_and_train.py
MISSION=machina_1
COGS=8
S1_CKPT=results_v22/S1_kl_kickstart/177523163232/model_000925.pt

mkdir -p $RESULTS

echo '========================================'
echo 'Round 20: Isolation Experiments'
echo '========================================'
date
echo "S1 checkpoint: $S1_CKPT"
ls -la $S1_CKPT 2>/dev/null || echo "WARNING: S1 checkpoint not found!"

# Apply kickstart source patch (needed for T3/T4)
echo 'Applying kickstart patches to pufferl.py...'
python3 scripts/sweep/apply_kickstart_patches.py
echo ''

# GPU 0: T1 — Warm-start S1, no KS, 1.5B more steps
echo '[GPU 0] T1: S1 warm-start, pure PPO, 1.5B steps...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  # No KICKSTART_MODE — pure PPO continuation
  python3 $PATCH train -m $MISSION -v no_clips \
    -p "class=cortex_policy.CortexSLSTMPolicy,data=$S1_CKPT" \
    --cogs $COGS --steps 1500000000 --device auto \
    --checkpoints $RESULTS/T1_warmstart_ppo \
    > $RESULTS/T1_warmstart_ppo.log 2>&1
) &
PID_T1=$!

# GPU 1: T2 — Warm-start S1 + milestones,credit rewards, 1B steps
echo '[GPU 1] T2: S1 warm-start + credit rewards, 1B steps...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  # No KICKSTART_MODE — just adding credit rewards
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p "class=cortex_policy.CortexSLSTMPolicy,data=$S1_CKPT" \
    --cogs $COGS --steps 1000000000 --device auto \
    --checkpoints $RESULTS/T2_warmstart_credit \
    > $RESULTS/T2_warmstart_credit.log 2>&1
) &
PID_T2=$!

# GPU 2: T3 — Fresh start, KL KS coef=0.3 anneal 30-60%, milestones,credit, 1B steps
echo '[GPU 2] T3: Fresh + KL KS 0.3 + credit, 1B steps...'
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
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 1000000000 --device auto \
    --checkpoints $RESULTS/T3_fresh_ks_credit \
    > $RESULTS/T3_fresh_ks_credit.log 2>&1
) &
PID_T3=$!

# GPU 3: T4 — Fresh, KL KS 0.3, milestones,credit,role_conditional, 1B steps
echo '[GPU 3] T4: Fresh + KL KS 0.3 + credit + role_conditional, 1B steps...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export KICKSTART_MODE=kl
  export KS_COEF=0.3
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.3
  export KS_ANNEAL_END=0.6
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit -v role_conditional \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 1000000000 --device auto \
    --checkpoints $RESULTS/T4_fresh_ks_credit_role \
    > $RESULTS/T4_fresh_ks_credit_role.log 2>&1
) &
PID_T4=$!

echo ""
echo "PIDs: T1=$PID_T1 T2=$PID_T2 T3=$PID_T3 T4=$PID_T4"
echo "T1: ~15 hours (1.5B steps)"
echo "T2/T3/T4: ~10 hours each (1B steps)"
echo ""
echo "Waiting for all..."

wait $PID_T1 || echo "T1 exited with code $?"
wait $PID_T2 || echo "T2 exited with code $?"
wait $PID_T3 || echo "T3 exited with code $?"
wait $PID_T4 || echo "T4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 20 COMPLETE — Results'
echo '========================================'
date

printf '%-30s %8s %8s %8s %8s %s\n' 'Experiment' 'Peak_J' 'Mean_J' 'Entropy' 'Clipfrac' 'Aligner_Gained'
printf '%-30s %8s %8s %8s %8s %s\n' '----------' '------' '------' '-------' '--------' '--------------'

for name in T1_warmstart_ppo T2_warmstart_credit T3_fresh_ks_credit T4_fresh_ks_credit_role; do
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

    printf '%-30s %8s %8s %8s %8s %s\n' "$name" "$PEAK_J" "$MEAN_J" "$LAST_ENT" "$LAST_CF" "$AG"
  else
    printf '%-30s %8s\n' "$name" "NO LOG"
  fi
done

echo ''
echo '=== CRITICAL CHECK: aligner_gained > 0 ? ==='
for name in T1_warmstart_ppo T2_warmstart_credit T3_fresh_ks_credit T4_fresh_ks_credit_role; do
  LOG=$RESULTS/${name}.log
  AG_MAX=$(grep -o 'aligner\.gained[^0-9]*[0-9.]*' "$LOG" 2>/dev/null | grep -o '[0-9.]*$' | sort -rn | head -1)
  if [ -z "$AG_MAX" ] || [ "$AG_MAX" = "0" ]; then
    echo "  $name: aligner_gained = 0 — NO GEAR ACQUISITION"
  else
    echo "  $name: aligner_gained = $AG_MAX — GEAR ACQUISITION DETECTED!"
  fi
done

echo ''
echo 'Generating training graphs...'
python3 scripts/sweep/plot_training.py \
  $RESULTS/T1_warmstart_ppo.log \
  $RESULTS/T2_warmstart_credit.log \
  $RESULTS/T3_fresh_ks_credit.log \
  $RESULTS/T4_fresh_ks_credit_role.log \
  2>/dev/null || echo "Plot generation failed"

echo ''
echo "Disk: $(df -h / | tail -1 | awk '{print $4}') free"
