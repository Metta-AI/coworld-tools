# co_gas

**Mission: Get to the top of the Beta-CogsGuard leaderboard.**

We build competitive CogsGuard agents — scripted baselines, trained policies, and optimized submissions — all aimed at
ranking #1.

## Approach

1. **Scripted agent baselines** — hand-coded strategies in `cogames-agents/` covering guard and intruder roles
2. **Behavioral cloning (BC)** — train neural policies from scripted agent demonstrations
3. **PPO optimization** — fine-tune trained policies with reinforcement learning
4. **Leaderboard submission** — evaluate and submit top-performing agents

## Quick Start

```bash
# Play a scripted agent locally
cogames play --mission CogsGuard

# Train a policy via BC or PPO
cogames tutorial train --mission CogsGuard

# Run a scrimmage between agents
cogames scrimmage --mission CogsGuard
```

## Repository Structure

- `cogames-agents/` — scripted agents, evolution system, and training workflows
- `cogames-agents/docs/` — detailed documentation (see index below)

## Docs Index

See [`cogames-agents/docs/`](cogames-agents/docs/) for full documentation:

- [Creating Scripted Agents](cogames-agents/docs/creating-scripted-agents.md)
- [Evolution System Architecture](cogames-agents/docs/evolution-system-architecture.md)
- [Training & Submission Guide](cogames-agents/docs/training-and-submission-guide.md)
- [Scripted Agent Registry](cogames-agents/docs/scripted-agent-registry.md)
- [Nim vs Python Agents Comparison](cogames-agents/docs/nim-vs-python-agents-comparison.md)
- [Mettaboxes](cogames-agents/docs/mettaboxes.md)
- [W&B Analysis](cogames-agents/docs/wandb-analysis-cogsguard-training.md)

## Team

Rig: `co_gas/polecats/rust`
