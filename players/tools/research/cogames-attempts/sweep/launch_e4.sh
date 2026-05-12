#!/bin/bash
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

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

python3 scripts/sweep/patch_and_train.py train -m machina_1 -v no_clips -v milestones -v credit \
  -p 'class=cortex_policy.CortexSLSTMPolicy' \
  --cogs 8 --steps 1000000000 --device auto \
  --checkpoints ./results_v22/E4_belt_suspenders \
  > ./results_v22/E4_belt_suspenders.log 2>&1
