# This file is included by src/environment.nim
import std/math
import replay_writer

proc createTumor(env: Environment, pos: IVec2, homeSpawner: IVec2, r: var Rand): Thing =
  ## Create a new Tumor seed that can branch once before turning inert.
  ## Uses object pool when available.
  result = acquireThing(env, Tumor)
  result.pos = pos
  result.orientation = Orientation(randIntInclusive(r, 0, 3))
  result.homeSpawner = homeSpawner
  result.hasClaimedTerritory = false
  result.turnsAlive = 0

const
  ResourceGround = {TerrainEmpty, TerrainGrass, TerrainSand, TerrainSnow, TerrainDune, TerrainMud}
  TreeGround = {TerrainEmpty, TerrainGrass, TerrainSand, TerrainDune, TerrainMud}
  TradingHubSize = 15
  TradingHubTint = TileColor(r: 0.58, g: 0.58, b: 0.58, intensity: 1.0)

type TreeOasis = tuple[center: IVec2, rx: int, ry: int]

proc randInteriorPos(r: var Rand, pad: int): IVec2 =
  let x = randIntInclusive(r, MapBorder + pad, MapWidth - MapBorder - pad)
  let y = randIntInclusive(r, MapBorder + pad, MapHeight - MapBorder - pad)
  ivec2(x.int32, y.int32)

proc setTerrain(env: Environment, pos: IVec2, kind: TerrainType) {.inline.} =
  env.terrain[pos.x][pos.y] = kind
  env.resetTileColor(pos)

proc clearTreeElseSkip(env: Environment, pos: IVec2): bool =
  let existing = env.getThing(pos)
  if existing.isNil:
    return true
  if existing.kind == Tree:
    removeThing(env, existing)
    return true
  false

proc isBlockedForPlacement(env: Environment, pos: IVec2,
                           allowWater: bool = false,
                           checkFrozen: bool = true): bool {.inline.} =
  (not allowWater and env.terrain[pos.x][pos.y] == Water) or
    env.terrain[pos.x][pos.y] == Mountain or
    (checkFrozen and isTileFrozen(pos, env))

type AttemptPredicate = proc(pos: IVec2, attempt: int): bool {.closure.}

proc pickInteriorPos(r: var Rand, pad, attempts: int, accept: AttemptPredicate): IVec2 =
  for attempt in 0 ..< attempts:
    let pos = randInteriorPos(r, pad)
    if accept(pos, attempt):
      return pos
  randInteriorPos(r, pad)

proc tryPickEmptyPos(r: var Rand, env: Environment, attempts: int,
                     accept: AttemptPredicate, pos: var IVec2): bool =
  for attempt in 0 ..< attempts:
    let candidate = r.randomEmptyPos(env)
    if accept(candidate, attempt):
      pos = candidate
      return true
  false

proc gatherEmptyAround(env: Environment, center: IVec2, primaryRadius: int,
                       secondaryRadius: int, minCount: int): seq[IVec2] =
  result = env.findEmptyPositionsAround(center, primaryRadius)
  if secondaryRadius > 0 and result.len < minCount:
    let extras = env.findEmptyPositionsAround(center, secondaryRadius)
    for pos in extras:
      if pos notin result:
        result.add(pos)

proc addResourceNode(env: Environment, pos: IVec2, kind: ThingKind,
                     item: ItemKey, amount: int = ResourceNodeInitial) =
  if not env.isSpawnable(pos):
    return
  let resourceNode = Thing(kind: kind, pos: pos)
  resourceNode.inventory = emptyInventory()
  if item != ItemNone and amount > 0:
    setInv(resourceNode, item, amount)
  env.add(resourceNode)

proc placeResourceCluster(env: Environment, centerX, centerY: int, size: int,
                          baseDensity: float, falloffRate: float, kind: ThingKind,
                          item: ItemKey, allowedTerrain: set[TerrainType], r: var Rand,
                          allowedBiomes: set[BiomeType] = {}) =
  let radius = max(1, (size.float / 2.0).int)
  for dx in -radius .. radius:
    for dy in -radius .. radius:
      let x = centerX + dx
      let y = centerY + dy
      if x < 0 or x >= MapWidth or y < 0 or y >= MapHeight:
        continue
      if env.terrain[x][y] notin allowedTerrain:
        continue
      if allowedBiomes.card > 0 and env.biomes[x][y] notin allowedBiomes:
        continue
      let dist = sqrt((dx * dx + dy * dy).float)
      if dist > radius.float:
        continue
      if randChance(r, baseDensity - (dist / radius.float) * falloffRate):
        addResourceNode(env, ivec2(x.int32, y.int32), kind, item)

proc placeBiomeResourceClusters(env: Environment, r: var Rand, count: int,
                                sizeMin, sizeMax: int, baseDensity, falloffRate: float,
                                kind: ThingKind, item: ItemKey, allowedBiome: BiomeType) =
  for _ in 0 ..< count:
    let pos = randInteriorPos(r, 2)
    let size = randIntInclusive(r, sizeMin, sizeMax)
    placeResourceCluster(env, pos.x.int, pos.y.int, size, baseDensity, falloffRate,
      kind, item, ResourceGround, r, allowedBiomes = {allowedBiome})

proc carveTreeOasisWater(env: Environment, center: IVec2, rx, ry: int, rng: var Rand) =
  ## Carve water features for a tree oasis. Moved to module level to avoid
  ## closure capture of var Rand which violates memory safety under ARC.
  let centerX = center.x.int
  let centerY = center.y.int
  for ox in -(rx + 1) .. (rx + 1):
    for oy in -(ry + 1) .. (ry + 1):
      let px = centerX + ox
      let py = centerY + oy
      if px < MapBorder or px >= MapWidth - MapBorder or py < MapBorder or py >= MapHeight - MapBorder:
        continue
      let waterPos = ivec2(px.int32, py.int32)
      # Inline canPlaceOasisWater check to avoid closure capture
      if not (env.isSpawnable(waterPos) and env.terrain[waterPos.x][waterPos.y] notin {Road, Bridge}):
        continue
      let dx = ox.float / rx.float
      let dy = oy.float / ry.float
      let dist = dx * dx + dy * dy
      if dist <= 1.0 + (randFloat(rng) - 0.5) * 0.35:
        setTerrain(env, waterPos, Water)

  for _ in 0 ..< randIntInclusive(rng, 1, 2):
    var pos = center
    for _ in 0 ..< randIntInclusive(rng, 4, 10):
      let dir = sample(rng, [ivec2(1, 0), ivec2(-1, 0), ivec2(0, 1), ivec2(0, -1),
                           ivec2(1, 1), ivec2(-1, 1), ivec2(1, -1), ivec2(-1, -1)])
      pos += dir
      if pos.x < MapBorder.int32 or pos.x >= (MapWidth - MapBorder).int32 or
         pos.y < MapBorder.int32 or pos.y >= (MapHeight - MapBorder).int32:
        break
      # Inline canPlaceOasisWater check
      if not (env.isSpawnable(pos) and env.terrain[pos.x][pos.y] notin {Road, Bridge}):
        continue
      setTerrain(env, pos, Water)

proc resetVictoryState(env: Environment) =
  env.victoryWinner = -1
  env.victoryWinners = NoTeamMask
  for teamId in 0 ..< MapRoomObjectsTeams:
    env.victoryStates[teamId].wonderBuiltStep = -1
    env.victoryStates[teamId].relicHoldStartStep = -1
    env.victoryStates[teamId].kingAgentId = -1
    env.victoryStates[teamId].hillControlStartStep = -1

proc resetVisualEffects(env: Environment) =
  ## Clear all visual effect pools for reset. setLen(0) preserves capacity.
  if env.projectiles.len == 0:
    env.projectiles = newSeqOfCap[Projectile](ProjectilePoolCapacity)
  else:
    env.projectiles.setLen(0)
  env.projectilePool.stats = PoolStats()
  env.damageNumbers.setLen(0)
  env.debris.setLen(0)
  env.spawnEffects.setLen(0)
  env.ragdolls.setLen(0)
  env.dyingUnits.setLen(0)
  env.gatherSparkles.setLen(0)
  env.constructionDust.setLen(0)
  env.unitTrails.setLen(0)
  env.waterRipples.setLen(0)
  env.attackImpacts.setLen(0)
  env.conversionEffects.setLen(0)

proc initState(env: Environment) =
  ## Reset all environment state to prepare for a new game.
  inc env.mapGeneration
  env.thingsByKind = default(array[ThingKind, seq[Thing]])

  # Clear aura unit tracking collections
  env.tankUnits.setLen(0)
  env.monkUnits.setLen(0)

  # Clear villager tracking per team
  for teamId in 0 ..< MapRoomObjectsTeams:
    env.teamVillagers[teamId].setLen(0)

  # Reset victory conditions (must be -1, not default 0, or Team 0 wins immediately)
  env.resetVictoryState()

  # Initialize alliance state: each team is allied with itself only
  for teamId in 0 ..< MapRoomObjectsTeams:
    env.teamAlliances[teamId] = TeamMasks[teamId]

  # Initialize tile colors: base to neutral brown, computed to zero
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      env.baseTintColors[x][y] = BaseTileColorDefault
  env.computedTintColors.clear()

  # Clear background grid and elevation via zeroMem (nil refs = zero bytes)
  env.backgroundGrid.clear()
  env.elevation.clear()

  # Reset team stockpiles
  env.teamStockpiles.clear()

  # Initialize civ bonuses to defaults (preserve any pre-set bonuses)
  # Only reset if all multipliers are zero (uninitialized)
  for teamId in 0 ..< MapRoomObjectsTeams:
    let cb = env.teamCivBonuses[teamId]
    if cb.gatherRateMultiplier == 0.0'f32 and cb.buildSpeedMultiplier == 0.0'f32 and
       cb.unitHpMultiplier == 0.0'f32 and cb.unitAttackMultiplier == 0.0'f32 and
       cb.buildingHpMultiplier == 0.0'f32 and cb.woodCostMultiplier == 0.0'f32 and
       cb.foodCostMultiplier == 0.0'f32:
      env.teamCivBonuses[teamId] = defaultCivBonus()

  # Initialize AoE2-style market prices
  env.initMarketPrices()

  # Initialize active tiles tracking via zeroMem
  env.activeTiles.positions.setLen(0)
  env.activeTiles.flags.clear()
  env.tumorActiveTiles.positions.setLen(0)
  env.tumorActiveTiles.flags.clear()
  env.stepDirtyPositions.setLen(0)
  env.stepDirtyFlags.clear()
  env.tumorTintMods.clear()
  env.tintStrength.clear()
  env.tumorStrength.clear()
  env.tintLocked.clear()

  # Clear action tints via zeroMem
  env.actionTintCountdown.clear()
  env.actionTintColor.clear()
  env.actionTintFlags.clear()
  env.actionTintCode.clear()
  env.actionTintPositions.setLen(0)
  env.shieldCountdown.clear()

  # Reset visual effect pools while keeping pooled capacity hot.
  env.resetVisualEffects()

  # Pre-allocate action tint positions capacity
  if env.actionTintPositions.len == 0:
    env.actionTintPositions = newSeqOfCap[IVec2](ActionTintPoolCapacity)
  # (already cleared above)

  # Initialize arena allocator for per-step temporary allocations
  if env.arena.things1.len == 0:
    env.arena = initArena()
  else:
    env.arena.reset()

  # Initialize tint tracking to invalid positions (ensures tint added on first step)
  for i in 0 ..< MapAgents:
    env.lastAgentPos[i] = ivec2(-1, -1)
    env.lastObsAgentPos[i] = ivec2(-1, -1)
    env.agentObsDirty[i] = true  # All agents need initial observation build
    env.agentOrder[i] = i  # Initialize shuffle array (step() will shuffle in place)
  env.lastLanternPos.setLen(0)

proc initTerrainAndBiomes(env: Environment, rng: var Rand, seed: int): seq[TreeOasis] =
  ## Initialize terrain, biomes, water features, elevation, and cliffs.
  ## Returns tree oasis positions for later tree placement.

  # Initialize base terrain and biomes (dry pass).
  initTerrain(env.terrain, env.biomes, MapWidth, MapHeight, MapBorder, seed)
  # Water features override biome terrain before elevation/cliffs.
  applySwampWater(env.terrain, env.biomes, MapWidth, MapHeight, MapBorder, rng, BiomeSwampConfig())
  env.terrain.generateRiver(MapWidth, MapHeight, MapBorder, rng)
  var treeOases: seq[TreeOasis] = @[]
  if UseTreeOases:
    let numGroves = randIntInclusive(rng, TreeOasisClusterCountMin, TreeOasisClusterCountMax)
    for _ in 0 ..< numGroves:
      let pos = pickInteriorPos(rng, 3, 16, proc(pos: IVec2, attempt: int): bool =
        hasWaterNearby(env, pos, 5, includeShallow = true) or attempt > 10
      )
      let rx = randIntInclusive(rng, TreeOasisWaterRadiusMin, TreeOasisWaterRadiusMax)
      let ry = randIntInclusive(rng, TreeOasisWaterRadiusMin, TreeOasisWaterRadiusMax)
      carveTreeOasisWater(env, pos, rx, ry, rng)
      treeOases.add((center: pos, rx: rx, ry: ry))
  # Apply biome elevation (inlined)
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      if env.terrain[x][y] in {Water, Bridge, Mountain}:
        env.elevation[x][y] = 0
        continue
      let biome = env.biomes[x][y]
      env.elevation[x][y] =
        if biome == BiomeSwampType:
          -1
        elif biome == BiomeSnowType:
          1
        else:
          0
  # Apply cliff ramps with variable widths (inlined)
  # Places ramp terrain tiles at elevation transitions.
  # Lower tile gets RampUp* (going up), higher tile gets RampDown* (coming down).
  # Ramp width varies from RampWidthMin to RampWidthMax tiles for visual variety.
  proc canPlaceRampTile(env: Environment, tx, ty: int, expectedElev: int8): bool =
    ## Check if a ramp tile can be placed at the given position.
    if tx < MapBorder or tx >= MapWidth - MapBorder or
       ty < MapBorder or ty >= MapHeight - MapBorder:
      return false
    if env.terrain[tx][ty] in {Water, Road} or isRampTerrain(env.terrain[tx][ty]):
      return false
    if env.elevation[tx][ty] != expectedElev:
      return false
    true

  proc placeRampWithWidth(env: Environment, lowerX, lowerY, higherX, higherY: int,
                          rampUpType, rampDownType: TerrainType,
                          perpX, perpY: int, rng: var Rand) =
    ## Place a ramp at the given location with variable width.
    ## perpX, perpY define the perpendicular direction for width expansion.
    let lowerElev = env.elevation[lowerX][lowerY]
    let higherElev = env.elevation[higherX][higherY]

    # Place center ramp tiles
    env.terrain[lowerX][lowerY] = rampUpType
    env.terrain[higherX][higherY] = rampDownType

    # Determine width (1-3 tiles total, so 0-1 tiles on each side of center)
    let width = randIntInclusive(rng, RampWidthMin, RampWidthMax)
    let sideExtent = (width - 1) div 2  # How far to extend on each side

    # Place additional tiles perpendicular to the ramp direction
    for offset in 1 .. sideExtent:
      for side in [-1, 1]:
        let px = lowerX + perpX * offset * side
        let py = lowerY + perpY * offset * side
        let hx = higherX + perpX * offset * side
        let hy = higherY + perpY * offset * side

        # Place lower (ramp up) tile if valid
        if canPlaceRampTile(env, px, py, lowerElev):
          env.terrain[px][py] = rampUpType

        # Place higher (ramp down) tile if valid
        if canPlaceRampTile(env, hx, hy, higherElev):
          env.terrain[hx][hy] = rampDownType

  var cliffCount = 0
  for x in MapBorder ..< MapWidth - MapBorder:
    for y in MapBorder ..< MapHeight - MapBorder:
      if env.terrain[x][y] in {Water, Mountain, Road} or
         isRampTerrain(env.terrain[x][y]):
        continue
      let elev = env.elevation[x][y]
      for d in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0)]:
        let nx = x + d.x.int
        let ny = y + d.y.int
        if nx < MapBorder or nx >= MapWidth - MapBorder or
           ny < MapBorder or ny >= MapHeight - MapBorder:
          continue
        if env.elevation[nx][ny] <= elev:
          continue
        if env.terrain[nx][ny] in {Water, Mountain, Road} or
           isRampTerrain(env.terrain[nx][ny]):
          continue
        inc cliffCount
        if cliffCount mod RampPlacementSpacing != 0:
          continue
        # Assign ramp types based on direction to neighbor.
        # d indicates direction from (x,y) to higher neighbor (nx,ny).
        # perpX, perpY define the perpendicular axis for width expansion.
        if d.x == 0 and d.y == -1:
          # Neighbor is North: lower goes up north, higher comes down from south
          # Perpendicular is East-West (x-axis)
          placeRampWithWidth(env, x, y, nx, ny, RampUpN, RampDownS, 1, 0, rng)
        elif d.x == 1 and d.y == 0:
          # Neighbor is East: perpendicular is North-South (y-axis)
          placeRampWithWidth(env, x, y, nx, ny, RampUpE, RampDownW, 0, 1, rng)
        elif d.x == 0 and d.y == 1:
          # Neighbor is South: perpendicular is East-West (x-axis)
          placeRampWithWidth(env, x, y, nx, ny, RampUpS, RampDownN, 1, 0, rng)
        else:
          # Neighbor is West (d.x == -1, d.y == 0): perpendicular is North-South (y-axis)
          placeRampWithWidth(env, x, y, nx, ny, RampUpW, RampDownE, 0, 1, rng)
  # Apply cliffs (inlined)
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      if env.terrain[x][y] in {Water, Mountain}:
        continue
      let elev = env.elevation[x][y]
      proc isLower(dx, dy: int): bool =
        let nx = x + dx
        let ny = y + dy
        if nx < 0 or nx >= MapWidth or ny < 0 or ny >= MapHeight:
          return false
        env.elevation[nx][ny] < elev

      let lowN = isLower(0, -1)
      let lowE = isLower(1, 0)
      let lowS = isLower(0, 1)
      let lowW = isLower(-1, 0)
      let lowNE = isLower(1, -1)
      let lowSE = isLower(1, 1)
      let lowSW = isLower(-1, 1)
      let lowNW = isLower(-1, -1)

      let cardinalCount =
        (if lowN: 1 else: 0) +
        (if lowE: 1 else: 0) +
        (if lowS: 1 else: 0) +
        (if lowW: 1 else: 0)
      let diagonalCount =
        (if lowNE: 1 else: 0) +
        (if lowSE: 1 else: 0) +
        (if lowSW: 1 else: 0) +
        (if lowNW: 1 else: 0)

      var kind: ThingKind
      var hasCliff = false

      if cardinalCount == 2:
        if lowN and lowE:
          kind = CliffCornerInNE
          hasCliff = true
        elif lowE and lowS:
          kind = CliffCornerInSE
          hasCliff = true
        elif lowS and lowW:
          kind = CliffCornerInSW
          hasCliff = true
        elif lowW and lowN:
          kind = CliffCornerInNW
          hasCliff = true
      elif cardinalCount == 1:
        if lowN:
          kind = CliffEdgeN
          hasCliff = true
        elif lowE:
          kind = CliffEdgeE
          hasCliff = true
        elif lowS:
          kind = CliffEdgeS
          hasCliff = true
        elif lowW:
          kind = CliffEdgeW
          hasCliff = true
      elif cardinalCount == 0 and diagonalCount == 1:
        if lowNE:
          kind = CliffCornerOutNE
          hasCliff = true
        elif lowSE:
          kind = CliffCornerOutSE
          hasCliff = true
        elif lowSW:
          kind = CliffCornerOutSW
          hasCliff = true
        elif lowNW:
          kind = CliffCornerOutNW
          hasCliff = true

      if hasCliff:
        env.add(Thing(kind: kind, pos: ivec2(x.int32, y.int32)))

  # Place waterfalls where water tiles border higher-elevation non-water terrain.
  # Waterfalls appear on water tiles that are adjacent to cliffs/elevated terrain,
  # indicating water cascading down from the higher ground.
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      if env.terrain[x][y] notin WaterTerrain:
        continue
      let waterElev = env.elevation[x][y]  # Always 0 for water tiles
      # Check each cardinal direction for higher non-water neighbor
      if y > 0 and env.terrain[x][y - 1] notin WaterTerrain and
         env.elevation[x][y - 1] > waterElev:
        env.add(Thing(kind: WaterfallN, pos: ivec2(x.int32, y.int32)))
      if x < MapWidth - 1 and env.terrain[x + 1][y] notin WaterTerrain and
         env.elevation[x + 1][y] > waterElev:
        env.add(Thing(kind: WaterfallE, pos: ivec2(x.int32, y.int32)))
      if y < MapHeight - 1 and env.terrain[x][y + 1] notin WaterTerrain and
         env.elevation[x][y + 1] > waterElev:
        env.add(Thing(kind: WaterfallS, pos: ivec2(x.int32, y.int32)))
      if x > 0 and env.terrain[x - 1][y] notin WaterTerrain and
         env.elevation[x - 1][y] > waterElev:
        env.add(Thing(kind: WaterfallW, pos: ivec2(x.int32, y.int32)))

  # Resource nodes are spawned as Things later; base terrain stays walkable.

  # Blocking structures pass (city/dungeon/border walls).
  # Convert city blocks into walls (roads remain passable).
  for x in MapBorder ..< MapWidth - MapBorder:
    for y in MapBorder ..< MapHeight - MapBorder:
      if env.biomes[x][y] != BiomeCityType:
        continue
      if env.terrain[x][y] != BiomeCityBlockTerrain:
        continue
      let pos = ivec2(x.int32, y.int32)
      if not env.getBackgroundThing(pos).isNil:
        continue
      if env.hasDoor(pos):
        continue
      if not clearTreeElseSkip(env, pos):
        continue
      setTerrain(env, pos, Empty)
      env.add(Thing(kind: Wall, pos: pos, teamId: -1))

  # Add sparse dungeon walls using procedural dungeon masks.
  if UseDungeonZones:
    let dungeonKinds = [DungeonMaze, DungeonRadial]
    let count = dungeonKinds.len
    var dungeonWalls: MaskGrid
    dungeonWalls.clearMask(MapWidth, MapHeight)
    var seqIdx = 0
    for zone in evenlyDistributedZones(rng, MapWidth, MapHeight, MapBorder, count, DungeonZoneMaxFraction):
      let x0 = max(MapBorder, zone.x)
      let y0 = max(MapBorder, zone.y)
      let x1 = min(MapWidth - MapBorder, zone.x + zone.w)
      let y1 = min(MapHeight - MapBorder, zone.y + zone.h)

      var zoneMask: MaskGrid
      buildZoneBlobMask(zoneMask, MapWidth, MapHeight, MapBorder, zone, rng)

      for x in x0 ..< x1:
        for y in y0 ..< y1:
          if not zoneMask[x][y]:
            continue
          env.biomes[x][y] = BiomeDungeonType
      var mask: MaskGrid
      let dungeonKind = block:
        let selected = dungeonKinds[seqIdx mod dungeonKinds.len]
        inc seqIdx
        selected
      case dungeonKind:
      of DungeonMaze:
        buildDungeonMazeMask(mask, MapWidth, MapHeight, zone.x, zone.y, zone.w, zone.h, rng, DungeonMazeConfig())
      of DungeonRadial:
        buildDungeonRadialMask(mask, MapWidth, MapHeight, zone.x, zone.y, zone.w, zone.h, rng, DungeonRadialConfig())

      for x in x0 ..< x1:
        for y in y0 ..< y1:
          if not zoneMask[x][y]:
            continue
          if (if dungeonKind == DungeonRadial:
                not mask[x][y]  # radial mask encodes corridors; invert for walls
              else:
                mask[x][y]) and not isBlockedTerrain(env.terrain[x][y]):
            dungeonWalls[x][y] = true

    # Soften dungeon edges so they blend into surrounding biomes.
    ditherEdges(dungeonWalls, MapWidth, MapHeight, 0.08, 3, rng)

    for x in MapBorder ..< MapWidth - MapBorder:
      for y in MapBorder ..< MapHeight - MapBorder:
        if not dungeonWalls[x][y]:
          continue
        if env.terrain[x][y] == Water:
          continue
        let pos = ivec2(x.int32, y.int32)
        if not env.getBackgroundThing(pos).isNil:
          continue
        if env.hasDoor(pos):
          continue
        if not clearTreeElseSkip(env, pos):
          continue
        env.add(Thing(kind: Wall, pos: pos, teamId: -1))

  # Apply biome colors after dungeon biomes are finalized.
  env.applyBiomeBaseColors()

  if MapBorder > 0:
    proc addBorderWall(pos: IVec2) =
      if not env.getBackgroundThing(pos).isNil:
        return
      env.add(Thing(kind: Wall, pos: pos, teamId: -1))
    for x in 0 ..< MapWidth:
      for j in 0 ..< MapBorder:
        addBorderWall(ivec2(x, j))
        addBorderWall(ivec2(x, MapHeight - j - 1))
    for y in 0 ..< MapHeight:
      for j in 0 ..< MapBorder:
        addBorderWall(ivec2(j, y))
        addBorderWall(ivec2(MapWidth - j - 1, y))

  result = treeOases

proc initTradingHub(env: Environment, rng: var Rand) =
  ## Place neutral trading hub near map center before villages.
  block tradingHub:
    let centerX = MapWidth div 2
    let centerY = MapHeight div 2
    let half = TradingHubSize div 2
    let x0 = centerX - half
    let x1 = centerX + half
    let y0 = centerY - half
    let y1 = centerY + half

    for x in x0 .. x1:
      for y in y0 .. y1:
        if x < 0 or x >= MapWidth or y < 0 or y >= MapHeight:
          continue
        let pos = ivec2(x.int32, y.int32)
        let existing = env.getThing(pos)
        if not existing.isNil:
          removeThing(env, existing)
        let background = env.getBackgroundThing(pos)
        if not background.isNil:
          removeThing(env, background)
        setTerrain(env, pos, Empty)
        env.baseTintColors[x][y] = TradingHubTint
        env.tintLocked[x][y] = true

    proc paintRoadTile(x, y: int) =
      let pos = ivec2(x.int32, y.int32)
      if env.terrain[x][y] in WaterTerrain:
        setTerrain(env, pos, Bridge)
      else:
        setTerrain(env, pos, Road)

    proc extendRoad(startX, startY, dx, dy: int) =
      var x = startX
      var y = startY
      while x >= MapBorder + 1 and x < MapWidth - MapBorder - 1 and
          y >= MapBorder + 1 and y < MapHeight - MapBorder - 1:
        let existing = env.terrain[x][y]
        paintRoadTile(x, y)
        if (x < x0 or x > x1 or y < y0 or y > y1) and existing in {Road, Bridge}:
          break
        x += dx
        y += dy

    let roadX = centerX
    for x in x0 .. x1:
      paintRoadTile(x, centerY)
    extendRoad(roadX, centerY, 0, 1)
    extendRoad(roadX, centerY, 0, -1)
    proc canPlaceHubThing(x, y: int): bool =
      if x < MapBorder + 1 or x >= MapWidth - MapBorder - 1 or
          y < MapBorder + 1 or y >= MapHeight - MapBorder - 1:
        return false
      if env.terrain[x][y] in {Water, Road, Bridge}:
        return false
      if x == roadX or y == centerY:
        return false
      let pos = ivec2(x.int32, y.int32)
      if not env.isEmpty(pos):
        return false
      if not env.getBackgroundThing(pos).isNil or env.hasDoor(pos):
        return false
      true

    var wallPositions: seq[IVec2] = @[]
    proc tryAddWall(x, y: int) =
      if not canPlaceHubThing(x, y):
        return
      let pos = ivec2(x.int32, y.int32)
      env.add(Thing(kind: Wall, pos: pos, teamId: -1))
      wallPositions.add(pos)

    let wallMinX = max(MapBorder + 1, x0 - 2)
    let wallMaxX = min(MapWidth - MapBorder - 2, x1 + 2)
    let wallMinY = max(MapBorder + 1, y0 - 2)
    let wallMaxY = min(MapHeight - MapBorder - 2, y1 + 2)
    let wallChance = TradingHubWallChance
    let driftChance = TradingHubDriftChance
    let topMin = wallMinY
    let topMax = min(wallMaxY, y0 + 2)
    let bottomMin = max(wallMinY, y1 - 2)
    let bottomMax = wallMaxY
    var topY = y0 - 1
    var bottomY = y1 + 1

    for x in wallMinX .. wallMaxX:
      if randChance(rng, wallChance):
        tryAddWall(x, topY)
      if randChance(rng, wallChance):
        tryAddWall(x, bottomY)
      if randChance(rng, driftChance):
        topY = max(topMin, min(topMax, topY + randIntInclusive(rng, -1, 1)))
      if randChance(rng, driftChance):
        bottomY = max(bottomMin, min(bottomMax, bottomY + randIntInclusive(rng, -1, 1)))

    let leftMin = wallMinX
    let leftMax = min(wallMaxX, x0 + 2)
    let rightMin = max(wallMinX, x1 - 2)
    let rightMax = wallMaxX
    var leftX = x0 - 1
    var rightX = x1 + 1
    for y in wallMinY .. wallMaxY:
      if randChance(rng, wallChance):
        tryAddWall(leftX, y)
      if randChance(rng, wallChance):
        tryAddWall(rightX, y)
      if randChance(rng, driftChance):
        leftX = max(leftMin, min(leftMax, leftX + randIntInclusive(rng, -1, 1)))
      if randChance(rng, driftChance):
        rightX = max(rightMin, min(rightMax, rightX + randIntInclusive(rng, -1, 1)))

    let spurCount = randIntInclusive(rng, TradingHubSpurCountMin, TradingHubSpurCountMax)
    let spurDirs = [ivec2(1, 0), ivec2(-1, 0), ivec2(0, 1), ivec2(0, -1)]
    for _ in 0 ..< spurCount:
      let startX = randIntInclusive(rng, x0 + 1, x1 - 1)
      let startY = randIntInclusive(rng, y0 + 1, y1 - 1)
      if startX == roadX or startY == centerY:
        continue
      let dir = spurDirs[randIntInclusive(rng, 0, spurDirs.len - 1)]
      let length = randIntInclusive(rng, TradingHubSpurLengthMin, TradingHubSpurLengthMax)
      var pos = ivec2(startX.int32, startY.int32)
      for _ in 0 ..< length:
        tryAddWall(pos.x.int, pos.y.int)
        pos = pos + dir

    var towerSlots = min(TradingHubTowerSlots, wallPositions.len)
    while towerSlots > 0 and wallPositions.len > 0:
      let wallIdx = randIntInclusive(rng, 0, wallPositions.len - 1)
      let pos = wallPositions[wallIdx]
      let wallThing = env.getThing(pos)
      if wallThing.isKind(Wall):
        removeThing(env, wallThing)
        env.add(Thing(kind: GuardTower, pos: pos, teamId: -1))
        dec towerSlots
      wallPositions[wallIdx] = wallPositions[^1]
      wallPositions.setLen(wallPositions.len - 1)

    let center = ivec2(centerX.int32, centerY.int32)
    env.add(Thing(kind: Castle, pos: center, teamId: -1))
    let hubCoreMultiplier = TradingHubCoreMultiplier
    let hubScatterMultiplier = TradingHubScatterMultiplier
    let baseHubBuildings = @[
      Market, Market, Market, Outpost, Blacksmith, ClayOven, WeavingLoom,
      Barracks, ArcheryRange, Stable, SiegeWorkshop, MangonelWorkshop,
      Monastery, University, House, House, Granary, Mill,
      LumberCamp, Quarry, MiningCamp, Barrel
    ]
    var hubBuildings: seq[ThingKind] = @[]
    for _ in 0 ..< hubCoreMultiplier:
      hubBuildings.add(baseHubBuildings)
    for i in countdown(hubBuildings.len - 1, 1):
      let j = randIntInclusive(rng, 0, i)
      swap(hubBuildings[i], hubBuildings[j])
    var placed = 0
    let mainTarget = min(hubBuildings.len, randIntInclusive(rng, TradingHubMainBuildingMin, TradingHubMainBuildingMax) * hubCoreMultiplier)
    for kind in hubBuildings:
      if placed >= mainTarget:
        break
      var attempts = 0
      var placedHere = false
      while attempts < TradingHubBuildingAttempts and not placedHere:
        inc attempts
        let x = randIntInclusive(rng, x0 + 1, x1 - 1)
        let y = randIntInclusive(rng, y0 + 1, y1 - 1)
        if x == centerX or y == centerY:
          continue
        let pos = ivec2(x.int32, y.int32)
        if not canPlaceHubThing(x, y):
          continue
        if abs(x - centerX) <= 1 and abs(y - centerY) <= 1:
          continue
        env.add(Thing(
          kind: kind,
          pos: pos,
          teamId: -1,
          barrelCapacity: buildingBarrelCapacity(kind)
        ))
        inc placed
        placedHere = true

    let minorPool = [House, House, House, Barrel, Barrel, Outpost, Market, Granary, Mill]
    let extraTarget = randIntInclusive(rng, TradingHubExtraBuildingMin, TradingHubExtraBuildingMax) * hubCoreMultiplier
    var extraPlaced = 0
    var extraAttempts = 0
    while extraPlaced < extraTarget and extraAttempts < extraTarget * 60:
      inc extraAttempts
      let x = randIntInclusive(rng, x0 + 1, x1 - 1)
      let y = randIntInclusive(rng, y0 + 1, y1 - 1)
      if not canPlaceHubThing(x, y):
        continue
      if abs(x - centerX) <= 1 and abs(y - centerY) <= 1:
        continue
      let kind = minorPool[randIntInclusive(rng, 0, minorPool.len - 1)]
      env.add(Thing(
        kind: kind,
        pos: ivec2(x.int32, y.int32),
        teamId: -1,
        barrelCapacity: buildingBarrelCapacity(kind)
      ))
      inc extraPlaced
    let scatterPool = [
      House, House, House, House, Barrel, Barrel, Outpost, Market, Granary, Mill,
      LumberCamp, Quarry, MiningCamp, WeavingLoom, ClayOven, Blacksmith, University
    ]
    let scatterTarget = randIntInclusive(rng, TradingHubScatterBuildingMin, TradingHubScatterBuildingMax) * hubScatterMultiplier
    let scatterRadius = half + TradingHubScatterPadding
    let scatterInner = half + TradingHubScatterInnerPad
    var scatterPlaced = 0
    var scatterAttempts = 0
    while scatterPlaced < scatterTarget and scatterAttempts < scatterTarget * 80:
      inc scatterAttempts
      let x = randIntInclusive(rng, centerX - scatterRadius, centerX + scatterRadius)
      let y = randIntInclusive(rng, centerY - scatterRadius, centerY + scatterRadius)
      if x >= x0 and x <= x1 and y >= y0 and y <= y1:
        continue
      let dist = max(abs(x - centerX), abs(y - centerY))
      if dist < scatterInner or dist > scatterRadius:
        continue
      if not canPlaceHubThing(x, y):
        continue
      let kind = scatterPool[randIntInclusive(rng, 0, scatterPool.len - 1)]
      env.add(Thing(
        kind: kind,
        pos: ivec2(x.int32, y.int32),
        teamId: -1,
        barrelCapacity: buildingBarrelCapacity(kind)
      ))
      inc scatterPlaced

proc placeStartingTownCenter(env: Environment, center: IVec2, teamId: int,
                              rng: var Rand): IVec2 =
  ## Place a town center near the altar for a team's starting village.
  var candidates: seq[IVec2] = @[]
  for dx in -3 .. 3:
    for dy in -3 .. 3:
      let dist = max(abs(dx), abs(dy))
      if dist == 0 or dist > 3:
        continue
      let pos = center + ivec2(dx.int32, dy.int32)
      # Skip corners where resource buildings go
      if pos == center + ivec2(2, -2) or pos == center + ivec2(2, 2) or
          pos == center + ivec2(-2, 2) or pos == center + ivec2(-2, -2):
        continue
      candidates.add(pos)
  # Shuffle candidates for variety
  for i in countdown(candidates.len - 1, 1):
    let j = randIntInclusive(rng, 0, i)
    swap(candidates[i], candidates[j])
  for pos in candidates:
    if not isValidPos(pos) or env.terrain[pos.x][pos.y] == Water:
      continue
    if not clearTreeElseSkip(env, pos):
      continue
    if env.hasDoor(pos) or not env.isEmpty(pos):
      continue
    env.add(Thing(kind: TownCenter, pos: pos, teamId: teamId))
    return pos
  # Fallback: place directly east if possible
  let fallback = center + ivec2(1, 0)
  if isValidPos(fallback) and env.isEmpty(fallback) and
      env.terrain[fallback.x][fallback.y] != Water and not env.hasDoor(fallback):
    env.add(Thing(kind: TownCenter, pos: fallback, teamId: teamId))
    return fallback
  center

proc placeStartingRoads(env: Environment, center: IVec2, teamId: int,
                         rng: var Rand) =
  ## Connect team buildings with roads extending from village center.
  proc placeRoad(pos: IVec2) =
    if not isValidPos(pos) or env.terrain[pos.x][pos.y] == Water or env.hasDoor(pos):
      return
    if not clearTreeElseSkip(env, pos):
      return
    if env.terrain[pos.x][pos.y] != Road:
      setTerrain(env, pos, Road)

  var anchors: seq[IVec2] = @[center]
  for thing in env.things:
    if thing.teamId != teamId:
      continue
    if thing.kind notin {TownCenter, House, Granary, LumberCamp, Quarry, MiningCamp, Mill}:
      continue
    let dist = max(abs(thing.pos.x - center.x), abs(thing.pos.y - center.y))
    if dist <= 7:
      anchors.add(thing.pos)

  # Connect anchors to center with L-shaped roads
  for anchor in anchors:
    if anchor == center:
      continue
    var pos = center
    while pos.x != anchor.x:
      let delta = anchor.x - pos.x
      pos.x += (if delta < 0: -1 elif delta > 0: 1 else: 0)
      placeRoad(pos)
    while pos.y != anchor.y:
      let delta = anchor.y - pos.y
      pos.y += (if delta < 0: -1 elif delta > 0: 1 else: 0)
      placeRoad(pos)

  # Track road extents
  var maxEast, maxWest, maxSouth, maxNorth = 0
  for anchor in anchors:
    let dx = (anchor.x - center.x).int
    let dy = (anchor.y - center.y).int
    if dx > maxEast: maxEast = dx
    if dx < 0 and -dx > maxWest: maxWest = -dx
    if dy > maxSouth: maxSouth = dy
    if dy < 0 and -dy > maxNorth: maxNorth = -dy

  # Extend roads beyond buildings
  for (dir, baseDist) in [(ivec2(1, 0), maxEast), (ivec2(-1, 0), maxWest),
                          (ivec2(0, 1), maxSouth), (ivec2(0, -1), maxNorth)]:
    let extra = randIntInclusive(rng, 3, 4)
    for step in 1 .. baseDist + extra:
      let pos = center + ivec2(dir.x.int32 * step.int32, dir.y.int32 * step.int32)
      placeRoad(pos)

proc placeStartingResourceBuildings(env: Environment, center: IVec2, teamId: int) =
  ## Place starting resource buildings at corners around the altar.
  for entry in [
    (offset: ivec2(2, -2), kind: LumberCamp, res: ResourceWood),
    (offset: ivec2(2, 2), kind: Granary, res: ResourceFood),
    (offset: ivec2(-2, 2), kind: Quarry, res: ResourceStone),
    (offset: ivec2(-2, -2), kind: MiningCamp, res: ResourceGold)
  ]:
    var placed = false
    for radius in 0 .. 2:
      for dx in -radius .. radius:
        for dy in -radius .. radius:
          if radius > 0 and max(abs(dx), abs(dy)) != radius:
            continue
          let pos = center + entry.offset + ivec2(dx.int32, dy.int32)
          if not isValidPos(pos) or isBlockedForPlacement(env, pos) or env.hasDoor(pos):
            continue
          if not clearTreeElseSkip(env, pos):
            continue
          if not env.isEmpty(pos):
            continue
          let building = Thing(kind: entry.kind, pos: pos, teamId: teamId)
          let capacity = buildingBarrelCapacity(entry.kind)
          if capacity > 0:
            building.barrelCapacity = capacity
          env.add(building)
          env.teamStockpiles[teamId].counts[entry.res] =
            max(env.teamStockpiles[teamId].counts[entry.res], 5)
          placed = true
          break
        if placed: break
      if placed: break

proc findResourceSpot(env: Environment, center: IVec2, rng: var Rand,
                      minRadius, maxRadius: int,
                      allowedTerrain: set[TerrainType]): IVec2 =
  ## Find a valid spot for resource placement within radius of center.
  for attempt in 0 ..< 40:
    let dx = randIntInclusive(rng, -maxRadius, maxRadius)
    let dy = randIntInclusive(rng, -maxRadius, maxRadius)
    let dist = max(abs(dx), abs(dy))
    if dist < minRadius or dist > maxRadius:
      continue
    let pos = center + ivec2(dx.int32, dy.int32)
    if not isValidPos(pos) or env.terrain[pos.x][pos.y] notin allowedTerrain or
        not env.isSpawnable(pos):
      continue
    return pos
  # Extended search with larger radius
  for attempt in 0 ..< 40:
    let radius = maxRadius + 4
    let dx = randIntInclusive(rng, -radius, radius)
    let dy = randIntInclusive(rng, -radius, radius)
    let dist = max(abs(dx), abs(dy))
    if dist < minRadius or dist > radius:
      continue
    let pos = center + ivec2(dx.int32, dy.int32)
    if not isValidPos(pos) or env.terrain[pos.x][pos.y] notin allowedTerrain or
        not env.isSpawnable(pos):
      continue
    return pos
  ivec2(-1, -1)

proc placeStartingResourceNodes(env: Environment, center: IVec2, rng: var Rand) =
  ## Place starting resource clusters (wood, food, stone, gold, magma) near village.
  # Wood cluster
  var woodSpot = findResourceSpot(env, center, rng, 6, 12, ResourceGround)
  if woodSpot.x < 0:
    woodSpot = rng.randomEmptyPos(env)
  placeResourceCluster(env, woodSpot.x, woodSpot.y,
    randIntInclusive(rng, 5, 8), 0.85, 0.4, Tree, ItemWood, ResourceGround, rng)

  # Food cluster
  var foodSpot = findResourceSpot(env, center, rng, 5, 11, ResourceGround)
  if foodSpot.x < 0:
    foodSpot = rng.randomEmptyPos(env)
  placeResourceCluster(env, foodSpot.x, foodSpot.y,
    randIntInclusive(rng, 4, 7), 0.85, 0.35, Wheat, ItemWheat, ResourceGround, rng)

  # Stone cluster
  block:
    let count = randIntInclusive(rng, 3, 4)
    var spot = findResourceSpot(env, center, rng, 7, 14, ResourceGround)
    if spot.x < 0:
      spot = rng.randomEmptyPos(env)
    addResourceNode(env, spot, Stone, ItemStone, MineDepositAmount)
    if count > 1:
      var candidates = env.findEmptyPositionsAround(spot, 2)
      let toPlace = min(count - 1, candidates.len)
      for i in 0 ..< toPlace:
        addResourceNode(env, candidates[i], Stone, ItemStone, MineDepositAmount)

  # Gold cluster
  block:
    let count = randIntInclusive(rng, 5, 7)
    var spot = findResourceSpot(env, center, rng, 8, 15, ResourceGround)
    if spot.x < 0:
      spot = rng.randomEmptyPos(env)
    addResourceNode(env, spot, Gold, ItemGold, MineDepositAmount)
    if count > 1:
      var candidates = env.findEmptyPositionsAround(spot, 2)
      let toPlace = min(count - 1, candidates.len)
      for i in 0 ..< toPlace:
        addResourceNode(env, candidates[i], Gold, ItemGold, MineDepositAmount)

  # Magma cluster
  block:
    var spot = findResourceSpot(env, center, rng, 9, 16, ResourceGround)
    if spot.x < 0:
      spot = rng.randomEmptyPos(env)
    if env.isSpawnable(spot) and env.terrain[spot.x][spot.y] in ResourceGround:
      env.add(Thing(kind: Magma, pos: spot))
    var candidates = env.findEmptyPositionsAround(spot, 2)
    let extraCount = randIntInclusive(rng, 1, 2)
    let toPlace = min(extraCount, candidates.len)
    for i in 0 ..< toPlace:
      let pos = candidates[i]
      if env.isSpawnable(pos) and env.terrain[pos.x][pos.y] in ResourceGround:
        env.add(Thing(kind: Magma, pos: pos))

proc placeStartingHouses(env: Environment, center: IVec2, teamId: int,
                          rng: var Rand) =
  ## Place starting houses around the village center.
  let count = randIntInclusive(rng, 4, 5)
  var placed = 0
  var attempts = 0
  while placed < count and attempts < 120:
    inc attempts
    let dx = randIntInclusive(rng, -5, 5)
    let dy = randIntInclusive(rng, -5, 5)
    let dist = max(abs(dx), abs(dy))
    if dist < 3 or dist > 5:
      continue
    let pos = center + ivec2(dx.int32, dy.int32)
    if not isValidPos(pos) or env.hasDoor(pos) or not env.isEmpty(pos) or
        isBlockedForPlacement(env, pos):
      continue
    env.add(Thing(kind: House, pos: pos, teamId: teamId))
    inc placed

proc placeTemple(env: Environment, rng: var Rand, villageCenters: seq[IVec2]) =
  let center = ivec2((MapWidth div 2).int32, (MapHeight div 2).int32)
  var placed = false
  for _ in 0 ..< TemplePlacementAttempts:
    let dx = randIntInclusive(rng, -TemplePlacementRange, TemplePlacementRange)
    let dy = randIntInclusive(rng, -TemplePlacementRange, TemplePlacementRange)
    let pos = center + ivec2(dx.int32, dy.int32)
    if not isValidPos(pos):
      continue
    if env.terrain[pos.x][pos.y] == Water:
      continue
    if not env.isSpawnable(pos):
      continue
    var tooClose = false
    for v in villageCenters:
      let dist = max(abs(v.x - pos.x), abs(v.y - pos.y))
      if dist < TempleMinDistance:
        tooClose = true
        break
    if tooClose:
      continue
    env.add(Thing(kind: Temple, pos: pos, teamId: -1))
    placed = true
    break
  if not placed:
    let fallback = rng.randomEmptyPos(env)
    env.add(Thing(kind: Temple, pos: fallback, teamId: -1))

proc initTeams(env: Environment, rng: var Rand): seq[IVec2] =
  ## Spawn teams with altars, town centers, and associated agents.
  ## Returns village center positions.
  # Clear and prepare team colors arrays (use Environment fields)
  env.agentColors.setLen(MapRoomObjectsAgents)  # Allocate space for all agents
  env.teamColors.setLen(0)  # Clear team colors
  env.altarColors.clear()  # Clear altar colors from previous game
  let numTeams = MapRoomObjectsTeams
  var totalAgentsSpawned = 0
  let totalTeamAgentCap = MapRoomObjectsTeams * MapAgentsPerTeam
  var villageCenters: seq[IVec2] = @[]

  # First phase: Find all village positions without assigning teams yet.
  # This prevents earlier teams from having positional advantages.
  var foundPositions: seq[IVec2] = @[]
  var tempVillageCenters: seq[IVec2] = @[]  # Used for spacing constraint
  for _ in 0 ..< numTeams:
    let villageStruct = block:
      let size = VillageStructureSize
      let radius = VillageStructureRadius
      let center = ivec2(radius.int32, radius.int32)
      var layout: seq[seq[char]] = newSeq[seq[char]](size)
      for y in 0 ..< size:
        layout[y] = newSeq[char](size)
        for x in 0 ..< size:
          layout[y][x] = ' '
      for y in 0 ..< size:
        for x in 0 ..< size:
          if abs(x - center.x) + abs(y - center.y) <= VillageFloorDistance:
            layout[y][x] = StructureFloorChar
      Structure(width: size, height: size, centerPos: center, layout: layout)
    var placementPosition: IVec2
    let placed = tryPickEmptyPos(rng, env, TemplePlacementAttempts, proc(candidatePos: IVec2, attempt: int): bool =
      for dy in 0 ..< villageStruct.height:
        for dx in 0 ..< villageStruct.width:
          let checkX = candidatePos.x + dx
          let checkY = candidatePos.y + dy
          if checkX >= MapWidth or checkY >= MapHeight or
             not env.isEmpty(ivec2(checkX, checkY)) or
             isBlockedTerrain(env.terrain[checkX][checkY]):
            return false
      const MinVillageSpacing = DefaultMinVillageSpacing
      let candidateCenter = candidatePos + villageStruct.centerPos
      for c in tempVillageCenters:
        let dx = abs(c.x - candidateCenter.x)
        let dy = abs(c.y - candidateCenter.y)
        if max(dx, dy) < MinVillageSpacing:
          return false
      true
    , placementPosition)
    if placed:
      let candidateCenter = placementPosition + villageStruct.centerPos
      foundPositions.add(placementPosition)
      tempVillageCenters.add(candidateCenter)

  # Shuffle positions so teams are randomly assigned to map locations.
  # This prevents systematic positional advantages for any team number.
  rng.shuffle(foundPositions)

  doAssert WarmTeamPalette.len >= numTeams,
    "WarmTeamPalette must cover all base colors without reuse."

  # Shuffle color indices so team-color pairings are randomized per game.
  # This prevents systematic color-based scoring advantages (e.g., olive-lime
  # being closest to the average mixed tint in contested territory).
  var colorIndices: seq[int] = @[]
  for idx in 0 ..< numTeams:
    colorIndices.add(idx)
  rng.shuffle(colorIndices)

  # Second phase: Assign teams to shuffled positions.
  for i in 0 ..< min(numTeams, foundPositions.len):
    let placementPosition = foundPositions[i]
    let villageStruct = block:
      ## Small town starter: altar + town center, no walls.
      let size = VillageStructureSize
      let radius = VillageStructureRadius
      let center = ivec2(radius.int32, radius.int32)
      var layout: seq[seq[char]] = newSeq[seq[char]](size)
      for y in 0 ..< size:
        layout[y] = newSeq[char](size)
        for x in 0 ..< size:
          layout[y][x] = ' '

      # Clear a small plaza around the altar so the start isn't cluttered.
      for y in 0 ..< size:
        for x in 0 ..< size:
          if abs(x - center.x) + abs(y - center.y) <= VillageFloorDistance:
            layout[y][x] = StructureFloorChar

      Structure(
        width: size,
        height: size,
        centerPos: center,
        layout: layout
      )
    block placed:
      let elements = getStructureElements(villageStruct, placementPosition)

      # Clear terrain within the village area to create a clearing
      for dy in 0 ..< villageStruct.height:
        for dx in 0 ..< villageStruct.width:
          let clearX = placementPosition.x + dx
          let clearY = placementPosition.y + dy
          if clearX >= 0 and clearX < MapWidth and clearY >= 0 and clearY < MapHeight:
            if dy < villageStruct.layout.len and dx < villageStruct.layout[dy].len:
              if villageStruct.layout[dy][dx] == ' ':
                continue
            # Clear any terrain features (wheat, trees) but keep blocked terrain
            if not isBlockedTerrain(env.terrain[clearX][clearY]):
              setTerrain(env, ivec2(clearX.int32, clearY.int32), Empty)

      # Generate a distinct warm color for this team (avoid cool/blue hues)
      # Use shuffled color index to prevent systematic color-based advantages
      let teamColor = WarmTeamPalette[colorIndices[i]]
      env.teamColors.add(teamColor)
      let teamId = env.teamColors.len - 1

      # Spawn agent slots for this team (six active, the rest dormant)
      let agentsForThisTeam = min(MapAgentsPerTeam, totalTeamAgentCap - totalAgentsSpawned)

      # Add the altar with initial hearts and team bounds
      let altar = Thing(
        kind: Altar,
        pos: elements.center,
        teamId: teamId
      )
      altar.inventory = emptyInventory()
      altar.hearts = MapObjectAltarInitialHearts
      env.add(altar)
      villageCenters.add(elements.center)
      env.altarColors[elements.center] = teamColor  # Associate altar position with team color

      discard placeStartingTownCenter(env, elements.center, teamId, rng)

      # Initialize base colors for village tiles to team color
      for dx in 0 ..< villageStruct.width:
        for dy in 0 ..< villageStruct.height:
          let tileX = placementPosition.x + dx
          let tileY = placementPosition.y + dy
          if tileX >= 0 and tileX < MapWidth and tileY >= 0 and tileY < MapHeight:
            if dy < villageStruct.layout.len and dx < villageStruct.layout[dy].len:
              if villageStruct.layout[dy][dx] == ' ':
                continue
            env.baseTintColors[tileX][tileY] = TileColor(
              r: teamColor.r,
              g: teamColor.g,
              b: teamColor.b,
              intensity: 1.0
            )

      # Add nearby village resources first, then connect roads between them.
      placeStartingResourceBuildings(env, elements.center, teamId)
      placeStartingHouses(env, elements.center, teamId, rng)
      placeStartingRoads(env, elements.center, teamId, rng)
      placeStartingResourceNodes(env, elements.center, rng)

      # Add the walls
      for wallPos in elements.walls:
        if not env.getBackgroundThing(wallPos).isNil:
          continue
        env.add(Thing(
          kind: Wall,
          pos: wallPos,
          teamId: teamId,
        ))

      # Add the doors (team-colored, passable only to that team)
      for doorPos in elements.doors:
        if doorPos.x >= 0 and doorPos.x < MapWidth and doorPos.y >= 0 and doorPos.y < MapHeight:
          if env.isEmpty(doorPos) and not env.hasDoor(doorPos):
            env.add(Thing(kind: Door, pos: doorPos, teamId: teamId))

      if agentsForThisTeam > 0:
        # Get nearby positions around the altar
        let nearbyPositions = env.findEmptyPositionsAround(elements.center, 3)

        for j in 0 ..< agentsForThisTeam:
          let agentId = teamId * MapAgentsPerTeam + j

          # Store the team color for this agent (shared by all agents of the team)
          env.agentColors[agentId] = env.teamColors[teamId]

          var agentPos = ivec2(-1, -1)
          var frozen = 0
          var hp = 0
          if j < min(6, agentsForThisTeam):
            if j < nearbyPositions.len:
              agentPos = nearbyPositions[j]
            else:
              agentPos = rng.randomEmptyPos(env)
            hp = AgentMaxHp
            env.terminated[agentId] = 0.0
          else:
            env.terminated[agentId] = 1.0

          # Create the agent slot (only the first is placed immediately)
          env.add(Thing(
            kind: Agent,
            agentId: agentId,
            pos: agentPos,
            orientation: Orientation(randIntInclusive(rng, 0, 3)),
            homeAltar: elements.center,  # Link agent to their home altar
            frozen: frozen,
            hp: hp,
            maxHp: AgentMaxHp,
            attackDamage: VillagerAttackDamage,
            unitClass: UnitVillager,
            embarkedUnitClass: UnitVillager,
            stance: StanceNoAttack,  # Villagers default to NoAttack
            teamIdOverride: -1
          ))

          # In Regicide mode, make the first agent the King
          if j == 0 and env.config.victoryCondition in {VictoryRegicide, VictoryAll}:
            let king = env.agents[agentId]
            applyUnitClass(env, king, UnitKing)
            env.victoryStates[teamId].kingAgentId = agentId

          totalAgentsSpawned += 1
          if totalAgentsSpawned >= totalTeamAgentCap:
            break

      # Note: Door gaps are placed instead of walls for defendable entrances

  placeTemple(env, rng, villageCenters)

  # Now place additional random walls after villages to avoid blocking corner placement
  for i in 0 ..< MapRoomObjectsWalls:
    let pos = rng.randomEmptyPos(env)
    if not env.getBackgroundThing(pos).isNil:
      continue
    env.add(Thing(kind: Wall, pos: pos, teamId: -1))

  # If there are still agents to spawn (e.g., if not enough teams), spawn them randomly
  # They will get a neutral color
  while totalAgentsSpawned < totalTeamAgentCap:
    let agentPos = rng.randomEmptyPos(env)
    let agentId = totalAgentsSpawned

    # Store neutral color for agents without a team
    env.agentColors[agentId] = NeutralGray  # Gray for unaffiliated agents

    env.add(Thing(
      kind: Agent,
      agentId: agentId,
      pos: agentPos,
      orientation: Orientation(randIntInclusive(rng, 0, 3)),
      homeAltar: ivec2(-1, -1),  # No home altar for unaffiliated agents
      frozen: 0,
      hp: AgentMaxHp,
      maxHp: AgentMaxHp,
      attackDamage: VillagerAttackDamage,
      unitClass: UnitVillager,
      embarkedUnitClass: UnitVillager,
      stance: StanceNoAttack,  # Villagers default to NoAttack
      teamIdOverride: -1,
    ))

    totalAgentsSpawned += 1

  result = villageCenters

# ---------------------------------------------------------------------------
# Village pond generation: local water access for dock building
# ---------------------------------------------------------------------------

const
  PondMinTiles = 3
  PondMaxTiles = 5
  PondSearchRadius = 10       # Max distance from village center to pond center
  PondMinDistFromCenter = 4   # Min distance so pond doesn't overlap village
  StreamMaxPathLen = 200      # BFS cutoff for stream pathfinding
  StreamTerrainType = ShallowWater

proc findNearestRiverTile(env: Environment, pos: IVec2, maxRadius: int): IVec2 =
  ## Find the nearest Water tile (river) within maxRadius using spiral scan.
  result = ivec2(-1, -1)
  var bestDist = int.high
  for dx in -maxRadius .. maxRadius:
    for dy in -maxRadius .. maxRadius:
      let x = pos.x + dx.int32
      let y = pos.y + dy.int32
      if x < MapBorder.int32 or x >= (MapWidth - MapBorder).int32 or
         y < MapBorder.int32 or y >= (MapHeight - MapBorder).int32:
        continue
      if env.terrain[x][y] != Water:
        continue
      let dist = abs(dx) + abs(dy)
      if dist < bestDist:
        bestDist = dist
        result = ivec2(x, y)

proc canPlacePondTile(env: Environment, pos: IVec2): bool =
  ## Check if a tile can be converted to pond water.
  if not isValidPos(pos):
    return false
  let t = env.terrain[pos.x][pos.y]
  if t in {Water, ShallowWater, Bridge, Road}:
    return false
  if t in RampTerrain:
    return false
  # Don't overwrite tiles that have things on them
  if not isNil(env.grid[pos.x][pos.y]):
    return false
  if not isNil(env.getBackgroundThing(pos)):
    return false
  true

proc placePond(env: Environment, center: IVec2, tileCount: int, rng: var Rand): seq[IVec2] =
  ## Place a small cluster of Water tiles around center. Returns placed positions.
  ## Uses flood-fill style expansion from center.
  result = @[]
  if not canPlacePondTile(env, center):
    return
  setTerrain(env, center, Water)
  result.add(center)
  # Expand outward from placed tiles
  var frontier: seq[IVec2] = @[center]
  let dirs = [ivec2(1, 0), ivec2(-1, 0), ivec2(0, 1), ivec2(0, -1)]
  while result.len < tileCount and frontier.len > 0:
    let idx = randIntExclusive(rng, 0, frontier.len)
    let src = frontier[idx]
    var expanded = false
    # Try each direction in random order
    var dirOrder = [0, 1, 2, 3]
    for i in countdown(3, 1):
      let j = randIntInclusive(rng, 0, i)
      swap(dirOrder[i], dirOrder[j])
    for di in dirOrder:
      let nb = src + dirs[di]
      if canPlacePondTile(env, nb) and nb notin result:
        setTerrain(env, nb, Water)
        result.add(nb)
        frontier.add(nb)
        expanded = true
        break
    if not expanded:
      # Remove exhausted tile from frontier
      frontier.del(idx)

proc canPlaceStreamTile(env: Environment, pos: IVec2): bool =
  ## Check if a tile can be part of a stream path.
  if not isValidPos(pos):
    return false
  let t = env.terrain[pos.x][pos.y]
  # Can walk through existing water, shallow water, bridges
  if t in {Water, ShallowWater, Bridge}:
    return true
  # Can convert empty/natural terrain to stream
  if t in RampTerrain:
    return false
  if t == Road:
    return false  # Streams don't overwrite roads (bridges handle crossings)
  # Don't overwrite tiles with things
  if not isNil(env.grid[pos.x][pos.y]):
    return false
  if not isNil(env.getBackgroundThing(pos)):
    return false
  true

proc reconstructPath(cameFrom: seq[tuple[pos, parent: IVec2]], endPos: IVec2): seq[IVec2] =
  ## Reconstruct BFS path by following parent pointers backward from endPos.
  result = @[]
  var cur = endPos
  var safety = cameFrom.len + 1
  while cur.x >= 0 and safety > 0:
    result.add(cur)
    var foundParent = false
    for entry in cameFrom:
      if entry.pos == cur:
        cur = entry.parent
        foundParent = true
        break
    if not foundParent:
      break
    dec safety
  # Reverse to get start-to-end order
  for i in 0 ..< result.len div 2:
    swap(result[i], result[result.len - 1 - i])

proc bfsStreamPath(env: Environment, start, goal: IVec2): seq[IVec2] =
  ## BFS pathfind from start to goal for stream placement.
  ## Returns path from start to nearest river water tile.
  result = @[]
  if start.x < 0 or goal.x < 0:
    return
  var queue: seq[IVec2] = @[start]
  var cameFrom: seq[tuple[pos, parent: IVec2]] = @[]
  cameFrom.add((pos: start, parent: ivec2(-1, -1)))
  let dirs = [ivec2(1, 0), ivec2(-1, 0), ivec2(0, 1), ivec2(0, -1)]
  var head = 0
  while head < queue.len and head < StreamMaxPathLen:
    let current = queue[head]
    inc head
    if current == goal:
      return reconstructPath(cameFrom, current)
    # Accept reaching any Water tile as "connected to river"
    if current != start and env.terrain[current.x][current.y] == Water:
      return reconstructPath(cameFrom, current)
    for dir in dirs:
      let nb = current + dir
      if not canPlaceStreamTile(env, nb):
        continue
      # Inline visited check to avoid closure capture
      var alreadyVisited = false
      for entry in cameFrom:
        if entry.pos == nb:
          alreadyVisited = true
          break
      if alreadyVisited:
        continue
      cameFrom.add((pos: nb, parent: current))
      queue.add(nb)
  result = @[]  # No path found

proc generateVillagePonds(env: Environment, villageCenters: seq[IVec2], rng: var Rand) =
  ## For each village, place a small pond nearby and connect it to the river
  ## via a narrow stream of ShallowWater.
  for vc in villageCenters:
    # Find a valid pond center within PondSearchRadius of village
    var pondCenter = ivec2(-1, -1)
    var bestDist = int.high
    # Try random positions, pick first valid one close to village
    for attempt in 0 ..< 80:
      let dx = randIntInclusive(rng, -PondSearchRadius, PondSearchRadius)
      let dy = randIntInclusive(rng, -PondSearchRadius, PondSearchRadius)
      let dist = abs(dx) + abs(dy)
      if dist < PondMinDistFromCenter or dist > PondSearchRadius:
        continue
      let candidate = ivec2(vc.x + dx.int32, vc.y + dy.int32)
      if not canPlacePondTile(env, candidate):
        continue
      # Verify at least a few neighbors are also placeable (room for pond)
      var openNeighbors = 0
      for ndx in -1 .. 1:
        for ndy in -1 .. 1:
          if ndx == 0 and ndy == 0: continue
          let nb = candidate + ivec2(ndx.int32, ndy.int32)
          if canPlacePondTile(env, nb):
            inc openNeighbors
      if openNeighbors < 2:
        continue
      if dist < bestDist:
        bestDist = dist
        pondCenter = candidate
        if dist <= PondMinDistFromCenter + 2:
          break  # Good enough, stop searching

    if pondCenter.x < 0:
      continue  # Skip this village if no valid pond location found

    # Place the pond
    let pondSize = randIntInclusive(rng, PondMinTiles, PondMaxTiles)
    let pondTiles = placePond(env, pondCenter, pondSize, rng)
    if pondTiles.len == 0:
      continue

    # Find nearest river tile from pond center (search wider area)
    let riverTarget = findNearestRiverTile(env, pondCenter, MapWidth)
    if riverTarget.x < 0:
      continue  # No river found (shouldn't happen normally)

    # BFS from pond edge to river
    let streamPath = bfsStreamPath(env, pondCenter, riverTarget)
    if streamPath.len == 0:
      continue  # No path found; pond still provides local water

    # Place stream tiles along path
    for pos in streamPath:
      let t = env.terrain[pos.x][pos.y]
      if t == Water or t == Bridge:
        continue  # Don't overwrite deep water or bridges
      if t == ShallowWater:
        continue  # Already a stream tile
      if canPlacePondTile(env, pos):
        setTerrain(env, pos, StreamTerrainType)

proc initNeutralStructures(env: Environment, rng: var Rand) =
  ## Place goblin hives, spawners, and other neutral structures.
  let numTeams = MapRoomObjectsTeams
  var totalAgentsSpawned = MapRoomObjectsTeams * MapAgentsPerTeam

  # Place goblin hives with surrounding structures, then spawn goblin agents.
  const GoblinHiveCount = 2
  var goblinHivePositions: seq[IVec2] = @[]

  proc findGoblinHivePos(existing: seq[IVec2], rng: var Rand): IVec2 =
    const HiveRadius = 2
    let minGoblinDist = DefaultSpawnerMinDistance
    let minGoblinDist2 = minGoblinDist * minGoblinDist
    let minHiveDist = max(4, DefaultSpawnerMinDistance div 2)
    let minHiveDist2 = minHiveDist * minHiveDist
    var center: IVec2
    if tryPickEmptyPos(rng, env, 200, proc(candidate: IVec2, attempt: int): bool =
      if env.terrain[candidate.x][candidate.y] == Water:
        return false
      for altar in env.thingsByKind[Altar]:
        let dx = int(candidate.x) - int(altar.pos.x)
        let dy = int(candidate.y) - int(altar.pos.y)
        if dx * dx + dy * dy < minGoblinDist2:
          return false
      for hive in existing:
        let dx = int(candidate.x) - int(hive.x)
        let dy = int(candidate.y) - int(hive.y)
        if dx * dx + dy * dy < minHiveDist2:
          return false
      for dx in -HiveRadius .. HiveRadius:
        for dy in -HiveRadius .. HiveRadius:
          let pos = candidate + ivec2(dx, dy)
          if not isValidPos(pos):
            return false
          if not env.isEmpty(pos) or not env.getBackgroundThing(pos).isNil or
              isBlockedTerrain(env.terrain[pos.x][pos.y]):
            return false
      true
    , center):
      for dx in -HiveRadius .. HiveRadius:
        for dy in -HiveRadius .. HiveRadius:
          let pos = center + ivec2(dx, dy)
          if isValidPos(pos) and not isBlockedTerrain(env.terrain[pos.x][pos.y]):
            setTerrain(env, pos, Empty)
      return center
    var fallback = rng.randomEmptyPos(env)
    var tries = 0
    while tries < 50:
      var fallbackOk = env.terrain[fallback.x][fallback.y] != Water
      if fallbackOk:
        for hive in existing:
          let dx = int(fallback.x) - int(hive.x)
          let dy = int(fallback.y) - int(hive.y)
          if dx * dx + dy * dy < minHiveDist2:
            fallbackOk = false
            break
      if fallbackOk:
        break
      fallback = rng.randomEmptyPos(env)
      inc tries
    fallback

  let goblinTint = GoblinTint
  for hiveIndex in 0 ..< GoblinHiveCount:
    let goblinHivePos = findGoblinHivePos(goblinHivePositions, rng)
    goblinHivePositions.add(goblinHivePos)
    env.add(Thing(kind: GoblinHive, pos: goblinHivePos, teamId: -1))

    var goblinSpots = env.findEmptyPositionsAround(goblinHivePos, 2)
    if goblinSpots.len == 0:
      goblinSpots = env.findEmptyPositionsAround(goblinHivePos, 3)
    template popGoblinSpot(): IVec2 =
      (block:
        let spotIdx = randIntInclusive(rng, 0, goblinSpots.len - 1)
        let pos = goblinSpots[spotIdx]
        goblinSpots[spotIdx] = goblinSpots[^1]
        goblinSpots.setLen(goblinSpots.len - 1)
        pos)

    let hutCount = MapRoomObjectsGoblinHuts div GoblinHiveCount +
      (if hiveIndex < MapRoomObjectsGoblinHuts mod GoblinHiveCount: 1 else: 0)
    var hutsRemaining = hutCount
    while hutsRemaining > 0 and goblinSpots.len > 0:
      dec hutsRemaining
      env.add(Thing(kind: GoblinHut, pos: popGoblinSpot(), teamId: -1))

    let totemCount = MapRoomObjectsGoblinTotems div GoblinHiveCount +
      (if hiveIndex < MapRoomObjectsGoblinTotems mod GoblinHiveCount: 1 else: 0)
    var totemsRemaining = totemCount
    while totemsRemaining > 0 and goblinSpots.len > 0:
      dec totemsRemaining
      env.add(Thing(kind: GoblinTotem, pos: popGoblinSpot(), teamId: -1))

    let agentCount = MapRoomObjectsGoblinAgents div GoblinHiveCount +
      (if hiveIndex < MapRoomObjectsGoblinAgents mod GoblinHiveCount: 1 else: 0)
    for _ in 0 ..< agentCount:
      let agentId = totalAgentsSpawned
      let agentPos = if goblinSpots.len > 0:
        popGoblinSpot()
      else:
        rng.randomEmptyPos(env)
      env.agentColors[agentId] = goblinTint
      env.terminated[agentId] = 0.0
      env.add(Thing(
        kind: Agent,
        agentId: agentId,
        pos: agentPos,
        orientation: Orientation(randIntInclusive(rng, 0, 3)),
        homeAltar: goblinHivePos,
        frozen: 0,
        hp: GoblinMaxHp,
        maxHp: GoblinMaxHp,
        attackDamage: GoblinAttackDamage,
        unitClass: UnitGoblin,
        embarkedUnitClass: UnitGoblin,
        stance: StanceDefensive,  # Goblins use Defensive stance
        teamIdOverride: GoblinTeamId
      ))
      totalAgentsSpawned += 1

  # Random spawner placement with minimum distance from teams and other spawners
  # Gather altar positions for distance checks
  var altarPositionsNow: seq[IVec2] = @[]
  var spawnerPositions: seq[IVec2] = @[]
  for thing in env.things:
    if thing.kind == Altar:
      altarPositionsNow.add(thing.pos)

  let minDist = DefaultSpawnerMinDistance
  let minDist2 = minDist * minDist

  for i in 0 ..< numTeams:
    let spawnerStruct = Structure(width: 3, height: 3, centerPos: ivec2(1, 1))
    var targetPos: IVec2
    let placed = tryPickEmptyPos(rng, env, 200, proc(candidate: IVec2, attempt: int): bool =
      # Keep within borders allowing spawner bounds.
      if candidate.x < MapBorder + spawnerStruct.width div 2 or
         candidate.x >= MapWidth - MapBorder - spawnerStruct.width div 2 or
         candidate.y < MapBorder + spawnerStruct.height div 2 or
         candidate.y >= MapHeight - MapBorder - spawnerStruct.height div 2:
        return false

      # Check simple area clear (3x3).
      for dx in -(spawnerStruct.width div 2) .. (spawnerStruct.width div 2):
        for dy in -(spawnerStruct.height div 2) .. (spawnerStruct.height div 2):
          let checkPos = candidate + ivec2(dx, dy)
          if not isValidPos(checkPos):
            return false
          if not env.isEmpty(checkPos) or isBlockedTerrain(env.terrain[checkPos.x][checkPos.y]):
            return false

      # Enforce min distance from any altar and other spawners.
      for ap in altarPositionsNow:
        let dx = int(candidate.x) - int(ap.x)
        let dy = int(candidate.y) - int(ap.y)
        if dx*dx + dy*dy < minDist2:
          return false
      for sp in spawnerPositions:
        let dx = int(candidate.x) - int(sp.x)
        let dy = int(candidate.y) - int(sp.y)
        if dx*dx + dy*dy < minDist2:
          return false
      true
    , targetPos)

    if placed:
      # Clear terrain and place spawner
      for dx in -(spawnerStruct.width div 2) .. (spawnerStruct.width div 2):
        for dy in -(spawnerStruct.height div 2) .. (spawnerStruct.height div 2):
          let clearPos = targetPos + ivec2(dx, dy)
          if clearPos.x >= 0 and clearPos.x < MapWidth and clearPos.y >= 0 and clearPos.y < MapHeight:
            if not isBlockedTerrain(env.terrain[clearPos.x][clearPos.y]):
              setTerrain(env, clearPos, Empty)

      env.add(Thing(
        kind: Spawner,
        pos: targetPos,
        cooldown: 0,
        homeSpawner: targetPos
      ))

      # Add this spawner position for future collision checks
      spawnerPositions.add(targetPos)

      let nearbyPositions = env.findEmptyPositionsAround(targetPos, 1)
      if nearbyPositions.len > 0:
        let spawnCount = min(3, nearbyPositions.len)
        for i in 0 ..< spawnCount:
          env.add(createTumor(env, nearbyPositions[i], targetPos, rng))

    # If we fail to satisfy distance after attempts, place anywhere random
    if not placed:
      targetPos = rng.randomEmptyPos(env)
      env.add(Thing(
        kind: Spawner,
        pos: targetPos,
        cooldown: 0,
        homeSpawner: targetPos
      ))
      let nearbyPositions = env.findEmptyPositionsAround(targetPos, 1)
      if nearbyPositions.len > 0:
        let spawnCount = min(3, nearbyPositions.len)
        for i in 0 ..< spawnCount:
          env.add(createTumor(env, nearbyPositions[i], targetPos, rng))

proc initResources(env: Environment, rng: var Rand, treeOases: seq[TreeOasis]) =
  ## Spawn resource nodes (magma, trees, wheat, ore, plants) as Things.
  # Magma spawns in slightly larger clusters (3-4) for higher local density.
  var poolsPlaced = 0
  let magmaClusterCount = max(1, min(MapRoomObjectsMagmaClusters, max(1, MapRoomObjectsMagmaPools div 2)))
  for clusterIndex in 0 ..< magmaClusterCount:
    let remaining = MapRoomObjectsMagmaPools - poolsPlaced
    if remaining <= 0:
      break
    let clustersLeft = magmaClusterCount - clusterIndex
    let maxCluster = min(4, remaining)
    let minCluster = if remaining >= 3: 3 else: 1
    let baseSize = max(minCluster, min(maxCluster, remaining div clustersLeft))
    let clusterSize = max(minCluster, min(maxCluster, baseSize + randIntInclusive(rng, -1, 1)))
    let center = rng.randomEmptyPos(env)

    env.add(Thing(
      kind: Magma,
      pos: center,
    ))
    inc poolsPlaced

    if poolsPlaced >= MapRoomObjectsMagmaPools:
      break

    var candidates = gatherEmptyAround(env, center, 1, 2, clusterSize - 1)

    let toPlace = min(clusterSize - 1, candidates.len)
    for i in 0 ..< toPlace:
      env.add(Thing(
        kind: Magma,
        pos: candidates[i],
      ))
      inc poolsPlaced
      if poolsPlaced >= MapRoomObjectsMagmaPools:
        break

  # Spawn resource nodes (trees, wheat, ore, plants) as Things.
  block:
    # Wheat fields.
    for _ in 0 ..< randIntInclusive(rng, WheatFieldClusterCountMin, WheatFieldClusterCountMax):
      let pos = pickInteriorPos(rng, 3, 20, proc(pos: IVec2, attempt: int): bool =
        hasWaterNearby(env, pos, 5, includeShallow = true) or attempt > 10
      )
      let fieldSize = randIntInclusive(rng, WheatFieldSizeMin, WheatFieldSizeMax)
      for (sizeDelta, density) in [(0, 1.0), (1, 0.5)]:
        placeResourceCluster(env, pos.x.int, pos.y.int, fieldSize + sizeDelta, density, 0.3,
          Wheat, ItemWheat, ResourceGround, rng)

    proc placeTreeOasisTrees(oasis: TreeOasis, rng: var Rand) =
      let centerX = oasis.center.x.int
      let centerY = oasis.center.y.int
      for ox in -(oasis.rx + 2) .. (oasis.rx + 2):
        for oy in -(oasis.ry + 2) .. (oasis.ry + 2):
          let px = centerX + ox
          let py = centerY + oy
          if px < MapBorder or px >= MapWidth - MapBorder or py < MapBorder or py >= MapHeight - MapBorder:
            continue
          if env.terrain[px][py] == Water:
            continue
          let pos = ivec2(px.int32, py.int32)
          if hasWaterNearby(env, pos, 1, includeShallow = true) and randChance(rng, 0.7) and env.terrain[px][py] in TreeGround:
            addResourceNode(env, pos, Tree, ItemWood)

    for oasis in treeOases:
      placeTreeOasisTrees(oasis, rng)

    if UseLegacyTreeClusters:
      let numGroves = randIntInclusive(rng, TreeGroveClusterCountMin, TreeGroveClusterCountMax)
      for _ in 0 ..< numGroves:
        let pos = randInteriorPos(rng, 3)
        let x = pos.x.int
        let y = pos.y.int
        let groveSize = randIntInclusive(rng, 3, 10)
        placeResourceCluster(env, x, y, groveSize, 0.8, 0.4, Tree, ItemWood, ResourceGround, rng)

    proc buildClusterSizes(targetDeposits: int, clusterCount: int, rng: var Rand): seq[int] =
      let minCluster = ClusterMineSizeMin
      let maxCluster = ClusterMineSizeMax
      let minDeposits = clusterCount * minCluster
      let maxDeposits = clusterCount * maxCluster
      let clamped = max(minDeposits, min(maxDeposits, targetDeposits))
      result = newSeq[int](clusterCount)
      for i in 0 ..< clusterCount:
        result[i] = minCluster
      var extras = clamped - minDeposits
      while extras > 0:
        let clusterIdx = randIntInclusive(rng, 0, clusterCount - 1)
        if result[clusterIdx] < maxCluster:
          inc result[clusterIdx]
          dec extras

    proc placeMineClusters(depositKind: ThingKind, depositItem: ItemKey,
                           targetDeposits: int, clusterCount: int, rng: var Rand) =
      if targetDeposits <= 0 or clusterCount <= 0:
        return
      let clusterSizes = buildClusterSizes(targetDeposits, clusterCount, rng)
      for clusterIndex in 0 ..< clusterSizes.len:
        let clusterSize = clusterSizes[clusterIndex]
        let center = rng.randomEmptyPos(env)

        addResourceNode(env, center, depositKind, depositItem, MineDepositAmount)

        var candidates = gatherEmptyAround(env, center, 1, 2, clusterSize - 1)

        let toPlace = min(clusterSize - 1, candidates.len)
        for i in 0 ..< toPlace:
          addResourceNode(env, candidates[i], depositKind, depositItem, MineDepositAmount)

    placeMineClusters(Stone, ItemStone, MapRoomObjectsStoneClusters, MapRoomObjectsStoneClusterCount, rng)
    placeMineClusters(Gold, ItemGold, MapRoomObjectsGoldClusters, MapRoomObjectsGoldClusterCount, rng)

    let fishClusters = max(8, MapWidth div 20)
    for _ in 0 ..< fishClusters:
      var placed = false
      for attempt in 0 ..< FishPlacementAttempts:
        let pos = randInteriorPos(rng, 2)
        let x = pos.x.int
        let y = pos.y.int
        if env.terrain[x][y] notin {Water, ShallowWater}:
          continue
        let size = randIntInclusive(rng, FishClusterSizeMin, FishClusterSizeMax)
        placeResourceCluster(env, x, y, size, ClusterDensityHigh, ClusterFalloffSteep, Fish, ItemFish, {Water, ShallowWater}, rng)
        placed = true
        break
      if not placed:
        break

    var relicsPlaced = 0
    var relicAttempts = 0
    while relicsPlaced < MapRoomObjectsRelics and relicAttempts < MapRoomObjectsRelics * 10:
      inc relicAttempts
      let pos = rng.randomEmptyPos(env)
      if env.terrain[pos.x][pos.y] == Water:
        continue
      if env.isSpawnable(pos):
        let relic = Thing(kind: Relic, pos: pos)
        relic.inventory = emptyInventory()
        setInv(relic, ItemGold, 1)
        env.add(relic)
        inc relicsPlaced

    for _ in 0 ..< BushClusterCount:
      let pos = pickInteriorPos(rng, 2, 12, proc(pos: IVec2, attempt: int): bool =
        hasWaterNearby(env, pos, BushWaterProximity, includeShallow = true) or attempt >= 9
      )
      let size = randIntInclusive(rng, BushClusterSizeMin, BushClusterSizeMax)
      placeResourceCluster(env, pos.x.int, pos.y.int, size, ClusterDensityMedium, ClusterFalloffSteep, Bush, ItemPlant, ResourceGround, rng)

    placeBiomeResourceClusters(env, rng, max(10, MapWidth div 20),
      2, 5, 0.65, 0.4, Cactus, ItemPlant, BiomeDesertType)

    placeBiomeResourceClusters(env, rng, max(10, MapWidth div 30),
      2, 6, 0.7, 0.45, Stalagmite, ItemStone, BiomeCavesType)

proc initContestedZones(env: Environment, rng: var Rand) =
  ## Place resource-rich contested zones near the map center.
  ## These zones have concentrated gold, stone, wheat, bushes, cows, and relics
  ## to incentivize teams to fight over central territory.
  let centerX = MapWidth div 2
  let centerY = MapHeight div 2

  # Define zone centers arranged around the trading hub.
  # 3 zones placed at ~120 degree intervals around center, offset enough
  # to avoid the trading hub (TradingHubSize/2 + clearance).
  let hubHalf = TradingHubSize div 2
  let offset = hubHalf + ContestedZoneHubClearance
  type ZonePos = tuple[x, y: int]
  var zoneCenters: seq[ZonePos] = @[]

  # NW of center
  zoneCenters.add((x: centerX - offset, y: centerY - offset + 4))
  # NE of center
  zoneCenters.add((x: centerX + offset, y: centerY - offset + 4))
  # S of center
  zoneCenters.add((x: centerX, y: centerY + offset))

  let zoneCount = min(ContestedZoneCount, zoneCenters.len)

  for zoneIdx in 0 ..< zoneCount:
    let zx = zoneCenters[zoneIdx].x
    let zy = zoneCenters[zoneIdx].y
    let radius = ContestedZoneRadius

    # Apply distinctive tint to zone tiles and set terrain to Fertile
    # (lighter grass) so players can visually identify the contested area.
    for dx in -radius .. radius:
      for dy in -radius .. radius:
        let dist = dx * dx + dy * dy
        if dist > radius * radius:
          continue
        let px = zx + dx
        let py = zy + dy
        if px < MapBorder or px >= MapWidth - MapBorder or
           py < MapBorder or py >= MapHeight - MapBorder:
          continue
        # Don't overwrite water, roads, or bridges
        if env.terrain[px][py] in {Water, ShallowWater, Road, Bridge}:
          continue
        # Set distinctive terrain and tint
        env.terrain[px][py] = Fertile
        env.baseTintColors[px][py] = ContestedZoneTint

    # Clear any trees/walls in the inner area to make space for resources
    let innerRadius = radius - 2
    for dx in -innerRadius .. innerRadius:
      for dy in -innerRadius .. innerRadius:
        let dist = dx * dx + dy * dy
        if dist > innerRadius * innerRadius:
          continue
        let px = zx + dx
        let py = zy + dy
        if px < MapBorder or px >= MapWidth - MapBorder or
           py < MapBorder or py >= MapHeight - MapBorder:
          continue
        let pos = ivec2(px.int32, py.int32)
        let existing = env.getThing(pos)
        if not existing.isNil and existing.kind in {Tree, Wall}:
          removeThing(env, existing)

    # Place gold mines (concentrated cluster)
    block:
      let goldCenter = ivec2((zx + randIntInclusive(rng, -3, 3)).int32,
                              (zy + randIntInclusive(rng, -3, 3)).int32)
      addResourceNode(env, goldCenter, Gold, ItemGold, MineDepositAmount)
      var candidates = gatherEmptyAround(env, goldCenter, 1, 2, ContestedZoneGoldCount - 1)
      let toPlace = min(ContestedZoneGoldCount - 1, candidates.len)
      for i in 0 ..< toPlace:
        addResourceNode(env, candidates[i], Gold, ItemGold, MineDepositAmount)

    # Place stone mines
    block:
      let stoneCenter = ivec2((zx + randIntInclusive(rng, -4, 4)).int32,
                               (zy + randIntInclusive(rng, -4, 4)).int32)
      addResourceNode(env, stoneCenter, Stone, ItemStone, MineDepositAmount)
      var candidates = gatherEmptyAround(env, stoneCenter, 1, 2, ContestedZoneStoneCount - 1)
      let toPlace = min(ContestedZoneStoneCount - 1, candidates.len)
      for i in 0 ..< toPlace:
        addResourceNode(env, candidates[i], Stone, ItemStone, MineDepositAmount)

    # Place wheat cluster
    block:
      let wheatPos = ivec2((zx + randIntInclusive(rng, -3, 3)).int32,
                            (zy + randIntInclusive(rng, -3, 3)).int32)
      placeResourceCluster(env, wheatPos.x.int, wheatPos.y.int,
        ContestedZoneWheatSize, 0.85, 0.35, Wheat, ItemWheat, ResourceGround, rng)

    # Place bush cluster
    block:
      let bushPos = ivec2((zx + randIntInclusive(rng, -4, 4)).int32,
                           (zy + randIntInclusive(rng, -4, 4)).int32)
      placeResourceCluster(env, bushPos.x.int, bushPos.y.int,
        ContestedZoneBushSize, ClusterDensityMedium, ClusterFalloffSteep, Bush, ItemPlant, ResourceGround, rng)

    # Place cows in the zone
    block:
      var cowsPlaced = 0
      var attempts = 0
      while cowsPlaced < ContestedZoneCowCount and attempts < ContestedZoneCowCount * 10:
        inc attempts
        let dx = randIntInclusive(rng, -radius + 2, radius - 2)
        let dy = randIntInclusive(rng, -radius + 2, radius - 2)
        if dx * dx + dy * dy > (radius - 2) * (radius - 2):
          continue
        let pos = ivec2((zx + dx).int32, (zy + dy).int32)
        if not isValidPos(pos) or not env.isSpawnable(pos):
          continue
        if env.terrain[pos.x][pos.y] in {Water, ShallowWater}:
          continue
        let cow = Thing(
          kind: Cow,
          pos: pos,
          orientation: Orientation.W,
          herdId: 100 + zoneIdx  # Unique herd IDs for contested zone cows
        )
        cow.inventory = emptyInventory()
        setInv(cow, ItemMeat, ResourceNodeInitial)
        env.add(cow)
        inc cowsPlaced

    # Place relic
    for _ in 0 ..< ContestedZoneRelics:
      for attempt in 0 ..< 20:
        let dx = randIntInclusive(rng, -radius + 3, radius - 3)
        let dy = randIntInclusive(rng, -radius + 3, radius - 3)
        let pos = ivec2((zx + dx).int32, (zy + dy).int32)
        if not isValidPos(pos) or not env.isSpawnable(pos):
          continue
        if env.terrain[pos.x][pos.y] in {Water, ShallowWater}:
          continue
        let relic = Thing(kind: Relic, pos: pos)
        relic.inventory = emptyInventory()
        setInv(relic, ItemGold, 1)
        env.add(relic)
        break

proc initWildlife(env: Environment, rng: var Rand) =
  ## Spawn wildlife: cows, bears, and wolves.
  proc chooseGroupSize(remaining, minSize, maxSize: int, rng: var Rand): int =
    if remaining <= maxSize:
      return remaining
    result = randIntInclusive(rng, minSize, maxSize)
    let remainder = remaining - result
    if remainder > 0 and remainder < minSize:
      result -= (minSize - remainder)

  proc collectGroupPositions(center: IVec2, radius: int): seq[IVec2] =
    var positions = env.findEmptyPositionsAround(center, radius)
    positions.insert(center, 0)
    result = @[]
    for pos in positions:
      if env.terrain[pos.x][pos.y] == Empty and env.biomes[pos.x][pos.y] != BiomeDungeonType:
        result.add(pos)


  # Cows spawn in herds (5-10) across open terrain.
  const MinHerdSize = 5
  const MaxHerdSize = 10
  var cowsPlaced = 0
  var herdId = 0
  while cowsPlaced < MapRoomObjectsCows:
    let center = rng.randomEmptyPos(env)
    if env.terrain[center.x][center.y] != Empty or env.biomes[center.x][center.y] == BiomeDungeonType:
      continue
    let filtered = collectGroupPositions(center, 3)
    if filtered.len < MinHerdSize:
      continue
    let toPlace = min(chooseGroupSize(MapRoomObjectsCows - cowsPlaced, MinHerdSize, MaxHerdSize, rng), filtered.len)
    for i in 0 ..< toPlace:
      let cow = Thing(
        kind: Cow,
        pos: filtered[i],
        orientation: Orientation.W,
        herdId: herdId
      )
      cow.inventory = emptyInventory()
      setInv(cow, ItemMeat, ResourceNodeInitial)
      env.add(cow)
      inc cowsPlaced
      if cowsPlaced >= MapRoomObjectsCows:
        break
    inc herdId

  # Bears spawn as solitary predators across open terrain.
  var bearsPlaced = 0
  while bearsPlaced < MapRoomObjectsBears:
    let pos = rng.randomEmptyPos(env)
    if env.terrain[pos.x][pos.y] != Empty or env.biomes[pos.x][pos.y] == BiomeDungeonType:
      continue
    let bear = Thing(
      kind: Bear,
      pos: pos,
      orientation: Orientation.W,
      maxHp: BearMaxHp,
      hp: BearMaxHp,
      attackDamage: BearAttackDamage
    )
    env.add(bear)
    inc bearsPlaced

  # Wolves spawn in packs (3-5) across open terrain.
  var wolvesPlaced = 0
  var packId = 0
  while wolvesPlaced < MapRoomObjectsWolves:
    let center = rng.randomEmptyPos(env)
    if env.terrain[center.x][center.y] != Empty or env.biomes[center.x][center.y] == BiomeDungeonType:
      continue
    let filtered = collectGroupPositions(center, 4)
    if filtered.len < WolfPackMinSize:
      continue
    let toPlace = min(chooseGroupSize(MapRoomObjectsWolves - wolvesPlaced, WolfPackMinSize, WolfPackMaxSize, rng), filtered.len)
    var packLeader: Thing = nil
    for i in 0 ..< toPlace:
      let wolf = Thing(
        kind: Wolf,
        pos: filtered[i],
        orientation: Orientation.W,
        packId: packId,
        maxHp: WolfMaxHp,
        hp: WolfMaxHp,
        attackDamage: WolfAttackDamage,
        isPackLeader: i == 0  # First wolf in pack is the leader
      )
      env.add(wolf)
      if i == 0:
        packLeader = wolf
      inc wolvesPlaced
      if wolvesPlaced >= MapRoomObjectsWolves:
        break
    # Track pack leader
    while env.wolfPackLeaders.len <= packId:
      env.wolfPackLeaders.add(nil)
    env.wolfPackLeaders[packId] = packLeader
    inc packId

proc initFinalize(env: Environment) =
  ## Final initialization steps: connectivity, replay, spatial index.
  # Ensure the world is a single connected component after terrain and structures.
  env.makeConnected()

  # Initialize observations only when first needed (lazy approach)
  # Individual action updates will populate observations as needed
  maybeStartReplayEpisode(env)

  # Build initial spatial index for efficient nearest-thing queries
  rebuildSpatialIndex(env)

proc init(env: Environment, seed: int = 0) =
  ## Initialize the environment by orchestrating all initialization phases.
  ## When seed is 0 (default), uses current time for non-deterministic init.
  let seed = if seed == 0: int(nowSeconds() * 1000) else: seed
  env.gameSeed = seed  # Store for step RNG variation
  var rng = initRand(seed)

  # Phase 1: Reset all state
  initState(env)

  # Phase 2: Terrain, biomes, water features, elevation, cliffs
  let treeOases = initTerrainAndBiomes(env, rng, seed)

  # Phase 3: Central trading hub
  initTradingHub(env, rng)

  # Phase 4: Teams, villages, altars, agents
  let villageCenters = initTeams(env, rng)

  # Phase 4b: Village ponds with stream connections to river
  generateVillagePonds(env, villageCenters, rng)

  # Phase 5: Goblin hives, spawners, neutral structures
  initNeutralStructures(env, rng)

  # Phase 6: Resource nodes (magma, trees, wheat, ore, plants)
  initResources(env, rng, treeOases)

  # Phase 6b: Control point (King of the Hill)
  if env.config.victoryCondition in {VictoryKingOfTheHill, VictoryAll}:
    let centerX = (MapWidth div 2).int32
    let centerY = (MapHeight div 2).int32
    var placed = false
    # Try center first, then spiral outward to find a valid spot
    for radius in 0 .. 20:
      if placed:
        break
      for dx in -radius .. radius:
        if placed:
          break
        for dy in -radius .. radius:
          if abs(dx) != radius and abs(dy) != radius:
            continue  # Only check perimeter of current ring
          let pos = ivec2(centerX + dx.int32, centerY + dy.int32)
          if isValidPos(pos) and env.isEmpty(pos):
            let cp = Thing(kind: ControlPoint, pos: pos, teamId: -1)
            cp.inventory = emptyInventory()
            env.add(cp)
            placed = true
            break

  # Phase 6c: Contested resource zones near map center
  initContestedZones(env, rng)

  # Phase 7: Wildlife (cows, bears, wolves)
  initWildlife(env, rng)

  # Phase 8: Connectivity, replay, spatial index
  initFinalize(env)


proc newEnvironment*(): Environment =
  ## Create a new environment with default configuration
  result = Environment(config: defaultEnvironmentConfig())
  result.init()

proc newEnvironment*(config: EnvironmentConfig): Environment =
  ## Create a new environment with custom configuration
  result = Environment(config: config)
  result.init()

proc newEnvironment*(config: EnvironmentConfig, seed: int): Environment =
  ## Create a new environment with custom configuration and explicit seed
  result = Environment(config: config)
  result.init(seed)

# Global environment is initialized by entry points (e.g., tribal_village.nim).
