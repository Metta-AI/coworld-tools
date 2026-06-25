# Terrain and Biomes Audit Report

Date: 2026-01-24
Owner: Engineering / Analysis
Status: Active
Issue: tv-6nhb
Investigator: polecat/immortan

## Executive Summary

The terrain and biome system is well-implemented with a staged generation pipeline. Most documented features are functional. Several opportunities exist for adding terrain variety and gameplay-impacting terrain mechanics.

## 1. Documented Features vs Implementation Status

### Generation Pipeline (All Implemented)

| Stage | Documentation | Status |
|-------|---------------|--------|
| `initTerrain` | Base terrain + biome types | Implemented in `terrain.nim:1172-1194` |
| `applyBiomeZones` | Overlay biome zones | Implemented in `terrain.nim:531-576` |
| `applySwampWater` | Swamp water ponds | Implemented in `terrain.nim:491-529` |
| `generateRiver` | River carving with bridges | Implemented in `terrain.nim:607-1170` |
| Tree oases | Water + tree clusters | Implemented in `spawn.nim:174-217` |
| `applyBiomeElevation` | Elevation from biome types | Implemented in `spawn.nim:218-231` |
| `applyCliffRamps` | Road ramps at elevation changes | Implemented in `spawn.nim:232-253` |
| `applyCliffs` | Cliff overlays | Implemented in `spawn.nim:254-331` |

### Biome Zones (All Implemented)

| Biome | Terrain Type | Mask Generator | Status |
|-------|--------------|----------------|--------|
| Forest | Grass | `buildBiomeForestMask` | Implemented |
| Desert | Sand/Dune | `buildBiomeDesertMask` | Implemented |
| Caves | Dune | `buildBiomeCavesMask` | Implemented |
| City | Grass/Road | `buildBiomeCityMasks` | Implemented |
| Plains | Grass | `buildBiomePlainsMask` | Implemented |
| Snow | Snow | `buildBiomeSnowMask` | Implemented |
| Swamp | Grass (with water) | `buildBiomeSwampMask` | Implemented |

### Elevation System (Implemented)

| Biome | Elevation | Status |
|-------|-----------|--------|
| Swamp | -1 (basin) | Implemented |
| Snow | +1 (plateau) | Implemented |
| All others | 0 | Implemented |
| Water/Bridge | 0 (forced) | Implemented |

### Cliff System (Implemented)

- Edge pieces: CliffEdgeN/E/S/W
- Inner corners: CliffCornerInNE/SE/SW/NW
- Outer corners: CliffCornerOutNE/SE/SW/NW
- All 12 cliff overlay types are registered and placed

### Partially Implemented Features

| Feature | Documentation | Status |
|---------|---------------|--------|
| Ramp tiles | `RampUp*`/`RampDown*` terrain types defined | **UNUSED** - Roads serve as ramps |
| Dungeon biome | Mentioned as `BiomeDungeonType` | Implemented but not in zone cycle |
| Sequential biome zones | `UseSequentialBiomeZones = true` mentioned | **NOT FOUND** - constant doesn't exist |

## 2. Identified Gaps

### Missing Constants/Features
1. **`UseSequentialBiomeZones`** - The documentation mentions this constant but it doesn't exist in the codebase. The current implementation uses sequential zone selection anyway (via `kinds[idx mod kinds.len]`).

2. **Ramp Tiles** - The terrain types `RampUpN/S/W/E` and `RampDownN/S/W/E` exist in the enum but are never placed. Roads are used as the ramp mechanic instead.

3. **Dungeon in Biome Cycle** - Dungeons are handled separately via `UseDungeonZones` rather than being part of the biome zone cycle. This is intentional design.

## 3. Improvement Recommendations

### High Priority (Gameplay Impact)

#### 3.1 Add Terrain Movement Modifiers
Currently all walkable terrain has equal movement cost. Add terrain-based movement speed modifiers:

```nim
# Proposed in environment.nim or movement.nim
const TerrainSpeedModifiers* = {
  Snow: 0.8,        # 20% slower in snow
  Sand: 0.9,        # 10% slower in sand
  Road: 1.2,        # 20% faster on roads
  Swamp: 0.7,       # 30% slower in swamp (currently uses Grass)
  Dune: 0.85,       # 15% slower on dunes
}.toTable
```

This would make terrain choices strategically meaningful.

#### 3.2 Implement Visual Ramp Tiles
The `RampUp*`/`RampDown*` terrain types exist but aren't used. Implementing visual ramps would:
- Provide clearer visual feedback for elevation transitions
- Allow different ramp widths (narrow mountain pass vs wide road)
- Enable blocking diagonal movement on ramps

#### 3.3 Add Biome-Specific Resource Bonuses
Different biomes could provide gathering bonuses:

| Biome | Bonus |
|-------|-------|
| Forest | +20% wood from trees |
| Plains | +20% food from wheat |
| Caves | +20% stone from rocks |
| Snow | +20% gold from mines |
| Desert | +10% all resources (oasis effect near water) |

### Medium Priority (Visual/Variety)

#### 3.4 Add Transitional Terrain Types
Create smooth transitions between biomes:
- `GrassSand` - Grass/desert border
- `GrassSnow` - Grass/snow border
- `MuddyGrass` - Grass/swamp border

Currently transitions are handled by mask dithering which works but could be enhanced.

#### 3.5 Add Weather Effects by Biome
Different biomes could trigger weather overlays:

| Biome | Weather | Effect |
|-------|---------|--------|
| Snow | Snowfall | Reduced vision range |
| Desert | Sandstorm | Reduced vision + movement |
| Swamp | Fog | Heavily reduced vision |
| Forest | Rain | Slight vision reduction |

#### 3.6 Cave Underground Mechanic
Caves could have an "underground" layer where:
- Entering cave tiles moves to underground
- Underground has different visibility rules
- Resource deposits are richer underground
- Requires torch items for navigation

### Lower Priority (Polish)

#### 3.7 River Flow Direction
Rivers are currently static water. Adding flow direction could enable:
- Boats/rafts that move faster downstream
- Fish spawning patterns based on flow
- Visual water current effects

#### 3.8 Seasonal Terrain Changes
Implement seasonal cycle affecting terrain:
- Winter: All grass becomes snow, water freezes
- Spring: Snow melts, rivers flood
- Summer: Normal state
- Autumn: Forest terrain gets fall colors, reduced food

#### 3.9 Height-Based Temperature
Use elevation for temperature effects:
- Higher elevation = colder = snow terrain appears
- Lower elevation = warmer = more vegetation
- Could affect unit stamina/health

## 4. Implementation Notes

### Current Architecture Strengths
1. **Staged Pipeline** - Clean separation of generation stages allows easy insertion of new steps
2. **Mask-Based Generation** - Biome masks are composable and extensible
3. **Zone System** - `evenlyDistributedZones` provides good spatial distribution
4. **Blob Generation** - `buildZoneBlobMask` creates natural-looking shapes

### Files to Modify for Improvements

| Improvement | Primary File | Secondary Files |
|-------------|--------------|-----------------|
| Movement modifiers | `environment.nim` | `types.nim`, `ffi.nim` |
| Visual ramps | `spawn.nim` | `terrain.nim`, `registry.nim` |
| Resource bonuses | `environment.nim` | `actions.nim` |
| Transition terrain | `terrain.nim` | `biome.nim` |
| Weather effects | New `weather.nim` | `renderer.nim`, `ffi.nim` |
| Cave underground | `spawn.nim` | `environment.nim`, `ffi.nim` |

## 5. Quick Wins

These improvements require minimal code changes:

1. **Add `BiomeSwampTerrain`** - Change from `Grass` to a distinct `Mud` terrain type for visual clarity

2. **Expose biome in observations** - Currently agents can't see biome type in their observations, limiting strategic biome-aware behavior

3. **Cliff damage** - Falling from cliff edges could deal damage, making elevation strategically important

4. **Water depth visualization** - River centers could be "deep water" (impassable) vs edges as "shallow water" (slower but passable)

## Conclusion

The terrain/biome system is robustly implemented and follows the documentation well. The main opportunities for improvement lie in making terrain more gameplay-relevant through movement modifiers, resource bonuses, and visual feedback enhancements. The existing architecture supports these extensions without major refactoring.
