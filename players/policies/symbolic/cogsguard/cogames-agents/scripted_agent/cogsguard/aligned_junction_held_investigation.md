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

## Related Files

- `packages/cogames/src/cogsguard/mission.py` - CogsGuard mission config
- `packages/cogames/src/cogsguard/stations.py` - Junction and Hub configs
- `packages/cogames-agents/src/cogames_agents/policy/nim_agents/cogsguard_agents.nim` - Nim scripted agents
- `packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/` - Python scripted agents
- `recipes/experiment/cogsguard.py` - Recipe for running CogsGuard
