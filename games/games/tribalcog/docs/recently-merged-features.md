# Recently Merged Features

Consolidated reference for recently merged performance instrumentation, visual features, and cleanup work.

## Summary Table

| Feature | PR/Bead | Type | Compile Flag | Key Files |
|---------|---------|------|-------------|-----------|
| AI decision timing | #253 | Perf | `-d:stepTiming` | `src/step.nim`, `src/agent_control.nim` |
| Pathfinding audit | #254 | Perf | &mdash; | `docs/performance_optimization_roadmap.md` |
| Action frequency counter | #257 | Perf | `-d:actionFreqCounter` | `src/action_freq_counter.nim` |
| Spatial index pre-computation | #249 | Perf | &mdash; | `src/spatial_index.nim` |
| Spatial index hotspots audit | #252 | Docs | &mdash; | `docs/analysis/spatial_stats_audit.md` |
| Spatial index auto-tuning | tv-wisp-p89ix | Perf | `-d:spatialAutoTune` | `src/spatial_index.nim` |
| Tower memory optimization | &mdash; | Perf | &mdash; | `src/step.nim` |
| Water ripple effects | #259 | Visual | &mdash; | `src/renderer.nim`, `src/types.nim` |
| Torch/fire flicker | #258 | Visual | &mdash; | `src/renderer.nim` |
| fogVisibility fix | #260, #262 | Bugfix | &mdash; | `src/renderer.nim` |
| Dead import cleanup | #256 | Cleanup | &mdash; | `src/ffi.nim`, tests |
| Double-kill crash fix | tv-cb72a | Bugfix | &mdash; | `src/combat.nim`, `src/step.nim` |
| Benchmark script | tv-h53aj | Tooling | `-d:perfRegression` | `scripts/benchmark_steps.nim` |

## Compile Flags

All flags are zero-cost when disabled (instrumentation code is compiled out entirely).

### `-d:stepTiming` &mdash; Per-subsystem step timing

Enables detailed timing breakdown of each simulation step across 11 subsystems (actionTint, shields, preDeaths, actions, things, tumors, tumorDamage, auras, popRespawn, survival, tintObs).

```bash
nim r -d:stepTiming -d:release --path:src tribal_village.nim
```

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TV_STEP_TIMING` | -1 | Step to start timing (-1 = disabled) |
| `TV_STEP_TIMING_WINDOW` | 0 | Number of steps to time (0 = all remaining) |
| `TV_TIMING_INTERVAL` | 100 | Report interval in steps |

### `-d:stepTiming` + AI timing &mdash; AI decision profiling

When `TV_AI_TIMING=1` is set alongside `-d:stepTiming`, reports per-agent decision times.

```bash
TV_AI_TIMING=1 TV_AI_TIMING_INTERVAL=50 \
  nim r -d:stepTiming -d:release --path:src tribal_village.nim
```

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TV_AI_TIMING` | 0 | Enable AI timing (1 = enabled) |
| `TV_AI_TIMING_INTERVAL` | 100 | Report interval in steps |
| `TV_AI_TIMING_TOP_N` | 10 | Number of slowest agents to show |

Reports total AI decision time (avg/max per step) and top-N slowest agents by cumulative decision time.

### `-d:renderTiming` &mdash; Frame-level render profiling

Enables per-frame render timing.

```bash
TV_RENDER_TIMING=100 TV_RENDER_TIMING_WINDOW=50 \
  nim r -d:renderTiming -d:release --path:src tribal_village.nim
```

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TV_RENDER_TIMING` | -1 | Frame to start timing (-1 = disabled) |
| `TV_RENDER_TIMING_WINDOW` | 0 | Number of frames to time |
| `TV_RENDER_TIMING_EVERY` | 1 | Log every N frames |
| `TV_RENDER_TIMING_EXIT` | -1 | Exit after this frame (-1 = disabled) |

### `-d:perfRegression` &mdash; Performance regression detection

Sliding-window statistics for per-subsystem mean, P95, and P99 latencies. Supports baseline capture and CI regression gates.

```bash
# Capture baseline
TV_PERF_SAVE_BASELINE=baselines/baseline.json \
  nim c -r -d:perfRegression -d:release --path:src scripts/benchmark_steps.nim

# Check for regressions (CI mode)
TV_PERF_BASELINE=baselines/baseline.json TV_PERF_FAIL_ON_REGRESSION=1 \
  nim c -r -d:perfRegression -d:release --path:src scripts/benchmark_steps.nim
```

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TV_PERF_BASELINE` | "" | Path to baseline JSON for comparison |
| `TV_PERF_THRESHOLD` | 10 | Regression threshold percentage |
| `TV_PERF_WINDOW` | 100 | Sliding window size in steps |
| `TV_PERF_INTERVAL` | 100 | Report interval in steps |
| `TV_PERF_SAVE_BASELINE` | "" | Path to save captured baseline |
| `TV_PERF_FAIL_ON_REGRESSION` | "0" | Exit non-zero on regression (CI mode) |

### `-d:actionFreqCounter` &mdash; Action distribution by unit type

Tracks per-step action distribution across 11 action verbs and 31 unit types.

```bash
TV_ACTION_FREQ_INTERVAL=100 \
  nim c -r -d:actionFreqCounter -d:release --path:src tribal_village.nim
```

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TV_ACTION_FREQ_INTERVAL` | 100 | Report interval in steps |

### `-d:spatialAutoTune` &mdash; Density-based spatial index auto-tuning

Automatically adapts spatial index cell size based on entity density. Includes hotspot detection that shrinks cells when clusters are found.

```bash
nim c -r -d:spatialAutoTune -d:release --path:src tribal_village.nim
```

Constants (defined in `src/types.nim`):
- `SpatialAutoTuneThreshold = 32` (max entities per cell before rebalance)
- `SpatialMinCellSize = 4`, `SpatialMaxCellSize = 64`
- `SpatialAutoTuneInterval = 100` (steps between density checks)

### `-d:spatialStats` &mdash; Spatial query efficiency stats

Tracks per-query-type metrics: total queries, cells scanned, things examined, hits, misses.

```bash
TV_SPATIAL_STATS_INTERVAL=100 \
  nim c -r -d:spatialStats -d:release --path:src tribal_village.nim
```

### `-d:flameGraph` &mdash; Flame graph profiling

Per-step CPU sampling in collapsed stack format (compatible with flamegraph.pl, speedscope).

```bash
TV_FLAME_OUTPUT=profile.folded TV_FLAME_SAMPLE=1 \
  nim c -r -d:flameGraph -d:release --path:src tribal_village.nim
```

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TV_FLAME_OUTPUT` | "flame_graph.folded" | Output file path |
| `TV_FLAME_INTERVAL` | 100 | Flush to disk every N steps |
| `TV_FLAME_SAMPLE` | 1 | Sample every N steps |

## Running Benchmarks

The `make benchmark` target runs 1000 measured steps (after 100 warmup steps) and saves a baseline:

```bash
make benchmark
```

This compiles and runs `scripts/benchmark_steps.nim` with `-d:perfRegression`, saving results to `baselines/benchmark.json`.

Configure via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_PERF_STEPS` | 1000 | Number of steps to measure |
| `TV_PERF_SEED` | 42 | Random seed for reproducibility |
| `TV_PERF_WARMUP` | 100 | Warmup steps before measurement |

Output includes wall-clock time, per-step latency statistics (mean, P50, P95, P99, min, max), steps/second throughput, and per-subsystem breakdown.

## Visual Features (QA Checklist)

### Water Ripple Effects (#259)

- [ ] Ripples appear when non-water units walk through water terrain
- [ ] Ripples expand outward from 20% to 100% scale over 16 frames
- [ ] Ripples fade with quadratic alpha (max 0.5 for subtle effect)
- [ ] Light cyan/blue tint: `color(0.5, 0.7, 0.9, alpha)`
- [ ] Pool capacity starts at 64, grows as needed
- [ ] Expired ripples are removed cleanly (no visual artifacts)

Key files: `src/types.nim` (WaterRipple type), `src/environment.nim` (spawnWaterRipple), `src/step.nim` (stepDecayWaterRipples), `src/renderer.nim` (drawWaterRipples)

### Torch/Fire Flicker (#258)

- [ ] Lanterns show organic flickering brightness variation (3 combined sine waves)
- [ ] Each lantern flickers independently (position-based phase offset)
- [ ] Brightness varies by +/-12% (`LanternFlickerAmplitude = 0.12`)
- [ ] Magma pools show slower warm glow pulsing (+/-8%, `MagmaGlowAmplitude = 0.08`)
- [ ] Magma tint is warm: reddish-orange bias
- [ ] No brightness overflow (clamped to 1.2 max)

Key file: `src/renderer.nim`

## Bug Fixes

### fogVisibility Fix (#260, #262)

Fixed `drawVisualRanges()` in `src/renderer.nim` which referenced an undeclared `visibility` variable instead of `fogVisibility`. Two commits addressed all occurrences.

### Double-Kill Crash Fix (tv-cb72a)

Prevented garrison tower volley crashes where units could be killed twice by the same attack. Three guards added:
- `killAgent()`: skip agents with invalid ID or already terminated
- `applyAgentDamage()`: skip invalid/terminated targets
- Tower/TownCenter volleys: skip targets killed by earlier arrows in the same volley

Key files: `src/combat.nim`, `src/step.nim`

## Performance Optimizations

### Spatial Index Pre-Computation (#249)

Pre-computed lookup tables replace runtime calculations:
- **Distance-to-cell-radius tables**: O(1) conversion replacing runtime division, pre-computed for distances 0-511 pixels
- **Neighbor cell offset lists**: Pre-computed (dx, dy) pairs for each radius (0-32), sorted by Chebyshev distance for early-exit optimization. ~68KB storage

Key file: `src/spatial_index.nim`

### Tower Memory Optimization

Eliminated per-call heap allocations in tower/TC attack and ungarrison operations by reusing pre-allocated Environment buffers (`tempTowerTargets`, `tempTCTargets`, `tempEmptyTiles`). In-place swap-and-pop filtering replaces secondary allocations.

Key file: `src/step.nim`

### Pathfinding Audit (#254)

Documented pathfinding and movement calculation overhead. See `docs/performance_optimization_roadmap.md`.

### Spatial Index Hotspots Audit (#252)

Profiled 10M+ spatial queries over 500 steps. Key finding: `collectThings` accounts for 83% of queries (8,158/step). Identified 40-50% reduction potential through resource position caching, staggered gathering search, and narrower enemy search radii. See `docs/analysis/spatial_stats_audit.md`.

## Cleanup

### Dead Import Cleanup (#256)

Removed unused imports and fixed unused variable warnings across `src/ffi.nim` and test files. Renamed generic `result` variables to specific names (e.g. `buyResult`, `sellResult`) for clarity.

## Known Issues and Follow-Up Work

- **Spatial query optimization**: `collectThings` hotspot (83% of queries) has 40-50% reduction potential but requires implementation of resource caching and staggered search (see `docs/analysis/spatial_stats_audit.md`)
- **Enemy search radius**: Current `enemyRadius ~ 50 tiles` could be reduced to 30 for ~50% fewer thing examinations
- **tempTowerRemovals**: Still `seq[Thing]` with O(n) containment checks; converting to `HashSet` would provide O(1) lookups (see `docs/performance_optimization_roadmap.md`)
- **canEnterForMove heap allocation**: Lantern spacing check still allocates local `seq[Thing]`; could use pre-allocated buffer (see `docs/performance_optimization_roadmap.md`)
