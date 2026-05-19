import
  ai_build_helpers, coordination, economy, options

export ai_build_helpers, options
export coordination, economy

const
  EarlyGameWeights = [0.35, 0.6, 1.2, 1.0]
  MidGameWeights = [0.7, 0.7, 0.85, 0.6]
  LateGameWeights = [1.2, 1.0, 0.65, 0.4]

optionGuard(canStartGathererGarrison, shouldTerminateGathererGarrison):
  not isNil(findNearbyEnemyForFlee(env, agent, GathererFleeRadius)) and
    not isNil(findNearestGarrisonableBuilding(env, agent.pos, getTeamId(agent), GarrisonSeekRadius))

proc optGathererGarrison(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  ## Seek nearest garrisonable building for protection when enemies are nearby.
  let enemy = findNearbyEnemyForFlee(env, agent, GathererFleeRadius)
  if isNil(enemy):
    return 0'u16
  let teamId = getTeamId(agent)
  let building = findNearestGarrisonableBuilding(env, agent.pos, teamId, GarrisonSeekRadius)
  if isNil(building):
    return 0'u16
  requestProtectionFromFighter(env, agent, enemy.pos)
  actOrMove(controller, env, agent, agentId, state, building.pos, 3'u16)

optionGuard(canStartGathererFlee, shouldTerminateGathererFlee):
  not isNil(findNearbyEnemyForFlee(env, agent, GathererFleeRadius))

proc optGathererFlee(controller: Controller, env: Environment, agent: Thing,
                     agentId: int, state: var AgentState): uint16 =
  ## Flee toward the home altar when enemies are nearby.
  let enemy = findNearbyEnemyForFlee(env, agent, GathererFleeRadius)
  if isNil(enemy):
    return 0'u16
  requestProtectionFromFighter(env, agent, enemy.pos)
  fleeToBase(controller, env, agent, agentId, state)

proc findFertileTarget(env: Environment, center: IVec2, radius: int, blocked: IVec2): IVec2 =
  ## Return the nearest open fertile-adjacent build target.
  let (startX, endX, startY, endY) = radiusBounds(center, radius)
  let cx = center.x.int
  let cy = center.y.int
  var bestDist = int.high
  var bestPos = ivec2(-1, -1)
  for x in startX .. endX:
    for y in startY .. endY:
      if max(abs(x - cx), abs(y - cy)) > radius:
        continue
      let pos = ivec2(x.int32, y.int32)
      if pos == blocked:
        continue
      if not env.isEmpty(pos) or env.hasDoor(pos) or isTileFrozen(pos, env):
        continue
      let terrain = env.terrain[x][y]
      if not isBuildableExcludingRoads(terrain):
        continue
      let dist = abs(x - cx) + abs(y - cy)
      if dist < bestDist:
        bestDist = dist
        bestPos = pos
  bestPos

const FoodKinds = {Wheat, Stubble, Fish, Bush, Cow, Corpse}

proc gathererStockpileTotal(agent: Thing): int =
  ## Sum carried stockpile resources for the agent.
  for key, count in agent.inventory.pairs:
    if count > 0 and isStockpileResourceKey(key):
      result += count

proc hasNearbyFood(env: Environment, pos: IVec2, radius: int): bool =
  ## Return true when any food source exists within the search radius.
  let nearest = findNearestThingOfKindsSpatial(env, pos, FoodKinds, radius)
  not nearest.isNil

proc tryDeliverGoldToMagma(controller: Controller, env: Environment, agent: Thing,
                           agentId: int, state: var AgentState,
                           magmaGlobal: Thing): (bool, uint16) =
  ## Move the agent toward a magma drop-off for altar-heart delivery.
  let (didKnown, actKnown) = controller.tryMoveToKnownResource(
    env, agent, agentId, state, state.closestMagmaPos, {Magma}, 3'u16)
  if didKnown: return (true, actKnown)
  if not isNil(magmaGlobal):
    updateClosestSeen(state, state.basePosition, magmaGlobal.pos, state.closestMagmaPos)
    return (true, actOrMove(controller, env, agent, agentId, state, magmaGlobal.pos, 3'u16))
  (false, 0'u16)


proc updateGathererTask*(
  controller: Controller,
  env: Environment,
  agent: Thing,
  state: var AgentState
) =
  ## Choose the gatherer task that best matches current economy pressure.
  let teamId = getTeamId(agent)
  let agentId = agent.agentId

  if controller.isGathererPriorityActive(agentId):
    let resource = controller.getGathererPriority(agentId)
    state.gathererTask = stockpileResourceToGathererTask(resource)
    return

  if controller.isTeamEconomyFocusActive(teamId):
    let resource = controller.getTeamEconomyFocus(teamId)
    state.gathererTask = stockpileResourceToGathererTask(resource)
    return

  let (altarPos, altarHearts) = findTeamAltar(env, agent, teamId)
  let altarFound = altarPos.x >= 0
  var task = TaskFood

  let bottleneck = getCurrentBottleneck(teamId)
  if bottleneck == FoodCritical:
    state.gathererTask = TaskFood
    return
  elif bottleneck == WoodCritical:
    state.gathererTask = TaskWood
    return

  if altarFound and altarHearts < 10:
    task = TaskHearts
  else:
    let gameProgress = if env.config.maxSteps > 0:
      env.currentStep.float / env.config.maxSteps.float
    else:
      0.5
    let weights = if gameProgress < EarlyGameThreshold:
      EarlyGameWeights
    elif gameProgress < MidGameThreshold:
      MidGameWeights
    elif gameProgress >= LateGameThreshold:
      LateGameWeights
    else:
      let blend =
        (gameProgress - MidGameThreshold) /
        (LateGameThreshold - MidGameThreshold)
      [
        MidGameWeights[0] + blend * (LateGameWeights[0] - MidGameWeights[0]),
        MidGameWeights[1] + blend * (LateGameWeights[1] - MidGameWeights[1]),
        MidGameWeights[2] + blend * (LateGameWeights[2] - MidGameWeights[2]),
        MidGameWeights[3] + blend * (LateGameWeights[3] - MidGameWeights[3])
      ]

    let flowRate = getFlowRate(teamId)
    proc flowAdj(rate: float): float =
      if rate < -0.1: rate * 2.0 else: 0.0
    let flowAdjust = [
      flowAdj(flowRate.foodPerStep),
      flowAdj(flowRate.woodPerStep),
      flowAdj(flowRate.stonePerStep),
      flowAdj(flowRate.goldPerStep)
    ]

    var ordered: array[5, (GathererTask, float)]
    var orderedLen = 4
    ordered[0] = (
      TaskFood,
      max(
        0.0,
        env.stockpileCount(teamId, ResourceFood).float + flowAdjust[0] * 10.0
      ) * weights[0]
    )
    ordered[1] = (
      TaskWood,
      max(
        0.0,
        env.stockpileCount(teamId, ResourceWood).float + flowAdjust[1] * 10.0
      ) * weights[1]
    )
    ordered[2] = (
      TaskStone,
      max(
        0.0,
        env.stockpileCount(teamId, ResourceStone).float + flowAdjust[2] * 10.0
      ) * weights[2]
    )
    ordered[3] = (
      TaskGold,
      max(
        0.0,
        env.stockpileCount(teamId, ResourceGold).float + flowAdjust[3] * 10.0
      ) * weights[3]
    )
    if altarFound:
      for i in countdown(3, 0):
        ordered[i + 1] = ordered[i]
      ordered[0] = (TaskHearts, altarHearts.float)
      orderedLen = 5
    var best = ordered[0]
    for i in 1 ..< orderedLen:
      if ordered[i][1] < best[1]:
        best = ordered[i]
    let currentTask = state.gathererTask
    if best[1] <= 0.0:
      task = best[0]
    elif currentTask != TaskHearts:
      var currentScore = float.high
      for i in 0 ..< orderedLen:
        if ordered[i][0] == currentTask:
          currentScore = ordered[i][1]
          break
      if best[1] > currentScore - TaskSwitchHysteresis:
        task = currentTask
      else:
        task = best[0]
    else:
      task = best[0]
  state.gathererTask = task

proc gathererTryBuildCamp(controller: Controller, env: Environment, agent: Thing,
                          agentId: int, state: var AgentState,
                          teamId: int, kind: ThingKind,
                          nearbyCount, minCount: int,
                          nearbyKinds: openArray[ThingKind]): uint16 =
  if agent.unitClass != UnitVillager:
    return 0'u16
  let (didBuild, buildAct) = controller.tryBuildCampThreshold(
    env, agent, agentId, state, teamId, kind,
    nearbyCount, minCount, nearbyKinds)
  if didBuild: buildAct else: 0'u16

optionGuard(canStartGathererPlantOnFertile, shouldTerminateGathererPlantOnFertile):
  state.gathererTask != TaskHearts and (agent.inventoryWheat > 0 or agent.inventoryWood > 0)

optionGuard(canStartGathererCarrying, shouldTerminateGathererCarrying):
  gathererStockpileTotal(agent) > 0

proc optGathererCarrying(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  state.basePosition = basePos
  let heartsPriority = state.gathererTask == TaskHearts
  var magmaGlobal: Thing = nil
  if heartsPriority:
    magmaGlobal = findNearestThing(env, agent.pos, Magma, maxDist = int.high)

  if agent.inventoryGold > 0 and heartsPriority:
    let (didDeliver, deliverAct) = tryDeliverGoldToMagma(
      controller,
      env,
      agent,
      agentId,
      state,
      magmaGlobal
    )
    if didDeliver: return deliverAct

  let (didDrop, dropAct) = controller.dropoffCarrying(
    env, agent, agentId, state,
    allowFood = true, allowWood = true, allowStone = true, allowGold = not heartsPriority
  )
  if didDrop: return dropAct
  controller.moveTo(env, agent, agentId, state, basePos)

optionGuard(canStartGathererHearts, shouldTerminateGathererHearts):
  state.gathererTask == TaskHearts

proc optGathererHearts(controller: Controller, env: Environment, agent: Thing,
                       agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  state.basePosition = basePos
  let magmaGlobal = findNearestThing(env, agent.pos, Magma, maxDist = int.high)

  if agent.inventoryBar > 0:
    var altarPos = agent.homeAltar
    if altarPos.x < 0:
      let altar = env.findNearestThingSpiral(state, Altar)
      if not isNil(altar):
        altarPos = altar.pos
    if altarPos.x >= 0:
      return actOrMove(controller, env, agent, agentId, state, altarPos, 3'u16)
  if agent.inventoryGold > 0:
    let (didDeliver, deliverAct) = tryDeliverGoldToMagma(
      controller,
      env,
      agent,
      agentId,
      state,
      magmaGlobal
    )
    if didDeliver: return deliverAct
    return controller.moveNextSearch(env, agent, agentId, state)
  if state.closestMagmaPos.x < 0 and isNil(magmaGlobal):
    return controller.moveNextSearch(env, agent, agentId, state)
  let (didGold, actGold) = controller.ensureGold(env, agent, agentId, state)
  if didGold: return actGold
  return controller.moveNextSearch(env, agent, agentId, state)

optionGuard(canStartGathererResource, shouldTerminateGathererResource):
  state.gathererTask in {TaskGold, TaskWood, TaskStone}

proc optGathererResource(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  var campKind: ThingKind
  var nearbyCount, minCount: int
  case state.gathererTask
  of TaskGold:
    campKind = MiningCamp
    nearbyCount = countNearbyThings(env, agent.pos, 4, {Gold})
    minCount = 3
  of TaskWood:
    campKind = LumberCamp
    nearbyCount = countNearbyThings(env, agent.pos, 4, {Tree})
    minCount = 6
  of TaskStone:
    campKind = Quarry
    nearbyCount = countNearbyThings(env, agent.pos, 4, {Stone, Stalagmite})
    minCount = 4
  else:
    discard
  let buildAct = gathererTryBuildCamp(
    controller, env, agent, agentId, state, teamId,
    campKind, nearbyCount, minCount, [campKind]
  )
  if buildAct != 0'u16: return buildAct
  let (didGather, actGather) = case state.gathererTask
    of TaskGold: controller.ensureGold(env, agent, agentId, state)
    of TaskWood: controller.ensureWood(env, agent, agentId, state)
    of TaskStone: controller.ensureStone(env, agent, agentId, state)
    else: (false, 0'u16)
  if didGather: return actGather
  return controller.moveNextSearch(env, agent, agentId, state)

optionGuard(canStartGathererFood, shouldTerminateGathererFood):
  state.gathererTask == TaskFood

proc optGathererFood(controller: Controller, env: Environment, agent: Thing,
                     agentId: int, state: var AgentState): uint16 =
  let teamId = getTeamId(agent)
  let basePos = agent.getBasePos()
  state.basePosition = basePos

  let buildGranary = gathererTryBuildCamp(
    controller, env, agent, agentId, state, teamId,
    Granary,
    countNearbyThings(env, agent.pos, 4, {Wheat, Stubble}) +
      countNearbyTerrain(env, agent.pos, 4, {Fertile}),
    8,
    [Granary]
  )
  if buildGranary != 0'u16: return buildGranary
  if agent.homeAltar.x < 0 or
     max(abs(agent.pos.x - agent.homeAltar.x), abs(agent.pos.y - agent.homeAltar.y)) > 10:
    let (didMill, actMill) = controller.tryBuildNearResource(
      env, agent, agentId, state, teamId, Mill,
      1, 1, [Mill], 6
    )
    if didMill: return actMill
  let (didPlant, actPlant) = controller.tryPlantOnFertile(env, agent, agentId, state)
  if didPlant: return actPlant

  if not hasNearbyFood(env, agent.pos, 4):
    let fertileRadius = 6
    let fertileCount = countNearbyTerrain(env, basePos, fertileRadius, {Fertile})
    let nearbyMill = findNearestFriendlyThingSpatial(env, basePos, teamId, Mill, fertileRadius)
    let hasMill = not nearbyMill.isNil
    if fertileCount < 6 and not hasMill:
      if agent.inventoryWater > 0:
        var target = findFertileTarget(env, basePos, fertileRadius, state.pathBlockedTarget)
        if target.x < 0:
          target = findFertileTarget(env, agent.pos, fertileRadius, state.pathBlockedTarget)
        if target.x >= 0:
          return actOrMove(controller, env, agent, agentId, state, target, 3'u16)
      else:
        let (didWater, actWater) = controller.ensureWater(env, agent, agentId, state)
        if didWater: return actWater

  if state.closestFoodPos.x >= 0:
    if state.closestFoodPos == state.pathBlockedTarget or
       isResourceReserved(teamId, state.closestFoodPos, agent.agentId):
      state.closestFoodPos = ivec2(-1, -1)
    else:
      let knownThing = env.getThing(state.closestFoodPos)
      if isNil(knownThing) or knownThing.kind notin FoodKinds or isThingFrozen(knownThing, env):
        state.closestFoodPos = ivec2(-1, -1)
      else:
        let verb = if knownThing.kind == Cow:
          let foodCritical = env.stockpileCount(teamId, ResourceFood) < 3
          let cowHealthy = knownThing.hp * 2 >= knownThing.maxHp
          if cowHealthy and not foodCritical: 3'u16 else: 2'u16
        else:
          3'u16
        discard reserveResource(teamId, agent.agentId, knownThing.pos, env.currentStep)
        return actOrMove(controller, env, agent, agentId, state, knownThing.pos, verb)

  for kind in [Wheat, Stubble]:
    let wheat = env.findNearestThingSpiral(state, kind)
    if isNil(wheat):
      continue
    if wheat.pos == state.pathBlockedTarget:
      state.cachedThingPos[kind] = ivec2(-1, -1)
      continue
    if isResourceReserved(teamId, wheat.pos, agent.agentId):
      continue
    updateClosestSeen(state, state.basePosition, wheat.pos, state.closestFoodPos)
    discard reserveResource(teamId, agent.agentId, wheat.pos, env.currentStep)
    return actOrMove(controller, env, agent, agentId, state, wheat.pos, 3'u16)

  let (didHunt, actHunt) = controller.ensureHuntFood(env, agent, agentId, state)
  if didHunt: return actHunt
  return controller.moveNextSearch(env, agent, agentId, state)

optionGuard(canStartGathererIrrigate, shouldTerminateGathererIrrigate):
  agent.inventoryWater > 0

proc optGathererIrrigate(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let basePos = agent.getBasePos()
  let target = findIrrigationTarget(env, basePos, 6)
  if target.x < 0:
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, target, 3'u16)

optionGuard(canStartGathererScavenge, shouldTerminateGathererScavenge):
  gathererStockpileTotal(agent) < ResourceCarryCapacity and env.thingsByKind[Skeleton].len > 0

proc optGathererScavenge(controller: Controller, env: Environment, agent: Thing,
                         agentId: int, state: var AgentState): uint16 =
  let skeleton = env.findNearestThingSpiral(state, Skeleton)
  if isNil(skeleton):
    return 0'u16
  return actOrMove(controller, env, agent, agentId, state, skeleton.pos, 3'u16)

optionGuard(canStartGathererPredatorFlee, shouldTerminateGathererPredatorFlee):
  not isNil(findNearestPredatorInRadius(env, agent.pos, GathererFleeRadius))

proc optGathererPredatorFlee(controller: Controller, env: Environment, agent: Thing,
                     agentId: int, state: var AgentState): uint16 =
  ## Flee away from predators toward friendly structures.
  let predator = findNearestPredatorInRadius(env, agent.pos, GathererFleeRadius)
  if isNil(predator):
    return 0'u16
  fleeAwayFrom(controller, env, agent, agentId, state, predator.pos)

optionGuard(canStartGathererFollow, shouldTerminateGathererFollow):
  ## Follow activates when follow mode is enabled and target is valid and alive.
  hasLiveFollowTarget(env, state)

proc optGathererFollow(controller: Controller, env: Environment, agent: Thing,
                       agentId: int, state: var AgentState): uint16 =
  ## Stay close to the followed agent without attacking.
  let target = resolveFollowTarget(env, state)
  if isNil(target):
    return 0'u16
  maintainFollowProximity(controller, env, agent, agentId, state, target)

proc gathererTaskToPatchKind(task: GathererTask): ResourcePatchKind =
  case task
  of TaskWood: PatchWood
  of TaskGold: PatchGold
  of TaskStone: PatchStone
  of TaskFood: PatchFood
  of TaskHearts: PatchGold

proc canStartGathererIdleAutoAssign(controller: Controller, env: Environment, agent: Thing,
                                    agentId: int, state: var AgentState): bool =
  ## Activate when the gatherer has been idle (no active task producing movement)
  ## for IdleAutoAssignSteps consecutive steps.
  if agent.isIdle and state.activeOptionTicks >= IdleAutoAssignSteps:
    let teamId = getTeamId(agent)
    let pk = gathererTaskToPatchKind(state.gathererTask)
    let patchPos = findUnderstaffedPatchPos(env, agent.pos, teamId, pk)
    return patchPos.x >= 0
  false

proc shouldTerminateGathererIdleAutoAssign(controller: Controller, env: Environment, agent: Thing,
                                           agentId: int, state: var AgentState): bool =
  ## Terminate once the gatherer reaches the patch area or starts gathering.
  gathererStockpileTotal(agent) > 0 or not agent.isIdle

proc optGathererIdleAutoAssign(controller: Controller, env: Environment, agent: Thing,
                               agentId: int, state: var AgentState): uint16 =
  ## Move idle gatherer toward the nearest undermanned resource patch.
  let teamId = getTeamId(agent)
  let pk = gathererTaskToPatchKind(state.gathererTask)
  let patchPos = findUnderstaffedPatchPos(env, agent.pos, teamId, pk)
  if patchPos.x < 0:
    return 0'u16
  controller.moveTo(env, agent, agentId, state, patchPos)

let GathererOptions* = [
  TownBellGarrisonOption,
  OptionDef(
    name: "GathererFlee",
    canStart: canStartGathererFlee,
    shouldTerminate: shouldTerminateGathererFlee,
    act: optGathererFlee,
    interruptible: false
  ),
  OptionDef(
    name: "GathererGarrison",
    canStart: canStartGathererGarrison,
    shouldTerminate: shouldTerminateGathererGarrison,
    act: optGathererGarrison,
    interruptible: false
  ),
  OptionDef(
    name: "GathererPredatorFlee",
    canStart: canStartGathererPredatorFlee,
    shouldTerminate: shouldTerminateGathererPredatorFlee,
    act: optGathererPredatorFlee,
    interruptible: false
  ),
  OptionDef(
    name: "GathererFollow",
    canStart: canStartGathererFollow,
    shouldTerminate: shouldTerminateGathererFollow,
    act: optGathererFollow,
    interruptible: true
  ),
  EmergencyHealOption,
  OptionDef(
    name: "GathererPlantOnFertile",
    canStart: canStartGathererPlantOnFertile,
    shouldTerminate: shouldTerminateGathererPlantOnFertile,
    act: optPlantOnFertile,
    interruptible: true
  ),
  MarketTradeOption,
  OptionDef(
    name: "GathererCarryingStockpile",
    canStart: canStartGathererCarrying,
    shouldTerminate: shouldTerminateGathererCarrying,
    act: optGathererCarrying,
    interruptible: true
  ),
  OptionDef(
    name: "GathererHearts",
    canStart: canStartGathererHearts,
    shouldTerminate: shouldTerminateGathererHearts,
    act: optGathererHearts,
    interruptible: true
  ),
  OptionDef(
    name: "GathererResource",
    canStart: canStartGathererResource,
    shouldTerminate: shouldTerminateGathererResource,
    act: optGathererResource,
    interruptible: true
  ),
  OptionDef(
    name: "GathererFood",
    canStart: canStartGathererFood,
    shouldTerminate: shouldTerminateGathererFood,
    act: optGathererFood,
    interruptible: true
  ),
  OptionDef(
    name: "GathererIrrigate",
    canStart: canStartGathererIrrigate,
    shouldTerminate: shouldTerminateGathererIrrigate,
    act: optGathererIrrigate,
    interruptible: true
  ),
  OptionDef(
    name: "GathererScavenge",
    canStart: canStartGathererScavenge,
    shouldTerminate: shouldTerminateGathererScavenge,
    act: optGathererScavenge,
    interruptible: true
  ),
  StoreValuablesOption,
  OptionDef(
    name: "GathererIdleAutoAssign",
    canStart: canStartGathererIdleAutoAssign,
    shouldTerminate: shouldTerminateGathererIdleAutoAssign,
    act: optGathererIdleAutoAssign,
    interruptible: true
  ),
  FallbackSearchOption
]
