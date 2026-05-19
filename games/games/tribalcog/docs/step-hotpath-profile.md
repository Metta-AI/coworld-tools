# Performance Audit: step() Hotpath with nimprof

**Bead:** tv-wisp-7vl1ha
**Author:** polecat
**Date:** 2026-02-11

## Executive Summary

Profiled the main `step()` function hotpath using nimprof and perfRegression instrumentation. The system achieves **1334 steps/second** with 1006 agents, far exceeding the 60fps target.

**Key findings:**
- `getActions()` (AI decisions) consumes ~75% of total step time
- `tintObs` subsystem takes ~52% of `step()` internal time (but only ~12% of total)
- No O(n²) loops detected in hot paths
- Spatial index queries use O(1) cell lookups with precomputed offsets

## Benchmark Results

| Metric | Value | Notes |
|--------|-------|-------|
| Steps/second | 1334.7 | 1006 agents, seed=42 |
| Mean step time | 0.749ms | Full step including AI |
| P95 step time | 1.215ms | 95th percentile |
| P99 step time | 1.426ms | 99th percentile |
| Target | 60fps | **Exceeded by 22x** |

## Subsystem Breakdown (perfRegression)

The `step()` function is instrumented with timing for 11 subsystems:

| Subsystem | Mean (ms) | P95 (ms) | P99 (ms) | % of step() |
|-----------|-----------|----------|----------|-------------|
| tintObs | 0.0876 | 0.1471 | 0.1802 | 51.9% |
| actions | 0.0258 | 0.0492 | 0.0641 | 15.3% |
| things | 0.0209 | 0.0436 | 0.0610 | 12.4% |
| popRespawn | 0.0120 | 0.0219 | 0.0277 | 7.1% |
| tumors | 0.0090 | 0.0222 | 0.0298 | 5.3% |
| tumorDamage | 0.0045 | 0.0080 | 0.0111 | 2.7% |
| preDeaths | 0.0034 | 0.0084 | 0.0127 | 2.0% |
| actionTint | 0.0029 | 0.0052 | 0.0059 | 1.7% |
| survival | 0.0019 | 0.0033 | 0.0037 | 1.1% |
| shields | 0.0007 | 0.0011 | 0.0014 | 0.4% |
| auras | 0.0002 | 0.0005 | 0.0007 | 0.1% |
| **TOTAL** | **0.1689** | **0.2933** | **0.3857** | **100%** |

### Time Distribution

```
Total step time: 0.749ms
├── getActions (AI): ~0.580ms (77%)
└── step() subsystems: ~0.169ms (23%)
    └── tintObs: ~0.088ms (52% of step)
```

## nimprof Profile Analysis

Top functions by sample count:

| Function | Samples | % | Notes |
|----------|---------|---|-------|
| getActions | 224/441 | 50.8% | AI decision loop |
| decideAction | 159/441 | 36.1% | Per-agent decisions |
| decideRoleFromCatalog | 103/441 | 23.4% | Role option evaluation |
| runOptions | 80/441 | 18.1% | Options system |
| scoreTerritory | 64/441 | 14.5% | Adaptive difficulty |
| moveTo | 51/441 | 11.6% | Pathfinding entry |
| findPath | 47/441 | 10.7% | A* algorithm |
| step | 45/441 | 10.2% | Env step function |

### Pathfinding Performance

The pathfinding system (profiled in detail in `perf-audit-pathfinding-movement.md`) shows:
- A* capped at 250 nodes per call
- Greedy movement for distance < 6 tiles
- Generation-counter cache invalidation (O(1))

nimprof shows `findPath` and `moveTo` combined at ~22% of getActions time.

## tintObs Subsystem Analysis

The `tintObs` timing covers:
1. `updateTintModifications()` - collect entity tint contributions
2. Set `observationsDirty = true` - lazy observation rebuilding

This subsystem is the largest portion of `step()` time because:
- Iterates over all entities with tint effects (lanterns, auras, fortifications)
- Uses counting sort for efficient tint area processing
- Frozen state computed eagerly for game logic

Observations are now lazily rebuilt only when accessed (FFI or getObservations), saving O(agents × observation_tiles) work per step.

## Spatial Index Performance

Verified that spatial index operations use O(1) cell lookups:

```nim
# From spatial_index.nim - precomputed offsets avoid nested loops
const PrecomputedOffsets: array[MaxPrecomputedRadius+1, seq[IVec2]] = ...
# Replaces runtime nested loop: for dx in -r..r: for dy in -r..r
```

Key spatial operations:
- `collectThingsInRangeSpatial()` - O(radius²) cell checks, precomputed for small radii
- `findNearestEnemyBuildingSpatial()` - O(cells in range)
- Incremental updates during position changes

## O(n²) Loop Verification

**No O(n²) loops detected in hot paths.**

The codebase uses:
- Spatial indexing for entity proximity queries
- Precomputed offset arrays for radius iteration
- Bounded iteration (e.g., A* 250-node cap)

Fallback nested loops exist for rare large-radius queries but are not hit during normal gameplay.

## Profiling Tools Used

| Tool | Flag | Purpose |
|------|------|---------|
| nimprof | `--profiler:on --stackTrace:on` | Call stack sampling |
| perfRegression | `-d:perfRegression` | Subsystem timing |
| stepTiming | `-d:stepTiming` | Per-step timing output |
| flameGraph | `-d:flameGraph` | Flame graph sampling |

### Running the Profilers

```bash
# Benchmark with subsystem timing
TV_PERF_STEPS=1000 nim r -d:release -d:perfRegression --path:src scripts/benchmark_steps.nim

# stepTiming output
TV_AI_TIMING=1 TV_AI_TIMING_INTERVAL=100 ./tribal_village -d:stepTiming
```

## Recommendations

### No Critical Issues Found

Performance significantly exceeds requirements:
- 1334 steps/sec vs 60fps target (22x headroom)
- tintObs is largest subsystem but still only 0.09ms mean
- AI decisions dominate but are well-optimized

### Potential Future Optimizations (Low Priority)

1. **Lazy tint computation** - defer tint color calculation until rendering
2. **AI decision batching** - group similar decisions to improve cache locality
3. **SIMD direction scoring** - parallelize getMoveTowards() direction tests

These are not recommended currently as performance is already excellent.

## Conclusion

The step() hotpath meets all performance targets with substantial margin. The 60fps requirement with 200+ units is exceeded by 22x even with 1006 agents. No algorithmic issues (O(n²) loops) were found. The codebase includes mature profiling infrastructure for ongoing performance monitoring.

**Status:** Performance audit complete. No action required.
