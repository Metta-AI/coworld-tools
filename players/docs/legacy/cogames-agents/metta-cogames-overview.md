# Metta CoGames Overview

This document provides a comprehensive overview of the CoGames ecosystem within the Metta monorepo: packages, CLI
commands, game mechanics, training pipeline, and leaderboard submission.

## 1. Metta Monorepo Structure (CoGames-Relevant)

```
metta/
├── packages/
│   ├── cogames/           # Core game engine, CLI, missions, policies
│   └── cogames-agents/    # Optional scripted & Nim-compiled agent policies
├── cogweb/                # Web frontend (leaderboard UI, tournament dashboards)
├── recipes/
│   ├── prod/cvc/          # Production CogsGuard training recipes
│   └── experiment/        # Experimental recipes (cogsguard, curricula, losses)
├── tools/                 # CLI entry points (run.py for recipe execution)
├── skills/                # CoGames-related skills for automation
├── pyproject.toml         # Root workspace config (uv workspace)
└── uv.lock                # Locked dependencies
```

The monorepo uses **uv workspaces** to manage package interdependencies. `cogames` is the core package; `cogames-agents`
is an optional add-on providing scripted baselines.

## 2. Packages and Their Roles

### cogames (core)

- **Location:** `packages/cogames/`
- **Entry point:** `cogames` CLI (`cogames.main:app`, Typer-based)
- **Purpose:** Game engine, mission definitions, CLI framework, training pipeline, evaluation, leaderboard client
- **Key dependencies:** mettagrid (game simulation), pufferlib-core (RL training), pydantic (config), typer/rich (CLI),
  fastapi/uvicorn (server), httpx (HTTP client)
- **Version:** Managed via `setuptools_scm` with git tags matching `cogames-v*`

### cogames-agents (optional)

- **Location:** `cogames-agents/`
- **Purpose:** Scripted and Nim-compiled agent policies, evolution-based agents, role-specific strategies
- **Key dependencies:** cogames >= 0.0.1, mettagrid == 0.2.0.58, numpy >= 2.0.0
- **Version:** 0.0.1

### mettagrid (environment)

- **Purpose:** Game simulation engine powering all CoGames environments
- **Version:** 0.2.0.58 (pinned)

## 3. CoGames CLI Commands

The CLI is accessed via the `cogames` command. All commands support `-h`/`--help`.

### Mission Discovery

| Command               | Description                        |
| --------------------- | ---------------------------------- |
| `cogames play --help` | Show play flags and mission syntax |
| `cogames run --help`  | Show evaluation flags and examples |

### Playing

| Command                             | Description                             |
| ----------------------------------- | --------------------------------------- |
| `cogames tutorial play`             | Interactive 6-step tutorial with GUI    |
| `cogames play -m MISSION -p POLICY` | Play a single episode (GUI or headless) |
| `cogames replay PATH`               | Rewatch a saved episode                 |

### Training

```bash
cogames tutorial train -m MISSION -p POLICY_CLASS \
  --steps N --parallel-envs N \
  --device auto --checkpoints DIR
```

Trains agents using PufferLib (PPO). Outputs versioned checkpoints with `policy_spec.json` and weight files.

### Evaluation

| Command                                          | Description                            |
| ------------------------------------------------ | -------------------------------------- |
| `cogames run -m MISSION -p POLICY --episodes N`  | Multi-episode evaluation with stats    |
| `cogames scrimmage -m MISSION -p POLICY`         | Single-policy evaluation               |
| `cogames pickup --policy CANDIDATE --pool P1 P2` | Value Over Replacement (VORP) analysis |

`cogames run` supports repeated `--mission` / `-m` values and wildcard mission patterns.

For a first local run, start with `cogames play`. Use `cogames scrimmage` when you want repeated single-policy
evaluation. Reserve `cogames pickup` for VOR comparisons against a policy pool.

### Leaderboard & Submission

| Command                                      | Description             |
| -------------------------------------------- | ----------------------- |
| `cogames auth login`                         | GitHub OAuth login      |
| `cogames upload --policy POLICY --name NAME` | Upload policy to server |
| `cogames submit POLICY:vN --season SEASON`   | Submit to tournament    |
| `cogames submissions`                        | View submission status  |
| `cogames leaderboard --season SEASON`        | View rankings           |
| `cogames season list`                        | List active seasons     |

### Policy Management

| Command                                         | Description                             |
| ----------------------------------------------- | --------------------------------------- |
| `cogames policies`                                      | List available policy classes/shortcuts |
| `cogames tutorial make-policy --scripted --output PATH` | Generate policy template                |
| `cogames validate-bundle --policy BUNDLE`               | Check bundle viability                  |

### Policy Argument Syntax

```bash
# Checkpoint bundle (versioned)
./train_dir/run:v5
./checkpoints:latest

# Class reference
class=lstm
class=cogames.policy.random.RandomPolicy

# With parameters
class=my_policy.MyPolicy,data=./weights.safetensors,kw.hidden_size=256

# With proportions (multi-policy games)
class=baseline,proportion=0.5

# URI format (role-based)
metta://policy/role?role_cycle=aligner,miner,scrambler,scout
metta://policy/role?miner=4&aligner=2&scrambler=4&scout=0
```

## 4. CogsGuard Game Mechanics

CogsGuard is a **cooperative territory-control game** where teams of AI agents ("Cogs") capture and defend junctions
against automated opponents ("Clips").

### Victory Condition

Score = `junctions_held / max_steps` accumulated per tick. Territory control generates continuous reward.

### Agent Resources

| Resource | Base Value                                | Notes                                                                |
| -------- | ----------------------------------------- | -------------------------------------------------------------------- |
| Energy   | 20 (Scouts: +100)                         | Solar regen +1/turn; friendly territory fully restores               |
| HP       | Standard (Scouts: +400, Scramblers: +200) | Heals in own territory; -1/tick in enemy territory                   |
| Cargo    | 100 (Miners: +40)                         | Holds resources and hearts                                           |
| Hearts   | Capacity: 1                               | Required for junction capture/disruption; assembled from 4 resources |

### Role System

Roles are acquired at Gear Stations by spending team resources. No single role can succeed alone.

| Role          | Bonus                     | Function                                                 | Dependencies                                            |
| ------------- | ------------------------- | -------------------------------------------------------- | ------------------------------------------------------- |
| **Miner**     | +40 cargo, 10x extraction | Gathers resources from extractors                        | Team needs deposits                                     |
| **Aligner**   | +20 influence             | Captures neutral junctions (costs 1 heart + 1 influence) | Needs miners for resources, scramblers to clear enemies |
| **Scrambler** | +200 HP                   | Disrupts enemy junctions (costs 1 heart)                 | Team presence needed                                    |
| **Scout**     | +100 energy, +400 HP      | Mobile reconnaissance                                    | Team needed to hold territory                           |

### Territory & Area-of-Effect

- **Neutral junctions:** No team controls them
- **Aligned junctions:** Your team controls them; projects AOE (~10 cells) providing energy/HP/influence restoration
- **Enemy junctions:** Opposing team controls; -1 HP/tick, influence drained within AOE

### Collective Inventory

Resources are team-shared: all agents deposit at aligned junctions/hubs, all withdraw hearts from collective chests.
This creates interdependence between roles.

### Clips (Automated Opponents)

Clips expand territory automatically, neutralize adjacent enemy junctions, and capture neutral junctions. They create
constant pressure requiring both expansion and defense.

### Heart Assembly

Hearts are created at Hub stations by combining 4 resources: carbon, oxygen, germanium, and silicon. Hearts are consumed
when capturing (Aligner) or disrupting (Scrambler) junctions.

## 5. Training Pipeline

### From Scripted Agents to Trained Policies

1. **Start with scripted baselines** -- Use built-in policies (baseline, thinky, role) to understand the game
2. **Create a custom policy** -- `cogames tutorial make-policy` generates a template (starter heuristic or trainable neural net)
3. **Train with PufferLib** -- `cogames tutorial train` runs PPO with vectorized environments
4. **Evaluate locally** -- `cogames play` / `cogames scrimmage` first; use `cogames pickup` later when you want VORP
5. **Submit to leaderboard** -- Upload and submit for tournament ranking

### Training Configuration

```bash
cogames tutorial train -m arena \
  -p class=cogames.policy.trainable_policy_template.MyTrainablePolicy \
  --steps 100000 --parallel-envs 32 \
  --device auto --checkpoints ./my_training
```

### Checkpoint Structure

```
train_dir/
  run_name/
    v1/
      policy_spec.json    # Class path, data path, init kwargs
      policy_data.pt      # Model weights
    v2/
      ...
```

### Curriculum Training

Recipes in `recipes/prod/cvc/` and `recipes/experiment/` support curriculum learning:

- Start with simple missions (TrainingVariant, PackRatVariant)
- Progress to harder variants (MinedOut, DarkSide, RoughTerrain)
- Mix diagnostic (fixed maps) and integrated (procedural) missions

Recipe execution:

```bash
./tools/run.py recipes.experiment.cogsguard train num_envs=32 learning_rate=5e-4
./tools/run.py recipes.experiment.scripted_agents.play agent=thinky suite=cvc_arena
```

### Available Policies

**Scripted baselines** (from cogames-agents):

- `baseline`, `tiny_baseline`, `ladybug_py` -- Python heuristics
- `thinky`, `race_car`, `ladybug` -- Nim-compiled (faster)
- `role`, `role_nim`, `wombo` -- Role-rotation strategies
- `miner`, `scout`, `aligner`, `scrambler` -- Tutorial role specialists (canonical in `cogames`)
- `teacher` -- Role assignment meta-policy

**Templates** (from cogames):

- `StarterCogPolicy` -- Heuristic behavior tree
- `MyTrainablePolicy` -- Minimal neural net template

## 6. Leaderboard Submission

### Workflow

```bash
# 1. Authenticate
cogames auth login

# 2. Upload your policy (creates versioned bundle)
cogames upload --policy class=my_policy.MyPolicy --name my.policy
# Returns: my.policy:v1

# 3. Submit to a tournament season
cogames submit my.policy:v1 --season beta-cogsguard

# 4. Monitor results
cogames submissions --policy my.policy
cogames leaderboard --season beta-cogsguard
```

### Scoring: VORP (Value Over Replacement Policy)

```
replacement_mean = average score when only pool plays
candidate_score  = average score when candidate plays
VORP = candidate_score - replacement_mean
```

- **Positive VORP** -- Your policy improves the team
- **Negative VORP** -- Your policy hurts the team
- **Zero VORP** -- Matches baseline

### Tournament Structure

- **Seasons** are time-bounded competitive periods
- **Qualifying pool** receives new submissions
- **Competition pool** contains top performers
- Server-side evaluation queues automated matches

## 7. Key Configuration Files and Recipes

### Mission Configuration (Pydantic models, YAML/JSON export)

```yaml
name: mission_name
site: site_config # Map generator + size + agent limits
num_cogs: 10
variants:
  - name: variant_name
    parameters: ...
carbon_extractor:
  efficiency: 100
  max_uses: 25
oxygen_extractor: { efficiency: 100, max_uses: 5 }
cargo_capacity: 100
energy_capacity: 100
energy_regen_amount: 1
move_energy_cost: 2
heart_capacity: 1
```

### Sites

| Site              | Map Size     | Agents       | Purpose                 |
| ----------------- | ------------ | ------------ | ----------------------- |
| TRAINING_FACILITY | 13x13        | 4            | Learning basics         |
| HELLO_WORLD       | 100x100      | 1-20         | Generalization testing  |
| MACHINA_1         | 88x88        | 1-20         | Multi-scenario training |
| COGSGUARD_ARENA   | Configurable | Configurable | Full gameplay           |
| EVALS             | Fixed        | Variable     | Reproducible evaluation |

### Mission Variants

**Resource:** MinedOut, ResourceBottleneck, PackRat, Energized, Training

**Environmental:** DarkSide (no regen), SuperCharged (+2 regen), RoughTerrain (+2 move cost), SolarFlare (-50% junction)

**Mechanic:** SharedRewards, HeartChorus, HubDrawsFromChests

**Evaluation sets:** diagnostic_evals (30+), integrated_evals (7), spanning_evals

### Key Source Files

| File                                                                     | Purpose                     |
| ------------------------------------------------------------------------ | --------------------------- |
| `packages/cogames/src/cogames/main.py`                                   | CLI entry point             |
| `packages/cogames/src/cogames/train.py`                                  | Training pipeline           |
| `packages/cogames/src/cogames/play.py`                                   | Single episode execution    |
| `packages/cogames/src/cogames/evaluate.py`                               | Multi-episode evaluation    |
| `packages/cogames/src/cogames/pickup.py`                                 | VORP calculation            |
| `packages/cogames/src/cogsguard/mission.py`            | Mission/Site/Variant config |
| `packages/cogames/src/cogsguard/missions.py`           | Mission definitions         |
| `packages/cogames/src/cogsguard/variants.py`           | Variant implementations     |
| `packages/cogames/src/cogames/cli/submit.py`                             | Submission/upload handling  |
| `packages/cogames/src/cogames/cli/leaderboard.py`                        | Leaderboard display         |
| `packages/cogames/src/cogames/policy/starter_agent.py`                   | Heuristic baseline          |
| `packages/cogames/src/cogames/policy/trainable_policy_template.py`       | Training template           |
| `cogames-agents/src/cogames_agents/policy/scripted_registry.py` | Policy registry             |
| `packages/cogames/MISSION.md`                                            | Game mechanics briefing     |
| `packages/cogames/TECHNICAL_MANUAL.md`                                   | Observation/action specs    |
