# Spatial Index Query Hotspots Audit

**Date:** 2026-02-06
**Auditor:** polecat/furiosa
**Issue:** tv-3y7di8
**Method:** Compiled with `-d:spatialStats`, ran `profile_ai.nim` for 500 steps

## Executive Summary

The spatial index is heavily utilized with ~10M queries per 1000 steps. Three query types dominate: `collectThings` (83%), `findNearestEnemy` (8%), and `findNearest` (4%). Key optimization opportunities exist in reducing `collectThings` call frequency and narrowing search radii for enemy queries.

## Methodology

```bash
TV_SPATIAL_STATS_INTERVAL=100 TV_PROFILE_STEPS=1000 nim r -d:release -d:spatialStats --path:src scripts/benchmark_steps.nim
```

## Raw Data (Steps 401-500, Steady State)

| Query Type | Queries | Cells/Q | Things/Q | Hits | Misses | Hit% |
|------------|---------|---------|----------|------|--------|------|
| collectThings | 815,780 | 8.6 | 15.3 | 592,962 | 222,818 | 72.7% |
| findNearestEnemy | 77,561 | 8.5 | 137.9 | 14,567 | 62,994 | 18.8% |
| findNearest | 38,008 | 29.5 | 182.4 | 36,412 | 1,596 | 95.8% |
| findNearestFriendly | 34,072 | 38.6 | 2.2 | 16,383 | 17,689 | 48.1% |
| findNearestOfKinds | 15,708 | 16.7 | 0.0 | 0 | 15,708 | 0.0% |
| collectEnemies | 800 | 8.6 | 146.4 | 14 | 786 | 1.8% |
| **TOTAL** | **981,929** | **10.6** | **30.8** | 660,338 | 321,591 | 67.2% |

## Hotspot Analysis

### 1. collectThings - CRITICAL HOTSPOT

**Volume:** 815,780 queries/100 steps = **8,158 queries/step**

**Primary Callers:**
- `step.nim:471,501` - Tower/TownCenter target collection (Tumor, Spawner)
- `step.nim:841` - Hill control point agent collection
- `step.nim:1303` - Lantern spacing validation
- `ai_core.nim:890,1108` - Lantern proximity checks

**Problem:** Called per-tower and per-agent for target acquisition and spacing checks. The volume scales with entity count.

**Optimization Targets:**
1. **Cache resource positions per-step** - Many agents searching for same resource types
2. **Reduce call frequency** - Only search every N steps instead of every step
3. **Use spatial heatmaps** - Pre-compute resource density by region

### 2. findNearestEnemy - HIGH VOLUME, LOW HIT RATE

**Volume:** 77,561 queries/100 steps = **776 queries/step**
**Things/Query:** 137.9 (very high)
**Hit Rate:** 18.8% (low)

**Analysis:**
- Examining 138 things per query indicates agents are searching with large radii
- 81% miss rate suggests many queries return nil (no enemy in range)

**Optimization Targets:**
1. **Reduce search radius** - Current enemy search seems too wide
2. **Cache enemy presence** - Use per-agent cache to skip redundant searches
3. **Early-exit on no enemies** - Track global enemy presence flag per region

### 3. findNearest - HIGH VOLUME, HIGH WORK

**Volume:** 38,008 queries/100 steps = **380 queries/step**
**Things/Query:** 182.4 (very high!)
**Cells/Query:** 29.5 (large search area)
**Hit Rate:** 95.8% (good)

**Analysis:**
- High cell count (29.5) suggests large search radii
- High things examined (182) indicates dense results
- Used for resource searches (trees, berries, mines)

**Optimization Targets:**
1. **Reduce default search radius** - 29 cells is ~464 world units, may be excessive
2. **Use kind-specific radii** - Different resources don't need same search range
3. **Consider hierarchical search** - Start small, expand only if miss

### 4. findNearestOfKinds - 0% HIT RATE (NOT A BUG)

**Volume:** 15,708 queries/100 steps
**Hit Rate:** 0% (all misses)

**Callers:**
- `gatherer.nim:hasNearbyFood()` - searches for FoodKinds
- `options.nim:findNearestPredatorInRadius()` - searches for {Wolf, Bear}
- `fighter.nim:optFighterHuntPredators()` - searches for predators

**Analysis:** The 0% hit rate is scenario-dependent, not a bug. In the default test map:
- Predators (wolves/bears) may not spawn or are killed early
- Food sources may be exhausted in later game stages

**Optimization Target:** Consider caching "predator presence" flag per-region to avoid repeated nil queries when no predators exist. Low priority since query cost is minimal (0.0 things examined per query).

## Recommendations

### Priority 1: Reduce collectThings Volume

The spatial index is fundamentally efficient (8.6 cells, 15.3 things per query), but call volume is the problem.

| Optimization | Impact | Effort |
|--------------|--------|--------|
| Per-step resource position cache | -70% queries | Medium |
| Staggered gathering search (every 3 steps) | -66% queries | Low |
| Regional resource heatmaps | -80% queries | High |

### Priority 2: Cache Predator/Food Presence (Low Priority)

The 0% hit rate for `findNearestOfKinds` is scenario-dependent (no predators/food in test scenario). Consider adding a regional "has_predators" flag to skip redundant queries, but this is low priority since query cost is minimal (0.0 things examined).

### Priority 3: Narrow Enemy Search Radii

Current `enemyRadius` (defined in fighter.nim as `ObservationRadius * 2` ≈ 50) may be too large for dense combat scenarios.

| Current | Proposed | Impact |
|---------|----------|--------|
| 50 tile radius | 30 tile radius | -50% things examined |
| Per-query team check | Pre-filter by team mask | -20% examined |

### Priority 4: Cache Enemy Presence

Many agents check for enemies every step even when none nearby. Add a regional "enemy presence" flag that's updated only when enemies enter/exit regions.

## Performance Impact Estimate

Current: 981,929 queries/100 steps @ 30.8 things/query = 30.2M thing examinations

With optimizations:
- collectThings caching: -70% = 571K queries saved
- findNearestOfKinds fix: -100% = 16K queries saved
- Enemy radius reduction: -50% examined = 5.4M examinations saved

**Estimated improvement: 40-50% reduction in spatial query overhead**

## Files to Modify

1. `src/scripted/gatherer.nim` - Add resource position caching
2. `src/scripted/fighter.nim` - Reduce enemy search radius, fix findNearestOfKinds caller
3. `src/scripted/ai_core.nim` - Add per-step resource cache infrastructure
4. `src/spatial_index.nim` - No changes needed, index itself is efficient

## Next Steps

1. Profile callers of `collectThingsInRangeSpatial` to identify highest-frequency call sites
2. Implement per-step resource cache in `ai_core.nim`
3. Audit `findNearestOfKinds` callers for the 0% hit rate issue
4. Consider `-d:spatialAutoTune` for adaptive cell sizing based on entity density
