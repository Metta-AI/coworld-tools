## spatial_index.nim - Spatial partitioning for O(1) nearest-thing queries
##
## This module provides procedures for maintaining and querying a cell-based
## spatial index for efficient nearest-neighbor queries.
##
## IMPORTANT: Always use these spatial queries instead of manual grid scans!
## Manual iteration over grid cells is O(n²) and causes performance issues.
## These spatial queries are O(1) amortized through cell-based partitioning.
##
## Architecture:
##   - World is partitioned into SpatialCellSize×SpatialCellSize cells
##   - Each cell maintains a seq of Things in that cell
##   - Queries examine cells within search radius
##   - When compiled with -d:spatialAutoTune, cell size adapts to entity density
##
## Maintenance:
##   - addToSpatialIndex(env, thing) - when a thing is added
##   - removeFromSpatialIndex(env, thing) - when a thing is removed
##   - updateSpatialIndex(env, thing, oldPos) - when a thing moves
##   - rebuildSpatialIndex(env) - rebuild from scratch after major changes
##
## Query Utilities (use these!):
##   - findNearestThingSpatial(env, pos, kind, maxDist) - nearest of one kind
##   - findNearestThingOfKindsSpatial(env, pos, kinds, maxDist) - nearest of multiple kinds
##   - findNearestFriendlyThingSpatial(env, pos, teamId, kind, maxDist) - nearest friendly
##   - findNearestEnemyAgentSpatial(env, pos, teamId, maxDist) - nearest enemy agent
##   - findNearestEnemyBuildingSpatial(env, pos, teamId, maxDist) - nearest enemy building
##   - findNearestEnemyInRangeSpatial(env, pos, teamId, minRange, maxRange) - enemy in range band
##   - collectEnemiesInRangeSpatial(env, pos, teamId, maxRange, targets) - all enemies in range
##   - collectAlliesInRangeSpatial(env, pos, teamId, maxRange, allies) - all allies in range
##   - collectThingsInRangeSpatial(env, pos, kind, maxRange, targets) - all of kind in range
##   - collectAgentsByClassInRange(env, pos, teamId, classes, maxRange, targets) - agents by unit class

import std/algorithm
import vmath
import types, registry

# ---------------------------------------------------------------------------
# Pre-computed lookup tables for O(1) distance-to-cell-radius conversion
# Replaces runtime division: (dist + cellSz - 1) div cellSz
# ---------------------------------------------------------------------------

const
  ## Maximum distance for lookup tables (covers max map diagonal ~500)
  MaxLookupDist* = 512

  ## Pre-computed distance-to-cell-radius for SpatialCellSize=16
  ## DistToCellRadius16[d] = (d + 15) div 16 = ceil(d / 16)
  DistToCellRadius16*: array[MaxLookupDist, int16] = block:
    var result: array[MaxLookupDist, int16]
    for dist in 0 ..< MaxLookupDist:
      result[dist] = int16((dist + 16 - 1) div 16)
    result

when defined(spatialAutoTune):
  const
    ## Lookup tables for each supported cell size in auto-tune mode
    DistToCellRadius4*: array[MaxLookupDist, int16] = block:
      var result: array[MaxLookupDist, int16]
      for dist in 0 ..< MaxLookupDist:
        result[dist] = int16((dist + 4 - 1) div 4)
      result

    DistToCellRadius8*: array[MaxLookupDist, int16] = block:
      var result: array[MaxLookupDist, int16]
      for dist in 0 ..< MaxLookupDist:
        result[dist] = int16((dist + 8 - 1) div 8)
      result

    DistToCellRadius32*: array[MaxLookupDist, int16] = block:
      var result: array[MaxLookupDist, int16]
      for dist in 0 ..< MaxLookupDist:
        result[dist] = int16((dist + 32 - 1) div 32)
      result

    DistToCellRadius64*: array[MaxLookupDist, int16] = block:
      var result: array[MaxLookupDist, int16]
      for dist in 0 ..< MaxLookupDist:
        result[dist] = int16((dist + 64 - 1) div 64)
      result

  proc distToCellRadiusLookup*(dist: int, cellSize: int): int {.inline.} =
    ## O(1) distance-to-cell-radius using pre-computed lookup tables
    ## Falls back to runtime division for unsupported cell sizes
    let clampedDist = min(dist, MaxLookupDist - 1)
    case cellSize
    of 4: DistToCellRadius4[clampedDist].int
    of 8: DistToCellRadius8[clampedDist].int
    of 16: DistToCellRadius16[clampedDist].int
    of 32: DistToCellRadius32[clampedDist].int
    of 64: DistToCellRadius64[clampedDist].int
    else: (dist + cellSize - 1) div cellSize  # Fallback for unexpected sizes

proc distToCellRadius16*(dist: int): int {.inline.} =
  ## O(1) distance-to-cell-radius for static cell size (16)
  DistToCellRadius16[min(dist, MaxLookupDist - 1)].int

# ---------------------------------------------------------------------------
# Pre-computed neighbor cell offset lists for O(1) spatial query setup
# Replaces runtime nested loop: for dx in -r..r: for dy in -r..r
# ---------------------------------------------------------------------------

const
  ## Maximum cell radius to pre-compute (32 cells * 16 pixels = 512 pixel radius)
  MaxPrecomputedRadius* = 32

  ## Cell offset type - stores (dx, dy) as int8 to minimize memory
  ## Chebyshev distance is implicit: max(|dx|, |dy|)

type
  CellOffset* = object
    dx*, dy*: int8

const
  ## Pre-computed neighbor offsets for each radius, sorted by Chebyshev distance.
  ## NeighborOffsets[r] contains all (dx, dy) pairs where max(|dx|, |dy|) <= r,
  ## sorted so closer cells come first (enables early exit optimization).
  ##
  ## Memory: ~68KB for radius 0-32 (worst case (2r+1)² entries per radius)
  NeighborOffsets*: array[MaxPrecomputedRadius + 1, seq[CellOffset]] = block:
    var result: array[MaxPrecomputedRadius + 1, seq[CellOffset]]
    for radius in 0 .. MaxPrecomputedRadius:
      var offsets: seq[CellOffset] = @[]
      # Generate all offsets within this radius
      for dx in -radius .. radius:
        for dy in -radius .. radius:
          offsets.add(CellOffset(dx: int8(dx), dy: int8(dy)))
      # Sort by Chebyshev distance (max of abs values) for early exit optimization
      # Stable sort preserves spatial locality within same distance
      offsets.sort do (a, b: CellOffset) -> int:
        let distA = max(abs(a.dx.int), abs(a.dy.int))
        let distB = max(abs(b.dx.int), abs(b.dy.int))
        distA - distB
      result[radius] = offsets
    result

  ## Count of offsets per radius (for bounds checking and stats)
  NeighborOffsetCounts*: array[MaxPrecomputedRadius + 1, int] = block:
    var result: array[MaxPrecomputedRadius + 1, int]
    for radius in 0 .. MaxPrecomputedRadius:
      result[radius] = (2 * radius + 1) * (2 * radius + 1)
    result

when defined(spatialStats):
  var
    neighborCacheHits*: int = 0
    neighborCacheMisses*: int = 0

when defined(spatialStats):
  import std/strutils
  import envconfig

  type
    SpatialQueryKind* = enum
      sqkFindNearest, sqkFindNearestFriendly, sqkFindNearestEnemy,
      sqkFindNearestEnemyInRange, sqkCollectEnemies, sqkCollectAllies,
      sqkFindNearestOfKinds, sqkCollectThings, sqkCollectAgentsByClass

  var
    spatialTotalQueries*: array[SpatialQueryKind, int]
    spatialTotalCellsScanned*: array[SpatialQueryKind, int]
    spatialTotalThingsExamined*: array[SpatialQueryKind, int]
    spatialTotalHits*: array[SpatialQueryKind, int]
    spatialTotalMisses*: array[SpatialQueryKind, int]
    spatialReportInterval*: int = 100
    spatialStepCounter*: int = 0

  spatialReportInterval = parseEnvInt("TV_SPATIAL_STATS_INTERVAL", spatialReportInterval)

  proc resetSpatialCounters*() =
    for k in SpatialQueryKind:
      spatialTotalQueries[k] = 0
      spatialTotalCellsScanned[k] = 0
      spatialTotalThingsExamined[k] = 0
      spatialTotalHits[k] = 0
      spatialTotalMisses[k] = 0
    neighborCacheHits = 0
    neighborCacheMisses = 0

  proc printSpatialReport*() =
    inc spatialStepCounter
    if spatialReportInterval <= 0 or spatialStepCounter mod spatialReportInterval != 0:
      return

    let stepStart = spatialStepCounter - spatialReportInterval + 1
    echo ""
    echo "=== Spatial Index Report (steps " & $stepStart & "-" & $spatialStepCounter & ") ==="

    const header = "Query Type                 Queries  Cells/Q  Things/Q      Hits   Misses   Hit%"
    const separator = "-------------------------------------------------------------------------------"
    echo header
    echo separator

    const names: array[SpatialQueryKind, string] = [
      "findNearest", "findNearestFriendly", "findNearestEnemy",
      "findNearestEnemyInRange", "collectEnemies", "collectAllies",
      "findNearestOfKinds", "collectThings", "collectAgentsByClass"
    ]

    proc fmtFloat1(v: float64): string =
      let i = int(v * 10 + 0.5)
      $int(i div 10) & "." & $int(i mod 10)

    var totalQ, totalC, totalT, totalH, totalM: int
    for k in SpatialQueryKind:
      let q = spatialTotalQueries[k]
      if q == 0:
        echo alignLeft(names[k], 26) & " " & align("0", 8) &
          align("-", 9) & align("-", 11) & align("-", 10) &
          align("-", 9) & align("-", 7)
        continue
      let avgCells = spatialTotalCellsScanned[k].float64 / q.float64
      let avgThings = spatialTotalThingsExamined[k].float64 / q.float64
      let h = spatialTotalHits[k]
      let m = spatialTotalMisses[k]
      let hitPct = if h + m > 0: (h.float64 / (h + m).float64) * 100.0 else: 0.0
      echo alignLeft(names[k], 26) & " " & align($q, 8) &
        align(fmtFloat1(avgCells), 9) & align(fmtFloat1(avgThings), 11) &
        align($h, 10) & align($m, 9) & align(fmtFloat1(hitPct) & "%", 7)
      totalQ += q; totalC += spatialTotalCellsScanned[k]
      totalT += spatialTotalThingsExamined[k]; totalH += h; totalM += m

    echo separator
    if totalQ > 0:
      let avgC = totalC.float64 / totalQ.float64
      let avgT = totalT.float64 / totalQ.float64
      let hitPct = if totalH + totalM > 0: (totalH.float64 / (totalH + totalM).float64) * 100.0 else: 0.0
      echo alignLeft("TOTAL", 26) & " " & align($totalQ, 8) &
        align(fmtFloat1(avgC), 9) & align(fmtFloat1(avgT), 11) &
        align($totalH, 10) & align($totalM, 9) & align(fmtFloat1(hitPct) & "%", 7)
    echo ""

    # Report neighbor offset cache stats
    let cacheTotal = neighborCacheHits + neighborCacheMisses
    if cacheTotal > 0:
      let cachePct = (neighborCacheHits.float64 / cacheTotal.float64) * 100.0
      echo "Neighbor Cache: " & $neighborCacheHits & " hits, " & $neighborCacheMisses &
        " misses (" & fmtFloat1(cachePct) & "% hit rate)"
      echo "Memory: ~" & $(NeighborOffsetCounts[MaxPrecomputedRadius] * sizeof(CellOffset) *
        (MaxPrecomputedRadius + 1) div 1024) & "KB for pre-computed offsets"
      echo ""

    resetSpatialCounters()

proc cellCoords*(pos: IVec2): tuple[cx, cy: int] {.inline.} =
  ## Convert world position to cell coordinates
  result.cx = clamp(pos.x.int div SpatialCellSize, 0, SpatialCellsX - 1)
  result.cy = clamp(pos.y.int div SpatialCellSize, 0, SpatialCellsY - 1)

# ---------------------------------------------------------------------------
# Auto-tune: adaptive cell sizing based on entity density
# Enabled with -d:spatialAutoTune
# ---------------------------------------------------------------------------

when defined(spatialAutoTune):
  proc dynCellCoords(si: SpatialIndex, pos: IVec2): tuple[cx, cy: int] {.inline.} =
    ## Convert world position to dynamic grid cell coordinates
    result.cx = clamp(pos.x.int div si.activeCellSize, 0, si.activeCellsX - 1)
    result.cy = clamp(pos.y.int div si.activeCellSize, 0, si.activeCellsY - 1)

  proc initDynGrid*(si: var SpatialIndex, cellSize: int) =
    ## Initialize or resize the dynamic grid to the given cell size
    si.activeCellSize = cellSize
    si.activeCellsX = (MapWidth + cellSize - 1) div cellSize
    si.activeCellsY = (MapHeight + cellSize - 1) div cellSize
    si.dynCells = newSeq[seq[SpatialCell]](si.activeCellsX)
    for cx in 0 ..< si.activeCellsX:
      si.dynCells[cx] = newSeq[SpatialCell](si.activeCellsY)
    for kind in ThingKind:
      si.dynKindCells[kind] = newSeq[seq[seq[Thing]]](si.activeCellsX)
      for cx in 0 ..< si.activeCellsX:
        si.dynKindCells[kind][cx] = newSeq[seq[Thing]](si.activeCellsY)

  proc clearDynGrid(si: var SpatialIndex) =
    ## Clear all entities from the dynamic grid without resizing
    for cx in 0 ..< si.activeCellsX:
      for cy in 0 ..< si.activeCellsY:
        si.dynCells[cx][cy].things.setLen(0)
        for kind in ThingKind:
          si.dynKindCells[kind][cx][cy].setLen(0)

  proc ensureDynGrid(si: var SpatialIndex) {.inline.} =
    ## Lazily initialize the dynamic grid if not yet set up
    if si.activeCellSize == 0:
      si.initDynGrid(SpatialCellSize)

  proc analyzeCellDensity*(si: SpatialIndex): tuple[maxCount, totalCount, nonEmpty: int] =
    ## Analyze entity density across all dynamic grid cells
    var maxCount, totalCount, nonEmpty: int
    for cx in 0 ..< si.activeCellsX:
      for cy in 0 ..< si.activeCellsY:
        let count = si.dynCells[cx][cy].things.len
        if count > 0:
          inc nonEmpty
          totalCount += count
          if count > maxCount:
            maxCount = count
    (maxCount, totalCount, nonEmpty)

  proc computeOptimalCellSizeFromDensity*(totalEntities: int): int =
    ## Calculate optimal cell size based on total entity count on the map.
    ## Uses the formula: cell_size = sqrt(map_area * target_per_cell / total_entities)
    ## This ensures each cell has approximately target_per_cell entities on average.
    const
      MapArea = MapWidth * MapHeight
      TargetPerCell = SpatialAutoTuneThreshold div 4  # Target ~8 entities per cell

    if totalEntities <= 0:
      # Very few entities: use large cells to minimize overhead
      return SpatialMaxCellSize

    # Calculate optimal area per cell to achieve target density
    let optimalAreaPerCell = MapArea * TargetPerCell div totalEntities

    # Cell size is sqrt of area (cells are square)
    # Use integer sqrt approximation: find largest power of 2 that fits
    var cellSize = SpatialMinCellSize
    while cellSize * cellSize * 4 <= optimalAreaPerCell and cellSize < SpatialMaxCellSize:
      cellSize = cellSize * 2

    # Clamp to valid range
    result = clamp(cellSize, SpatialMinCellSize, SpatialMaxCellSize)

  proc computeOptimalCellSize*(si: SpatialIndex): int =
    ## Determine if the cell size should change based on current density.
    ## Returns the recommended cell size.
    ## Primary: density-based calculation from total entity count
    ## Secondary: hotspot detection for clustered entities
    let (maxCount, totalCount, nonEmpty) = si.analyzeCellDensity()

    # Primary: Calculate cell size based on total unit density
    let densityOptimal = computeOptimalCellSizeFromDensity(totalCount)

    # Secondary: Check for hotspots that need finer partitioning
    # Calculate average occupancy for non-empty cells
    let avgCount = if nonEmpty > 0: totalCount div nonEmpty else: 0

    # Shrink cells if max density is high AND significantly above average
    # This prevents unnecessary shrinking when one outlier cell is dense
    let hotspotThreshold = avgCount * 3  # Cell is a hotspot if 3x average
    let isHotspot = maxCount > hotspotThreshold and maxCount > SpatialAutoTuneThreshold

    if isHotspot and densityOptimal > SpatialMinCellSize:
      # Hotspot detected: use smaller of density-optimal or halved current size
      result = max(min(densityOptimal, si.activeCellSize div 2), SpatialMinCellSize)
    else:
      # No hotspot: use density-optimal size
      result = densityOptimal

  proc resizeDynGrid(env: Environment, newCellSize: int) =
    ## Resize the dynamic grid to a new cell size and repopulate from things list.
    ## This is an incremental operation that doesn't touch the static grid.
    env.spatialIndex.initDynGrid(newCellSize)
    for thing in env.things:
      if not thing.isNil and isValidPos(thing.pos):
        let (dx, dy) = env.spatialIndex.dynCellCoords(thing.pos)
        env.spatialIndex.dynCells[dx][dy].things.add(thing)
        env.spatialIndex.dynKindCells[thing.kind][dx][dy].add(thing)

  proc maybeTuneSpatialIndex*(env: Environment, currentStep: int) =
    ## Periodically check density and rebalance the dynamic grid if needed.
    ## Called from step() every SpatialAutoTuneInterval steps.
    ## This is a lightweight check that only triggers resize when beneficial.
    env.spatialIndex.ensureDynGrid()

    # Check if enough time has passed since last tune
    if currentStep - env.spatialIndex.lastTuneStep < SpatialAutoTuneInterval:
      return

    env.spatialIndex.lastTuneStep = currentStep

    let optimalSize = env.spatialIndex.computeOptimalCellSize()
    if optimalSize != env.spatialIndex.activeCellSize:
      env.resizeDynGrid(optimalSize)

proc clearSpatialIndex*(env: Environment) =
  ## Clear all cells in the spatial index
  for cx in 0 ..< SpatialCellsX:
    for cy in 0 ..< SpatialCellsY:
      env.spatialIndex.cells[cx][cy].things.setLen(0)
      for kind in ThingKind:
        env.spatialIndex.kindCells[kind][cx][cy].setLen(0)
  when defined(spatialAutoTune):
    env.spatialIndex.ensureDynGrid()
    env.spatialIndex.clearDynGrid()

proc addToSpatialIndex*(env: Environment, thing: Thing) =
  ## Add a thing to the spatial index at its current position
  if thing.isNil or not isValidPos(thing.pos):
    return
  let (cx, cy) = cellCoords(thing.pos)
  env.spatialIndex.cells[cx][cy].things.add(thing)
  env.spatialIndex.kindCells[thing.kind][cx][cy].add(thing)
  when defined(spatialAutoTune):
    env.spatialIndex.ensureDynGrid()
    let (dx, dy) = env.spatialIndex.dynCellCoords(thing.pos)
    env.spatialIndex.dynCells[dx][dy].things.add(thing)
    env.spatialIndex.dynKindCells[thing.kind][dx][dy].add(thing)

proc removeFromSpatialIndex*(env: Environment, thing: Thing) =
  ## Remove a thing from the spatial index
  if thing.isNil or not isValidPos(thing.pos):
    return
  let (cx, cy) = cellCoords(thing.pos)

  # Remove from general cell (swap-and-pop for O(1) removal)
  let cellThings = addr env.spatialIndex.cells[cx][cy].things
  for i in 0 ..< cellThings[].len:
    if cellThings[][i] == thing:
      cellThings[][i] = cellThings[][^1]
      cellThings[].setLen(cellThings[].len - 1)
      break

  # Remove from kind-specific cell (swap-and-pop for O(1) removal)
  let kindCellThings = addr env.spatialIndex.kindCells[thing.kind][cx][cy]
  for i in 0 ..< kindCellThings[].len:
    if kindCellThings[][i] == thing:
      kindCellThings[][i] = kindCellThings[][^1]
      kindCellThings[].setLen(kindCellThings[].len - 1)
      break

  when defined(spatialAutoTune):
    env.spatialIndex.ensureDynGrid()
    let (dx, dy) = env.spatialIndex.dynCellCoords(thing.pos)
    # Remove from dynamic general cell
    let dynCellThings = addr env.spatialIndex.dynCells[dx][dy].things
    for i in 0 ..< dynCellThings[].len:
      if dynCellThings[][i] == thing:
        dynCellThings[][i] = dynCellThings[][^1]
        dynCellThings[].setLen(dynCellThings[].len - 1)
        break
    # Remove from dynamic kind-specific cell
    let dynKindThings = addr env.spatialIndex.dynKindCells[thing.kind][dx][dy]
    for i in 0 ..< dynKindThings[].len:
      if dynKindThings[][i] == thing:
        dynKindThings[][i] = dynKindThings[][^1]
        dynKindThings[].setLen(dynKindThings[].len - 1)
        break

proc updateSpatialIndex*(env: Environment, thing: Thing, oldPos: IVec2) =
  ## Update a thing's position in the spatial index
  ## Called when a thing moves from oldPos to thing.pos
  if thing.isNil:
    return

  # Mark agent observations as dirty when they move (for lazy rebuild optimization)
  if thing.kind == Agent:
    env.agentObsDirty[thing.agentId] = true

  let (oldCx, oldCy) = cellCoords(oldPos)
  let (newCx, newCy) = cellCoords(thing.pos)

  # If cell hasn't changed, no update needed
  if oldCx == newCx and oldCy == newCy:
    when defined(spatialAutoTune):
      env.spatialIndex.ensureDynGrid()
      # Dynamic grid may have different cell size; check it too
      let (oldDx, oldDy) = env.spatialIndex.dynCellCoords(oldPos)
      let (newDx, newDy) = env.spatialIndex.dynCellCoords(thing.pos)
      if oldDx == newDx and oldDy == newDy:
        return
      # Static grid unchanged but dynamic grid cell changed
      if isValidPos(oldPos):
        let dynCellThings = addr env.spatialIndex.dynCells[oldDx][oldDy].things
        for i in 0 ..< dynCellThings[].len:
          if dynCellThings[][i] == thing:
            dynCellThings[][i] = dynCellThings[][^1]
            dynCellThings[].setLen(dynCellThings[].len - 1)
            break
        let dynKindThings = addr env.spatialIndex.dynKindCells[thing.kind][oldDx][oldDy]
        for i in 0 ..< dynKindThings[].len:
          if dynKindThings[][i] == thing:
            dynKindThings[][i] = dynKindThings[][^1]
            dynKindThings[].setLen(dynKindThings[].len - 1)
            break
      if isValidPos(thing.pos):
        env.spatialIndex.dynCells[newDx][newDy].things.add(thing)
        env.spatialIndex.dynKindCells[thing.kind][newDx][newDy].add(thing)
    return

  # Remove from old cell (swap-and-pop for O(1) removal)
  if isValidPos(oldPos):
    let cellThings = addr env.spatialIndex.cells[oldCx][oldCy].things
    for i in 0 ..< cellThings[].len:
      if cellThings[][i] == thing:
        cellThings[][i] = cellThings[][^1]
        cellThings[].setLen(cellThings[].len - 1)
        break

    let kindCellThings = addr env.spatialIndex.kindCells[thing.kind][oldCx][oldCy]
    for i in 0 ..< kindCellThings[].len:
      if kindCellThings[][i] == thing:
        kindCellThings[][i] = kindCellThings[][^1]
        kindCellThings[].setLen(kindCellThings[].len - 1)
        break

  # Add to new cell
  if isValidPos(thing.pos):
    env.spatialIndex.cells[newCx][newCy].things.add(thing)
    env.spatialIndex.kindCells[thing.kind][newCx][newCy].add(thing)

  when defined(spatialAutoTune):
    env.spatialIndex.ensureDynGrid()
    let (oldDx, oldDy) = env.spatialIndex.dynCellCoords(oldPos)
    let (newDx, newDy) = env.spatialIndex.dynCellCoords(thing.pos)
    if oldDx != newDx or oldDy != newDy:
      if isValidPos(oldPos):
        let dynCellThings = addr env.spatialIndex.dynCells[oldDx][oldDy].things
        for i in 0 ..< dynCellThings[].len:
          if dynCellThings[][i] == thing:
            dynCellThings[][i] = dynCellThings[][^1]
            dynCellThings[].setLen(dynCellThings[].len - 1)
            break
        let dynKindThings = addr env.spatialIndex.dynKindCells[thing.kind][oldDx][oldDy]
        for i in 0 ..< dynKindThings[].len:
          if dynKindThings[][i] == thing:
            dynKindThings[][i] = dynKindThings[][^1]
            dynKindThings[].setLen(dynKindThings[].len - 1)
            break
      if isValidPos(thing.pos):
        env.spatialIndex.dynCells[newDx][newDy].things.add(thing)
        env.spatialIndex.dynKindCells[thing.kind][newDx][newDy].add(thing)

when defined(spatialAutoTune):
  template forEachInRadius(envExpr: Environment, posExpr: IVec2,
                            kindExpr: ThingKind, maxDistExpr: int,
                            thingVar: untyped, body: untyped) =
    ## Iterates over non-nil things of a given kind within a maximum distance.
    ## Auto-tuned variant using dynamic grid with adaptive cell size.
    ##
    ## **Injected variables:**
    ## - `qPos: IVec2` - The query position (copied from posExpr)
    ## - `searchRadius: int` - Current search radius in cells (mutable - body can
    ##   shrink this for early-exit optimization in findNearest queries)
    ## - `cellsScanned: int` - Debug counter (only with -d:spatialStats)
    ## - `thingsExamined: int` - Debug counter (only with -d:spatialStats)
    ##
    ## **Parameters:**
    ## - `envExpr` - The Environment containing the spatial index
    ## - `posExpr` - Query center position
    ## - `kindExpr` - ThingKind to search for
    ## - `maxDistExpr` - Maximum Chebyshev distance to search
    ## - `thingVar` - Name for the iteration variable (each found Thing)
    ## - `body` - Code to execute for each found thing
    ##
    ## **Example:**
    ## ```nim
    ## var nearest: Thing = nil
    ## var bestDist = int.high
    ## forEachInRadius(env, agentPos, Tree, 10, tree):
    ##   let dist = chebyshevDist(tree.pos, agentPos)
    ##   if dist < bestDist:
    ##     bestDist = dist
    ##     nearest = tree
    ##     searchRadius = distToCellRadius(bestDist)  # Shrink search area
    ## ```
    envExpr.spatialIndex.ensureDynGrid()
    let qPos  {.inject.} = posExpr
    let si = envExpr.spatialIndex
    let cellSz = si.activeCellSize
    let cellsX = si.activeCellsX
    let cellsY = si.activeCellsY
    let qCx = clamp(qPos.x.int div cellSz, 0, cellsX - 1)
    let qCy = clamp(qPos.y.int div cellSz, 0, cellsY - 1)
    let clampedMax = min(maxDistExpr, max(cellsX, cellsY) * cellSz)
    var searchRadius {.inject.} = distToCellRadiusLookup(clampedMax, cellSz)
    let maxRadius = searchRadius
    let queryKind = kindExpr
    let queryEnv  = envExpr
    when defined(spatialStats):
      var cellsScanned {.inject.} = 0
      var thingsExamined {.inject.} = 0

    # Use pre-computed neighbor lists when radius is within cache range
    if maxRadius <= MaxPrecomputedRadius:
      when defined(spatialStats):
        inc neighborCacheHits
      let offsets = NeighborOffsets[maxRadius]
      for offset in offsets:
        # Early exit: offsets are sorted by distance, so if this one exceeds
        # searchRadius (which may have shrunk), all remaining ones will too
        let offsetDist = max(abs(offset.dx.int), abs(offset.dy.int))
        if offsetDist > searchRadius:
          break
        let nx = qCx + offset.dx.int
        let ny = qCy + offset.dy.int
        if nx < 0 or nx >= cellsX or ny < 0 or ny >= cellsY:
          continue
        when defined(spatialStats):
          inc cellsScanned
        for thingVar in queryEnv.spatialIndex.dynKindCells[queryKind][nx][ny]:
          if not thingVar.isNil:
            when defined(spatialStats):
              inc thingsExamined
            body
    else:
      # Fallback to nested loops for large radii (rare case)
      when defined(spatialStats):
        inc neighborCacheMisses
      for dx in -maxRadius .. maxRadius:
        if abs(dx) > searchRadius: continue
        for dy in -maxRadius .. maxRadius:
          if abs(dy) > searchRadius: continue
          let nx = qCx + dx
          let ny = qCy + dy
          if nx < 0 or nx >= cellsX or ny < 0 or ny >= cellsY:
            continue
          when defined(spatialStats):
            inc cellsScanned
          for thingVar in queryEnv.spatialIndex.dynKindCells[queryKind][nx][ny]:
            if not thingVar.isNil:
              when defined(spatialStats):
                inc thingsExamined
              body
else:
  template forEachInRadius(envExpr: Environment, posExpr: IVec2,
                            kindExpr: ThingKind, maxDistExpr: int,
                            thingVar: untyped, body: untyped) =
    ## Iterates over non-nil things of a given kind within a maximum distance.
    ## Fixed-cell-size variant using 16x16 spatial grid.
    ##
    ## **Injected variables:**
    ## - `qPos: IVec2` - The query position (copied from posExpr)
    ## - `searchRadius: int` - Current search radius in cells (mutable - body can
    ##   shrink this for early-exit optimization in findNearest queries)
    ## - `cellsScanned: int` - Debug counter (only with -d:spatialStats)
    ## - `thingsExamined: int` - Debug counter (only with -d:spatialStats)
    ##
    ## **Parameters:**
    ## - `envExpr` - The Environment containing the spatial index
    ## - `posExpr` - Query center position
    ## - `kindExpr` - ThingKind to search for
    ## - `maxDistExpr` - Maximum Chebyshev distance to search
    ## - `thingVar` - Name for the iteration variable (each found Thing)
    ## - `body` - Code to execute for each found thing
    ##
    ## **Example:**
    ## ```nim
    ## var nearest: Thing = nil
    ## var bestDist = int.high
    ## forEachInRadius(env, agentPos, Tree, 10, tree):
    ##   let dist = chebyshevDist(tree.pos, agentPos)
    ##   if dist < bestDist:
    ##     bestDist = dist
    ##     nearest = tree
    ##     searchRadius = distToCellRadius16(bestDist)  # Shrink search area
    ## ```
    let qPos  {.inject.} = posExpr
    let (qCx, qCy) = cellCoords(qPos)
    let clampedMax = min(maxDistExpr, max(SpatialCellsX, SpatialCellsY) * SpatialCellSize)
    var searchRadius {.inject.} = distToCellRadius16(clampedMax)
    let maxRadius = searchRadius
    let queryKind = kindExpr
    let queryEnv  = envExpr
    when defined(spatialStats):
      var cellsScanned {.inject.} = 0
      var thingsExamined {.inject.} = 0

    # Use pre-computed neighbor lists when radius is within cache range
    if maxRadius <= MaxPrecomputedRadius:
      when defined(spatialStats):
        inc neighborCacheHits
      let offsets = NeighborOffsets[maxRadius]
      for offset in offsets:
        # Early exit: offsets are sorted by distance, so if this one exceeds
        # searchRadius (which may have shrunk), all remaining ones will too
        let offsetDist = max(abs(offset.dx.int), abs(offset.dy.int))
        if offsetDist > searchRadius:
          break
        let nx = qCx + offset.dx.int
        let ny = qCy + offset.dy.int
        if nx < 0 or nx >= SpatialCellsX or ny < 0 or ny >= SpatialCellsY:
          continue
        when defined(spatialStats):
          inc cellsScanned
        for thingVar in queryEnv.spatialIndex.kindCells[queryKind][nx][ny]:
          if not thingVar.isNil:
            when defined(spatialStats):
              inc thingsExamined
            body
    else:
      # Fallback to nested loops for large radii (rare case)
      when defined(spatialStats):
        inc neighborCacheMisses
      for dx in -maxRadius .. maxRadius:
        if abs(dx) > searchRadius: continue
        for dy in -maxRadius .. maxRadius:
          if abs(dy) > searchRadius: continue
          let nx = qCx + dx
          let ny = qCy + dy
          if nx < 0 or nx >= SpatialCellsX or ny < 0 or ny >= SpatialCellsY:
            continue
          when defined(spatialStats):
            inc cellsScanned
          for thingVar in queryEnv.spatialIndex.kindCells[queryKind][nx][ny]:
            if not thingVar.isNil:
              when defined(spatialStats):
                inc thingsExamined
              body

# Helper: get effective cell size for searchRadius computation in query procs
template effectiveCellSize(envParam: Environment): int =
  when defined(spatialAutoTune):
    envParam.spatialIndex.ensureDynGrid()
    envParam.spatialIndex.activeCellSize
  else:
    SpatialCellSize

# Helper: O(1) distance-to-cell-radius using lookup tables
template distToCellRadiusEffective(dist: int, cellSz: int): int =
  when defined(spatialAutoTune):
    distToCellRadiusLookup(dist, cellSz)
  else:
    distToCellRadius16(dist)

proc findNearestThingSpatial*(env: Environment, pos: IVec2, kind: ThingKind,
                               maxDist: int): Thing =
  ## Find nearest thing of a given kind using spatial index.
  ## Returns nil if no thing found within maxDist.
  result = nil
  var minDist = int.high
  let cellSz = effectiveCellSize(env)

  forEachInRadius(env, pos, kind, maxDist, thing):
    # Skip things with invalid positions to prevent overflow in distance calculation
    if not isValidPos(thing.pos):
      continue
    let dist = abs(thing.pos.x - qPos.x) + abs(thing.pos.y - qPos.y)
    if dist < minDist and dist < maxDist:
      minDist = dist
      result = thing
      searchRadius = distToCellRadiusEffective(dist, cellSz)

  when defined(spatialStats):
    inc spatialTotalQueries[sqkFindNearest]
    spatialTotalCellsScanned[sqkFindNearest] += cellsScanned
    spatialTotalThingsExamined[sqkFindNearest] += thingsExamined
    if result.isNil: inc spatialTotalMisses[sqkFindNearest]
    else: inc spatialTotalHits[sqkFindNearest]

proc findNearestFriendlyThingSpatial*(env: Environment, pos: IVec2, teamId: int,
                                       kind: ThingKind, maxDist: int): Thing =
  ## Find nearest team-owned thing of a given kind using spatial index.
  ## Optimized: uses bitwise team mask comparison for O(1) team checks.
  result = nil
  var minDist = int.high
  let cellSz = effectiveCellSize(env)
  let teamMask = getTeamMask(teamId)  # Pre-compute for bitwise checks

  forEachInRadius(env, pos, kind, maxDist, thing):
    # Bitwise team check: compare thing's team mask with expected mask
    # For buildings, use thing.teamId directly (not all buildings are agents)
    if (getTeamMask(thing.teamId) and teamMask) == 0:
      continue
    # Skip things with invalid positions to prevent overflow in distance calculation
    if not isValidPos(thing.pos):
      continue
    let dist = abs(thing.pos.x - qPos.x) + abs(thing.pos.y - qPos.y)
    if dist < minDist and dist < maxDist:
      minDist = dist
      result = thing
      searchRadius = distToCellRadiusEffective(dist, cellSz)

  when defined(spatialStats):
    inc spatialTotalQueries[sqkFindNearestFriendly]
    spatialTotalCellsScanned[sqkFindNearestFriendly] += cellsScanned
    spatialTotalThingsExamined[sqkFindNearestFriendly] += thingsExamined
    if result.isNil: inc spatialTotalMisses[sqkFindNearestFriendly]
    else: inc spatialTotalHits[sqkFindNearestFriendly]

proc findNearestEnemyAgentSpatial*(env: Environment, pos: IVec2, teamId: int,
                                    maxDist: int): Thing =
  ## Find nearest enemy agent (alive, different team) using spatial index.
  ## Uses Chebyshev distance for consistency with game mechanics.
  ## Optimized: uses bitwise team mask comparison for O(1) team checks.
  result = nil
  var minDist = int.high
  let cellSz = effectiveCellSize(env)
  let teamMask = getTeamMask(teamId)  # Pre-compute for bitwise checks

  forEachInRadius(env, pos, Agent, maxDist, thing):
    if not isAgentAlive(env, thing):
      continue
    # Bitwise team check: (thingMask and teamMask) == 0 means different team
    if (getTeamMask(thing) and teamMask) != 0:
      continue
    # Skip things with invalid positions to prevent overflow in distance calculation
    if not isValidPos(thing.pos):
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist <= maxDist and dist < minDist:
      minDist = dist
      result = thing
      searchRadius = distToCellRadiusEffective(dist, cellSz)

  when defined(spatialStats):
    inc spatialTotalQueries[sqkFindNearestEnemy]
    spatialTotalCellsScanned[sqkFindNearestEnemy] += cellsScanned
    spatialTotalThingsExamined[sqkFindNearestEnemy] += thingsExamined
    if result.isNil: inc spatialTotalMisses[sqkFindNearestEnemy]
    else: inc spatialTotalHits[sqkFindNearestEnemy]

proc findNearestEnemyInRangeSpatial*(env: Environment, pos: IVec2, teamId: int,
                                      minRange, maxRange: int): Thing =
  ## Find nearest enemy agent in [minRange, maxRange] Chebyshev distance.
  ## Used by towers and buildings with minimum attack ranges.
  ## Optimized: uses bitwise team mask comparison for O(1) team checks.
  result = nil
  var bestDist = int.high
  let cellSz = effectiveCellSize(env)
  let teamMask = getTeamMask(teamId)  # Pre-compute for bitwise checks

  forEachInRadius(env, pos, Agent, maxRange, thing):
    if not isAgentAlive(env, thing):
      continue
    # Bitwise team check: (thingMask and teamMask) == 0 means different team
    if (getTeamMask(thing) and teamMask) != 0:
      continue
    # Skip things with invalid positions to prevent overflow in distance calculation
    if not isValidPos(thing.pos):
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist >= minRange and dist <= maxRange and dist < bestDist:
      bestDist = dist
      result = thing
      searchRadius = distToCellRadiusEffective(dist, cellSz)

  when defined(spatialStats):
    inc spatialTotalQueries[sqkFindNearestEnemyInRange]
    spatialTotalCellsScanned[sqkFindNearestEnemyInRange] += cellsScanned
    spatialTotalThingsExamined[sqkFindNearestEnemyInRange] += thingsExamined
    if result.isNil: inc spatialTotalMisses[sqkFindNearestEnemyInRange]
    else: inc spatialTotalHits[sqkFindNearestEnemyInRange]

proc collectEnemiesInRangeSpatial*(env: Environment, pos: IVec2, teamId: int,
                                    maxRange: int, targets: var seq[Thing]) =
  ## Collect all enemy agents within maxRange Chebyshev distance.
  ## Used by town centers that need to fire at multiple targets.
  ## Optimized: uses bitwise team mask comparison for O(1) team checks.
  let teamMask = getTeamMask(teamId)  # Pre-compute for bitwise checks
  when defined(spatialStats):
    let prevLen = targets.len
  forEachInRadius(env, pos, Agent, maxRange, thing):
    if not isAgentAlive(env, thing):
      continue
    # Bitwise team check: (thingMask and teamMask) == 0 means different team
    if (getTeamMask(thing) and teamMask) != 0:
      continue
    # Skip things with invalid positions to prevent overflow in distance calculation
    if not isValidPos(thing.pos):
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist <= maxRange:
      targets.add(thing)

  when defined(spatialStats):
    inc spatialTotalQueries[sqkCollectEnemies]
    spatialTotalCellsScanned[sqkCollectEnemies] += cellsScanned
    spatialTotalThingsExamined[sqkCollectEnemies] += thingsExamined
    let found = targets.len - prevLen
    if found > 0: inc spatialTotalHits[sqkCollectEnemies]
    else: inc spatialTotalMisses[sqkCollectEnemies]

proc collectAlliesInRangeSpatial*(env: Environment, pos: IVec2, teamId: int,
                                    maxRange: int, allies: var seq[Thing]) =
  ## Collect all allied agents within maxRange Chebyshev distance.
  ## Optimized: uses bitwise team mask comparison for O(1) team checks.
  let teamMask = getTeamMask(teamId)  # Pre-compute for bitwise checks
  when defined(spatialStats):
    let prevLen = allies.len
  forEachInRadius(env, pos, Agent, maxRange, thing):
    if not isAgentAlive(env, thing):
      continue
    # Bitwise team check: (thingMask and teamMask) != 0 means same team
    if (getTeamMask(thing) and teamMask) == 0:
      continue
    # Skip things with invalid positions to prevent overflow in distance calculation
    if not isValidPos(thing.pos):
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist <= maxRange:
      allies.add(thing)

  when defined(spatialStats):
    inc spatialTotalQueries[sqkCollectAllies]
    spatialTotalCellsScanned[sqkCollectAllies] += cellsScanned
    spatialTotalThingsExamined[sqkCollectAllies] += thingsExamined
    let found = allies.len - prevLen
    if found > 0: inc spatialTotalHits[sqkCollectAllies]
    else: inc spatialTotalMisses[sqkCollectAllies]

proc countAlliesInRangeSpatial*(env: Environment, pos: IVec2, teamId: int,
                                  maxRange: int, excludeAgentId: int = -1): int =
  ## Count allied agents within maxRange Chebyshev distance.
  ## Allocation-free alternative to collectAlliesInRangeSpatial.
  ## If excludeAgentId >= 0, that agent is excluded from the count.
  let teamMask = getTeamMask(teamId)
  result = 0
  forEachInRadius(env, pos, Agent, maxRange, thing):
    if not isAgentAlive(env, thing):
      continue
    if (getTeamMask(thing) and teamMask) == 0:
      continue
    if not isValidPos(thing.pos):
      continue
    if thing.agentId == excludeAgentId:
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist <= maxRange:
      inc result

proc countEnemiesInRangeSpatial*(env: Environment, pos: IVec2, teamId: int,
                                   maxRange: int): int =
  ## Count enemy agents within maxRange Chebyshev distance.
  ## Allocation-free alternative to collectEnemiesInRangeSpatial.
  let teamMask = getTeamMask(teamId)
  result = 0
  forEachInRadius(env, pos, Agent, maxRange, thing):
    if not isAgentAlive(env, thing):
      continue
    if (getTeamMask(thing) and teamMask) != 0:
      continue
    if not isValidPos(thing.pos):
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist <= maxRange:
      inc result

proc hasAllyInRangeSpatial*(env: Environment, pos: IVec2, teamId: int,
                              maxRange: int, excludeAgentId: int): bool =
  ## Check if any ally (excluding excludeAgentId) is within maxRange.
  ## Early-exit, allocation-free alternative to collectAlliesInRangeSpatial.
  let teamMask = getTeamMask(teamId)
  forEachInRadius(env, pos, Agent, maxRange, thing):
    if not isAgentAlive(env, thing):
      continue
    if (getTeamMask(thing) and teamMask) == 0:
      continue
    if not isValidPos(thing.pos):
      continue
    if thing.agentId == excludeAgentId:
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist <= maxRange:
      return true
  return false

proc findNearestThingOfKindsSpatial*(env: Environment, pos: IVec2,
                                      kinds: set[ThingKind], maxDist: int): Thing =
  ## Find nearest thing matching any of the given kinds using spatial index.
  ## Searches all specified kinds and returns the closest match.
  ## Returns nil if no matching thing found within maxDist.
  ## Uses Chebyshev distance for consistency with game mechanics.
  result = nil
  var minDist = int.high
  when defined(spatialStats):
    var totalCellsScanned = 0
    var totalThingsExamined = 0

  for kind in kinds:
    forEachInRadius(env, pos, kind, maxDist, thing):
      # Skip things with invalid positions to prevent overflow in distance calculation
      if not isValidPos(thing.pos):
        continue
      let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
      if dist <= maxDist and dist < minDist:
        minDist = dist
        result = thing
    when defined(spatialStats):
      totalCellsScanned += cellsScanned
      totalThingsExamined += thingsExamined

  when defined(spatialStats):
    inc spatialTotalQueries[sqkFindNearestOfKinds]
    spatialTotalCellsScanned[sqkFindNearestOfKinds] += totalCellsScanned
    spatialTotalThingsExamined[sqkFindNearestOfKinds] += totalThingsExamined
    if result.isNil: inc spatialTotalMisses[sqkFindNearestOfKinds]
    else: inc spatialTotalHits[sqkFindNearestOfKinds]

proc collectThingsInRangeSpatial*(env: Environment, pos: IVec2, kind: ThingKind,
                                   maxRange: int, targets: var seq[Thing]) =
  ## Collect all things of the given kind within maxRange Chebyshev distance.
  ## Generic collection utility for any ThingKind.
  when defined(spatialStats):
    let prevLen = targets.len
  forEachInRadius(env, pos, kind, maxRange, thing):
    # Skip things with invalid positions to prevent overflow in distance calculation
    if not isValidPos(thing.pos):
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist <= maxRange:
      targets.add(thing)

  when defined(spatialStats):
    inc spatialTotalQueries[sqkCollectThings]
    spatialTotalCellsScanned[sqkCollectThings] += cellsScanned
    spatialTotalThingsExamined[sqkCollectThings] += thingsExamined
    let found = targets.len - prevLen
    if found > 0: inc spatialTotalHits[sqkCollectThings]
    else: inc spatialTotalMisses[sqkCollectThings]

proc collectAgentsByClassInRange*(env: Environment, pos: IVec2, teamId: int,
                                   classes: set[AgentUnitClass], maxRange: int,
                                   targets: var seq[Thing]) =
  ## Collect all agents of specified unit classes within maxRange.
  ## teamId: -1 for any team, 0+ for specific team filtering.
  ## Uses Chebyshev distance for consistency with game mechanics.
  let teamMask = if teamId >= 0: getTeamMask(teamId) else: 0
  when defined(spatialStats):
    let prevLen = targets.len
  forEachInRadius(env, pos, Agent, maxRange, thing):
    if not isAgentAlive(env, thing):
      continue
    # Team filtering: if teamId >= 0, require same team
    if teamId >= 0 and (getTeamMask(thing) and teamMask) == 0:
      continue
    # Unit class filtering
    if thing.unitClass notin classes:
      continue
    # Skip things with invalid positions to prevent overflow in distance calculation
    if not isValidPos(thing.pos):
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist <= maxRange:
      targets.add(thing)

  when defined(spatialStats):
    inc spatialTotalQueries[sqkCollectAgentsByClass]
    spatialTotalCellsScanned[sqkCollectAgentsByClass] += cellsScanned
    spatialTotalThingsExamined[sqkCollectAgentsByClass] += thingsExamined
    let found = targets.len - prevLen
    if found > 0: inc spatialTotalHits[sqkCollectAgentsByClass]
    else: inc spatialTotalMisses[sqkCollectAgentsByClass]

proc countUnclaimedTumorsInRangeSpatial*(env: Environment, pos: IVec2,
                                          maxRange: int): int =
  ## Count unclaimed tumors within maxRange Chebyshev distance.
  ## Used by spawners to limit tumor density around them.
  result = 0
  forEachInRadius(env, pos, Tumor, maxRange, thing):
    if not isValidPos(thing.pos):
      continue
    if thing.hasClaimedTerritory:
      continue
    let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
    if dist <= maxRange:
      inc result

proc rebuildSpatialIndex*(env: Environment) =
  ## Rebuild the entire spatial index from scratch
  ## Useful for initialization or after major map changes
  clearSpatialIndex(env)
  for thing in env.things:
    addToSpatialIndex(env, thing)
  when defined(spatialAutoTune):
    # Analyze density and rebalance if needed
    let optimalSize = env.spatialIndex.computeOptimalCellSize()
    if optimalSize != env.spatialIndex.activeCellSize:
      env.spatialIndex.initDynGrid(optimalSize)
      # Repopulate dynamic grid with new cell size
      for thing in env.things:
        if not thing.isNil and isValidPos(thing.pos):
          let (dx, dy) = env.spatialIndex.dynCellCoords(thing.pos)
          env.spatialIndex.dynCells[dx][dy].things.add(thing)
          env.spatialIndex.dynKindCells[thing.kind][dx][dy].add(thing)

# Military unit classes that draw predator aggro (fighters)
const PredatorFighterClasses = {UnitManAtArms, UnitArcher, UnitScout, UnitKnight}

proc findNearestPredatorTargetSpatial*(env: Environment, center: IVec2,
                                        maxDist: int): IVec2 =
  ## Find nearest predator target using spatial index.
  ## Priority: tumor (unclaimed) > fighter agent > villager agent.
  ## Returns ivec2(-1, -1) if no target found.
  ## Uses Chebyshev distance for consistency with game mechanics.
  var bestTumorDist = int.high
  var bestTumor = ivec2(-1, -1)
  var bestFighterDist = int.high
  var bestFighter = ivec2(-1, -1)
  var bestVillagerDist = int.high
  var bestVillager = ivec2(-1, -1)

  # Search for tumors (unclaimed only)
  block tumorSearch:
    forEachInRadius(env, center, Tumor, maxDist, thing):
      if not isValidPos(thing.pos):
        continue
      if thing.hasClaimedTerritory:
        continue
      let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
      if dist <= maxDist and dist < bestTumorDist:
        bestTumorDist = dist
        bestTumor = thing.pos

  # Search for agents (alive, categorized by fighter vs villager)
  block agentSearch:
    forEachInRadius(env, center, Agent, maxDist, thing):
      if not isAgentAlive(env, thing):
        continue
      if not isValidPos(thing.pos):
        continue
      let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
      if dist > maxDist:
        continue
      if thing.unitClass in PredatorFighterClasses:
        if dist < bestFighterDist:
          bestFighterDist = dist
          bestFighter = thing.pos
      else:
        if dist < bestVillagerDist:
          bestVillagerDist = dist
          bestVillager = thing.pos

  # Priority: tumor > fighter > villager
  if bestTumor.x >= 0: bestTumor
  elif bestFighter.x >= 0: bestFighter
  else: bestVillager

# Building kinds that can be enemy-owned (have teamId >= 0 in gameplay)
# This includes all player-buildable and team-assigned buildings
const TeamBuildingKinds* = {
  Altar, TownCenter, House, Door, ClayOven, WeavingLoom, Outpost, GuardTower,
  Barrel, Mill, Granary, LumberCamp, Quarry, MiningCamp, Barracks, ArcheryRange,
  Stable, SiegeWorkshop, MangonelWorkshop, TrebuchetWorkshop, Blacksmith, Market,
  Dock, Monastery, University, Castle, Wonder, Wall, Lantern
}

proc findNearestEnemyBuildingSpatial*(env: Environment, pos: IVec2,
                                       teamId: int, maxDist: int = int.high): Thing =
  ## Find nearest enemy building using spatial index.
  ## Searches buildings owned by a different team (teamId >= 0, teamId != query team).
  ## Returns nil if no enemy building found within maxDist.
  ## Uses Chebyshev distance for consistency with game mechanics.
  result = nil
  var minDist = int.high
  let cellSz = effectiveCellSize(env)
  let teamMask = getTeamMask(teamId)

  for kind in TeamBuildingKinds:
    forEachInRadius(env, pos, kind, maxDist, thing):
      # Must have a team and be enemy (not same team)
      if thing.teamId < 0:
        continue
      if (getTeamMask(thing.teamId) and teamMask) != 0:
        continue
      if not isValidPos(thing.pos):
        continue
      let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
      if dist <= maxDist and dist < minDist:
        minDist = dist
        result = thing
        searchRadius = distToCellRadiusEffective(dist, cellSz)

proc findNearestEnemyPresenceSpatial*(env: Environment, pos: IVec2,
                                       teamId: int, maxDist: int = int.high): tuple[target: IVec2, dist: int] =
  ## Find nearest enemy presence (agent or building) using spatial index.
  ## Returns position and distance of nearest enemy, or ivec2(-1,-1) if none found.
  ## Uses Chebyshev distance for consistency with game mechanics.
  var bestPos = ivec2(-1, -1)
  var bestDist = int.high
  let teamMask = getTeamMask(teamId)

  # Search for enemy agents
  block agentSearch:
    forEachInRadius(env, pos, Agent, maxDist, thing):
      if not isAgentAlive(env, thing):
        continue
      # Enemy: different team
      if (getTeamMask(thing) and teamMask) != 0:
        continue
      if not isValidPos(thing.pos):
        continue
      let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
      if dist <= maxDist and dist < bestDist:
        bestDist = dist
        bestPos = thing.pos

  # Search for enemy buildings (use bestDist as maxDist for early exit)
  for kind in TeamBuildingKinds:
    forEachInRadius(env, pos, kind, bestDist, thing):
      if thing.teamId < 0:
        continue
      if (getTeamMask(thing.teamId) and teamMask) != 0:
        continue
      if not isValidPos(thing.pos):
        continue
      let dist = max(abs(thing.pos.x - qPos.x), abs(thing.pos.y - qPos.y))
      if dist < bestDist:
        bestDist = dist
        bestPos = thing.pos

  (target: bestPos, dist: bestDist)
