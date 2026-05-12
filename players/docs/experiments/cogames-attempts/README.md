# CogsGuard: Active Inference for Multi-Agent Coordination

Research project exploring active inference, Cortex architectures, and PPO optimization for the [Alignment League](https://softmax.com/alignmentleague) CogsGuard benchmark. Part of a Softmax contract (80 hrs) with Subhojeet, plus a research collaboration with Luca Manneschi and Alejandro on meta-learning world models.

**Goal**: Build a learned agent that scores >6 junctions on the CogsGuard leaderboard (no learned agent has achieved this). Stretch: approach the scripted dinky baseline (21.09).

**Best results**: PPO track: cinky teacher converged at **8,639 j/held** (training) / **6,926 j/held** (eval, 10k-step arena). PazBot-v47 vibe teacher active at **1,218 j/held** (epoch 29, growing ~72/epoch). AIF iterative pipeline = **10.43 j/agent mean** (5 rounds, arena, peak 34.08). Training fully migrated into metta internal recipe pipeline (PR #11757).

---

## Documentation

| Document | Description |
|----------|-------------|
| [ROADMAP.md](ROADMAP.md) | Current status, phase tracker, PI meeting notes, R17-R24 details, active workstreams |
| [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md) | Complete record of 100+ experiments with metrics and findings (Rounds 1-24) |
| [AIF_DESIGN.md](AIF_DESIGN.md) | Full AIF architecture: 288-state POMDP, VFE/EFE math, G-coupling, ToM |
| [LITERATURE.md](LITERATURE.md) | Papers on MARL methods and recurrent architectures for RL |

**Archived** (historical, superseded by above):
| [RESEARCH_ROADMAP.md](RESEARCH_ROADMAP.md) | 10 research approaches, sweep schedule (R11-R15). Superseded by ROADMAP Phase 4. |
| [RESEARCH_PROPOSAL.md](RESEARCH_PROPOSAL.md) | Five-step pipeline sent to PI (2026-03). AIF sections superseded by AIF_DESIGN.md. |

---

## Quick Start

### AWS Setup

```bash
# SSH into the sandbox (4x L4 GPUs, 181GB RAM, 512GB disk)
ssh -i "mahault_key_pair.pem" ec2-user@ec2-52-91-78-2.compute-1.amazonaws.com

# Activate environment
source ~/projects/cogames-env/bin/activate

# Repos:
#   ~/projects/cogames/          (game environment)
#   ~/projects/cogames-agents/   (policies + sweep scripts)
```

### Authentication

```bash
# Set auth token (from local cogames login)
cogames auth set-token 'YOUR_TOKEN_HERE'
# Token stored at ~/.metta/cogames.yaml
cogames auth status
```

### Key Commands

```bash
# Evaluate a policy
cogames eval -m arena -p starter --cogs 8
cogames eval -m arena -v no_clips -p class=cortex_policy.CortexSLSTMPolicy -c 8 -e 3

# Train (native pipeline — ALWAYS use this, not custom scripts)
cogames train -m arena -p class=cortex_policy.CortexSLSTMPolicy --cogs 8 --steps 50000000 --device auto

# Train with hyperparameter overrides (via monkey-patching)
PYTHONPATH=scripts/policy \
SWEEP_OVERRIDES='{"vf_coef": 0.5, "ent_coef": 0.03}' \
SWEEP_FIXES='sep_lr,redo' \
CRITIC_LR_RATIO=0.2 \
python3 scripts/sweep/patch_and_train.py train -m arena -v no_clips -v aligner \
  -p 'class=cortex_policy.CortexSLSTMPolicy' --cogs 8 --steps 50000000 --device auto

# Run a sweep round (4 GPUs in parallel)
bash scripts/sweep/round11.sh

# Submit to leaderboard (requires cogames >= 0.22 for season beta-cvc)
cogames ship -p <dir> --skip-validation
# or: cogames upload -p <policy> -n "mahault.name" --season beta-cvc
# NOTE: PYTHONPATH must include policy dir for class imports in ship bundle

# AIF agent eval
cogames eval -m arena -v no_clips \
  -p class=aif_meta_cogames.aif_agent.cogames_policy.AIFPolicy \
  -c 4 -e 3 --action-timeout-ms 1000
```

### Mission Names (cogames 0.19+)

| Short name | Full name | Map | Notes |
|------------|-----------|-----|-------|
| `arena` | `cogsguard_arena.basic` | 50x50 | Training map, ~59 junctions |
| `machina_1` | `cogsguard_machina_1.basic` | 88x88 | Tournament standard, 141 junctions, 10K steps |
| `tutorial` | `cogsguard_tutorial.basic` | 35x35 | Fast validation, no clips |
| `easy_hearts_training` | -- | 13x13 | Hearts + energy only, minimal map |

**Note**: `machina_1` is the tournament map used for leaderboard ranking. All future training experiments should use `machina_1` (not `arena`) for relevance to submissions.

**Variants** (add with `-v`): `no_clips` (no enemies), `aligner`/`miner`/`scrambler` (role rewards), `forced_role_vibes` (force roles), `braveheart` (max hearts), `credit` (dense economy rewards)

### Observation Format

Tokens: `(num_agents, num_tokens, 3)` — each token is `[location, feature_id, value]`
- **location**: packed `(row << 4 | col)` in 13x13 egocentric grid. Center = `0x66`. `0xFF` = empty, `0xFE` = global
- **feature_id**: maps to named features via `IdMap` (e.g., `inv:carbon`, `tag`, `vibe`, `agent:group`)
- **value**: uint8 feature value

### Action Space

**Primary actions** (Discrete(5)): `noop(0)`, `move_north(1)`, `move_south(2)`, `move_west(3)`, `move_east(4)`. Moving onto a tile triggers interaction automatically (deposit, extract, align, craft).

**Transport actions** (Discrete(40)): Combines movement + vibe (role) change in a single action.
- Actions 0-4: primary only, no vibe change (`vibe_actions.fill(0)` → default vibe)
- Actions 5-39: `offset = action - 5; primary = offset // 7; vibe = offset % 7`
- Encode: `transport = 5 + primary * 7 + vibe_idx`
- Vibes (machina_1/arena/tutorial): `[default(0), heart(1), gear(2), scrambler(3), aligner(4), miner(5), scout(6)]`

**CRITICAL**: Without vibe actions, agents stay on "default" vibe and CANNOT mine, craft, or align. Use `VIBE_ROLES` (fixed assignment) or `VIBE_ACTIONS=1` (learnable) — see `patch_and_train.py`.

---

## Policy Interface

**Scripted** (`StatefulPolicyImpl`):
```python
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl

class MyImpl(StatefulPolicyImpl[MyState]):
    def initial_agent_state(self) -> MyState:
        return MyState()
    def step_with_state(self, obs, state) -> tuple[Action, MyState]:
        return Action(name="move_north"), state

class MyPolicy(MultiAgentPolicy):
    def agent_policy(self, agent_id):
        return StatefulAgentPolicy(MyImpl(...), self._policy_env_info, agent_id=agent_id)
```

**Trainable** (`nn.Module`): Must implement `forward_eval(x, state) -> (logits, values)`. See `scripts/policy/cortex_policy.py` for example.

---

## Sweep Infrastructure

The `scripts/sweep/` directory contains:
- **`patch_and_train.py`** — Monkey-patches cogames/PufferLib to override hyperparams, inject training fixes, kickstarting, entropy control, and reward variant wiring (~950 lines)
- **`apply_kickstart_patches.py`** — Source-patches `pufferl.py` for KL kickstarting CE loss and teacher-led rollouts
- **`apply_tier1_patches.py`** — Source-patches `pufferl.py` for PFO loss and asymmetric clipping
- **`round17_hparams.sh` through `launch_r22.sh`** — Sweep scripts running 4 parallel GPU experiments each
- **`plot_training.py`** — Multi-panel matplotlib training graphs from log files

Key env vars for `patch_and_train.py`:
- `SWEEP_PRESET=metta_optimal` — Apply metta's sweep-tuned hyperparameters (lr=0.00738, gamma=0.9986, etc.)
- `SWEEP_OVERRIDES='{"ent_coef": 0.15}'` — Override PufferLib train_args (wins over preset)
- `SWEEP_FIXES='sep_lr,redo'` — Enable optimization fixes
- `KICKSTART_MODE=kl` — KL divergence kickstarting from scripted teacher
- `KS_COEF=0.3` / `KS_ANNEAL_START=0.3` / `KS_ANNEAL_END=0.6` — Kickstarting schedule
- `ENTROPY_MODE=adaptive|cosine` — Entropy collapse prevention (adaptive floor/ceiling or cosine schedule)
- `ENT_COEF_MAX=0.15` / `ENT_COEF_MIN=0.05` — Entropy coefficient bounds
- `ENTROPY_FLOOR=0.3` / `ENTROPY_CEIL=0.8` — Adaptive entropy thresholds
- `REWARD_MODE=chain_rewards|curiosity` — Reward shaping hooks
- `ADVANTAGE_MODE=dual_gamma|prd` — Advantage manipulation

**Note**: Reward variants (`credit`, `milestones`, `role_conditional`) are NOT wired into the cogames 0.22 CLI. `patch_and_train.py` patches `parse_variants()` and `train()` to enable them via `-v credit -v milestones` syntax.

---

## Reward Shaping Variants

Built-in stackable variants from `reward_variants.py`:

| Variant | Effect |
|---------|--------|
| `credit` | Dense rewards for economy chain steps (hearts, elements, gear) |
| `milestones` | Bonus for alignment/scrambling actions |
| `objective_mine:<N>` | Scale junction reward by N + role shaping |
| `miner` / `aligner` / `scrambler` / `scout` | Single-role focused shaping |
| `forced_role_vibes` | Force distinct roles per agent |
| `no_clips` | Remove enemy pressure |
| `braveheart` | Max hearts (remove survival pressure) |

Stack: `cogames train ... -v no_clips -v aligner -v credit`

---

## Known Issues

- **Submission Version Mismatch (RESOLVED)**: Upgraded to cogames 0.22.2. Obs space changed 600→900 — **all old checkpoints are incompatible**. Must retrain. PufferLib renamed to `pufferlib-core` 3.0.21 but same import path. Tier 1 patches survived. Training pipeline verified working.
- **mettagrid has no Windows wheel** — must use AWS or Docker
- **`cogames train` drops `kw.*` init_kwargs** — use dedicated policy classes (e.g., `CortexSLSTMPolicy`) with preset baked in
- **vf_coef=2.0 causes advantage collapse** — fix: use `SWEEP_PRESET=metta_optimal` (sets vf=1.465 with weight_decay=0.3)
- **Entropy collapse at 600-800M steps** — ent_coef=0.0257 (metta default) is too low for 1B+ training. Use ent_coef=0.15 or `ENTROPY_MODE=adaptive` with floor=0.3
- **Reward variants not in CLI** — `parse_variants()` rejects credit/milestones/role_conditional. Fixed by monkey-patch in `patch_and_train.py`
- **Cortex `post_norm=True` kills gradients** — always use `post_norm=False`

### PufferLib CUDA Kernel Fix

PufferLib 3.0.17 ships CUDA source but doesn't compile it. Fix:

```bash
pip install ninja
python3 -c "
from torch.utils.cpp_extension import load
import os
cuda_dir = '/home/ec2-user/projects/cogames-env/lib64/python3.12/site-packages/pufferlib/extensions/cuda'
load(name='pufferlib_cuda_advantage', sources=[os.path.join(cuda_dir, 'advantage.cu')], verbose=True)
"
# Copy compiled .so to PufferLib extensions dir
cp ~/.cache/torch_extensions/py312_cu128/pufferlib_cuda_advantage/pufferlib_cuda_advantage.so \
   /home/ec2-user/projects/cogames-env/lib64/python3.12/site-packages/pufferlib/extensions/cuda/
```

Then patch `pufferl.py` line 76 to load via `torch.ops.load_library()` instead of checking for `nvcc`.
