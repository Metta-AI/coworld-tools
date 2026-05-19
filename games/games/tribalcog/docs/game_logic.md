# Game Logic Overview

Date: 2026-01-28
Owner: Docs / Systems
Status: Active

## Purpose
This document describes how the Tribal Village simulation behaves each step, what agents can do,
what systems update automatically, and how the episode ends. It is a code-aligned summary of the
current gameplay rules.

Key implementation files:
- `src/step.nim` (per-step simulation)
- `src/spawn.nim` (map + initial entity placement)
- `src/types.nim` (constants, config, core data types)
- `src/items.nim` (item catalog)
- `src/colors.nim` (clippy tint + frozen tiles)

## Core Loop (per step)
The main loop is `proc step*(env, actions)` in `src/step.nim`.

Order of operations (high level):
1. Decay short-lived effects (combat/heal tints, shields).
2. Remove agents already at 0 HP so they cannot act this step.
3. Apply each alive agent's action in shuffled order (randomized each step for fairness).
4. Update world objects (building cooldowns, tower/castle attacks, spawners, wildlife movement).
5. Process tumor branching/spawning.
6. Resolve adjacency deaths for agents/predators touching tumors.
7. Apply tank auras, monk healing auras, and their tints.
8. Remove any agents killed during the step.
9. Respawn dead agents at their altar if hearts and pop-cap allow it; process temple hybrid spawns.
10. Apply per-step survival penalty.
11. Recompute tint overlays (lanterns, tumors, etc.).
12. End episode if max steps reached or all agents are done.

## Map and Terrain
- Map size is derived from `MapWidth`/`MapHeight` in `src/types.nim`.
- Procedural terrain includes rivers/bridges, cliffs/ramps, biomes, and resource clusters.
- Roads can speed movement; fertile tiles enable planting/growth.
- Frozen tiles: a tile is frozen when its combined tint matches the clippy color threshold
  (`src/colors.nim`). Frozen tiles and things on them are non-interactable.

## Teams and Agents
- 8 teams, 125 agent slots each (1000 total), plus 6 goblin agents = 1006 total slots.
  Only 6 are active per team at spawn; the rest start dormant and can respawn later.
- Each agent has: position, orientation, HP/max HP, unit class, inventory, home altar, stance, and movement debt.
- Base unit classes: villager, man-at-arms, archer, scout, knight, monk, battering ram,
  mangonel, trebuchet, boat, trade cog, and goblin.
- Castle unique units (one per civilization/team): samurai, longbowman, cataphract, woad raider,
  teutonic knight, huskarl, mameluke, janissary, king.
- Unit upgrade tiers: long swordsman, champion (infantry); light cavalry, hussar (cavalry);
  crossbowman, arbalester (archer).
- Naval combat units: galley, fire ship.
- Additional siege: scorpion (anti-infantry ballista).

## Inventory and Stockpiles
- Each agent carries a small inventory (see `MapObjectAgentMaxInventory`).
- Team stockpiles track shared resources: food, wood, stone, gold, water.
- Resources are gathered from nodes (trees, wheat, stone, gold, fish, plants, etc.).
- Corpses and skeletons can store loot and be harvested.

## Actions
Action space is discrete: `verb * 28 + argument` (11 verbs x 28 arguments = 308 total actions).

Verbs:
- **noop**: do nothing.
- **move**: step in a direction; blocked by water, cliffs, doors, or occupied tiles.
  Roads and cavalry classes can move 2 tiles if space allows.
- **attack**: directional attack with class-specific patterns and ranges.
  - Archers are ranged; scouts/rams have short range; mangonel has AoE.
  - Spears extend melee attacks and consume spear charges.
  - Monks heal allies; against enemies they can convert if pop-cap allows.
- **use/craft**: interact with the tile or thing in front (harvest resources, craft at stations,
  heal with bread, smelt bars at magma, trade at market, etc.).
- **swap**: exchange positions with adjacent teammate.
- **give**: pass items to adjacent teammate.
- **plant lantern**: place a lantern that provides friendly tint and territory control.
- **plant resource**: plant wheat/tree (requires inputs).
- **build**: place structures from recipes, spending inventory or stockpile resources.
- **orient**: change facing without moving.

## Buildings and Production
- Town centers, houses, and other buildings provide population cap.
- Production buildings (oven, loom, blacksmith, etc.) craft items from inputs.
- Markets convert carried goods into team stockpiles using configured ratios.
- Altars store hearts; bars can be converted into hearts at altars.
- Guard towers and castles auto-attack nearby enemies and tumors.
- Mills periodically fertilize nearby tiles.

### Production Queues and Training
- Buildings with training capability maintain a **production queue** (batch training).
- Each unit type has a per-unit **training time**; a progress bar tracks completion.
- **Rally points** can be set on production buildings; newly trained units move toward the rally point.
- Batch training allows queuing multiple units for sequential production.

### Garrisoning
- Units can **garrison** inside buildings (Town Centers, Castles, etc.).
- Town Center garrison provides a **defensive bonus** to garrisoned units.
- Garrisoned units are removed from the map until un-garrisoned.

### Technology and Upgrades
- **Blacksmith**: Provides named upgrade progression for unit attack/armor stats (AoE2-style Forging → Iron Casting → Blast Furnace, etc.).
- **University**: Researches building upgrades (Ballistics, Murder Holes, etc.).
- **Castle unique technologies**: Each civilization has unique techs available at the Castle.
- **Unit upgrades and promotions**: Units can be upgraded along promotion chains (e.g., Scout → Light Cavalry → Hussar).

## Population and Respawning
- Dead agents can respawn near their home altar if the altar has hearts and the team is under
  its population cap.
- Temples can spawn a new villager if two adjacent teammates are present and a heart is spent.

## Threats and NPCs
- **Tumors (clippy):** spawned by spawners; they branch and spread clippy tint, freezing tiles.
  Agents or predators adjacent to tumors can die with a probability.
- **Wildlife:** bears and wolves roam and attack; cows wander in herds and can be harvested.
- **Goblins:** spawn from hives and act as a hostile faction.

## Unit Commands
- **Attack-move**: Military units can be issued an attack-move command; they move toward a target
  and engage any enemy encountered along the path.
- **Patrol**: Military units can patrol between positions, automatically engaging enemies in range.
- **Unit stances**: Combat behavior modes that control engagement rules (aggressive, defensive, stand ground, etc.).
- **Control groups**: Units can be assigned to numbered control groups (Ctrl+1-9) for quick selection and hotkey access.
- **Idle villager detection**: The UI highlights idle villagers with an indicator for quick task assignment.

## Victory Conditions
Multiple victory modes are supported (configurable per game). See [Victory Conditions](victory_conditions.md) for detailed mechanics, countdown durations, and implementation references.

- **Conquest**: Eliminate all enemy units and buildings. Rewards are applied for total elimination.
- **Wonder**: Build a Wonder structure and defend it for 600 steps. The countdown starts
  when the Wonder is **completed**, not when placement begins.
- **Relic**: Collect all 18 relics and hold them in Monasteries for 200 steps. Destroying a Monastery releases held relics.
- **King of the Hill**: Control the central ControlPoint for 300 consecutive steps (most units within 5-tile radius).
- **Regicide**: Each team has a King unit; the game ends when only one team's King survives.

## Rewards and Episode End
- Rewards are configured in `EnvironmentConfig` (`src/types.nim`): ore, bar, heart, tumor kill,
  survival penalty, death penalty, etc.
- Episode ends at `maxSteps`, victory condition met, or if all agents are terminated/truncated.
- At episode end, territory scoring and altar rewards are applied.

## Reference Pointers
- Per-step behavior: `src/step.nim`
- Spawn rules: `src/spawn.nim`
- Combat overlays and bonuses: `src/combat.nim`
- Items/inventory: `src/items.nim`
- Terrain/biomes: `src/terrain.nim` and `src/biome.nim`
- Victory conditions: [Victory Conditions](victory_conditions.md) and `src/step.nim:783-980`
