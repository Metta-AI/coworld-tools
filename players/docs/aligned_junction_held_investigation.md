# Investigation: aligned.junction.held Scoring Gap (300 vs 30k)

## Summary

The 100x scoring gap (PPO: ~300 vs expected: ~30,000) for `aligned.junction.held` is caused by a fundamental energy
starvation problem that prevents agents from effectively navigating and completing their roles.

## Key Findings

### 1. Scripted Agents Are NOT Successfully Aligning Junctions

After running `cogames play` with both the Nim (`metta://policy/role_nim`) and Python (`metta://policy/role`) policies,
I observed:

- **clips.aligned.junction.held: ~135,000** (over 5000 steps)
- **cogs.aligned.junction.held: 0** (zero junctions aligned to cogs)

This means the scripted agents themselves are failing to align junctions, just like PPO.

### 2. Root Cause: Energy Starvation

Agents are experiencing severe energy starvation:

| Metric                     | Expected | Observed                  |
| -------------------------- | -------- | ------------------------- |
| action.move.failed         | ~0%      | ~99%                      |
| action.move.success        | ~99%     | ~1%                       |
| max_steps_without_motion   | low      | ~2900 (out of 3000 steps) |
| energy.gained (3000 steps) | ~300,000 | ~130-200                  |

### 3. Why Energy is Depleted

The game is designed with an energy-based economy:

- **Move action costs**: 3 energy per move
- **Agent initial energy**: 100
- **Base energy regen**: +1 energy/tick
- **Hub AOE (expected)**: +100 energy/tick to cogs agents within range 10

**Problem**: The hub's AOE energy buff is NOT being applied to agents.

In testing, I observed:

- Agent spawns at (26, 26), hub at (29, 29) - distance 6 (within AOE range 10)
- Agent starts with 100 energy
- After 1 step: energy = 10 (dropped 90!)
- Expected: energy should increase to 200+ from AOE

### 4. The Junction Alignment Flow

To align a junction, agents must:

1. **Scrambler** scrambles clips-aligned junctions to neutral
   - Requires: scrambler gear + 1 heart
   - Must navigate to junction and bump into it

2. **Aligner** aligns neutral junctions to cogs
   - Requires: aligner gear + 1 influence + 1 heart
   - Must navigate to junction and bump into it

**Problem**: Agents can't navigate because they don't have energy to move.

### 5. Chicken-and-Egg Problem

The game design creates a catch-22:

- Agents need energy to move to junctions
- Junctions provide energy AOE when aligned to cogs
- But junctions start aligned to clips (enemy)
- The hub should provide energy, but its AOE isn't working

## Configuration Details

### Agent Energy Config

```python
inventory.limits = {'energy': ResourceLimitsConfig(base=10, max=65535, ...)}
inventory.initial = {'energy': 100}
inventory.regen_amounts = {'default': {'energy': 1, 'hp': -1, 'influence': -1}}
```

### Move Action Cost

```python
actions.move = MoveActionConfig(consumed_resources={'energy': 3})
```

### Hub AOE (Hub)

```python
aoes = [
    AOEEffectConfig(
        range=10,
        resource_deltas={'influence': 10, 'energy': 100, 'hp': 100},
        filters=[isAlignedToActor()]  # Same collective
    ),
    AOEEffectConfig(
        range=10,
        resource_deltas={'hp': -1, 'influence': -100},
        filters=[isEnemy()]  # Different collective
    )
]
```

### Junction AOE

Same structure as hub, but junctions are clips-aligned, so they:

- Give +100 energy to clips agents
- Deal -1 hp to cogs agents

## Recommendations

1. **Investigate AOE Application Bug**: The hub's energy AOE is not being applied to cogs agents. Check if there's a bug
   in the collective alignment matching for AOE effects.

2. **Reduce Move Energy Cost**: Consider lowering from 3 to 1 or 2 to make agents more mobile.

3. **Increase Base Energy Regen**: Increase from +1 to +5 or +10 per tick.

4. **Give Agents Initial Hearts**: Currently agents start with 0 hearts and must get them from chests, but they can't
   reach chests without energy.

5. **Check Scripted Agent Logic**: The Nim agents may have bugs in their pathfinding or role execution that cause them
   to get stuck even when they have energy.

## Follow-up (2026-01-27): Scripted Agent Position/Action Drift

I audited the Python scripted agents (`role`) with the debug harness to verify whether they are behaving sensibly in the
current Cogsguard arena. The results point to a concrete failure mode in the scripted agent stack, independent of PPO.

### Summary

- **Action execution appears 1-step delayed** in observations. The policy compares the _current_ intended action with
  `last_action_executed`, but the observation's `last_action` appears to reflect the **previous** step. This creates
  persistent mismatches.
- **Internal position drifts** for some agents (up to ~20 cells by ~200 steps), which corrupts the internal map.
- **Map pollution** follows: agents believe there are ~40k junctions (nearly the entire 200x200 internal grid) and only
  1 extractor, which collapses mining/gear loops.
- **Economy stalls quickly**: carbon/oxygen/germanium never increase in the collective, only silicon drifts upward. Gear
  resource windows close at steps ~15-17 and never reopen, so miners never get gear and aligner/scrambler are starved
  for hearts.

### Key Evidence

**Action mismatch (agent 0, first few steps)**

```
1 intended change_vibe_scrambler executed noop
2 intended move_south executed change_vibe_scrambler
3 intended move_south executed move_south
4 intended move_west executed move_south
5 intended move_south executed move_west
```

**Internal vs actual position drift after ~200 steps**

- Example: agent 0 delta ≈ (-21, -1) between internal and actual positions (computed using initial offset)
- Several other agents show smaller but non-zero drift

**Structure discovery skew (agent 0 @ 300 steps)**

- Extractors known: **1**
- Chargers known: **~39,940** (cogs-aligned: 0)

**Collective resource deltas (first 300 steps)**

- carbon: +0
- oxygen: +0
- germanium: +0
- silicon: +33

**Gear resource availability windows**

- aligner/scrambler: available only for ~15 steps
- miner/scout: available only for ~17 steps
- After that, resources never re-accumulate

### Likely Root Cause

The policy updates position only when `last_action_executed == last_action` (intended). If `last_action_executed` lags
by one step, the policy effectively discards real movement and accumulates drift. That drift corrupts object locations,
causing junctions to fill the map and extractors to be ignored as unsafe/unreachable.

### Suggested Fix Directions

- Verify `last_action` timing in observations and adjust tracking (e.g., compare against previous intended action or
  update position from executed action alone).
- Add a debug sanity check to detect action mismatch rates and position drift early.
- Re-run the scripted audit after the action tracking fix to validate extractor discovery and gear acquisition.

### Future Work & Potential Leads

- Confirm `last_action` semantics in the simulator (does it report the previous step?). Add a minimal probe to log the
  raw action id each step to verify the off-by-one hypothesis.
- Consider tracking movement solely from `last_action_executed` (ignore intended action), or stash the previous intended
  action to align with the observation timing.
- Improve object tag handling: prefer `type:*` tags over `collective:*` tags when choosing the primary object name, or
  use explicit tag precedence to reduce misclassification.
- Add a drift/mismatch counter to the debug harness that fails fast when mismatch rate exceeds a threshold.
- Revisit extractor safety heuristics after fixing drift (danger radius 12 on a 50x50 map may be too conservative once
  junctions are correctly localized).
- Re-run multi-seed audits (e.g., seeds 1–5) and longer rollouts (2–5k steps) to confirm resource accumulation, gear
  acquisition, and alignment/scramble loops are restored.

### Likely Failure Modes Across Scripted Agents (Role, Teacher, Targeted)

Below are the top suspected failure modes that explain _all_ observed symptoms (no gear, no mining loop, no alignment),
and what would definitively confirm or clear each one. These are ordered by impact.

1. **Action timing off-by-one in scripted agent tracking (position drift)**
   - **Symptom:** Large intended vs executed mismatch rates; internal position drift; map pollution.
   - **Why it breaks everything:** Incorrect positions cause object coordinates to shift, so junctions/extractors are
     recorded in wrong places. This makes extractors appear unsafe/unreachable and stalls mining.
   - **Definitive test:** Log `(intended_action, last_action_executed)` with step index and compare to simulator action
     stream. If `last_action_executed` consistently matches the _previous_ intended action, this is confirmed.

2. **Tag precedence / object naming misclassification**
   - **Symptom:** Objects are identified by first tag (e.g., `collective:*`), which can hide type tags; leads to
     incorrect structure typing and alignment inference.
   - **Why it breaks everything:** Stations/extractors/junctions are misclassified, so role logic targets the wrong
     tiles or never discovers the required structure types.
   - **Definitive test:** Force tag precedence (`type:*` over `collective:*`) and re-run scripted audit. If extractor
     discovery and gear acquisition recover, this was a key blocker.

3. **Charger over-discovery / map flooding**
   - **Symptom:** 10s of thousands of junctions recorded in a 200x200 internal grid after a few hundred steps.
   - **Why it breaks everything:** Safety heuristics see junctions everywhere (enemy danger zones), so miners avoid
     extractors; aligner/scrambler logic targets noise.
   - **Definitive test:** After fixing action timing + tag precedence, junctions should localize to a small count. If
     not, the junction discovery logic itself is faulty.

4. **Extractor safety heuristics too conservative for Cogsguard map**
   - **Symptom:** Even with correct localization, miners reject extractors as “unsafe” and never gather resources.
   - **Why it breaks everything:** Collective resources never replenish; gear stations stay unaffordable; align/scramble
     loops never start.
   - **Definitive test:** Temporarily relax danger radius (e.g., 12 -> 6) or bypass danger check for first 200 steps. If
     mining/gear starts, heuristics are the culprit.

5. **Resource bootstrap loop too fragile (gear depends on deposits that depend on gear)**
   - **Symptom:** Gear availability only in the first 15–17 steps, then permanently unavailable.
   - **Why it breaks everything:** Miners never get gear; aligners/scramblers never get hearts/influence; junctions
     remain clips-aligned.
   - **Definitive test:** Seed collective resources for gear (e.g., 2–3 gear purchases worth) or give miners initial
     gear. If scripted policies stabilize, bootstrap constraints are too tight.

### Agent-Specific Failure Modes to Check

**Role (multi-role scripted policy)**

- **Action tracking drift**: already observed in audit; this is the primary suspect.
- **Gear acquisition race**: scramblers spam gear stations without resources early; miners/scouts stay gearless.
- **Map pollution**: junctions/extractors mislocalized if tag precedence + action timing are both off.
- **Definitive checks**: fix action timing; enforce tag precedence; re-run role audit.

**Teacher (CogsguardTeacherPolicy + Nim backend)**

- **Vibe reset / schedule issues**: teacher relies on episode pct + scheduler; resets could pin agents in wrong vibe.
- **Cross-impl parity**: Nim agents may interpret obs/vibe tags differently than Python.
- **Definitive checks**: run teacher in the same debug harness for 200–500 steps with verbose vibe logs; compare to role
  on identical seed/map. If behavior diverges, Nim parity is suspect.

**Targeted/Control/V2 policies**

- **Extractor targeting assumptions**: targeted miners prefer extractors based on `inventory_amount` and
  `resource_type`; if extractor tags are misclassified, targeting degenerates.
- **Role allocation stability**: targeted/control policies can shift role ratios; if miners drop to zero or are delayed,
  the economy never recovers.
- **Definitive checks**: log role counts each step and ensure miners stay ≥1; verify extractor discovery count rises.

**Wombo/Swiss (generalist multi-role)**

- **Role thrash**: frequent role switching can prevent any agent from completing gear → action loops.
- **Definitive check**: add a role-lock window or log role switches; if action throughput increases, thrash was hurting.

**Single-role policies (miner/scout/aligner/scrambler)**

- **Tooling sanity**: if single-role agents fail to do their one job, the environment or tag parsing is broken.
- **Definitive check**: run `miner` alone and verify extractor discovery + deposit; run `aligner` and verify junction
  alignment when hearts/influence are seeded.

### Additional Failure Modes Worth Ruling Out

- **Agent occupancy detection depends on tag order**: occupancy is only recorded when `obj_name == "agent"`. If tag
  ordering yields `obj_name = "collective:cogs"` or `type:agent`, collisions will be ignored and pathing will walk
  through other agents. This can strand agents on stations or block extractor access.
  - **Test:** treat any object with tag `agent` or `type:agent` as an agent for occupancy.

- **Extractor inventory visibility**: `inventory_amount` is derived from `obj_state.inventory`. If extractor inventory
  tokens are absent in observations, the first “empty dict” after discovery marks the extractor as depleted forever.
  - **Test:** log `obj_state.inventory` for extractors over time; if it is always empty, treat extractors as usable.

- **Junction/junction alignment inference**: alignment uses `obj_state.clipped` or tag heuristics. If `clipped` is not
  reliable for junctions, junctions can appear neutral or misaligned, breaking align/scramble targeting and safety.
  - **Test:** compare alignment inferred by tags vs. by simulator ground truth for a few steps.

- **Vibe change reliability**: initial role assignment depends on successful `change_vibe_*` actions. If those actions
  are delayed or rate-limited, agents can remain in `default` longer than expected.
  - **Test:** log current vibe vs. intended vibe for the first 20 steps; ensure all agents reach their role vibe.

- **Policy URI mismatch during audits**: `cogsguard_py` is not a registered short name; `teacher` does not accept
  role-count kwargs. Passing the wrong URI can silently invalidate comparisons.
  - **Test:** use `role` for multi-role counts and `teacher` with no role args.

### Shortlist: 3–5 Things That Should Clear This Up

If we want the fastest route to clarity, do these in order:

1. Fix/validate action timing (`last_action_executed`) and update position tracking accordingly.
2. Enforce tag precedence (`type:*` > `collective:*`) when choosing object names/types.
3. Re-run scripted audit; confirm junction counts and extractor discovery normalize.
4. If still stalled, relax extractor danger radius or disable danger gating for early steps.
5. If still stalled, provide minimal resource/gear bootstrap and re-test.

## Test Commands Used

```bash
# Run with teacher policy (uses Nim backend)
uv run tools/run.py cogsguard.play "policy_uri=metta://policy/teacher" render=log max_steps=3000

# Run with Python policy
uv run tools/run.py cogsguard.play "policy_uri=metta://policy/role" render=log max_steps=3000

# Check simulation state
uv run python -c "
from mettagrid.simulator.simulator import Simulator
from recipes.experiment.cogsguard import make_env
cfg = make_env(num_agents=10, max_steps=100)
sim = Simulator().new_simulation(cfg, seed=42)
# ... inspect state
"
```

## 2026-01-27 Follow-up: 1000-step scripted runs (seed 42)

This follow-up rechecked scripted agents on a single 1000-step `recipes.experiment.cogsguard` episode and compared the
full evaluation pipeline (`tools/run.py evaluate`) with the debug harness
(`packages/cogames-agents/scripts/run_cogsguard_rollout.py`).

### 1) EvaluateTool results (max_steps=1000, max_workers=1)

For each policy, we extracted `collective.cogs["aligned.junction.held"]` and `collective.clips["aligned.junction.held"]`
from the episode stats. The cogs key is missing and effectively zero in all cases, while clips continues to accumulate
junction hold time.

| policy_uri              | cogs.aligned.junction.held | clips.aligned.junction.held |
| ----------------------- | -------------------------- | --------------------------- |
| metta://policy/wombo    | 0.00                       | 35033.00                    |
| metta://policy/role_nim | 0.00                       | 37000.00                    |
| metta://policy/role     | 0.00                       | 29023.00                    |
| metta://policy/alignall | 0.00                       | 28021.00                    |
| metta://policy/teacher  | 0.00                       | 36022.00                    |

### 2) Debug harness instrumentation

The debug harness gives role/gear/structure visibility that the eval pipeline does not.

#### wombo (metta://policy/wombo)

- aligner: 0 align attempts
- scrambler: 3 scramble attempts
- gear station use is mostly without resources (e.g., aligner 1055 uses, 1 with resources)
- gear resource windows are rare (8-16 steps total), and even rarer when a role is adjacent (0-4 steps)

#### role with miner-heavy ratio

Command:

```bash
uv run packages/cogames-agents/scripts/run_cogsguard_rollout.py \
  --steps 1000 --max-steps 1000 --seed 42 --agents 10 \
  --policy-uri 'metta://policy/role?miner=5&scout=1&aligner=2&scrambler=2' \
  --allow-missing-roles
```

Findings:

- miners: 32 mine attempts, 29 deposits
- aligner: 29 align attempts, 0 mismatches
- scrambler: 4 scramble attempts
- gear station use is still mostly without resources (aligner 970 uses, 1 with resources)
- resource windows are short (17-21 steps) with limited adjacency (0-4 steps)

#### Note on Nim role policy

The Nim `metta://policy/role_nim` policy does not expose per-agent `_state` to the harness, so role-level
instrumentation appears empty. Use `role` for detailed instrumentation.

### 3) Interpretation

These 1000-step runs still point to resource/coordination starvation (gear resource windows and adjacency are rare),
rather than purely insufficient miner counts.

### 4) Future plans / next debug targets

- Instrument why resource windows are so brief (collective inventory deltas vs gear costs) and whether miners are
  depositing in the right chest/collective bucket.
- Check if role agents are reaching the right stations when resources are available (trace adjacency timing).
- Verify whether align/scramble actions require additional prerequisites (hearts/influence) that remain starved.
- Compare 1000-step vs 3000-step runs to see if longer horizons meaningfully increase cogs alignment.
- Add a small experiment that forces fixed role ratios in `wombo` (or a targeted policy) to isolate role-mix effects.

## Additional failure modes observed across scripted agents

These are inferred from the 1000-step evals plus the debug harness runs. Each bullet is a distinct failure mode that can
block `cogs.aligned.junction.held`, regardless of role mix.

1. **Resource windows are too short and poorly aligned with role adjacency**
   - Gear station usage is dominated by attempts without resources.
   - Resource windows exist but are brief, and the right role is rarely adjacent during those windows.
   - Outcome: role agents fail to equip, so alignment actions never trigger.

2. **Aligner/scrambler action rate is extremely low**
   - Even with role and miner-heavy ratios, align/scramble attempts are sparse.
   - Outcome: junctions remain clips-aligned, so cogs never get junction hold credit.

3. **Role thrash / non-concurrent roles**
   - In role, the “agents=10” count reflects agents spending time in that role at some point, not concurrent role
     assignment. This suggests roles may be cycling without sustained role coverage.
   - Outcome: miners/aligners/scramblers are not reliably present at the same time to complete the multi-step flow.

4. **Instrumentation visibility mismatch (Nim vs Python)**
   - Nim `role_nim` policy does not expose `_state`, so debug harness visibility is limited. This can mask state/role
     misbehaviors in the Nim path.
   - Outcome: we may be missing a Nim-specific failure mode (pathing/role execution), distinct from Python behavior.

5. **Potential prerequisites beyond gear (hearts/influence)**
   - Aligner requires aligner gear + influence + heart. Scrambler requires scrambler gear + heart.
   - The debug harness does not currently verify these prerequisites at the moment of action.
   - Outcome: actions may fail even with gear, if hearts/influence are starved.

## Definitive next steps (3–5 experiments to disambiguate causes)

These are designed to be decisive; each should either confirm a root cause or eliminate it.

1. **Resource window tracing (collective inventory deltas)**
   - Add a short-lived trace that logs collective resource levels each tick plus gear station attempts.
   - Goal: confirm whether resources are actually available when agents are adjacent and whether deposits are hitting
     the correct collective bucket.

2. **Action prerequisite audit (hearts/influence at action time)**
   - Instrument align/scramble attempts to log inventory state (gear, hearts, influence).
   - Goal: determine if action failures are due to missing hearts/influence versus pathing/targeting.

3. **Concurrent role coverage audit**
   - Track per-tick role counts and role transitions for role/wombo.
   - Goal: measure how often the miner + scrambler + aligner roles are simultaneously staffed for >N steps.

4. **Nim vs Python parity check**
   - Run the same scenario with `role_nim` (Nim) vs `role`, capturing only metrics available to both (e.g., action
     counts, movement success).
   - Goal: isolate Nim-specific logic or pathing regressions that don’t exist in Python.

5. **Long-horizon comparison (1000 vs 3000 steps)**
   - Repeat the 1000-step runs at 3000 steps to determine if time horizon is the limiting factor.
   - Goal: verify whether alignment is simply delayed versus fundamentally blocked.

## Related Files

- `packages/cogames/src/cogsguard/mission.py` - CogsGuard mission config
- `packages/cogames/src/cogsguard/stations.py` - Junction and Hub configs
- `packages/cogames-agents/src/cogames_agents/policy/nim_agents/cogsguard_agents.nim` - Nim scripted agents
- `packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/` - Python scripted agents
- `recipes/experiment/cogsguard.py` - Recipe for running CogsGuard
