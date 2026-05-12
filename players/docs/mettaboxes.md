# Mettabox Guide

Guide for using mettaboxes (metta0, metta1, metta2) for GPU training jobs.

## Machine Overview

| Machine | GPU             | Status    | SSH Access         |
| ------- | --------------- | --------- | ------------------ |
| metta0  | RTX 4090 (24GB) | Available | `ssh metta@metta0` |
| metta1  | RTX 4090 (24GB) | Available | `ssh metta@metta1` |
| metta2  | RTX 4090 (24GB) | Available | `ssh metta@metta2` |

All machines run CUDA 12.8 and have identical setups.

## Quick Start

```bash
# 1. SSH to a mettabox
ssh metta@metta0

# 2. You'll automatically be inside the metta container with tmux
# If not already in container, run:
cd /home/metta/metta/devops/mettabox && bash docker.sh test

# 3. Run a training job
python tools/run.py cogsguard.train run=my_experiment_name

# 4. Run a quick test
python tools/run.py cogsguard.play max_steps=100 render=log
```

## Architecture

### Directory Structure

```
/home/metta/                      # Host machine home
├── metta/                        # Metta repo (synced)
│   └── devops/mettabox/          # Container setup
│       └── docker.sh             # Container launcher script
├── data_dir/                     # Training data (mounted to container)
└── .aws/                         # AWS credentials (mounted to container)

# Inside container:
/workspace/metta/                 # Metta repo
├── tools/run.py                  # Job launcher
├── recipes/experiment/           # Available training recipes
├── train_dir/                    # Training outputs (mounted from host data_dir)
└── wandb/                        # Weights & Biases logs
```

### Container Setup

The mettaboxes run a Docker container from AWS ECR:

- Image: `751442549699.dkr.ecr.us-east-1.amazonaws.com/metta:latest`
- Container name: `metta`
- Auto-starts on SSH (configured in `.bashrc`)

Container features:

- Full GPU access (`--gpus all`)
- 80GB shared memory (`--shm-size=80g`)
- Host networking (`--network host`)
- Persistent data via volume mounts

## Running Training Jobs

### Basic Command Structure

```bash
python tools/run.py <recipe>.<tool> [key=value args...]
```

### Available Recipes

| Recipe       | Description                   |
| ------------ | ----------------------------- |
| `cogsguard`  | CogsGuard training/evaluation |
| `arena`      | Arena-based training          |
| `machina_1`  | Machina experiments           |
| `navigation` | Navigation tasks              |

### Common Tools

| Tool       | Purpose                        |
| ---------- | ------------------------------ |
| `train`    | Train a new policy             |
| `evaluate` | Run evaluation suite           |
| `play`     | Interactive gameplay (browser) |
| `replay`   | View recorded gameplay         |

### Examples

```bash
# Train cogsguard with custom run name
python tools/run.py cogsguard.train run=my_run_name

# Evaluate a trained model
python tools/run.py cogsguard.evaluate

# Quick test with log output
python tools/run.py cogsguard.play max_steps=100 render=log

# Show all available args
python tools/run.py cogsguard.train -h

# Dry run (validate config without running)
python tools/run.py cogsguard.train --dry-run
```

## Monitoring Jobs

### GPU Utilization

```bash
# On host (outside container)
nvidia-smi
watch -n 1 nvidia-smi  # Live monitoring

# Inside container
nvidia-smi
```

### Weights & Biases

Jobs log to W&B automatically. Check the `wandb/` directory or the W&B dashboard.

### Training Outputs

Checkpoints and logs are saved to:

- Container: `/workspace/metta/train_dir/<run_id>/`
- Host: `/home/metta/data_dir/<run_id>/`

## Checking Machine Status

### Which Machines Are Free?

```bash
# Check if GPU is in use on a machine
ssh metta@metta0 nvidia-smi
ssh metta@metta1 nvidia-smi
ssh metta@metta2 nvidia-smi

# A "free" machine shows no processes under "Processes" section
```

### Is the Container Running?

```bash
ssh metta@metta0 docker ps
# Should show the "metta" container running
```

## Multi-Machine Usage

Jobs do **not** span multiple machines automatically. Each mettabox runs independent jobs.

Workflow for parallel experiments:

1. SSH to each machine in separate terminals
2. Launch different experiments on each
3. Monitor via W&B or individual `nvidia-smi`

## Troubleshooting

### Container Not Starting

```bash
# Check if container exists but stopped
docker ps -a

# Start existing container
docker start metta

# Or run fresh
cd /home/metta/metta/devops/mettabox && bash docker.sh test
```

### AWS/ECR Authentication

```bash
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  751442549699.dkr.ecr.us-east-1.amazonaws.com
```

### GPU Not Detected

```bash
# Verify GPU visible on host
nvidia-smi

# Check container has GPU access
docker exec metta nvidia-smi
```

### Tmux Commands

Inside the container you'll be in tmux:

- `Ctrl+b d` - Detach (leave job running)
- `Ctrl+b c` - New window
- `Ctrl+b n/p` - Next/prev window
- `tmux attach` - Reattach to existing session

## Environment Variables

Set in `~/.metta_env` on host, passed to container:

```
AWS_PROFILE=softmax
AWS_SDK_LOAD_CONFIG=1
AWS_DEFAULT_REGION=us-east-1
```

WANDB_API_KEY is passed from environment.

## Best Practices

1. **Check GPU availability** before launching: `nvidia-smi`
2. **Use descriptive run names**: `run=cogsguard_lr0001_v2`
3. **Detach with tmux** for long runs: `Ctrl+b d`
4. **Monitor via W&B** rather than watching terminal output
5. **Keep one job per machine** - RTX 4090 has 24GB VRAM
