import std/math
import entropy

const
  # Keep in sync with terrain.nim's MaxTerrainSize.
  MaxBiomeSize* = 512

type
  MaskGrid* = array[MaxBiomeSize, array[MaxBiomeSize, bool]]

proc clearMask*(mask: var MaskGrid, mapWidth, mapHeight: int, value = false) =
  for x in 0 ..< mapWidth:
    for y in 0 ..< mapHeight:
      mask[x][y] = value

proc ditherEdges*(mask: var MaskGrid, mapWidth, mapHeight: int, prob: float, depth: int, r: var Rand) =
  if depth <= 0 or prob <= 0.0:
    return

  for layer in 0 ..< depth:
    let layerProb = prob * (float(depth - layer) / float(depth))
    var boundary: MaskGrid
    for x in depth ..< mapWidth - depth:
      for y in depth ..< mapHeight - depth:
        block checkBoundary:
          for dx in -1 .. 1:
            for dy in -1 .. 1:
              if dx == 0 and dy == 0: continue
              if mask[x + dx][y + dy] != mask[x][y]:
                boundary[x][y] = true
                break checkBoundary

    for x in depth ..< mapWidth - depth:
      for y in depth ..< mapHeight - depth:
        if boundary[x][y] and randFloat(r) < layerProb:
          mask[x][y] = not mask[x][y]

template ditherIf(mask: var MaskGrid, mapWidth, mapHeight: int,
                  enabled: bool, prob: float, depth: int, r: var Rand) =
  if enabled:
    ditherEdges(mask, mapWidth, mapHeight, prob, depth, r)

type
  DungeonMazeConfig* = object
    wallKeepProb*: float = 0.65

  DungeonRadialConfig* = object
    arms*: int = 8
    armWidth*: int = 1
    ring*: bool = true

  BiomePlainsConfig* = object
    clusterPeriod*: int = 7
    clusterMinRadius*: int = 0
    clusterMaxRadius*: int = 2
    clusterFill*: float = 0.7
    clusterProb*: float = 0.8
    jitter*: int = 2

  BiomeSwampConfig* = object
    clusterPeriod*: int = 6
    clusterMinRadius*: int = 1
    clusterMaxRadius*: int = 3
    clusterFill*: float = 0.85
    clusterProb*: float = 0.9
    jitter*: int = 2
    waterScatterProb*: float = 0.25
    pondCountMin*: int = 2
    pondCountMax*: int = 8
    pondRadiusMin*: int = 3
    pondRadiusMax*: int = 6
    pondTilesPerPond*: int = 500
    pondEdgeDitherProb*: float = 0.25

proc clearZoneMask(mask: var MaskGrid, mapWidth, mapHeight: int,
                   zoneX, zoneY, zoneW, zoneH: int) =
  let startX = max(0, zoneX)
  let endX = min(mapWidth, zoneX + zoneW)
  let startY = max(0, zoneY)
  let endY = min(mapHeight, zoneY + zoneH)
  for x in startX ..< endX:
    for y in startY ..< endY:
      mask[x][y] = false

template forClusterCenters(mapWidth, mapHeight, mapBorder: int,
                           period, jitter: int, prob: float,
                           r: var Rand, body: untyped) =
  ## Iterates over cluster center positions on a grid with optional jitter and probability.
  ## Used for procedural placement of biome features like forests, stone deposits, etc.
  ##
  ## **Injected variables:**
  ## - `cx: int` - Center X coordinate (potentially jittered from grid position)
  ## - `cy: int` - Center Y coordinate (potentially jittered from grid position)
  ##
  ## **Parameters:**
  ## - `mapWidth`, `mapHeight` - Map dimensions
  ## - `mapBorder` - Border margin to avoid placing centers too close to edges
  ## - `period` - Grid spacing between potential cluster centers
  ## - `jitter` - Maximum random offset from grid positions (0 for no jitter)
  ## - `prob` - Probability (0.0-1.0) that each grid point becomes a cluster center
  ## - `r` - Random number generator
  ##
  ## **Example:**
  ## ```nim
  ## forClusterCenters(MapWidth, MapHeight, 5, 20, 3, 0.8, rng):
  ##   # Place a tree cluster at (cx, cy)
  ##   placeTreeCluster(mask, cx, cy, radius = 5)
  ## ```
  for ay in countup(mapBorder, mapHeight - mapBorder - 1, period):
    for ax in countup(mapBorder, mapWidth - mapBorder - 1, period):
      if randFloat(r) > prob:
        continue
      var cx {.inject.} = ax
      var cy {.inject.} = ay
      if jitter > 0:
        cx += randIntInclusive(r, -jitter, jitter)
        cy += randIntInclusive(r, -jitter, jitter)
      if cx < mapBorder or cx >= mapWidth - mapBorder or
         cy < mapBorder or cy >= mapHeight - mapBorder:
        continue
      body

proc buildClusterBiomeMask(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                           r: var Rand,
                           clusterPeriod, clusterMinRadius, clusterMaxRadius: int,
                           clusterFill, clusterProb: float,
                           jitter: int) =
  mask.clearMask(mapWidth, mapHeight)

  let period = max(3, clusterPeriod)
  let minRadius = max(0, clusterMinRadius)
  let maxRadius = max(minRadius, clusterMaxRadius)

  forClusterCenters(mapWidth, mapHeight, mapBorder, period, max(0, jitter), clusterProb, r):
      let radius = if maxRadius > 0: randIntInclusive(r, minRadius, maxRadius) else: 0
      if radius == 0:
        mask[cx][cy] = true
        continue

      let fill = clusterFill * (0.6 + 0.4 * randFloat(r))
      for dx in -radius .. radius:
        for dy in -radius .. radius:
          if dx * dx + dy * dy > radius * radius:
            continue
          let x = cx + dx
          let y = cy + dy
          if x < mapBorder or x >= mapWidth - mapBorder or
             y < mapBorder or y >= mapHeight - mapBorder:
            continue
          if randFloat(r) <= fill:
            mask[x][y] = true

proc buildDungeonMazeMask*(mask: var MaskGrid, mapWidth, mapHeight: int,
                           zoneX, zoneY, zoneW, zoneH: int,
                           r: var Rand, cfg: DungeonMazeConfig) =
  clearZoneMask(mask, mapWidth, mapHeight, zoneX, zoneY, zoneW, zoneH)

  var w = zoneW
  var h = zoneH
  if w < 3 or h < 3:
    return
  if w mod 2 == 0:
    dec w
  if h mod 2 == 0:
    dec h
  let cellW = (w - 1) div 2
  let cellH = (h - 1) div 2
  if cellW <= 0 or cellH <= 0:
    return

  var walls = newSeq[seq[bool]](w)
  for x in 0 ..< w:
    walls[x] = newSeq[bool](h)
    for y in 0 ..< h:
      walls[x][y] = true

  var visited = newSeq[seq[bool]](cellW)
  for x in 0 ..< cellW:
    visited[x] = newSeq[bool](cellH)

  var stack: seq[(int, int)] = @[]
  let startX = randIntExclusive(r, 0, cellW)
  let startY = randIntExclusive(r, 0, cellH)
  stack.add((startX, startY))
  visited[startX][startY] = true
  walls[1 + startX * 2][1 + startY * 2] = false

  const dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]

  while stack.len > 0:
    let (cx, cy) = stack[^1]
    var candidates: seq[(int, int)] = @[]
    for (dx, dy) in dirs:
      let nx = cx + dx
      let ny = cy + dy
      if nx >= 0 and nx < cellW and ny >= 0 and ny < cellH:
        if not visited[nx][ny]:
          candidates.add((nx, ny))
    if candidates.len == 0:
      discard stack.pop()
      continue

    let (nx, ny) = candidates[randIntExclusive(r, 0, candidates.len)]
    visited[nx][ny] = true

    let x1 = 1 + cx * 2
    let y1 = 1 + cy * 2
    let x2 = 1 + nx * 2
    let y2 = 1 + ny * 2
    walls[x2][y2] = false
    walls[x1 + (x2 - x1) div 2][y1 + (y2 - y1) div 2] = false

    stack.add((nx, ny))

  for x in 0 ..< w:
    for y in 0 ..< h:
      if not walls[x][y]:
        continue
      let gx = zoneX + x
      let gy = zoneY + y
      if gx < 0 or gx >= mapWidth or gy < 0 or gy >= mapHeight:
        continue
      if randFloat(r) <= cfg.wallKeepProb:
        mask[gx][gy] = true

template stampWidth(mask: var MaskGrid, fx, fy, armWidth,
                    zoneX, zoneY, zoneW, zoneH, mapWidth, mapHeight: int) =
  for ox in -armWidth .. armWidth:
    for oy in -armWidth .. armWidth:
      let gx = fx + ox
      let gy = fy + oy
      if gx >= zoneX and gx < zoneX + zoneW and gy >= zoneY and gy < zoneY + zoneH and
         gx >= 0 and gx < mapWidth and gy >= 0 and gy < mapHeight:
        mask[gx][gy] = true

proc buildDungeonRadialMask*(mask: var MaskGrid, mapWidth, mapHeight: int,
                             zoneX, zoneY, zoneW, zoneH: int,
                             r: var Rand, cfg: DungeonRadialConfig) =
  clearZoneMask(mask, mapWidth, mapHeight, zoneX, zoneY, zoneW, zoneH)

  if zoneW < 3 or zoneH < 3:
    return

  let cx = zoneX + zoneW div 2
  let cy = zoneY + zoneH div 2
  let radius = min(zoneW, zoneH) div 2
  let arms = max(1, cfg.arms)
  let armWidth = max(1, cfg.armWidth)

  for i in 0 ..< arms:
    let angle = 2.0 * PI * float(i) / float(arms)
    let dx = cos(angle)
    let dy = sin(angle)
    for step in 0 .. radius:
      let fx = cx + int(round(dx * float(step)))
      let fy = cy + int(round(dy * float(step)))
      stampWidth(mask, fx, fy, armWidth, zoneX, zoneY, zoneW, zoneH, mapWidth, mapHeight)

  if cfg.ring:
    let ringRadius = max(2, radius div 2)
    let steps = max(16, ringRadius * 6)
    for i in 0 ..< steps:
      let angle = 2.0 * PI * float(i) / float(steps)
      let fx = cx + int(round(cos(angle) * float(ringRadius)))
      let fy = cy + int(round(sin(angle) * float(ringRadius)))
      stampWidth(mask, fx, fy, armWidth, zoneX, zoneY, zoneW, zoneH, mapWidth, mapHeight)

  # Soften edges with a tiny bit of noise.
  for x in zoneX ..< zoneX + zoneW:
    for y in zoneY ..< zoneY + zoneH:
      if x < 0 or x >= mapWidth or y < 0 or y >= mapHeight:
        continue
      if mask[x][y] and randFloat(r) < 0.08:
        mask[x][y] = false

  # Ensure at least one corridor reaches the zone boundary so the dungeon
  # connects back to the rest of the map.
  let dirs = [(dx: 0, dy: -1), (dx: 0, dy: 1), (dx: -1, dy: 0), (dx: 1, dy: 0)]
  let dir = dirs[randIntInclusive(r, 0, dirs.high)]
  let maxStep =
    if dir.dx == 1: (zoneX + zoneW - 1) - cx
    elif dir.dx == -1: cx - zoneX
    elif dir.dy == 1: (zoneY + zoneH - 1) - cy
    else: cy - zoneY
  for step in 0 .. maxStep:
    let x = cx + dir.dx * step
    let y = cy + dir.dy * step
    for off in -armWidth .. armWidth:
      let gx = x + (if dir.dy == 0: 0 else: off)
      let gy = y + (if dir.dx == 0: 0 else: off)
      if gx >= max(0, zoneX) and gx < min(mapWidth, zoneX + zoneW) and
         gy >= max(0, zoneY) and gy < min(mapHeight, zoneY + zoneH):
        mask[gx][gy] = true

proc buildBiomePlainsMask*(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                           r: var Rand, cfg: BiomePlainsConfig) =
  buildClusterBiomeMask(mask, mapWidth, mapHeight, mapBorder, r,
    cfg.clusterPeriod, cfg.clusterMinRadius, cfg.clusterMaxRadius,
    cfg.clusterFill, cfg.clusterProb, cfg.jitter)

proc buildBiomeSwampMask*(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                          r: var Rand, cfg: BiomeSwampConfig) =
  buildClusterBiomeMask(mask, mapWidth, mapHeight, mapBorder, r,
    cfg.clusterPeriod, cfg.clusterMinRadius, cfg.clusterMaxRadius,
    cfg.clusterFill, cfg.clusterProb, cfg.jitter)

type
  BiomeForestConfig* = object
    clumpiness*: int = 2
    seedProb*: float = 0.03
    growthProb*: float = 0.5
    neighborThreshold*: int = 3
    ditherEdges*: bool = true
    ditherProb*: float = 0.15
    ditherDepth*: int = 5

template cellularStep(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                      countEdge: bool, rule: untyped) =
  ## Performs one step of cellular automata on a boolean mask.
  ## The rule expression determines whether each cell should be alive in the next generation.
  ##
  ## **Injected variables:**
  ## - `neighbors: int` - Count of alive neighboring cells (8-connectivity)
  ## - `alive: bool` - Whether the current cell is alive in the current generation
  ##
  ## **Parameters:**
  ## - `mask` - The boolean grid to evolve (modified in place)
  ## - `mapWidth`, `mapHeight` - Map dimensions
  ## - `mapBorder` - Border margin to exclude from processing
  ## - `countEdge` - When true, out-of-bounds cells count as alive neighbors
  ## - `rule` - Expression returning bool for whether cell should be alive
  ##
  ## **Example:**
  ## ```nim
  ## # Conway's Game of Life rule: survive with 2-3 neighbors, born with 3
  ## cellularStep(mask, MapWidth, MapHeight, 5, false):
  ##   (alive and neighbors in {2, 3}) or (not alive and neighbors == 3)
  ##
  ## # Growth rule: alive cells stay, dead cells become alive if 3+ neighbors
  ## cellularStep(mask, MapWidth, MapHeight, 5, false):
  ##   alive or (neighbors >= 3 and randFloat(r) < 0.5)
  ## ```
  var nextMask: MaskGrid
  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      var neighbors {.inject.} = 0
      for dx in -1 .. 1:
        for dy in -1 .. 1:
          if dx == 0 and dy == 0: continue
          let nx = x + dx
          let ny = y + dy
          when countEdge:
            if nx < mapBorder or nx >= mapWidth - mapBorder or
               ny < mapBorder or ny >= mapHeight - mapBorder:
              inc neighbors
            elif mask[nx][ny]:
              inc neighbors
          else:
            if nx >= 0 and nx < mapWidth and ny >= 0 and ny < mapHeight and mask[nx][ny]:
              inc neighbors
      var alive {.inject.} = mask[x][y]
      nextMask[x][y] = rule
  mask = nextMask

proc buildBiomeForestMask*(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                           r: var Rand, cfg: BiomeForestConfig) =
  mask.clearMask(mapWidth, mapHeight)

  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      if randFloat(r) < cfg.seedProb:
        mask[x][y] = true

  for _ in 0 ..< max(0, cfg.clumpiness):
    cellularStep(mask, mapWidth, mapHeight, mapBorder, false):
      (neighbors >= cfg.neighborThreshold and randFloat(r) < cfg.growthProb) or alive

  ditherIf(mask, mapWidth, mapHeight, cfg.ditherEdges, cfg.ditherProb, cfg.ditherDepth, r)

type
  BiomeDesertConfig* = object
    dunePeriod*: int = 8
    ridgeWidth*: int = 1
    angle*: float = PI / 4
    noiseProb*: float = 0.1
    ditherEdges*: bool = true
    ditherProb*: float = 0.15
    ditherDepth*: int = 5

proc buildBiomeDesertMask*(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                           r: var Rand, cfg: BiomeDesertConfig) =
  mask.clearMask(mapWidth, mapHeight)

  let period = max(2, cfg.dunePeriod)
  let cosT = cos(cfg.angle)
  let sinT = sin(cfg.angle)

  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      let xr = x.float * cosT + y.float * sinT
      var modv = xr - floor(xr / period.float) * period.float
      if modv < max(1, cfg.ridgeWidth).float:
        mask[x][y] = true
      if mask[x][y] and randFloat(r) < cfg.noiseProb:
        mask[x][y] = false

  ditherIf(mask, mapWidth, mapHeight, cfg.ditherEdges, cfg.ditherProb, cfg.ditherDepth, r)

type
  BiomeCavesConfig* = object
    fillProb*: float = 0.25
    steps*: int = 3
    birthLimit*: int = 5
    deathLimit*: int = 3
    ditherEdges*: bool = true
    ditherProb*: float = 0.15
    ditherDepth*: int = 5

proc buildBiomeCavesMask*(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                          r: var Rand, cfg: BiomeCavesConfig) =
  mask.clearMask(mapWidth, mapHeight)

  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      mask[x][y] = randFloat(r) < cfg.fillProb

  for _ in 0 ..< max(0, cfg.steps):
    cellularStep(mask, mapWidth, mapHeight, mapBorder, true):
      (neighbors > cfg.birthLimit) or (neighbors >= cfg.deathLimit and alive)

  ditherIf(mask, mapWidth, mapHeight, cfg.ditherEdges, cfg.ditherProb, cfg.ditherDepth, r)

type
  BiomeCityConfig* = object
    pitch*: int = 10
    roadWidth*: int = 3
    placeProb*: float = 0.9
    minBlockFrac*: float = 0.5
    jitter*: int = 1
    ditherEdges*: bool = true
    ditherProb*: float = 0.15
    ditherDepth*: int = 5

proc buildBiomeCityMasks*(blockMask: var MaskGrid, roadMask: var MaskGrid,
                          mapWidth, mapHeight, mapBorder: int,
                          r: var Rand, cfg: BiomeCityConfig) =
  blockMask.clearMask(mapWidth, mapHeight)
  roadMask.clearMask(mapWidth, mapHeight)

  let pitch = max(4, cfg.pitch)
  let roadW = max(1, cfg.roadWidth)
  let minBlock = max(1, int(float(pitch) * cfg.minBlockFrac))
  let jitter = max(0, cfg.jitter)

  for gy in countup(mapBorder, mapHeight - mapBorder - 1, pitch):
    for gx in countup(mapBorder, mapWidth - mapBorder - 1, pitch):
      if randFloat(r) > cfg.placeProb:
        continue
      let x0 = gx + roadW
      let y0 = gy + roadW
      var bw = minBlock
      var bh = minBlock
      if jitter > 0:
        bw += randIntInclusive(r, -jitter, jitter)
        bh += randIntInclusive(r, -jitter, jitter)
      bw = min(bw, pitch - 2 * roadW)
      bh = min(bh, pitch - 2 * roadW)
      if bw <= 0 or bh <= 0:
        continue
      let cx0 = max(mapBorder, x0)
      let cy0 = max(mapBorder, y0)
      let cx1 = min(mapWidth - mapBorder, x0 + bw)
      let cy1 = min(mapHeight - mapBorder, y0 + bh)
      if cx1 <= cx0 or cy1 <= cy0:
        continue
      for x in cx0 ..< cx1:
        for y in cy0 ..< cy1:
          blockMask[x][y] = true

  ditherIf(blockMask, mapWidth, mapHeight, cfg.ditherEdges, cfg.ditherProb, cfg.ditherDepth, r)

  for gy in countup(mapBorder, mapHeight - mapBorder - 1, pitch):
    let y1 = min(mapHeight - mapBorder, gy + roadW)
    for y in gy ..< y1:
      for x in mapBorder ..< mapWidth - mapBorder:
        if not blockMask[x][y]:
          roadMask[x][y] = true

  for gx in countup(mapBorder, mapWidth - mapBorder - 1, pitch):
    let x1 = min(mapWidth - mapBorder, gx + roadW)
    for x in gx ..< x1:
      for y in mapBorder ..< mapHeight - mapBorder:
        if not blockMask[x][y]:
          roadMask[x][y] = true

type
  BiomeSnowConfig* = object
    clusterPeriod*: int = 12
    clusterMinRadius*: int = 2
    clusterMaxRadius*: int = 5
    clusterFill*: float = 0.85
    clusterProb*: float = 0.75
    jitter*: int = 2
    ditherEdges*: bool = true
    ditherProb*: float = 0.12
    ditherDepth*: int = 3

proc buildBiomeSnowMask*(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                         r: var Rand, cfg: BiomeSnowConfig) =
  mask.clearMask(mapWidth, mapHeight)

  let period = max(4, cfg.clusterPeriod)
  let minRadius = max(1, cfg.clusterMinRadius)
  let maxRadius = max(minRadius, cfg.clusterMaxRadius)
  let jitter = max(0, cfg.jitter)

  forClusterCenters(mapWidth, mapHeight, mapBorder, period, jitter, cfg.clusterProb, r):
      let radius = randIntInclusive(r, minRadius, maxRadius)
      let fill = cfg.clusterFill * (0.7 + 0.3 * randFloat(r))
      for dx in -radius .. radius:
        for dy in -radius .. radius:
          let x = cx + dx
          let y = cy + dy
          if x < mapBorder or x >= mapWidth - mapBorder or
             y < mapBorder or y >= mapHeight - mapBorder:
            continue
          let dist2 = dx * dx + dy * dy
          if dist2 > radius * radius:
            continue
          let dist = sqrt(dist2.float)
          let falloff = 1.0 - min(1.0, dist / radius.float)
          let chance = fill * (0.6 + 0.4 * falloff)
          if randFloat(r) < chance:
            mask[x][y] = true

  ditherIf(mask, mapWidth, mapHeight, cfg.ditherEdges, cfg.ditherProb, cfg.ditherDepth, r)
