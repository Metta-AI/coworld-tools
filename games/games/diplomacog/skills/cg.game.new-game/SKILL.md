---
name: cg.game.new-game
description:
  Use when creating a new mettagrid game from scratch and you need the design-first workflow that writes the rules
  contract, checks engine fit, and hands a clean build plan to `cg.game.build-game`.
---

# New Game

## Overview

`cg.game.new-game` is the design-first entrypoint for the `cg.game` suite. Use it when the game does not exist yet and
the main risk is choosing mechanics, engine mappings, or variant cuts that do not fit mettagrid. The outputs of this
skill are a written rules contract, a dependency-ordered variant table, and a clean handoff into `cg.game.build-game`.

**Announce at start:** "I'm using cg.game.new-game: I'll design the game with you first, map it to engine capabilities,
agree on a variant tree, then build and test each layer incrementally."

## Choose the Entrypoint

| If you need                                      | Start with             |
| ------------------------------------------------ | ---------------------- |
| A net-new mettagrid game                         | `cg.game.new-game`     |
| An existing game fixed or overhauled             | `cg.game.build-game`   |
| A player or policy improved for an existing game | `cg.game.build-player` |

## Phase 1: Design Contract

Collaborate with the user to define the game. Write the contract down, preferably in the game-local `rules.md`,
covering:

1. **Game concept.** What is the game? What's the core loop? What makes it interesting for RL training?
2. **Win/lose conditions.** How do episodes end? What reward signals drive learning?
3. **Agent actions.** What can agents do? Movement, placement, interaction, role-switching.
4. **Game objects.** What entities exist on the grid? How do they behave?
5. **Map structure.** What does the grid look like? What spatial patterns matter?

Present the contract section by section until the game loop is explicit enough that a different engineer could implement
it without guessing.

### Engine Capability Check

For each mechanic in your contract, identify the engine primitive it maps to. Read
`packages/mettagrid/docs/capabilities.md` first -- it lists what's available and (importantly) what's deliberately not.
Also read a few nearby game examples: `overcogged` for fixed-map cooperative flows, `hunger` or `territories` for
procedural and role-heavy patterns, and `cogs_vs_clips` for larger multi-system composition.

Common mismatches that have wrecked prior games:

- **Episode termination.** No primitive exists; `max_steps` only. Reframe "episode ends when X" as "X grants a large
  reward; episode runs to max_steps." Don't write rules.md with terminator language.
- **Directional / line-of-sight effects.** `isNear` is Euclidean with no occlusion. `RaycastQuery` is what you want for
  blast arms, beams, sightlines, etc. Don't approximate with `isNear`.
- **GridObject state machines.** `on_tick` is agent-only; use EventConfig for object countdowns / cleanup.
- **Object removal.** No "remove object" mutation. Use `ResourceTransferMutation` with `remove_source_when_empty=True`.
- **AOE for one-shot effects.** AOE is persistent aura-like effects only; `apply_fixed` only hits agents, never
  GridObjects. Use events + RaycastSpawnMutation for explosions.

Flag any mechanic that has no clear primitive. If it requires C++, scope it as an isolated additive extension (new
mutation type, new filter type) -- not an architectural change.

Plan these deliverables during design, not as an afterthought:

- **Recipe entrypoint:** `recipes/game/<name>.py` with both `play()` and `train()` functions. Without `play()`, the game
  can't be run via `./tools/run.py <game>.play`. Without `train()`, agents can't be trained via
  `./tools/run.py <game>.train`. Plan both alongside the game, not after. Follow the pattern in
  `recipes/game/overcogged.py`: import `make_game` from the game registry, build a `SimulationConfig`, return a
  `tools.PlayTool` (for play) or `tools.TrainTool` (for train). For cogames-based games, register via `register_game()`
  in the game module and ensure the module is imported at startup (add to `cogames/__init__.py`). The recipe MUST handle
  `policy_uri=None` gracefully — new games have no trained policy yet. The correct random policy URI is
  `"metta://policy/random"` (NOT the bare string `"random"`, which is treated as a file path and crashes). Either
  register a `policy_uri` in the `register()` call or default to `"metta://policy/random"` in the recipe. A recipe that
  crashes on `policy_uri=None` is not a working recipe. **Always test the recipe end-to-end** with
  `uv run ./tools/run.py <game>.play render=none max_steps=100` before claiming the game is playable — unit tests alone
  do not exercise the recipe path.
- **Vibe restriction:** Define a minimal vibe list with only game-relevant vibes (e.g.,
  `[Vibe("😐", "default"), Vibe("💣", "fire")]`). The default list has 150+ vibes, making the UI unusable.

- **Observation space:** The default `ObsConfig` automatically exposes all inventory resources (multi-token encoded) and
  all tags as observation features. The key design decision is ensuring game-critical state is stored as resources in
  `resource_names` (automatically observable) rather than in hidden engine state. For example, a power-up timer should
  be a resource on the agent, not a Python-side variable. Configure `GlobalObsConfig` options like `local_position=True`
  and `last_action_move=True` for additional spatial awareness. The observation window size (`width`/`height`, default
  13x13) determines how far agents can see — adjust for large maps.

Lock down a few implementation-sensitive decisions before handing off:

- Agent count fields: `CoGameMission` uses `num_cogs` (with `min_cogs`/`max_cogs` bounds), while `GameConfig` uses
  `num_agents`. Your mission's `create(num_agents, max_steps)` classmethod receives the caller's requested count — pass
  it as `num_cogs` to the mission constructor and then use `self.num_cogs` in `make_base_env()` to set
  `GameConfig(num_agents=...)`. Do not add a separate `num_agents` field on the mission — it shadows the inherited one.
- Interaction model: agents usually act by moving into objects and firing handlers rather than sharing cells with them.
- Inventory model: gear and carry slots should be explicit; `ResourceLimitsConfig.base/max` encode the dynamic capacity
  range. `base` is the capacity with no modifiers (not a floor on the resource value). `max` is the ceiling even with
  modifiers.
- Handler order: first match wins, so object interactions must be ordered intentionally.
- Agent identity: distinguish agents with `team_id` and tags, not by changing `name`.

## Phase 2: Variant Decomposition

Break the game into layers. Each variant adds one mechanic on top of the base game or a prior variant. Agree on:

1. **Base game:** The minimal playable version. Just enough to test the core loop.
2. **Variant table:** Each variant has a name, description, what it adds, and what it depends on.
3. **Implementation order:** Base first, then variants ordered by dependency. Independent variants can be built in any
   order.

The variant table is the contract. Don't start building until it's agreed upon.

## Design Outputs

Before leaving `cg.game.new-game`, make sure you have:

- A written rules contract with the base loop, objects, rewards, and map shape — committed as `rules.md` in the game
  directory, not just discussed.
- A variant table with names, dependencies, and implementation order — even if the base game has no variants, document
  the table with at least the base entry.
- The target package surfaces for the build phase. Decide which package the game belongs in:
  - **`packages/cogames/src/cogames/games/<game>/`** for games using the cogames `CoGameMission`/`CoGame` framework
    (missions, variants, eval missions). Register via `register_game()` in a `game/__init__.py` module AND add an import
    in `cogames/__init__.py` so the game is discoverable at runtime. Without the init import, `get_game("<name>")`
    silently fails — the `register_game()` call never executes. This was missed in 2 out of 3 test games.
  - **`metta/games/<game>/`** for games using the simpler `metta.games.games.register()` pattern. Register in
    `metta/games/games.py` with a guarded import.
  - **Standalone repo** for games developed outside the monorepo (e.g., tournament entries, external collaborators).
    These depend on `mettagrid` and optionally `cogames` as published packages. The recipe still lives in the consuming
    repo's `recipes/` directory.
  - In either case, plan the recipe entrypoint at `recipes/game/<name>.py` and tests alongside the game package.

## Phase 3: Shared Build Loop

Once the design contract and variant table are locked, switch to `cg.game.build-game` for the implementation loop:

1. Scaffold the game package, tests, and recipe surfaces from the agreed contract.
2. Run `cg.game.core-mechanics` and keep the base game playable, tested, and green in headless smoke before art or
   variants.
3. Run `cg.game.generate-assets` only after the base loop works, and verify atlas/render integration immediately.
4. Run `cg.game.variant-tree` only after the default game is stable, and prove the default/full paths still agree.
5. Finish with bop-it discipline: lint, focused tests, play smokes, diff review, and PR.

Keep this handoff explicit. `cg.game.new-game` owns blank-sheet design, capability mapping, and variant planning.
`cg.game.build-game` owns scaffold, implementation, asset integration, and overhaul.

## Common Pitfalls

These are things that consistently caused issues during game development:

### Tick Ordering

Events fire BEFORE actions and AOE each tick. If an event modifies a resource that an AOE filter checks, the AOE sees
the post-event value. Schedule multi-step lifecycles across events carefully: e.g., an event that sets hp=0 will cause
an AOE filter checking hp>=1 to fail on the same tick. Use separate events with ordered names to stagger effects.

### Event Execution Order

EventScheduler uses `std::map` (alphabetical by event name) with `std::stable_sort` by timestep. Events at the same
timestep fire in alphabetical name order — not Python dict insertion order. Name events with numeric prefixes to enforce
the correct order (e.g., `bomb_1_fuse_tick`, `bomb_2_explode`, `bomb_3_cleanup`).

### Mettascope Sprites

- **Agent sprites** go in `data/agents/` with lowercase direction suffixes: `<name>.n.png`, `<name>.s.png`, etc.
- **Object sprites** go in `data/objects/` at 64x64.
- **Vibe sprites** go in `data/vibe/` at 32x32.
- **Rebuild the atlas** after adding any sprite: `cd packages/mettagrid/nim/mettascope && nim c -r tools/gen_atlas.nim`
- **Verify visually** — check for "Sprite not found" warnings in mettascope output.

### Agent Naming and Teams

- All agents must have `name="agent"` for mettascope replay compatibility (it checks `typeName == "agent"`).
- Differentiate agent types by `team_id` and tags, not by name.
- Map chars use team color names: team 0 = `"agent.agent"` (alias) or `"agent.red"`, team 1 = `"agent.blue"`.

### GridObject Lifecycle

- `on_tick` is agent-only. Use EventConfig for GridObject state machines (countdowns, cleanup).
- `remove_source_when_empty` on `ResourceTransferMutation` removes objects when their inventory is fully depleted.
  `ResourceDeltaMutation` does NOT support removal. In event context (actor=target), use a self-transfer with
  `remove_source_when_empty=True` to trigger removal after zeroing resources.
- SpawnObjectMutation spawns at target_location (not actor location). The agent stays in place.

### Variant Registration

- `game.py` must import the variants module (e.g., `from .variants import VARIANTS as _VARIANTS`) or variant classes
  won't be registered in `CoGameMissionVariant._type_registry`. Without this import, `make_env()` silently falls back to
  a different game's variant with the same name.

### Variant-Added Inventory

When a variant adds new resources or objects, ensure those resources appear in `resource_names` on the base
`GameConfig`. If they're only added in the variant's `make_env()` override but not in the base config, the observation
encoder won't allocate tokens for them and agents will be blind to the new state. Add all resources the full variant
tree will ever use to the base config's `resource_names`, even if the base game doesn't use them yet.

### Testing

- **TDD for every new mechanic**, not just bug fixes. Before implementing a mechanic (blast radius, object removal,
  visual markers), write a test that exercises it and confirm it fails. Then implement and confirm it passes. This
  catches lifecycle issues (markers created and immediately destroyed), spatial bugs (diagonals hit when they shouldn't
  be), and timing issues (events firing in unexpected order).
- **Integration tests are mandatory** — config-level tests that validate structure (map dimensions, resource names,
  object counts) are necessary but not sufficient. Every game must have at least one test that instantiates a
  `Simulation` from the full game config, steps agents through the core mechanic (tag someone, place a bomb, push a
  box), and asserts on the resulting grid state via `sim.grid_objects()` and `sim.agent(i).inventory`. Config tests
  missed broken mechanics in 3 out of 3 test games. If a mechanic cannot be tested because it depends on a C++ extension
  that cannot be built, mark the test with `@pytest.mark.skipif` and document why — but still write the test.
- **Test what the player sees**, not just what the simulation computes. If explosions should be visible, assert that
  explosion objects exist in `sim.grid_objects()`. If destroyed crates should be walkable, test that movement succeeds.
  Headless smoke tests that only check "no crash" miss most gameplay bugs.
- **Run the game interactively** (`./tools/run.py <game>.play`) and verify mechanics yourself before claiming they work.
  Headless tests missed explosion markers being created and immediately destroyed (0 visible ticks) in the Bomber game.
- Use `make_game()` for integration tests, not minimal hand-built configs. Minimal configs miss tag registration, event
  context wiring, and variant module loading.
- Use `sim.grid_objects()` to verify object counts and state directly — don't use indirect proxies like
  agent-walking-through-cell.
- Write a failing test that reproduces a bug before fixing it. Verify it fails for the right reason.
- **Beware false-positive tests.** A test that asserts "no crash after N steps" passes for both working and broken
  mechanics. Always assert on specific grid state: object counts, agent inventory values, tag presence. If a mechanic
  creates explosion markers, assert `len([o for o in sim.grid_objects() if o.type == "explosion"]) > 0` at the right
  tick, not just that the simulation didn't crash.

### Pipeline-Split Discipline

When the game design spans both the skill (design contract) and the reference (`capabilities.md`), keep them in sync.
The skill owns design decisions, variant decomposition, and patterns. The reference owns primitive signatures and
constraints. If you discover a new engine limitation during implementation, update `capabilities.md` (or file a PR
against mettagrid) -- don't just add a workaround note in the skill.

### Common Mechanic Patterns

Study existing games for reusable patterns before inventing new ones:

- **Vibe-gated placement:** Agent switches vibe, then move spawns an object instead of walking. See
  `territories/variants/building.py` (wall building).
- **Timed object lifecycle:** Object has a countdown resource. EventConfig decrements each tick. When it reaches 0, a
  filter triggers an effect (removal, state change). See overcogged hub cooking.
- **Cooldown-based replenishment:** Agent resource depleted on action, replenished by event after a countdown resource
  ticks down to 0. Two events: one decrements cooldown, one replenishes when cooldown is empty.
- **Contact interaction (object):** Move handler with team/tag filters applies mutations when an agent walks onto a
  GridObject. Use `handlers` on `GridObjectConfig`. Filters gate on actor (the walking agent) and target (the object).
- **Contact interaction (agent-to-agent):** When agent A moves onto agent B, B's `on_use_handler` fires via the default
  move chain's on-use step (actor=A the mover, target=B the occupant). Use `actorHasTag()`/`hasTag()` filters to gate on
  roles. Mutations can modify both actor and target in the same handler — all filters evaluate before any mutations
  execute, so tag swaps are safe. Use `sharedTagPrefix("team")` to distinguish friend from foe. This requires the
  default move chain (no custom `MoveActionConfig.handlers`). See `territories/variants/mating.py` for a working
  example.
- **Tag/role transfer on contact:** For mechanics where contact transfers a role (tag, infection, "it" status), use
  `on_use_handler` with `actorHasTag("role")` filter and mutations: `removeTag("role", target=EntityTarget.ACTOR)`,
  `addTag("role", target=EntityTarget.TARGET)`. Both agents must have the handler defined.
- **Short-lived visual markers:** Spawn GridObjects with a `life` resource and a cleanup event that decrements and
  removes when empty. **Timing matters:** if the spawn event and cleanup event fire on the same tick (common when both
  are periodic), start with `life=2` so the cleanup decrements to 1 on the spawn tick, then to 0 next tick (1 visible
  tick). `life=1` results in 0 visible ticks. This depends on event naming — the spawn event must sort alphabetically
  before the cleanup event. Document this ordering dependency in the code. Use `ResourceTransferMutation` with
  `remove_source_when_empty=True` for the removal (not `ResourceDeltaMutation`, which does not support object removal).
- **Asymmetric agent initialization:** When agents start with different roles (e.g., one "it" agent and N-1 runners),
  build separate `AgentConfig` instances with different `tags` lists inside `make_base_env()`:
  `agents=[AgentConfig(tags=["it"] if i == 0 else [], ...) for i in range(N)]`. All dynamic tags used in
  `addTag`/`removeTag` mutations must also be declared in `GameConfig.tags` — omitting this causes a `ValueError` at
  build time. The `GameConfig.agents` list is per-agent, so index 0 can differ from the rest.
- **Per-tick conditional scoring:** Use `on_tick` handlers on `AgentConfig` with tag filters to award resources
  conditionally each tick. Example:
  `on_tick={"runner_score": Handler(filters=[isNot(actorHasTag("it"))], mutations=[updateActor({"survival_score": 1})])}`
  — only non-"it" agents accumulate score. Pair with `inventoryReward("survival_score", weight=1.0)` for the RL signal.
- **Directional blast / ray-based effects:** Use `RaycastQuery` as `target_query` for damage events and
  `RaycastSpawnMutation` to spawn visual markers along the ray path. Both take `directions` (default: 4 cardinal),
  `max_range`, and `blocker` filters (OR semantics — any match stops the ray). See bomber game for a complete example.
- **Destroy-and-replace:** No in-place mutation of object type exists. To "upgrade" or "transform" an object, remove it
  via `ResourceTransferMutation(remove_source_when_empty=True)` and spawn the replacement with `SpawnObjectMutation` in
  the same handler or event. The replacement spawns at `target_location`, so ordering within the handler matters —
  remove first, then spawn.
- **Upgradeable capacity (modifier-based caps):** Use `ResourceLimitsConfig.modifiers` to let inventory items raise
  another resource's cap dynamically. E.g., each `backpack` held adds 5 to `cargo` capacity:
  `ResourceLimitsConfig(base=5, max=20, resources=["cargo"], modifiers={"backpack": 5})`. The agent observes effective
  limits automatically.
- **Carry-placer stats:** When an agent carries an item and places it (vibe-gated placement), track placement counts via
  `StatsMutation` in the placement handler. Pair with `inventoryReward` on the carried resource for the RL signal and
  `logStatToGame` for analytics.
- **Vibe auto-reset:** After a vibe-gated action (placement, special move), reset the agent's vibe to `"default"` in the
  same handler chain using `ChangeVibeMutation(vibe_name="default", target=EntityTarget.ACTOR)`. Prevents agents from
  staying in a special vibe indefinitely.
- **Bodyblock / push mechanics:** Use `PushObjectMutation` in a move handler to push objects the agent walks into. The
  push direction is actor-to-target. If the destination is occupied or off-grid, `ctx.mutation_failed` is set — chain a
  fallback handler after the push attempt if the agent should stop instead of walking through.

## Rules Compliance Verification

After implementing all mechanics, do a line-by-line comparison of `rules.md` against `game.py`. For each rule in the
contract:

1. Identify the concrete code that implements it (handler, event, mutation, config).
2. If no code exists, the mechanic was silently dropped. Either implement it or update `rules.md` to reflect reality.
3. If the engine cannot support the mechanic (e.g., early episode termination — see the episode termination note in
   Engine Capability Check), update `rules.md` before implementation to avoid unimplementable promises.

This check caught 4 silently dropped mechanics in the Pac-Man test game: ghost respawn, win condition, lose condition,
and ghost vulnerability visuals. The implementer wrote rules.md, implemented the easy parts, and never went back to
verify completeness.

## Stop Conditions

- Do not start `cg.game.build-game` until the design contract is committed as `rules.md` in the game directory AND the
  variant table is written down. "Discussed but not written" does not count — the contract must be a file in the repo.
- Do not start implementing game mechanics until at least one failing test exists for the first mechanic (TDD). The test
  file must exist and run (even if it fails) before the mechanic code is written.
- Do not implement variants before the base game runs headless without errors.
- Do not generate art before mechanics are testable.
- Do not hand off to the user without running the game yourself first — both headless tests and interactive play.
- Do not silently downgrade mechanics when you hit an engine limitation. If the design calls for range-2 cross-shaped
  blast and the engine can only do range-1, tell the user: "This requires a C++ extension (e.g., RaycastQuery). Want me
  to implement it?" Don't quietly reduce the blast radius and move on.
- Do not assume engine capabilities — read existing game configs and the C++ implementation to verify what's possible.
- Do not use agent `name` for differentiation — use tags and team_id.
- Do not claim engine features work without reading the C++ implementation — the Python config layer may reference
  fields or behaviors that don't exist in the engine.
- Do not skip the recipe entrypoint. If the game has no `recipes/game/<name>.py` with a `play()` function, it cannot be
  run via `./tools/run.py`. Create it alongside the game package, not after.

## Exit Criteria

- The design contract and variant table are written and agreed.
- The shared `cg.game.build-game` loop is complete for the base game and all agreed variants.
- All relevant tests and headless smokes pass.
- Sprites render correctly in mettascope with no missing-asset warnings.
- The game is registered and playable via recipe.

## Integration

**Uses:** `cg.game.build-game`, `cg.game.core-mechanics`, `cg.game.generate-assets`, `cg.game.variant-tree`,
`cg.gen-sprite`

**Pairs with:** `cg.game.build-game`, `pr.summary`, `pr.check-ci`
