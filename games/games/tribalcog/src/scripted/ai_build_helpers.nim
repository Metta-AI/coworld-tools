import
  ai_core,
  ../constants,
  ../entropy

export ai_core

proc clearBuildState*(state: var AgentState) {.inline.} =
  ## Clear the active build target and lock state.
  state.buildIndex = -1
  state.buildTarget = ivec2(-1, -1)
  state.buildStand = ivec2(-1, -1)
  state.buildLockSteps = 0

proc clearCachedPositions*(state: var AgentState) {.inline.} =
  ## Clear cached resource and thing positions.
  for kind in ThingKind:
    state.cachedThingPos[kind] = ivec2(-1, -1)
  state.closestFoodPos = ivec2(-1, -1)
  state.closestWoodPos = ivec2(-1, -1)
  state.closestStonePos = ivec2(-1, -1)
  state.closestGoldPos = ivec2(-1, -1)
  state.closestMagmaPos = ivec2(-1, -1)

proc canBuilderStandAt(env: Environment, agent: Thing, stand: IVec2,
                       requireDryLand = false): bool {.inline.} =
  ## Return whether a builder may stand on the requested tile.
  isValidPos(stand) and
    (not requireDryLand or env.terrain[stand.x][stand.y] notin WaterTerrain) and
    not env.hasDoor(stand) and
    not isBlockedTerrain(env.terrain[stand.x][stand.y]) and
    not isTileFrozen(stand, env) and
    (env.isEmpty(stand) or stand == agent.pos) and
    env.canAgentPassDoor(agent, stand)

proc defaultBuildAnchor(agent: Thing, state: AgentState): IVec2 {.inline.} =
  ## Return the preferred anchor for local building searches.
  if state.basePosition.x >= 0:
    state.basePosition
  elif agent.homeAltar.x >= 0:
    agent.homeAltar
  else:
    agent.pos

proc claimAndGatherMissingBuildInputs(controller: Controller, env: Environment,
                                      agent: Thing, agentId: int,
                                      state: var AgentState,
                                      teamId: int, kind: ThingKind,
                                      costs: openArray[
                                        tuple[key: ItemKey, count: int]
                                      ]):
                                      tuple[did: bool, action: uint16] =
  ## Claim a building and gather the first missing stockpile resource.
  controller.claimBuilding(teamId, kind)
  for cost in costs:
    case stockpileResourceForItem(cost.key)
    of ResourceWood:
      return controller.ensureWood(env, agent, agentId, state)
    of ResourceStone:
      return controller.ensureStone(env, agent, agentId, state)
    of ResourceGold:
      return controller.ensureGold(env, agent, agentId, state)
    of ResourceFood:
      return controller.ensureWheat(env, agent, agentId, state)
    of ResourceWater, ResourceNone:
      discard
  (false, 0'u16)

proc findNearestBuildSite(env: Environment, agent: Thing, anchor: IVec2,
                          searchRadius: int): tuple[build, stand: IVec2] =
  ## Find the nearest valid build tile and adjacent stand tile.
  result = (build: ivec2(-1, -1), stand: ivec2(-1, -1))
  var bestDist = int.high
  let minX = max(0, anchor.x - searchRadius)
  let maxX = min(MapWidth - 1, anchor.x + searchRadius)
  let minY = max(0, anchor.y - searchRadius)
  let maxY = min(MapHeight - 1, anchor.y + searchRadius)
  let ax = anchor.x.int
  let ay = anchor.y.int
  for x in minX .. maxX:
    for y in minY .. maxY:
      let pos = ivec2(x.int32, y.int32)
      if not env.canPlace(pos) or
          not isBuildableExcludingRoads(env.terrain[pos.x][pos.y]):
        continue
      for d in CardinalOffsets:
        let stand = pos + d
        if canBuilderStandAt(env, agent, stand):
          let dist = abs(x - ax) + abs(y - ay)
          if dist < bestDist:
            bestDist = dist
            result = (build: pos, stand: stand)
          break

proc tryBuildAction*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  index: int
): tuple[did: bool, action: uint16] =
  ## Attempt an immediate build action adjacent to the agent.
  if index < 0 or index >= BuildChoices.len:
    return (false, 0'u16)
  let key = BuildChoices[index]
  if not env.canAffordBuild(agent, key):
    return (false, 0'u16)
  let preferDir = orientationToVec(agent.orientation)
  const cardinalDirs = [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0)]
  const diagonalDirs = [ivec2(1, -1), ivec2(1, 1), ivec2(-1, 1), ivec2(-1, -1)]
  template checkDir(d: IVec2): bool =
    if d.x != 0 or d.y != 0:
      let candidate = agent.pos + d
      if isValidPos(candidate) and env.canPlace(candidate) and
          isBuildableExcludingRoads(env.terrain[candidate.x][candidate.y]):
        true
      else: false
    else: false
  if checkDir(preferDir):
    return (
      true,
      saveStateAndReturn(
        controller,
        agentId,
        state,
        encodeAction(8'u16, index.uint8)
      )
    )
  for d in cardinalDirs:
    if checkDir(d):
      return (
        true,
        saveStateAndReturn(
          controller,
          agentId,
          state,
          encodeAction(8'u16, index.uint8)
        )
      )
  for d in diagonalDirs:
    if checkDir(d):
      return (
        true,
        saveStateAndReturn(
          controller,
          agentId,
          state,
          encodeAction(8'u16, index.uint8)
        )
      )
  (false, 0'u16)

proc goToAdjacentAndBuild*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  targetPos: IVec2,
  buildIndex: int
): tuple[did: bool, action: uint16] =
  ## Move toward a build tile and build when adjacent.
  if targetPos.x < 0:
    return (false, 0'u16)
  if buildIndex < 0 or buildIndex >= BuildChoices.len:
    return (false, 0'u16)
  if state.buildLockSteps > 0 and state.buildIndex != buildIndex:
    clearBuildState(state)
  var target = targetPos
  if state.buildLockSteps > 0 and state.buildIndex == buildIndex and
      state.buildTarget.x >= 0:
    if env.canPlace(state.buildTarget) and
        isBuildableExcludingRoads(
          env.terrain[state.buildTarget.x][state.buildTarget.y]
        ):
      target = state.buildTarget
    dec state.buildLockSteps
    if state.buildLockSteps <= 0:
      clearBuildState(state)
  if not env.canAffordBuild(agent, BuildChoices[buildIndex]):
    return (false, 0'u16)
  if not env.canPlace(target) or
      not isBuildableExcludingRoads(env.terrain[target.x][target.y]):
    return (false, 0'u16)
  if ai_core.chebyshevDist(agent.pos, target) == 1'i32:
    let (did, act) = tryBuildAction(controller, env, agent, agentId, state, buildIndex)
    if did:
      clearBuildState(state)
      return (true, act)
  state.buildTarget = target
  state.buildStand = ivec2(-1, -1)
  state.buildIndex = buildIndex
  if state.buildLockSteps <= 0:
    state.buildLockSteps = 8
  return (true, controller.moveTo(env, agent, agentId, state, target))

proc goToStandAndBuild*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  standPos, targetPos: IVec2,
  buildIndex: int
): tuple[did: bool, action: uint16] =
  ## Move toward a stand tile and build once it is reached.
  if standPos.x < 0:
    return (false, 0'u16)
  if buildIndex < 0 or buildIndex >= BuildChoices.len:
    return (false, 0'u16)
  if state.buildLockSteps > 0 and state.buildIndex != buildIndex:
    clearBuildState(state)
  var stand = standPos
  var target = targetPos
  if state.buildLockSteps > 0 and state.buildIndex == buildIndex and
      state.buildTarget.x >= 0 and
      state.buildStand.x >= 0:
    if env.canPlace(state.buildTarget) and
        isBuildableExcludingRoads(
          env.terrain[state.buildTarget.x][state.buildTarget.y]
        ) and
        canBuilderStandAt(env, agent, state.buildStand):
      target = state.buildTarget
      stand = state.buildStand
    dec state.buildLockSteps
    if state.buildLockSteps <= 0:
      clearBuildState(state)
  if not env.canAffordBuild(agent, BuildChoices[buildIndex]):
    return (false, 0'u16)
  if not env.canPlace(target) or
      not isBuildableExcludingRoads(env.terrain[target.x][target.y]):
    return (false, 0'u16)
  if not canBuilderStandAt(env, agent, stand):
    return (false, 0'u16)
  if agent.pos == stand:
    let (did, act) = tryBuildAction(controller, env, agent, agentId, state, buildIndex)
    if did:
      clearBuildState(state)
      return (true, act)
  state.buildTarget = target
  state.buildStand = stand
  state.buildIndex = buildIndex
  if state.buildLockSteps <= 0:
    let dist = int(ai_core.chebyshevDist(agent.pos, stand))
    state.buildLockSteps = max(8, dist + 4)
  return (true, controller.moveTo(env, agent, agentId, state, stand))

proc tryBuildNearResource*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  teamId: int,
  kind: ThingKind,
  resourceCount, minResource: int,
  nearbyKinds: openArray[ThingKind],
  distanceThreshold: int
): tuple[did: bool, action: uint16] =
  ## Build immediately when nearby resource and spacing allow it.
  if resourceCount < minResource:
    return (false, 0'u16)
  if nearestFriendlyBuildingDistance(
    env,
    teamId,
    nearbyKinds,
    agent.pos
  ) <= distanceThreshold:
    return (false, 0'u16)
  let idx = buildIndexFor(kind)
  if idx >= 0:
    return tryBuildAction(controller, env, agent, agentId, state, idx)
  (false, 0'u16)

proc tryBuildCampThreshold*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  teamId: int,
  kind: ThingKind,
  resourceCount, minResource: int,
  nearbyKinds: openArray[ThingKind],
  minSpacing: int = 3,
  searchRadius: int = 4
): tuple[did: bool, action: uint16] =
  ## Build a camp when the resource threshold and spacing checks pass.
  if resourceCount < minResource:
    return (false, 0'u16)
  let dist = nearestFriendlyBuildingDistance(env, teamId, nearbyKinds, agent.pos)
  if dist <= minSpacing:
    return (false, 0'u16)
  let idx = buildIndexFor(kind)
  if idx < 0 or idx >= BuildChoices.len:
    return (false, 0'u16)
  if not env.canAffordBuild(agent, BuildChoices[idx]):
    return (false, 0'u16)
  block findBuildSpotNear:
    var buildPos = ivec2(-1, -1)
    var standPos = ivec2(-1, -1)
    let minX = max(0, agent.pos.x - searchRadius)
    let maxX = min(MapWidth - 1, agent.pos.x + searchRadius)
    let minY = max(0, agent.pos.y - searchRadius)
    let maxY = min(MapHeight - 1, agent.pos.y + searchRadius)
    for x in minX .. maxX:
      for y in minY .. maxY:
        let pos = ivec2(x.int32, y.int32)
        if not env.canPlace(pos) or
            not isBuildableExcludingRoads(env.terrain[pos.x][pos.y]):
          continue
        for d in CardinalOffsets:
          let stand = pos + d
          if canBuilderStandAt(env, agent, stand):
            buildPos = pos
            standPos = stand
            break
        if buildPos.x >= 0:
          break
      if buildPos.x >= 0:
        break
    if buildPos.x < 0:
      return (false, 0'u16)
    return goToStandAndBuild(
      controller,
      env,
      agent,
      agentId,
      state,
      standPos,
      buildPos,
      idx
    )

proc tryBuildIfMissing*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  teamId: int,
  kind: ThingKind
): tuple[did: bool, action: uint16] =
  ## Build one missing team-wide structure when possible.
  if controller.getBuildingCount(env, teamId, kind) != 0:
    return (false, 0'u16)
  if controller.isBuildingClaimed(teamId, kind):
    return (false, 0'u16)
  let idx = buildIndexFor(kind)
  if idx < 0:
    return (false, 0'u16)
  let key = BuildChoices[idx]
  let costs = buildCostsForKey(key)
  if costs.len == 0:
    return (false, 0'u16)
  if choosePayment(env, agent, costs) == PayNone:
    return claimAndGatherMissingBuildInputs(
      controller,
      env,
      agent,
      agentId,
      state,
      teamId,
      kind,
      costs
    )

  let (didAdjacent, actAdjacent) =
    tryBuildAction(controller, env, agent, agentId, state, idx)
  if didAdjacent:
    controller.claimBuilding(teamId, kind)
    return (didAdjacent, actAdjacent)

  let buildSite =
    findNearestBuildSite(env, agent, defaultBuildAnchor(agent, state), 16)
  if buildSite.build.x >= 0:
    controller.claimBuilding(teamId, kind)
    return goToStandAndBuild(
      controller,
      env,
      agent,
      agentId,
      state,
      buildSite.stand,
      buildSite.build,
      idx
    )
  (false, 0'u16)

proc tryBuildForSettlement*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  teamId: int,
  kind: ThingKind,
  settlementCenter: IVec2
): tuple[did: bool, action: uint16] =
  ## Build one missing settlement-local structure when possible.
  if getBuildingCountNear(env, teamId, kind, settlementCenter) != 0:
    return (false, 0'u16)
  if controller.isBuildingClaimed(teamId, kind):
    return (false, 0'u16)
  let idx = buildIndexFor(kind)
  if idx < 0:
    return (false, 0'u16)
  let key = BuildChoices[idx]
  let costs = buildCostsForKey(key)
  if costs.len == 0:
    return (false, 0'u16)
  if choosePayment(env, agent, costs) == PayNone:
    return claimAndGatherMissingBuildInputs(
      controller,
      env,
      agent,
      agentId,
      state,
      teamId,
      kind,
      costs
    )

  let (didAdjacent, actAdjacent) =
    tryBuildAction(controller, env, agent, agentId, state, idx)
  if didAdjacent:
    controller.claimBuilding(teamId, kind)
    return (didAdjacent, actAdjacent)

  let buildSite = findNearestBuildSite(env, agent, settlementCenter, 16)
  if buildSite.build.x >= 0:
    controller.claimBuilding(teamId, kind)
    return goToStandAndBuild(
      controller,
      env,
      agent,
      agentId,
      state,
      buildSite.stand,
      buildSite.build,
      idx
    )
  (false, 0'u16)

proc tryBuildDockIfMissing*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  teamId: int
): tuple[did: bool, action: uint16] =
  ## Build a missing dock near the base using water placement rules.
  if controller.getBuildingCount(env, teamId, Dock) != 0:
    return (false, 0'u16)
  if controller.isBuildingClaimed(teamId, Dock):
    return (false, 0'u16)
  let idx = buildIndexFor(Dock)
  if idx < 0:
    return (false, 0'u16)
  let key = BuildChoices[idx]
  let costs = buildCostsForKey(key)
  if costs.len == 0:
    return (false, 0'u16)
  if choosePayment(env, agent, costs) == PayNone:
    return claimAndGatherMissingBuildInputs(
      controller,
      env,
      agent,
      agentId,
      state,
      teamId,
      Dock,
      costs
    )

  for d in AdjacentOffsets8:
    let candidate = agent.pos + d
    if isValidPos(candidate) and env.canPlaceDock(candidate):
      controller.claimBuilding(teamId, Dock)
      return (
        true,
        saveStateAndReturn(
          controller,
          agentId,
          state,
          encodeAction(8'u16, idx.uint8)
        )
      )

  let anchor = defaultBuildAnchor(agent, state)

  const searchRadius = 20
  var bestDist = int.high
  var bestStand = ivec2(-1, -1)
  let minX = max(0, anchor.x - searchRadius)
  let maxX = min(MapWidth - 1, anchor.x + searchRadius)
  let minY = max(0, anchor.y - searchRadius)
  let maxY = min(MapHeight - 1, anchor.y + searchRadius)
  let ax = anchor.x.int
  let ay = anchor.y.int
  for x in minX .. maxX:
    for y in minY .. maxY:
      let pos = ivec2(x.int32, y.int32)
      if not env.canPlaceDock(pos):
        continue
      for d in CardinalOffsets:
        let stand = pos + d
        if canBuilderStandAt(env, agent, stand, requireDryLand = true):
          let dist = abs(x - ax) + abs(y - ay)
          if dist < bestDist:
            bestDist = dist
            bestStand = stand
          break
  if bestStand.x >= 0:
    controller.claimBuilding(teamId, Dock)
    if bestStand == agent.pos:
      return (
        true,
        saveStateAndReturn(
          controller,
          agentId,
          state,
          encodeAction(8'u16, idx.uint8)
        )
      )
    return (true, controller.moveTo(env, agent, agentId, state, bestStand))
  (false, 0'u16)

proc getTeamPopCount*(controller: Controller, env: Environment, teamId: int): int =
  ## Get team population count from pre-computed step data.
  if teamId >= 0 and teamId < MapRoomObjectsTeams:
    env.stepTeamPopCounts[teamId]
  else:
    0

proc needsPopCapHouse*(controller: Controller, env: Environment, teamId: int): bool =
  ## Return whether a team needs another house for population cap.
  let popCount = controller.getTeamPopCount(env, teamId)
  let houseCount = controller.getBuildingCount(env, teamId, House)
  let townCenterCount = controller.getBuildingCount(env, teamId, TownCenter)
  let popCap = houseCount * HousePopCap + townCenterCount * TownCenterPopCap
  let hasBase = houseCount > 0 or townCenterCount > 0 or
    controller.getBuildingCount(env, teamId, Altar) > 0
  if popCap >= MapAgentsPerTeam:
    return false
  let hasBarracks = controller.getBuildingCount(env, teamId, Barracks) > 0
  let buffer = if hasBarracks: HousePopCap else: 1
  (popCap > 0 and popCount >= popCap - buffer) or
    (popCap == 0 and hasBase and popCount >= buffer)

proc tryBuildHouseForPopCap*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState,
  teamId: int,
  basePos: IVec2
): tuple[did: bool, action: uint16] =
  ## Build a house when the team is at or near population cap.
  if needsPopCapHouse(controller, env, teamId):
    let minX = max(0, basePos.x - 15)
    let maxX = min(MapWidth - 1, basePos.x + 15)
    let minY = max(0, basePos.y - 15)
    let maxY = min(MapHeight - 1, basePos.y + 15)
    var preferred: seq[tuple[build, stand: IVec2]]
    var fallback: seq[tuple[build, stand: IVec2]]
    for x in minX .. maxX:
      for y in minY .. maxY:
        let pos = ivec2(x.int32, y.int32)
        let dist = ai_core.chebyshevDist(basePos, pos).int
        if dist < 5 or dist > 15:
          continue
        if not env.canPlace(pos) or
            not isBuildableExcludingRoads(env.terrain[pos.x][pos.y]):
          continue
        var standPos = ivec2(-1, -1)
        for d in CardinalOffsets:
          let stand = pos + d
          if canBuilderStandAt(env, agent, stand):
            standPos = stand
            break
        if standPos.x < 0:
          continue
        var adjacentHouses = 0
        for d in AdjacentOffsets8:
          let neighbor = pos + d
          if not isValidPos(neighbor):
            continue
          let occ = env.grid[neighbor.x][neighbor.y]
          if not isNil(occ) and occ.kind == House and occ.teamId == teamId:
            inc adjacentHouses
        var makesLine = false
        for dir in CardinalOffsets:
          var lineCount = 0
          for step in 1 .. 2:
            let neighbor = pos + ivec2(dir.x.int * step, dir.y.int * step)
            if not isValidPos(neighbor):
              break
            let occ = env.grid[neighbor.x][neighbor.y]
            if isNil(occ) or occ.kind != House or occ.teamId != teamId:
              break
            inc lineCount
          for step in 1 .. 2:
            let neighbor = pos - ivec2(dir.x.int * step, dir.y.int * step)
            if not isValidPos(neighbor):
              break
            let occ = env.grid[neighbor.x][neighbor.y]
            if isNil(occ) or occ.kind != House or occ.teamId != teamId:
              break
            inc lineCount
          if lineCount >= 2:
            makesLine = true
            break
        let candidate = (build: pos, stand: standPos)
        if adjacentHouses <= 1 and not makesLine:
          preferred.add(candidate)
        else:
          fallback.add(candidate)
    let candidates = if preferred.len > 0: preferred else: fallback
    if candidates.len > 0:
      let choice = candidates[randIntExclusive(controller.rng, 0, candidates.len)]
      return goToStandAndBuild(
        controller, env, agent, agentId, state,
        choice.stand, choice.build, buildIndexFor(House)
      )
  (false, 0'u16)
