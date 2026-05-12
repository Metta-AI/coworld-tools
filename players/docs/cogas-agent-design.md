# Cogas Agent Design

Blueprint for a leaderboard-winning agent targeting `cogs.aligned.junction.held > 1500`.

## 1. Architecture Choice: Phased Goal-Tree Hybrid

Cogas uses a **phased goal-tree** architecture, combining Planky's declarative goal decomposition with CogsGuard's
phase-based state machine and evolution-driven role selection.

**Why not pure behavior-tree?** A vibe-driven approach lacks explicit precondition reasoning. Agents thrash between
behaviors when preconditions aren't met (e.g., attempting to align without hearts). Goal-trees naturally decompose
"align junction" into "have gear AND have hearts AND be adjacent" without custom priority logic.

**Why not pure goal-tree (Planky)?** Planky has no phase awareness. It re-evaluates the full goal list every tick, which
is wasteful when the agent is mid-navigation. Adding phases (BOOTSTRAP, CONTROL, SUSTAIN) gives temporal structure that
reduces wasted re-evaluation and enables phase-specific goal priorities.

**Why not pure vibe-based (CogsGuard)?** CogsGuard's SmartRoleCoordinator is valuable, but the role behaviors themselves
are imperative spaghetti. Goal-tree decomposition inside each phase keeps role logic clean and extensible.

### Architecture Stack

```
┌─────────────────────────────────────┐
│  EvolutionaryRoleCoordinator        │  Role selection (adaptive)
├─────────────────────────────────────┤
│  PhaseController                    │  BOOTSTRAP → CONTROL → SUSTAIN
├─────────────────────────────────────┤
│  GoalEvaluator (per-phase goals)    │  Precondition decomposition
├─────────────────────────────────────┤
│  Navigator + EntityMap + SafetyMgr  │  Shared services (from Planky)
└─────────────────────────────────────┘
```

Each agent has:

- A **role** assigned by the coordinator (miner, scout, aligner, scrambler)
- A **phase** driven by game state (bootstrap, control, sustain)
- A **goal list** determined by role + phase, evaluated as a priority-ordered tree
- **Shared services** for navigation, entity tracking, and safety

## 2. Optimal Role Distribution for Machina1

### Default Distribution (10 agents)

| Role      | Count | Rationale                                                            |
| --------- | ----- | -------------------------------------------------------------------- |
| Miner     | 3     | Resource foundation; hearts require steady element supply            |
| Scout     | 1     | Procedural map demands early discovery of extractors + junctions     |
| Aligner   | 3     | Primary scoring role; more aligners = more junctions held            |
| Scrambler | 2     | Deny enemy junctions; converts clips-aligned to neutral for aligners |
| Flex      | 1     | Starts scout, transitions to aligner after map discovered            |

### Rationale

The `aligned.junction.held` metric is cumulative (junctions x time), so **early alignment** and **sustained control**
dominate. Three aligners working in parallel capture junctions faster. Two scramblers ensure the enemy cannot hold
junctions unopposed. Three miners produce the heart resources that aligners and scramblers consume. The flex agent
maximizes early discovery then converts to the highest-value late-game role.

### Adaptive Distribution (Evolution-Driven)

The evolutionary coordinator adjusts counts based on game-state signals:

| Signal                                        | Adjustment                      |
| --------------------------------------------- | ------------------------------- |
| All junctions already discovered (step > 200) | Convert scout → aligner         |
| Heart stockpile > 10                          | Reduce miners by 1, add aligner |
| No clips-aligned junctions remain             | Convert scramblers → aligners   |
| Resource deficit (any element < 5)            | Convert 1 aligner → miner       |
| Energy starvation (avg energy < 20)           | Prioritize junction alignment   |

## 3. Key Innovations Over Existing Agents

### 3.1 Energy-Aware Pathing

**Problem**: Move costs 3 energy. Agents exhaust energy after ~33 moves, then stall. Hub AOE (+100 energy) requires
standing near an aligned junction.

**Solution**: The navigator maintains an **energy budget**. Before committing to a path, it checks
`path_cost = len(path) * 3` against current energy. If the path exceeds budget, the agent detours to the nearest aligned
junction for recharge first. Charger positions are shared across all agents via the coordinator.

```
if path_energy_cost(target) > agent.energy - ENERGY_RESERVE:
    detour_to_nearest_junction()
else:
    navigate(target)
```

`ENERGY_RESERVE = 15` ensures agents always have enough energy to reach a junction from their current position.

### 3.2 Aligner Priority Queue

**Problem**: Existing aligners pick the nearest neutral junction. This leads to suboptimal sequencing when junctions
have different strategic value.

**Solution**: Score junctions by strategic value:

```
junction_score = (
    base_value
    + proximity_bonus(distance_to_hub)      # Near-hub junctions sustain energy
    + cluster_bonus(nearby_cogs_junctions)   # Cluster control creates energy zones
    - contest_penalty(nearby_clips_agents)   # Avoid contested junctions
    + resource_bonus(nearby_extractors)      # Junctions near resources help miners
)
```

Aligners pick the highest-scoring junction from a shared priority queue. Once an aligner claims a junction, it's removed
from the queue so others target different junctions.

### 3.3 Scrambler Target Selection

**Problem**: Scramblers target the nearest clips-aligned junction, ignoring strategic impact.

**Solution**: Score enemy junctions by disruption value:

```
disruption_score = (
    time_held_by_enemy                       # Longer-held = more valuable to disrupt
    + enemy_cluster_bonus(nearby_clips)       # Breaking clusters fragments enemy control
    + energy_denial(near_enemy_miners)        # Scrambling near enemy work zones denies energy
    - distance_penalty(from_scrambler)        # Still prefer reachable targets
)
```

### 3.4 Coordinated Heart Economy

**Problem**: Aligners and scramblers both need hearts. They independently navigate to the chest, creating contention and
wasted trips.

**Solution**: The coordinator tracks heart inventory across the team. Miners deposit to the commons. A shared counter
tracks available hearts. Aligners and scramblers **reserve** hearts before navigating to pick them up:

```
if coordinator.reserve_heart(agent_id):
    navigate_to_chest()
else:
    execute_fallback_behavior()  # mine, explore, or escort
```

This prevents two agents from racing to the same heart.

### 3.5 Bootstrap Fast-Path

**Problem**: The first 15-20 steps are critical. Gear stations are only available briefly. Agents that miss gear
acquisition are useless for the rest of the game.

**Solution**: The BOOTSTRAP phase has a single goal: **acquire gear within the first 20 steps**. All agents immediately
navigate to their role's gear station on spawn. The coordinator pre-assigns roles before step 0 so agents don't waste
steps on role selection. Scout gets first priority on gear (earliest discovery = most value).

### 3.6 Junction Defense

**Problem**: No existing agent defends aligned junctions. Enemy scramblers freely revert cogs-aligned junctions to
neutral.

**Solution**: After the CONTROL phase aligns key junctions, one aligner transitions to **sentinel mode** in the SUSTAIN
phase. The sentinel patrols aligned junctions and re-aligns any that get scrambled. This prevents score decay from enemy
disruption.

## 4. Evolution Integration

### Wiring Fitness to Game Metrics

The current evolution system never calls `record_agent_performance()`. Cogas wires this properly:

```python
def on_episode_end(self, metrics: dict):
    score = metrics.get("cogs.aligned.junction.held", 0)
    won = score > metrics.get("clips.aligned.junction.held", 0)
    for agent_id, assignment in self.agent_assignments.items():
        self.coordinator.record_agent_performance(agent_id, score, won)
    self.coordinator.end_game(won)
```

### Evolved Role Materialization

Current evolution samples roles but maps them back to static vibes, losing tier information. Cogas materializes evolved
roles into actual behavior sequences:

```python
def get_goals_for_evolved_role(role: RoleDef) -> list[Goal]:
    goals = []
    for tier in role.tiers:
        for behavior_id in tier.behavior_ids:
            behavior = catalog.get_behavior(behavior_id)
            goals.append(behavior_to_goal(behavior))
    return goals
```

Each `BehaviorDef` maps to a concrete `Goal` subclass. The goal-tree evaluator executes them in tier priority order,
preserving the evolved structure.

### Fitness-Weighted Role Assignment

Roles with higher fitness get assigned more often. The coordinator uses softmax selection:

```
P(role_i) = exp(fitness_i / temperature) / sum(exp(fitness_j / temperature))
```

Temperature starts high (exploration) and decays over generations (exploitation).

### Persistence

Cogas writes `role_catalog.json` at episode end and loads it at episode start. This enables cross-run knowledge
accumulation. The catalog tracks:

- Role definitions with fitness scores
- Behavior usage statistics
- Generation history

## 5. Phase-by-Phase Behavior Specification

### Phase 1: BOOTSTRAP (Steps 0-30)

**Objective**: Every agent acquires role gear and establishes map knowledge.

**Goal Priority (all roles)**:

1. `NavigateToGearStation` - Move directly to role-specific station
2. `AcquireGear` - Bump station to equip gear
3. `ShareDiscovery` - Log discovered structures to coordinator

**Scout-specific**:

1. `AcquireGear` (scout station)
2. `ExploreFrontier` - BFS-based frontier exploration, prioritize junction/extractor discovery
3. `BroadcastMap` - Update coordinator with all discovered positions

**Exit condition**: All agents have gear OR step > 30.

**Flex agent**: Starts as scout. After discovering 80% of map features or step > 50, transitions to aligner.

### Phase 2: CONTROL (Steps 30-300)

**Objective**: Establish junction control and resource production.

**Miner goals**:

1. `Survive(hp=15)` - Retreat if low HP
2. `RechargeEnergy(threshold=20)` - Detour to junction if energy low
3. `SelectResource` - Pick resource type based on team deficit (coordinator tracks)
4. `NavigateToExtractor` - Path to selected extractor
5. `MineResource` - Bump extractor to mine
6. `DepositCargo` - Navigate to hub/chest when cargo full

**Aligner goals**:

1. `Survive(hp=50)` - Higher HP threshold (aligners are high-value)
2. `RechargeEnergy(threshold=20)`
3. `AcquireHearts` - Navigate to chest, withdraw hearts (check reservation)
4. `SelectJunction` - Pick highest-value junction from priority queue
5. `NavigateToJunction` - Path to selected junction
6. `AlignJunction` - Execute align action (requires gear + heart + adjacent)

**Scrambler goals**:

1. `Survive(hp=30)` - Moderate threshold (scramblers have +200 HP from gear)
2. `RechargeEnergy(threshold=20)`
3. `AcquireHearts` - Navigate to chest (check reservation)
4. `SelectTarget` - Pick highest-disruption enemy junction
5. `NavigateToTarget` - Path to target junction
6. `ScrambleJunction` - Execute scramble action

**Scout goals** (pre-transition):

1. `Survive(hp=50)` - Scout has high HP from gear
2. `ExploreFrontier` - Continue discovering structures
3. `ReportNewFinds` - Update coordinator with discoveries

**Exit condition**: >=3 junctions aligned to cogs OR step > 300.

### Phase 3: SUSTAIN (Steps 300+)

**Objective**: Maintain junction control, defend against enemy scramblers, maximize cumulative score.

**Changes from CONTROL**:

- One aligner enters **sentinel mode**: patrols aligned junctions, re-aligns any that get scrambled. Selects patrol
  route as shortest cycle through all cogs-aligned junctions.
- Scramblers become more selective: only target enemy junctions that threaten cogs-controlled clusters.
- Miners prioritize heart production over raw resource gathering (deposit to commons more frequently).
- Flex agent (if not already transitioned) becomes aligner.

**Sentinel goals**:

1. `Survive(hp=50)`
2. `RechargeEnergy(threshold=20)`
3. `PatrolJunctions` - Cycle through aligned junctions
4. `RealignIfScrambled` - Re-align any junctions that lost alignment
5. `AlignNewJunction` - If all defended, opportunistically align new junctions

**Adaptive role rebalancing**: The coordinator checks every 50 steps:

- If heart stockpile is depleted: convert 1 scrambler → miner
- If no enemy junctions remain: convert scramblers → aligners
- If aligned junctions are being lost: add sentinel

## 6. Success Metrics and Targets

### Primary Target

| Metric                       | Target | Rationale                               |
| ---------------------------- | ------ | --------------------------------------- |
| `cogs.aligned.junction.held` | > 1500 | Bead requirement; competitive threshold |

### Secondary Targets

| Metric                       | Target          | Rationale                        |
| ---------------------------- | --------------- | -------------------------------- |
| `cogs.aligned.junction.held` | > 5000          | Top-tier leaderboard competitive |
| `resource.gathered`          | > 500           | Sufficient heart production      |
| `clipped.alignment.removed`  | > 10            | Active enemy denial              |
| Gear acquisition rate        | 100% by step 30 | Bootstrap reliability            |
| Energy starvation rate       | < 5% of moves   | Energy-aware pathing works       |
| Junction control ratio       | > 0.6           | Cogs holds majority of junctions |

### Baseline Comparisons

| Agent             | Expected `aligned.junction.held` |
| ----------------- | -------------------------------- |
| baseline          | ~0 (energy starvation)           |
| role              | ~0-100 (limited aligner logic)   |
| cogsguard_control | ~100-500 (best current)          |
| **cogas**         | **> 1500** (target)              |

### Risk Factors

1. **Energy starvation not resolved at engine level**: If hub AOE remains broken, energy-aware pathing is a workaround,
   not a fix. Score ceiling is lower.
2. **Procedural map variance**: Bad map seeds can place junctions far from hub, making early alignment slow. Mitigation:
   scout fast-path + flex agent.
3. **Strong enemy scramblers**: If the opponent runs aggressive scramble strategies, our sentinel + re-align loop may
   not keep pace. Mitigation: increase scrambler count via adaptive distribution.
4. **Evolution convergence time**: Cross-run persistence helps, but first-run performance relies on hand-tuned defaults.
   Mitigation: seed catalog with optimized base roles from this design.

## 7. Implementation Roadmap

### Stage 1: Core Agent

1. Create `cogames-agents/src/cogames_agents/policy/scripted_agent/cogas/` directory
2. Implement `CogasPolicy` extending `MultiAgentPolicy`
3. Implement `PhaseController` with BOOTSTRAP/CONTROL/SUSTAIN transitions
4. Port Planky's goal-tree evaluator with phase-aware goal lists
5. Implement role-specific goals (miner, aligner, scrambler, scout)
6. Reuse Planky's `Navigator` and `EntityMap`

### Stage 2: Innovations

7. Add energy-aware navigator wrapper
8. Implement junction priority queue with strategic scoring
9. Implement scrambler target selection with disruption scoring
10. Add coordinated heart reservation system
11. Add sentinel mode for SUSTAIN phase
12. Add flex agent role transition logic

### Stage 3: Evolution

13. Wire `EvolutionaryRoleCoordinator` with episode-end metrics
14. Implement `behavior_to_goal()` mapping for evolved roles
15. Add role catalog persistence (`role_catalog.json`)
16. Seed catalog with optimized defaults from this design

### Stage 4: Tuning

17. Run scrimmages against all existing agents
18. Tune role distribution counts
19. Tune junction scoring weights
20. Tune phase transition thresholds
21. Evaluate evolution convergence over multi-run sequences
