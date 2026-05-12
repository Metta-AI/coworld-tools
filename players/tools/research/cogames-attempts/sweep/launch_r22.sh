#!/bin/bash
# Round 22: Scale E4 + Test Fixed Adaptive Controller
#
# R21 finding: E4 (ent=0.15) was the ONLY run that survived entropy collapse.
# The adaptive controller had 3 bugs (now fixed):
#   1. Gate excluded "cosine" mode
#   2. Entropy lookup used trainer.stats instead of trainer.losses
#   3. Used trainer.config instead of trainer.train_args
#
# GPU 0: F1 — E4 config scaled to 2B steps (does it keep improving?)
# GPU 1: F2 — Adaptive controller (fixed) with ent_coef=0.05 start, floor=0.3
# GPU 2: F3 — ent_coef=0.12 (between 0.08 collapse and 0.15 survival)
# GPU 3: F4 — Cosine schedule (fixed) 0.15 -> 0.05 over 2B steps
#
# All: 2B steps each (~20 hours per L4 GPU)

cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v22
PATCH=scripts/sweep/patch_and_train.py
MISSION=machina_1
COGS=8

mkdir -p $RESULTS

echo '========================================'
echo 'Round 22: Scale E4 + Fixed Adaptive'
echo '========================================'
date

# Apply kickstart source patch
echo 'Applying kickstart patches to pufferl.py...'
python3 scripts/sweep/apply_kickstart_patches.py
echo ''

# GPU 0: F1 — E4 config at 2B steps
echo '[GPU 0] F1: E4 config (ent=0.15), 2B steps...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export SWEEP_OVERRIDES='{"ent_coef": 0.15}'
  export KICKSTART_MODE=kl
  export KS_COEF=0.3
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.3
  export KS_ANNEAL_END=0.6
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 2000000000 --device auto \
    --checkpoints $RESULTS/F1_e4_2B \
    > $RESULTS/F1_e4_2B.log 2>&1
) &
PID_F1=$!

# GPU 1: F2 — Fixed adaptive controller, start ent=0.05, floor=0.3
echo '[GPU 1] F2: Fixed adaptive (floor=0.3, start=0.05), 2B steps...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export SWEEP_OVERRIDES='{"ent_coef": 0.05}'
  export KICKSTART_MODE=kl
  export KS_COEF=0.3
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.3
  export KS_ANNEAL_END=0.6
  export ENTROPY_MODE=adaptive
  export ENTROPY_FLOOR=0.3
  export ENTROPY_CEIL=1.0
  export ENT_COEF_MIN=0.02
  export ENT_COEF_MAX=0.25
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 2000000000 --device auto \
    --checkpoints $RESULTS/F2_adaptive_fixed \
    > $RESULTS/F2_adaptive_fixed.log 2>&1
) &
PID_F2=$!

# GPU 2: F3 — ent_coef=0.12 (between 0.08 collapse and 0.15 survival)
echo '[GPU 2] F3: ent_coef=0.12 (threshold test), 2B steps...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_FIXES=sep_lr,redo
  export SWEEP_OVERRIDES='{"ent_coef": 0.12}'
  export KICKSTART_MODE=kl
  export KS_COEF=0.3
  export KS_TEMPERATURE=2.0
  export KS_ANNEAL_START=0.3
  export KS_ANNEAL_END=0.6
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 2000000000 --device auto \
    --checkpoints $RESULTS/F3_ent012 \
    > $RESULTS/F3_ent012.log 2>&1
) &
PID_F3=$!

# GPU 3: F4 — Fixed cosine schedule 0.15 -> 0.05 over 2B
echo '[GPU 3] F4: Cosine schedule 0.15->0.05 (fixed), 2B steps...'
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
  export ENTROPY_MODE=cosine
  export ENT_COEF_MAX=0.15
  export ENT_COEF_MIN=0.05
  python3 $PATCH train -m $MISSION -v no_clips -v milestones -v credit \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps 2000000000 --device auto \
    --checkpoints $RESULTS/F4_cosine_fixed \
    > $RESULTS/F4_cosine_fixed.log 2>&1
) &
PID_F4=$!

echo ""
echo "PIDs: F1=$PID_F1 F2=$PID_F2 F3=$PID_F3 F4=$PID_F4"
echo "Each ~20 hours (2B steps on L4)"
echo ""
echo "Monitor:"
echo "  tail -f $RESULTS/F1_e4_2B.log"
echo "  grep '\[ENTROPY\]' $RESULTS/F2_adaptive_fixed.log"
echo "  grep 'entropy' $RESULTS/F3_ent012.log | tail -5"
