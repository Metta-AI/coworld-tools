#!/bin/bash
# Round 18: Batch Size + BPTT
# Testing whether larger batch sizes close the gap further.
# Uses Q1 winner config (metta_optimal) as base.
# Batch size controlled via --num-envs and --num-agents-per-env flags.
# PufferLib batch_size = num_envs * num_agents_per_env * bptt_horizon
cd ~/projects/cogames-agents
source ~/projects/cogames-env/bin/activate

RESULTS=./results_v22
PATCH=scripts/sweep/patch_and_train.py
MISSION=machina_1
COGS=8
STEPS=50000000

mkdir -p $RESULTS

echo '========================================'
echo 'Round 18: Batch Size + BPTT'
echo '========================================'
date

# NOTE: Adjust --num-envs to increase batch size.
# Default: ~8 envs * 8 agents * 64 bptt = ~4K per segment, ~65K total batch
# Target: 256K-1M batch sizes
# With bptt=256 (metta default), 8 agents:
#   num_envs=128 → 128*8*256 = 262K batch
#   num_envs=256 → 256*8*256 = 524K batch
#   num_envs=512 → 512*8*256 = 1M batch
# Memory per env ~100MB, so 512 envs needs ~50GB VRAM (may need CPU envs)

# GPU 0: R1 — batch_size ~256K (128 envs)
echo '[GPU 0] R1: batch ~256K...'
(
  export CUDA_VISIBLE_DEVICES=0
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --num-envs 128 \
    --checkpoints $RESULTS/R1_batch256k \
    > $RESULTS/R1_batch256k.log 2>&1
) &
PID_R1=$!

# GPU 1: R2 — batch_size ~512K (256 envs)
echo '[GPU 1] R2: batch ~512K...'
(
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --num-envs 256 \
    --checkpoints $RESULTS/R2_batch512k \
    > $RESULTS/R2_batch512k.log 2>&1
) &
PID_R2=$!

# GPU 2: R3 — batch_size ~1M (512 envs) — approaching metta's 2M
echo '[GPU 2] R3: batch ~1M...'
(
  export CUDA_VISIBLE_DEVICES=2
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --num-envs 512 \
    --checkpoints $RESULTS/R3_batch1M \
    > $RESULTS/R3_batch1M.log 2>&1
) &
PID_R3=$!

# GPU 3: R4 — bptt=256 explicitly (metta value, should be set by preset but confirm)
# Also test with bptt=512 to see if even longer context helps
echo '[GPU 3] R4: bptt=512...'
(
  export CUDA_VISIBLE_DEVICES=3
  export PYTHONPATH=scripts/policy
  export SWEEP_PRESET=metta_optimal
  export SWEEP_OVERRIDES='{"bptt_horizon": 512}'
  python3 $PATCH train -m $MISSION -v no_clips \
    -p 'class=cortex_policy.CortexSLSTMPolicy' \
    --cogs $COGS --steps $STEPS --device auto \
    --checkpoints $RESULTS/R4_bptt512 \
    > $RESULTS/R4_bptt512.log 2>&1
) &
PID_R4=$!

echo "PIDs: R1=$PID_R1 R2=$PID_R2 R3=$PID_R3 R4=$PID_R4"
echo "NOTE: Larger batch sizes may be slower (more envs = more CPU work)"
echo "Waiting for all..."

wait $PID_R1 || echo "R1 exited with code $?"
wait $PID_R2 || echo "R2 exited with code $?"
wait $PID_R3 || echo "R3 exited with code $?"
wait $PID_R4 || echo "R4 exited with code $?"

echo ''
echo '========================================'
echo 'Round 18 COMPLETE — Results'
echo '========================================'
date

printf '%-30s %8s %8s %8s %8s %s\n' 'Experiment' 'Peak_J' 'Mean_J' 'Entropy' 'Clipfrac' 'Aligner_Gained'
printf '%-30s %8s %8s %8s %8s %s\n' '----------' '------' '------' '-------' '--------' '--------------'

for name in R1_batch256k R2_batch512k R3_batch1M R4_bptt512; do
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
echo 'Generating training graphs...'
python3 scripts/sweep/plot_training.py $RESULTS/R1_batch256k.log $RESULTS/R2_batch512k.log $RESULTS/R3_batch1M.log $RESULTS/R4_bptt512.log 2>/dev/null || echo "Plot generation failed"

echo ''
echo "Disk: $(df -h / | tail -1 | awk '{print $4}') free"
