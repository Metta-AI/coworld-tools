import
  std/[sets, tables],
  vmath,
  ../[common_types, entropy, environment, terrain],
  ai_types, ai_utils, coordination, memoization

export ai_types, ai_utils, environment, common_types
export terrain, coordination, entropy, memoization

const
  CacheMaxAge* = 12
  ThreatMapStaggerInterval* = 5
  PathBlockRetryInterval* = 8

proc stanceAllowsAutoAttack*(env: Environment, agent: Thing): bool =
  ## Return whether the agent's stance allows auto-attack.
  stanceAllows(env, agent, BehaviorAutoAttack)

proc hasHarvestableResource*(thing: Thing): bool =
  ## Return whether a resource thing still has harvestable inventory.
  if thing.isNil:
    return false
  case thing.kind
  of Stump, Stubble:
    let key = if thing.kind == Stubble: ItemWheat else: ItemWood
    return getInv(thing, key) > 0
  of Stone, Stalagmite:
    return getInv(thing, ItemStone) > 0
  of Gold:
    return getInv(thing, ItemGold) > 0
  of Bush, Cactus:
    return getInv(thing, ItemPlant) > 0
  of Fish:
    return getInv(thing, ItemFish) > 0
  of Wheat:
    return getInv(thing, ItemWheat) > 0
  of Corpse:
    for key, count in thing.inventory.pairs:
      if count > 0:
        return true
    return false
  of Tree:
    return true
  of Cow:
    return true
  else:
    return true

const
  Directions8* = [
    ivec2(0, -1),
    ivec2(0, 1),
    ivec2(-1, 0),
    ivec2(1, 0),
    ivec2(-1, -1),
    ivec2(1, -1),
    ivec2(-1, 1),
    ivec2(1, 1)
  ]

  SearchRadius* = 50
  SpiralAdvanceSteps = 3

type
  PerAgentCache*[T] = object
    cacheStep*: int
    cache*: array[MapAgents, T]
    valid*: array[MapAgents, bool]

proc invalidateIfStale*[T](cache: var PerAgentCache[T], currentStep: int) {.inline.} =
  ## Clear cached entries when the simulation step changes.
  if cache.cacheStep != currentStep:
    cache.cacheStep = currentStep
    for i in 0 ..< MapAgents:
      cache.valid[i] = false

proc get*[T](
  cache: var PerAgentCache[T],
  env: Environment,
  agentId: int,
  compute: proc(env: Environment, agentId: int): T
): T =
  ## Return the cached value for an agent.
  cache.invalidateIfStale(env.currentStep)
  if agentId >= 0 and agentId < MapAgents:
    if not cache.valid[agentId]:
      cache.cache[agentId] = compute(env, agentId)
      cache.valid[agentId] = true
    return cache.cache[agentId]
  compute(env, agentId)

proc getWithAgent*[T](
  cache: var PerAgentCache[T],
  env: Environment,
  agent: Thing,
  compute: proc(env: Environment, agent: Thing): T
): T =
  ## Return the cached value for an agent `Thing`.
  cache.invalidateIfStale(env.currentStep)
  let aid = agent.agentId
  if aid >= 0 and aid < MapAgents:
    if not cache.valid[aid]:
      cache.cache[aid] = compute(env, agent)
      cache.valid[aid] = true
    return cache.cache[aid]
  compute(env, agent)

proc getDifficulty*(controller: Controller, teamId: int): DifficultyConfig =
  ## Get the difficulty configuration for a team.
  if teamId >= 0 and teamId < MapRoomObjectsTeams:
    return controller.difficulty[teamId]
  return defaultDifficultyConfig(DiffNormal)

proc setDifficulty*(controller: Controller, teamId: int, level: DifficultyLevel) =
  ## Set the difficulty level for a team.
  if teamId >= 0 and teamId < MapRoomObjectsTeams:
    controller.difficulty[teamId] = defaultDifficultyConfig(level)

proc enableAdaptiveDifficulty*(
  controller: Controller,
  teamId: int,
  targetTerritory: float32 = 0.5
) =
  ## Enable adaptive difficulty for a team.
  if teamId >= 0 and teamId < MapRoomObjectsTeams:
    controller.difficulty[teamId].adaptive = true
    controller.difficulty[teamId].adaptiveTarget = targetTerritory

proc disableAdaptiveDifficulty*(controller: Controller, teamId: int) =
  ## Disable adaptive difficulty for a team.
  if teamId >= 0 and teamId < MapRoomObjectsTeams:
    controller.difficulty[teamId].adaptive = false

proc shouldApplyDecisionDelay*(controller: Controller, teamId: int): bool =
  ## Return whether the AI should emit a difficulty-based NOOP.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  let chance = controller.difficulty[teamId].decisionDelayChance
  if chance <= 0.0:
    return false
  randChance(controller.rng, chance)

const
  AdaptiveCheckInterval* = 500

proc updateAdaptiveDifficulty*(controller: Controller, env: Environment) =
  ## Update difficulty levels for teams with adaptive mode enabled.
  let currentStep = env.currentStep.int32
  let score = env.scoreTerritory()
  let totalTiles = max(1, score.scoredTiles)
  const Threshold = 0.15

  for teamId in 0 ..< MapRoomObjectsTeams:
    if not controller.difficulty[teamId].adaptive:
      continue
    if currentStep - controller.difficulty[teamId].lastAdaptiveCheck <
        AdaptiveCheckInterval:
      continue

    controller.difficulty[teamId].lastAdaptiveCheck = currentStep
    let territoryRatio = float32(score.teamTiles[teamId]) / float32(totalTiles)
    let target = controller.difficulty[teamId].adaptiveTarget
    let currentLevel = controller.difficulty[teamId].level

    template applyDifficultyLevel(newLevel: DifficultyLevel) =
      if newLevel != currentLevel:
        let savedAdaptive = controller.difficulty[teamId].adaptive
        let savedTarget = controller.difficulty[teamId].adaptiveTarget
        controller.difficulty[teamId] = defaultDifficultyConfig(newLevel)
        controller.difficulty[teamId].adaptive = savedAdaptive
        controller.difficulty[teamId].adaptiveTarget = savedTarget
        controller.difficulty[teamId].lastAdaptiveCheck = currentStep

    if territoryRatio > target + Threshold:
      applyDifficultyLevel(case currentLevel
        of DiffEasy: DiffNormal
        of DiffNormal: DiffHard
        of DiffHard, DiffBrutal: DiffBrutal)
    elif territoryRatio < target - Threshold:
      applyDifficultyLevel(case currentLevel
        of DiffEasy, DiffNormal: DiffEasy
        of DiffHard: DiffNormal
        of DiffBrutal: DiffHard)

proc getAgentRole*(controller: Controller, agentId: int): AgentRole =
  ## Return the current role for an initialized agent.
  if agentId >= 0 and agentId < MapAgents and controller.agentsInitialized[agentId]:
    return controller.agents[agentId].role
  return Gatherer

proc isAgentInitialized*(controller: Controller, agentId: int): bool =
  ## Return true when the controller has initialized this agent slot.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agentsInitialized[agentId]
  return false

proc saveStateAndReturn*(
  controller: Controller,
  agentId: int,
  state: AgentState,
  action: uint16
): uint16 =
  ## Persist the updated state for an agent and return the chosen action.
  var nextState = state
  nextState.lastActionVerb = action.int div ActionArgumentCount
  nextState.lastActionArg = action.int mod ActionArgumentCount
  controller.agents[agentId] = nextState
  controller.agentsInitialized[agentId] = true
  return action

proc vecToOrientation*(vec: IVec2): int =
  ## Map a step vector to the corresponding orientation index.
  const orientationTable = [
    4, 2, 6,
    0, 0, 1,
    5, 3, 7
  ]
  let ix = (if vec.x < 0: 0 elif vec.x > 0: 2 else: 1)
  let iy = (if vec.y < 0: 0 elif vec.y > 0: 2 else: 1)
  orientationTable[ix * 3 + iy]

proc signi*(x: int32): int32 =
  ## Return the sign of `x` as -1, 0, or 1.
  if x < 0: -1
  elif x > 0: 1
  else: 0

proc revealTilesInRange*(
  env: Environment,
  teamId: int,
  center: IVec2,
  radius: int
) =
  ## Mark tiles within range as revealed for the specified team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  let minX = max(0, center.x.int - radius)
  let maxX = min(MapWidth - 1, center.x.int + radius)
  let minY = max(0, center.y.int - radius)
  let maxY = min(MapHeight - 1, center.y.int + radius)
  if env.revealedMaps[teamId][center.x][center.y]:
    let cornerRevealed =
      env.revealedMaps[teamId][minX][minY] and
      env.revealedMaps[teamId][maxX][maxY] and
      env.revealedMaps[teamId][minX][maxY] and
      env.revealedMaps[teamId][maxX][minY]
    if cornerRevealed:
      return
  for x in minX .. maxX:
    for y in minY .. maxY:
      if not env.revealedMaps[teamId][x][y]:
        env.revealedMaps[teamId][x][y] = true

proc isRevealed*(env: Environment, teamId: int, pos: IVec2): bool =
  ## Check whether a tile has been revealed by the specified team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  if not isValidPos(pos):
    return false
  env.revealedMaps[teamId][pos.x][pos.y]

proc clearRevealedMap*(env: Environment, teamId: int) =
  ## Clear the revealed map for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      env.revealedMaps[teamId][x][y] = false

proc updateRevealedMapFromVision*(env: Environment, agent: Thing) =
  ## Update the revealed map from the agent's current vision.
  let teamId = getTeamId(agent)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return

  let visionRadius = if agent.unitClass == UnitScout:
    ScoutVisionRange.int
  else:
    ThreatVisionRange.int

  env.revealTilesInRange(teamId, agent.pos, visionRadius)

proc getRevealedTileCount*(env: Environment, teamId: int): int =
  ## Count how many tiles a team has revealed.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  result = 0
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      if env.revealedMaps[teamId][x][y]:
        inc result

proc decayThreats*(controller: Controller, teamId: int, currentStep: int32) =
  ## Remove stale threat entries for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  var map = addr controller.threatMaps[teamId]
  var writeIdx = 0
  for readIdx in 0 ..< map.count:
    let age = currentStep - map.entries[readIdx].lastSeen
    if age < ThreatDecaySteps:
      if writeIdx != readIdx:
        map.entries[writeIdx] = map.entries[readIdx]
      inc writeIdx
  map.count = writeIdx.int32
  map.lastUpdateStep = currentStep

proc reportThreat*(
  controller: Controller,
  teamId: int,
  pos: IVec2,
  strength: int32,
  currentStep: int32,
  agentId: int32 = -1,
  isStructure: bool = false
) =
  ## Report a threat position to the team's shared threat map.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  var map = addr controller.threatMaps[teamId]

  for i in 0 ..< map.count:
    let entry = addr map.entries[i]
    if (entry.pos == pos) or (agentId >= 0 and entry.agentId == agentId):
      entry.pos = pos
      entry.strength = max(entry.strength, strength)
      entry.lastSeen = currentStep
      entry.agentId = agentId
      entry.isStructure = isStructure
      return

  if map.count < MaxThreatEntries:
    map.entries[map.count] = ThreatEntry(
      pos: pos,
      strength: strength,
      lastSeen: currentStep,
      agentId: agentId,
      isStructure: isStructure
    )
    inc map.count

proc getNearestThreat*(
  controller: Controller,
  teamId: int,
  pos: IVec2,
  currentStep: int32
): tuple[pos: IVec2, dist: int32, found: bool] =
  ## Get the nearest known threat to a position.
  result = (pos: ivec2(-1, -1), dist: int32.high, found: false)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  let map = addr controller.threatMaps[teamId]
  for i in 0 ..< map.count:
    let entry = map.entries[i]
    let age = currentStep - entry.lastSeen
    if age >= ThreatDecaySteps:
      continue
    let dist = chebyshevDist(pos, entry.pos)
    if dist < result.dist:
      result = (pos: entry.pos, dist: dist, found: true)

proc getThreatsInRange*(
  controller: Controller,
  teamId: int,
  pos: IVec2,
  rangeVal: int32,
  currentStep: int32
): seq[ThreatEntry] =
  ## Get all known threats within range of a position.
  result = @[]
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  let map = addr controller.threatMaps[teamId]
  for i in 0 ..< map.count:
    let entry = map.entries[i]
    let age = currentStep - entry.lastSeen
    if age >= ThreatDecaySteps:
      continue
    let dist = chebyshevDist(pos, entry.pos)
    if dist <= rangeVal:
      result.add entry

proc getTotalThreatStrength*(
  controller: Controller,
  teamId: int,
  pos: IVec2,
  rangeVal: int32,
  currentStep: int32
): int32 =
  ## Get the total threat strength within range of a position.
  result = 0
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  let map = addr controller.threatMaps[teamId]
  for i in 0 ..< map.count:
    let entry = map.entries[i]
    let age = currentStep - entry.lastSeen
    if age >= ThreatDecaySteps:
      continue
    let dist = chebyshevDist(pos, entry.pos)
    if dist <= rangeVal:
      result += entry.strength

proc hasKnownThreats*(controller: Controller, teamId: int, currentStep: int32): bool =
  ## Return true when a team still has non-stale threats.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  let map = addr controller.threatMaps[teamId]
  for i in 0 ..< map.count:
    let age = currentStep - map.entries[i].lastSeen
    if age < ThreatDecaySteps:
      return true
  false

proc clearThreatMap*(controller: Controller, teamId: int) =
  ## Clear all threats for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  controller.threatMaps[teamId].count = 0
  controller.threatMaps[teamId].lastUpdateStep = 0

proc updateThreatMapFromVision*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  currentStep: int32
) =
  ## Update threat and revealed maps from the agent's current vision.
  let teamId = getTeamId(agent)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return

  let visionRange = if agent.unitClass == UnitScout:
    ScoutVisionRange
  else:
    ThreatVisionRange

  let agentId = agent.agentId
  if agentId >= 0 and agentId < MapAgents:
    let lastPos = controller.fogLastRevealPos[agentId]
    let lastStep = controller.fogLastRevealStep[agentId]
    if lastPos != agent.pos or lastStep <= 0:
      env.updateRevealedMapFromVision(agent)
      controller.fogLastRevealPos[agentId] = agent.pos
      controller.fogLastRevealStep[agentId] = currentStep
  else:
    env.updateRevealedMapFromVision(agent)

  let (cx, cy) = cellCoords(agent.pos)
  let vr = visionRange.int
  let teamMask = getTeamMask(teamId)
  let cellRadius = distToCellRadius16(
    min(vr, max(SpatialCellsX, SpatialCellsY) * SpatialCellSize)
  )
  for ddx in -cellRadius .. cellRadius:
    for ddy in -cellRadius .. cellRadius:
      let nx = cx + ddx
      let ny = cy + ddy
      if nx < 0 or nx >= SpatialCellsX or ny < 0 or ny >= SpatialCellsY:
        continue
      for other in env.spatialIndex.kindCells[Agent][nx][ny]:
        if other.isNil or not isAgentAlive(env, other):
          continue
        let otherMask = getTeamMask(other)
        if (otherMask and teamMask) != 0 or otherMask == NoTeamMask:
          continue
        if chebyshevDist(agent.pos, other.pos) <= visionRange:
          let strength: int32 = case other.unitClass
            of UnitKnight, UnitCavalier: 3
            of UnitPaladin: 4
            of UnitManAtArms, UnitLongSwordsman, UnitArcher, UnitCrossbowman: 2
            of UnitChampion, UnitArbalester: 3
            of UnitScout, UnitLightCavalry: 1
            of UnitHussar: 2
            of UnitMangonel: 4
            of UnitTrebuchet: 5
            else: 1
          controller.reportThreat(teamId, other.pos, strength, currentStep,
                                  agentId = other.agentId.int32, isStructure = false)
      for thing in env.spatialIndex.cells[nx][ny].things:
        if thing.isNil or not isBuildingKind(thing.kind):
          continue
        let thingMask = getTeamMask(thing.teamId)
        if thingMask == NoTeamMask or (thingMask and teamMask) != 0:
          continue
        if chebyshevDist(agent.pos, thing.pos) <= visionRange:
          let strength: int32 = case thing.kind
            of Castle: 5
            of GuardTower: 3
            of Barracks, ArcheryRange, Stable: 2
            else: 1
          controller.reportThreat(teamId, thing.pos, strength, currentStep,
                                  agentId = -1, isStructure = true)

proc updateClosestSeen*(
  state: var AgentState,
  basePos: IVec2,
  candidate: IVec2,
  current: var IVec2
) =
  if candidate.x < 0:
    return
  if current.x < 0:
    current = candidate
    return
  if chebyshevDist(candidate, basePos) < chebyshevDist(current, basePos):
    current = candidate

proc clampToPlayable*(pos: IVec2): IVec2 {.inline.} =
  ## Keep positions inside the playable area (inside border walls).
  result.x = min(MapWidth - MapBorder - 1, max(MapBorder, pos.x))
  result.y = min(MapHeight - MapBorder - 1, max(MapBorder, pos.y))

proc getNextSpiralPoint*(state: var AgentState): IVec2 =
  ## Advance the spiral one step using incremental state.
  var direction = state.spiralArcsCompleted mod 4
  if not state.spiralClockwise:
    case direction
    of 1: direction = 3
    of 3: direction = 1
    else: discard
  let delta = case direction
    of 0: ivec2(0, -1)
    of 1: ivec2(1, 0)
    of 2: ivec2(0, 1)
    else: ivec2(-1, 0)

  state.lastSearchPosition = clampToPlayable(state.lastSearchPosition + delta)
  state.spiralStepsInArc += 1
  if state.spiralStepsInArc > (state.spiralArcsCompleted div 2) + 1:
    state.spiralArcsCompleted += 1
    state.spiralStepsInArc = 1
    if state.spiralArcsCompleted > 100:
      state.spiralArcsCompleted = 0
      state.spiralStepsInArc = 1
      state.basePosition = state.lastSearchPosition
  state.lastSearchPosition

proc findNearestThing*(env: Environment, pos: IVec2, kind: ThingKind,
                      maxDist: int = SearchRadius): Thing =
  ## Find the nearest thing of a kind with the spatial index.
  findNearestThingSpatial(env, pos, kind, maxDist)

proc radiusBounds*(center: IVec2, radius: int): tuple[startX, endX, startY, endY: int] {.inline.} =
  (max(0, center.x.int - radius), min(MapWidth - 1, center.x.int + radius),
   max(0, center.y.int - radius), min(MapHeight - 1, center.y.int + radius))

proc findNearestWater*(env: Environment, pos: IVec2): IVec2 =
  result = ivec2(-1, -1)
  let (startX, endX, startY, endY) = radiusBounds(pos, SearchRadius)
  var minDist = int.high
  for x in startX .. endX:
    for y in startY .. endY:
      let dist = abs(x - pos.x.int) + abs(y - pos.y.int)
      if dist >= SearchRadius or dist >= minDist:
        continue
      if env.terrain[x][y] != Water:
        continue
      let candidate = ivec2(x.int32, y.int32)
      if isTileFrozen(candidate, env):
        continue
      minDist = dist
      result = candidate

proc findNearestFriendlyThing*(env: Environment, pos: IVec2, teamId: int, kind: ThingKind): Thing =
  ## Find the nearest friendly thing of a kind with the spatial index.
  findNearestFriendlyThingSpatial(env, pos, teamId, kind, SearchRadius)

proc findNearestThingSpiral*(env: Environment, state: var AgentState, kind: ThingKind): Thing =
  ## Find the nearest thing with cached and spiral-search fallbacks.
  template cacheAndReturn(thing: Thing) =
    state.cachedThingPos[kind] = thing.pos
    state.cachedThingStep[kind] = env.currentStep
    return thing

  let cachedPos = state.cachedThingPos[kind]
  if cachedPos.x >= 0:
    if env.currentStep - state.cachedThingStep[kind] < CacheMaxAge and
        abs(cachedPos.x - state.lastSearchPosition.x) +
        abs(cachedPos.y - state.lastSearchPosition.y) < 30:
      var cachedThing = env.getThing(cachedPos)
      if cachedThing.isNil:
        cachedThing = env.getBackgroundThing(cachedPos)
      if not isNil(cachedThing) and cachedThing.kind == kind and
         hasHarvestableResource(cachedThing):
        return cachedThing
    state.cachedThingPos[kind] = ivec2(-1, -1)

  result = findNearestThing(env, state.lastSearchPosition, kind)
  if not isNil(result): cacheAndReturn(result)
  result = findNearestThing(env, state.basePosition, kind)
  if not isNil(result): cacheAndReturn(result)

  for _ in 0 ..< SpiralAdvanceSteps:
    discard getNextSpiralPoint(state)
  result = findNearestThing(env, state.lastSearchPosition, kind)
  if not isNil(result): cacheAndReturn(result)

proc findNearestWaterSpiral*(env: Environment, state: var AgentState): IVec2 =
  template cacheAndReturn(pos: IVec2) =
    state.cachedWaterPos = pos
    state.cachedWaterStep = env.currentStep
    return pos

  let cachedPos = state.cachedWaterPos
  if cachedPos.x >= 0:
    if env.currentStep - state.cachedWaterStep < CacheMaxAge and
        abs(cachedPos.x - state.lastSearchPosition.x) +
        abs(cachedPos.y - state.lastSearchPosition.y) < 30:
      if env.terrain[cachedPos.x][cachedPos.y] == Water and not isTileFrozen(cachedPos, env):
        return cachedPos
    state.cachedWaterPos = ivec2(-1, -1)

  result = findNearestWater(env, state.lastSearchPosition)
  if result.x >= 0: cacheAndReturn(result)
  result = findNearestWater(env, state.basePosition)
  if result.x >= 0: cacheAndReturn(result)

  for _ in 0 ..< SpiralAdvanceSteps:
    discard getNextSpiralPoint(state)
  result = findNearestWater(env, state.lastSearchPosition)
  if result.x >= 0: cacheAndReturn(result)

proc findNearestFriendlyThingSpiral*(env: Environment, state: var AgentState, teamId: int,
                                    kind: ThingKind): Thing =
  ## Find the nearest team-owned thing with spiral search fallback.
  result = findNearestFriendlyThing(env, state.lastSearchPosition, teamId, kind)
  if not isNil(result):
    return result

  result = findNearestFriendlyThing(env, state.basePosition, teamId, kind)
  if not isNil(result):
    return result

  var nextSearchPos = state.lastSearchPosition
  for _ in 0 ..< SpiralAdvanceSteps:
    nextSearchPos = getNextSpiralPoint(state)
  result = findNearestFriendlyThing(env, nextSearchPos, teamId, kind)
  return result

template forNearbyCells*(center: IVec2, radius: int, body: untyped) =
  ## Iterate over nearby cells within Chebyshev distance `radius`.
  let cx {.inject.} = center.x.int
  let cy {.inject.} = center.y.int
  let startX {.inject.} = max(0, cx - radius)
  let endX {.inject.} = min(MapWidth - 1, cx + radius)
  let startY {.inject.} = max(0, cy - radius)
  let endY {.inject.} = min(MapHeight - 1, cy + radius)
  for x {.inject.} in startX..endX:
    for y {.inject.} in startY..endY:
      if max(abs(x - cx), abs(y - cy)) > radius:
        continue
      body

proc countNearbyTerrain*(env: Environment, center: IVec2, radius: int,
                         allowed: set[TerrainType]): int =
  forNearbyCells(center, radius):
    if env.terrain[x][y] in allowed:
      inc result

proc countNearbyThings*(env: Environment, center: IVec2, radius: int,
                        allowed: set[ThingKind]): int =
  forNearbyCells(center, radius):
    let occ = env.grid[x][y]
    if not isNil(occ) and occ.kind in allowed:
      inc result

proc nearestFriendlyBuildingDistance*(env: Environment, teamId: int,
                                      kinds: openArray[ThingKind], pos: IVec2): int =
  ## Return the distance to the nearest friendly building in `kinds`.
  result = int.high
  for kind in kinds:
    let nearest = findNearestFriendlyThingSpatial(env, pos, teamId, kind, result)
    if not nearest.isNil:
      result = min(result, int(chebyshevDist(nearest.pos, pos)))

proc getBuildingCount*(
  controller: Controller,
  env: Environment,
  teamId: int,
  kind: ThingKind
): int =
  if controller.buildingCountsStep != env.currentStep:
    controller.buildingCountsStep = env.currentStep
    controller.buildingCounts = default(array[MapRoomObjectsTeams, array[ThingKind, int]])
    controller.claimedBuildings = default(array[MapRoomObjectsTeams, set[ThingKind]])
    for bKind in TeamBuildingKinds:
      for thing in env.thingsByKind[bKind]:
        if thing.teamId < 0 or thing.teamId >= MapRoomObjectsTeams:
          continue
        controller.buildingCounts[thing.teamId][thing.kind] += 1
  controller.buildingCounts[teamId][kind]

proc isBuildingClaimed*(controller: Controller, teamId: int, kind: ThingKind): bool =
  ## Check if a building type is claimed by another builder this step.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  kind in controller.claimedBuildings[teamId]

proc claimBuilding*(controller: Controller, teamId: int, kind: ThingKind) =
  ## Claim a building type so other builders don't try to build the same thing.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  controller.claimedBuildings[teamId].incl(kind)

proc getBuildingCountNear*(env: Environment, teamId: int, kind: ThingKind,
                          center: IVec2, radius: int32 = SettlementRadius): int =
  ## Count team buildings of one type near a settlement center.
  for thing in env.thingsByKind[kind]:
    if thing.teamId != teamId:
      continue
    if chebyshevDist(center, thing.pos) <= radius:
      inc result

proc anyMissingBuildingNear*(env: Environment, teamId: int,
                             kinds: openArray[ThingKind],
                             center: IVec2, radius: int32 = SettlementRadius): bool =
  ## Check if any of the given building types are missing near a settlement center.
  for kind in kinds:
    if getBuildingCountNear(env, teamId, kind, center, radius) == 0:
      return true
  false

proc getTotalBuildingCountNear*(env: Environment, teamId: int,
                                center: IVec2, radius: int32 = SettlementRadius): int =
  ## Count total buildings for a team within Chebyshev distance of a settlement center.
  for bKind in TeamBuildingKinds:
    for thing in env.thingsByKind[bKind]:
      if thing.teamId != teamId:
        continue
      if chebyshevDist(center, thing.pos) <= radius:
        inc result

proc canAffordBuild*(env: Environment, agent: Thing, key: ItemKey): bool =
  let costs = buildCostsForKey(key)
  choosePayment(env, agent, costs) != PayNone


proc neighborDirIndex*(fromPos, toPos: IVec2): int =
  ## Return the orientation index toward an adjacent target.
  vecToOrientation(ivec2(signi(toPos.x - fromPos.x), signi(toPos.y - fromPos.y)))

proc sameTeam*(agentA, agentB: Thing): bool =
  ## Return whether two things share a team mask.
  sameTeamMask(agentA, agentB)

proc getBasePos*(agent: Thing): IVec2 =
  ## Return the agent's home altar position if valid, otherwise the agent's current position.
  if agent.homeAltar.x >= 0: agent.homeAltar else: agent.pos

proc findTeamAltar*(env: Environment, agent: Thing, teamId: int): tuple[pos: IVec2, hearts: int] =
  ## Return the nearest team altar, preferring the agent's home altar.
  if agent.homeAltar.x >= 0:
    let homeAltar = env.getThing(agent.homeAltar)
    if not isNil(homeAltar) and homeAltar.kind == Altar and homeAltar.teamId == teamId:
      return (homeAltar.pos, homeAltar.hearts)
  let nearestAltar = findNearestFriendlyThingSpatial(env, agent.pos, teamId, Altar, 1000)
  if not nearestAltar.isNil:
    return (nearestAltar.pos, nearestAltar.hearts)
  (ivec2(-1, -1), 0)

proc findAttackOpportunity*(env: Environment, agent: Thing, ignoreStance: bool = false): int =
  ## Return the best in-range attack direction, or `-1`.
  if agent.unitClass == UnitMonk:
    return -1
  if not ignoreStance and not stanceAllowsAutoAttack(env, agent):
    return -1

  let maxRange = case agent.unitClass
    of UnitArcher, UnitCrossbowman, UnitArbalester: ArcherBaseRange
    of UnitMangonel: MangonelAoELength
    of UnitTrebuchet:
      if agent.packed: 0 else: TrebuchetBaseRange
    else:
      if agent.inventorySpear > 0: 2 else: 1

  if maxRange <= 0:
    return -1

  proc targetPriority(kind: ThingKind): int =
    if agent.unitClass in {UnitMangonel, UnitBatteringRam, UnitTrebuchet}:
      if kind in AttackableStructures:
        return 0
      case kind
      of Tumor: 1
      of Spawner: 2
      of Agent: 3
      else: 4
    else:
      case kind
      of Tumor: 0
      of Spawner: 1
      of Agent: 2
      else:
        if kind in AttackableStructures: 3 else: 4

  let agentTeamId = getTeamId(agent)
  var bestDir = -1
  var bestDist = int.high
  var bestPriority = int.high

  template tryTarget(thing: Thing, dirI: int, stepDist: int) =
    ## Check if thing is a valid attack target and update best if higher priority.
    let isEnemy = case thing.kind
      of Agent: isAgentAlive(env, thing) and not sameTeam(agent, thing)
      of Tumor, Spawner: true
      else: thing.kind in AttackableStructures and thing.teamId != agentTeamId
    if isEnemy:
      let priority = targetPriority(thing.kind)
      if priority < bestPriority or (priority == bestPriority and stepDist < bestDist):
        bestPriority = priority
        bestDist = stepDist
        bestDir = dirI

  for dirIdx in 0 .. 7:
    let d = Directions8[dirIdx]
    for step in 1 .. maxRange:
      let tx = agent.pos.x + d.x * step
      let ty = agent.pos.y + d.y * step
      if tx < 0 or tx >= MapWidth or ty < 0 or ty >= MapHeight:
        break
      let gridThing = env.grid[tx][ty]
      if not gridThing.isNil:
        tryTarget(gridThing, dirIdx, step)
      let bgThing = env.backgroundGrid[tx][ty]
      if not bgThing.isNil and bgThing != gridThing:
        tryTarget(bgThing, dirIdx, step)

  return bestDir

proc isPassable*(env: Environment, agent: Thing, pos: IVec2): bool =
  ## Return true when a tile is statically passable for pathfinding.
  if not isValidPos(pos):
    return false
  if env.isWaterBlockedForAgent(agent, pos):
    return false
  if env.terrain[pos.x][pos.y] == Mountain:
    return false
  if not env.canAgentPassDoor(agent, pos):
    return false
  let occupant = env.grid[pos.x][pos.y]
  if isNil(occupant):
    return true
  return occupant.kind == Lantern

proc canEnterForMove*(env: Environment, agent: Thing, fromPos, toPos: IVec2): bool =
  ## Return true when a one-step move is legal, including lantern pushes.
  if not isValidPos(toPos):
    return false
  if toPos.x < MapBorder.int32 or toPos.x >= (MapWidth - MapBorder).int32 or
      toPos.y < MapBorder.int32 or toPos.y >= (MapHeight - MapBorder).int32:
    return false
  if not env.canTraverseElevation(fromPos, toPos):
    return false
  if env.isWaterBlockedForAgent(agent, toPos):
    return false
  if env.terrain[toPos.x][toPos.y] == Mountain:
    return false
  if not env.canAgentPassDoor(agent, toPos):
    return false
  if env.isEmpty(toPos):
    return true
  let blocker = env.getThing(toPos)
  if isNil(blocker) or blocker.kind != Lantern:
    return false

  template spacingOk(nextPos: IVec2): bool =
    var ok = true
    env.tempTowerTargets.setLen(0)
    collectThingsInRangeSpatial(env, nextPos, Lantern, 2, env.tempTowerTargets)
    for t in env.tempTowerTargets:
      if t != blocker:
        ok = false
        break
    ok

  let delta = toPos - fromPos
  let ahead1 = ivec2(toPos.x + delta.x, toPos.y + delta.y)
  let ahead2 = ivec2(toPos.x + delta.x * 2, toPos.y + delta.y * 2)
  if isValidPos(ahead2) and env.isEmpty(ahead2) and not env.hasDoor(ahead2) and
      not env.isWaterBlockedForAgent(agent, ahead2) and spacingOk(ahead2):
    return true
  if isValidPos(ahead1) and env.isEmpty(ahead1) and not env.hasDoor(ahead1) and
      not env.isWaterBlockedForAgent(agent, ahead1) and spacingOk(ahead1):
    return true

  for dy in -1 .. 1:
    for dx in -1 .. 1:
      if dx == 0 and dy == 0:
        continue
      let alt = ivec2(toPos.x + dx, toPos.y + dy)
      if not isValidPos(alt):
        continue
      if env.isEmpty(alt) and not env.hasDoor(alt) and
          not env.isWaterBlockedForAgent(agent, alt) and spacingOk(alt):
        return true
  return false

proc getMoveTowards*(env: Environment, agent: Thing, fromPos, toPos: IVec2,
                    rng: var Rand, avoidDir: int = -1): int =
  ## Return a greedy one-step direction toward the target, or `-1`.
  let clampedTarget = clampToPlayable(toPos)
  if clampedTarget == fromPos:
    var bestDir = -1
    var bestMargin = -1
    var avoidCandidate = -1
    for dirIdx, delta in Directions8:
      let neighborPos = fromPos + delta
      if not canEnterForMove(env, agent, fromPos, neighborPos):
        continue
      if dirIdx == avoidDir:
        avoidCandidate = dirIdx
        continue
      let marginX = min(neighborPos.x - MapBorder, (MapWidth - MapBorder - 1) - neighborPos.x)
      let marginY = min(neighborPos.y - MapBorder, (MapHeight - MapBorder - 1) - neighborPos.y)
      let margin = min(marginX, marginY)
      if margin > bestMargin:
        bestMargin = margin
        bestDir = dirIdx
    if bestDir >= 0:
      return bestDir
    if avoidCandidate >= 0:
      return avoidCandidate
    return -1

  let dx = clampedTarget.x - fromPos.x
  let dy = clampedTarget.y - fromPos.y
  let stepVector = ivec2(signi(dx), signi(dy))

  if stepVector.x != 0 or stepVector.y != 0:
    let primaryDir = vecToOrientation(stepVector)
    let primaryMove = fromPos + Directions8[primaryDir]
    if primaryDir != avoidDir and canEnterForMove(env, agent, fromPos, primaryMove):
      return primaryDir

  var bestDir = -1
  var bestDist = int.high
  var avoidCandidate = -1
  for dirIdx, delta in Directions8:
    let neighborPos = fromPos + delta
    if not canEnterForMove(env, agent, fromPos, neighborPos):
      continue
    if dirIdx == avoidDir:
      avoidCandidate = dirIdx
      continue
    let dist = int(chebyshevDist(neighborPos, clampedTarget))
    if dist < bestDist:
      bestDist = dist
      bestDir = dirIdx
  if bestDir >= 0:
    return bestDir
  if avoidCandidate >= 0:
    return avoidCandidate
  -1

proc findPath*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  fromPos,
  targetPos: IVec2,
  output: var seq[IVec2]
) =
  ## Run A* from `fromPos` toward `targetPos`.
  ## Returns an empty path when no route is found within the search budget.
  inc controller.pathCache.generation
  let currentGen = controller.pathCache.generation

  controller.pathCache.goalsLen = 0
  if isPassable(env, agent, targetPos):
    controller.pathCache.goals[0] = targetPos
    controller.pathCache.goalsLen = 1
  else:
    for delta in Directions8:
      let candidate = targetPos + delta
      if isValidPos(candidate) and isPassable(env, agent, candidate):
        if controller.pathCache.goalsLen < MaxPathGoals:
          controller.pathCache.goals[controller.pathCache.goalsLen] = candidate
          inc controller.pathCache.goalsLen

  if controller.pathCache.goalsLen == 0:
    output.setLen(0)
    return

  for goalIdx in 0 ..< controller.pathCache.goalsLen:
    if controller.pathCache.goals[goalIdx] == fromPos:
      output.setLen(1)
      output[0] = fromPos
      return

  proc heuristic(cache: PathfindingCache, pos: IVec2): int32 =
    var minDist = int32.high
    for goalIdx in 0 ..< cache.goalsLen:
      let dist = int32(chebyshevDist(pos, cache.goals[goalIdx]))
      if dist < minDist:
        minDist = dist
    minDist

  controller.pathCache.openHeap.clear()
  let startHeuristic = heuristic(controller.pathCache, fromPos)
  controller.pathCache.openHeap.push(PathHeapNode(fScore: startHeuristic, pos: fromPos))

  controller.pathCache.gScoreGen[fromPos.x][fromPos.y] = currentGen
  controller.pathCache.gScoreVal[fromPos.x][fromPos.y] = 0

  var nodesExplored = 0
  const MaxExplorationNodes = 250

  while controller.pathCache.openHeap.len > 0:
    if nodesExplored > MaxExplorationNodes:
      output.setLen(0)
      return

    let node = controller.pathCache.openHeap.pop()
    let currentPos = node.pos

    if controller.pathCache.closedGen[currentPos.x][currentPos.y] == currentGen:
      continue

    controller.pathCache.closedGen[currentPos.x][currentPos.y] = currentGen
    inc nodesExplored

    for goalIdx in 0 ..< controller.pathCache.goalsLen:
      if currentPos == controller.pathCache.goals[goalIdx]:
        controller.pathCache.pathLen = 0
        var tracePos = currentPos
        while true:
          if controller.pathCache.pathLen >= MaxPathLength:
            break
          controller.pathCache.path[controller.pathCache.pathLen] = tracePos
          inc controller.pathCache.pathLen
          if controller.pathCache.cameFromGen[tracePos.x][tracePos.y] != currentGen:
            break
          tracePos = controller.pathCache.cameFromVal[tracePos.x][tracePos.y]

        output.setLen(controller.pathCache.pathLen)
        for pathIdx in 0 ..< controller.pathCache.pathLen:
          output[pathIdx] = controller.pathCache.path[controller.pathCache.pathLen - 1 - pathIdx]
        return

    for dirIdx in 0 .. 7:
      let neighborPos = currentPos + Directions8[dirIdx]
      if not isValidPos(neighborPos):
        continue
      if not canEnterForMove(env, agent, currentPos, neighborPos):
        continue

      if controller.pathCache.closedGen[neighborPos.x][neighborPos.y] == currentGen:
        continue

      let currentGScore = controller.pathCache.gScoreVal[currentPos.x][currentPos.y]
      let tentativeGScore = currentGScore + 1

      let neighborHasScore =
        controller.pathCache.gScoreGen[neighborPos.x][neighborPos.y] == currentGen
      let neighborGScore =
        if neighborHasScore:
          controller.pathCache.gScoreVal[neighborPos.x][neighborPos.y]
        else:
          int32.high

      if tentativeGScore < neighborGScore:
        controller.pathCache.cameFromGen[neighborPos.x][neighborPos.y] = currentGen
        controller.pathCache.cameFromVal[neighborPos.x][neighborPos.y] = currentPos
        controller.pathCache.gScoreGen[neighborPos.x][neighborPos.y] = currentGen
        controller.pathCache.gScoreVal[neighborPos.x][neighborPos.y] = tentativeGScore
        let neighborHeuristic = heuristic(controller.pathCache, neighborPos)
        let fScore = tentativeGScore + neighborHeuristic
        controller.pathCache.openHeap.push(PathHeapNode(fScore: fScore, pos: neighborPos))

  output.setLen(0)

proc hasTeamLanternNear*(env: Environment, teamId: int, pos: IVec2): bool =
  ## Return true when a healthy team lantern is within three tiles.
  env.tempTowerTargets.setLen(0)
  collectThingsInRangeSpatial(env, pos, Lantern, 3, env.tempTowerTargets)
  for thing in env.tempTowerTargets:
    if thing.lanternHealthy and thing.teamId == teamId:
      return true
  false

proc isLanternPlacementValid*(env: Environment, pos: IVec2): bool =
  isValidPos(pos) and env.isEmpty(pos) and
    not env.hasDoor(pos) and
    not isBlockedTerrain(env.terrain[pos.x][pos.y]) and
    not isTileFrozen(pos, env) and
    env.terrain[pos.x][pos.y] != Water

proc tryPlantOnFertile*(controller: Controller, env: Environment, agent: Thing,
                       agentId: int, state: var AgentState): tuple[did: bool, action: uint16] =
  ## If carrying wood/wheat and a fertile tile is nearby, plant; otherwise move toward it.
  if agent.inventoryWheat > 0 or agent.inventoryWood > 0:
    var fertilePos = ivec2(-1, -1)
    var minDist = int.high
    let startX = max(0, agent.pos.x - 8)
    let endX = min(MapWidth - 1, agent.pos.x + 8)
    let startY = max(0, agent.pos.y - 8)
    let endY = min(MapHeight - 1, agent.pos.y + 8)
    let ax = agent.pos.x.int
    let ay = agent.pos.y.int
    block search:
      for x in startX..endX:
        for y in startY..endY:
          if env.terrain[x][y] != TerrainType.Fertile:
            continue
          let candPos = ivec2(x.int32, y.int32)
          if env.isEmpty(candPos) and
              isNil(env.getBackgroundThing(candPos)) and
              not env.hasDoor(candPos):
            let dist = abs(x - ax) + abs(y - ay)
            if dist < minDist:
              minDist = dist
              fertilePos = candPos
              if minDist <= 1:
                break search
    if fertilePos.x >= 0:
      if max(abs(fertilePos.x - agent.pos.x), abs(fertilePos.y - agent.pos.y)) == 1'i32:
        let dirIdx = neighborDirIndex(agent.pos, fertilePos)
        let plantArg = (if agent.inventoryWheat > 0: dirIdx else: dirIdx + 4)
        return (true, saveStateAndReturn(controller, agentId, state,
                 encodeAction(7'u16, plantArg.uint8)))
      else:
        let avoidDir = (if state.blockedMoveSteps > 0: state.blockedMoveDir else: -1)
        let dir = getMoveTowards(env, agent, agent.pos, fertilePos, controller.rng, avoidDir)
        if dir < 0:
          return (false, 0'u16)
        return (true, saveStateAndReturn(controller, agentId, state,
                 encodeAction(1'u16, dir.uint8)))
  return (false, 0'u16)

proc moveNextSearch*(controller: Controller, env: Environment, agent: Thing, agentId: int,
                    state: var AgentState): uint16 =
  let dir = getMoveTowards(
    env, agent, agent.pos, getNextSpiralPoint(state),
    controller.rng, (if state.blockedMoveSteps > 0: state.blockedMoveDir else: -1))
  if dir < 0:
    return saveStateAndReturn(controller, agentId, state, 0'u16)
  return saveStateAndReturn(controller, agentId, state, encodeAction(1'u16, dir.uint8))

proc isAdjacent*(a, b: IVec2): bool =
  let dx = abs(a.x - b.x)
  let dy = abs(a.y - b.y)
  max(dx, dy) == 1'i32

proc actAt*(controller: Controller, env: Environment, agent: Thing, agentId: int,
           state: var AgentState, targetPos: IVec2, verb: uint16,
           argument: int = -1): uint16 =
  return saveStateAndReturn(controller, agentId, state,
    encodeAction(verb,
      (if argument < 0: neighborDirIndex(agent.pos, targetPos) else: argument).uint8))

proc isOscillating*(state: AgentState): bool =
  ## Detect stuck/oscillating movement by checking if the last 6 positions
  ## contain at most 2 unique locations (bouncing between the same tiles).
  if state.recentPosCount < 6:
    return false
  var uniqueCount = 0
  var unique: array[4, IVec2]
  let historyLen = state.recentPositions.len
  for i in 0 ..< 6:
    let idx = (state.recentPosIndex - 1 - i + historyLen * historyLen) mod historyLen
    let p = state.recentPositions[idx]
    var seen = false
    for j in 0 ..< uniqueCount:
      if unique[j] == p:
        seen = true
        break
    if not seen:
      if uniqueCount < unique.len:
        unique[uniqueCount] = p
        inc uniqueCount
      if uniqueCount > 2:
        return false
  uniqueCount <= 2

proc moveTo*(controller: Controller, env: Environment, agent: Thing, agentId: int,
            state: var AgentState, targetPos: IVec2): uint16 =
  ## Move an agent toward `targetPos`.
  ## Uses greedy steps nearby, A*, and spiral fallback when movement gets stuck.
  if state.pathBlockedTarget == targetPos:
    if (env.currentStep mod PathBlockRetryInterval) == 0:
      state.pathBlockedTarget = ivec2(-1, -1)
      state.plannedPath.setLen(0)
    else:
      return controller.moveNextSearch(env, agent, agentId, state)
  let stuck = isOscillating(state)
  if stuck:
    state.pathBlockedTarget = ivec2(-1, -1)
    state.plannedPath.setLen(0)

  template replanPath() =
    findPath(controller, env, agent, agent.pos, targetPos, state.plannedPath)
    state.plannedTarget = targetPos
    state.plannedPathIndex = 0

  let usesAstar = chebyshevDist(agent.pos, targetPos) >= 4 or stuck
  if usesAstar:
    if state.pathBlockedTarget != targetPos or stuck:
      let needsReplan = state.plannedTarget != targetPos or
                        state.plannedPath.len == 0 or stuck
      let driftedOffPath = not needsReplan and
                           state.plannedPathIndex < state.plannedPath.len and
                           state.plannedPath[state.plannedPathIndex] != agent.pos
      if needsReplan or driftedOffPath:
        replanPath()
      if state.plannedPath.len >= 2 and state.plannedPathIndex < state.plannedPath.len - 1:
        let nextPos = state.plannedPath[state.plannedPathIndex + 1]
        if canEnterForMove(env, agent, agent.pos, nextPos):
          var dirIdx = neighborDirIndex(agent.pos, nextPos)
          if state.role == Builder and state.lastPosition == nextPos:
            let altDir = getMoveTowards(env, agent, agent.pos, targetPos, controller.rng, dirIdx)
            if altDir != dirIdx:
              state.plannedPath.setLen(0)
              state.plannedPathIndex = 0
              return saveStateAndReturn(controller, agentId, state,
                encodeAction(1'u16, altDir.uint8))
          state.plannedPathIndex += 1
          return saveStateAndReturn(controller, agentId, state,
            encodeAction(1'u16, dirIdx.uint8))
        findPath(controller, env, agent, agent.pos, targetPos, state.plannedPath)
        state.plannedTarget = targetPos
        state.plannedPathIndex = 0
        if state.plannedPath.len >= 2:
          let recomputedNext = state.plannedPath[1]
          if canEnterForMove(env, agent, agent.pos, recomputedNext):
            let dirIdx = neighborDirIndex(agent.pos, recomputedNext)
            state.plannedPathIndex = 1
            return saveStateAndReturn(controller, agentId, state,
              encodeAction(1'u16, dirIdx.uint8))
        state.plannedPath.setLen(0)
        state.pathBlockedTarget = targetPos
        return controller.moveNextSearch(env, agent, agentId, state)
      elif state.plannedPath.len == 0:
        state.pathBlockedTarget = targetPos
        return controller.moveNextSearch(env, agent, agentId, state)
    else:
      state.plannedPath.setLen(0)
  var dirIdx = getMoveTowards(
    env, agent, agent.pos, targetPos, controller.rng,
    (if state.blockedMoveSteps > 0: state.blockedMoveDir else: -1)
  )
  if dirIdx < 0:
    let attackDir = findAttackOpportunity(env, agent)
    if attackDir >= 0:
      return saveStateAndReturn(controller, agentId, state, encodeAction(2'u16, attackDir.uint8))
    return saveStateAndReturn(controller, agentId, state, 0'u16)
  if state.role == Builder and state.lastPosition == agent.pos + Directions8[dirIdx]:
    let altDir = getMoveTowards(env, agent, agent.pos, targetPos, controller.rng, dirIdx)
    if altDir >= 0 and altDir != dirIdx:
      dirIdx = altDir
  return saveStateAndReturn(controller, agentId, state,
    encodeAction(1'u16, dirIdx.uint8))

proc useAt*(controller: Controller, env: Environment, agent: Thing, agentId: int,
           state: var AgentState, targetPos: IVec2): uint16 =
  actAt(controller, env, agent, agentId, state, targetPos, 3'u16)

proc useOrMoveTo*(controller: Controller, env: Environment, agent: Thing,
                  agentId: int, state: var AgentState, targetPos: IVec2): uint16 =
  ## If adjacent to target, interact (use); otherwise move toward it.
  if isAdjacent(agent.pos, targetPos):
    controller.actAt(env, agent, agentId, state, targetPos, 3'u16)
  else:
    controller.moveTo(env, agent, agentId, state, targetPos)

proc tryMoveToKnownResource*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  pos: var IVec2,
  allowed: set[ThingKind],
  verb: uint16
): tuple[did: bool, action: uint16] =
  if pos.x < 0:
    return (false, 0'u16)
  if pos == state.pathBlockedTarget:
    pos = ivec2(-1, -1)
    return (false, 0'u16)
  let thing = env.getThing(pos)
  if isNil(thing) or thing.kind notin allowed or isThingFrozen(thing, env) or
     not hasHarvestableResource(thing):
    pos = ivec2(-1, -1)
    return (false, 0'u16)
  let teamId = getTeamId(agent)
  if isResourceReserved(teamId, pos, agentId):
    pos = ivec2(-1, -1)
    return (false, 0'u16)
  discard reserveResource(teamId, agentId, pos, env.currentStep)
  return (true, if isAdjacent(agent.pos, pos):
    actAt(controller, env, agent, agentId, state, pos, verb)
  else:
    moveTo(controller, env, agent, agentId, state, pos))

proc moveToNearestSmith*(controller: Controller, env: Environment, agent: Thing, agentId: int,
                        state: var AgentState, teamId: int): tuple[did: bool, action: uint16] =
  let smith = env.findNearestFriendlyThingSpiral(state, teamId, Blacksmith)
  if not isNil(smith):
    return (true, controller.useOrMoveTo(env, agent, agentId, state, smith.pos))
  (false, 0'u16)

proc findDropoffBuilding*(env: Environment, state: var AgentState, teamId: int,
                          res: StockpileResource, rng: var Rand): Thing =
  template tryKind(kind: ThingKind) =
    if isNil(result):
      result = env.findNearestFriendlyThingSpiral(state, teamId, kind)
  case res
  of ResourceFood:
    tryKind(Granary); tryKind(Mill); tryKind(TownCenter)
  of ResourceWood:
    tryKind(LumberCamp); tryKind(TownCenter)
  of ResourceStone:
    tryKind(Quarry); tryKind(TownCenter)
  of ResourceGold:
    tryKind(MiningCamp); tryKind(TownCenter)
  of ResourceWater, ResourceNone:
    discard
  if isNil(result):
    result = findNearestFriendlyThingSpatial(env, state.basePosition, teamId, TownCenter, 1000)

proc dropoffCarrying*(controller: Controller, env: Environment, agent: Thing,
                      agentId: int, state: var AgentState,
                      allowFood: bool = false,
                      allowWood: bool = false,
                      allowStone: bool = false,
                      allowGold: bool = false): tuple[did: bool, action: uint16] =
  ## Drop carried resources at the nearest valid building.
  let teamId = getTeamId(agent)

  template tryDropoff(res: StockpileResource) =
    let dropoff = findDropoffBuilding(env, state, teamId, res, controller.rng)
    if not isNil(dropoff):
      return (true, controller.useOrMoveTo(env, agent, agentId, state, dropoff.pos))

  if allowFood:
    for key, count in agent.inventory.pairs:
      if count > 0 and isFoodItem(key):
        tryDropoff(ResourceFood)
        break

  if allowWood and agent.inventoryWood > 0: tryDropoff(ResourceWood)
  if allowGold and agent.inventoryGold > 0: tryDropoff(ResourceGold)
  if allowStone and agent.inventoryStone > 0: tryDropoff(ResourceStone)

  (false, 0'u16)

proc ensureResourceReserved(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  closestPos: var IVec2,
  allowedKinds: set[ThingKind],
  kinds: openArray[ThingKind],
  patchKind: ResourcePatchKind = PatchFood
): tuple[did: bool, action: uint16] =
  ## Shared resource-gathering with reservation: check cached position, spiral-search
  ## for the nearest resource of the given kinds, reserve it, then use or move to it.
  ## Prefers resources near drop-off buildings (AoE-style clustering).
  let (didKnown, actKnown) = controller.tryMoveToKnownResource(
    env, agent, agentId, state, closestPos, allowedKinds, 3'u16)
  if didKnown: return (didKnown, actKnown)
  let teamId = getTeamId(agent)

  let dropoff = findNearestDropoffForResource(env, agent.pos, teamId, patchKind)
  if not isNil(dropoff):
    let gatherers = countGatherersNearPos(env, teamId, dropoff.pos, PatchRadius)
    if gatherers < MaxGatherersPerPatch:
      for kind in kinds:
        let nearDropoff = findNearestThing(env, dropoff.pos, kind, maxDist = DropoffProximityRadius)
        if isNil(nearDropoff):
          continue
        if nearDropoff.pos == state.pathBlockedTarget:
          continue
        if isResourceReserved(teamId, nearDropoff.pos, agentId):
          continue
        if not hasHarvestableResource(nearDropoff):
          continue
        if isThingFrozen(nearDropoff, env):
          continue
        updateClosestSeen(state, state.basePosition, nearDropoff.pos, closestPos)
        discard reserveResource(teamId, agentId, nearDropoff.pos, env.currentStep)
        return (true, if isAdjacent(agent.pos, nearDropoff.pos):
          controller.useAt(env, agent, agentId, state, nearDropoff.pos)
        else:
          controller.moveTo(env, agent, agentId, state, nearDropoff.pos))

  for kind in kinds:
    let target = env.findNearestThingSpiral(state, kind)
    if isNil(target):
      continue
    if target.pos == state.pathBlockedTarget:
      state.cachedThingPos[kind] = ivec2(-1, -1)
      continue
    if isResourceReserved(teamId, target.pos, agentId):
      continue
    updateClosestSeen(state, state.basePosition, target.pos, closestPos)
    discard reserveResource(teamId, agentId, target.pos, env.currentStep)
    return (true, if isAdjacent(agent.pos, target.pos):
      controller.useAt(env, agent, agentId, state, target.pos)
    else:
      controller.moveTo(env, agent, agentId, state, target.pos))
  (true, controller.moveNextSearch(env, agent, agentId, state))

proc ensureWood*(controller: Controller, env: Environment, agent: Thing, agentId: int,
                state: var AgentState): tuple[did: bool, action: uint16] =
  ensureResourceReserved(controller, env, agent, agentId, state,
    state.closestWoodPos, {Stump, Tree}, [Stump, Tree], PatchWood)

proc ensureStone*(controller: Controller, env: Environment, agent: Thing, agentId: int,
                 state: var AgentState): tuple[did: bool, action: uint16] =
  ensureResourceReserved(controller, env, agent, agentId, state,
    state.closestStonePos, {Stone, Stalagmite}, [Stone, Stalagmite], PatchStone)

proc ensureGold*(controller: Controller, env: Environment, agent: Thing, agentId: int,
                state: var AgentState): tuple[did: bool, action: uint16] =
  ensureResourceReserved(controller, env, agent, agentId, state,
    state.closestGoldPos, {Gold}, [Gold], PatchGold)

proc ensureWater*(controller: Controller, env: Environment, agent: Thing, agentId: int,
                 state: var AgentState): tuple[did: bool, action: uint16] =
  if state.closestWaterPos.x >= 0 and
     (state.closestWaterPos == state.pathBlockedTarget or
      env.terrain[state.closestWaterPos.x][state.closestWaterPos.y] != Water or
      isTileFrozen(state.closestWaterPos, env)):
    state.closestWaterPos = ivec2(-1, -1)
  if state.closestWaterPos.x >= 0:
    return (true, controller.useOrMoveTo(env, agent, agentId, state, state.closestWaterPos))
  let target = findNearestWaterSpiral(env, state)
  if target.x >= 0 and target != state.pathBlockedTarget:
    updateClosestSeen(state, state.basePosition, target, state.closestWaterPos)
    return (true, controller.useOrMoveTo(env, agent, agentId, state, target))
  if target.x >= 0:
    state.cachedWaterPos = ivec2(-1, -1)
  (true, controller.moveNextSearch(env, agent, agentId, state))

proc ensureWheat*(controller: Controller, env: Environment, agent: Thing, agentId: int,
                 state: var AgentState): tuple[did: bool, action: uint16] =
  let teamId = getTeamId(agent)
  for kind in [Wheat, Stubble]:
    let target = env.findNearestThingSpiral(state, kind)
    if isNil(target):
      continue
    if target.pos == state.pathBlockedTarget:
      state.cachedThingPos[kind] = ivec2(-1, -1)
      continue
    if isResourceReserved(teamId, target.pos, agentId):
      continue
    discard reserveResource(teamId, agentId, target.pos, env.currentStep)
    return (true, if isAdjacent(agent.pos, target.pos):
      controller.useAt(env, agent, agentId, state, target.pos)
    else:
      controller.moveTo(env, agent, agentId, state, target.pos))
  (true, controller.moveNextSearch(env, agent, agentId, state))

proc ensureHuntFood*(controller: Controller, env: Environment, agent: Thing, agentId: int,
                    state: var AgentState): tuple[did: bool, action: uint16] =
  let teamId = getTeamId(agent)
  for kind in [Corpse, Cow, Bush, Fish]:
    let target = env.findNearestThingSpiral(state, kind)
    if isNil(target):
      continue
    if target.pos == state.pathBlockedTarget:
      state.cachedThingPos[kind] = ivec2(-1, -1)
      continue
    if isResourceReserved(teamId, target.pos, agentId):
      continue
    updateClosestSeen(state, state.basePosition, target.pos, state.closestFoodPos)
    discard reserveResource(teamId, agentId, target.pos, env.currentStep)
    let verb = if kind == Cow:
      let foodCritical = env.stockpileCount(teamId, ResourceFood) < 3
      let cowHealthy = target.hp * 2 >= target.maxHp
      if cowHealthy and not foodCritical: 3'u16 else: 2'u16
    else:
      3'u16
    return (true, if isAdjacent(agent.pos, target.pos):
      (if verb == 2'u16:
        controller.actAt(env, agent, agentId, state, target.pos, verb)
      else:
        controller.useAt(env, agent, agentId, state, target.pos))
    else:
      controller.moveTo(env, agent, agentId, state, target.pos))
  (true, controller.moveNextSearch(env, agent, agentId, state))

proc setPatrol*(controller: Controller, agentId: int, point1, point2: IVec2) =
  ## Set patrol waypoints for an agent. Enables patrol mode.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].patrolPoint1 = point1
    controller.agents[agentId].patrolPoint2 = point2
    controller.agents[agentId].patrolToSecondPoint = true
    controller.agents[agentId].patrolActive = true

proc clearPatrol*(controller: Controller, agentId: int) =
  ## Disable patrol mode for an agent.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].patrolActive = false
    controller.agents[agentId].patrolPoint1 = ivec2(-1, -1)
    controller.agents[agentId].patrolPoint2 = ivec2(-1, -1)
    controller.agents[agentId].patrolWaypointCount = 0
    controller.agents[agentId].patrolCurrentWaypoint = 0

proc isPatrolActive*(controller: Controller, agentId: int): bool =
  ## Check if patrol mode is active for an agent.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].patrolActive
  false

proc getPatrolTarget*(controller: Controller, agentId: int): IVec2 =
  ## Return the current patrol target waypoint.
  if agentId >= 0 and agentId < MapAgents:
    let state = controller.agents[agentId]
    if state.patrolWaypointCount > 0:
      return state.patrolWaypoints[state.patrolCurrentWaypoint]
    if state.patrolToSecondPoint:
      return state.patrolPoint2
    return state.patrolPoint1
  ivec2(-1, -1)

proc setMultiWaypointPatrol*(controller: Controller, agentId: int, waypoints: openArray[IVec2]) =
  ## Set a multi-waypoint patrol route for an agent.
  if agentId < 0 or agentId >= MapAgents:
    return
  let count = min(waypoints.len, 8)
  if count < 2:
    return
  controller.agents[agentId].patrolWaypointCount = count
  controller.agents[agentId].patrolCurrentWaypoint = 0
  for i in 0 ..< count:
    controller.agents[agentId].patrolWaypoints[i] = waypoints[i]
  controller.agents[agentId].patrolActive = true
  controller.agents[agentId].patrolPoint1 = waypoints[0]
  controller.agents[agentId].patrolPoint2 = waypoints[count - 1]
  controller.agents[agentId].patrolToSecondPoint = true

proc advancePatrolWaypoint*(controller: Controller, agentId: int) =
  ## Advance to the next waypoint in multi-waypoint patrol, wrapping to first.
  if agentId >= 0 and agentId < MapAgents:
    let count = controller.agents[agentId].patrolWaypointCount
    if count > 0:
      controller.agents[agentId].patrolCurrentWaypoint =
        (controller.agents[agentId].patrolCurrentWaypoint + 1) mod count

proc getPatrolWaypointCount*(controller: Controller, agentId: int): int =
  ## Return the number of patrol waypoints for an agent.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].patrolWaypointCount
  0

proc getPatrolCurrentWaypointIndex*(controller: Controller, agentId: int): int =
  ## Get the current waypoint index in multi-waypoint patrol.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].patrolCurrentWaypoint
  0

proc setScoutMode*(controller: Controller, agentId: int, active: bool = true) =
  ## Enable or disable scout mode for an agent.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].scoutActive = active
    if active:
      controller.agents[agentId].scoutExploreRadius = ObservationRadius.int32 + 5
      controller.agents[agentId].scoutLastEnemySeenStep = -100

proc clearScoutMode*(controller: Controller, agentId: int) =
  ## Disable scout mode for an agent.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].scoutActive = false

proc isScoutModeActive*(controller: Controller, agentId: int): bool =
  ## Check if scout mode is active for an agent.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].scoutActive
  false

proc getScoutExploreRadius*(controller: Controller, agentId: int): int32 =
  ## Get the current exploration radius for a scouting agent.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].scoutExploreRadius
  0

proc recordScoutEnemySighting*(controller: Controller, agentId: int, currentStep: int32) =
  ## Record that a scout has seen an enemy.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].scoutLastEnemySeenStep = currentStep

proc setHoldPosition*(controller: Controller, agentId: int, pos: IVec2) =
  ## Set hold position for an agent.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].holdPositionTarget = pos
    controller.agents[agentId].holdPositionActive = true

proc clearHoldPosition*(controller: Controller, agentId: int) =
  ## Disable hold position for an agent.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].holdPositionActive = false
    controller.agents[agentId].holdPositionTarget = ivec2(-1, -1)

proc isHoldPositionActive*(controller: Controller, agentId: int): bool =
  ## Check if hold position is active for an agent.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].holdPositionActive
  false

proc getHoldPosition*(controller: Controller, agentId: int): IVec2 =
  ## Get the hold position target for an agent.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].holdPositionTarget
  ivec2(-1, -1)

proc setFollowTarget*(controller: Controller, agentId: int, targetAgentId: int) =
  ## Set an agent to follow another agent.
  if agentId >= 0 and agentId < MapAgents and
     targetAgentId >= 0 and targetAgentId < MapAgents:
    controller.agents[agentId].followTargetAgentId = targetAgentId
    controller.agents[agentId].followActive = true

proc clearFollowTarget*(controller: Controller, agentId: int) =
  ## Disable follow mode for an agent.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].followActive = false
    controller.agents[agentId].followTargetAgentId = -1

proc isFollowActive*(controller: Controller, agentId: int): bool =
  ## Check if follow mode is active for an agent.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].followActive
  false

proc getFollowTargetId*(controller: Controller, agentId: int): int =
  ## Get the follow target agent ID for an agent.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].followTargetAgentId
  -1

proc setGuardTarget*(controller: Controller, agentId: int, targetAgentId: int) =
  ## Set an agent to guard another agent.
  if agentId >= 0 and agentId < MapAgents and
     targetAgentId >= 0 and targetAgentId < MapAgents:
    controller.agents[agentId].guardTargetAgentId = targetAgentId
    controller.agents[agentId].guardTargetPos = ivec2(-1, -1)
    controller.agents[agentId].guardActive = true

proc setGuardPosition*(controller: Controller, agentId: int, pos: IVec2) =
  ## Set an agent to guard a specific position.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].guardTargetAgentId = -1
    controller.agents[agentId].guardTargetPos = pos
    controller.agents[agentId].guardActive = true

proc clearGuard*(controller: Controller, agentId: int) =
  ## Disable guard mode for an agent.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].guardActive = false
    controller.agents[agentId].guardTargetAgentId = -1
    controller.agents[agentId].guardTargetPos = ivec2(-1, -1)

proc isGuardActive*(controller: Controller, agentId: int): bool =
  ## Check if guard mode is active for an agent.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].guardActive
  false

proc getGuardTargetId*(controller: Controller, agentId: int): int =
  ## Return the guarded agent id, or `-1`.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].guardTargetAgentId
  -1

proc getGuardPosition*(controller: Controller, agentId: int): IVec2 =
  ## Return the guarded position, or `(-1, -1)`.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].guardTargetPos
  ivec2(-1, -1)

const
  StopIdleSteps* = 200

proc stopAgentInternal(controller: Controller, agentId: int) =
  ## Clear active orders, path state, and options without setting stop expiry.
  if agentId >= 0 and agentId < MapAgents:
    clearPatrol(controller, agentId)
    controller.agents[agentId].attackMoveTarget = ivec2(-1, -1)
    clearScoutMode(controller, agentId)
    clearHoldPosition(controller, agentId)
    clearFollowTarget(controller, agentId)
    clearGuard(controller, agentId)
    controller.agents[agentId].plannedPath.setLen(0)
    controller.agents[agentId].plannedPathIndex = 0
    controller.agents[agentId].plannedTarget = ivec2(-1, -1)
    controller.agents[agentId].pathBlockedTarget = ivec2(-1, -1)
    controller.agents[agentId].activeOptionId = -1
    controller.agents[agentId].activeOptionTicks = 0
    controller.agents[agentId].commandQueueCount = 0

proc stopAgentFull*(controller: Controller, agentId: int, currentStep: int32) =
  ## Fully stop an agent and set the idle timeout.
  stopAgentInternal(controller, agentId)
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].stoppedActive = true
    controller.agents[agentId].stoppedUntilStep = currentStep + StopIdleSteps

proc stopAgentDeferred*(controller: Controller, agentId: int) =
  ## Stop an agent before the caller knows the current step.
  stopAgentInternal(controller, agentId)
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].stoppedActive = true
    controller.agents[agentId].stoppedUntilStep = -1

proc clearAgentStop*(controller: Controller, agentId: int) =
  ## Clear the stopped state for an agent, allowing normal behavior to resume.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].stoppedActive = false
    controller.agents[agentId].stoppedUntilStep = 0

proc isAgentStopped*(controller: Controller, agentId: int): bool =
  ## Check if an agent is currently in stopped state.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].stoppedActive
  false

proc getAgentStoppedUntilStep*(controller: Controller, agentId: int): int32 =
  ## Get the step at which the stopped state will expire.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].stoppedUntilStep
  0

proc clearCommandQueue*(controller: Controller, agentId: int) =
  ## Clear all queued commands for an agent.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].commandQueueCount = 0

proc getCommandQueueCount*(controller: Controller, agentId: int): int =
  ## Get the number of commands in an agent's queue.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].commandQueueCount
  0

proc hasQueuedCommands*(controller: Controller, agentId: int): bool =
  ## Check if an agent has commands in the queue.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].commandQueueCount > 0
  false

proc queueCommand*(controller: Controller, agentId: int, cmd: QueuedCommand) =
  ## Add a command to an agent's queue. Returns silently if queue is full.
  if agentId >= 0 and agentId < MapAgents:
    let count = controller.agents[agentId].commandQueueCount
    if count < MaxCommandQueueSize:
      controller.agents[agentId].commandQueue[count] = cmd
      controller.agents[agentId].commandQueueCount = count + 1

proc queuePositionalCommand(controller: Controller, agentId: int,
                            cmdType: QueuedCommandType, targetPos: IVec2) =
  queueCommand(controller, agentId, QueuedCommand(
    cmdType: cmdType,
    targetPos: targetPos,
    targetAgentId: -1
  ))

proc queueAgentCommand(controller: Controller, agentId: int,
                       cmdType: QueuedCommandType, targetAgentId: int) =
  queueCommand(controller, agentId, QueuedCommand(
    cmdType: cmdType,
    targetPos: ivec2(-1, -1),
    targetAgentId: targetAgentId.int32
  ))

proc defaultQueuedCommand(): QueuedCommand {.inline.} =
  QueuedCommand(cmdType: CmdAttackMove, targetPos: ivec2(-1, -1), targetAgentId: -1)

proc queueAttackMove*(controller: Controller, agentId: int, target: IVec2) =
  ## Queue an attack-move command.
  queuePositionalCommand(controller, agentId, CmdAttackMove, target)

proc queuePatrol*(controller: Controller, agentId: int, target: IVec2) =
  ## Queue a patrol command (from current position to target).
  queuePositionalCommand(controller, agentId, CmdPatrol, target)

proc queueFollow*(controller: Controller, agentId: int, targetAgentId: int) =
  ## Queue a follow command.
  queueAgentCommand(controller, agentId, CmdFollow, targetAgentId)

proc queueGuardAgent*(controller: Controller, agentId: int, targetAgentId: int) =
  ## Queue a guard-agent command.
  queueAgentCommand(controller, agentId, CmdGuard, targetAgentId)

proc queueGuardPosition*(controller: Controller, agentId: int, target: IVec2) =
  ## Queue a guard-position command.
  queuePositionalCommand(controller, agentId, CmdGuard, target)

proc queueHoldPosition*(controller: Controller, agentId: int, target: IVec2) =
  ## Queue a hold-position command.
  queuePositionalCommand(controller, agentId, CmdHoldPosition, target)

proc peekNextCommand*(controller: Controller, agentId: int): QueuedCommand =
  ## Return the next queued command without removing it.
  if agentId >= 0 and agentId < MapAgents and
     controller.agents[agentId].commandQueueCount > 0:
    return controller.agents[agentId].commandQueue[0]
  defaultQueuedCommand()

proc popNextCommand*(controller: Controller, agentId: int): QueuedCommand =
  ## Remove and return the next queued command.
  if agentId >= 0 and agentId < MapAgents:
    let count = controller.agents[agentId].commandQueueCount
    if count > 0:
      result = controller.agents[agentId].commandQueue[0]
      for i in 0 ..< count - 1:
        controller.agents[agentId].commandQueue[i] = controller.agents[agentId].commandQueue[i + 1]
      controller.agents[agentId].commandQueueCount = count - 1
      return result
  defaultQueuedCommand()

proc executeQueuedCommand*(controller: Controller, agentId: int, agentPos: IVec2) =
  ## Pop the next command from the queue and execute it.
  if agentId < 0 or agentId >= MapAgents:
    return
  let count = controller.agents[agentId].commandQueueCount
  if count == 0:
    return
  let cmd = popNextCommand(controller, agentId)
  case cmd.cmdType
  of CmdAttackMove:
    controller.agents[agentId].attackMoveTarget = cmd.targetPos
  of CmdPatrol:
    setPatrol(controller, agentId, agentPos, cmd.targetPos)
  of CmdFollow:
    if cmd.targetAgentId >= 0 and cmd.targetAgentId < MapAgents:
      setFollowTarget(controller, agentId, cmd.targetAgentId.int)
  of CmdGuard:
    if cmd.targetAgentId >= 0:
      if cmd.targetAgentId < MapAgents:
        setGuardTarget(controller, agentId, cmd.targetAgentId.int)
    else:
      setGuardPosition(controller, agentId, cmd.targetPos)
  of CmdHoldPosition:
    setHoldPosition(controller, agentId, cmd.targetPos)

proc setAgentStanceDeferred*(controller: Controller, agentId: int, stance: AgentStance) =
  ## Set pending stance for an agent. Applied in decideAction when we have env access.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].pendingStance = stance
    controller.agents[agentId].stanceModified = true

proc getAgentPendingStance*(controller: Controller, agentId: int): AgentStance =
  ## Return the pending stance for an agent.
  if agentId >= 0 and agentId < MapAgents and
     controller.agents[agentId].stanceModified:
    return controller.agents[agentId].pendingStance
  StanceDefensive

proc isAgentStanceModified*(controller: Controller, agentId: int): bool =
  ## Check if agent has a pending stance modification.
  if agentId >= 0 and agentId < MapAgents:
    return controller.agents[agentId].stanceModified
  false

proc clearAgentStanceModified*(controller: Controller, agentId: int) =
  ## Clear the stance modified flag after applying the stance.
  if agentId >= 0 and agentId < MapAgents:
    controller.agents[agentId].stanceModified = false
