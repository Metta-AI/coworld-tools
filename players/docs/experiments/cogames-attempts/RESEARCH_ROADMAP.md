# CogsGuard Research Roadmap: Breaking the Junction Ceiling

> **NOTE (2026-04-16)**: This document is now **archived**. The active roadmap is [ROADMAP.md](ROADMAP.md).
> The TRUE root cause of 0 junctions (R24) was missing vibe actions, not entropy collapse.
> All 10 research approaches below were designed to solve a misdiagnosed problem.
> See ROADMAP.md R24 section for the actual fix.

## Problem Statement (OUTDATED — see note above)

After 100+ experiments across PPO hyperparameters, Cortex architectures, kickstarting, and entropy
control, the primary bottleneck was believed to be **entropy collapse** — all policies become deterministic after
600-800M steps. However, **R24 (2026-04-16) revealed the TRUE root cause**: policy outputs Discrete(5) = movement only, and without vibe actions, agents cannot mine/craft/align. See [ROADMAP.md](ROADMAP.md) for current status.

## Current Best Results

| Experiment | Config | Peak J | Mean J | Status |
|-----------|--------|--------|--------|--------|
| T3/R20 | sLSTM + KL KS 0.3 + credit + machina_1 | **8.0** | ~2.5 | Best peak (collapsed at ~700M) |
| E4/R21 | sLSTM + ent=0.15 + KL KS + credit | ~3.0 | ~1.5 | **First run to survive 1B steps** |
| S1/R19 | sLSTM + KL KS 0.6 + machina_1 | 7.0 | ~2.0 | Entropy collapsed, recovered late |
| N3/R14 | sLSTM + no_clips + machina_1 (baseline) | 5.0 | 1.77 | Pre-metta-pipeline baseline |
| AIF iter | Active inference iterative pipeline | 34.08 | **10.43** | Best mean (arena, 5 rounds) |

## The 10 Research Approaches

### Approach #1: Dense Chain Rewards (Reward Machines)
**Literature**: Icarte et al., "Reward Machines: Exploiting Reward Function Structure in RL" (JMLR 2022)

**Problem it solves**: The mine→deposit→craft→gear→capture chain is too long for PPO to assign credit. Terminal junction reward is ~1000 steps away from the initial mining action.

**Implementation**: Post-step reward shaping in patch_and_train.py evaluate() hook. Track per-agent observation deltas and reward intermediate steps:
- Heart gained (mining chain complete): +0.5
- Gear crafted: +1.0
- Junction approached: +0.3

**Sweep variants**:
| ID | Scale | Steps | Notes |
|----|-------|-------|-------|
| K1 | 0.5 | 50M | Conservative shaping |
| K2 | 1.0 | 50M | Aggressive shaping |

**How to build**: Monitor observation feature deltas between steps. Requires identifying
heart/gear/junction observation indices from mettagrid token format.

### Approach #2: Temporal Abstraction (TAR² / Dual-Gamma)
**Literature**: Romoff et al., "TDγ: Re-evaluating Complex Backups in Temporal Difference Learning" (NeurIPS 2019); Zhang et al., "TAR²: Temporal Abstraction and Reasoning for RL" (2024)

**Problem it solves**: gamma=0.995 discounts the junction reward at step 1000 to 0.995^1000 ≈ 0.007 — effectively invisible. A dual-gamma system uses fast gamma (0.99) for tactical decisions and slow gamma (0.999) for strategic planning.

**Implementation**: In train() hook after GAE computation. Compute two advantage estimates at different timescales and blend:
```python
adv_fast = compute_gae(rewards, values, gamma=0.99, lambda_=0.90)
adv_slow = compute_gae(rewards, values, gamma=0.999, lambda_=0.95)
advantages = alpha * adv_fast + (1-alpha) * adv_slow
```

**Sweep variants**:
| ID | alpha | gamma_slow | Notes |
|----|-------|------------|-------|
| L1 | 0.5 | 0.999 | Equal weighting |
| L2 | 0.3 | 0.999 | Strategic bias |

### Approach #3: Population Diversity / Ensemble
**Literature**: Parker-Holder et al., "Effective Diversity in Population Based RL" (NeurIPS 2020)

**Problem it solves**: Single-seed PPO converges to one behavioral mode. Multiple seeds explore different strategy spaces.

**Implementation**: Already partially supported. Train 3+ seeds per best config. Combine via heterogeneous team eval:
```bash
cogames run -p best_seed1,proportion=4 -p best_seed2,proportion=4
```

**Sweep**: 3 seeds × best config from Round 11. No code changes needed.

### Approach #4: Role Discovery via Mission Variants (R3DM)
**Literature**: Wang et al., "RODE: Learning Roles to Decompose Multi-Agent Tasks" (ICLR 2021)

**Problem it solves**: Without forced roles, all 8 agents do the same thing (herd behavior).

**Implementation**: Use existing cogames variants:
- `forced_role_vibes` (forces distinct roles per agent)
- `vibes` (makes role signals visible)
- `aligner` / `miner` / `scrambler` (per-role reward shaping)

**Already tested**: I2v2 (forced_roles, 2.0j), J1 (no_clips+forced_roles, 3.0j but collapsed), J2 (no_clips+aligner+forced_roles, 2.778j)
**Remaining**: Proportion tuning (more aligners vs more miners)

### Approach #5: Adaptive Entropy (SAEIR)
**Literature**: Han et al., "SAEIR: Soft Actor-Entropy Intrinsic Reward" (2023)

**Problem it solves**: Fixed ent_coef either collapses (too low) or prevents convergence (too high). Adaptive entropy increases exploration when policy becomes deterministic.

**Implementation**: In train() hook, adjust ent_coef based on current policy entropy:
```python
current_entropy = policy_entropy.mean().item()
max_entropy = log(num_actions)  # log(5) ≈ 1.609
target_ratio = 0.5
if current_entropy / max_entropy < target_ratio:
    ent_coef *= 1.05  # ramp up
else:
    ent_coef *= 0.995  # gentle decay
ent_coef = clamp(ent_coef, 0.01, 0.15)
```

**Sweep variants**:
| ID | Target ratio | Ramp rate | Notes |
|----|-------------|-----------|-------|
| K4 | 0.5 | 1.05/0.995 | Moderate |

### Approach #6: Advantage Decomposition (PRD-MAPPO)
**Literature**: Lyu et al., "PRD-MAPPO: Partially Decoupled Value Decomposition" (2023)

**Problem it solves**: Shared reward means individual contributions are invisible. Decomposing advantages into individual + team components provides clearer credit assignment.

**Implementation**: In train() hook after GAE:
```python
# advantages shape: (num_envs * num_agents * steps_per_rollout,)
adv_reshaped = advantages.reshape(num_envs, num_agents, -1)
team_mean = adv_reshaped.mean(dim=1, keepdim=True)
individual = adv_reshaped - alpha * team_mean
advantages = individual.reshape(-1)
```

**Sweep variants**:
| ID | alpha | Notes |
|----|-------|-------|
| L2 | 0.5 | Equal individual/team |
| L3 | 0.3 | Mostly individual |

### Approach #7: Curriculum / Environment Simplification (PORTAL)
**Literature**: Portelas et al., "Teacher algorithms for curriculum learning" (2020)

**Problem it solves**: Full arena (88x88 with enemies) is too hard for initial learning. Simpler environments let agents discover the economy chain.

**Implementation**: Use existing mission variants as curriculum stages:
- Stage 1: `no_clips` (no enemies — most effective single variant)
- Stage 2: `no_clips + role_reward` (add role-specific reward shaping)
- Stage 3: Full `arena` (finetune from Stage 2 checkpoint)

**Already tested**: no_clips (2.5j), no_clips+aligner (4.0j), braveheart (untested)
**Remaining**: Sequential curriculum (train on no_clips → finetune on arena), braveheart variant, small_50

**Sweep variants**:
| ID | Config | Notes |
|----|--------|-------|
| L4 | braveheart + aligner | Remove survival pressure |

### Approach #8: Curiosity / Intrinsic Motivation (CERMIC)
**Literature**: Pathak et al., "Curiosity-driven Exploration by Self-Supervised Prediction" (ICML 2017)

**Problem it solves**: PPO explores via entropy alone, which is random. Count-based curiosity rewards novel observations, driving directed exploration of the economy chain.

**Implementation**: In evaluate() hook, hash key observation features and provide count-based bonus:
```python
# Track visit counts for (position, inventory_state) tuples
key = (agent_x, agent_y, has_gear, has_heart)
visit_count[key] = visit_count.get(key, 0) + 1
intrinsic_reward = beta / sqrt(visit_count[key])
rewards[agent_id] += intrinsic_reward
```

**Sweep variants**:
| ID | beta | Features | Notes |
|----|------|----------|-------|
| K3 | 0.1 | pos+inv | Moderate curiosity |

### Approach #9: Role-Oriented Decomposition (RODE+MASL)
**Literature**: Wang et al., "RODE: Learning Roles to Decompose Multi-Agent Tasks" (ICLR 2021)

**Problem it solves**: Agents need to specialize into roles without hand-coding. RODE learns role embeddings that decompose the action space.

**Implementation**: Requires policy modification — add auxiliary role prediction head:
```python
class RoleAugmentedPolicy(CortexSLSTMPolicy):
    def __init__(self):
        super().__init__()
        self.role_head = nn.Linear(d_hidden, num_roles)

    def forward(self, obs, state):
        hidden, state = super().forward(obs, state)
        role_logits = self.role_head(hidden)
        # Aux loss: predict visible vibe token from hidden state
        return hidden, state, role_logits
```
**Deferred**: Requires more infrastructure than a sweep script. Implement if simpler approaches (#4) don't work.

### Approach #10: Co-evolution (CCL)
**Literature**: Jaderberg et al., "Population Based Training of Neural Networks" (2017)

**Problem it solves**: Single training run converges to local optima. Population-based training with selection and mutation explores the strategy landscape.

**Implementation**: PBT-lite orchestration script:
1. Train 4 policies for 10M steps
2. Evaluate each in 3 episodes
3. Clone best → mutate worst (perturb hyperparams ±20%)
4. Repeat for 5 generations

**Sweep**: 1 experiment (O4), uses all 4 GPUs sequentially over 5 generations.

---

## Cortex Architecture Exploration

### Design Space

| Cell | Token | Tested | Best Result | Memory | Hypothesis |
|------|-------|--------|-------------|--------|-----------|
| LSTM | L | Yes | 3.75j (0.18) | O(d) | Baseline gated recurrence |
| sLSTM | S | Yes | 5.0j (noise) | O(d) | Stabilized gating, exp gates |
| Axon | A | Yes | 2.25j | O(d^2) RTRL | Linear SSM + RTRL |
| AGaLiTe | Ag | Yes (combo) | 2.56j | O(d) | Attention-based memory |
| mLSTM | M | Yes | 2.0j | O(d^2) | Multiplicative gating |
| XL | X | Yes | 1.5j | O(d) | Extended recurrence |
| CausalConv1d | C | Yes | 1.5j | O(k*d) | Local temporal patterns |
| sLSTM^ | S^ | Yes | 2.0j | O(3.5d^2) | sLSTM + RTRL (buggy init) |
| mLSTM^ | M^ | Crashed | -- | O(38K) | Impractical memory |

### What We Know
1. **sLSTM dominates** when it works (5.0j peak, but unreproducible -- median ~1.0j)
2. **LSTM is most reliable** (consistent 2-3j, small variance)
3. **Combinations don't help** (L+S, Ag+S all ~ single cell performance)
4. **Router is dead** at this training budget (Wq=Wk=0 in S15)
5. **d_hidden=128 is optimal** (d=64 hurts everything)
6. **Architecture matters less than environment/reward** (I3v2's 4.0j used native LSTM!)

### Remaining Questions
1. Does sLSTM + best environment (no_clips+aligner) break 5j reliably?
2. Can we reproduce B1's 5.0j with more seeds?
3. Does sLSTM benefit more from reward shaping than LSTM?

### Plan
Test sLSTM on best environment config (no_clips+aligner) in Round 13 (M1). If it beats LSTM there, do focused sLSTM tuning in Round 14. Otherwise, architecture is solved (LSTM is fine) and effort goes to reward/curriculum.

### Approach #11: Separate Actor/Critic Networks (Subhojeet suggestion, 2026-03-31)
**Literature**: Andrychowicz et al., "What Matters in On-Policy RL" (2021); Cobbe et al., "PPG: Phasic Policy Gradient" (ICML 2021)

**Problem it solves**: Shared backbone means critic convergence can degrade actor representations. When vf_coef is high (our 2.0 → advantage collapse), the critic's loss dominates gradient updates and distorts features the actor needs for policy improvement. SepLR (critic_lr_ratio=0.2) mitigates this but still shares representations.

**Implementation**: New policy class `SeparateACLSTMPolicy` with two independent LSTM backbones:
```python
class SeparateACLSTMPolicy(nn.Module):
    # Actor: encoder_a → lstm_a → action_head (logits)
    # Critic: encoder_c → lstm_c → value_head (scalar)
    # No shared parameters. Double recurrent state (512 vs 256).
    # State packing: lstm_h = [actor_h; critic_h] concatenated along hidden dim
```

**Trade-offs**:
- (+) Critic can't corrupt actor representations
- (+) Each network specializes (actor for action discrimination, critic for value prediction)
- (-) Doubles parameter count and recurrent state (512 vs 256 per agent)
- (-) Actor loses "free" representation learning from critic's value signal
- (-) PufferLib integration: must pack two LSTM states into one buffer

**Sweep**: L3b in Round 12 (replaces PRD alpha=0.3)

### Approach #12: Target Networks for Value Stabilization (Subhojeet suggestion, 2026-03-31)
**Literature**: Mnih et al., "Human-level control through deep RL" (Nature 2015); Lillicrap et al., "DDPG" (ICLR 2016)

**Problem it solves**: In PPO, the value function is used both to compute GAE targets (during rollout) and trained against those targets (during optimization). If the critic changes rapidly between rollout and training, the advantage estimates become stale. Target networks provide stable value targets by maintaining a slowly-updated copy of the critic.

**Implementation**: Training loop patch in `patch_and_train.py`:
```python
# Initialize: target_critic = deepcopy(critic)
# GAE computation: use target_critic values instead of online critic
# After each training epoch:
#   for p_t, p_o in zip(target_critic.params(), critic.params()):
#       p_t.data.mul_(1 - tau).add_(tau * p_o.data)
# tau = 0.005 (standard polyak averaging)
```

**Trade-offs**:
- (+) Stabilizes advantage estimates across training epochs
- (+) Prevents value oscillation from destabilizing policy updates
- (-) Adds memory overhead (full critic copy)
- (-) Slows critic adaptation (by design — may hurt in non-stationary multi-agent setting)
- (-) PPO's clipping already provides some stabilization — may be redundant

**Note**: Unusual for PPO (standard in off-policy methods like DQN/SAC). Worth testing because our vf_coef=2.0 collapse showed the critic IS a source of instability, even after SepLR fix.

**Sweep**: L4b in Round 12 (replaces braveheart+aligner)

---

## Sweep Schedule

All experiments use H4 base: `vf_coef=0.5, ent_coef=0.03, SepLR (critic_lr_ratio=0.2), ReDo`

### Round 11: Reward Shaping (4 GPUs, ~25 min)
Build on I3v2's success (no_clips + aligner = 4.0j).

| GPU | ID | Config | Approach |
|-----|----|--------|----------|
| 0 | K1 | no_clips + aligner + chain rewards (scale=0.5) | #1 Dense chain |
| 1 | K2 | no_clips + aligner + chain rewards (scale=1.0) | #1 Dense chain |
| 2 | K3 | no_clips + aligner + curiosity (beta=0.1) | #8 Curiosity |
| 3 | K4 | no_clips + aligner + adaptive entropy (target=0.5) | #5 SAEIR |

### Round 12: Advantage + Architecture (4 GPUs, ~25 min)
| GPU | ID | Config | Approach |
|-----|----|--------|----------|
| 0 | L1 | no_clips + aligner + dual-gamma (alpha=0.5) | #2 TAR^2 |
| 1 | L2 | no_clips + aligner + PRD (alpha=0.5) | #6 Advantage decomp |
| 2 | L3b | no_clips + aligner + **separate actor/critic** | #11 Sep AC (Subho) |
| 3 | L4b | no_clips + aligner + **target network (τ=0.005)** | #12 Target net (Subho) |

### Round 13: Bug-Fix Rerun (4 GPUs, ~25 min) — COMPLETE (2026-04-01)

R11 K1-K3 were bugged (PufferLib 3.0 attr names). Rerun with fixes applied.

| GPU | ID | Config | Peak J | Mean J | Clipfrac | Approach |
|-----|----|--------|--------|--------|----------|----------|
| 0 | M1 | chain_rewards scale=0.5 | 3.0 | ~1.64 | 0.043 | #1 Dense chain |
| 1 | M2 | curiosity beta=0.1 | 2.667 | ~1.81 | 0.053 | #8 Curiosity |
| 2 | M3 | dual-gamma α=0.5 | 3.0 | ~1.70 | 0.114 | #2 TAR² |
| 3 | M4 | target-net τ=0.005 | 3.0 | ~1.62 | 0.091 | #12 Target net |

**Verdict**: All techniques produce baseline-level results (~1.5-2.0 mean junctions). Healthy clipfrac confirms bug fixes worked. No technique significantly improves junction count at 50M steps.

### Round 14-15: **DELAYED** — Pending Extended Training

R14-R15 postponed. PPO improvement approaches exhausted at 50M steps. PI feedback (2026-04-01): Softmax trains for **billions** of steps internally. Our 50M is 100-200x shorter. The ~1.5-2.0 mean junction ceiling may be a compute budget issue, not an architectural or algorithmic one.

**R14-R15 may still be valid at higher step counts.** Approaches like dual-gamma (L1/M3) and target-net (L4b/M4) could compound over longer training. Revisit after extended training (500M+ steps) on machina_1 validates whether the ceiling persists at scale.

Original R14-R15 plans preserved for reference:
| Round | GPU | ID | Config | Notes |
|-------|-----|----|--------|-------|
| R14 | 0 | N1 | Best approach + sLSTM | Architecture x reward |
| R14 | 1 | N2 | Best approach + LSTM | Control |
| R14 | 2 | N3 | 2nd best approach + sLSTM | Alternative |
| R14 | 3 | N4 | Top 2 approaches combined | Stacking test |
| R15 | 0 | O1 | Best overall, 100M steps | Does longer training help? |
| R15 | 1 | O2 | Best overall, d_hidden=256 | Does capacity help? |
| R15 | 2 | O3 | Sequential curriculum: no_clips -> arena | Finetune transfer |
| R15 | 3 | O4 | PBT-lite (4 policies x 5 gen) | #10 Co-evolution |

---

## Infrastructure Changes

### patch_and_train.py modifications (AWS)
All hooks are **implemented** (~950 lines). Key env vars:
- `SWEEP_PRESET=metta_optimal` — Metta's sweep-tuned hyperparams (lr=0.00738, gamma=0.9986, etc.)
- `SWEEP_OVERRIDES='{"ent_coef": 0.15}'` — Override any PufferLib train_arg
- `SWEEP_FIXES='sep_lr,redo'` — Optimization fixes
- `KICKSTART_MODE=kl` — KL kickstarting from scripted teacher
- `KS_COEF=0.3` / `KS_ANNEAL_START=0.3` / `KS_ANNEAL_END=0.6` — Kickstarting schedule
- `ENTROPY_MODE=adaptive|cosine` — Entropy collapse prevention
- `ENT_COEF_MAX` / `ENT_COEF_MIN` / `ENTROPY_FLOOR` / `ENTROPY_CEIL` — Entropy bounds
- `REWARD_MODE=chain_rewards|curiosity|none` — Evaluate() reward hooks
- `ADVANTAGE_MODE=standard|dual_gamma|prd` — Advantage manipulation

Reward variant monkey-patch: Patches `parse_variants()` and `train()` to wire `credit`, `milestones`, `role_conditional` into the training pipeline (not natively supported in cogames 0.22 CLI).

### cortex_policy.py (AWS)
- `CortexSLSTMPolicy` — sLSTM preset (d=128), default for all R17+ experiments

### Sweep scripts (AWS)
`round17_hparams.sh` through `launch_r22.sh`:
- 4 parallel GPU processes per round
- metta_optimal preset + sep_lr,redo fixes
- KL kickstarting with configurable coef/annealing
- Entropy collapse prevention (R21+)
- Results extraction and diagnostic checks at end

---

## Corrections

### Hyperparameter History
The EXPERIMENT_LOG.md section at lines 2206-2368 claimed hyperparams changed between 0.18 and 0.19.
**This is WRONG.** Git archaeology confirmed: vf_coef=2.0, gamma=0.995, gae_lambda=0.90,
bptt_horizon=64, max_grad_norm=1.5 have been the SAME since the first cogames training commit
(Sept 2025). Only ent_coef changed: 0.001 -> 0.01 (increased, not decreased).

What we called "0.18 hyperparams" were actually PufferLib/CleanRL defaults that we assumed were
the old cogames values. Subhojeet confirmed via git blame.

---

## Total Compute
- 5 rounds x 25 min = ~2 hours
- Plus conditional rounds if needed
- Can complete in one AWS session

## Post-Sweep Direction (Updated 2026-04-08)

R1-R16 exhausted PPO at 50M steps. R17-R22 adopted metta's pipeline (8x higher LR, weight_decay, bptt=256, KL kickstarting, credit rewards) and scaled to 1-2B steps. **Entropy collapse** emerged as the dominant failure mode at scale.

### Current Priorities

| Priority | Task | Status |
|----------|------|--------|
| ~~P1~~ | ~~Upgrade cogames to 0.22~~ | ✅ Done (0.22.2) |
| ~~P2~~ | ~~Adopt metta hyperparams~~ | ✅ Done (SWEEP_PRESET=metta_optimal) |
| ~~P3~~ | ~~KL kickstarting~~ | ✅ Done (coef=0.3, anneal 30-60%) |
| ~~P4~~ | ~~Entropy collapse prevention~~ | ✅ Done (ent=0.15 survives, adaptive controller fixed) |
| **P5** | Scale to 2B+ steps | R22 RUNNING (4 experiments, ~20 hrs) |
| **P6** | Architecture exploration | TutorialPolicyNet (CNN+LSTM d=512) after entropy solved |
| **P7** | AIF on CLIPs variant | Subhojeet suggestion — after PPO baseline established |

### Key Insights (R17-R22)

1. **Metta defaults are 8x better than cogames defaults**: LR, weight_decay, batch size, bptt all wrong in cogames train.
2. **KL kickstarting works, EER doesn't**: KL preserves value function; EER corrupts it via reward shaping.
3. **Entropy collapse is the #1 problem at scale**: All policies collapse to deterministic at 600-800M steps. ent_coef=0.15 (6x metta default) prevents collapse.
4. **Reward variants require monkey-patching**: cogames 0.22 has credit/milestones/role_conditional but they're not wired into the CLI.
5. **Warm-starting is counterproductive**: Fresh training with KL KS outperforms warm-started checkpoints.
6. **PufferLib 3.0 stores entropy in `trainer.losses`**, not `trainer.stats` — critical for adaptive controllers.

## Success Criteria
- ~~**Minimum**: Break 5.0j on machina_1~~ ✅ Done (8.0j, T3/R20)
- **Target**: Sustain >10j mean over 2B+ steps without entropy collapse
- **Stretch**: Approach 30j+ (scripted agent territory) with learned policy
