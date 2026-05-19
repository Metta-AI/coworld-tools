import
  ai_build_helpers, coordination, options

export ai_build_helpers, options, coordination

const
  CoreInfrastructureKinds = [Granary, LumberCamp, Quarry, MiningCamp]
  TechBuildingKinds = [
    Barracks, Blacksmith, ArcheryRange, Market,
    WeavingLoom, ClayOven, Stable, Monastery,
    Outpost, University, SiegeWorkshop, MangonelWorkshop, TrebuchetWorkshop,
    Castle, Wonder
  ]
  DefenseRequestBuildingKinds = [Barracks, Outpost]
  CampThresholds: array[
    4,
    tuple[kind: ThingKind, nearbyKinds: set[ThingKind], minCount: int]
  ] = [
    (kind: LumberCamp, nearbyKinds: {Tree}, minCount: 6),
    (kind: MiningCamp, nearbyKinds: {Gold}, minCount: 3),
    (kind: Quarry, nearbyKinds: {Stone, Stalagmite}, minCount: 6),
    (kind: Granary, nearbyKinds: {Wheat, Stubble, Bush, Fish}, minCount: 6)
  ]
  StrategicDropoffSearchRadius = 30
  StrategicDropoffMinResources = 5
  StrategicDropoffMinSpacing = 6
  BuilderThreatRadius* = 15
  BuilderFleeRadius* = 8
  BuilderFleeRadiusConst = BuilderFleeRadius

proc calculateWallRingRadius(controller: Controller, env: Environment, teamId: int,
                             altarPos: IVec2): int =
  ## Return the wall ring radius from the local building count.
  var totalBuildings =
    if altarPos.x >= 0:
      getTotalBuildingCountNear(env, teamId, altarPos)
    else:
      0
  if altarPos.x < 0:
    for kind in ThingKind:
      if isBuildingKind(kind):
        totalBuildings += controller.getBuildingCount(env, teamId, kind)
  let extraRadius = totalBuildings div WallRingBuildingsPerRadius
  result = min(WallRingMaxRadius, WallRingBaseRadius + extraRadius)

proc isBuilderUnderThreat*(env: Environment, agent: Thing): bool =
  ## Check whether the builder's home area is under threat.
  let teamId = getTeamId(agent)
  let basePos = agent.getBasePos()
  let nearestEnemy =
    findNearestEnemyAgentSpatial(env, basePos, teamId, BuilderThreatRadius)
  if not nearestEnemy.isNil:
    return true
  not findNearestEnemyBuildingSpatial(env, basePos, teamId, BuilderThreatRadius).isNil

optionGuard(canStartBuilderFlee, shouldTerminateBuilderFlee):
  not isNil(findNearbyEnemyForFlee(env, agent, BuilderFleeRadiusConst))

proc optBuilderFlee(controller: Controller, env: Environment, agent: Thing,
                    agentId: int, state: var AgentState): uint16 =
  ## Flee toward the home altar when enemies are nearby.
  let enemy = findNearbyEnemyForFlee(env, agent, BuilderFleeRadiusConst)
  if isNil(enemy):
    return 0'u16
  fleeToBase(controller, env, agent, agentId, state)

proc refreshDamagedBuildingCache*(controller: Controller, env: Environment) =
  ## Refresh the per-team damaged-building cache for the current step.
  if controller.damagedBuildingCacheStep == env.currentStep:
    return
  controller.damagedBuildingCacheStep = env.currentStep
  for t in 0 ..< MapRoomObjectsTeams:
    controller.damagedBuildingCounts[t] = 0
  for bKind in TeamBuildingKinds:
    for thing in env.thingsByKind[bKind]:
      if thing.teamId < 0 or thing.teamId >= MapRoomObjectsTeams:
        continue
      if thing.maxHp <= 0 or thing.hp >= thing.maxHp:
        continue
      let t = thing.teamId
      if controller.damagedBuildingCounts[t] < MaxDamagedBuildingsPerTeam:
        controller.damagedBuildingPositions[
          t
        ][controller.damagedBuildingCounts[t]] = thing.pos
        controller.damagedBuildingCounts[t] += 1

proc findDamagedBuilding*(
  controller: Controller,
  env: Environment,
  agent: Thing
): Thing =
  ## Find the nearest damaged friendly building that needs repair.
  let teamId = getTeamId(agent)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return nil
  refreshDamagedBuildingCache(controller, env)
  var best: Thing = nil
  var bestDist = int.high
  for i in 0 ..< controller.damagedBuildingCounts[teamId]:
    let pos = controller.damagedBuildingPositions[teamId][i]
    let thing = env.getThing(pos)
    if thing.isNil:
      let bgThing = env.getBackgroundThing(pos)
      if bgThing.isNil:
        continue
      if bgThing.maxHp <= 0 or bgThing.hp >= bgThing.maxHp:
        continue
      let dist = int(chebyshevDist(pos, agent.pos))
      if dist < bestDist:
        bestDist = dist
        best = bgThing
    else:
      if thing.maxHp <= 0 or thing.hp >= thing.maxHp:
        continue
      let dist = int(chebyshevDist(pos, agent.pos))
      if dist < bestDist:
        bestDist = dist
        best = thing
  best

optionGuard(canStartBuilderRepair, shouldTerminateBuilderRepair):
  not isNil(findDamagedBuilding(controller, env, agent))

proc optBuilderRepair(controller: Controller, env: Environment, agent: Thing,
                      agentId: int, state: var AgentState): uint16 =
  ## Move to and repair a damaged friendly building.
  let building = findDamagedBuilding(controller, env, agent)
  if isNil(building):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, building.pos, 3'u16)

proc anyMissingBuilding(controller: Controller, env: Environment, teamId: int,
                        kinds: openArray[ThingKind]): bool =
  ## Return whether any building in the list is still missing.
  for kind in kinds:
    if controller.getBuildingCount(env, teamId, kind) == 0:
      return true
  false

proc buildFirstMissing(controller: Controller, env: Environment, agent: Thing,
                       agentId: int, state: var AgentState, teamId: int,
                       kinds: openArray[ThingKind]): uint16 =
  ## Try to build the first missing building from the list.
  for kind in kinds:
    let (did, act) =
      controller.tryBuildIfMissing(env, agent, agentId, state, teamId, kind)
    if did: return act
  0'u16

optionGuard(canStartBuilderPlantOnFertile, shouldTerminateBuilderPlantOnFertile):
  agent.inventoryWheat > 0 or agent.inventoryWood > 0

proc hasCarryingResources(agent: Thing): bool =
  ## Return true when the builder carries a drop-off resource.
  for key, count in agent.inventory.pairs:
    if count > 0 and (isFoodItem(key) or isStockpileResourceKey(key)):
      return true
  false

optionGuard(canStartBuilderDropoffCarrying, shouldTerminateBuilderDropoffCarrying):
  hasCarryingResources(agent)

proc optBuilderDropoffCarrying(controller: Controller, env: Environment, agent: Thing,
                               agentId: int, state: var AgentState): uint16 =
  ## Drop carried stockpile resources at the nearest valid building.
  let (didDrop, dropAct) = controller.dropoffCarrying(
    env, agent, agentId, state,
    allowFood = true,
    allowWood = true,
    allowStone = true,
    allowGold = true
  )
  if didDrop: return dropAct
  0'u16

optionGuard(canStartBuilderPopCap, shouldTerminateBuilderPopCap):
  needsPopCapHouse(controller, env, getTeamId(agent))

proc optBuilderPopCap(controller: Controller, env: Environment, agent: Thing,
                      agentId: int, state: var AgentState): uint16 =
  ## Build a house when the team is near population cap.
  let teamId = getTeamId(agent)
  let basePos = agent.getBasePos()
  state.basePosition = basePos
  let (didHouse, houseAct) =
    tryBuildHouseForPopCap(controller, env, agent, agentId, state, teamId, basePos)
  if didHouse: return houseAct
  0'u16

optionGuard(
  canStartBuilderCoreInfrastructure,
  shouldTerminateBuilderCoreInfrastructure
):
  let altarPos = agent.homeAltar
  if altarPos.x >= 0:
    anyMissingBuildingNear(env, getTeamId(agent), CoreInfrastructureKinds, altarPos)
  else:
    anyMissingBuilding(controller, env, getTeamId(agent), CoreInfrastructureKinds)

proc optBuilderCoreInfrastructure(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState
): uint16 =
  ## Build missing core infrastructure for the current settlement.
  let teamId = getTeamId(agent)
  let altarPos = agent.homeAltar
  if altarPos.x >= 0:
    for kind in CoreInfrastructureKinds:
      let (did, act) = controller.tryBuildForSettlement(
        env,
        agent,
        agentId,
        state,
        teamId,
        kind,
        altarPos
      )
      if did: return act
    0'u16
  else:
    buildFirstMissing(
      controller,
      env,
      agent,
      agentId,
      state,
      teamId,
      CoreInfrastructureKinds
    )

proc millResourceCount(env: Environment, pos: IVec2): int =
  ## Count nearby wheat resources and fertile tiles for mills.
  countNearbyThings(env, pos, 4, {Wheat, Stubble}) +
    countNearbyTerrain(env, pos, 4, {Fertile})

optionGuard(canStartBuilderMillNearResource, shouldTerminateBuilderMillNearResource):
  let teamId = getTeamId(agent)
  let nearHome = agent.homeAltar.x >= 0 and
    max(
      abs(agent.pos.x - agent.homeAltar.x),
      abs(agent.pos.y - agent.homeAltar.y)
    ) <= 10
  not nearHome and
    millResourceCount(env, agent.pos) >= 8 and
    nearestFriendlyBuildingDistance(
      env,
      teamId,
      [Mill, Granary, TownCenter],
      agent.pos
    ) > 5

proc optBuilderMillNearResource(controller: Controller, env: Environment, agent: Thing,
                                agentId: int, state: var AgentState): uint16 =
  ## Build a mill near a dense local resource patch.
  let teamId = getTeamId(agent)
  let (didMill, actMill) = controller.tryBuildNearResource(
    env, agent, agentId, state, teamId, Mill, millResourceCount(env, agent.pos),
    8, [Mill, Granary, TownCenter], 5)
  if didMill: return actMill
  0'u16

proc canStartBuilderPlantIfMills(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState
): bool =
  ## Start planting when the team already has multiple mills.
  (agent.inventoryWheat > 0 or agent.inventoryWood > 0) and
    controller.getBuildingCount(env, getTeamId(agent), Mill) >= 2

proc shouldTerminateBuilderPlantIfMills(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState
): bool =
  ## Stop planting once the builder runs out of wheat and wood.
  agent.inventoryWheat <= 0 and agent.inventoryWood <= 0

proc optBuilderPlantIfMills(controller: Controller, env: Environment, agent: Thing,
                            agentId: int, state: var AgentState): uint16 =
  ## Plant on fertile ground when the mill economy is established.
  let (didPlant, actPlant) = controller.tryPlantOnFertile(env, agent, agentId, state)
  if didPlant: return actPlant
  0'u16

proc campResourceCount(
  env: Environment,
  pos: IVec2,
  entry: tuple[kind: ThingKind, nearbyKinds: set[ThingKind], minCount: int]
): int =
  ## Count nearby resources for a camp-threshold entry.
  result = countNearbyThings(env, pos, 4, entry.nearbyKinds)
  if entry.kind == Granary:
    result += countNearbyTerrain(env, pos, 4, {Fertile})

optionGuard(canStartBuilderCampThreshold, shouldTerminateBuilderCampThreshold):
  let teamId = getTeamId(agent)
  block:
    var shouldBuild = false
    for entry in CampThresholds:
      let nearbyCount = campResourceCount(env, agent.pos, entry)
      if nearbyCount < entry.minCount:
        continue
      let dist = nearestFriendlyBuildingDistance(env, teamId, [entry.kind], agent.pos)
      if dist > 3:
        shouldBuild = true
        break
    shouldBuild

proc optBuilderCampThreshold(controller: Controller, env: Environment, agent: Thing,
                             agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  for entry in CampThresholds:
    let nearbyCount = campResourceCount(env, agent.pos, entry)
    let (did, act) = controller.tryBuildCampThreshold(
      env, agent, agentId, state, teamId, entry.kind,
      nearbyCount, entry.minCount,
      [entry.kind]
    )
    if did: return act
  0'u16

proc findStrategicDropoffTarget(
  env: Environment,
  agent: Thing
): tuple[pos: IVec2, kind: ThingKind, found: bool] =
  ## Find a distant resource cluster that needs a new drop-off.
  result = (pos: ivec2(-1, -1), kind: LumberCamp, found: false)
  let teamId = getTeamId(agent)
  let basePos = agent.getBasePos()
  var bestScore = 0
  const gridStep = 4
  let minX = max(0, basePos.x - StrategicDropoffSearchRadius)
  let maxX = min(MapWidth - 1, basePos.x + StrategicDropoffSearchRadius)
  let minY = max(0, basePos.y - StrategicDropoffSearchRadius)
  let maxY = min(MapHeight - 1, basePos.y + StrategicDropoffSearchRadius)
  for entry in CampThresholds:
    var x = minX
    while x <= maxX:
      var y = minY
      while y <= maxY:
        let samplePos = ivec2(x.int32, y.int32)
        let resCount = campResourceCount(env, samplePos, entry)
        if resCount >= StrategicDropoffMinResources:
          let dropoffDist =
            nearestFriendlyBuildingDistance(env, teamId, [entry.kind], samplePos)
          if dropoffDist > StrategicDropoffMinSpacing:
            let score = resCount + min(dropoffDist, 20)
            if score > bestScore:
              bestScore = score
              result = (pos: samplePos, kind: entry.kind, found: true)
        y += gridStep
      x += gridStep

var
  strategicDropoffCache: PerAgentCache[
    tuple[pos: IVec2, kind: ThingKind, found: bool]
  ]

optionGuard(canStartBuilderStrategicDropoff, shouldTerminateBuilderStrategicDropoff):
  let teamId = getTeamId(agent)
  (controller.getBuildingCount(env, teamId, Granary) > 0 or
    controller.getBuildingCount(env, teamId, LumberCamp) > 0) and
    strategicDropoffCache.getWithAgent(
      env,
      agent,
      findStrategicDropoffTarget
    ).found

proc optBuilderStrategicDropoff(controller: Controller, env: Environment, agent: Thing,
                                agentId: int, state: var AgentState): uint16 =
  ## Move to a resource cluster and build a drop-off building there.
  let teamId = getTeamId(agent)
  let cached =
    strategicDropoffCache.getWithAgent(
      env,
      agent,
      findStrategicDropoffTarget
    )
  if not cached.found:
    return 0'u16
  let distToCluster = int(chebyshevDist(agent.pos, cached.pos))
  if distToCluster <= 4:
    for entry in CampThresholds:
      if entry.kind == cached.kind:
        let resCount = campResourceCount(env, agent.pos, entry)
        let (did, act) = controller.tryBuildCampThreshold(
          env, agent, agentId, state, teamId, entry.kind,
          resCount, 1,
          [entry.kind],
          minSpacing = StrategicDropoffMinSpacing
        )
        if did: return act
        break
  controller.moveTo(env, agent, agentId, state, cached.pos)

let BuilderStrategicDropoffOption = OptionDef(
  name: "BuilderStrategicDropoff", canStart: canStartBuilderStrategicDropoff,
  shouldTerminate: shouldTerminateBuilderStrategicDropoff,
  act: optBuilderStrategicDropoff,
  interruptible: true
)

optionGuard(canStartBuilderTechBuildings, shouldTerminateBuilderTechBuildings):
  anyMissingBuilding(controller, env, getTeamId(agent), TechBuildingKinds)

proc optBuilderTechBuildings(controller: Controller, env: Environment, agent: Thing,
                             agentId: int, state: var AgentState): uint16 =
  ## Build the first missing technology building.
  let teamId = getTeamId(agent)
  buildFirstMissing(controller, env, agent, agentId, state, teamId, TechBuildingKinds)

optionGuard(canStartBuilderWallRing, shouldTerminateBuilderWallRing):
  let teamId = getTeamId(agent)
  agent.homeAltar.x >= 0 and
    controller.getBuildingCount(env, teamId, LumberCamp) > 0 and
    controller.getBuildingCount(env, teamId, Wall) < MaxWallsPerTeam and
    env.stockpileCount(teamId, ResourceWood) >= 3

proc optBuilderWallRing(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): uint16 =
  ## Build a defensive wall ring around the home altar.
  if not canStartBuilderWallRing(controller, env, agent, agentId, state):
    return 0'u16
  let teamId = getTeamId(agent)
  let altarPos = agent.homeAltar
  var wallTarget = ivec2(-1, -1)
  var doorTarget = ivec2(-1, -1)
  var ringDoorCount = 0
  var bestBlocked = int.high
  var bestDist = int.high
  let baseRadius = calculateWallRingRadius(controller, env, teamId, altarPos)
  let wallRingRadii = [
    baseRadius,
    baseRadius - WallRingRadiusSlack,
    baseRadius + WallRingRadiusSlack
  ]
  for radius in wallRingRadii:
    var blocked = 0
    var doorCount = 0
    var candidateWall = ivec2(-1, -1)
    var candidateDoor = ivec2(-1, -1)
    var candidateWallDist = int.high
    var candidateDoorDist = int.high
    for dx in -radius .. radius:
      for dy in -radius .. radius:
        if max(abs(dx), abs(dy)) != radius:
          continue
        let pos = altarPos + ivec2(dx.int32, dy.int32)
        if not isValidPos(pos):
          inc blocked
          continue
        let posTerrain = env.terrain[pos.x][pos.y]
        if posTerrain == TerrainRoad or isRampTerrain(posTerrain):
          inc blocked
          continue
        let wallThing = env.getThing(pos)
        if not isNil(wallThing) and wallThing.kind == Wall:
          continue
        let doorThing = env.getBackgroundThing(pos)
        if not isNil(doorThing) and doorThing.kind == Door:
          inc doorCount
          continue
        if not env.canPlace(pos):
          inc blocked
          continue
        let dist = int(chebyshevDist(agent.pos, pos))
        let isDoorSlot = (dx == 0 or dy == 0 or abs(dx) == abs(dy))
        if isDoorSlot:
          if dist < candidateDoorDist:
            candidateDoorDist = dist
            candidateDoor = pos
        else:
          if dist < candidateWallDist:
            candidateWallDist = dist
            candidateWall = pos
    let candidateDist = min(candidateWallDist, candidateDoorDist)
    if candidateWall.x < 0 and candidateDoor.x < 0:
      continue
    if blocked < bestBlocked or (blocked == bestBlocked and candidateDist < bestDist):
      bestBlocked = blocked
      bestDist = candidateDist
      wallTarget = candidateWall
      doorTarget = candidateDoor
      ringDoorCount = doorCount
  if wallTarget.x >= 0:
    if env.canAffordBuild(agent, thingItem("Wall")):
      let (did, act) = goToAdjacentAndBuild(
        controller, env, agent, agentId, state, wallTarget, BuildIndexWall
      )
      if did: return act
    else:
      let (didWood, actWood) = controller.ensureWood(env, agent, agentId, state)
      if didWood: return actWood
  if doorTarget.x >= 0:
    if ringDoorCount < WallRingMaxDoors and
        env.canAffordBuild(agent, thingItem("Door")):
      let (didDoor, actDoor) = goToAdjacentAndBuild(
        controller, env, agent, agentId, state, doorTarget, BuildIndexDoor
      )
      if didDoor: return actDoor
    if env.canAffordBuild(agent, thingItem("Wall")):
      let (didWall, actWall) = goToAdjacentAndBuild(
        controller, env, agent, agentId, state, doorTarget, BuildIndexWall
      )
      if didWall: return actWall
    else:
      let (didWood, actWood) = controller.ensureWood(env, agent, agentId, state)
      if didWood: return actWood
  0'u16

proc canStartBuilderDefenseResponse(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState
): bool =
  ## Start when a defense request needs military construction.
  let teamId = getTeamId(agent)
  hasUnfulfilledRequest(teamId, RequestDefense) and
    anyMissingBuilding(controller, env, teamId, DefenseRequestBuildingKinds)

proc shouldTerminateBuilderDefenseResponse(
  controller: Controller,
  env: Environment,
  agent: Thing,
  agentId: int,
  state: var AgentState
): bool =
  ## Stop when no defense request remains or the buildings exist.
  let teamId = getTeamId(agent)
  not hasUnfulfilledRequest(teamId, RequestDefense) or
    not anyMissingBuilding(controller, env, teamId, DefenseRequestBuildingKinds)

proc optBuilderDefenseResponse(controller: Controller, env: Environment, agent: Thing,
                               agentId: int, state: var AgentState): uint16 =
  ## Build military structures for the pending defense request.
  let teamId = getTeamId(agent)
  for kind in DefenseRequestBuildingKinds:
    if controller.getBuildingCount(env, teamId, kind) == 0:
      let (did, act) =
        controller.tryBuildIfMissing(
          env,
          agent,
          agentId,
          state,
          teamId,
          kind
        )
      if did:
        markRequestFulfilled(teamId, RequestDefense)
        return act
  0'u16

optionGuard(canStartBuilderDock, shouldTerminateBuilderDock):
  let checkPos = agent.getBasePos()
  controller.getBuildingCount(env, getTeamId(agent), Dock) == 0 and
    hasWaterNearby(env, checkPos, 20)

proc optBuilderDock(controller: Controller, env: Environment, agent: Thing,
                    agentId: int, state: var AgentState): uint16 =
  ## Build a dock near the base when water access is available.
  let teamId = getTeamId(agent)
  let (did, act) = controller.tryBuildDockIfMissing(env, agent, agentId, state, teamId)
  if did: return act
  0'u16

optionGuard(canStartBuilderNavalTrain, shouldTerminateBuilderNavalTrain):
  agent.unitClass == UnitVillager and
    controller.getBuildingCount(env, getTeamId(agent), Dock) > 0 and
    countTeamNavalAgents(env, getTeamId(agent)) < MaxNavalPerTeam and
    env.canSpendStockpile(getTeamId(agent), buildingTrainCosts(Dock))

proc optBuilderNavalTrain(controller: Controller, env: Environment, agent: Thing,
                          agentId: int, state: var AgentState): uint16 =
  ## Send a builder to the Dock to create one naval unit.
  let teamId = getTeamId(agent)
  let dock = env.findNearestFriendlyThingSpiral(state, teamId, Dock)
  if isNil(dock):
    return 0'u16
  if not dock.productionQueueHasReady() and
     dock.productionQueue.entries.len < ProductionQueueMaxSize:
    discard env.tryBatchQueueTrain(dock, teamId, 1)
  actOrMove(controller, env, agent, agentId, state, dock.pos, 3'u16)

let BuilderNavalTrainOption* = OptionDef(
  name: "BuilderNavalTrain",
  canStart: canStartBuilderNavalTrain,
  shouldTerminate: shouldTerminateBuilderNavalTrain,
  act: optBuilderNavalTrain,
  interruptible: true
)

optionGuard(canStartBuilderSiegeResponse, shouldTerminateBuilderSiegeResponse):
  let teamId = getTeamId(agent)
  hasUnfulfilledRequest(teamId, RequestSiegeBuild) and
    controller.getBuildingCount(env, teamId, SiegeWorkshop) == 0

proc optBuilderSiegeResponse(controller: Controller, env: Environment, agent: Thing,
                             agentId: int, state: var AgentState): uint16 =
  ## Build a siege workshop for the pending coordination request.
  let teamId = getTeamId(agent)
  let (did, act) =
    controller.tryBuildIfMissing(
      env,
      agent,
      agentId,
      state,
      teamId,
      SiegeWorkshop
    )
  if did:
    markRequestFulfilled(teamId, RequestSiegeBuild)
    return act
  0'u16

proc minBasicStockpile(env: Environment, teamId: int): int =
  ## Return the minimum stockpile count among food, wood, and stone.
  result = env.stockpileCount(teamId, ResourceFood)
  let wood = env.stockpileCount(teamId, ResourceWood)
  let stone = env.stockpileCount(teamId, ResourceStone)
  if wood < result: result = wood
  if stone < result: result = stone

optionGuard(canStartBuilderGatherScarce, shouldTerminateBuilderGatherScarce):
  agent.unitClass == UnitVillager and minBasicStockpile(env, getTeamId(agent)) < 5

proc optBuilderGatherScarce(controller: Controller, env: Environment, agent: Thing,
                            agentId: int, state: var AgentState): uint16 =
  ## Gather the scarcest basic resource when stockpiles are low.
  let teamId = getTeamId(agent)
  let food = env.stockpileCount(teamId, ResourceFood)
  let wood = env.stockpileCount(teamId, ResourceWood)
  let stone = env.stockpileCount(teamId, ResourceStone)
  var targetRes = ResourceFood
  var best = food
  if wood < best:
    best = wood
    targetRes = ResourceWood
  if stone < best:
    best = stone
    targetRes = ResourceStone
  if best < 5:
    case targetRes
    of ResourceFood:
      let (didFood, actFood) = controller.ensureWheat(env, agent, agentId, state)
      if didFood: return actFood
    of ResourceWood:
      let (didWood, actWood) = controller.ensureWood(env, agent, agentId, state)
      if didWood: return actWood
    of ResourceStone:
      let (didStone, actStone) = controller.ensureStone(env, agent, agentId, state)
      if didStone: return actStone
    else:
      discard
  0'u16

optionGuard(canStartBuilderVisitTradingHub, shouldTerminateBuilderVisitTradingHub):
  agent.inventory.len == 0 and
    (block:
      let hub = findNearestNeutralHub(env, agent.pos)
      not isNil(hub) and chebyshevDist(agent.pos, hub.pos) > 6'i32)

proc optBuilderVisitTradingHub(controller: Controller, env: Environment, agent: Thing,
                               agentId: int, state: var AgentState): uint16 =
  ## Visit the nearest trading hub when idle and empty-handed.
  let hub = findNearestNeutralHub(env, agent.pos)
  if isNil(hub):
    return 0'u16
  if isAdjacent(agent.pos, hub.pos):
    return 0'u16
  controller.moveTo(env, agent, agentId, state, hub.pos)

let
  BuilderFleeOption = OptionDef(
    name: "BuilderFlee",
    canStart: canStartBuilderFlee,
    shouldTerminate: shouldTerminateBuilderFlee,
    act: optBuilderFlee,
    interruptible: false
  )
  BuilderPlantOnFertileOption = OptionDef(
    name: "BuilderPlantOnFertile",
    canStart: canStartBuilderPlantOnFertile,
    shouldTerminate: shouldTerminateBuilderPlantOnFertile,
    act: optPlantOnFertile,
    interruptible: true
  )
  BuilderWallRingOption = OptionDef(
    name: "BuilderWallRing",
    canStart: canStartBuilderWallRing,
    shouldTerminate: shouldTerminateBuilderWallRing,
    act: optBuilderWallRing,
    interruptible: true
  )
  BuilderDefenseResponseOption = OptionDef(
    name: "BuilderDefenseResponse",
    canStart: canStartBuilderDefenseResponse,
    shouldTerminate: shouldTerminateBuilderDefenseResponse,
    act: optBuilderDefenseResponse,
    interruptible: true
  )
  BuilderSiegeResponseOption = OptionDef(
    name: "BuilderSiegeResponse",
    canStart: canStartBuilderSiegeResponse,
    shouldTerminate: shouldTerminateBuilderSiegeResponse,
    act: optBuilderSiegeResponse,
    interruptible: true
  )
  BuilderRepairOption = OptionDef(
    name: "BuilderRepair",
    canStart: canStartBuilderRepair,
    shouldTerminate: shouldTerminateBuilderRepair,
    act: optBuilderRepair,
    interruptible: true
  )
  BuilderMillNearResourceOption = OptionDef(
    name: "BuilderMillNearResource",
    canStart: canStartBuilderMillNearResource,
    shouldTerminate: shouldTerminateBuilderMillNearResource,
    act: optBuilderMillNearResource,
    interruptible: true
  )
  BuilderPlantIfMillsOption = OptionDef(
    name: "BuilderPlantIfMills",
    canStart: canStartBuilderPlantIfMills,
    shouldTerminate: shouldTerminateBuilderPlantIfMills,
    act: optBuilderPlantIfMills,
    interruptible: true
  )
  BuilderCampThresholdOption = OptionDef(
    name: "BuilderCampThreshold",
    canStart: canStartBuilderCampThreshold,
    shouldTerminate: shouldTerminateBuilderCampThreshold,
    act: optBuilderCampThreshold,
    interruptible: true
  )
  BuilderDockOption = OptionDef(
    name: "BuilderDock",
    canStart: canStartBuilderDock,
    shouldTerminate: shouldTerminateBuilderDock,
    act: optBuilderDock,
    interruptible: true
  )
  BuilderVisitTradingHubOption = OptionDef(
    name: "BuilderVisitTradingHub",
    canStart: canStartBuilderVisitTradingHub,
    shouldTerminate: shouldTerminateBuilderVisitTradingHub,
    act: optBuilderVisitTradingHub,
    interruptible: true
  )
  BuilderOptions* = [
    TownBellGarrisonOption,
    BuilderFleeOption,
    EmergencyHealOption,
    BuilderPlantOnFertileOption,
    OptionDef(
      name: "BuilderDropoffCarrying",
      canStart: canStartBuilderDropoffCarrying,
      shouldTerminate: shouldTerminateBuilderDropoffCarrying,
      act: optBuilderDropoffCarrying,
      interruptible: true
    ),
    OptionDef(
      name: "BuilderPopCap",
      canStart: canStartBuilderPopCap,
      shouldTerminate: shouldTerminateBuilderPopCap,
      act: optBuilderPopCap,
      interruptible: true
    ),
    OptionDef(
      name: "BuilderCoreInfrastructure",
      canStart: canStartBuilderCoreInfrastructure,
      shouldTerminate: shouldTerminateBuilderCoreInfrastructure,
      act: optBuilderCoreInfrastructure,
      interruptible: true
    ),
    BuilderMillNearResourceOption,
    BuilderPlantIfMillsOption,
    BuilderDefenseResponseOption,
    BuilderSiegeResponseOption,
    OptionDef(
      name: "BuilderTechBuildings",
      canStart: canStartBuilderTechBuildings,
      shouldTerminate: shouldTerminateBuilderTechBuildings,
      act: optBuilderTechBuildings,
      interruptible: true
    ),
    BuilderRepairOption,
    BuilderCampThresholdOption,
    BuilderStrategicDropoffOption,
    ResearchUniversityTechOption,
    BuilderDockOption,
    BuilderNavalTrainOption,
    ResearchCastleTechOption,
    ResearchUnitUpgradeOption,
    ResearchBlacksmithUpgradeOption,
    ResearchEconomyTechOption,
    BuilderWallRingOption,
    OptionDef(
      name: "BuilderGatherScarce",
      canStart: canStartBuilderGatherScarce,
      shouldTerminate: shouldTerminateBuilderGatherScarce,
      act: optBuilderGatherScarce,
      interruptible: true
    ),
    MarketTradeOption,
    BuilderVisitTradingHubOption,
    SmeltGoldOption,
    CraftBreadOption,
    StoreValuablesOption,
    FallbackSearchOption
  ]
  BuilderOptionsThreat* = [
    TownBellGarrisonOption,
    BuilderFleeOption,
    EmergencyHealOption,
    BuilderPlantOnFertileOption,
    OptionDef(
      name: "BuilderDropoffCarrying",
      canStart: canStartBuilderDropoffCarrying,
      shouldTerminate: optionsAlwaysTerminate,
      act: optBuilderDropoffCarrying,
      interruptible: true
    ),
    OptionDef(
      name: "BuilderPopCap",
      canStart: canStartBuilderPopCap,
      shouldTerminate: optionsAlwaysTerminate,
      act: optBuilderPopCap,
      interruptible: true
    ),
    BuilderDefenseResponseOption,
    BuilderSiegeResponseOption,
    OptionDef(
      name: "BuilderTechBuildings",
      canStart: canStartBuilderTechBuildings,
      shouldTerminate: optionsAlwaysTerminate,
      act: optBuilderTechBuildings,
      interruptible: true
    ),
    BuilderRepairOption,
    ResearchUniversityTechOption,
    BuilderDockOption,
    BuilderNavalTrainOption,
    ResearchCastleTechOption,
    ResearchUnitUpgradeOption,
    ResearchBlacksmithUpgradeOption,
    ResearchEconomyTechOption,
    OptionDef(
      name: "BuilderCoreInfrastructure",
      canStart: canStartBuilderCoreInfrastructure,
      shouldTerminate: optionsAlwaysTerminate,
      act: optBuilderCoreInfrastructure,
      interruptible: true
    ),
    BuilderMillNearResourceOption,
    BuilderPlantIfMillsOption,
    BuilderCampThresholdOption,
    BuilderStrategicDropoffOption,
    BuilderWallRingOption,
    OptionDef(
      name: "BuilderGatherScarce",
      canStart: canStartBuilderGatherScarce,
      shouldTerminate: optionsAlwaysTerminate,
      act: optBuilderGatherScarce,
      interruptible: true
    ),
    MarketTradeOption,
    BuilderVisitTradingHubOption,
    SmeltGoldOption,
    CraftBreadOption,
    StoreValuablesOption,
    FallbackSearchOption
  ]
