# Spawn and Placement Pipeline

Date: 2026-01-19
Owner: Docs / Systems
Status: Active

## Purpose
This document summarizes the spawn and placement flow in `src/spawn.nim` once the
terrain/biomes are established. It focuses on villages, structures, resources,
and creature spawns.

Related docs:
- `docs/terrain_biomes.md`
- `docs/world_generation.md`

Key implementation files:
- `src/spawn.nim`
- `src/placement.nim`
- `src/connectivity.nim`

## Core Data Structures
- **Terrain grid**: `env.terrain[x][y]` stores TerrainType (water, road, sand, etc.).
- **Blocking grid**: `env.grid` holds blocking Things (agents, walls, trees, buildings).
- **Background grid**: `env.backgroundGrid` holds non-blocking Things (doors, cliffs, docks).

Placement helpers (typical):
- `env.isSpawnable`, `env.canPlace`, `env.findEmptyPositionsAround`
- `tryPickEmptyPos`, `pickInteriorPos`, `placeResourceCluster`

## High-Level Spawn Order (spawn.nim `init()`)
1. **Initialize state** (`initState`)
   - Reset tints, grids, stockpiles, victory states, and per-step state.

2. **Terrain and biomes** (`initTerrainAndBiomes`)
   - Base terrain + biome zones, swamp water, river generation, tree oases.
   - Apply biome elevation (swamp=-1, snow=+1, base=0).
   - Apply cliff ramps with variable widths and cliff overlays.
   - City/dungeon wall structures, border walls.

3. **Trading hub** (`initTradingHub`)
   - Carve a neutral central hub, lock its tint, and extend cardinal roads.
   - Meandering wall ring, spur walls, neutral guard towers.
   - Castle at center, shuffled neutral buildings, scattered structures.

4. **Villages and teams** (`initTeams`)
   - Find village positions with spacing constraints, then shuffle and assign teams.
   - Clear village footprint, place altar, town center, resource buildings, houses.
   - Roads connect buildings to village center and extend outward.
   - Starting resource clusters (wood, food, stone, gold, magma) near each village.
   - Spawn six active agents per team; remaining 119 slots are dormant.
   - Place temple near map center.

5. **Hostile camps and spawners** (`initNeutralStructures`)
   - Place 2 goblin hives with surrounding huts/totems, then spawn goblin agents.
   - Place tumor spawners (one per team) with minimum distance from altars and other spawners.

6. **Resources** (`initResources`)
   - Magma in clusters of 3-4, wheat fields, tree groves/oases.
   - Stone and gold mine clusters, fish clusters, relics, bushes.
   - Biome-specific resources: cacti (desert), stalagmites (caves).

6b. **Control point** (if King of the Hill mode)
   - Place ControlPoint near map center.

7. **Wildlife** (`initWildlife`)
   - Cow herds (5-10), solitary bears, wolf packs (3-5) with pack leaders.

8. **Finalize** (`initFinalize`)
   - `makeConnected` ensures single connected walkable component.
   - Start replay, build initial spatial index.

## Tuning and Debugging
- Resource densities and cluster sizes live in `src/spawn.nim` constants.
- Placement and spacing helpers live in `src/placement.nim`.
- Connectivity issues can be diagnosed in `src/connectivity.nim`.
