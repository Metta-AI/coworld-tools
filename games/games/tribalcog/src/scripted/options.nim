## Minimal RL-style options: initiation, termination, and per-tick policy step.

import ai_types
export ai_types

import ai_build_helpers
export ai_build_helpers

import ../entropy

# optionGuard template consolidated in ai_types.nim (re-exported via ai_types export)

const ValuableStorageKinds = [Blacksmith, Granary, Barrel]

proc actOrMove*(controller: Controller, env: Environment, agent: Thing,
               agentId: int, state: var AgentState,
               targetPos: IVec2, verb: uint16): uint16 =
  if isAdjacent(agent.pos, targetPos):
    return controller.actAt(env, agent, agentId, state, targetPos, verb)
  controller.moveTo(env, agent, agentId, state, targetPos)

proc nearestFriendlyBuilding(env: Environment, state: var AgentState, teamId: int,
                             kind: ThingKind): Thing {.inline.} =
  env.findNearestFriendlyThingSpiral(state, teamId, kind)

proc nearestReadyFriendlyBuilding(env: Environment, state: var AgentState, teamId: int,
                                  kind: ThingKind): Thing {.inline.} =
  let building = env.nearestFriendlyBuilding(state, teamId, kind)
  if isNil(building) or building.cooldown != 0:
    return nil
  building

proc useNearestFriendlyBuilding(controller: Controller, env: Environment, agent: Thing,
                                agentId: int, state: var AgentState, teamId: int,
                                kind: ThingKind): uint16 {.inline.} =
  let building = env.nearestFriendlyBuilding(state, teamId, kind)
  if isNil(building):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, building.pos, 3'u16)

proc useNearestReadyFriendlyBuilding(controller: Controller, env: Environment, agent: Thing,
                                     agentId: int, state: var AgentState, teamId: int,
                                     kind: ThingKind): uint16 {.inline.} =
  let building = env.nearestReadyFriendlyBuilding(state, teamId, kind)
  if isNil(building):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, building.pos, 3'u16)

proc actAtReadyFriendlyThing*(controller: Controller, env: Environment, agent: Thing,
                              agentId: int, state: var AgentState, teamId: int,
                              kind: ThingKind, verb: uint16): uint16 =
  let building = env.nearestReadyFriendlyBuilding(state, teamId, kind)
  if isNil(building):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, building.pos, verb)

proc hasLiveFollowTarget*(env: Environment, state: AgentState): bool {.inline.} =
  if not state.followActive or state.followTargetAgentId < 0 or
      state.followTargetAgentId >= env.agents.len:
    return false
  isAgentAlive(env, env.agents[state.followTargetAgentId])

proc resolveFollowTarget*(env: Environment, state: var AgentState): Thing {.inline.} =
  if not state.followActive or state.followTargetAgentId < 0:
    return nil
  if state.followTargetAgentId >= env.agents.len:
    state.followActive = false
    return nil
  let target = env.agents[state.followTargetAgentId]
  if not isAgentAlive(env, target):
    state.followActive = false
    state.followTargetAgentId = -1
    return nil
  target

proc maintainFollowProximity*(controller: Controller, env: Environment, agent: Thing,
                              agentId: int, state: var AgentState, target: Thing): uint16 =
  if int(chebyshevDist(agent.pos, target.pos)) > FollowProximityRadius:
    return controller.moveTo(env, agent, agentId, state, target.pos)
  0'u16

proc agentHasAnyItem*(agent: Thing, keys: openArray[ItemKey]): bool =
  for key in keys:
    if getInv(agent, key) > 0:
      return true
  false

proc canStartVillagerBuild(agent: Thing, env: Environment, buildName: string): bool {.inline.} =
  agent.unitClass == UnitVillager and env.canAffordBuild(agent, thingItem(buildName))

optionGuard(canStartCarryLantern, shouldTerminateCarryLantern):
  agent.inventoryLantern > 0

optionGuard(canStartCarryRelic, shouldTerminateCarryRelic):
  agent.inventoryRelic > 0

proc enemyDirectionalBuildTarget(env: Environment, basePos: IVec2, teamId: int,
                                 fallbackOffset: IVec2): IVec2 {.inline.} =
  let enemy = findNearestEnemyBuildingSpatial(env, basePos, teamId)
  if not isNil(enemy): enemy.pos else: basePos + fallbackOffset

optionGuardExported(canStartStoreValuables, shouldTerminateStoreValuables):
  let teamId = getTeamId(agent)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  for kind in ValuableStorageKinds:
    if controller.getBuildingCount(env, teamId, kind) > 0 and
        agentHasAnyItem(agent, buildingStorageItems(kind)):
      return true
  false

proc optStoreValuables*(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  for kind in ValuableStorageKinds:
    if not agentHasAnyItem(agent, buildingStorageItems(kind)):
      continue
    let building = env.nearestFriendlyBuilding(state, teamId, kind)
    if not isNil(building):
      return actOrMove(controller, env, agent, agentId, state, building.pos, 3'u16)
  0'u16

proc canStartCraftBread*(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): bool =
  let teamId = getTeamId(agent)
  agent.inventoryWheat > 0 and agent.inventoryBread < MapObjectAgentMaxInventory and
    controller.getBuildingCount(env, teamId, ClayOven) > 0

proc shouldTerminateCraftBread*(controller: Controller, env: Environment, agent: Thing,
                                agentId: int, state: var AgentState): bool =
  ## Terminate when no wheat to craft or bread inventory is full
  agent.inventoryWheat == 0 or agent.inventoryBread >= MapObjectAgentMaxInventory

proc optCraftBread*(controller: Controller, env: Environment, agent: Thing,
                    agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  controller.useNearestReadyFriendlyBuilding(env, agent, agentId, state, teamId, ClayOven)

proc canStartSmeltGold*(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): bool =
  agent.inventoryGold > 0 and agent.inventoryBar < MapObjectAgentMaxInventory and
    env.thingsByKind[Magma].len > 0

proc shouldTerminateSmeltGold*(controller: Controller, env: Environment, agent: Thing,
                               agentId: int, state: var AgentState): bool =
  ## Terminate when no gold to smelt or bar inventory is full
  agent.inventoryGold == 0 or agent.inventoryBar >= MapObjectAgentMaxInventory

proc optSmeltGold*(controller: Controller, env: Environment, agent: Thing,
                   agentId: int, state: var AgentState): uint16 =
  state.basePosition = agent.getBasePos()
  let (didKnown, actKnown) = controller.tryMoveToKnownResource(
    env, agent, agentId, state, state.closestMagmaPos, {Magma}, 3'u16)
  if didKnown:
    return actKnown
  let magmaGlobal = findNearestThing(env, agent.pos, Magma, maxDist = int.high)
  if isNil(magmaGlobal):
    return 0'u16
  updateClosestSeen(state, state.basePosition, magmaGlobal.pos, state.closestMagmaPos)
  return actOrMove(controller, env, agent, agentId, state, magmaGlobal.pos, 3'u16)

# Shared OptionDef constants for behaviors used across multiple roles
# These can be directly included in role option arrays to reduce duplication
let SmeltGoldOption* = OptionDef(
  name: "SmeltGold",
  canStart: canStartSmeltGold,
  shouldTerminate: shouldTerminateSmeltGold,
  act: optSmeltGold,
  interruptible: true
)

let CraftBreadOption* = OptionDef(
  name: "CraftBread",
  canStart: canStartCraftBread,
  shouldTerminate: shouldTerminateCraftBread,
  act: optCraftBread,
  interruptible: true
)

let StoreValuablesOption* = OptionDef(
  name: "StoreValuables",
  canStart: canStartStoreValuables,
  shouldTerminate: shouldTerminateStoreValuables,
  act: optStoreValuables,
  interruptible: true
)

# EmergencyHeal: eat bread when HP < 50% (high priority survival behavior)
proc canStartEmergencyHeal*(controller: Controller, env: Environment, agent: Thing,
                            agentId: int, state: var AgentState): bool =
  agent.inventoryBread > 0 and agent.hp * 2 < agent.maxHp

proc shouldTerminateEmergencyHeal*(controller: Controller, env: Environment, agent: Thing,
                                   agentId: int, state: var AgentState): bool =
  ## Terminate when HP recovered above 50% or no bread left
  agent.inventoryBread == 0 or agent.hp * 2 >= agent.maxHp

proc optEmergencyHeal*(controller: Controller, env: Environment, agent: Thing,
                       agentId: int, state: var AgentState): uint16 =
  # Find a valid adjacent position to use bread (eating uses the Use action)
  for d in AdjacentOffsets8:
    let target = agent.pos + d
    if not env.hasDoor(target) and
        isValidPos(target) and
        env.isEmpty(target) and
        not isBlockedTerrain(env.terrain[target.x][target.y]) and
        env.canAgentPassDoor(agent, target):
      let dirIdx = neighborDirIndex(agent.pos, target)
      return encodeAction(3'u16, dirIdx.uint8)
  return 0'u16

let EmergencyHealOption* = OptionDef(
  name: "EmergencyHeal",
  canStart: canStartEmergencyHeal,
  shouldTerminate: shouldTerminateEmergencyHeal,
  act: optEmergencyHeal,
  interruptible: true
)

proc findNearestNeutralHub*(env: Environment, pos: IVec2): Thing =
  ## Find nearest neutral hub building (teamId < 0).
  ## Optimized: iterates only hub building kinds via thingsByKind instead of all env.things.
  const NeutralHubKinds = [Castle, Market, Outpost, University, Blacksmith, Barracks,
                           ArcheryRange, Stable, SiegeWorkshop, Monastery, TownCenter,
                           Mill, Granary, LumberCamp, Quarry, MiningCamp, Dock]
  var best: Thing = nil
  var bestDist = int.high
  for kind in NeutralHubKinds:
    for thing in env.thingsByKind[kind]:
      if thing.teamId >= 0:
        continue  # Only neutral buildings
      let dist = int(chebyshevDist(thing.pos, pos))
      if dist < bestDist:
        bestDist = dist
        best = thing
  best

proc findLanternFrontierCandidate(env: Environment, state: var AgentState,
                                  teamId: int, basePos: IVec2): IVec2 =
  var farthest = 0
  for thing in env.thingsByKind[Lantern]:
    if not thing.lanternHealthy or thing.teamId != teamId:
      continue
    let dist = int(chebyshevDist(basePos, thing.pos))
    if dist > farthest:
      farthest = dist
  let desired = max(ObservationRadius + 2, farthest + 3)
  for _ in 0 ..< 24:
    let candidate = getNextSpiralPoint(state)
    if chebyshevDist(candidate, basePos) < desired:
      continue
    if not isLanternPlacementValid(env, candidate):
      continue
    if hasTeamLanternNear(env, teamId, candidate):
      continue
    return candidate
  ivec2(-1, -1)

proc findDirectionalBuildPos(env: Environment, basePos: IVec2, targetPos: IVec2,
                             minStep, maxStep: int): IVec2 =
  if targetPos.x < 0:
    return ivec2(-1, -1)
  let dx = signi(targetPos.x - basePos.x)
  let dy = signi(targetPos.y - basePos.y)
  for step in minStep .. maxStep:
    let pos = basePos + ivec2(dx * step.int32, dy * step.int32)
    if not isValidPos(pos):
      continue
    let posTerrain = env.terrain[pos.x][pos.y]
    if posTerrain == TerrainRoad or isRampTerrain(posTerrain):
      continue
    if env.canPlace(pos):
      return pos
  ivec2(-1, -1)

proc optDirectionalBuild(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState, targetPos: IVec2,
                         minDist, maxDist, buildIndex: int): uint16 =
  let basePos = agent.getBasePos()
  let target = findDirectionalBuildPos(env, basePos, targetPos, minDist, maxDist)
  let (didBuild, buildAct) =
    goToAdjacentAndBuild(controller, env, agent, agentId, state, target, buildIndex)
  if didBuild: return buildAct
  0'u16

proc findIrrigationTarget*(env: Environment, center: IVec2, radius: int): IVec2 =
  let (startX, endX, startY, endY) = radiusBounds(center, radius)
  let cx = center.x.int
  let cy = center.y.int
  var bestDist = int.high
  var bestPos = ivec2(-1, -1)
  for x in startX .. endX:
    for y in startY .. endY:
      if max(abs(x - cx), abs(y - cy)) > radius:
        continue
      if env.terrain[x][y] notin {Empty, Grass, Dune, Sand, Snow}:
        continue
      let pos = ivec2(x.int32, y.int32)
      if not env.isEmpty(pos) or env.hasDoor(pos) or not isNil(env.getBackgroundThing(pos)):
        continue
      if isTileFrozen(pos, env):
        continue
      let dist = abs(x - cx) + abs(y - cy)
      if dist < bestDist:
        bestDist = dist
        bestPos = pos
  bestPos

proc findNearestThingOfKinds(env: Environment, pos: IVec2, kinds: openArray[ThingKind]): Thing =
  var best: Thing = nil
  var bestDist = int.high
  for kind in kinds:
    for thing in env.thingsByKind[kind]:
      let dist = int(chebyshevDist(thing.pos, pos))
      if dist < bestDist:
        bestDist = dist
        best = thing
  best

proc findNearestPredatorInRadius*(env: Environment, pos: IVec2, radius: int): Thing =
  ## Find the nearest wolf or bear within the given radius using spatial index.
  findNearestThingOfKindsSpatial(env, pos, {Wolf, Bear}, radius)

proc findNearestPredator*(env: Environment, pos: IVec2): Thing =
  ## Find the nearest predator (unbounded search).
  findNearestThingOfKinds(env, pos, [Bear, Wolf])

proc findNearbyEnemyForFlee*(env: Environment, agent: Thing, radius: int): Thing =
  ## Find nearest enemy agent within given radius using spatial index.
  ## Shared utility for gatherer/builder/fighter flee behaviors.
  let teamId = getTeamId(agent)
  findNearestEnemyAgentSpatial(env, agent.pos, teamId, radius)

proc fleeToBase*(controller: Controller, env: Environment, agent: Thing,
                 agentId: int, state: var AgentState): uint16 =
  ## Shared flee behavior - move toward home altar for safety.
  ## Used by gatherer and builder flee behaviors.
  let basePos = agent.getBasePos()
  state.basePosition = basePos
  controller.moveTo(env, agent, agentId, state, basePos)

proc fleeAwayFrom*(controller: Controller, env: Environment, agent: Thing,
                   agentId: int, state: var AgentState, threatPos: IVec2): uint16 =
  ## Flee away from a threat position, trying to maximize distance while
  ## moving toward the agent's base for safety.
  ## Returns the best movement action or NOOP if blocked.
  let basePos = agent.getBasePos()
  state.basePosition = basePos

  # Try all directions and pick the one that maximizes distance from threat
  var bestDir = -1
  var bestScore = int.low
  for dirIdx in 0 .. 7:
    let delta = Directions8[dirIdx]
    let newPos = agent.pos + delta
    if not canEnterForMove(env, agent, agent.pos, newPos):
      continue
    # Score: distance from threat + proximity to base
    let distFromThreat = max(abs(newPos.x - threatPos.x), abs(newPos.y - threatPos.y))
    let distToBase = max(abs(newPos.x - basePos.x), abs(newPos.y - basePos.y))
    let score = distFromThreat * 2 - distToBase  # Prioritize getting away from threat
    if score > bestScore:
      bestScore = score
      bestDir = dirIdx

  if bestDir >= 0:
    return saveStateAndReturn(controller, agentId, state, encodeAction(1'u16, bestDir.uint8))

  # If can't move, just noop
  saveStateAndReturn(controller, agentId, state, 0'u16)

proc optFallbackSearch*(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): uint16 =
  ## Shared fallback search behavior - explore when nothing else to do.
  controller.moveNextSearch(env, agent, agentId, state)

let FallbackSearchOption* = OptionDef(
  name: "FallbackSearch",
  canStart: optionsAlwaysCanStart,
  shouldTerminate: optionsAlwaysTerminate,
  act: optFallbackSearch,
  interruptible: true
)

# ============================================================================
# Town Bell Garrison - shared highest-priority option for gatherer/builder
# ============================================================================

const TownBellGarrisonableKinds = {TownCenter, Castle, GuardTower, House}

proc townBellGarrisonCapacity(kind: ThingKind): int =
  ## Garrison capacity lookup (mirrors step.garrisonCapacity for use in AI options).
  case kind
  of TownCenter: TownCenterGarrisonCapacity
  of Castle: CastleGarrisonCapacity
  of GuardTower: GuardTowerGarrisonCapacity
  of House: HouseGarrisonCapacity
  else: 0

proc findNearestGarrisonableBuilding*(env: Environment, pos: IVec2, teamId: int,
                                       maxDist: int): Thing =
  ## Find the nearest friendly garrisonable building with available capacity.
  var best: Thing = nil
  var bestDist = int.high
  for kind in TownBellGarrisonableKinds:
    for building in env.thingsByKind[kind]:
      if building.teamId != teamId or building.hp <= 0:
        continue
      let capacity = townBellGarrisonCapacity(building.kind)
      if building.garrisonedUnits.len >= capacity:
        continue
      let dist = abs(building.pos.x - pos.x) + abs(building.pos.y - pos.y)
      if dist < bestDist and dist <= maxDist:
        bestDist = dist
        best = building
  best

optionGuard(canStartTownBellGarrison, shouldTerminateTownBellGarrison):
  let teamId = getTeamId(agent)
  teamId >= 0 and teamId < MapRoomObjectsTeams and env.townBellActive[teamId]

proc optTownBellGarrison(controller: Controller, env: Environment, agent: Thing,
                          agentId: int, state: var AgentState): uint16 =
  ## When town bell is active, pathfind to nearest garrisonable building.
  ## Garrison happens automatically via actOrMove when adjacent (ActionUse on building).
  let teamId = getTeamId(agent)
  let building = findNearestGarrisonableBuilding(env, agent.pos, teamId, GarrisonSeekRadius)
  if isNil(building):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, building.pos, 3'u16)

let TownBellGarrisonOption* = OptionDef(
  name: "TownBellGarrison",
  canStart: canStartTownBellGarrison,
  shouldTerminate: shouldTerminateTownBellGarrison,
  act: optTownBellGarrison,
  interruptible: false  # Town bell garrison is not interruptible - recall is highest priority
)

proc optPlantOnFertile*(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): uint16 =
  ## Shared act proc for PlantOnFertile behavior - plants seeds on fertile tiles.
  let (didPlant, actPlant) = controller.tryPlantOnFertile(env, agent, agentId, state)
  if didPlant: return actPlant
  0'u16

proc findNearestGoblinStructure*(env: Environment, pos: IVec2): Thing =
  findNearestThingOfKinds(env, pos, [GoblinHive, GoblinHut, GoblinTotem])

proc optLanternFrontierPush(controller: Controller, env: Environment, agent: Thing,
                            agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  let basePos = agent.getBasePos()
  let target = findLanternFrontierCandidate(env, state, teamId, basePos)
  if target.x < 0:
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, target, 6'u16)

proc optLanternGapFill(controller: Controller, env: Environment, agent: Thing,
                       agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  let agentPos = agent.pos
  let altarPos = agent.homeAltar
  # Find lantern gap candidate near agent's settlement
  # When agent has a homeAltar, only consider buildings within settlement radius
  var target = ivec2(-1, -1)
  var bestDist = int.high
  for bKind in TeamBuildingKinds:
    for thing in env.thingsByKind[bKind]:
      if thing.teamId != teamId:
        continue
      # Per-settlement: only fill lantern gaps near this agent's home altar
      if altarPos.x >= 0 and chebyshevDist(altarPos, thing.pos) > SettlementRadius:
        continue
      if hasTeamLanternNear(env, teamId, thing.pos):
        continue
      for dx in -2 .. 2:
        for dy in -2 .. 2:
          if abs(dx) + abs(dy) > 2:
            continue
          let cand = thing.pos + ivec2(dx.int32, dy.int32)
          if not isLanternPlacementValid(env, cand):
            continue
          if hasTeamLanternNear(env, teamId, cand):
            continue
          let dist = abs(cand.x - agentPos.x).int + abs(cand.y - agentPos.y).int
          if dist < bestDist:
            bestDist = dist
            target = cand
  if target.x < 0:
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, target, 6'u16)

proc optLanternRecovery(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  # Find frozen edge candidate (inlined)
  var target = ivec2(-1, -1)
  let radius = 8
  block search:
    for x in max(0, basePos.x.int - radius) .. min(MapWidth - 1, basePos.x.int + radius):
      for y in max(0, basePos.y.int - radius) .. min(MapHeight - 1, basePos.y.int + radius):
        let pos = ivec2(x.int32, y.int32)
        if not isTileFrozen(pos, env):
          continue
        for d in AdjacentOffsets8:
          let cand = pos + d
          if isLanternPlacementValid(env, cand):
            target = cand
            break search
  if target.x < 0:
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, target, 6'u16)

optionGuard(canStartLanternLogistics, shouldTerminateLanternLogistics):
  agent.inventoryLantern == 0 and agent.unitClass == UnitVillager

proc optLanternLogistics(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  let loom = env.nearestFriendlyBuilding(state, teamId, WeavingLoom)
  if agent.inventoryWood > 0 or agent.inventoryWheat > 0:
    if not isNil(loom):
      return actOrMove(controller, env, agent, agentId, state, loom.pos, 3'u16)
  if agent.inventoryWood == 0:
    let (didWood, actWood) = controller.ensureWood(env, agent, agentId, state)
    if didWood: return actWood
  let (didWheat, actWheat) = controller.ensureWheat(env, agent, agentId, state)
  if didWheat: return actWheat
  0'u16

optionGuard(canStartAntiTumorPatrol, shouldTerminateAntiTumorPatrol):
  env.thingsByKind[Tumor].len > 0

proc optAntiTumorPatrol(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): uint16 =
  let tumor = env.findNearestThingSpiral(state, Tumor)
  if isNil(tumor):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, tumor.pos, 2'u16)

let AntiTumorPatrolOption* = OptionDef(
  name: "AntiTumorPatrol",
  canStart: canStartAntiTumorPatrol,
  shouldTerminate: shouldTerminateAntiTumorPatrol,
  act: optAntiTumorPatrol,
  interruptible: true
)

optionGuard(canStartSpawnerHunter, shouldTerminateSpawnerHunter):
  env.thingsByKind[Spawner].len > 0

proc optSpawnerHunter(controller: Controller, env: Environment, agent: Thing,
                      agentId: int, state: var AgentState): uint16 =
  let spawner = env.findNearestThingSpiral(state, Spawner)
  if isNil(spawner):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, spawner.pos, 2'u16)

optionGuard(canStartFrozenEdgeBreaker, shouldTerminateFrozenEdgeBreaker):
  for tumor in env.thingsByKind[Tumor]:
    if isTileFrozen(tumor.pos, env):
      return true
    for d in AdjacentOffsets8:
      if isTileFrozen(tumor.pos + d, env):
        return true
  false

proc optFrozenEdgeBreaker(controller: Controller, env: Environment, agent: Thing,
                          agentId: int, state: var AgentState): uint16 =
  var best: Thing = nil
  var bestDist = int.high
  for tumor in env.thingsByKind[Tumor]:
    var touchesFrozen = isTileFrozen(tumor.pos, env)
    if not touchesFrozen:
      for d in AdjacentOffsets8:
        if isTileFrozen(tumor.pos + d, env):
          touchesFrozen = true
          break
    if not touchesFrozen:
      continue
    let dist = int(chebyshevDist(agent.pos, tumor.pos))
    if dist < bestDist:
      bestDist = dist
      best = tumor
  if isNil(best):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, best.pos, 2'u16)

optionGuard(canStartGuardTowerBorder, shouldTerminateGuardTowerBorder):
  canStartVillagerBuild(agent, env, "GuardTower")
proc optGuardTowerBorder(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  optDirectionalBuild(controller, env, agent, agentId, state,
    enemyDirectionalBuildTarget(env, basePos, getTeamId(agent), ivec2(6, 0)), 4, 7,
    buildIndexFor(GuardTower))

optionGuard(canStartOutpostNetwork, shouldTerminateOutpostNetwork):
  canStartVillagerBuild(agent, env, "Outpost")
proc optOutpostNetwork(controller: Controller, env: Environment, agent: Thing,
                       agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  optDirectionalBuild(controller, env, agent, agentId, state,
    enemyDirectionalBuildTarget(env, basePos, getTeamId(agent), ivec2(0, 6)), 3, 6,
    buildIndexFor(Outpost))

optionGuard(canStartEnemyWallFortify, shouldTerminateEnemyWallFortify):
  if agent.unitClass != UnitVillager:
    return false
  if not env.canAffordBuild(agent, thingItem("Wall")):
    return false
  let basePos = agent.getBasePos()
  let (enemyPos, dist) = findNearestEnemyPresenceSpatial(env, basePos, getTeamId(agent))
  enemyPos.x >= 0 and dist <= EnemyWallFortifyRadius

proc optEnemyWallFortify(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  let (enemyPos, dist) = findNearestEnemyPresenceSpatial(env, basePos, getTeamId(agent))
  if enemyPos.x < 0 or dist > EnemyWallFortifyRadius:
    return 0'u16
  optDirectionalBuild(controller, env, agent, agentId, state, enemyPos, 2, 6, BuildIndexWall)

optionGuard(canStartWallChokeFortify, shouldTerminateWallChokeFortify):
  canStartVillagerBuild(agent, env, "Wall")
proc optWallChokeFortify(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  # Find wall choke candidate (inlined)
  var target = ivec2(-1, -1)
  let radius = 8
  block search:
    for x in max(0, basePos.x.int - radius) .. min(MapWidth - 1, basePos.x.int + radius):
      for y in max(0, basePos.y.int - radius) .. min(MapHeight - 1, basePos.y.int + radius):
        let pos = ivec2(x.int32, y.int32)
        let posTerrain = env.terrain[x][y]
        if posTerrain == TerrainRoad or isRampTerrain(posTerrain):
          continue
        if not env.canPlace(pos):
          continue
        let north = env.getThing(pos + ivec2(0, -1))
        let south = env.getThing(pos + ivec2(0, 1))
        let east = env.getThing(pos + ivec2(1, 0))
        let west = env.getThing(pos + ivec2(-1, 0))
        let northDoor = env.getBackgroundThing(pos + ivec2(0, -1))
        let southDoor = env.getBackgroundThing(pos + ivec2(0, 1))
        let eastDoor = env.getBackgroundThing(pos + ivec2(1, 0))
        let westDoor = env.getBackgroundThing(pos + ivec2(-1, 0))
        let northWall = (not isNil(north) and north.kind == Wall) or
          (not isNil(northDoor) and northDoor.kind == Door)
        let southWall = (not isNil(south) and south.kind == Wall) or
          (not isNil(southDoor) and southDoor.kind == Door)
        let eastWall = (not isNil(east) and east.kind == Wall) or
          (not isNil(eastDoor) and eastDoor.kind == Door)
        let westWall = (not isNil(west) and west.kind == Wall) or
          (not isNil(westDoor) and westDoor.kind == Door)
        if northWall or southWall or eastWall or westWall:
          target = pos
          break search
  let (did, act) = goToAdjacentAndBuild(
    controller, env, agent, agentId, state, target, BuildIndexWall
  )
  if did: return act
  0'u16

optionGuard(canStartDoorChokeFortify, shouldTerminateDoorChokeFortify):
  canStartVillagerBuild(agent, env, "Door")
proc optDoorChokeFortify(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  # Find door choke candidate (inlined)
  var target = ivec2(-1, -1)
  let radius = 8
  block search:
    for x in max(0, basePos.x.int - radius) .. min(MapWidth - 1, basePos.x.int + radius):
      for y in max(0, basePos.y.int - radius) .. min(MapHeight - 1, basePos.y.int + radius):
        let pos = ivec2(x.int32, y.int32)
        let posTerrain = env.terrain[x][y]
        if posTerrain == TerrainRoad or isRampTerrain(posTerrain):
          continue
        if not env.canPlace(pos):
          continue
        let north = env.getThing(pos + ivec2(0, -1))
        let south = env.getThing(pos + ivec2(0, 1))
        let east = env.getThing(pos + ivec2(1, 0))
        let west = env.getThing(pos + ivec2(-1, 0))
        let nsWall = (not isNil(north) and north.kind == Wall) and
                     (not isNil(south) and south.kind == Wall)
        let ewWall = (not isNil(east) and east.kind == Wall) and
                     (not isNil(west) and west.kind == Wall)
        if nsWall or ewWall:
          target = pos
          break search
  let (did, act) = goToAdjacentAndBuild(
    controller, env, agent, agentId, state, target, buildIndexFor(Door)
  )
  if did: return act
  0'u16

optionGuard(canStartRoadExpansion, shouldTerminateRoadExpansion):
  canStartVillagerBuild(agent, env, "Road")
proc optRoadExpansion(controller: Controller, env: Environment, agent: Thing,
                      agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  optDirectionalBuild(controller, env, agent, agentId, state,
    enemyDirectionalBuildTarget(env, basePos, getTeamId(agent), ivec2(8, 0)), 2, 5,
    BuildIndexRoad)

optionGuard(canStartCastleAnchor, shouldTerminateCastleAnchor):
  canStartVillagerBuild(agent, env, "Castle")
proc optCastleAnchor(controller: Controller, env: Environment, agent: Thing,
                     agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  optDirectionalBuild(controller, env, agent, agentId, state,
    enemyDirectionalBuildTarget(env, basePos, getTeamId(agent), ivec2(0, -8)), 5, 9,
    buildIndexFor(Castle))

optionGuard(canStartSiegeBreacher, shouldTerminateSiegeBreacher):
  agent.unitClass == UnitVillager and
    controller.getBuildingCount(env, getTeamId(agent), SiegeWorkshop) > 0 and
    not isNil(findNearestEnemyBuildingSpatial(env, agent.pos, getTeamId(agent))) and
    env.canSpendStockpile(getTeamId(agent), buildingTrainCosts(SiegeWorkshop))

proc optSiegeBreacher(controller: Controller, env: Environment, agent: Thing,
                      agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  controller.useNearestReadyFriendlyBuilding(env, agent, agentId, state, teamId, SiegeWorkshop)

optionGuard(canStartMangonelSuppression, shouldTerminateMangonelSuppression):
  agent.unitClass == UnitVillager and
    controller.getBuildingCount(env, getTeamId(agent), MangonelWorkshop) > 0 and
    env.canSpendStockpile(getTeamId(agent), buildingTrainCosts(MangonelWorkshop))

proc optMangonelSuppression(controller: Controller, env: Environment, agent: Thing,
                            agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  controller.useNearestReadyFriendlyBuilding(env, agent, agentId, state, teamId, MangonelWorkshop)

optionGuard(canStartUnitPromotionFocus, shouldTerminateUnitPromotionFocus):
  if agent.unitClass != UnitVillager:
    return false
  let teamId = getTeamId(agent)
  for kind in [Castle, Monastery, Barracks, ArcheryRange, Stable]:
    if controller.getBuildingCount(env, teamId, kind) == 0:
      continue
    if env.canSpendStockpile(teamId, buildingTrainCosts(kind)):
      return true
  false

proc optUnitPromotionFocus(controller: Controller, env: Environment, agent: Thing,
                           agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  for kind in [Castle, Monastery, Barracks, ArcheryRange, Stable]:
    if controller.getBuildingCount(env, teamId, kind) == 0:
      continue
    if not env.canSpendStockpile(teamId, buildingTrainCosts(kind)):
      continue
    let building = env.nearestFriendlyBuilding(state, teamId, kind)
    if isNil(building):
      continue
    # Batch-queue additional units if resources allow
    if building.productionQueue.entries.len < ProductionQueueMaxSize:
      discard env.tryBatchQueueTrain(building, teamId, BatchTrainSmall)
    return actOrMove(controller, env, agent, agentId, state, building.pos, 3'u16)
  0'u16

optionGuard(canStartRelicRaider, shouldTerminateRelicRaider):
  agent.inventoryRelic == 0 and env.thingsByKind[Relic].len > 0

proc optRelicRaider(controller: Controller, env: Environment, agent: Thing,
                    agentId: int, state: var AgentState): uint16 =
  let relic = env.findNearestThingSpiral(state, Relic)
  if isNil(relic):
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, relic.pos, 3'u16)

proc optRelicCourier(controller: Controller, env: Environment, agent: Thing,
                     agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  let monastery = env.nearestFriendlyBuilding(state, teamId, Monastery)
  let target =
    if not isNil(monastery): monastery.pos
    elif agent.homeAltar.x >= 0: agent.homeAltar
    else: agent.pos
  if target == agent.pos:
    return 0'u16
  controller.moveTo(env, agent, agentId, state, target)

optionGuard(canStartPredatorCull, shouldTerminatePredatorCull):
  agent.hp * 2 >= agent.maxHp and not isNil(findNearestPredator(env, agent.pos))

proc optPredatorCull(controller: Controller, env: Environment, agent: Thing,
                     agentId: int, state: var AgentState): uint16 =
  let target = findNearestPredator(env, agent.pos)
  if isNil(target):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, target.pos, 2'u16)

optionGuard(canStartGoblinNestClear, shouldTerminateGoblinNestClear):
  not isNil(findNearestGoblinStructure(env, agent.pos))

proc optGoblinNestClear(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): uint16 =
  let target = findNearestGoblinStructure(env, agent.pos)
  if isNil(target):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, target.pos, 2'u16)

optionGuard(canStartFertileExpansion, shouldTerminateFertileExpansion):
  agent.inventoryWheat > 0 or agent.inventoryWood > 0 or agent.inventoryWater > 0

proc optFertileExpansion(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  if agent.inventoryWheat > 0 or agent.inventoryWood > 0:
    let (didPlant, actPlant) = controller.tryPlantOnFertile(env, agent, agentId, state)
    if didPlant: return actPlant
  if agent.inventoryWater > 0:
    let basePos = agent.getBasePos()
    let target = findIrrigationTarget(env, basePos, 6)
    if target.x >= 0:
      return actOrMove(controller, env, agent, agentId, state, target, 3'u16)
  0'u16

optionGuardExported(canStartMarketTrade, shouldTerminateMarketTrade):
  ## Shared market trading initiation condition used by Gatherer, Builder, and Scripted roles.
  ## Returns true when:
  ## - Team has a Market building
  ## - Agent has gold AND team needs food (stockpile < 10), OR
  ## - Agent has non-food/water/gold resources AND team needs gold (stockpile < 5)
  let teamId = getTeamId(agent)
  if controller.getBuildingCount(env, teamId, Market) == 0:
    return false
  if agent.inventoryGold > 0 and env.stockpileCount(teamId, ResourceFood) < 10:
    return true
  var hasNonFood = false
  for key, count in agent.inventory.pairs:
    if count <= 0 or not isStockpileResourceKey(key):
      continue
    let res = stockpileResourceForItem(key)
    if res notin {ResourceFood, ResourceWater, ResourceGold}:
      hasNonFood = true
      break
  hasNonFood and env.stockpileCount(teamId, ResourceGold) < 5

proc optMarketTrade*(controller: Controller, env: Environment, agent: Thing,
                     agentId: int, state: var AgentState): uint16 =
  ## Shared market trading action used by Gatherer, Builder, and Scripted roles.
  ## Moves to nearest friendly Market and interacts with it.
  let teamId = getTeamId(agent)
  state.basePosition = agent.getBasePos()
  controller.useNearestReadyFriendlyBuilding(env, agent, agentId, state, teamId, Market)

let MarketTradeOption* = OptionDef(
  name: "MarketTrade",
  canStart: canStartMarketTrade,
  shouldTerminate: shouldTerminateMarketTrade,
  act: optMarketTrade,
  interruptible: true
)

# ============================================================================
# Tech Research Options - University and Castle
# ============================================================================

proc canStartResearchUniversityTech*(controller: Controller, env: Environment, agent: Thing,
                                     agentId: int, state: var AgentState): bool =
  if agent.unitClass != UnitVillager:
    return false
  let teamId = getTeamId(agent)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  if controller.getBuildingCount(env, teamId, University) == 0:
    return false
  for techType in UniversityTechType:
    if env.teamUniversityTechs[teamId].researched[techType]:
      continue
    let techIndex = ord(techType) + 1
    return env.canSpendStockpile(teamId,
      [(res: ResourceFood, count: UniversityTechFoodCost * techIndex),
       (res: ResourceGold, count: UniversityTechGoldCost * techIndex),
       (res: ResourceWood, count: UniversityTechWoodCost * techIndex)])
  false

proc shouldTerminateResearchUniversityTech*(controller: Controller, env: Environment, agent: Thing,
                                            agentId: int, state: var AgentState): bool =
  ## Only terminate if university gone or all techs researched (not for temporary resource dips)
  let teamId = getTeamId(agent)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return true
  if controller.getBuildingCount(env, teamId, University) == 0:
    return true
  for techType in UniversityTechType:
    if not env.teamUniversityTechs[teamId].researched[techType]:
      return false
  true

proc optResearchUniversityTech*(controller: Controller, env: Environment, agent: Thing,
                                agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  controller.useNearestReadyFriendlyBuilding(env, agent, agentId, state, teamId, University)

let ResearchUniversityTechOption* = OptionDef(
  name: "ResearchUniversityTech",
  canStart: canStartResearchUniversityTech,
  shouldTerminate: shouldTerminateResearchUniversityTech,
  act: optResearchUniversityTech,
  interruptible: true
)

proc canStartResearchCastleTech*(controller: Controller, env: Environment, agent: Thing,
                                 agentId: int, state: var AgentState): bool =
  if agent.unitClass != UnitVillager:
    return false
  let teamId = getTeamId(agent)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  if controller.getBuildingCount(env, teamId, Castle) == 0:
    return false
  let (castleAge, imperialAge) = castleTechsForTeam(teamId)
  if not env.teamCastleTechs[teamId].researched[castleAge]:
    return env.canSpendStockpile(teamId,
      [(res: ResourceFood, count: CastleTechFoodCost),
       (res: ResourceGold, count: CastleTechGoldCost)])
  if not env.teamCastleTechs[teamId].researched[imperialAge]:
    return env.canSpendStockpile(teamId,
      [(res: ResourceFood, count: CastleTechImperialFoodCost),
       (res: ResourceGold, count: CastleTechImperialGoldCost)])
  false

proc shouldTerminateResearchCastleTech*(controller: Controller, env: Environment, agent: Thing,
                                        agentId: int, state: var AgentState): bool =
  ## Only terminate if castle is gone or all techs researched (not for temporary resource dips)
  let teamId = getTeamId(agent)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return true
  if controller.getBuildingCount(env, teamId, Castle) == 0:
    return true
  let (castleAge, imperialAge) = castleTechsForTeam(teamId)
  env.teamCastleTechs[teamId].researched[castleAge] and
    env.teamCastleTechs[teamId].researched[imperialAge]

proc optResearchCastleTech*(controller: Controller, env: Environment, agent: Thing,
                            agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  controller.useNearestFriendlyBuilding(env, agent, agentId, state, teamId, Castle)

let ResearchCastleTechOption* = OptionDef(
  name: "ResearchCastleTech",
  canStart: canStartResearchCastleTech,
  shouldTerminate: shouldTerminateResearchCastleTech,
  act: optResearchCastleTech,
  interruptible: true
)

# ============================================================================
# Economy Tech Research Option - Mill, LumberCamp, MiningCamp, TownCenter
# ============================================================================

const EconomyTechBuildings = [TownCenter, Mill, LumberCamp, MiningCamp]

proc findNextAffordableEconomyTech(env: Environment, teamId: int): tuple[tech: EconomyTechType, building: ThingKind, found: bool] =
  ## Find the next affordable, unresearched economy tech across all building types.
  ## Returns the tech, the building it's researched at, and whether one was found.
  for buildingKind in EconomyTechBuildings:
    let tech = env.getNextEconomyTech(teamId, buildingKind)
    if economyTechBuilding(tech) != buildingKind:
      continue  # No available tech for this building
    if env.teamEconomyTechs[teamId].researched[tech]:
      continue  # Already researched
    let costs = economyTechCost(tech)
    if env.canSpendStockpile(teamId, costs):
      return (tech, buildingKind, true)
  return (TechWheelbarrow, TownCenter, false)

optionGuard(canStartResearchEconomyTech, shouldTerminateResearchEconomyTech):
  agent.unitClass == UnitVillager and
    (block:
      let teamId = getTeamId(agent)
      if teamId < 0 or teamId >= MapRoomObjectsTeams:
        false
      else:
        let (_, _, found) = findNextAffordableEconomyTech(env, teamId)
        found)

proc optResearchEconomyTech*(controller: Controller, env: Environment, agent: Thing,
                              agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  let (_, buildingKind, found) = findNextAffordableEconomyTech(env, teamId)
  if not found:
    return 0'u16
  controller.useNearestReadyFriendlyBuilding(env, agent, agentId, state, teamId, buildingKind)

let ResearchEconomyTechOption* = OptionDef(
  name: "ResearchEconomyTech",
  canStart: canStartResearchEconomyTech,
  shouldTerminate: shouldTerminateResearchEconomyTech,
  act: optResearchEconomyTech,
  interruptible: true
)

# ============================================================================
# Blacksmith Upgrade Research Option
# ============================================================================

optionGuard(canStartResearchBlacksmithUpgrade, shouldTerminateResearchBlacksmithUpgrade):
  agent.unitClass == UnitVillager and
    (block:
      let teamId = getTeamId(agent)
      if teamId < 0 or teamId >= MapRoomObjectsTeams or
          controller.getBuildingCount(env, teamId, Blacksmith) == 0:
        false
      else:
        let upgradeType = env.getNextBlacksmithUpgrade(teamId)
        let currentLevel = env.teamBlacksmithUpgrades[teamId].levels[upgradeType]
        let costMultiplier = currentLevel + 1
        currentLevel < BlacksmithUpgradeMaxLevel and
          env.canSpendStockpile(teamId,
            [(res: ResourceFood, count: BlacksmithUpgradeFoodCost * costMultiplier),
             (res: ResourceGold, count: BlacksmithUpgradeGoldCost * costMultiplier)]))

proc optResearchBlacksmithUpgrade*(controller: Controller, env: Environment, agent: Thing,
                                    agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  controller.useNearestReadyFriendlyBuilding(env, agent, agentId, state, teamId, Blacksmith)

let ResearchBlacksmithUpgradeOption* = OptionDef(
  name: "ResearchBlacksmithUpgrade",
  canStart: canStartResearchBlacksmithUpgrade,
  shouldTerminate: shouldTerminateResearchBlacksmithUpgrade,
  act: optResearchBlacksmithUpgrade,
  interruptible: true
)

# ============================================================================
# Unit Upgrade Research Option - Barracks, Stable, ArcheryRange
# ============================================================================

const UnitUpgradeBuildings = [Barracks, Stable, ArcheryRange]

optionGuard(canStartResearchUnitUpgrade, shouldTerminateResearchUnitUpgrade):
  agent.unitClass == UnitVillager and
    (block:
      let teamId = getTeamId(agent)
      if teamId < 0 or teamId >= MapRoomObjectsTeams:
        false
      else:
        var hasBuilding = false
        for kind in UnitUpgradeBuildings:
          if controller.getBuildingCount(env, teamId, kind) > 0:
            hasBuilding = true
            break
        if not hasBuilding:
          false
        else:
          var hasAffordableUpgrade = false
          for upgrade in UnitUpgradeType:
            if env.teamUnitUpgrades[teamId].researched[upgrade]:
              continue
            let prereq = upgradePrerequisite(upgrade)
            if prereq != upgrade and not env.teamUnitUpgrades[teamId].researched[prereq]:
              continue
            if env.canSpendStockpile(teamId, upgradeCosts(upgrade)):
              hasAffordableUpgrade = true
              break
          hasAffordableUpgrade)

proc optResearchUnitUpgrade*(controller: Controller, env: Environment, agent: Thing,
                              agentId: int, state: var AgentState): uint16 =
  ## Move to nearest military building that has an affordable, available upgrade.
  let teamId = getTeamId(agent)
  var bestBuilding: Thing = nil
  var bestDist = int.high
  for kind in UnitUpgradeBuildings:
    if controller.getBuildingCount(env, teamId, kind) == 0:
      continue
    # Check if this building type has an available upgrade
    let upgrade = env.getNextUnitUpgrade(teamId, kind)
    if env.teamUnitUpgrades[teamId].researched[upgrade]:
      continue
    let prereq = upgradePrerequisite(upgrade)
    if prereq != upgrade and not env.teamUnitUpgrades[teamId].researched[prereq]:
      continue
    let costs = upgradeCosts(upgrade)
    if not env.canSpendStockpile(teamId, costs):
      continue
    let building = env.nearestReadyFriendlyBuilding(state, teamId, kind)
    if isNil(building):
      continue
    let dist = int(chebyshevDist(agent.pos, building.pos))
    if dist < bestDist:
      bestDist = dist
      bestBuilding = building
  if isNil(bestBuilding):
    return 0'u16
  actOrMove(controller, env, agent, agentId, state, bestBuilding.pos, 3'u16)

let ResearchUnitUpgradeOption* = OptionDef(
  name: "ResearchUnitUpgrade",
  canStart: canStartResearchUnitUpgrade,
  shouldTerminate: shouldTerminateResearchUnitUpgrade,
  act: optResearchUnitUpgrade,
  interruptible: true
)

optionGuard(canStartDockControl, shouldTerminateDockControl):
  if agent.unitClass == UnitBoat:
    env.thingsByKind[Fish].len > 0
  else:
    agent.unitClass == UnitVillager and env.canAffordBuild(agent, thingItem("Dock"))

proc optDockControl(controller: Controller, env: Environment, agent: Thing,
                    agentId: int, state: var AgentState): uint16 =
  if agent.unitClass == UnitBoat:
    let fish = env.findNearestThingSpiral(state, Fish)
    if isNil(fish):
      return 0'u16
    return actOrMove(controller, env, agent, agentId, state, fish.pos, 3'u16)

  # Find water and adjacent standing position (inlined from findNearestWaterEdge)
  let water = findNearestWaterSpiral(env, state)
  if water.x < 0:
    return 0'u16
  var stand = ivec2(-1, -1)
  for d in AdjacentOffsets8:
    let pos = water + d
    if not isValidPos(pos) or env.terrain[pos.x][pos.y] == Water:
      continue
    if env.isEmpty(pos) and not env.hasDoor(pos) and
        not isBlockedTerrain(env.terrain[pos.x][pos.y]) and
        not isTileFrozen(pos, env):
      stand = pos
      break
  if stand.x < 0:
    return 0'u16
  if stand == agent.pos:
    return saveStateAndReturn(controller, agentId, state,
      encodeAction(8'u16, buildIndexFor(Dock).uint8))
  controller.moveTo(env, agent, agentId, state, stand)

optionGuard(canStartTerritorySweeper, shouldTerminateTerritorySweeper):
  agent.inventoryLantern > 0 or
    not isNil(findNearestEnemyBuildingSpatial(env, agent.pos, getTeamId(agent)))

proc optTerritorySweeper(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let enemy = findNearestEnemyBuildingSpatial(env, agent.pos, getTeamId(agent))
  if not isNil(enemy):
    return actOrMove(controller, env, agent, agentId, state, enemy.pos, 2'u16)
  let teamId = getTeamId(agent)
  let basePos = agent.getBasePos()
  let target = findLanternFrontierCandidate(env, state, teamId, basePos)
  if target.x < 0 or agent.inventoryLantern <= 0:
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, target, 6'u16)

proc canStartTempleFusion(controller: Controller, env: Environment, agent: Thing,
                          agentId: int, state: var AgentState): bool =
  agent.unitClass == UnitVillager and env.thingsByKind[Temple].len > 0 and
    randChance(controller.rng, 0.01)

proc shouldTerminateTempleFusion(controller: Controller, env: Environment, agent: Thing,
                                 agentId: int, state: var AgentState): bool =
  ## Terminate when no longer a villager or no temples
  agent.unitClass != UnitVillager or env.thingsByKind[Temple].len == 0

proc optTempleFusion(controller: Controller, env: Environment, agent: Thing,
                     agentId: int, state: var AgentState): uint16 =
  let temple = env.findNearestThingSpiral(state, Temple)
  if isNil(temple):
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, temple.pos, 3'u16)

# ============================================================================
# Monk Behaviors
# ============================================================================

proc findNearestWoundedAlly(env: Environment, agent: Thing, radius: int): Thing =
  ## Find nearest allied agent with HP < maxHp within radius using spatial index.
  let teamId = getTeamId(agent)
  env.tempAIAllies.setLen(0)
  collectAlliesInRangeSpatial(env, agent.pos, teamId, radius, env.tempAIAllies)
  var best: Thing = nil
  var bestDist = int.high
  for ally in env.tempAIAllies:
    if ally.agentId == agent.agentId:
      continue
    if ally.hp >= ally.maxHp:
      continue
    let dist = int(chebyshevDist(agent.pos, ally.pos))
    if dist < bestDist:
      bestDist = dist
      best = ally
  best

optionGuard(canStartMonkHeal, shouldTerminateMonkHeal):
  ## Monk healing: position near wounded allies to heal them with aura.
  ## Requires: monk unit class and a wounded ally within seek radius.
  agent.unitClass == UnitMonk and
    not isNil(findNearestWoundedAlly(env, agent, HealerSeekRadius))

proc optMonkHeal*(controller: Controller, env: Environment, agent: Thing,
                  agentId: int, state: var AgentState): uint16 =
  ## Move toward the nearest wounded ally to heal them with aura.
  let wounded = findNearestWoundedAlly(env, agent, HealerSeekRadius)
  if isNil(wounded):
    return 0'u16
  let dist = int(chebyshevDist(agent.pos, wounded.pos))
  # Already within healing aura range - stay put and let aura heal
  if dist <= MonkAuraRadius:
    return 0'u16
  controller.moveTo(env, agent, agentId, state, wounded.pos)

let MonkHealOption* = OptionDef(
  name: "MonkHeal",
  canStart: canStartMonkHeal,
  shouldTerminate: shouldTerminateMonkHeal,
  act: optMonkHeal,
  interruptible: true
)

optionGuard(canStartMonkRelicCollect, shouldTerminateMonkRelicCollect):
  ## Monk relic collection: pick up relics and deposit in monastery.
  ## Requires: monk unit class.
  agent.unitClass == UnitMonk and
    (agent.inventoryRelic > 0 or env.thingsByKind[Relic].len > 0)

proc optMonkRelicCollect*(controller: Controller, env: Environment, agent: Thing,
                          agentId: int, state: var AgentState): uint16 =
  ## Collect relics and deposit them in a monastery for gold generation.
  let teamId = getTeamId(agent)
  # If carrying a relic, deposit it in a monastery
  if agent.inventoryRelic > 0:
    let monastery = env.nearestFriendlyBuilding(state, teamId, Monastery)
    if not isNil(monastery):
      return actOrMove(controller, env, agent, agentId, state, monastery.pos, 3'u16)
    # No monastery - return to home altar
    if agent.homeAltar.x >= 0:
      return controller.moveTo(env, agent, agentId, state, agent.homeAltar)
    return 0'u16
  # Otherwise, find and collect a relic
  let relic = env.findNearestThingSpiral(state, Relic)
  if isNil(relic):
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, relic.pos, 3'u16)

let MonkRelicCollectOption* = OptionDef(
  name: "MonkRelicCollect",
  canStart: canStartMonkRelicCollect,
  shouldTerminate: shouldTerminateMonkRelicCollect,
  act: optMonkRelicCollect,
  interruptible: true
)

optionGuard(canStartMonkConversion, shouldTerminateMonkConversion):
  ## Monk conversion: convert enemy units using faith.
  ## Requires: monk unit class with sufficient faith and enemy in range.
  agent.unitClass == UnitMonk and
    agent.faith >= MonkConversionFaithCost and
    (block:
      let teamId = getTeamId(agent)
      let conversionRadius = ObservationRadius.int * 2
      not isNil(findNearestEnemyAgentSpatial(env, agent.pos, teamId, conversionRadius)))

proc optMonkConversion*(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): uint16 =
  ## Move toward and convert the nearest enemy agent.
  let teamId = getTeamId(agent)
  let conversionRadius = ObservationRadius.int * 2
  let enemy = findNearestEnemyAgentSpatial(env, agent.pos, teamId, conversionRadius)
  if isNil(enemy):
    return 0'u16
  # Monks use attack action (verb 2) to convert
  return actOrMove(controller, env, agent, agentId, state, enemy.pos, 2'u16)

let MonkConversionOption* = OptionDef(
  name: "MonkConversion",
  canStart: canStartMonkConversion,
  shouldTerminate: shouldTerminateMonkConversion,
  act: optMonkConversion,
  interruptible: true
)

# ============================================================================
# Trade Cog Behaviors
# ============================================================================

# TradeCogTradeRoute: Trade cogs travel between friendly docks to generate gold
proc findNearestFriendlyDock(env: Environment, pos: IVec2, teamId: int, excludePos: IVec2): Thing =
  ## Find the nearest friendly dock, optionally excluding a specific position
  var best: Thing = nil
  var bestDist = int.high
  for thing in env.thingsByKind[Dock]:
    if thing.teamId != teamId:
      continue
    if excludePos.x >= 0 and thing.pos == excludePos:
      continue
    let dist = int(chebyshevDist(pos, thing.pos))
    if dist < bestDist:
      bestDist = dist
      best = thing
  best

optionGuardExported(canStartTradeCogTradeRoute, shouldTerminateTradeCogTradeRoute):
  ## Trade cogs trade when there are at least 2 friendly docks
  if agent.unitClass != UnitTradeCog:
    return false
  let teamId = getTeamId(agent)
  var dockCount = 0
  for thing in env.thingsByKind[Dock]:
    if thing.teamId == teamId:
      inc dockCount
      if dockCount >= 2:
        return true
  false

proc optTradeCogTradeRoute*(controller: Controller, env: Environment, agent: Thing,
                             agentId: int, state: var AgentState): uint16 =
  ## Trade cog navigates between friendly docks to generate gold
  let teamId = getTeamId(agent)
  let homeDock = agent.tradeHomeDock

  # Find target dock (different from home dock)
  let targetDock = findNearestFriendlyDock(env, agent.pos, teamId, homeDock)
  if isNil(targetDock):
    return 0'u16

  # Move toward target dock
  controller.moveTo(env, agent, agentId, state, targetDock.pos)

let TradeCogTradeRouteOption* = OptionDef(
  name: "TradeCogTradeRoute",
  canStart: canStartTradeCogTradeRoute,
  shouldTerminate: shouldTerminateTradeCogTradeRoute,
  act: optTradeCogTradeRoute,
  interruptible: true
)

# ============================================================================
# Siege Behaviors
# ============================================================================

optionGuardExported(canStartSiegeAdvance, shouldTerminateSiegeAdvance):
  ## Siege units (mangonel, trebuchet) advance when there are enemy buildings
  agent.unitClass in {UnitMangonel, UnitTrebuchet} and
    not isNil(findNearestEnemyBuildingSpatial(env, agent.pos, getTeamId(agent)))

proc optSiegeAdvance*(controller: Controller, env: Environment, agent: Thing,
                      agentId: int, state: var AgentState): uint16 =
  ## Siege unit advances toward enemy buildings and attacks them
  let enemy = findNearestEnemyBuildingSpatial(env, agent.pos, getTeamId(agent))
  if isNil(enemy):
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, enemy.pos, 2'u16)

let SiegeAdvanceOption* = OptionDef(
  name: "SiegeAdvance",
  canStart: canStartSiegeAdvance,
  shouldTerminate: shouldTerminateSiegeAdvance,
  act: optSiegeAdvance,
  interruptible: true
)

# ============================================================================
# Settler Migration Behaviors
# ============================================================================

const SettlerMinGroupSize = 5  ## Minimum settlers alive to continue migration
const SettlerArrivalRadius = 3  ## Tiles from target to consider "arrived"

optionGuardExported(canStartSettlerMigrate, shouldTerminateSettlerMigrate):
  agent.isSettler and agent.settlerTarget.x >= 0 and not agent.settlerArrived

proc optSettlerMigrate*(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)

  # Abort migration if too few settlers remain alive
  var settlerCount = 0
  for other in env.teamAliveAgents(teamId):
    if other.isSettler:
      inc settlerCount
  if settlerCount < SettlerMinGroupSize:
    agent.isSettler = false
    agent.settlerTarget = ivec2(-1, -1)
    agent.settlerArrived = false
    return 0'u16

  # Check if target is blocked by an enemy building; find alternate if so
  var target = agent.settlerTarget
  let thingAtTarget = env.getThing(target)
  if not isNil(thingAtTarget) and thingAtTarget.teamId != teamId and thingAtTarget.teamId >= 0:
    # Find a nearby open position
    var found = false
    for radius in 1 .. 5:
      for dx in -radius .. radius:
        for dy in -radius .. radius:
          if abs(dx) != radius and abs(dy) != radius:
            continue
          let candidate = target + ivec2(dx.int32, dy.int32)
          if not isValidPos(candidate):
            continue
          let t = env.getThing(candidate)
          if isNil(t) or (t.teamId == teamId):
            agent.settlerTarget = candidate
            target = candidate
            found = true
            break
        if found: break
      if found: break

  let dist = int(chebyshevDist(agent.pos, target))
  if dist <= SettlerArrivalRadius:
    agent.settlerArrived = true
    return 0'u16

  controller.moveTo(env, agent, agentId, state, target)

let SettlerMigrateOption* = OptionDef(
  name: "SettlerMigrate",
  canStart: canStartSettlerMigrate,
  shouldTerminate: shouldTerminateSettlerMigrate,
  act: optSettlerMigrate,
  interruptible: false  # Settlers should not be interrupted by lower-priority options
)

let MetaBehaviorOptions* = [
  OptionDef(
    name: "BehaviorSettlerMigrate",
    canStart: canStartSettlerMigrate,
    shouldTerminate: shouldTerminateSettlerMigrate,
    act: optSettlerMigrate,
    interruptible: false
  ),
  OptionDef(
    name: "BehaviorLanternFrontierPush",
    canStart: canStartCarryLantern,
    shouldTerminate: shouldTerminateCarryLantern,
    act: optLanternFrontierPush,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorLanternGapFill",
    canStart: canStartCarryLantern,
    shouldTerminate: shouldTerminateCarryLantern,
    act: optLanternGapFill,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorLanternRecovery",
    canStart: canStartCarryLantern,
    shouldTerminate: shouldTerminateCarryLantern,
    act: optLanternRecovery,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorLanternLogistics",
    canStart: canStartLanternLogistics,
    shouldTerminate: shouldTerminateLanternLogistics,
    act: optLanternLogistics,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorAntiTumorPatrol",
    canStart: canStartAntiTumorPatrol,
    shouldTerminate: shouldTerminateAntiTumorPatrol,
    act: optAntiTumorPatrol,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorSpawnerHunter",
    canStart: canStartSpawnerHunter,
    shouldTerminate: shouldTerminateSpawnerHunter,
    act: optSpawnerHunter,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorFrozenEdgeBreaker",
    canStart: canStartFrozenEdgeBreaker,
    shouldTerminate: shouldTerminateFrozenEdgeBreaker,
    act: optFrozenEdgeBreaker,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorGuardTowerBorder",
    canStart: canStartGuardTowerBorder,
    shouldTerminate: shouldTerminateGuardTowerBorder,
    act: optGuardTowerBorder,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorOutpostNetwork",
    canStart: canStartOutpostNetwork,
    shouldTerminate: shouldTerminateOutpostNetwork,
    act: optOutpostNetwork,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorEnemyWallFortify",
    canStart: canStartEnemyWallFortify,
    shouldTerminate: shouldTerminateEnemyWallFortify,
    act: optEnemyWallFortify,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorWallChokeFortify",
    canStart: canStartWallChokeFortify,
    shouldTerminate: shouldTerminateWallChokeFortify,
    act: optWallChokeFortify,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorDoorChokeFortify",
    canStart: canStartDoorChokeFortify,
    shouldTerminate: shouldTerminateDoorChokeFortify,
    act: optDoorChokeFortify,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorRoadExpansion",
    canStart: canStartRoadExpansion,
    shouldTerminate: shouldTerminateRoadExpansion,
    act: optRoadExpansion,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorCastleAnchor",
    canStart: canStartCastleAnchor,
    shouldTerminate: shouldTerminateCastleAnchor,
    act: optCastleAnchor,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorSiegeBreacher",
    canStart: canStartSiegeBreacher,
    shouldTerminate: shouldTerminateSiegeBreacher,
    act: optSiegeBreacher,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorMangonelSuppression",
    canStart: canStartMangonelSuppression,
    shouldTerminate: shouldTerminateMangonelSuppression,
    act: optMangonelSuppression,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorUnitPromotionFocus",
    canStart: canStartUnitPromotionFocus,
    shouldTerminate: shouldTerminateUnitPromotionFocus,
    act: optUnitPromotionFocus,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorRelicRaider",
    canStart: canStartRelicRaider,
    shouldTerminate: shouldTerminateRelicRaider,
    act: optRelicRaider,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorRelicCourier",
    canStart: canStartCarryRelic,
    shouldTerminate: shouldTerminateCarryRelic,
    act: optRelicCourier,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorPredatorCull",
    canStart: canStartPredatorCull,
    shouldTerminate: shouldTerminatePredatorCull,
    act: optPredatorCull,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorGoblinNestClear",
    canStart: canStartGoblinNestClear,
    shouldTerminate: shouldTerminateGoblinNestClear,
    act: optGoblinNestClear,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorFertileExpansion",
    canStart: canStartFertileExpansion,
    shouldTerminate: shouldTerminateFertileExpansion,
    act: optFertileExpansion,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorBreadSupply",
    canStart: canStartCraftBread,
    shouldTerminate: shouldTerminateCraftBread,
    act: optCraftBread,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorMarketManipulator",
    canStart: canStartMarketTrade,
    shouldTerminate: shouldTerminateMarketTrade,
    act: optMarketTrade,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorStockpileDistributor",
    canStart: canStartStoreValuables,
    shouldTerminate: shouldTerminateStoreValuables,
    act: optStoreValuables,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorDockControl",
    canStart: canStartDockControl,
    shouldTerminate: shouldTerminateDockControl,
    act: optDockControl,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorTerritorySweeper",
    canStart: canStartTerritorySweeper,
    shouldTerminate: shouldTerminateTerritorySweeper,
    act: optTerritorySweeper,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorTempleFusion",
    canStart: canStartTempleFusion,
    shouldTerminate: shouldTerminateTempleFusion,
    act: optTempleFusion,
    interruptible: true
  ),
  # Monk behaviors
  OptionDef(
    name: "BehaviorMonkHeal",
    canStart: canStartMonkHeal,
    shouldTerminate: shouldTerminateMonkHeal,
    act: optMonkHeal,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorMonkRelicCollect",
    canStart: canStartMonkRelicCollect,
    shouldTerminate: shouldTerminateMonkRelicCollect,
    act: optMonkRelicCollect,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorMonkConversion",
    canStart: canStartMonkConversion,
    shouldTerminate: shouldTerminateMonkConversion,
    act: optMonkConversion,
    interruptible: true
  ),
  # Trade and siege behaviors
  OptionDef(
    name: "BehaviorTradeCogTradeRoute",
    canStart: canStartTradeCogTradeRoute,
    shouldTerminate: shouldTerminateTradeCogTradeRoute,
    act: optTradeCogTradeRoute,
    interruptible: true
  ),
  OptionDef(
    name: "BehaviorSiegeAdvance",
    canStart: canStartSiegeAdvance,
    shouldTerminate: shouldTerminateSiegeAdvance,
    act: optSiegeAdvance,
    interruptible: true
  )
]
