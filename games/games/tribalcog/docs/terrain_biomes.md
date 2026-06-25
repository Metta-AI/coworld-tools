# Terrain, Biomes, Elevation, and Cliffs

Date: 2026-01-28
Owner: Design / Systems
Status: Active

## Generation pipeline (high level)
Map generation is staged so terrain, biomes, elevation, and cliffs stay
consistent:
1) `initTerrain` sets base terrain + biome types (no water yet).
2) `applyBiomeZones` overlays biome zones (forest/desert/caves/city/plains/snow/swamp).
3) `applySwampWater` paints water ponds inside swamp biomes.
4) `generateRiver` carves a river across the map.
5) Optional tree oases add extra water and trees.
6) `applyBiomeElevation` assigns elevation from biome types.
7) `applyCliffRamps` adds occasional road ramps across elevation changes.
8) `applyCliffs` places cliff overlays where higher tiles border lower tiles.

Primary files:
- `src/terrain.nim` (biomes, river, terrain masks)
- `src/spawn.nim` (elevation, ramps, cliffs)

## Biome zones and masks
Biome zones are blob-shaped regions distributed across the map. The zone
selection order is sequential by default (`UseSequentialBiomeZones = true`) so
most maps include every biome at least once. Each zone has its own mask, then
each biome applies additional rules:

- Forest / Caves / Plains
  - Uses a biome-specific mask to dither edges and add internal texture.
- Desert
  - Blends sand into the zone edges (low density), then applies dunes on top.
- City
  - Separate block and road masks. Blocks later become walls, roads remain
    passable.
- Snow / Swamp
  - Uses an inset fill so the biome core is solid and the edge ring is left as
    base biome. This supports clear elevation/cliff boundaries.
  - Swamp biomes include **Mud** terrain tiles (`mud.png` sprite) that slow
    movement.
  - Swamp zones may include **shallow water** ponds (via `applySwampWater`).

Zones do not freely overwrite each other. `canApplyBiome` only allows
overwriting if the current biome is base, empty, or the same biome. This keeps
overlaps stable and predictable.

## Elevation rules
Elevation is assigned per tile in `applyBiomeElevation` (`src/spawn.nim`):
- Swamp tiles: elevation `-1`
- Snow tiles: elevation `+1`
- All other tiles: elevation `0`
- Water and bridges are forced to elevation `0`

This means snow forms plateaus and swamp forms basins relative to base terrain.

## Cliffs and ramps
Cliffs are visual overlays generated from elevation deltas:
- `applyCliffs` scans each tile and compares neighbor elevations.
- If a neighbor is lower, a cliff edge or corner overlay is placed.
- Cardinal adjacency yields edge or inner-corner pieces.
- Diagonal-only gaps yield outer-corner pieces.

Cliff overlays are background Things (non-blocking). Movement is restricted by
`env.canTraverseElevation`, not by cliffs directly.

Ramps are implemented by converting adjacent tiles to `Road` in
`applyCliffRamps`:
- A 1-level step is allowed if either tile is a road.
- Larger elevation deltas are blocked.

Terrain enums include ramp tiles (`RampUp*`, `RampDown*`) but they are not
currently placed or checked. Roads are the ramp mechanic today.

## Rendering and assets (cliffs)
- Draw order is defined in `renderer.nim` (`CliffDrawOrder`) to keep edges clean.
- Observation layers exist for each cliff piece
  (`ThingCliffEdgeNLayer`, `ThingCliffCornerInNELayer`, etc.).
- Assets are registered in `registry.nim` and map to sprite keys like
  `cliff_edge_ew`, `cliff_edge_ns`, and `oriented/cliff_corner_*`.

## Movement and observation effects
`env.canTraverseElevation` allows movement on the same elevation, or a 1-step
height change when a road connects the tiles. The observation system masks tiles
above the agent's elevation via `ObscuredLayer` in `src/ffi.nim`
(`applyObscuredMask`).

## Connectivity pass
`makeConnected` in `src/connectivity.nim` runs after generation:
- Labels connected components on walkable tiles.
- Digs minimal paths through walls/terrain if multiple components exist.
- Uses `env.canTraverseElevation`, so ramps matter for connectivity.

## Terrain Movement Speed Modifiers
Different terrain types apply **movement speed modifiers** via `TerrainSpeedModifier`
in `src/terrain.nim`. Agents accumulate `movementDebt` when moving on slow terrain;
when debt >= 1.0, one move is skipped:
- **Shallow water**: 0.5x (50% slower wading)
- **Mud**: 0.7x (30% slower in swamp)
- **Snow**: 0.8x (20% slower)
- **Dune**: 0.85x (15% slower)
- **Sand**: 0.9x (10% slower)
- **Road**: 1.0x base, but cavalry (Scout/Knight) get 2-tile steps on roads
- **Deep water**: Impassable to non-boat units

## Water Depth Visualization
Water tiles have two visual depth levels:
- **Deep water**: Standard water tiles, impassable to land units.
- **Shallow water**: Lighter-colored water tiles near shorelines. Land units
  can wade through shallow water at reduced speed. Visually distinct from deep
  water for readability.

## Cliff Fall Damage
When a unit moves from a higher elevation tile to a lower one without using a
ramp (road), **cliff fall damage** is applied:
- Damage is proportional to the elevation difference.
- Ramps (road tiles at cliff boundaries) allow safe elevation changes.
- See `docs/combat.md` for details.

## Mud Terrain
Swamp biomes include **Mud** tiles:
- Rendered with a dedicated `mud.png` sprite.
- Movement through mud is slowed (0.7x speed modifier = 30% slower).
- Mud tiles are walkable and buildable.

## Ramp Sprites
Elevation transitions now have **visual ramp sprites** for each cardinal
direction (`RampUp*`, `RampDown*`), providing clearer visual feedback for
passable cliff edges.

## Biome-Specific Resource Bonuses
Each biome zone can apply a **resource gathering bonus** to agents collecting
resources within it (e.g., bonus wood in forests, bonus gold in deserts).

## Practical notes
- Zone masks are blob + dither based, so biome edges are intentionally irregular.
- Snow and swamp zones are contiguous in their cores, but can still inherit
  holes from the zone mask itself.
