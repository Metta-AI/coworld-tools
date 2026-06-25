# World Generation Notes

Date: 2026-01-19
Owner: Systems / Worldgen
Status: Active

## Overview
World generation is split across:
- `src/terrain.nim` for terrain/biome/river layout.
- `src/spawn.nim` for neutral structures, villages, and creature spawns.
- `src/connectivity.nim` for post-pass connectivity fixes.

This doc focuses on the parts that changed during recent Codex sessions:
central trading hub, river meander tuning, and guaranteed dual goblin hives.

## Resolved Start State and Gameplay Handoff
`newEnvironment()` builds the full map synchronously before gameplay starts.
The generation order in `src/spawn.nim` is:

1. `initState` resets grids, tint state, stockpiles, agent slots, and pooled effects.
2. `initTerrainAndBiomes` lays down base biome terrain, swamp water, the river,
   optional tree oases, elevation, ramps, cliffs, waterfalls, dungeon walls,
   city walls, border walls, and biome tint colors.
3. `initTradingHub` clears the center, paints the hub, extends roads/bridges,
   and adds the neutral castle, towers, walls, and hub buildings.
4. `initTeams` places each village start: altar, town center, houses, roads,
   starter resource buildings/nodes, team walls/doors, and initial villagers.
5. `generateVillagePonds` adds a local pond plus a shallow-water stream toward
   the nearest river when pathing allows.
6. `initNeutralStructures` adds goblin hives, huts, totems, goblin agents,
   spawners, and initial tumors.
7. `initResources` adds magma, wheat fields, trees, stone, gold, fish, relics,
   bushes, cacti, and stalagmites.
8. `initContestedZones` converts the central contest rings to fertile ground and
   seeds concentrated gold, stone, wheat, bushes, cows, and relics.
9. `initWildlife` adds ambient cows, bears, and wolf packs.
10. `initFinalize` runs `makeConnected()`, starts replay bookkeeping, and builds
    the initial spatial index.

The important handoff detail is that this all finishes before the first
rendered frame. The terrain/build pass and spawn/buildout phases are therefore
already complete by the time `tribalcog play` enters the live step loop.
That is the handoff point: worldgen is finished, then normal simulation begins.

## Central Trading Hub (neutral)
Implemented in the `tradingHub` block inside `src/spawn.nim`.

Key behaviors:
- Clears a centered square of size `TradingHubSize` and applies a fixed tint
  (`TradingHubTint`).
- Lays down a **cross-shaped road** through the hub center and extends each arm
  outward (bridges are placed if the road crosses water).
- Creates a **meandering wall ring** instead of a rigid box:
  - Walls are placed with a probability per step.
  - The ring “drifts” as it traces the hub perimeter.
  - Short **spur walls** are added inside the perimeter for organic shape.
  - A few walls are replaced with neutral guard towers.
- Populates the hub with a shuffled list of neutral buildings and **scattered
  extra structures** around the hub, while respecting road clearance.

Placement guardrails (via `canPlaceHubThing`):
- Never place on roads/bridges/water.
- Never block the main road cross.
- Avoid occupied or background-occupied tiles.

## River Generation and Meander Tuning
Implemented in `generateRiver()` in `src/terrain.nim`.

High-level flow:
1) **Main river** starts near the left edge and flows rightward.
2) A target Y is sampled; the river’s vertical velocity gently drifts toward it
   with occasional random perturbations.
3) The river’s Y is clamped to avoid borders and reserved village corners.
4) **Branches (tributaries)** optionally fork from the main river and terminate
   toward the top/bottom edges.
5) Bridges are placed across the main river and any tributary branches.

Recent tuning makes the river **less meandering** by reducing random vertical
velocity changes and jitter while preserving gentle curvature. If you need a
stronger effect, adjust the probability knobs in `generateRiver()`.

Constants to know:
- `RiverWidth` (in `src/terrain.nim`)
- Border and reserve spacing (`mapBorder`, corner reserve in `generateRiver()`)

## Goblin Hives (guaranteed two)
Goblin spawns are handled in `src/spawn.nim` under the goblin hive section.

Current behavior:
- `GoblinHiveCount = 2` ensures every map has **two** hives.
- Hive placement:
  - Avoids water.
  - Enforces minimum distance from village altars.
  - Enforces minimum distance between hives.
  - Requires a clear 5x5 area (HiveRadius 2) for surrounding structures.
- Each hive spawns its share of:
  - `GoblinHut`
  - `GoblinTotem`
  - goblin agents (team override + green tint)

This guarantees two distinct goblin clusters rather than a single concentrated
spawn.

## Dungeon Zones
Dungeon zones (`BiomeDungeonType`) are procedurally generated regions with wall
structures. Two layout types alternate:
- **Maze** (`DungeonMaze`): classic maze wall patterns.
- **Radial** (`DungeonRadial`): corridor-based radial layouts (mask is inverted).

Dungeon edges are softened with `ditherEdges` for organic blending.
Wildlife avoids dungeon biomes.

## Where to tweak
- **Hub density / shape**: `initTradingHub` in `src/spawn.nim`.
- **River meander**: `generateRiver()` in `src/terrain.nim`.
- **Goblin hive rules**: `initNeutralStructures` in `src/spawn.nim`.
- **Post-pass connectivity**: `makeConnected()` in `src/connectivity.nim` if
  map generation introduces disconnected traversable regions.
- **Dungeon zones**: `UseDungeonZones` and dungeon mask builders in `src/spawn.nim`.
