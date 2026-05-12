# Training and Leaderboard Submission Guide

> Workflow guide for developing, training, evaluating, and submitting CoGsGuard policies.

---

## 1. Local Development Loop

The local loop lets you iterate on policies without GPU training. Use the `cogames` CLI.

> **Note:** When running locally in a uv-managed workspace, prefix commands with `uv run` (e.g.,
> `uv run cogames play ...`, `uv run python ...`). Inside mettabox Docker containers (section 4), commands run directly
> without `uv run`.

### Play (Interactive)

Run a single episode with visual feedback:

```bash
# Default GUI mode with a scripted policy
uv run cogames play -m arena -p role

# Terminal mode
uv run cogames play -m arena -p role -r unicode

# Log-only (no GUI)
uv run cogames play -m arena -p role -r log -s 500
```

Available scripted policies: `role`, `role_nim`, `teacher`, `baseline`, `cogsguard_v2`, `wombo`, `cogsguard_control`,
`cogsguard_targeted`.

Tutorial role specialists (`miner`, `scout`, `aligner`, `scrambler`) are canonical in `cogames`.

Use `uv run cogames policies` to list all policies.

### Scrimmage (Single-Policy Evaluation)

Run multiple episodes and collect metrics:

```bash
# 10 episodes, default settings
uv run cogames scrimmage -m arena -p role

# More episodes, longer steps, JSON output
uv run cogames scrimmage -m arena -p role -e 50 -s 2000 --format json

# Evaluate a trained checkpoint
uv run cogames scrimmage -m arena -p ./train_dir/my_run:v5
```

### Run (Multi-Policy Evaluation)

Evaluate multiple policies together (each controls a proportion of agents):

```bash
# Two policies competing
uv run cogames run -m arena -p role -p random

# Custom proportions (3:5 split)
uv run cogames run -m arena \
  -p ./train_dir/my_run:v5,proportion=3 \
  -p class=random,proportion=5

# Evaluate on the main Machina1 mission
uv run cogames run -m machina_1 -p ./train_dir/my_run:v5
```

### Evaluate via Recipe Runner (Advanced)

The recipe runner (`tools/run.py`) provides more configuration:

```bash
uv run python tools/run.py recipes.experiment.cogsguard.play \
  policy_uri=metta://policy/role render=gui max_steps=1000

uv run python tools/run.py recipes.experiment.cogsguard.evaluate
```

---

## 2. BC Training with Scripted Teachers

Behavioral cloning (BC) trains a neural policy to imitate a scripted teacher while PPO optimizes for reward. This hybrid
approach produced the best results in prior experiments.

### Teacher Options

| Teacher    | URI / Name                         | Description                                   |
| ---------- | ---------------------------------- | --------------------------------------------- |
| smart-gear | `metta://policy/cogsguard?gear=10` | Meta role that selects optimal gear per agent |
| cogsguard  | `metta://policy/cogsguard`         | Full multi-role scripted agent                |
| teacher    | `metta://policy/teacher`           | Wrapper that forces initial vibe              |
| miner      | `metta://policy/miner`             | Single-role: resource extraction              |
| scout      | `metta://policy/scout`             | Single-role: map exploration                  |
| aligner    | `metta://policy/aligner`           | Single-role: junction alignment               |
| scrambler  | `metta://policy/scrambler`         | Single-role: anti-clips disruption            |

**Recommended starting teacher:** `metta://policy/cogsguard?gear=10` (smart-gear meta role).

### CLI Training

```bash
# BC training with smart-gear teacher
uv run cogames tutorial train -m arena \
  --steps 5000000000 \
  --batch-size 2097152 \
  -p lstm

# Smaller local test
uv run cogames tutorial train -m arena \
  --steps 1000000 \
  --batch-size 4096 \
  --device cpu
```

### Recipe Runner Training (Full Config Control)

```bash
# Recommended: BC with smart-gear teacher
uv run python tools/run.py recipes.experiment.cogsguard.train \
    run=my-cogsguard-bc-001 \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/cogsguard?gear=10", teacher_led_proportion: 0.5, student_led_proportion: 0.5}' \
    trainer.total_timesteps=5_000_000_000 \
    trainer.batch_size=2097152

# Pure PPO (no teacher)
uv run python tools/run.py recipes.experiment.cogsguard.train \
    run=my-cogsguard-ppo-001 \
    trainer.total_timesteps=10_000_000_000

# Curriculum: start with a single role
uv run python tools/run.py recipes.experiment.cogsguard.train \
    run=my-cogsguard-miner-001 \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/miner", teacher_led_proportion: 0.7}' \
    trainer.total_timesteps=2_000_000_000
```

### Key Training Config (Reference)

From the best-performing prior runs (machina1_cloner series):

```yaml
trainer:
  total_timesteps: 20_000_000_000
  batch_size: 2097152
  losses:
    ppo_actor:
      enabled: true
      ent_coef: 0.01
      norm_adv: true
      clip_coef: 0.22
    ppo_critic:
      enabled: true
      vf_coef: 0.50
      critic_update: gtd_lambda
    sliced_scripted_cloner:
      enabled: true
      action_loss_coef: 1
      student_led_proportion: 0.5
      teacher_led_proportion: 0.5

training_env:
  supervisor_policy_uri: 'metta://policy/cogsguard?gear=10'
```

---

## 3. Key W&B Metrics to Monitor

Jobs log to Weights & Biases automatically. Check the dashboard at `wandb.ai/metta-research/metta`.

| Metric                                      | What It Tells You         | Target           |
| ------------------------------------------- | ------------------------- | ---------------- |
| `env_agent/heart.gained`                    | Hearts collected          | Higher is better |
| `env_collective/cogs/aligned.junction.held` | Junction alignment        | Higher is better |
| `overview/reward`                           | Episode reward            | Increasing trend |
| `losses/approx_kl`                          | KL divergence (stability) | < 0.03           |

**What to look for:**

- `heart.gained` should climb within the first 1B steps if BC is working.
- If `approx_kl` spikes above 0.03, the learning rate may be too high or the teacher/student proportion needs
  adjustment.
- Compare against the machina1 baselines: top runs achieved heart.gained of 10-14.

---

## 4. Mettabox GPU Training Setup

The mettaboxes (metta0, metta1, metta2) are RTX 4090 (24GB VRAM) machines for GPU training.

### Connecting

```bash
ssh metta@metta0   # or metta1, metta2
```

You'll auto-enter the metta Docker container with tmux. If not:

```bash
cd /home/metta/metta/devops/mettabox && bash docker.sh test
```

### Running a Training Job

```bash
# Inside the container
python tools/run.py recipes.experiment.cogsguard.train \
    run=my_experiment_name \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/cogsguard?gear=10", teacher_led_proportion: 0.5, student_led_proportion: 0.5}' \
    trainer.total_timesteps=5_000_000_000 \
    trainer.batch_size=2097152
```

### Directory Layout

```
# Host
/home/metta/data_dir/<run_id>/     # Checkpoints and logs

# Container
/workspace/metta/train_dir/<run_id>/  # Same via mount
```

### Monitoring

```bash
# GPU utilization
watch -n 1 nvidia-smi

# Check if a machine is free
ssh metta@metta0 nvidia-smi
ssh metta@metta1 nvidia-smi
ssh metta@metta2 nvidia-smi
```

### Tmux Basics

- `Ctrl+b d` — detach (job keeps running)
- `tmux attach` — reattach
- `Ctrl+b c` — new window
- `Ctrl+b n/p` — next/prev window

### AWS SSO (If Needed)

If AWS credentials expire inside the container:

```bash
# From your local machine
uv run python devops/mettabox/cli.py exec metta1 -- \
  /usr/local/bin/aws sso login --profile softmax --no-browser

# Open an SSH tunnel for the callback port shown in the URL
ssh -L <PORT>:127.0.0.1:<PORT> metta@metta1

# Open the printed URL in your browser to complete login
```

---

## 5. Rollout and Parity Testing Scripts

Three scripts in `cogames-agents/scripts/` provide diagnostic tooling for scripted policies.

### Rollout Sanity Check

`run_cogsguard_rollout.py` runs a short rollout and validates structure discovery, role behavior, and gear acquisition:

```bash
uv run python scripts/run_cogsguard_rollout.py \
  --steps 200 \
  --agents 10 \
  --policy-uri "metta://policy/role?miner=4&scout=2&aligner=2&scrambler=2"

# With tracing enabled
uv run python scripts/run_cogsguard_rollout.py \
  --steps 500 \
  --trace-roles \
  --trace-prereqs \
  --trace-resources
```

What it checks:

- Hub discovery and structure registration
- Charger alignment consistency (cogs vs clips tags)
- All four roles observed (miner, scout, aligner, scrambler)
- Miner deposits resources near aligned structures
- Aligner/scrambler target correct structure types
- Gear acquisition and station usage

Exit code 0 = pass, 1 = failure detected.

### Parity Comparison

`run_cogsguard_parity.py` compares action distributions between two policies:

```bash
uv run python scripts/run_cogsguard_parity.py \
  --policy-a "metta://policy/role_nim" \
  --policy-b "metta://policy/role" \
  --steps 500 \
  --agents 10
```

Reports per-policy action counts, move success rates, and the largest action deltas between the two policies. Useful for
verifying Nim/Python parity or comparing policy versions.

### Instrumented Audit

`run_cogsguard_instrumented_audit.py` produces detailed role and resource traces over a longer rollout:

```bash
uv run python scripts/run_cogsguard_instrumented_audit.py \
  --steps 1000 \
  --agents 2 \
  --policy-uri "metta://policy/role?miner=1&scout=1" \
  --trace-every 200
```

Outputs:

- Per-step role distribution trace
- Collective resource inventory over time (with deltas)
- Role transition counts
- Structure counts per agent (junctions, extractors)

---

## 6. Instrumented Audit Workflow

Use the audit workflow to diagnose policy behavior before training or after a regression.

### Quick Diagnosis

```bash
# 1. Run the rollout sanity check
uv run python scripts/run_cogsguard_rollout.py --steps 500 --agents 10 --trace-roles

# 2. If failures: run the instrumented audit for detailed traces
uv run python scripts/run_cogsguard_instrumented_audit.py --steps 1000 --agents 10 --trace-every 50

# 3. If comparing two implementations: run parity
uv run python scripts/run_cogsguard_parity.py --policy-a role_nim --policy-b role --steps 500
```

### What to Look For

- **Role coverage**: All four roles (miner, scout, aligner, scrambler) should be active. If `steps_with_all_roles` is 0,
  role assignment is broken.
- **Gear acquisition**: `gear_acquired` should be > 0 for roles that need gear. If `gear_attempts_without_resources` is
  high, the collective isn't producing enough resources.
- **Structure targeting**: `mine_mismatches`, `align_mismatches`, `scramble_mismatches` should all be 0. Non-zero means
  agents target wrong structure types.
- **Resource flow**: In the resource trace, watch for `heart`, `ore`, `influence` accumulating over time. Flat lines
  indicate broken production.

---

## 7. Submission and Leaderboard

The `cogames` CLI handles the full upload-submit-leaderboard flow.

### Prerequisites

```bash
# Authenticate (one-time)
uv run cogames auth login
```

### Upload a Policy

Canonical portable flow:

```bash
# 1. Build a self-contained submission bundle
uv run cogames create-bundle -p <policy-or-checkpoint> -o ./submission.zip \
  [-f <extra-path> ...] [--setup-script <setup.py>]

# 2. Dry-run the portable bundle
uv run cogames upload -p ./submission.zip -n my-policy --dry-run

# 3. Upload for real
uv run cogames upload -p ./submission.zip -n my-policy --no-submit

# 4. Submit latest version
uv run cogames submit my-policy --season beta-cogsguard
```

If your `-p` value already points at a self-contained bundle directory or zip, you can upload it directly. For
Metta-trained checkpoints in this repo, use `agent/COGAMES_SUBMISSION.md` for the exact bundle command.

### Submit to a Tournament

```bash
# Submit latest version
uv run cogames submit my-policy --season beta-cogsguard

# Submit a specific version
uv run cogames submit my-policy:v3 --season beta-cogsguard
```

### Check Status

```bash
# View your uploads and submissions
uv run cogames submissions

# View available seasons
uv run cogames season list

# View leaderboard
uv run cogames leaderboard --season beta-cogsguard

# JSON output for scripting
uv run cogames leaderboard --season beta-cogsguard --json
```

---

## 8. Common Recipes and Configuration Patterns

### Recipe: BC with Smart-Gear Teacher (Recommended Starting Point)

```bash
ssh metta@metta0
python tools/run.py recipes.experiment.cogsguard.train \
    run=cogsguard-bc-smartgear-v1 \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/cogsguard?gear=10", teacher_led_proportion: 0.5, student_led_proportion: 0.5}' \
    trainer.total_timesteps=5_000_000_000 \
    trainer.batch_size=2097152
```

### Recipe: Curriculum Training (Role-by-Role)

Train on one role at a time, then combine:

```bash
# Phase 1: Miner (high teacher proportion)
python tools/run.py recipes.experiment.cogsguard.train \
    run=cogsguard-curriculum-miner \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/miner", teacher_led_proportion: 0.7}' \
    trainer.total_timesteps=2_000_000_000

# Phase 2: Switch to full cogsguard teacher, lower teacher proportion
python tools/run.py recipes.experiment.cogsguard.train \
    run=cogsguard-curriculum-full \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/cogsguard?gear=10", teacher_led_proportion: 0.3, student_led_proportion: 0.7}' \
    trainer.total_timesteps=5_000_000_000
```

### Recipe: Pure PPO (No Teacher)

```bash
python tools/run.py recipes.experiment.cogsguard.train \
    run=cogsguard-ppo-baseline \
    trainer.total_timesteps=10_000_000_000
```

### Recipe: Quick Local Validation

```bash
uv run cogames tutorial train -m arena --steps 100000 --batch-size 4096 --device cpu
```

### Tuning Parameters

| Parameter                | Range to Try   | Effect                                     |
| ------------------------ | -------------- | ------------------------------------------ |
| `teacher_led_proportion` | 0.3 - 0.7      | Higher = more cloning, less exploration    |
| `batch_size`             | 4096 - 2097152 | Larger = more stable but slower per update |
| `total_timesteps`        | 1B - 20B       | Longer = more thorough but more compute    |
| `ent_coef`               | 0.005 - 0.02   | Higher = more exploration                  |
| `clip_coef`              | 0.1 - 0.3      | PPO clipping range                         |

### Full End-to-End Workflow

```bash
# 1. Develop locally
uv run cogames play -m arena -p role -r log
uv run cogames scrimmage -m arena -p role -e 20

# 2. Train on mettabox
ssh metta@metta0
python tools/run.py recipes.experiment.cogsguard.train \
    run=my-run \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/cogsguard?gear=10", teacher_led_proportion: 0.5, student_led_proportion: 0.5}' \
    trainer.total_timesteps=5_000_000_000 \
    trainer.batch_size=2097152

# 3. Monitor on W&B
# Check wandb.ai/metta-research/metta for heart.gained and reward curves

# 4. Evaluate the checkpoint
uv run cogames scrimmage -m arena -p ./train_dir/my-run -e 50
uv run cogames run -m machina_1 -p ./train_dir/my-run

# 5. Build a portable submission bundle, upload it, then submit it
# For Metta-trained checkpoints in this repo, see agent/COGAMES_SUBMISSION.md
uv run cogames create-bundle -p <policy-or-checkpoint> -o ./submission.zip \
  [-f <extra-path> ...] [--setup-script <setup.py>]
uv run cogames upload -p ./submission.zip -n my-policy --no-submit
uv run cogames submit my-policy --season beta-cogsguard

# 6. Check standings
uv run cogames leaderboard --season beta-cogsguard
```
