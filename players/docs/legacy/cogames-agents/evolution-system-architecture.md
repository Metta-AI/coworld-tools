# Evolution System Architecture

This document describes the evolutionary role system for CogsGuard agents. The system allows agent roles to evolve over
time based on game performance, creating new role variations through sampling, recombination, and mutation.

## Source files

| File                                                     | Purpose                                                        |
| -------------------------------------------------------- | -------------------------------------------------------------- |
| `policy/evolution/cogsguard/evolution.py`                | Data model, evolutionary operators, fitness tracking           |
| `policy/evolution/cogsguard/evolutionary_coordinator.py` | Lifecycle coordination, role assignment, generation management |
| `policy/scripted_agent/cogsguard/behavior_hooks.py`      | Binds behavior names to real role implementations              |
| `policy/scripted_agent/cogsguard/policy.py`              | URI flag parsing, coordinator wiring, vibe selection           |

All paths relative to `cogames-agents/src/cogames_agents/`.

---

## 1. Data model

```
RoleCatalog
 ├── behaviors: list[BehaviorDef]     # all registered behaviors
 ├── roles: list[RoleDef]             # all registered roles
 ├── next_role_id: int
 └── next_name_id: int

BehaviorDef
 ├── id: int                          # index in catalog.behaviors
 ├── name: str                        # e.g. "mine_resource"
 ├── source: BehaviorSource           # MINER | SCOUT | ALIGNER | SCRAMBLER | COMMON
 ├── can_start(state) -> bool
 ├── act(state) -> Action
 ├── should_terminate(state) -> bool
 ├── interruptible: bool
 ├── fitness: float                   # EMA fitness score
 ├── games: int
 └── uses: int

RoleDef
 ├── id: int                          # index in catalog.roles
 ├── name: str                        # auto-generated or manual
 ├── tiers: list[RoleTier]            # priority-ordered behavior tiers
 ├── origin: str                      # "manual" | "sampled" | "recombined" | "mutated"
 ├── locked_name: bool                # frozen once fitness >= 0.7
 ├── fitness: float                   # EMA fitness score
 ├── games: int
 └── wins: int

RoleTier
 ├── behavior_ids: list[int]          # references into catalog.behaviors
 ├── weights: list[float]             # optional, for weighted selection
 └── selection: TierSelection         # FIXED | SHUFFLE | WEIGHTED
```

### Relationships

```
RoleCatalog ──1:N──> BehaviorDef
RoleCatalog ──1:N──> RoleDef
RoleDef     ──1:N──> RoleTier
RoleTier    ──*:*──> BehaviorDef  (via behavior_ids)
```

### Default behaviors (seeded by coordinator)

| Name                | Source    | Description             |
| ------------------- | --------- | ----------------------- |
| explore             | COMMON    | General exploration     |
| recharge            | COMMON    | Energy recharge         |
| mine_resource       | MINER     | Gather from extractor   |
| deposit_resource    | MINER     | Deposit at station      |
| find_extractor      | MINER     | Locate extractor        |
| discover_stations   | SCOUT     | Find stations           |
| discover_extractors | SCOUT     | Find extractors         |
| discover_junctions  | SCOUT     | Find junctions          |
| get_hearts          | ALIGNER   | Acquire hearts          |
| get_influence       | ALIGNER   | Acquire influence       |
| align_junction      | ALIGNER   | Align a junction        |
| scramble_junction   | SCRAMBLER | Scramble enemy junction |
| find_enemy_junction | SCRAMBLER | Locate enemy junction   |

### Default roles (seeded by coordinator)

| Role          | Tier 1                    | Tier 2              | Tier 3             | Tier 4  |
| ------------- | ------------------------- | ------------------- | ------------------ | ------- |
| BaseMiner     | deposit_resource          | mine_resource       | find_extractor     | explore |
| BaseScout     | discover_stations         | discover_extractors | discover_junctions | explore |
| BaseAligner   | get_hearts, get_influence | align_junction      | explore            | -       |
| BaseScrambler | get_hearts                | find_enemy_junction | scramble_junction  | explore |

---

## 2. Evolutionary loop lifecycle

```
┌─────────────────────────────────────────────────────────┐
│                 EvolutionaryRoleCoordinator              │
│                                                         │
│  __post_init__()                                        │
│    ├── _seed_default_behaviors()  (13 behaviors)        │
│    └── _seed_initial_roles()      (4 base roles)        │
│                                                         │
│  ┌──── GAME LOOP ────────────────────────────────────┐  │
│  │                                                    │  │
│  │  assign_role(agent_id, step)                       │  │
│  │    └── pick_role_id_weighted() → RoleDef           │  │
│  │                                                    │  │
│  │  choose_vibe(agent_id, step)                       │  │
│  │    ├── assign_role()                               │  │
│  │    └── map_role_to_vibe() → "miner"|"scout"|...    │  │
│  │                                                    │  │
│  │  get_role_behaviors(agent_id)                      │  │
│  │    └── materialize_role_behaviors()                │  │
│  │        └── resolve_tier_order() per tier           │  │
│  │                                                    │  │
│  │  record_agent_performance(agent_id, score, won)    │  │
│  │    └── record_role_score() → EMA update            │  │
│  │                                                    │  │
│  │  end_game(won)                                     │  │
│  │    ├── games_this_generation++                     │  │
│  │    └── if games >= games_per_generation:           │  │
│  │        └── _evolve_generation()                    │  │
│  │                                                    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                         │
│  _evolve_generation()                                   │
│    ├── generation++                                     │
│    ├── sort roles by fitness (descending)               │
│    ├── keep top 50% as survivors                        │
│    ├── fill remaining slots:                            │
│    │   ├── select 2 parents (fitness-weighted)          │
│    │   ├── recombine_roles(parent1, parent2)            │
│    │   └── mutate_role(child)                           │
│    ├── 10% chance: sample_role() for diversity          │
│    └── clear agent_assignments                          │
└─────────────────────────────────────────────────────────┘
```

### Generation cadence

The coordinator advances one generation every `games_per_generation` games (default 10). At each generation boundary:

1. Roles are ranked by fitness.
2. The bottom 50% are culled.
3. Offspring are created via crossover + mutation to refill the population.
4. A 10% random injection of a fully-sampled role maintains diversity.
5. All agent-role assignments are cleared so agents get new roles next game.

---

## 3. Fitness tracking mechanics

### EMA update formula

Both behaviors and roles use exponential moving average (EMA) for fitness:

```
if games == 1:
    fitness = score
else:
    fitness = fitness * (1 - alpha) + score * alpha
```

Default `alpha = 0.2`, configurable via `EvolutionConfig.fitness_alpha`.

### Selection weights

| Entity      | No games                      | Has games                  |
| ----------- | ----------------------------- | -------------------------- |
| BehaviorDef | weight = 1.0 (explore new)    | weight = max(0.1, fitness) |
| RoleDef     | weight = 0.1 (slight explore) | weight = max(0.1, fitness) |

Untested behaviors get full weight (1.0) to encourage exploration. Untested roles get low weight (0.1) since they
already exist in the catalog.

### Name locking

When a role's fitness reaches `lock_fitness_threshold` (default 0.7), its name is frozen (`locked_name = True`). This
preserves identity for high-performing roles across mutations.

---

## 4. Evolutionary operators

### sample_role

Creates a new role from scratch:

- Picks a random tier count in `[min_tiers, max_tiers]` (default 2-4).
- For each tier, picks `[min_tier_size, max_tier_size]` behaviors (default 1-3), weighted by behavior fitness.
- Total behaviors capped at `max_behaviors_per_role` (default 12).
- Each tier gets a random selection mode (50/50 FIXED vs SHUFFLE).
- Origin set to `"sampled"`.

### recombine_roles (crossover)

Creates a child role from two parents:

- Pick random cut points `cut_left` in parent1, `cut_right` in parent2.
- Child tiers = parent1.tiers[:cut_left] + parent2.tiers[cut_right:].
- Guarantees at least one tier.
- Origin set to `"recombined"`.

### mutate_role (point mutation)

Applies mutations to a copy of a role:

- Per tier, with probability `mutation_rate` (default 0.15): replace one random behavior ID with another random behavior
  from the catalog.
- Per tier, with probability `mutation_rate * 0.5`: flip selection mode between FIXED and SHUFFLE.
- Preserves fitness/games/wins from the original.
- Origin set to `"mutated"`.

### materialize_role_behaviors

Converts a `RoleDef` into an ordered `list[BehaviorDef]` for execution:

- Iterates tiers in priority order.
- Resolves each tier's behavior order based on its `TierSelection` mode.
- Returns actual `BehaviorDef` objects ready for execution.

---

## 5. Enabling evolution via URI params

Evolution is toggled on through policy URI parameters. Any of these flags enable it:

```
evolution=1
evolutionary=1
evolve=1
```

Values `1`, `true`, `yes`, and `on` (case-insensitive) are all accepted.

Example URI:

```
metta://policy/role?evolution=1&miner=4&scrambler=2
```

### How the flag flows

1. `CogsguardPolicy.__init__` parses the URI params via `_parse_flag()`.
2. If any evolution flag is truthy, `_use_evolutionary_roles` is set to `True` and an `EvolutionaryRoleCoordinator` is
   created.
3. On first policy execution, behavior hooks are wired from `build_cogsguard_behavior_hooks()`.
4. `_choose_role_vibe()` checks the flag:
   - If evolution is enabled: delegates to `coordinator.choose_vibe(agent_id, step)`.
   - Otherwise: falls back to `SmartRoleCoordinator.choose_role()` or random selection.

---

## 6. Current gaps

### No episode trigger wiring

`record_agent_performance()` and `end_game()` exist on the coordinator but are **never called** from the policy. Fitness
stays at initial defaults (0.0) and selection is effectively uniform random.

### Evolved roles don't drive behavior

Roles are mapped back to base vibes (`miner`, `scout`, `aligner`, `scrambler`) via `map_role_to_vibe()`, which checks
which `BehaviorSource` dominates the role. This means recombination and mutation do not actually change per-step action
ordering. A recombined role with miner + scout behaviors still just maps to whichever source has the most behaviors.

### No persistence

The `RoleCatalog` is not serialized or loaded. Evolution resets every run. The tribal-village implementation writes
`data/role_history.json` for continuity across runs; no equivalent exists here.

### No behavior injection

The tribal-village system has `injectBehavior` (35% chance to inject an extra behavior into the first tier of a hybrid
role). This is not implemented in the Python port.

---

## 7. Extending with new behaviors

To add a new behavior to the evolutionary system:

1. **Register the behavior** in `EvolutionaryRoleCoordinator._seed_default_behaviors()`:

   ```python
   self.catalog.add_behavior(
       name="new_behavior_name",
       source=BehaviorSource.MINER,  # or other source
       can_start=_always_true,
       act=self._behavior_act("new_behavior_name"),
       should_terminate=_always_false,
       interruptible=True,
   )
   ```

2. **Add a behavior hook** in `build_cogsguard_behavior_hooks()`:

   ```python
   return {
       ...
       "new_behavior_name": some_role_impl._do_new_thing,
   }
   ```

3. **Optionally add to a base role** in `_seed_initial_roles()` by including the behavior ID in the appropriate tier.

The evolution system will automatically include the new behavior in sampled roles and mutations. No changes to the
evolutionary operators are needed.

---

## 8. Comparison to tribal-village Nim implementation

| Aspect                 | tribal-village (Nim)                                                                    | cogames-agents (Python)                                                        |
| ---------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **Data model**         | BehaviorDef wraps OptionDef; RoleDef with kind enum (Gatherer/Builder/Fighter/Scripted) | BehaviorDef with source enum; RoleDef without kind                             |
| **Tier model**         | RoleTier with fixed/shuffle/weighted selection                                          | Identical: RoleTier with FIXED/SHUFFLE/WEIGHTED                                |
| **Catalog**            | RoleCatalog with serialization to `role_history.json`                                   | RoleCatalog without serialization                                              |
| **Sampling**           | `sampleRole`: 2-4 tiers, 1-3 behaviors, fitness-weighted                                | `sample_role`: same parameters, same logic                                     |
| **Crossover**          | `recombineRoles`: random cut points on tier lists                                       | `recombine_roles`: same algorithm                                              |
| **Mutation**           | `mutateRole`: replace behaviors, flip selection modes                                   | `mutate_role`: same algorithm, same rates                                      |
| **Fitness**            | EMA with alpha, scored at `ScriptedScoreStep` (5000)                                    | EMA with alpha, but scoring is not wired                                       |
| **Trigger**            | Temple spawn: two adjacent agents + altar heart                                         | Coordinator-driven: games-per-generation cadence                               |
| **Hybrid flow**        | `processTempleHybridRequests` queues hybrids for newborn agents                         | No hybrid queue; offspring created during `_evolve_generation`                 |
| **Behavior injection** | `injectBehavior` (35% chance, first tier)                                               | Not implemented                                                                |
| **Role assignment**    | Pending hybrid roles assigned immediately; otherwise fitness-weighted pool              | Fitness-weighted selection only                                                |
| **Exploration**        | `ScriptedRoleExplorationChance` = 0.08, `ScriptedRoleMutationChance` = 0.25             | 10% random injection per generation                                            |
| **Persistence**        | `role_history.json` saved/loaded                                                        | None                                                                           |
| **Execution**          | Materialized into `OptionDef` sequences, run by `runOptions` with priority preemption   | `materialize_role_behaviors` exists but roles map to vibes, not behavior lists |
| **Name locking**       | `lockRoleNameIfFit` at threshold 0.7                                                    | Same: `lock_role_name_if_fit` at threshold 0.7                                 |

### Key architectural differences

1. **Trigger mechanism**: Nim uses an in-game event (temple spawn with two parents physically adjacent). Python uses a
   fixed cadence (every N games). The Nim approach ties evolution to gameplay; the Python approach is decoupled.

2. **Execution model**: Nim roles directly control agent behavior via option lists with priority-based preemption.
   Python roles currently only select a vibe string, losing the tier ordering that evolution produces.

3. **Population management**: Nim maintains a role pool separate from core roles, with explicit exploration vs
   exploitation chances. Python uses a flat catalog with generational culling (top 50% survive).

---

## Configuration reference

`EvolutionConfig` fields:

| Field                  | Default | Description                         |
| ---------------------- | ------- | ----------------------------------- |
| min_tiers              | 2       | Minimum tiers when sampling a role  |
| max_tiers              | 4       | Maximum tiers when sampling a role  |
| min_tier_size          | 1       | Minimum behaviors per tier          |
| max_tier_size          | 3       | Maximum behaviors per tier          |
| mutation_rate          | 0.15    | Probability of mutating each tier   |
| lock_fitness_threshold | 0.7     | Fitness threshold to lock role name |
| max_behaviors_per_role | 12      | Cap on total behaviors per role     |
| fitness_alpha          | 0.2     | EMA smoothing factor                |

`EvolutionaryRoleCoordinator` fields:

| Field                | Default    | Description                             |
| -------------------- | ---------- | --------------------------------------- |
| num_agents           | (required) | Number of agents to coordinate          |
| games_per_generation | 10         | Games before evolving new roles         |
| rng                  | None       | Optional seeded RNG for reproducibility |
