# Wandb Analysis: High heart.created Runs and Cogsguard Training Plan

> **Date:** 2026-01-24 **Author:** Polecat brotherhood (automated analysis) **Issue:** mt-wandb-runs

## Executive Summary

Analyzed recent wandb runs (last 2 weeks) with prefix "relh" from `metta-research/metta` project. Found 11 runs, with
the top performers using the `machina1_cloner` recipe with `sliced_scripted_cloner` loss and a then-current `dinky`
supervisor policy.

**Key Finding:** The successful runs use behavioral cloning from a scripted teacher (`dinky`) combined with PPO,
achieving heart.gained scores of 10-14.

**Important:** The historical `dinky:v15` pin is stale. For current runs, use
`recipes.experiment.machina_1.train(use_default_teacher=True)` so the recipe resolves the highest-ranked `dinky` on the
current `beta-cvc` leaderboard.

**Recommendation for Cogsguard:** Use `metta://policy/cogsguard?gear=10` (smart-gear meta role) as teacher with
`sliced_cloner` mode.

---

## Top Performing Runs (Last 2 Weeks)

| Run Name                                     | heart.gained | State    | Created    | Recipe          |
| -------------------------------------------- | ------------ | -------- | ---------- | --------------- |
| relh.machina1_cloner.115.2                   | **14.02**    | running  | 2026-01-16 | machina1_cloner |
| relh.machina1_cloner.114.35.big_teacherbc.v2 | **13.52**    | crashed  | 2026-01-16 | machina1_cloner |
| relh.machina1_cloner.114.5.big3_teacherbc    | **13.46**    | finished | 2026-01-14 | machina1_cloner |
| relh.machina1_cloner.114.5.big3_teacherbc.v2 | **12.08**    | finished | 2026-01-16 | machina1_cloner |
| relh.machina1_cloner.114.35.big_teacherbc    | **11.84**    | finished | 2026-01-14 | machina1_cloner |
| relh.machina1_cloner.121.teacherbc.1         | **10.62**    | running  | 2026-01-22 | machina1_cloner |

### Wandb URLs

- Top run: https://wandb.ai/metta-research/metta/runs/relh.machina1_cloner.115.2
- Best finished: https://wandb.ai/metta-research/metta/runs/relh.machina1_cloner.114.5.big3_teacherbc

---

## Analysis of Successful Configs

### Common Configuration Pattern

All top runs share these characteristics:

1. **Loss Configuration:**
   - `ppo_actor`: enabled (clip_coef=0.22, ent_coef=0.01, norm_adv=true)
   - `ppo_critic`: enabled (vf_coef=0.50, critic_update="gtd_lambda")
   - `sliced_scripted_cloner`: enabled (action_loss_coef=1)

2. **Teacher/BC Settings:**
   - `supervisor_policy_uri`: historical runs used a pinned `dinky` teacher; current defaults should resolve the top
     `dinky` from the `beta-cvc` leaderboard instead of pinning an old version
   - `teacher_led_proportion`: 0.5 (best run)
   - `student_led_proportion`: 0.5 (best run)

3. **Training Parameters:**
   - `total_timesteps`: 20B (20,001,317,888)
   - `batch_size`: 2,097,152 (2M)

4. **Architecture:**
   - ViT with perceiver latent and cortex
   - Policy auto-builder components: obs_shim_tokens, obs_attr_embed_fourier, obs_perceiver_latent, cortex, actor_mlp,
     critic, gtd_aux, actor_head

### What Made Them Successful

1. **Behavioral Cloning + PPO hybrid:** The `sliced_scripted_cloner` loss clones actions from a scripted teacher while
   PPO optimizes for rewards
2. **Teacher/student balance:** 50/50 split between teacher-led and student-led experience
3. **Large batch sizes:** 2M batch enables stable learning
4. **Long training:** 20B timesteps allows thorough exploration

---

## Teacher Options for Cogsguard

| Teacher               | URI                                | Pros                                                            | Cons                            | Recommendation  |
| --------------------- | ---------------------------------- | --------------------------------------------------------------- | ------------------------------- | --------------- |
| **smart-gear (meta)** | `metta://policy/cogsguard?gear=10` | Selects optimal role per agent, handles all Cogsguard behaviors | Complex, may be harder to clone | **RECOMMENDED** |
| cogsguard             | `metta://policy/cogsguard`         | Full multi-role scripted agent                                  | Fixed role distribution         | Good baseline   |
| teacher               | `metta://policy/teacher`           | Wrapper that forces initial vibe                                | Less complete behavior          | Alternative     |
| miner                 | `metta://policy/miner`             | Simple, focused behavior                                        | Single role only                | For curriculum  |
| scout                 | `metta://policy/scout`             | Exploration focus                                               | Limited utility collection      | For curriculum  |
| aligner               | `metta://policy/aligner`           | Junction alignment specialist                                   | Single task focus               | For curriculum  |
| scrambler             | `metta://policy/scrambler`         | Anti-clips behavior                                             | Adversarial                     | For curriculum  |

**Recommendation:** Start with `metta://policy/cogsguard?gear=10` (smart-gear meta role) as it provides intelligent role
selection similar to how dinky worked for machina1.

---

## Ready-to-Run Training Commands

### Option 1: Cogsguard BC with Smart-Gear Teacher (Recommended)

```bash
# SSH to mettabox
ssh metta@metta0

# Run cogsguard training with smart-gear teacher
cd ~/metta
./tools/run.py recipes.experiment.cogsguard.train \
    run=relh-cogsguard-bc-001 \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/cogsguard?gear=10", teacher_led_proportion: 0.5, student_led_proportion: 0.5}' \
    trainer.total_timesteps=5_000_000_000 \
    trainer.batch_size=2097152
```

### Option 2: Cogsguard BC with Standard Teacher

```bash
ssh metta@metta0
cd ~/metta
./tools/run.py recipes.experiment.cogsguard.train \
    run=relh-cogsguard-bc-002 \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/teacher", teacher_led_proportion: 0.5}' \
    trainer.total_timesteps=5_000_000_000
```

### Option 3: Pure PPO (No BC)

```bash
ssh metta@metta0
cd ~/metta
./tools/run.py recipes.experiment.cogsguard.train \
    run=relh-cogsguard-ppo-001 \
    trainer.total_timesteps=10_000_000_000
```

### Option 4: Curriculum with Role-Specific Teachers

```bash
# Start with miner role
ssh metta@metta0
cd ~/metta
./tools/run.py recipes.experiment.cogsguard.train \
    run=relh-cogsguard-miner-001 \
    'teacher={mode: sliced_cloner, policy_uri: "metta://policy/miner", teacher_led_proportion: 0.7}' \
    trainer.total_timesteps=2_000_000_000
```

---

## Key Metrics to Monitor

| Metric                                      | Description                 | Target           |
| ------------------------------------------- | --------------------------- | ---------------- |
| `env_agent/heart.gained`                    | Hearts collected by agents  | Higher is better |
| `env_collective/cogs/aligned.junction.held` | Junction alignment progress | Higher is better |
| `overview/reward`                           | Episode reward              | Increasing trend |
| `losses/approx_kl`                          | KL divergence (stability)   | < 0.03           |

---

## Next Steps

1. **Launch initial run** with smart-gear teacher (Option 1)
2. **Monitor metrics** on wandb for first 1B steps
3. **Compare** with machina1 baseline performance
4. **Iterate** on teacher_led_proportion if needed (try 0.3, 0.5, 0.7)
5. **Scale up** training timesteps once config is validated

---

## Appendix: Full Config Reference

From top run `relh.machina1_cloner.114.5.big3_teacherbc`:

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
  # For machina1, prefer recipes.experiment.machina_1.train(use_default_teacher=True)
  # so the current top-ranked beta-cvc dinky policy is resolved dynamically.
  # For cogsguard, use: "metta://policy/cogsguard?gear=10"
```
