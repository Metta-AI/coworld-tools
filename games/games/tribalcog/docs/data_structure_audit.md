# Data Structure Audit: Spatial Indexing, Entity Lookups, Observation Building

**Date**: 2026-02-04
**Auditor**: tv-wisp-j74qd (Polecat/Slit)
**Scope**: Analyze spatial indexing, entity lookups, and observation building for efficiency improvements

---

## Executive Summary

The codebase has a well-designed spatial index (`spatial_index.nim`) with O(1) amortized queries. However, several hotpath functions bypass the spatial index and iterate `thingsByKind[]` globally, creating O(n) bottlenecks. The primary optimization opportunities are:

1. **High Impact**: Replace `nearestFriendlyBuildingDistance` with spatial query (~200 buildings/call)
2. **High Impact**: Replace `hasTeamLanternNear` with spatial query (~50 lanterns/call)
3. **Medium Impact**: Replace `hasNearbyFood` with spatial query in gatherer logic
4. **Low Impact**: Cache `teamMask` on Thing objects to avoid per-entity `getTeamMask()` calls

---

## 1. Spatial Index Architecture

### Current Implementation (`spatial_index.nim`)

**Strengths**:
- Cell-based partitioning: 16x16 tile cells covering 305x191 map (20x12 grid = 240 cells)
- Pre-computed lookup tables (`DistToCellRadius16[]`) for O(1) distance-to-cell conversion
- Per-kind indices (`kindCells[ThingKind][cx][cy]`) for filtered queries without scanning all entities
- Optional adaptive tuning (`-d:spatialAutoTune`) for dynamic cell resizing based on density
- Swap-and-pop removal for O(1) entity removal from cells

**Data Structure** (types.nim:620-630):
```nim
SpatialIndex* = object
  cells*: array[SpatialCellsX, array[SpatialCellsY, SpatialCell]]
  kindCells*: array[ThingKind, array[SpatialCellsX, array[SpatialCellsY, seq[Thing]]]]
```

**Query Functions Available**:
| Function | Complexity | Use Case |
|----------|-----------|----------|
| `findNearestThingSpatial` | O(cells in radius) | Nearest single entity |
| `findNearestFriendlyThingSpatial` | O(cells in radius) | Nearest team-owned entity |
| `findNearestEnemyAgentSpatial` | O(cells in radius) | Nearest enemy agent |
| `findNearestEnemyBuildingSpatial` | O(cells in radius) | Nearest enemy structure |
| `collectEnemiesInRangeSpatial` | O(cells in radius) | All enemies in range |
| `collectThingsInRangeSpatial` | O(cells in radius) | All entities of type in range |

---

## 2. Identified Inefficiencies

### 2.1 ~~HIGH: `nearestFriendlyBuildingDistance`~~ (FIXED)

**Status**: **Fixed.** Now uses `findNearestFriendlyThingSpatial` for each kind with the current best distance as `maxDist` for early-exit optimization. Changed from O(k * n) to O(k * cells_in_radius).

```nim
proc nearestFriendlyBuildingDistance*(env: Environment, teamId: int,
                                      kinds: openArray[ThingKind], pos: IVec2): int =
  result = int.high
  for kind in kinds:
    let nearest = findNearestFriendlyThingSpatial(env, pos, teamId, kind, result)
    if not nearest.isNil:
      result = min(result, int(chebyshevDist(nearest.pos, pos)))
```

---

### 2.2 ~~HIGH: `hasTeamLanternNear`~~ (FIXED)

**Status**: **Fixed.** Now uses `collectThingsInRangeSpatial(env, pos, Lantern, 3, nearby)` for O(1 cell) lookups instead of iterating all lanterns. Remaining optimization opportunity: the local `seq[Thing]` allocation could be replaced with a pre-allocated buffer.

---

### 2.3 ~~MEDIUM: `hasNearbyFood`~~ (FIXED)

**Status**: **Fixed.** Now uses `findNearestThingOfKindsSpatial(env, pos, FoodKinds, radius)` for O(cells) lookups instead of iterating all food items.

---

### 2.4 ~~MEDIUM: `fighterSeesEnemyStructureUncached`~~ (FIXED)

**Status**: **Fixed.** Now uses `findNearestEnemyBuildingSpatial(env, agent.pos, teamId, radius)` for O(cells) lookups instead of iterating all buildings by kind. Also remains cached per-step via `seesEnemyStructureCache`.

---

### 2.5 LOW: `getTeamMask` Called Twice Per Entity

**Problem**: In team-filtered queries, `getTeamMask(teamId)` is pre-computed but `getTeamMask(thing.teamId)` is called for each entity (spatial_index.nim:565):

```nim
let teamMask = getTeamMask(teamId)  # Pre-computed
forEachInRadius(env, pos, kind, maxDist, thing):
  if (getTeamMask(thing.teamId) and teamMask) == 0:  # Called per entity
    continue
```

**Impact**: `getTeamMask` is a simple lookup (`1 shl teamId`), so overhead is minimal. However, caching on Thing would eliminate the call entirely.

**Potential Fix**: Add `teamMask` field to Thing, updated when `teamId` changes:
```nim
Thing* = ref object
  teamId*: int
  teamMask*: int  # = 1 shl teamId, or 0 if teamId < 0
```

---

### 2.6 LOW: `forEachInRadius` Loop Bounds

**Problem**: The nested loop checks `abs(dx) > searchRadius` inside the loop (spatial_index.nim:497-500):

```nim
for dx in -maxRadius .. maxRadius:
  if abs(dx) > searchRadius: continue  # Redundant check
  for dy in -maxRadius .. maxRadius:
    if abs(dy) > searchRadius: continue  # Redundant check
```

**Note**: `searchRadius` can shrink during the loop (early-exit optimization), so this check is intentional.

**Impact**: Low - the check is simple and enables the early-exit optimization.

---

## 3. Entity Lookup Patterns Summary

| Pattern | Current | Status | Files |
|---------|---------|--------|-------|
| Find nearest building (any team) | Spatial O(cells) | **Fixed** | ai_core.nim |
| Find nearest friendly building | Spatial O(cells) | **Fixed** | ai_core.nim |
| Find lantern within 3 tiles | Spatial O(1 cell) | **Fixed** | ai_core.nim |
| Find nearest food | Spatial O(cells) | **Fixed** | gatherer.nim |
| Find enemy in vision | Spatial + cache | **Fixed** | fighter.nim |
| Direct grid lookup | `grid[x][y]` O(1) | Optimal | environment.nim |
| Per-kind iteration (render) | `thingsByKind` O(n) | Acceptable | renderer.nim |

---

## 4. Observation Building Analysis

### Current Implementation (environment.nim:766-817)

**Architecture**:
- Each agent has an 11x11 observation window (121 tiles)
- 82 observation layers encoded as uint8
- Rebuilt per-step, but stationary agents skip rebuild

**Optimization Already Applied**:
```nim
if firstRun or agentMoved:
  rebuildObservationsForAgent(env, agentId, agent)
```

**Complexity**: O(agents * tiles) = O(1006 * 121) ≈ 121K memory accesses per step (worst case)

**Potential Improvements** (not urgent):
1. Per-agent dirty bits instead of global flag
2. Vectorize terrain layer encoding
3. Pre-compute observation tile offsets at initialization

---

## 5. Recommendations Priority Matrix

| Priority | Change | Status |
|----------|--------|--------|
| ~~P0~~ | ~~Replace `nearestFriendlyBuildingDistance` with spatial queries~~ | **Done** |
| ~~P0~~ | ~~Replace `hasTeamLanternNear` with spatial query~~ | **Done** |
| ~~P1~~ | ~~Replace `hasNearbyFood` with spatial query~~ | **Done** |
| ~~P1~~ | ~~Replace `fighterSeesEnemyStructureUncached` with spatial query~~ | **Done** |
| **P2** | Cache teamMask on Thing objects | Open |
| **P3** | Per-agent observation dirty bits | Open |

---

## 6. Implementation Notes

### Completed P0 Changes:

All P0 and P1 recommendations have been implemented. The spatial index is now used
consistently for entity lookups throughout the AI system.

### Remaining Optimization (P2):

Caching `teamMask` on Thing objects would eliminate per-entity `getTeamMask()` calls
in spatial queries. Currently `getTeamMask` is a simple `1 shl teamId` computation,
so overhead is minimal.

### Testing Strategy:

1. Run benchmark: `make benchmark`
2. Profile with `-d:spatialStats` + `TV_SPATIAL_STATS_INTERVAL=100`
3. Run integration tests: `nim r --path:src tests/integration_behaviors.nim`
4. Run settlement tests: `make test-settlement`

---

## 7. Appendix: Key Files

| File | Purpose | Lines |
|------|---------|-------|
| `src/spatial_index.nim` | Spatial partitioning queries | 949 |
| `src/types.nim` | Data structure definitions | 1200+ |
| `src/scripted/ai_core.nim` | AI utility functions | 1487 |
| `src/scripted/fighter.nim` | Fighter behavior | 1000+ |
| `src/scripted/gatherer.nim` | Gatherer behavior | 400+ |
| `src/environment.nim` | Grid/observation management | 1800+ |
