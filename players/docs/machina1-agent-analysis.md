# Machina1 Arena: Scripted Agent Strategic Analysis

This document analyzes the machina1 open-world arena and evaluates the expected performance of each scripted agent
variant. It covers map layout, agent strengths/weaknesses, optimal role distributions, and strategic recommendations.

---

## 1. Machina1 Map Layout and Key Features

### Generation

Machina1 uses a procedurally generated 88x88 grid via `SequentialMachinaArena`. The arena is not a static map file -- it
is rebuilt each episode from a deterministic pipeline:

1. **Base biome** (plains) fills the entire grid.
2. **Biome zones** (forest, desert, caves, city) are placed as bounded sub-regions consuming up to 27% of the map area
   each, using BSP layout.
3. **Dungeon zones** (DFS mazes, Kruskal mazes, radial mazes) overlay up to 20% of the area.
4. **Asteroid boundary mask** carves the outer border into an irregular ring (enabled for maps >= 80x80).
5. **Building placement** distributes extractors and junctions across the walkable area at 1.75% coverage.
6. **Central hub** places the hub, chest, spawn points, and role stations.
7. **Connectivity pass** ensures all zones are reachable.

### Key Structures

| Structure           | Role                                                   | Placement                          |
| ------------------- | ------------------------------------------------------ | ---------------------------------- |
| Hub                 | Craft hearts from 4 resources                          | Central hub                        |
| Chest               | Store/transfer resources and hearts                    | Central hub                        |
| Charger             | Recharge agent energy (50 energy/use)                  | Distributed (weight 0.6)           |
| Carbon extractor    | 2 carbon/use, 25 uses, no cooldown                     | Distributed (weight 0.3) + corners |
| Oxygen extractor    | 10 oxygen/use, 5 uses, 10k-tick cooldown               | Distributed (weight 0.3) + corners |
| Germanium extractor | 2 germanium/use, 5 uses, 20k-tick cooldown, synergy=50 | Distributed (weight 0.5) + corners |
| Silicon extractor   | 15 silicon/use, 10 uses, costs 20 energy               | Distributed (weight 0.3) + corners |
| Spawn points        | Agent starting locations                               | Central hub perimeter (up to 20)   |
| Role stations       | Gear dispensers (miner/scout/aligner/scrambler)        | Central hub                        |

### Heart Assembly Recipes

| Tier | Carbon | Oxygen | Germanium | Silicon | Hearts produced |
| ---- | ------ | ------ | --------- | ------- | --------------- |
| 1    | 10     | 10     | 2         | 30      | 1               |
| 2    | 15     | 15     | 3         | 45      | 2               |
| 3    | 20     | 20     | 4         | 60      | 3               |
| 4    | 25     | 25     | 5         | 75      | 4               |

Higher tiers are more efficient (4 hearts for 2.5x the cost of 1 heart).

### Map Characteristics Relevant to Strategy

- **88x88 with asteroid mask**: Effective walkable area is smaller than the full grid. Agents waste time if they wander
  into dead-end wall pockets near borders.
- **Mixed biomes**: Cave regions have narrow corridors (chokepoints), forest regions have scattered obstacles, city
  regions have grid-like paths, desert regions are open. Agents need robust pathfinding.
- **Central hub convergence**: All agents spawn near the hub/chest. Early game is a scramble for nearby extractors;
  mid/late game requires traversing biome zones to reach distant resources.
- **Resource scarcity gradient**: Carbon is abundant (25 uses, no cooldown) but yields only 2 per use. Germanium is
  scarce (5 uses, 20k cooldown) but has synergy bonuses. Silicon is energy-expensive. Oxygen has long cooldowns.
  Germanium and silicon are the bottleneck resources.
- **Charger density**: Chargers have the highest placement weight (0.6), ensuring reasonable energy access. However,
  junction alignment is the core competitive mechanic in cogs-vs-clips variants.
- **Episode length**: 10,000 steps. At 2 energy per move, agents can traverse ~50 tiles before needing a recharge
  (starting energy 100, regen 1/tick).

---

## 2. Predicted Strengths and Weaknesses by Agent

### Baseline Agent

**Architecture**: Phase-based state machine (GATHER -> ASSEMBLE -> DELIVER -> RECHARGE). Simple explore-gather-assemble
loop.

| Aspect       | Assessment                                                                                                                                                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Strengths    | Simple and reliable. Low overhead. Handles basic resource loop. Stuck detection with escape.                                                                                                           |
| Weaknesses   | No role specialization. No junction alignment (critical in competitive play). No multi-agent coordination. Explores randomly -- wastes steps in maze/cave biomes. No resource prioritization.          |
| Machina1 fit | **Poor**. The mixed-biome procedural map punishes random exploration. No alignment mechanics means zero competitive capability. Single-loop resource gathering misses higher-tier assembly efficiency. |

### Unclipping Agent (ladybug_py)

**Architecture**: Extends baseline with extractor unclipping via gear items.

| Aspect       | Assessment                                                                                                                                                  |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Strengths    | Can restore clipped extractors, recovering resource access. Handles the unclip craft-and-apply workflow.                                                    |
| Weaknesses   | Inherits all baseline weaknesses. Unclipping is only relevant when enemy scramblers have clipped extractors -- in pure resource gathering it adds overhead. |
| Machina1 fit | **Poor to moderate**. Useful only in adversarial scenarios. The baseline movement inefficiency dominates performance.                                       |

### Planky Agent

**Architecture**: Goal-tree hierarchical policy. Each role has a priority-ordered goal list. Goals evaluate
preconditions and execute in priority order.

| Aspect       | Assessment                                                                                                                                                                                                                                   |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Strengths    | Priority-based goal evaluation naturally handles interrupts (e.g., recharge when low energy). Entity map tracks discovered objects. Failed-move detection improves maze navigation. Supports dynamic "stem" role that picks role at runtime. |
| Weaknesses   | Goal evaluation overhead per tick. Entity map doesn't persist across episodes. No team-level coordination beyond role distribution.                                                                                                          |
| Machina1 fit | **Moderate to good**. Goal-tree priority handles the mixed-terrain well (recharge goals fire when needed). Stem role adapts to discovered map state. Lacks the junction-alignment sophistication of CoGsGuard.                               |

### CoGsGuard (role)

**Architecture**: Multi-role vibe system with SmartRoleCoordinator. Tracks junction alignments, manages structure
discovery, coordinates role selection across team.

| Aspect       | Assessment                                                                                                                                                                                                                                                                                                                                |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Strengths    | Most sophisticated coordination. SmartRoleCoordinator distributes roles based on team state and discovered structures. Charger alignment tracking enables competitive play. Location loop detection breaks pathfinding deadlocks. Frontier exploration algorithm for systematic map coverage. Path caching reduces redundant computation. |
| Weaknesses   | Complexity means more failure modes. Initial role assignment before map discovery may not be optimal. Smart coordinator relies on shared state that takes time to populate.                                                                                                                                                               |
| Machina1 fit | **Good**. The coordinator handles mixed biomes well by adapting roles to discovered structures. Frontier exploration is valuable on the 88x88 procedural map. Charger alignment is critical for competitive scoring.                                                                                                                      |

### CoGsGuard V2 (cogsguard_v2)

**Architecture**: CoGsGuard with tuned default role allocation formula.

| Aspect       | Assessment                                                                                                                                                        |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Strengths    | Better initial role distribution than base CoGsGuard. For 4 agents: 1 scrambler, 1 aligner, 1 scout, 1 miner. Scales role counts proportionally for larger teams. |
| Weaknesses   | Static initial distribution doesn't adapt to map characteristics. Same runtime behavior as base CoGsGuard once roles are assigned.                                |
| Machina1 fit | **Good to strong**. The default 4-agent split is well-balanced for machina1 where all four roles have clear utility.                                              |

### CoGsGuard Control (cogsguard_control)

**Architecture**: Phased commander coordinator with active role management. Phases: exploration -> control -> sustained
operations.

| Aspect       | Assessment                                                                                                                                                                                                                                                                                   |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Strengths    | Phase-based planning matches machina1 game flow (explore early, control mid, sustain late). Commander reassigns roles every 40 steps based on game state. Shared junction mapping across team. Scrambler variant prioritizes enemy junctions. Aligner variant prioritizes neutral junctions. |
| Weaknesses   | Commander coordination adds latency (40-step decision cycle). Phase transitions may not align with stochastic procedural map discovery. Single point of failure if commander logic has bugs.                                                                                                 |
| Machina1 fit | **Strong**. The phased approach maps well to the 10k-step episode structure. Commander coordination is valuable on the complex procedural map where reactive role switching outperforms static assignment.                                                                                   |

### Wombo (CoGsGuard Generalist)

**Architecture**: CoGsGuard variant prioritizing junction alignment across multiple locations.

| Aspect       | Assessment                                                                                                                                         |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Strengths    | Focuses on controlling multiple junctions (junctions), which dominates scoring in competitive modes. Adapts roles based on current map conditions. |
| Weaknesses   | Junction-focused strategy may underperform in pure resource-gathering scenarios. Less effective if few junctions are discovered early.             |
| Machina1 fit | **Strong in competitive play**. Junction control is the primary competitive lever. Less optimal for pure heart-production metrics.                 |

### Demo Policy (tiny_baseline)

**Architecture**: Minimal random-movement policy for testing.

| Aspect       | Assessment                    |
| ------------ | ----------------------------- |
| Strengths    | None for production use.      |
| Weaknesses   | Random movement. No strategy. |
| Machina1 fit | **Non-viable**. Testing only. |

---

## 3. Optimal Role Distributions

### Resource Economy Analysis

The heart recipe bottleneck determines optimal role ratios. For tier-1 hearts (10C, 10O, 2Ge, 30Si):

| Resource  | Per heart | Yield/use | Uses | Effective trips | Bottleneck?                             |
| --------- | --------- | --------- | ---- | --------------- | --------------------------------------- |
| Carbon    | 10        | 2         | 25   | 5 uses/heart    | No (abundant, no cooldown)              |
| Oxygen    | 10        | 10        | 5    | 1 use/heart     | Moderate (long cooldown)                |
| Germanium | 2         | 2         | 5    | 1 use/heart     | **Yes** (longest cooldown, fewest uses) |
| Silicon   | 30        | 15        | 10   | 2 uses/heart    | **Yes** (energy cost, volume)           |

Germanium and silicon are the bottleneck resources. Silicon requires 20 energy per extraction, meaning miners need
junction access.

### Recommended Distributions by Team Size

**4 agents (default machina1 configuration):**

| Role      | Count | Rationale                                                                                                |
| --------- | ----- | -------------------------------------------------------------------------------------------------------- |
| Miner     | 1     | Handles resource gathering loop. Focus on Ge/Si.                                                         |
| Scout     | 1     | Critical on procedural 88x88 map. Discovers extractors, junctions, and junction alignments for the team. |
| Aligner   | 1     | Secures junctions for team energy access and competitive scoring.                                        |
| Scrambler | 1     | Denies enemy junction control. Essential in competitive variants.                                        |

**8 agents:**

| Role      | Count | Rationale                                     |
| --------- | ----- | --------------------------------------------- |
| Miner     | 3     | Two focused on Si/Ge bottleneck, one on C/O.  |
| Scout     | 1     | One scout covers the map.                     |
| Aligner   | 2     | More junctions to align on larger team games. |
| Scrambler | 2     | Counter enemy aligners and deny resources.    |

**12+ agents:**

| Role      | Count | Rationale                                                 |
| --------- | ----- | --------------------------------------------------------- |
| Miner     | 4-5   | Diminishing returns after 5 (extractor exhaustion).       |
| Scout     | 1-2   | Map fully discovered quickly. Second scout becomes miner. |
| Aligner   | 3-4   | Charger control scales with team size.                    |
| Scrambler | 3-4   | Denial scales with opponent team size.                    |

### Variant-Specific Adjustments

- **Pure resource gathering (no competition)**: 3 miners, 1 scout. No aligners/scramblers needed.
- **heart_chorus variant**: Shift toward more aligners (junction control amplifies heart production).
- **High-difficulty variants**: More scramblers to counter aggressive enemy policies.

---

## 4. Strategic Recommendations for Leaderboard-Winning Agent

### Tier 1: High-Impact Improvements

1. **Use CoGsGuard Control or V2 as the base.** These have the best coordination for machina1's procedural complexity.
   Control's phased planning matches the explore-then-exploit game flow.

2. **Optimize early-game scouting.** The procedural map means extractors and junctions are in unknown locations each
   episode. A scout that systematically covers the map using frontier exploration (already in CoGsGuard) should
   broadcast discoveries to the team immediately. First-mover advantage on germanium extractors is decisive.

3. **Prioritize tier-4 heart assembly.** Batch resources for tier-4 recipes (25C, 25O, 5Ge, 75Si -> 4 hearts) rather
   than crafting tier-1 hearts individually. This is 60% more efficient per resource unit. Agents should accumulate
   resources (cargo capacity 100) before visiting the hub.

4. **Germanium synergy exploitation.** Germanium extractors have synergy=50, meaning multiple agents extracting
   simultaneously get bonus yields. Coordinate 2+ miners to arrive at germanium extractors together. This is the single
   highest-leverage tactical coordination available.

### Tier 2: Medium-Impact Improvements

5. **Energy-aware silicon mining.** Silicon costs 20 energy per extraction. Miners should ensure junction access before
   committing to silicon runs. Route planning: junction -> silicon extractor -> junction -> hub.

6. **Adaptive role switching mid-episode.** After the map is fully scouted (typically by step 2000-3000 on 88x88),
   convert the scout to a miner or aligner. The control agent's 40-step reassignment cycle enables this.

7. **Charger control as force multiplier.** Aligned junctions benefit the whole team. Prioritize aligning junctions near
   the central hub and near germanium/ silicon extractor clusters. One well-placed aligned junction supports multiple
   miners.

8. **Maze biome navigation.** Maze and cave biomes create long detours. Agents should cache paths and prefer extractors
   in open biomes (desert, plains) over equivalent extractors in maze zones. Path length should factor into extractor
   selection.

### Tier 3: Refinements

9. **Chest utilization for resource buffering.** The central chest enables resource sharing. A dedicated miner can
   deposit partial resources for another agent to assemble, avoiding the round-trip cost.

10. **Scrambler target prioritization.** Focus scrambling on enemy-aligned junctions near the hub or near resource
    clusters. Scrambling an isolated junction has less impact than scrambling one that supports enemy mining.

11. **Cooldown-aware extractor rotation.** Oxygen (10k ticks) and germanium (20k ticks) have long cooldowns. Miners
    should rotate between multiple extractors rather than waiting at one. The scout's discovered-extractor list enables
    optimal rotation routes.

---

## 5. Evolution System Optimization for Machina1

### Current State

The evolution system (see `evolution-system-architecture.md`) uses generational selection with crossover and mutation to
evolve role definitions. However, two critical gaps limit its effectiveness:

1. **No episode trigger wiring**: `record_agent_performance()` and `end_game()` are never called, so fitness stays at
   0.0 and selection is uniform random.
2. **Roles map to vibes, not behavior sequences**: Evolved roles just select a vibe string (`miner`, `scout`, etc.),
   losing the tier-ordering that evolution produces.

### What Evolution Could Optimize for Machina1

**If the gaps were fixed**, the evolution system could optimize:

#### A. Role Distribution Ratios

Instead of static distributions (1:1:1:1), evolution could discover that machina1 favors specific ratios like 2 miners :
1 scout : 1 aligner for pure resource gathering, or 1 miner : 0 scouts : 2 aligners : 1 scrambler for competitive
junction control.

#### B. Behavior Priority Ordering

The tier system allows different orderings like:

- Aggressive miner: `[find_extractor, mine_resource, deposit_resource, explore]`
- Cautious miner: `[recharge, find_extractor, mine_resource, deposit_resource]`

Evolution could discover that on machina1 (with its energy-expensive silicon and scattered junctions), the cautious
miner ordering outperforms aggressive mining.

#### C. Hybrid Roles

Recombination could produce roles that combine behaviors from multiple sources:

- **Scout-miner**: `[discover_extractors, mine_resource, explore]` -- scouts while mining, useful after initial map
  discovery.
- **Aligner-scrambler**: `[align_junction, scramble_junction, explore]` -- controls junctions opportunistically.

These hybrids are impossible with static role definitions.

#### D. Phase-Aware Role Switching

With fitness tracking, evolution could learn that:

- Early game: High scout fitness (map discovery has outsized value)
- Mid game: High miner/aligner fitness (resource/control phase)
- Late game: High scrambler fitness (denial matters when extractors are exhausted)

This would produce generation-over-generation shifts in the role population.

### Recommended Evolution Improvements for Machina1

1. **Wire fitness scoring**: Connect `record_agent_performance()` to episode-end metrics (hearts produced, junctions
   aligned, resources gathered). Use the `hub.heart.created` metric that the sweep system already tracks.

2. **Make evolved roles drive behavior**: Instead of mapping roles to vibe strings, use `materialize_role_behaviors()`
   to produce actual behavior sequences that the agent executes tier-by-tier.

3. **Add map-conditioned fitness**: Score roles differently based on discovered map characteristics (e.g., biome
   composition, extractor density). This lets evolution adapt to the procedural generation.

4. **Persist the catalog**: Serialize `RoleCatalog` to `role_history.json` (as the Nim tribal-village implementation
   does) so evolution accumulates knowledge across training runs rather than resetting each episode.

5. **Add machina1-specific behaviors**: Register behaviors like `synergy_mine_germanium` (coordinate with another miner
   at germanium extractors) or `tier4_assembly` (batch resources for tier-4 recipes). These give evolution
   machina1-specific building blocks to compose.

---

## Summary

| Agent                 | Machina1 Rating      | Best Use Case                     |
| --------------------- | -------------------- | --------------------------------- |
| tiny_baseline         | Non-viable           | Testing only                      |
| baseline              | Poor                 | Ablation baseline                 |
| ladybug_py            | Poor-Moderate        | Adversarial unclipping            |
| planky                | Moderate-Good        | Goal-priority research            |
| role (CoGsGuard)      | Good                 | General competitive play          |
| cogsguard_v2          | Good-Strong          | Balanced default teams            |
| wombo                 | Strong (competitive) | Junction control focus            |
| **cogsguard_control** | **Strong**           | **Best for machina1 leaderboard** |

The recommended leaderboard strategy is: **CoGsGuard Control** with 4 agents, phased exploration-to-control planning,
germanium synergy exploitation, and tier-4 heart batching. Fixing the evolution system's fitness wiring would enable
further automated optimization of role distributions and behavior priorities specifically for machina1's procedural
arena characteristics.
