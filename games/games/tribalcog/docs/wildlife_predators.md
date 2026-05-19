# Wildlife and Predators

Date: 2026-01-19
Owner: Design / Systems
Status: Active

## Entities
Neutral wildlife lives in the main simulation loop as `ThingKind` values:
- Cow (prey)
- Bear (predator)
- Wolf (predator)

Key constants live in `src/types.nim`:
- Counts: `MapRoomObjectsCows`, `MapRoomObjectsBears`, `MapRoomObjectsWolves`
- Bear stats: `BearMaxHp`, `BearAttackDamage`, `BearAggroRadius`
- Wolf stats: `WolfMaxHp`, `WolfAttackDamage`, `WolfPackMinSize`, `WolfPackMaxSize`,
  `WolfPackAggroRadius`, `WolfPackCohesionRadius`

## Spawning
Spawn logic is in `src/spawn.nim`:
- **Cows** spawn in herds (5-10). Each cow gets a `herdId` so the step loop can track
  herd centers and drift.
- **Bears** spawn as solitary predators.
- **Wolves** spawn in packs (3-5) and each wolf gets a shared `packId`. The first
  wolf in each pack is the `isPackLeader`. Pack leaders are tracked per pack.
- All wildlife avoids `BiomeDungeonType` and requires open terrain (`Empty`).

## Movement and Group Behavior
The main behavior loop is in `src/step.nim`:
- **Cows**
  - Herd center is computed each step.
  - Herds drift between corner targets and away from borders.
  - Individual cows follow the herd drift with light random wandering.
- **Wolves**
  - Pack centers are computed each step.
  - Packs hunt nearby tumors or agents within `WolfPackAggroRadius` (7).
  - Wolves keep cohesion within `WolfPackCohesionRadius` (3): if a wolf is far from the
    pack center, it returns to the center.
  - When the pack leader is killed, surviving wolves enter a `scatteredSteps` state
    (`ScatteredDuration` = 10) with increased random movement (`WolfScatteredMoveChance` = 0.4).
- **Bears**
  - Solitary hunter using `BearAggroRadius`.
  - Chases the nearest tumor or agent in range; otherwise wanders.

All three use a simple cardinal-step movement that respects doors, blocked terrain, and
occupied tiles.

## Predation and Combat
Predator attacks happen in `src/step.nim`:
- Bears and wolves check adjacent tiles each step.
- If adjacent to an **active tumor**, they remove it first.
- If adjacent to an **agent**, they apply damage with their attack stat.

Agents can attack wildlife via the normal attack action (`src/step.nim`):
- `Cow`, `Bear`, and `Wolf` are valid attack targets.
- A successful attack yields `ItemMeat` and removes the wildlife.
- If the resource node has extra meat, a `Corpse` is spawned with remaining meat.

## AI Integration
Scripted AI exposes predator cleanup behaviors:
- `findNearestPredator` and predator cull options live in `src/scripted/options.nim`.
- Fighters and gatherers can choose predator cull behaviors when conditions are safe.

## Observation and Rendering
- Observation layers include `ThingCowLayer`, `ThingBearLayer`, and `ThingWolfLayer`.
- FFI tint colors for cows/bears/wolves are defined in `src/ffi.nim`.
- Dedicated sprites exist for all three wildlife types in `data/oriented/` (bear, wolf, cow).
