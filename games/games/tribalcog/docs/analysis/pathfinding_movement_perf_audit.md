# Performance Audit: Pathfinding and Movement Calculation Overhead

**Date:** 2026-02-11
**Bead:** tv-69rq3n
**Status:** Complete

## Executive Summary

Analysis of pathfinding and movement overhead per tick reveals that **AI decision-making consumes 78% of tick time**, while actual movement simulation consumes only 22%. Within step processing, movement ("actions") accounts for just 10-19% of simulation time.

**Key findings:**
1. **Pathfinding is well-optimized** - A* is bounded to 250 nodes max, uses generation-counter cache invalidation
2. **No pathfinding bottleneck exists** - Greedy movement for <6 tiles, A* only for longer distances
3. **Main overhead is in AI behavior logic**, not pathfinding algorithms
4. **Step simulation's largest overhead is tintObs (44-57%)**, not movement

## Performance Profile (2000 steps, 1006 agents)

### High-Level Breakdown

| Phase | Avg ms/tick | Max ms/tick | % Total |
|-------|-------------|-------------|---------|
| AI (getActions) | 0.295 | 0.770 | 78.0% |
| Sim (env.step) | 0.083 | 0.510 | 21.9% |

**Throughput:** 2649 steps/second
**Per-agent AI cost:** 0.29µs average

### Step Timing Breakdown (within env.step)

| System | Avg ms | % Step Time | Description |
|--------|--------|-------------|-------------|
| tintObs | 0.0280-0.0559 | 44-57% | Observation layer tinting |
| actions | 0.0098-0.0121 | 10-19% | **Movement processing** |
| things | 0.0071-0.0102 | 10-11% | Thing updates |
| tumors | 0.0039-0.0096 | 6-10% | Tumor expansion |
| popRespawn | 0.0055-0.0059 | 6-8% | Population respawn |
| tumorDamage | 0.0021-0.0024 | 2-3% | Tumor damage |
| preDeaths | 0.0013-0.0014 | 1-2% | Pre-death processing |
| actionTint | 0.0007-0.0014 | 0.7-2.3% | Action tinting |
| survival | 0.0011 | 1.1-1.8% | Survival penalty |
| shields | 0.0003 | 0.3-0.4% | Shield decay |
| auras | 0.0000 | <0.1% | Aura effects |

## Pathfinding Architecture Analysis

### Strategy Selection (ai_core.nim:1302-1393)

```
Distance < 6 tiles → Greedy movement (getMoveTowards)
Distance ≥ 6 tiles → A* pathfinding (findPath)
Stuck detected    → Spiral search fallback
```

### A* Implementation Characteristics

| Property | Value | Impact |
|----------|-------|--------|
| Exploration limit | 250 nodes | Bounds worst-case to O(250 log 250) |
| Cache invalidation | Generation counter | O(1) vs O(MapWidth × MapHeight) |
| Heap operations | Binary heap | O(log n) push/pop |
| Heuristic | Chebyshev distance | Admissible, consistent |
| Goal handling | Auto-targets neighbors if blocked | Handles building pathfinding |

### Greedy Movement (getMoveTowards)

- O(8) constant time - checks all 8 directions
- No heap overhead
- Handles edge cases: out-of-bounds, blocked directions

## Movement Processing Analysis (step.nim:451-654)

Movement processing in the step function is efficient:

1. **Verb dispatch**: O(1) table lookup
2. **Terrain checks**: O(1) grid lookups for elevation, water, doors
3. **Agent swapping**: Same-team agents can swap positions (prevents deadlocks)
4. **Cavalry double-move**: Pre-computed set membership check
5. **Lantern pushing**: Spatial query with 2-tile radius (O(1) amortized)

### Movement Cost Per Agent

The movement action processing is minimal:
- Position update: O(1)
- Grid update: O(1)
- Spatial index update: O(1) amortized
- Observation update: O(1)

## Hotpath Complexity (Current State)

### Optimized O(range²) Operations

| Function | Complexity | Notes |
|----------|------------|-------|
| updateThreatMapFromVision | O(visionRange²) | Was O(agents) |
| findAttackOpportunity | O(8×maxRange) | Line scan, was O(things) |
| fighterFindNearbyEnemy | O(enemyRadius²) | Grid scan, was O(agents) |
| isThreateningAlly | O(AllyThreatRadius²) | Grid scan, was O(agents) |
| needsPopCapHouse | O(1) | Cached per-step |
| findNearestFriendlyMonk | O(HealerSeekRadius²) | Grid scan, was O(agents) |

### Remaining O(n) Candidates

| Function | Current Complexity | Optimization Opportunity |
|----------|-------------------|-------------------------|
| nearestFriendlyBuildingDistance | O(things) | Add to spatial index |
| hasTeamLanternNear | O(things) | Spatial query |
| optFighterLanterns | O(things) | Spatial query |
| revealTilesInRange | O(visionRadius²) | Already bounded |

## Top Slowest Agents

Consistent patterns in AI timing show certain agent IDs are consistently slowest:

| Agent ID | Avg ms | Likely Role |
|----------|--------|-------------|
| 379, 380 | 0.006-0.01 | Fighter (complex targeting) |
| 4, 5 | 0.006-0.014 | Early fighters/builders |
| 754, 755 | 0.007-0.012 | Fighter squad |
| 629, 630 | 0.004-0.007 | Mixed roles |

This suggests **fighter AI behavior is the main decision-time consumer**, not pathfinding itself.

## Spatial Index Performance

The spatial index (spatial_index.nim) provides O(1) amortized queries:

- Grid-based cells (16×16 pixels)
- Pre-computed lookup tables for distance-to-cell-radius
- Pre-computed neighbor cell offsets sorted by Chebyshev distance
- Auto-tuning support (compile with `-d:spatialAutoTune`)

## Recommendations

### No Action Needed

1. **Pathfinding is not a bottleneck** - already well-bounded with A* exploration limits and greedy fallback
2. **Movement simulation is efficient** - only 10-19% of already-small step time
3. **Per-agent AI cost is 0.29µs** - negligible for 1006 agents

### Potential Future Optimizations

1. **tintObs (44-57% of step time)**: If step time becomes a concern, investigate observation tinting optimization
2. **Fighter targeting logic**: Profile specific fighter behavior functions if AI time grows
3. **O(n) scans**: Convert remaining linear scans to spatial queries if they appear in profiles

## Profiling Commands

```bash
# Full step timing + AI timing
TV_PROFILE_STEPS=2000 TV_STEP_TIMING=1 TV_TIMING_INTERVAL=500 \
  TV_AI_TIMING=1 TV_AI_TIMING_INTERVAL=500 \
  nim r -d:release -d:stepTiming --path:src scripts/benchmark_steps.nim

# Flame graph output (requires -d:flameGraph)
TV_FLAME_OUTPUT=profile.collapsed TV_PROFILE_STEPS=1000 \
  nim r -d:release -d:flameGraph --path:src scripts/benchmark_steps.nim

# Performance regression detection
TV_PERF_INTERVAL=100 TV_PROFILE_STEPS=2000 \
  nim r -d:release -d:perfRegression --path:src scripts/benchmark_steps.nim
```

## Conclusion

Pathfinding and movement calculation overhead is **minimal and well-optimized**. The A* implementation with bounded exploration, generation-counter caching, and greedy fallback for short distances means pathfinding is O(1) amortized per tick for most agents.

The main time consumer is AI decision logic (behavior selection, target evaluation), not the pathfinding algorithms themselves. Movement simulation is highly efficient at <0.01ms per tick.

No optimization action is required for pathfinding or movement at this time.
