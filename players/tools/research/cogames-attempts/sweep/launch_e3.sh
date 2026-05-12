#!/bin/bash
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

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

python3 scripts/sweep/patch_and_train.py train -m machina_1 -v no_clips -v milestones -v credit \
  -p 'class=cortex_policy.CortexSLSTMPolicy' \
  --cogs 8 --steps 1000000000 --device auto \
  --checkpoints ./results_v22/E3_adaptive_ent \
  > ./results_v22/E3_adaptive_ent.log 2>&1
