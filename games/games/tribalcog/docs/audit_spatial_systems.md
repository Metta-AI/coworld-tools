# Spatial Systems Audit Report

**Audit ID:** tv-wisp-234e8
**Date:** 2026-02-08
**Scope:** spatial_index.nim, connectivity.nim, placement.nim, biome.nim

## Executive Summary

The spatial systems are generally well-architected. The `spatial_index.nim` module provides efficient O(1) spatial queries with pre-computed lookup tables. However, there are opportunities to consolidate duplicated distance calculations and direction definitions.

## Findings

### 1. Duplicated Distance Calculations

**Issue:** Chebyshev and Manhattan distance calculations are duplicated across the codebase.

**Current State:**
- `chebyshevDist` template defined in `step.nim:107` and used in ~40 places
- However, ~30 additional places use inline `max(abs(x1-x2), abs(y1-y2))` instead
- Manhattan distance (`abs(x1-x2) + abs(y1-y2)`) appears inline in ~14 places with no template

**Files with inline Chebyshev (not using template):**
- `src/spawn.nim`: lines 810, 1001
- `src/environment.nim`: lines 1900, 1917
- `src/scripted/gatherer.nim`: line 308
- `src/scripted/builder.nim`: line 222
- `src/scripted/ai_core.nim`: line 1143
- `src/scripted/options.nim`: lines 299, 300

**Files with inline Manhattan (no template exists):**
- `src/renderer.nim`: line 2524
- `src/spatial_index.nim`: lines 688, 718 (findNearestThingSpatial, findNearestFriendlyThingSpatial)
- `src/step.nim`: lines 1452, 2743
- `src/scripted/options.nim`: line 352
- `src/scripted/fighter.nim`: line 430
- `src/scripted/ai_core.nim`: lines 592, 618

**Recommendation:** Create `manhattanDist` template alongside `chebyshevDist` and consolidate usage.

### 2. Duplicated Direction Definitions

**Issue:** 8-direction vectors defined in multiple places.

**Current State:**
- `Directions8` const in `ai_core.nim:65` (exported, used by fighter.nim, options.nim)
- `ConnectDirs8` let in `connectivity.nim:7` (local, identical values, different order)

**Recommendation:** Consolidate to single exported definition, likely in `types.nim` or a new `spatial_common.nim`.

### 3. Biome Module Analysis

**Current State:** Already well-structured with config objects:
- `BiomePlainsConfig`, `BiomeSwampConfig`, `BiomeForestConfig`, etc.
- Uses reusable templates: `forClusterCenters`, `cellularStep`, `ditherIf`
- `buildClusterBiomeMask` shared by Plains and Swamp biomes

**Finding:** The biome module is already mostly table-driven via config structs. No significant consolidation needed.

**Minor Opportunity:** The `buildBiomePlainsMask` and `buildBiomeSwampMask` procs are thin wrappers around `buildClusterBiomeMask`. Consider whether these add value or could be replaced with direct calls.

### 4. Connectivity Module Analysis

**Current State:**
- Self-contained map connectivity algorithm using BFS
- Does NOT use spatial_index (correct - runs during map generation before gameplay)
- Uses own `digCost` and `labelComponents` functions

**Finding:** The connectivity module's approach is appropriate:
- Map generation phase, not gameplay
- Needs grid-cell-level operations, not thing-based queries
- Separate concerns from runtime spatial queries

**No changes recommended.**

### 5. Placement Module Analysis

**Current State:**
- Correctly calls `addToSpatialIndex` and `removeFromSpatialIndex`
- No duplicated spatial lookups
- Clean integration with spatial_index module

**Finding:** Well-implemented, no issues found.

### 6. Spatial Query Usage Analysis

**Observation:** Some code iterates `env.thingsByKind[Kind]` where spatial queries might be more efficient.

**Files to consider for spatial query adoption:**
- `src/scripted/fighter.nim:427-430` - iterates all Altars to find nearest (though small N)
- `src/scripted/fighter.nim:599-631` - iterates building kinds for rally points
- `src/environment.nim:1914` - iterates all Mills for farm distance check

**Mitigating factor:** These iterations are over `thingsByKind` (filtered by type) and often have small N. The spatial index benefit is marginal and may not justify code changes.

## Recommendations Summary

### Priority 1: Consolidate Distance Templates
Create in `types.nim` or `spatial_common.nim`:
```nim
template chebyshevDist*(a, b: IVec2): int32 =
  max(abs(a.x - b.x), abs(a.y - b.y))

template manhattanDist*(a, b: IVec2): int32 =
  abs(a.x - b.x) + abs(a.y - b.y)
```

### Priority 2: Consolidate Direction Definitions
Move `Directions8` to shared location and update connectivity.nim to import it.

### Priority 3 (Optional): Audit spatial query opportunities
Review high-frequency loops over `thingsByKind` that include distance checks.

## Files Changed Assessment

| File | Status | Action Needed |
|------|--------|---------------|
| spatial_index.nim | Good | None |
| connectivity.nim | Good | Import shared Directions8 |
| placement.nim | Good | None |
| biome.nim | Good | None |
| types.nim | N/A | Add distance templates |

## Test Impact

Changes are refactoring only - no behavioral changes expected. Existing tests should pass.
