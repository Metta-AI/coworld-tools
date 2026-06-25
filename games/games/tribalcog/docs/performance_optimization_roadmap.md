# Performance Optimization Roadmap

> Consolidated from individual audit docs on 2026-02-08.
> Updated 2026-02-10 with latest optimization status.
> See also: `PERF_OPTIMIZATION_TASKS.md` for the completed spatial optimization sprint (7/7 tasks done).

## Key Performance Bottlenecks (Post-Refactor Investigation Targets)

**AI computation time dominates total wall time.** At ~500 steps/sec, `getActions()` consumes ~45% of total wall time (~0.9ms/step) but is invisible to the step profiler since it runs before `env.step()`. Further AI optimization is limited by fundamental decision-making complexity — reducing update frequency causes regressions (staler data → worse decisions → more pathfinding retries).

**tintObs remains the dominant step subsystem at 69% of step time** (~0.76ms/step). Five optimizations have been applied (fixed-point decay, counting sort, steeper decay, dirty tracking, skip unchanged colors), reducing it from 82-86%. Further gains likely require SIMD vectorization or architectural changes (tile-level LOD, less frequent updates). This should be a continued investigation target post-refactor.

## Performance Baseline

| Date | Agents | Steps/sec | Per-agent AI | Notes |
|------|--------|-----------|-------------|-------|
| 2026-01-24 | 1006 | ~2.25 | - | Pre-optimization baseline |
| 2026-01-28 | 1006 | 733 → 1017 | - | After observation batch rebuild (+38%) |
| 2026-02-04 | 1006 | 76.4 (step only) | 10.98us | With stepTiming instrumentation |
| 2026-02-06 | 1006 | 146.0 | 5.86us | After spatial optimizations, AI profiled separately |
| 2026-02-10 | 1006 | ~500 | - | After tint optimizations + AI allocation elimination |

## Step() Subsystem Breakdown

Profiled with `-d:release -d:perfRegression`, 1006 agents over 1000 steps (2026-02-10):

| Subsystem | Mean ms | Avg % | Notes |
|-----------|---------|-------|-------|
| **tintObs** | 0.76 | 69% | Down from 82-86% after fixed-point decay, counting sort, dirty tracking |
| actions | 0.11 | 10% | Agent action processing |
| things | 0.15 | 14% | Thing updates (spawners, animals, buildings) |
| tumorDamage | 0.02 | 2% | Tumor damage calculation |
| tumors | 0.02 | 2% | Tumor processing |
| popRespawn | 0.04 | 4% | Respawn logic |
| **TOTAL step** | 1.10 | - | Step subsystem only |
| **AI (getActions)** | ~0.90 | - | Runs before step, not in step profiler |
| **Total wall** | ~2.00 | - | ~500 steps/sec |

AI (getActions) consumes ~45% of total wall time but is invisible to the step profiler.

---

## Completed Optimizations

### Observation Batch Rebuild (2026-01-28) DONE

Replaced incremental per-tile `updateObservations()` (called ~50+ times/step, each iterating all 1006 agents) with a single `rebuildObservations()` at end of step.

- **Before**: ~50,300 agent iterations/step (50 updates x 1006 agents), 65% of runtime
- **After**: 121,726 writes/step (1006 agents x 121 tiles), batch rebuild is 57% of runtime
- **Result**: 733 → 1017 steps/sec (+38%)

### Spatial Index Infrastructure (2026-02-02) DONE

Added `SpatialIndex` with cell-based partitioning for O(1) amortized spatial queries. See `src/spatial_index.nim`. Utilities added:
- `findNearestThingOfKindsSpatial()` - multi-kind queries
- `collectThingsInRangeSpatial()` - generic collection by kind
- `collectAgentsByClassInRange()` - unit-class filtering (tanks, monks)
- `countAlliesInRangeSpatial()` - allocation-free counting
- `countEnemiesInRangeSpatial()` - allocation-free counting
- `hasAllyInRangeSpatial()` - allocation-free early-exit check

### Predator Targeting with Spatial Queries DONE
Replaced O(radius^2) grid scans with `findNearestPredatorTargetSpatial()` for wolves and bears.

### Aura Processing Optimization DONE
Added `env.tankUnits` and `env.monkUnits` collections maintained on spawn/death/class-change. Aura processing iterates only relevant units instead of all agents.

### Spawner Tumor Scan with Spatial Query DONE
Replaced 11x11 grid scans with `countUnclaimedTumorsInRangeSpatial()`.

### Staggered AI Threat Map Updates DONE
Threat map updates staggered by agent ID mod 5, reducing per-step cost by 5x. Decay also staggered to every 5 steps.

### Fighter Target Re-evaluation Optimization DONE
Increased `TargetSwapInterval` and added caching for `isThreateningAlly()` results.

### Combat Aura Damage Check with Spatial Query DONE
Replaced O(n) agent scan with `collectAgentsByClassInRange()` for tank aura damage reduction.

### stepRechargeMonkFaith DONE
Now iterates `env.monkUnits` instead of all agents, consistent with `stepApplyMonkAuras`.

### hasTeamLanternNear Spatial Query DONE
Uses `collectThingsInRangeSpatial(env, pos, Lantern, 3, ...)` with `env.tempTowerTargets` scratch buffer. No heap allocation.

### nearestFriendlyBuildingDistance DONE
Uses `findNearestFriendlyThingSpatial` for O(cells) lookups instead of O(buildings).

### Pathfinding Cache Pre-allocation DONE
`PathfindingCache` added to `Controller` with pre-allocated arrays, generation counters for O(1) cache invalidation, binary heap for O(log n) open set, and 250-node exploration cap.

### Previously-O(n) Hotpaths Fixed DONE
- `updateThreatMapFromVision`: O(visionRange^2) via spatial cells
- `findAttackOpportunity`: O(8 x maxRange) line scan
- `fighterFindNearbyEnemy`: O(enemyRadius^2) grid scan
- `needsPopCapHouse`: O(1) cached per-step
- `findNearestThing` / `findNearestThingSpiral`: Replaced with spatial index lookups

### Tint System Optimizations (2026-02-10) DONE
Five-phase optimization reducing tintObs from 82-86% to 69% of step time:
1. **Fixed-point decay**: `v * 65339 >> 16` instead of integer division
2. **Steeper decay**: 0.997 vs 0.9985, halves active tile count
3. **Counting sort**: O(n) radix sort replaces O(n log n) Timsort for cache locality
4. **Skip unchanged colors**: Decay-only tiles update intensity without color recompute
5. **Dirty tracking**: `stepDirtyFlags`/`stepDirtyPositions` for tint transition detection

### Eliminate Fighter Seq Allocations (2026-02-10) DONE
Added allocation-free `countAlliesInRangeSpatial`, `countEnemiesInRangeSpatial`, `hasAllyInRangeSpatial` to spatial_index.nim. Replaced 3 per-fighter per-step heap allocations. Converted kite candidates from heap seq to `array[3, IVec2]`. Reused `tempAIAllies` buffer for monk wounded-ally search.

### Formation Position Cache (2026-02-10) DONE
`getFormationTargetForAgent` was allocating full `seq[IVec2]` per-agent (×3 calls per agent per step). Added per-group position cache that only recomputes when center/size/type/rotation changes. For 20-unit group: 60 allocations → 1 per step.

### Gatherer Scoring Stack Array (2026-02-10) DONE
Replaced gatherer task scoring `seq[(GathererTask, float)]` literal with `array[5, ...]`. Called per-gatherer per-step (50-200 agents).

### findPath Buffer Reuse (2026-02-10) DONE
Changed `findPath` from returning `seq[IVec2]` to writing into caller's existing `state.plannedPath` buffer. Reuses seq capacity across pathfinding invocations instead of allocating new seq each call.

### tempTowerRemovals HashSet DONE
Already converted to `HashSet[Thing]` for O(1) membership checks.

### Duplicate Population Calculations DONE
Already consolidated to single calculation at step start in `env.stepTeamPopCaps`/`env.stepTeamPopCounts`.

### canEnterForMove Lantern Buffer DONE
Already uses `env.tempTowerTargets` scratch buffer. No heap allocation.

### Fog Reveal Staggering DONE
Already staggered 1/5 of agents per step via `ThreatMapStaggerInterval`. Stationary agents skip reveal via position tracking. Corner sampling avoids tile iteration if area already revealed.

### Animal Movement Array DONE
Corner target selection already uses `array[4, IVec2]` instead of heap seq.

### Test Suite Speedup (2026-02-10) DONE
Combined test runner + `-d:release` mode. Wall time: ~9m → ~2m15s (4x speedup).

---

## Open Optimization Opportunities

### MEDIUM IMPACT

#### 1. Tint System — Further Optimization (69% of step time)

The tint system remains the dominant hotpath. Next-level options:
- **SIMD vectorization**: Use nimsimd for batch decay/color computation
- **Less frequent tint updates**: Skip tint every N steps (visual quality tradeoff)
- **Tile-level LOD**: Reduce computation for distant/non-observed tiles

#### 2. ~~Cache nearestFriendlyBuildingDistance Per-Step~~ NOT NEEDED

Already efficiently handled by spatial index. Each call is O(cells) with early-exit via decreasing `maxDist`. Different agents query from different positions, so per-step caching by (team, kinds) doesn't help.

### LOW IMPACT

#### 3. ~~Fertile Tile 17x17 Scan~~ DONE (2026-02-10)

Added early exit from 17x17 scan when adjacent fertile tile found (`minDist <= 1`). Gatherers near farms typically find an adjacent tile immediately, avoiding the remaining ~288 tile checks.

#### 4. Inventory String Allocations

**Location**: `step.nim` (USE action path)

`thingItem($thing.kind)` creates string allocation per USE action. Low frequency (~1-10/step).

#### 5. tumorsToRemove seq `in` Check

**Location**: `tumors.nim`

`tumorsToRemove` is `ptr seq[Thing]` with O(n) `in` checks. N is typically 0-5 so impact is negligible.

---

## Profiling Infrastructure

The codebase has good profiling support:

- **Step timing**: Compile with `-d:release -d:stepTiming`, set `TV_STEP_TIMING=100` (start step) and `TV_STEP_TIMING_WINDOW=50` (window)
- **Benchmarking**: `make benchmark` for steps/sec + regression detection
- **Spatial auto-tune**: Compile with `-d:spatialAutoTune`

---

## Source Documents

This roadmap was consolidated from:
- `docs/perf_audit_hotloops.md` (2026-02-04) — Hotloop audit of step.nim and ai_core.nim
- `docs/perf-audit-pathfinding-movement.md` (2026-02-06) — Pathfinding and movement overhead audit
- `docs/analysis/performance_analysis.md` (2026-01-28) — General performance analysis
- `docs/analysis/performance_scaling_1000_agents.md` (2026-01-24) — 1000+ agent scaling investigation
- `docs/analysis/perf-improvements.md` (2026-01-28) — Observation batch rebuild improvement
- `docs/analysis/step_hotpath_profile.md` (2026-02-04) — Step hotpath profile analysis
