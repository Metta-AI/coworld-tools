#!/bin/bash
# Relaunch T2/T3/T4 with fixed -v syntax (separate -v flags, not comma-separated)
# T1 is already running on GPU 0.
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v22
PATCH=scripts/sweep/patch_and_train.py
MISSION=machina_1
COGS=8
S1_CKPT=results_v22/S1_kl_kickstart/177523163232/model_000925.pt

# Clear old failed logs
rm -f $RESULTS/T2_warmstart_credit.log $RESULTS/T3_fresh_ks_credit.log $RESULTS/T4_fresh_ks_credit_role.log

echo "Relaunching T2/T3/T4 with fixed variant syntax..."
date

# GPU 1: T2 — Warm-start S1 + credit rewards
echo '[GPU 1] T2: S1 warm-start + credit rewards, 1B steps...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p "class=cortex_policy.CortexSLSTMPolicy,data=$S1_CKPT" \
    --cogs $COGS --steps 1000000000 --device auto \
    --checkpoints $RESULTS/T2_warmstart_credit \
    > $RESULTS/T2_warmstart_credit.log 2>&1
) &
PID_T2=$!

# GPU 2: T3 — Fresh, KL KS coef=0.3, credit
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

# GPU 3: T4 — Fresh, KL KS 0.3, credit + role_conditional
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

echo "PIDs: T2=$PID_T2 T3=$PID_T3 T4=$PID_T4"
echo "Each ~10 hours (1B steps on L4)"
echo "T1 already running on GPU 0."
