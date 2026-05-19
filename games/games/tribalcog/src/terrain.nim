import std/math, vmath
import entropy
import biome

const
  # Keep in sync with biome.nim's MaxBiomeSize.
  MaxTerrainSize* = 512

type
  TerrainType* = enum
    Empty
    Water
    ShallowWater
    Bridge
    Fertile
    Road
    Grass
    Dune
    Sand
    Snow
    Mud
    Mountain
    RampUpN
    RampUpS
    RampUpW
    RampUpE
    RampDownN
    RampDownS
    RampDownW
    RampDownE

  ## Sized to comfortably exceed current MapWidth/MapHeight.
  TerrainGrid* = array[MaxTerrainSize, array[MaxTerrainSize, TerrainType]]

const
  ## Terrain movement speed modifiers.
  ## Values < 1.0 slow movement, values > 1.0 speed it up.
  ## Default terrain has modifier 1.0 (no effect).
  TerrainSpeedModifier*: array[TerrainType, float32] = [
    Empty: 1.0'f32,
    Water: 1.0'f32,      # Deep water is impassable (boats only)
    ShallowWater: 0.5'f32, # 50% slower wading through shallow water
    Bridge: 1.0'f32,
    Fertile: 1.0'f32,
    Road: 1.0'f32,       # Roads already give double-step bonus in step.nim
    Grass: 1.0'f32,
    Dune: 0.85'f32,      # 15% slower on dunes
    Sand: 0.9'f32,       # 10% slower in sand
    Snow: 0.8'f32,       # 20% slower in snow
    Mud: 0.7'f32,        # 30% slower in swamp mud
    Mountain: 1.0'f32,   # Impassable mountain terrain (speed irrelevant)
    RampUpN: 1.0'f32,    # Ramps already have special handling
    RampUpS: 1.0'f32,
    RampUpW: 1.0'f32,
    RampUpE: 1.0'f32,
    RampDownN: 1.0'f32,
    RampDownS: 1.0'f32,
    RampDownW: 1.0'f32,
    RampDownE: 1.0'f32,
  ]

proc getTerrainSpeedModifier*(terrain: TerrainType): float32 {.inline.} =
  ## Get the movement speed modifier for a terrain type.
  TerrainSpeedModifier[terrain]

type
  Structure* = object
    width*, height*: int
    centerPos*: IVec2
    layout*: seq[seq[char]]

const
  # Structure layout ASCII schema (typeable characters).
  StructureWallChar* = '#'
  StructureFloorChar* = '.'
  StructureDoorChar* = 'D'
  StructureAltarChar* = 'a'
  StructureBlacksmithChar* = 'F'
  StructureClayOvenChar* = 'C'
  StructureWeavingLoomChar* = 'W'

type
  BiomeKind = enum
    BiomeBase
    BiomeForest
    BiomeDesert
    BiomeCaves
    BiomeCity
    BiomePlains
    BiomeSnow
    BiomeSwamp

  BiomeType* = enum
    BiomeNone
    BiomeBaseType
    BiomeForestType
    BiomeDesertType
    BiomeCavesType
    BiomeCityType
    BiomePlainsType
    BiomeSnowType
    BiomeSwampType
    BiomeDungeonType

  BiomeGrid* = array[MaxTerrainSize, array[MaxTerrainSize, BiomeType]]

  DungeonKind* = enum
    DungeonMaze
    DungeonRadial

const
  UseBiomeTerrain* = true
  BaseBiome* = BiomeBase
  BiomeForestTerrain* = Grass
  BiomeDesertTerrain* = Sand
  BiomeCavesTerrain* = Dune
  BiomePlainsTerrain* = Grass
  BiomeSnowTerrain* = Snow
  BiomeSwampTerrain* = Mud
  BiomeCityBlockTerrain* = Grass
  BiomeCityRoadTerrain* = Road
  UseBiomeZones* = true
  UseDungeonZones* = true
  UseLegacyTreeClusters* = true
  UseTreeOases* = true
  WheatFieldClusterCountMin* = 98
  WheatFieldClusterCountMax* = 140
  WheatFieldSizeMin* = 3
  WheatFieldSizeMax* = 6
  TreeGroveClusterCountMin* = 98
  TreeGroveClusterCountMax* = 140
  TreeOasisClusterCountMin* = 18
  TreeOasisClusterCountMax* = 30
  TreeOasisWaterRadiusMin* = 1
  TreeOasisWaterRadiusMax* = 2
  # Biome/dungeon zone counts are derived from the available kinds.
  BiomeZoneMaxFraction* = 0.48
  DungeonZoneMaxFraction* = 0.24
  ZoneMinSize* = 18
  BiomeBlendDepth* = 6
  BiomeZoneGridJitter* = 0.35
  BiomeZoneCellFill* = 0.95
  ZoneBlobNoise* = 0.35
  ZoneBlobLobesMin* = 1
  ZoneBlobLobesMax* = 3
  ZoneBlobLobeOffset* = 0.7
  ZoneBlobAnisotropy* = 0.45
  ZoneBlobBiteCountMin* = 1
  ZoneBlobBiteCountMax* = 4
  ZoneBlobBiteScaleMin* = 0.28
  ZoneBlobBiteScaleMax* = 0.7
  ZoneBlobBiteAngleMin* = 0.35
  ZoneBlobBiteAngleMax* = 0.75
  ZoneBlobJaggedPasses* = 2
  ZoneBlobJaggedProb* = 0.18
  ZoneBlobDitherProb* = 0.12
  ZoneBlobDitherDepth* = 4
  DungeonTerrainWall* = Dune
  DungeonTerrainPath* = Road

const
  TerrainEmpty* = TerrainType.Empty
  TerrainRoad* = TerrainType.Road
  TerrainGrass* = TerrainType.Grass
  TerrainDune* = TerrainType.Dune
  TerrainSand* = TerrainType.Sand
  TerrainSnow* = TerrainType.Snow
  TerrainMud* = TerrainType.Mud
  RampTerrain* = {RampUpN, RampUpS, RampUpW, RampUpE,
                   RampDownN, RampDownS, RampDownW, RampDownE}
  WaterTerrain* = {Water, ShallowWater}
  DustyTerrain* = {Sand, Dune, Snow, Mud, Grass, Fertile, Road}  ## Terrain that kicks up dust when walked on
  BuildableTerrain* = {Empty, Grass, Sand, Snow, Mud, Dune, Road, Fertile,
                        RampUpN, RampUpS, RampUpW, RampUpE,
                        RampDownN, RampDownS, RampDownW, RampDownE}
  # BuildableTerrain excluding roads and ramps - for AI build location selection
  PlaceableBuildTerrain* = {Empty, Grass, Sand, Snow, Mud, Dune, Fertile}

template isBlockedTerrain*(terrain: TerrainType): bool =
  terrain == Water or terrain == Mountain

template isWaterTerrain*(terrain: TerrainType): bool =
  ## Check if terrain is water (deep or shallow)
  terrain in WaterTerrain

template isRampTerrain*(terrain: TerrainType): bool =
  terrain in RampTerrain

template isBuildableExcludingRoads*(terrain: TerrainType): bool =
  ## Check if terrain allows building placement (excludes roads and ramps)
  terrain in PlaceableBuildTerrain

const
  RiverWidth* = 6

type
  ZoneRect* = object
    x*, y*, w*, h*: int

proc applyMaskToTerrain(terrain: var TerrainGrid, mask: MaskGrid, mapWidth, mapHeight, mapBorder: int,
                        terrainType: TerrainType) =
  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      if mask[x][y] and terrain[x][y] == Empty:
        terrain[x][y] = terrainType

proc blendChanceForDistance(dist, depth: int, edgeChance: float): float =
  if depth <= 0:
    return 1.0
  let blendT = min(1.0, dist.float / depth.float)
  edgeChance + (1.0 - edgeChance) * blendT

proc canApplyBiome(currentBiome, biomeType, baseBiomeType: BiomeType): bool =
  currentBiome == BiomeNone or currentBiome == baseBiomeType or currentBiome == biomeType

proc splitCliffRing(mask: MaskGrid, mapWidth, mapHeight: int,
                    ringMask, innerMask: var MaskGrid) =
  ringMask.clearMask(mapWidth, mapHeight)
  innerMask.clearMask(mapWidth, mapHeight)
  for x in 0 ..< mapWidth:
    for y in 0 ..< mapHeight:
      if not mask[x][y]:
        continue
      if (y == 0 or not mask[x][y - 1]) or (x == mapWidth - 1 or not mask[x + 1][y]) or
         (y == mapHeight - 1 or not mask[x][y + 1]) or (x == 0 or not mask[x - 1][y]):
        ringMask[x][y] = true
      else:
        innerMask[x][y] = true

proc baseBiomeType(): BiomeType =
  case BaseBiome:
  of BiomeBase: BiomeBaseType
  of BiomeForest: BiomeForestType
  of BiomeDesert: BiomeDesertType
  of BiomeCaves: BiomeCavesType
  of BiomeCity: BiomeCityType
  of BiomePlains: BiomePlainsType
  of BiomeSnow: BiomeSnowType
  of BiomeSwamp: BiomeSwampType

proc zoneBounds(zone: ZoneRect, mapWidth, mapHeight, mapBorder: int): tuple[x0, y0, x1, y1: int] =
  (x0: max(mapBorder, zone.x), y0: max(mapBorder, zone.y),
   x1: min(mapWidth - mapBorder, zone.x + zone.w),
   y1: min(mapHeight - mapBorder, zone.y + zone.h))

proc isInCorner*(x, y, mapBorder, reserve, mapWidth, mapHeight: int): bool =
  ## Check if a position is within a reserved corner area.
  ## Corners are reserved for villages so rivers/roads don't block them.
  let left = mapBorder
  let right = mapWidth - mapBorder
  let top = mapBorder
  let bottom = mapHeight - mapBorder
  ((x >= left and x < left + reserve) and (y >= top and y < top + reserve)) or
  ((x >= right - reserve and x < right) and (y >= top and y < top + reserve)) or
  ((x >= left and x < left + reserve) and (y >= bottom - reserve and y < bottom)) or
  ((x >= right - reserve and x < right) and (y >= bottom - reserve and y < bottom))

proc maskEdgeDistance(mask: MaskGrid, mapWidth, mapHeight: int, x, y, maxDepth: int): int =
  if not mask[x][y]:
    return 0
  for depth in 0 .. maxDepth:
    let radius = depth + 1
    for dx in -radius .. radius:
      for dy in -radius .. radius:
        if abs(dx) != radius and abs(dy) != radius:
          continue
        let nx = x + dx
        let ny = y + dy
        if nx < 0 or nx >= mapWidth or ny < 0 or ny >= mapHeight:
          return depth
        if not mask[nx][ny]:
          return depth
  maxDepth + 1

proc applyBiomeMaskToZone(terrain: var TerrainGrid, biomes: var BiomeGrid, mask: MaskGrid,
                          zoneMask: MaskGrid, zone: ZoneRect, mapWidth, mapHeight, mapBorder: int,
                          terrainType: TerrainType, biomeType: BiomeType, baseBiomeType: BiomeType,
                          r: var Rand, edgeChance: float, blendDepth: int = BiomeBlendDepth,
                          density: float = 1.0) =
  let (x0, y0, x1, y1) = zoneBounds(zone, mapWidth, mapHeight, mapBorder)
  if x1 <= x0 or y1 <= y0:
    return
  for x in x0 ..< x1:
    for y in y0 ..< y1:
      if not zoneMask[x][y] or not mask[x][y]:
        continue
      if not canApplyBiome(biomes[x][y], biomeType, baseBiomeType):
        continue
      let maskDist = maskEdgeDistance(mask, mapWidth, mapHeight, x, y, blendDepth)
      let zoneDist = maskEdgeDistance(zoneMask, mapWidth, mapHeight, x, y, blendDepth)
      let edgeDist = min(maskDist, zoneDist)
      let chance = min(1.0, blendChanceForDistance(edgeDist, blendDepth, edgeChance) * density)
      if terrain[x][y] == Empty or randChance(r, chance):
        terrain[x][y] = terrainType
      if randChance(r, chance):
        biomes[x][y] = biomeType

proc applyTerrainBlendToZone(terrain: var TerrainGrid, biomes: var BiomeGrid, zoneMask: MaskGrid,
                             zone: ZoneRect, mapWidth, mapHeight, mapBorder: int,
                             terrainType: TerrainType, biomeType: BiomeType,
                             baseBiomeType: BiomeType, r: var Rand, edgeChance: float,
                             blendDepth: int = BiomeBlendDepth, overwriteWater = false,
                             density: float = 1.0) =
  let (x0, y0, x1, y1) = zoneBounds(zone, mapWidth, mapHeight, mapBorder)
  if x1 <= x0 or y1 <= y0:
    return
  for x in x0 ..< x1:
    for y in y0 ..< y1:
      if not overwriteWater and terrain[x][y] == Water:
        continue
      if not zoneMask[x][y]:
        continue
      if not canApplyBiome(biomes[x][y], biomeType, baseBiomeType):
        continue
      let edgeDist = maskEdgeDistance(zoneMask, mapWidth, mapHeight, x, y, blendDepth)
      let chance = min(1.0, blendChanceForDistance(edgeDist, blendDepth, edgeChance) * density)
      if randChance(r, chance):
        terrain[x][y] = terrainType
        biomes[x][y] = biomeType

proc ensureInnerCells(innerMask: var MaskGrid, zoneMask: MaskGrid,
                      zone: ZoneRect, mapWidth, mapHeight, mapBorder: int) =
  ## If innerMask has no set cells, seed it with the zone center or first available cell.
  for x in 0 ..< mapWidth:
    for y in 0 ..< mapHeight:
      if innerMask[x][y]:
        return
  let (x0, y0, x1, y1) = zoneBounds(zone, mapWidth, mapHeight, mapBorder)
  if x1 <= x0 or y1 <= y0:
    return
  let cx = (x0 + x1 - 1) div 2
  let cy = (y0 + y1 - 1) div 2
  if zoneMask[cx][cy]:
    innerMask[cx][cy] = true
    return
  for x in x0 ..< x1:
    for y in y0 ..< y1:
      if zoneMask[x][y]:
        innerMask[x][y] = true
        return

proc applyBiomeZoneInsetFill(terrain: var TerrainGrid, biomes: var BiomeGrid, zoneMask: MaskGrid,
                             zone: ZoneRect, mapWidth, mapHeight, mapBorder: int,
                             biomeTerrain: TerrainType,
                             biomeType, baseBiomeType: BiomeType) =
  var ringMask: MaskGrid
  var innerMask: MaskGrid
  splitCliffRing(zoneMask, mapWidth, mapHeight, ringMask, innerMask)
  ensureInnerCells(innerMask, zoneMask, zone, mapWidth, mapHeight, mapBorder)
  let (x0, y0, x1, y1) = zoneBounds(zone, mapWidth, mapHeight, mapBorder)
  if x1 <= x0 or y1 <= y0:
    return
  for x in x0 ..< x1:
    for y in y0 ..< y1:
      if not innerMask[x][y]:
        continue
      if not canApplyBiome(biomes[x][y], biomeType, baseBiomeType):
        continue
      terrain[x][y] = biomeTerrain
      biomes[x][y] = biomeType

type
  MaskBuilder[T] = proc(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                        r: var Rand, cfg: T) {.nimcall.}

proc applyBiomeZoneMask[T](terrain: var TerrainGrid, biomes: var BiomeGrid,
                           zoneMask: MaskGrid, zone: ZoneRect, mapWidth, mapHeight, mapBorder: int,
                           r: var Rand, edgeChance: float,
                           builder: MaskBuilder[T], cfg: T,
                           terrainType: TerrainType, biomeType: BiomeType,
                           baseBiomeType: BiomeType) =
  var mask: MaskGrid
  builder(mask, mapWidth, mapHeight, mapBorder, r, cfg)
  applyBiomeMaskToZone(terrain, biomes, mask, zoneMask, zone, mapWidth, mapHeight, mapBorder,
    terrainType, biomeType, baseBiomeType, r, edgeChance)

proc applyBaseBiomeMask[T](terrain: var TerrainGrid, mapWidth, mapHeight, mapBorder: int,
                           r: var Rand, builder: MaskBuilder[T], cfg: T,
                           terrainType: TerrainType) =
  var mask: MaskGrid
  builder(mask, mapWidth, mapHeight, mapBorder, r, cfg)
  applyMaskToTerrain(terrain, mask, mapWidth, mapHeight, mapBorder, terrainType)

proc evenlyDistributedZones*(r: var Rand, mapWidth, mapHeight, mapBorder: int, count: int,
                             maxFraction: float): seq[ZoneRect] =
  if count <= 0:
    return @[]
  let playableW = max(1, mapWidth - mapBorder * 2)
  let playableH = max(1, mapHeight - mapBorder * 2)
  let aspect = playableW.float / playableH.float
  let cols = max(1, int(round(sqrt(count.float * aspect))))
  let rows = max(1, int(ceil(count.float / cols.float)))
  let cellW = playableW.float / cols.float
  let cellH = playableH.float / rows.float

  var cells: seq[tuple[cx, cy: int]] = @[]
  for cy in 0 ..< rows:
    for cx in 0 ..< cols:
      cells.add((cx, cy))

  for i in countdown(cells.len - 1, 1):
    let j = randIntInclusive(r, 0, i)
    swap(cells[i], cells[j])

  let maxW = max(ZoneMinSize, int(playableW.float * maxFraction))
  let maxH = max(ZoneMinSize, int(playableH.float * maxFraction))

  result = @[]
  for i in 0 ..< min(count, cells.len):
    let cell = cells[i]
    let jitterX = (randFloat(r) - 0.5) * BiomeZoneGridJitter * cellW
    let jitterY = (randFloat(r) - 0.5) * BiomeZoneGridJitter * cellH
    let centerX = mapBorder.float + (cell.cx.float + 0.5) * cellW + jitterX
    let centerY = mapBorder.float + (cell.cy.float + 0.5) * cellH + jitterY

    let sizeW = clamp(int(cellW * BiomeZoneCellFill * (0.85 + 0.3 * randFloat(r))), ZoneMinSize, maxW)
    let sizeH = clamp(int(cellH * BiomeZoneCellFill * (0.85 + 0.3 * randFloat(r))), ZoneMinSize, maxH)
    let x = clamp(int(centerX) - sizeW div 2, mapBorder, mapWidth - mapBorder - sizeW)
    let y = clamp(int(centerY) - sizeH div 2, mapBorder, mapHeight - mapBorder - sizeH)
    result.add(ZoneRect(x: x, y: y, w: sizeW, h: sizeH))

type
  BlobLobe = tuple[cx, cy, rx, ry: float]

proc generateBlobLobes(cx, cy, rx, ry: int, r: var Rand): seq[BlobLobe] =
  ## Generate elliptical lobes for zone blob shapes.
  let lobeCount = randIntInclusive(r, ZoneBlobLobesMin, ZoneBlobLobesMax)
  result = @[]
  let baseStretch = max(0.35, 1.0 + (randFloat(r) * 2.0 - 1.0) * ZoneBlobAnisotropy)
  result.add((
    cx: cx.float,
    cy: cy.float,
    rx: max(2.0, rx.float * baseStretch),
    ry: max(2.0, ry.float / baseStretch)
  ))
  if lobeCount > 1:
    let minRadius = min(rx.float, ry.float)
    for _ in 1 ..< lobeCount:
      let angle = randFloat(r) * 2.0 * PI
      let offset = (0.35 + 0.55 * randFloat(r)) * minRadius * ZoneBlobLobeOffset
      let stretch = max(0.35, 1.0 + (randFloat(r) * 2.0 - 1.0) * ZoneBlobAnisotropy)
      let lrx = max(2.0, rx.float * (0.45 + 0.55 * randFloat(r)) * stretch)
      let lry = max(2.0, ry.float * (0.45 + 0.55 * randFloat(r)) / stretch)
      result.add((
        cx: cx.float + cos(angle) * offset,
        cy: cy.float + sin(angle) * offset,
        rx: lrx,
        ry: lry
      ))

proc isInsideLobe(x, y: int, lobes: seq[BlobLobe], noise: float): bool =
  ## Check if a point is inside any of the lobes (with noise factor).
  for lobe in lobes:
    let dx = (x.float - lobe.cx) / lobe.rx
    let dy = (y.float - lobe.cy) / lobe.ry
    let dist = dx * dx + dy * dy
    if dist <= 1.0 + noise:
      return true
  false

proc normalizeAngle(ang: float): float =
  ## Normalize angle to [-PI, PI] range.
  result = ang
  while result > PI:
    result -= 2.0 * PI
  while result < -PI:
    result += 2.0 * PI

proc carveBlobBite(mask: var MaskGrid, bx, by, biteRadius: int,
                   biteAngle, biteSpread: float, x0, y0, x1, y1: int) =
  ## Carve a wedge-shaped bite out of the blob mask.
  let minX = max(x0, bx - biteRadius)
  let maxX = min(x1 - 1, bx + biteRadius)
  let minY = max(y0, by - biteRadius)
  let maxY = min(y1 - 1, by + biteRadius)
  let radiusSq = biteRadius * biteRadius
  for x in minX .. maxX:
    for y in minY .. maxY:
      if not mask[x][y]:
        continue
      let dx = x - bx
      let dy = y - by
      if dx * dx + dy * dy > radiusSq:
        continue
      let ang = normalizeAngle(arctan2(dy.float, dx.float) - biteAngle)
      if abs(ang) <= biteSpread:
        mask[x][y] = false

proc applyBlobBites(mask: var MaskGrid, baseRadius, x0, y0, x1, y1: int, r: var Rand) =
  ## Apply random wedge-shaped bites to create irregular blob edges.
  let biteCount = randIntInclusive(r, ZoneBlobBiteCountMin, ZoneBlobBiteCountMax)
  for _ in 0 ..< biteCount:
    var bx = randIntInclusive(r, x0, x1 - 1)
    var by = randIntInclusive(r, y0, y1 - 1)
    var attempts = 0
    while attempts < 10 and not mask[bx][by]:
      bx = randIntInclusive(r, x0, x1 - 1)
      by = randIntInclusive(r, y0, y1 - 1)
      inc attempts
    if not mask[bx][by]:
      continue
    let biteMin = max(2, int(baseRadius.float * ZoneBlobBiteScaleMin))
    let biteMax = max(biteMin, int(baseRadius.float * ZoneBlobBiteScaleMax))
    let biteRadius = randIntInclusive(r, biteMin, biteMax)
    let biteAngle = randFloat(r) * 2.0 * PI
    let biteSpread = (ZoneBlobBiteAngleMin + randFloat(r) *
      (ZoneBlobBiteAngleMax - ZoneBlobBiteAngleMin)) * PI
    carveBlobBite(mask, bx, by, biteRadius, biteAngle, biteSpread, x0, y0, x1, y1)

proc isEdgeCell(mask: MaskGrid, x, y, x0, y0, x1, y1: int): bool =
  ## Check if a cell is on the edge of the masked region.
  for dx in -1 .. 1:
    for dy in -1 .. 1:
      if dx == 0 and dy == 0:
        continue
      let nx = x + dx
      let ny = y + dy
      if nx < x0 or nx >= x1 or ny < y0 or ny >= y1 or not mask[nx][ny]:
        return true
  false

proc applyJaggedEdges(mask: var MaskGrid, x0, y0, x1, y1: int, r: var Rand) =
  ## Apply jagged edge erosion passes to create natural-looking boundaries.
  for _ in 0 ..< ZoneBlobJaggedPasses:
    var nextMask = mask
    for x in x0 ..< x1:
      for y in y0 ..< y1:
        if not mask[x][y]:
          continue
        if isEdgeCell(mask, x, y, x0, y0, x1, y1) and randChance(r, ZoneBlobJaggedProb):
          nextMask[x][y] = false
    mask = nextMask

proc buildZoneBlobMask*(mask: var MaskGrid, mapWidth, mapHeight, mapBorder: int,
                        zone: ZoneRect, r: var Rand) =
  mask.clearMask(mapWidth, mapHeight)
  let (x0, y0, x1, y1) = zoneBounds(zone, mapWidth, mapHeight, mapBorder)
  if x1 <= x0 or y1 <= y0:
    return
  let cx = (x0 + x1 - 1) div 2
  let cy = (y0 + y1 - 1) div 2
  let rx = max(2, (x1 - x0) div 2)
  let ry = max(2, (y1 - y0) div 2)
  let lobes = generateBlobLobes(cx, cy, rx, ry, r)

  for x in x0 ..< x1:
    for y in y0 ..< y1:
      let noise = (randFloat(r) - 0.5) * ZoneBlobNoise
      if isInsideLobe(x, y, lobes, noise):
        mask[x][y] = true

  let baseRadius = max(2, min(rx, ry))
  applyBlobBites(mask, baseRadius, x0, y0, x1, y1, r)
  applyJaggedEdges(mask, x0, y0, x1, y1, r)
  mask[cx][cy] = true
  ditherEdges(mask, mapWidth, mapHeight, ZoneBlobDitherProb, ZoneBlobDitherDepth, r)

proc applySwampWater*(terrain: var TerrainGrid, biomes: var BiomeGrid,
                      mapWidth, mapHeight, mapBorder: int,
                      r: var Rand, cfg: BiomeSwampConfig) =
  var swampTiles: seq[IVec2] = @[]
  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      if biomes[x][y] != BiomeSwampType:
        continue
      swampTiles.add(ivec2(x.int32, y.int32))
      if randChance(r, cfg.waterScatterProb):
        terrain[x][y] = Water

  if swampTiles.len == 0:
    return

  let tilesPerPond = max(1, cfg.pondTilesPerPond)
  let desired = max(cfg.pondCountMin, swampTiles.len div tilesPerPond)
  let pondCount = min(cfg.pondCountMax, desired)

  for _ in 0 ..< pondCount:
    let center = swampTiles[randIntExclusive(r, 0, swampTiles.len)]
    let radius = randIntInclusive(r, cfg.pondRadiusMin, cfg.pondRadiusMax)
    let radius2 = radius * radius
    let inner2 = max(0, (radius - 1) * (radius - 1))
    for dx in -radius .. radius:
      for dy in -radius .. radius:
        let wx = center.x + dx
        let wy = center.y + dy
        if wx < mapBorder or wx >= mapWidth - mapBorder or
           wy < mapBorder or wy >= mapHeight - mapBorder:
          continue
        if biomes[wx][wy] != BiomeSwampType:
          continue
        let dist2 = dx * dx + dy * dy
        if dist2 > radius2:
          continue
        if dist2 > inner2 and randChance(r, cfg.pondEdgeDitherProb):
          continue
        terrain[wx][wy] = Water

proc applyBiomeZones(terrain: var TerrainGrid, biomes: var BiomeGrid, mapWidth, mapHeight, mapBorder: int,
                     r: var Rand) =
  let kinds = [BiomeForest, BiomeDesert, BiomeCaves, BiomeCity, BiomePlains, BiomeSnow, BiomeSwamp]
  let baseBiomeType = baseBiomeType()
  let edgeChance = 0.25
  let zones = evenlyDistributedZones(r, mapWidth, mapHeight, mapBorder, kinds.len, BiomeZoneMaxFraction)
  for idx, zone in zones:
    let biome = kinds[idx mod kinds.len]
    var zoneMask: MaskGrid
    buildZoneBlobMask(zoneMask, mapWidth, mapHeight, mapBorder, zone, r)
    case biome:
    of BiomeBase:
      discard
    of BiomeForest:
      applyBiomeZoneMask(terrain, biomes, zoneMask, zone, mapWidth, mapHeight, mapBorder,
        r, edgeChance, buildBiomeForestMask, BiomeForestConfig(),
        BiomeForestTerrain, BiomeForestType, baseBiomeType)
    of BiomeDesert:
      # Blend sand into the zone so edges ease into the base biome, then layer dunes.
      applyTerrainBlendToZone(terrain, biomes, zoneMask, zone, mapWidth, mapHeight, mapBorder,
        TerrainSand, BiomeDesertType, baseBiomeType, r, edgeChance, density = 0.3)
      applyBiomeZoneMask(terrain, biomes, zoneMask, zone, mapWidth, mapHeight, mapBorder,
        r, edgeChance, buildBiomeDesertMask, BiomeDesertConfig(),
        TerrainDune, BiomeDesertType, baseBiomeType)
    of BiomeCaves:
      applyBiomeZoneMask(terrain, biomes, zoneMask, zone, mapWidth, mapHeight, mapBorder,
        r, edgeChance, buildBiomeCavesMask, BiomeCavesConfig(),
        BiomeCavesTerrain, BiomeCavesType, baseBiomeType)
    of BiomeSnow:
      applyBiomeZoneInsetFill(terrain, biomes, zoneMask, zone, mapWidth, mapHeight, mapBorder,
        BiomeSnowTerrain, BiomeSnowType, baseBiomeType)
    of BiomeSwamp:
      applyBiomeZoneInsetFill(terrain, biomes, zoneMask, zone, mapWidth, mapHeight, mapBorder,
        BiomeSwampTerrain, BiomeSwampType, baseBiomeType)
    of BiomeCity:
      var mask: MaskGrid
      var roadMask: MaskGrid
      buildBiomeCityMasks(mask, roadMask, mapWidth, mapHeight, mapBorder, r, BiomeCityConfig())
      applyBiomeMaskToZone(terrain, biomes, mask, zoneMask, zone, mapWidth, mapHeight, mapBorder,
        BiomeCityBlockTerrain, BiomeCityType, baseBiomeType, r, edgeChance)
      applyBiomeMaskToZone(terrain, biomes, roadMask, zoneMask, zone, mapWidth, mapHeight, mapBorder,
        BiomeCityRoadTerrain, BiomeCityType, baseBiomeType, r, edgeChance)
    of BiomePlains:
      applyBiomeZoneMask(terrain, biomes, zoneMask, zone, mapWidth, mapHeight, mapBorder,
        r, edgeChance, buildBiomePlainsMask, BiomePlainsConfig(),
        BiomePlainsTerrain, BiomePlainsType, baseBiomeType)

proc applyBaseBiome(terrain: var TerrainGrid, mapWidth, mapHeight, mapBorder: int, r: var Rand) =
  case BaseBiome:
  of BiomeBase:
    discard
  of BiomeForest:
    applyBaseBiomeMask(terrain, mapWidth, mapHeight, mapBorder, r,
      buildBiomeForestMask, BiomeForestConfig(), BiomeForestTerrain)
  of BiomeDesert:
    applyBaseBiomeMask(terrain, mapWidth, mapHeight, mapBorder, r,
      buildBiomeDesertMask, BiomeDesertConfig(), BiomeDesertTerrain)
  of BiomeCaves:
    applyBaseBiomeMask(terrain, mapWidth, mapHeight, mapBorder, r,
      buildBiomeCavesMask, BiomeCavesConfig(), BiomeCavesTerrain)
  of BiomeCity:
    var mask: MaskGrid
    var roadMask: MaskGrid
    buildBiomeCityMasks(mask, roadMask, mapWidth, mapHeight, mapBorder, r, BiomeCityConfig())
    applyMaskToTerrain(terrain, mask, mapWidth, mapHeight, mapBorder, BiomeCityBlockTerrain)
    applyMaskToTerrain(terrain, roadMask, mapWidth, mapHeight, mapBorder, BiomeCityRoadTerrain)
  of BiomePlains:
    applyBaseBiomeMask(terrain, mapWidth, mapHeight, mapBorder, r,
      buildBiomePlainsMask, BiomePlainsConfig(), BiomePlainsTerrain)
  of BiomeSnow:
    applyBaseBiomeMask(terrain, mapWidth, mapHeight, mapBorder, r,
      buildBiomeSnowMask, BiomeSnowConfig(), BiomeSnowTerrain)
  of BiomeSwamp:
    applyBaseBiomeMask(terrain, mapWidth, mapHeight, mapBorder, r,
      buildBiomeSwampMask, BiomeSwampConfig(), BiomeSwampTerrain)

# ---------------------------------------------------------------------------
# River generation: tributary branch paths
# ---------------------------------------------------------------------------

proc generateBranchPath(
    forkPos: IVec2,
    dirY: int,
    mapWidth, mapHeight, mapBorder: int,
    reserve: int,
    inCorner: proc(x, y: int): bool,
    r: var Rand
): seq[IVec2] =
  var path: seq[IVec2] = @[]
  var secondaryPos = forkPos
  var lastValid = forkPos
  var hasValid = false
  let maxSteps = max(mapWidth * 2, mapHeight * 2)
  var steps = 0
  var yBranchVel = dirY

  # Generate meandering branch path
  while secondaryPos.y > mapBorder + RiverWidth and
        secondaryPos.y < mapHeight - mapBorder - RiverWidth and
        steps < maxSteps:
    secondaryPos.x += 1
    if randChance(r, 0.08):
      yBranchVel += sample(r, [-1, 1])
    yBranchVel = max(-1, min(1, yBranchVel))
    if yBranchVel == 0:
      yBranchVel = dirY
    secondaryPos.y += yBranchVel.int32
    if randChance(r, 0.04):
      secondaryPos.y += sample(r, [-1, 0, 1]).int32
    if secondaryPos.x >= mapBorder and secondaryPos.x < mapWidth - mapBorder and
       secondaryPos.y >= mapBorder and secondaryPos.y < mapHeight - mapBorder:
      if not inCorner(secondaryPos.x, secondaryPos.y):
        path.add(secondaryPos)
        lastValid = secondaryPos
        hasValid = true
    else:
      break
    inc steps

  # Extend branch horizontally to safe x-position
  var tip = (if hasValid: lastValid else: forkPos)
  let safeMinX = mapBorder + reserve
  let safeMaxX = mapWidth - mapBorder - reserve - 1
  var edgeX = tip.x.int
  if safeMinX <= safeMaxX:
    if edgeX < safeMinX:
      edgeX = safeMinX
    elif edgeX > safeMaxX:
      edgeX = safeMaxX
  else:
    edgeX = max(mapBorder, min(mapWidth - mapBorder - 1, edgeX))
  if edgeX != tip.x.int:
    let stepX = (if edgeX > tip.x.int: 1 else: -1)
    var x = tip.x.int
    while x != edgeX:
      x += stepX
      let drift = ivec2(x.int32, tip.y)
      if drift.x >= mapBorder and drift.x < mapWidth - mapBorder and
         drift.y >= mapBorder and drift.y < mapHeight - mapBorder:
        if not inCorner(drift.x, drift.y):
          path.add(drift)
          lastValid = drift
          hasValid = true
    tip = (if hasValid: lastValid else: tip)

  # Extend branch vertically to map edge
  var pushSteps = 0
  let maxPush = mapHeight
  if dirY < 0:
    while tip.y > mapBorder and pushSteps < maxPush:
      dec tip.y
      if tip.x >= mapBorder and tip.x < mapWidth and tip.y >= mapBorder and tip.y < mapHeight:
        if not inCorner(tip.x, tip.y):
          path.add(tip)
      inc pushSteps
  else:
    while tip.y < mapHeight - mapBorder and pushSteps < maxPush:
      inc tip.y
      if tip.x >= mapBorder and tip.x < mapWidth and tip.y >= mapBorder and tip.y < mapHeight:
        if not inCorner(tip.x, tip.y):
          path.add(tip)
      inc pushSteps

  result = path

# ---------------------------------------------------------------------------
# River generation: water tile placement
# ---------------------------------------------------------------------------

proc placeWaterPath*(
    terrain: var TerrainGrid,
    path: seq[IVec2],
    radius: int,
    mapWidth, mapHeight: int,
    inCorner: proc(x, y: int): bool
) =
  let radius2 = radius * radius
  # Keep rivers mostly non-walkable deep water, with only a thin shallow fringe.
  let deepRadius2 = max(1, (radius2 * 4) div 5)
  for pos in path:
    for dx in -radius .. radius:
      for dy in -radius .. radius:
        let waterPos = pos + ivec2(dx.int32, dy.int32)
        if waterPos.x < 0 or waterPos.x >= mapWidth or
           waterPos.y < 0 or waterPos.y >= mapHeight:
          continue
        if inCorner(waterPos.x, waterPos.y):
          continue
        let dist2 = dx * dx + dy * dy
        if dist2 > radius2:
          continue
        if dist2 <= deepRadius2:
          terrain[waterPos.x][waterPos.y] = Water
        elif terrain[waterPos.x][waterPos.y] != Water:
          terrain[waterPos.x][waterPos.y] = ShallowWater

# ---------------------------------------------------------------------------
# Bridge helpers (extracted from generateRiver)
# ---------------------------------------------------------------------------

proc slopeSignForRiverAt(riverYByX: seq[int], center: IVec2): int =
  ## Determine the river's slope direction at a given x-position.
  let x = center.x.int
  let y = center.y.int
  if x + 1 < riverYByX.len and riverYByX[x + 1] >= 0:
    let dy = riverYByX[x + 1] - y
    if dy != 0:
      return (if dy > 0: 1 else: -1)
  if x - 1 >= 0 and riverYByX[x - 1] >= 0:
    let dy = y - riverYByX[x - 1]
    if dy != 0:
      return (if dy > 0: 1 else: -1)
  0

proc slopeSignForPath(path: seq[IVec2], center: IVec2): int =
  ## Determine the slope direction along a path at a given position.
  let idx = path.find(center)
  if idx < 0:
    return 0
  if idx + 1 < path.len:
    let dy = (path[idx + 1].y - center.y).int
    if dy != 0:
      return (if dy > 0: 1 else: -1)
  if idx > 0:
    let dy = (center.y - path[idx - 1].y).int
    if dy != 0:
      return (if dy > 0: 1 else: -1)
  0

proc placeBridgeSpan(terrain: var TerrainGrid, center, dir, width: IVec2,
                     mapWidth, mapHeight, mapBorder: int,
                     inCorner: proc(x, y: int): bool) =
  ## Place a three-tile-wide bridge span across water in the given direction.
  let bridgeOverhang = 1
  let scanLimit = RiverWidth * 2 + 6
  let cx = center.x.int
  let cy = center.y.int
  let dx = dir.x.int
  let dy = dir.y.int
  let wx = width.x.int
  let wy = width.y.int

  template setBridgeTile(x, y: int) =
    if x >= mapBorder and x < mapWidth - mapBorder and
       y >= mapBorder and y < mapHeight - mapBorder and
       not inCorner(x, y):
      terrain[x][y] = Bridge

  proc hasWaterAt(grid: var TerrainGrid, step: int): bool =
    for w in -1 .. 1:
      let x = cx + dx * step + wx * w
      let y = cy + dy * step + wy * w
      if x < mapBorder or x >= mapWidth - mapBorder or
         y < mapBorder or y >= mapHeight - mapBorder:
        continue
      if inCorner(x, y):
        continue
      if grid[x][y] in {Water, Bridge}:
        return true
    false

  if not hasWaterAt(terrain, 0):
    return
  var startStep = 0
  var endStep = 0
  while startStep > -scanLimit and hasWaterAt(terrain, startStep - 1):
    dec startStep
  while endStep < scanLimit and hasWaterAt(terrain, endStep + 1):
    inc endStep
  startStep -= bridgeOverhang
  endStep += bridgeOverhang

  if abs(dx) + abs(dy) == 2:
    let spanSteps = endStep - startStep
    for w in -1 .. 1:
      var x = cx + dx * startStep + wx * w
      var y = cy + dy * startStep + wy * w
      setBridgeTile(x, y)
      for _ in 0 ..< spanSteps:
        x += dx
        setBridgeTile(x, y)
        y += dy
        setBridgeTile(x, y)
  else:
    for step in startStep .. endStep:
      for w in -1 .. 1:
        let x = cx + dx * step + wx * w
        let y = cy + dy * step + wy * w
        setBridgeTile(x, y)

proc placeBridgeOnRiver(terrain: var TerrainGrid, center: IVec2,
                        riverYByX: seq[int],
                        mapWidth, mapHeight, mapBorder: int,
                        inCorner: proc(x, y: int): bool) =
  ## Place a bridge across the main river at the given center point.
  let slope = slopeSignForRiverAt(riverYByX, center)
  if slope != 0:
    placeBridgeSpan(terrain, center, ivec2(1'i32, (-slope).int32),
                    ivec2(1'i32, slope.int32), mapWidth, mapHeight, mapBorder, inCorner)
  else:
    placeBridgeSpan(terrain, center, ivec2(0, 1), ivec2(1, 0),
                    mapWidth, mapHeight, mapBorder, inCorner)

proc placeBridgeOnBranch(terrain: var TerrainGrid, center: IVec2,
                         branchUpPath, branchDownPath: seq[IVec2],
                         mapWidth, mapHeight, mapBorder: int,
                         inCorner: proc(x, y: int): bool) =
  ## Place a bridge across a tributary branch at the given center point.
  var slope = slopeSignForPath(branchUpPath, center)
  if slope == 0:
    slope = slopeSignForPath(branchDownPath, center)
  if slope != 0:
    placeBridgeSpan(terrain, center, ivec2(1'i32, (-slope).int32),
                    ivec2(1'i32, slope.int32), mapWidth, mapHeight, mapBorder, inCorner)
  else:
    placeBridgeSpan(terrain, center, ivec2(1, 0), ivec2(0, 1),
                    mapWidth, mapHeight, mapBorder, inCorner)

proc buildBridgeCandidates(path: seq[IVec2],
                           mapWidth, mapHeight, mapBorder: int,
                           inCorner: proc(x, y: int): bool): seq[IVec2] =
  result = @[]
  for pos in path:
    if pos.x > mapBorder + RiverWidth and pos.x < mapWidth - mapBorder - RiverWidth and
       pos.y > mapBorder + RiverWidth and pos.y < mapHeight - mapBorder - RiverWidth and
       not inCorner(pos.x, pos.y):
      result.add(pos)

proc placeBridges(terrain: var TerrainGrid,
                  riverPath, branchUpPath, branchDownPath: seq[IVec2],
                  riverYByX: seq[int],
                  forkUpIdx, forkDownIdx: int,
                  mapWidth, mapHeight, mapBorder: int,
                  inCorner: proc(x, y: int): bool,
                  r: var Rand) =
  ## Place bridges across the river and tributary branches.
  let mainCandidates = buildBridgeCandidates(riverPath, mapWidth, mapHeight, mapBorder, inCorner)
  let branchUpCandidates = buildBridgeCandidates(branchUpPath, mapWidth, mapHeight, mapBorder, inCorner)
  let branchDownCandidates = buildBridgeCandidates(branchDownPath, mapWidth, mapHeight, mapBorder, inCorner)

  let hasBranch = branchUpPath.len > 0 or branchDownPath.len > 0
  let desiredBridges = max(randIntInclusive(r, 3, 4), (if hasBranch: 3 else: 0)) * 2

  var placed: seq[IVec2] = @[]

  template placeFromMain(cands: seq[IVec2]) =
    if cands.len > 0:
      let center = cands[cands.len div 2]
      placeBridgeOnRiver(terrain, center, riverYByX, mapWidth, mapHeight, mapBorder, inCorner)
      placed.add(center)

  # Place strategic bridges near fork points
  if hasBranch:
    if forkUpIdx >= 0:
      let upstream = if forkUpIdx > 0: mainCandidates[0 ..< min(forkUpIdx, mainCandidates.len)] else: @[]
      placeFromMain(upstream)
    for candidates in [branchUpCandidates, branchDownCandidates]:
      if candidates.len > 0:
        let firstIdx = candidates.len div 3
        let secondIdx = max(firstIdx + 1, (candidates.len * 2) div 3)
        placeBridgeOnBranch(terrain, candidates[firstIdx], branchUpPath, branchDownPath,
                            mapWidth, mapHeight, mapBorder, inCorner)
        placed.add(candidates[firstIdx])
        if secondIdx < candidates.len:
          placeBridgeOnBranch(terrain, candidates[secondIdx], branchUpPath, branchDownPath,
                              mapWidth, mapHeight, mapBorder, inCorner)
          placed.add(candidates[secondIdx])
    if forkDownIdx >= 0 and forkDownIdx < mainCandidates.len:
      let downstream = mainCandidates[min(forkDownIdx, mainCandidates.len - 1) ..< mainCandidates.len]
      placeFromMain(downstream)

  # Fill remaining bridges by spreading along main river first, then branches
  var remaining = desiredBridges - placed.len
  let remainingGroups: array[3, tuple[cands: seq[IVec2], isBranch: bool]] = [
    (cands: mainCandidates, isBranch: false),
    (cands: branchUpCandidates, isBranch: true),
    (cands: branchDownCandidates, isBranch: true)
  ]
  for group in remainingGroups:
    if remaining <= 0:
      break
    if group.cands.len == 0:
      continue
    let stride = max(1, group.cands.len div (remaining + 1))
    var candidateIdx = stride
    while remaining > 0 and candidateIdx < group.cands.len:
      let center = group.cands[candidateIdx]
      if center notin placed:
        placed.add(center)
      if group.isBranch:
        placeBridgeOnBranch(terrain, center, branchUpPath, branchDownPath,
                            mapWidth, mapHeight, mapBorder, inCorner)
      else:
        placeBridgeOnRiver(terrain, center, riverYByX, mapWidth, mapHeight, mapBorder, inCorner)
      dec remaining
      candidateIdx += stride

# ---------------------------------------------------------------------------
# Road generation (extracted from generateRiver)
# ---------------------------------------------------------------------------

proc computeDirectionToGoal(current, goal: IVec2): IVec2 =
  ## Compute the primary direction vector toward a goal position.
  let dx = goal.x - current.x
  let dy = goal.y - current.y
  let sx = (if dx < 0: -1'i32 elif dx > 0: 1'i32 else: 0'i32)
  let sy = (if dy < 0: -1'i32 elif dy > 0: 1'i32 else: 0'i32)
  if abs(dx) >= abs(dy): ivec2(sx, 0) else: ivec2(0, sy)

proc chooseSegmentDirection(baseDir: IVec2, r: var Rand): tuple[dir: IVec2, steps: int, toggle: bool] =
  ## Choose a randomized segment direction based on the base direction toward goal.
  let orthoA = ivec2(baseDir.y, baseDir.x)
  let orthoB = ivec2(-baseDir.y, -baseDir.x)
  let diagA = ivec2(baseDir.x + orthoA.x, baseDir.y + orthoA.y)
  let diagB = ivec2(baseDir.x + orthoB.x, baseDir.y + orthoB.y)
  let roll = randFloat(r)
  let dir = if roll < 0.35:
    if randChance(r, 0.5): diagA else: diagB
  elif roll < 0.92:
    baseDir
  else:
    if randChance(r, 0.5): orthoA else: orthoB
  (dir: dir, steps: randIntInclusive(r, 7, 12), toggle: randChance(r, 0.5))

proc isValidRoadPosition(pos: IVec2, terrain: TerrainGrid,
                         side, riverMid, mapBorder, mapWidth, mapHeight: int,
                         inCorner: proc(x, y: int): bool): bool =
  ## Check if a position is valid for road placement.
  if pos.x < mapBorder or pos.x >= mapWidth - mapBorder:
    return false
  if pos.y < mapBorder or pos.y >= mapHeight - mapBorder:
    return false
  if inCorner(pos.x, pos.y):
    return false
  if terrain[pos.x][pos.y] == Water:
    return false
  if side < 0 and pos.y >= riverMid:
    return false
  if side > 0 and pos.y <= riverMid:
    return false
  true

proc findBestFallbackMove(terrain: TerrainGrid, current, goalPos: IVec2,
                          side, riverMid, mapBorder, mapWidth, mapHeight: int,
                          inCorner: proc(x, y: int): bool, r: var Rand): IVec2 =
  ## Find the best fallback move when the preferred direction is blocked.
  ## Returns (0, 0) if no valid move exists.
  const dirs = [ivec2(1, 0), ivec2(-1, 0), ivec2(0, 1), ivec2(0, -1)]
  var bestScore = int.high
  var best: seq[IVec2] = @[]
  for d in dirs:
    let nx = current.x + d.x
    let ny = current.y + d.y
    if not isValidRoadPosition(ivec2(nx, ny), terrain, side, riverMid,
                               mapBorder, mapWidth, mapHeight, inCorner):
      continue
    let terrainHere = terrain[nx][ny]
    var score = abs(goalPos.x - nx).int + abs(goalPos.y - ny).int
    if terrainHere == Bridge:
      score -= 2
    elif terrainHere == Road:
      score -= 1
    score += randIntInclusive(r, 0, 2)
    if score < bestScore:
      bestScore = score
      best.setLen(0)
      best.add(ivec2(nx, ny))
    elif score == bestScore:
      best.add(ivec2(nx, ny))
  if best.len == 0:
    return ivec2(0, 0)
  best[randIntExclusive(r, 0, best.len)]

proc carveRoadPath(terrain: var TerrainGrid, startPos, goalPos: IVec2,
                   side, riverMid: int,
                   mapWidth, mapHeight, mapBorder: int,
                   inCorner: proc(x, y: int): bool,
                   r: var Rand) =
  ## Carve a meandering road path between two points.
  ## `side` constrains which side of the river to stay on: -1 = north, 1 = south, 0 = either.
  var current = startPos
  var segmentDir = ivec2(0, 0)
  var segmentStepsLeft = 0
  var diagToggle = false
  let maxSteps = mapWidth * mapHeight
  var steps = 0
  var stagnation = 0
  var lastDist = abs(goalPos.x - current.x).int + abs(goalPos.y - current.y).int

  if terrain[current.x][current.y] notin {Water, Bridge}:
    terrain[current.x][current.y] = Road

  while current != goalPos and steps < maxSteps:
    # Choose a new segment direction when needed
    if segmentStepsLeft <= 0 or stagnation > 10 or steps > (maxSteps div 2):
      let baseDir = computeDirectionToGoal(current, goalPos)
      if baseDir.x == 0 and baseDir.y == 0:
        break
      let segment = chooseSegmentDirection(baseDir, r)
      segmentDir = segment.dir
      segmentStepsLeft = segment.steps
      diagToggle = segment.toggle

    # Compute step direction (handle diagonal by alternating)
    let stepDir = if segmentDir.x != 0 and segmentDir.y != 0:
      let dir = if diagToggle: ivec2(segmentDir.x, 0) else: ivec2(0, segmentDir.y)
      diagToggle = not diagToggle
      dir
    else:
      segmentDir

    # Try preferred direction, fallback to best alternative
    let nextPos = current + stepDir
    var moved = false
    if isValidRoadPosition(nextPos, terrain, side, riverMid,
                           mapBorder, mapWidth, mapHeight, inCorner):
      current = nextPos
      dec segmentStepsLeft
      moved = true
    else:
      segmentStepsLeft = 0
      let fallback = findBestFallbackMove(terrain, current, goalPos,
                                          side, riverMid, mapBorder, mapWidth, mapHeight,
                                          inCorner, r)
      if fallback.x == 0 and fallback.y == 0:
        break
      current = fallback
      moved = true

    # Place road tile and update tracking
    if moved:
      if terrain[current.x][current.y] notin {Water, Bridge}:
        terrain[current.x][current.y] = Road
      let newDist = abs(goalPos.x - current.x).int + abs(goalPos.y - current.y).int
      if newDist >= lastDist:
        inc stagnation
      else:
        stagnation = 0
      lastDist = newDist
      inc steps

proc generateRoadGrid(terrain: var TerrainGrid,
                      riverPath: seq[IVec2], riverYByX: seq[int],
                      mapWidth, mapHeight, mapBorder: int,
                      inCorner: proc(x, y: int): bool,
                      r: var Rand) =
  ## Generate a meandering road grid that criss-crosses the map.
  var riverMid = mapHeight div 2
  if riverPath.len > 0:
    var sumY = 0
    for pos in riverPath:
      sumY += pos.y.int
    riverMid = sumY div riverPath.len

  # Vertical roads
  let verticalCount = randIntInclusive(r, 4, 5)
  let playWidth = mapWidth - 2 * mapBorder
  let vStride = max(1, playWidth div (verticalCount + 1))
  var vIdx = vStride
  var roadXs: seq[int] = @[]
  while roadXs.len < verticalCount and vIdx < mapWidth - mapBorder:
    let jitter = max(1, vStride div 4)
    var x = vIdx + randIntInclusive(r, -jitter, jitter)
    x = max(mapBorder + 2, min(mapWidth - mapBorder - 3, x))
    if x notin roadXs:
      roadXs.add(x)
    vIdx += vStride

  for x in roadXs:
    let start = ivec2(x.int32, (mapBorder + 1).int32)
    let goal = ivec2(x.int32, (mapHeight - mapBorder - 2).int32)
    if x >= 0 and x < riverYByX.len and riverYByX[x] >= 0:
      let bridgeCenter = ivec2(x.int32, riverYByX[x].int32)
      placeBridgeOnRiver(terrain, bridgeCenter, riverYByX, mapWidth, mapHeight, mapBorder, inCorner)
      carveRoadPath(terrain, start, bridgeCenter, 0, riverMid,
                    mapWidth, mapHeight, mapBorder, inCorner, r)
      carveRoadPath(terrain, bridgeCenter, goal, 0, riverMid,
                    mapWidth, mapHeight, mapBorder, inCorner, r)
    else:
      carveRoadPath(terrain, start, goal, 0, riverMid,
                    mapWidth, mapHeight, mapBorder, inCorner, r)

  # Horizontal roads (north of river)
  let northCount = randIntInclusive(r, 1, 2)
  let northMin = mapBorder + 2
  let northMax = min(mapHeight - mapBorder - 3, riverMid - (RiverWidth div 2) - 3)
  if northMax >= northMin:
    let nStride = max(1, (northMax - northMin) div (northCount + 1))
    var y = northMin + nStride
    for _ in 0 ..< northCount:
      let start = ivec2((mapBorder + 1).int32, y.int32)
      let goal = ivec2((mapWidth - mapBorder - 2).int32, y.int32)
      carveRoadPath(terrain, start, goal, -1, riverMid,
                    mapWidth, mapHeight, mapBorder, inCorner, r)
      y += nStride

  # Horizontal roads (south of river)
  let southCount = randIntInclusive(r, 1, 2)
  let southMin = max(mapBorder + 2, riverMid + (RiverWidth div 2) + 3)
  let southMax = mapHeight - mapBorder - 3
  if southMax >= southMin:
    let sStride = max(1, (southMax - southMin) div (southCount + 1))
    var y = southMin + sStride
    for _ in 0 ..< southCount:
      let start = ivec2((mapBorder + 1).int32, y.int32)
      let goal = ivec2((mapWidth - mapBorder - 2).int32, y.int32)
      carveRoadPath(terrain, start, goal, 1, riverMid,
                    mapWidth, mapHeight, mapBorder, inCorner, r)
      y += sStride

# ---------------------------------------------------------------------------
# Main river generation orchestrator
# ---------------------------------------------------------------------------

proc generateRiver*(terrain: var TerrainGrid, mapWidth, mapHeight, mapBorder: int, r: var Rand) =
  ## Generate the river system: main river, tributaries, bridges, and road grid.
  var riverPath: seq[IVec2] = @[]
  var riverYByX: seq[int] = newSeq[int](mapWidth)
  for x in 0 ..< mapWidth:
    riverYByX[x] = -1

  # Reserve corners for villages so river doesn't block them
  let reserve = max(8, min(mapWidth, mapHeight) div 10)

  let inCorner = proc(x, y: int): bool =
    isInCorner(x, y, mapBorder, reserve, mapWidth, mapHeight)

  # Generate main river path (left to right)
  let centerY = mapHeight div 2
  let span = max(6, mapHeight div 6)
  var startMin = max(mapBorder + RiverWidth + reserve, centerY - span)
  var startMax = min(mapHeight - mapBorder - RiverWidth - reserve, centerY + span)
  if startMin > startMax: swap(startMin, startMax)
  let yMin = max(mapBorder + RiverWidth + reserve, mapBorder + 2)
  let yMax = min(mapHeight - mapBorder - RiverWidth - reserve, mapHeight - mapBorder - 2)
  var currentPos = ivec2(mapBorder.int32, randIntInclusive(r, startMin, startMax).int32)
  var targetY = randIntInclusive(r, yMin, yMax)
  var yVel = 0

  while currentPos.x >= mapBorder and currentPos.x < mapWidth - mapBorder and
        currentPos.y >= mapBorder and currentPos.y < mapHeight - mapBorder:
    riverPath.add(currentPos)
    currentPos.x += 1
    if randChance(r, 0.02):
      targetY = randIntInclusive(r, yMin, yMax)
    let dyBias = if targetY < currentPos.y.int: -1 elif targetY > currentPos.y.int: 1 else: 0
    if randChance(r, 0.12):
      yVel += dyBias
    elif randChance(r, 0.03):
      yVel += sample(r, [-1, 1])
    yVel = max(-1, min(1, yVel))
    if yVel != 0 or randChance(r, 0.08):
      currentPos.y += yVel.int32
    if currentPos.y < yMin.int32:
      currentPos.y = yMin.int32
      yVel = 1
    elif currentPos.y > yMax.int32:
      currentPos.y = yMax.int32
      yVel = -1

  # Find fork points for tributary branches
  var forkUp, forkDown: IVec2
  var forkUpIdx, forkDownIdx = -1
  var forkCandidates: seq[IVec2] = @[]
  for pos in riverPath:
    if pos.y > mapBorder + RiverWidth + 2 and pos.y < mapHeight - mapBorder - RiverWidth - 2 and
       not inCorner(pos.x, pos.y):
      forkCandidates.add(pos)
  let forkSource = if forkCandidates.len > 0: forkCandidates else: riverPath
  if forkSource.len > 0:
    let upIdx = forkSource.len div 3
    let downIdx = max(upIdx + 1, (forkSource.len * 2) div 3)
    forkUp = forkSource[upIdx]
    forkDown = forkSource[min(downIdx, forkSource.len - 1)]

  # Generate tributary branches
  var branchUpPath, branchDownPath: seq[IVec2] = @[]
  if riverPath.len > 0:
    forkUpIdx = riverPath.find(forkUp)
    forkDownIdx = riverPath.find(forkDown)
    branchUpPath = generateBranchPath(forkUp, -1, mapWidth, mapHeight, mapBorder, reserve, inCorner, r)
    branchDownPath = generateBranchPath(forkDown, 1, mapWidth, mapHeight, mapBorder, reserve, inCorner, r)

  # Place water tiles for main river
  for pos in riverPath:
    if pos.x >= 0 and pos.x < mapWidth:
      riverYByX[pos.x] = pos.y.int
  placeWaterPath(terrain, riverPath, RiverWidth div 2, mapWidth, mapHeight, inCorner)

  # Place water tiles for tributary branches (narrower than main river)
  let branchRadius = RiverWidth div 2 - 1
  placeWaterPath(terrain, branchUpPath, branchRadius, mapWidth, mapHeight, inCorner)
  placeWaterPath(terrain, branchDownPath, branchRadius, mapWidth, mapHeight, inCorner)

  # Place bridges and generate road grid
  placeBridges(terrain, riverPath, branchUpPath, branchDownPath, riverYByX,
               forkUpIdx, forkDownIdx, mapWidth, mapHeight, mapBorder, inCorner, r)
  generateRoadGrid(terrain, riverPath, riverYByX, mapWidth, mapHeight, mapBorder, inCorner, r)

const
  ## Mountain chokepoint generation parameters.
  MountainMinSegmentLen* = 12    ## Minimum boundary segment length to consider
  MountainRidgeThickness* = 2   ## Extra tiles on each side of boundary
  MountainPassWidth* = 3        ## Tile width of passes through ridges
  MountainChance* = 0.40        ## Probability of mountainizing a boundary segment
  MountainMinChokepoints* = 2   ## Minimum mountain chokepoints per map
  ## Biome pairs that qualify for mountain ridges.
  ## Includes BiomeBaseType boundaries since biome zones are islands
  ## surrounded by base biome — these are the most common boundaries.
  MountainBiomePairs = [
    (BiomeBaseType, BiomeSnowType),
    (BiomeBaseType, BiomeCavesType),
    (BiomeBaseType, BiomeDesertType),
    (BiomeBaseType, BiomeSwampType),
    (BiomeSnowType, BiomeForestType),
    (BiomeSnowType, BiomePlainsType),
    (BiomeSnowType, BiomeCavesType),
    (BiomeDesertType, BiomePlainsType),
    (BiomeDesertType, BiomeForestType),
    (BiomeCavesType, BiomeForestType),
    (BiomeCavesType, BiomePlainsType),
    (BiomeSwampType, BiomeForestType),
    (BiomeSwampType, BiomePlainsType),
  ]

proc isQualifyingBiomePair(a, b: BiomeType): bool =
  for pair in MountainBiomePairs:
    if (a == pair[0] and b == pair[1]) or (a == pair[1] and b == pair[0]):
      return true
  false

proc applyMountainChokepoints*(terrain: var TerrainGrid, biomes: BiomeGrid,
                               mapWidth, mapHeight, mapBorder: int,
                               r: var Rand) =
  ## Place mountain ridges along qualifying biome boundaries to create chokepoints.
  ## Each ridge has 1-2 passes for unit passage. Connectivity is ensured by
  ## makeConnected() which runs later.

  # Step 1: Find boundary tiles between qualifying biome pairs.
  let reserve = max(8, min(mapWidth, mapHeight) div 10)
  var boundaryMask: MaskGrid
  boundaryMask.clearMask(mapWidth, mapHeight)

  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      # Skip corner areas reserved for villages.
      if isInCorner(x, y, mapBorder, reserve, mapWidth, mapHeight):
        continue
      let biome = biomes[x][y]
      if biome == BiomeNone:
        continue
      # Check 4-connected neighbors for different qualifying biome.
      for d in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0)]:
        let nx = x + d.x.int
        let ny = y + d.y.int
        if nx < mapBorder or nx >= mapWidth - mapBorder or
           ny < mapBorder or ny >= mapHeight - mapBorder:
          continue
        let neighborBiome = biomes[nx][ny]
        if neighborBiome != biome and isQualifyingBiomePair(biome, neighborBiome):
          boundaryMask[x][y] = true
          break

  # Step 2: Label connected components of boundary tiles.
  var labels: array[MaxTerrainSize, array[MaxTerrainSize, int16]]
  for x in 0 ..< mapWidth:
    for y in 0 ..< mapHeight:
      labels[x][y] = 0

  var segmentCount = 0
  var segmentSizes: seq[int] = @[]
  var segmentCenters: seq[IVec2] = @[]

  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      if not boundaryMask[x][y] or labels[x][y] != 0:
        continue
      inc segmentCount
      var queue: seq[IVec2] = @[ivec2(x.int32, y.int32)]
      var head = 0
      labels[x][y] = segmentCount.int16
      var count = 0
      var sumX = 0
      var sumY = 0
      while head < queue.len:
        let pos = queue[head]
        inc head
        inc count
        sumX += pos.x.int
        sumY += pos.y.int
        for d in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
                  ivec2(1, -1), ivec2(1, 1), ivec2(-1, 1), ivec2(-1, -1)]:
          let nx = pos.x + d.x
          let ny = pos.y + d.y
          if nx < mapBorder.int32 or nx >= (mapWidth - mapBorder).int32 or
             ny < mapBorder.int32 or ny >= (mapHeight - mapBorder).int32:
            continue
          if boundaryMask[nx][ny] and labels[nx][ny] == 0:
            labels[nx][ny] = segmentCount.int16
            queue.add(ivec2(nx, ny))
      segmentSizes.add(count)
      if count > 0:
        segmentCenters.add(ivec2((sumX div count).int32, (sumY div count).int32))
      else:
        segmentCenters.add(ivec2(0, 0))

  # Step 3: Select segments to mountainize.
  var selectedSegments: seq[int] = @[]
  for i in 0 ..< segmentCount:
    if segmentSizes[i] >= MountainMinSegmentLen and randChance(r, MountainChance):
      selectedSegments.add(i + 1)  # Labels are 1-indexed

  # Ensure minimum chokepoint count by forcibly selecting largest unselected segments.
  if selectedSegments.len < MountainMinChokepoints:
    var candidates: seq[tuple[size: int, label: int]] = @[]
    for i in 0 ..< segmentCount:
      let label = i + 1
      if segmentSizes[i] >= MountainMinSegmentLen and label notin selectedSegments:
        candidates.add((size: segmentSizes[i], label: label))
    # Sort by size descending.
    for i in 0 ..< candidates.len:
      for j in i + 1 ..< candidates.len:
        if candidates[j].size > candidates[i].size:
          swap(candidates[i], candidates[j])
    for c in candidates:
      if selectedSegments.len >= MountainMinChokepoints:
        break
      selectedSegments.add(c.label)

  if selectedSegments.len == 0:
    return

  # Step 4: Apply Mountain terrain to selected boundary segments with thickening.
  # Build a mountain mask by expanding boundary tiles outward.
  var mountainMask: MaskGrid
  mountainMask.clearMask(mapWidth, mapHeight)

  for label in selectedSegments:
    for x in mapBorder ..< mapWidth - mapBorder:
      for y in mapBorder ..< mapHeight - mapBorder:
        if labels[x][y] != label.int16:
          continue
        # Mark this tile and surrounding tiles for mountain.
        for dx in -MountainRidgeThickness .. MountainRidgeThickness:
          for dy in -MountainRidgeThickness .. MountainRidgeThickness:
            let mx = x + dx
            let my = y + dy
            if mx < mapBorder or mx >= mapWidth - mapBorder or
               my < mapBorder or my >= mapHeight - mapBorder:
              continue
            if isInCorner(mx, my, mapBorder, reserve, mapWidth, mapHeight):
              continue
            # Don't overwrite water or bridge terrain.
            if terrain[mx][my] in {Water, ShallowWater, Bridge, Road}:
              continue
            mountainMask[mx][my] = true

  # Step 5: Cut passes through each mountain segment.
  # For each selected segment, find a pass location near the center and clear it.
  for idx, label in selectedSegments:
    let center = segmentCenters[label - 1]
    let passCount = randIntInclusive(r, 1, 2)

    for passIdx in 0 ..< passCount:
      # Find pass location: offset from center along the segment.
      var passCenter = center
      if passCount > 1:
        # Spread passes apart by shifting along the boundary.
        let offsetFraction = if passIdx == 0: 0.33 else: 0.67
        # Find a tile in the segment near this fraction of the segment extent.
        var segmentTiles: seq[IVec2] = @[]
        for x in mapBorder ..< mapWidth - mapBorder:
          for y in mapBorder ..< mapHeight - mapBorder:
            if labels[x][y] == label.int16:
              segmentTiles.add(ivec2(x.int32, y.int32))
        if segmentTiles.len > 0:
          let targetIdx = int(offsetFraction * segmentTiles.len.float)
          passCenter = segmentTiles[min(targetIdx, segmentTiles.len - 1)]

      # Clear a circular pass of MountainPassWidth radius around the pass center.
      let passRadius = MountainPassWidth
      for dx in -passRadius .. passRadius:
        for dy in -passRadius .. passRadius:
          if dx * dx + dy * dy > passRadius * passRadius:
            continue
          let px = passCenter.x.int + dx
          let py = passCenter.y.int + dy
          if px >= 0 and px < mapWidth and py >= 0 and py < mapHeight:
            mountainMask[px][py] = false

  # Step 6: Apply the mountain mask to terrain.
  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      if mountainMask[x][y]:
        terrain[x][y] = Mountain

proc initTerrain*(terrain: var TerrainGrid, biomes: var BiomeGrid,
                  mapWidth, mapHeight, mapBorder: int, seed: int = 2024) =
  ## Initialize base terrain and biomes (no water features).
  var rng = initRand(seed)

  if mapWidth > terrain.len or mapHeight > terrain[0].len:
    raise newException(ValueError, "Map size exceeds TerrainGrid bounds")

  for x in 0 ..< mapWidth:
    for y in 0 ..< mapHeight:
      terrain[x][y] = Empty
      biomes[x][y] = BiomeNone

  # Set base biome background across the playable area.
  let baseBiomeType = baseBiomeType()
  for x in mapBorder ..< mapWidth - mapBorder:
    for y in mapBorder ..< mapHeight - mapBorder:
      biomes[x][y] = baseBiomeType

  if UseBiomeTerrain:
    applyBaseBiome(terrain, mapWidth, mapHeight, mapBorder, rng)
  if UseBiomeZones:
    applyBiomeZones(terrain, biomes, mapWidth, mapHeight, mapBorder, rng)
  # Apply mountain chokepoints along biome boundaries.
  applyMountainChokepoints(terrain, biomes, mapWidth, mapHeight, mapBorder, rng)

proc getStructureElements*(structure: Structure, topLeft: IVec2): tuple[
    walls: seq[IVec2],
    doors: seq[IVec2],
    floors: seq[IVec2],
    altars: seq[IVec2],
    blacksmiths: seq[IVec2],
    clayOvens: seq[IVec2],
    weavingLooms: seq[IVec2],
    center: IVec2
  ] =
  ## Extract tiles for placing a structure
  result = (
    walls: @[],
    doors: @[],
    floors: @[],
    altars: @[],
    blacksmiths: @[],
    clayOvens: @[],
    weavingLooms: @[],
    center: topLeft + structure.centerPos
  )

  for y, row in structure.layout:
    for x, cell in row:
      let pos = ivec2(topLeft.x + x.int32, topLeft.y + y.int32)
      case cell
      of StructureWallChar: result.walls.add(pos)
      of StructureDoorChar: result.doors.add(pos)
      of StructureFloorChar: result.floors.add(pos)
      of StructureAltarChar: result.altars.add(pos)
      of StructureBlacksmithChar: result.blacksmiths.add(pos)
      of StructureClayOvenChar: result.clayOvens.add(pos)
      of StructureWeavingLoomChar: result.weavingLooms.add(pos)
      else: discard
