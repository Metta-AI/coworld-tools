import ai_core
export ai_core

const
  EconomyTrackingWindow* = 60
  MinGatherersRatio* = 0.3
  MaxGatherersRatio* = 0.7
  MinBuildersRatio* = 0.1
  MaxBuildersRatio* = 0.4
  MinFightersRatio* = 0.1
  CriticalFoodLevel* = 3
  CriticalWoodLevel* = 5

type
  ResourceSnapshot* = object
    food*: int
    wood*: int
    stone*: int
    gold*: int
    step*: int

  ResourceFlowRate* = object
    foodPerStep*: float
    woodPerStep*: float
    stonePerStep*: float
    goldPerStep*: float

  WorkerCounts* = object
    gatherers*: int
    builders*: int
    fighters*: int
    total*: int

  BottleneckKind* = enum
    NoBottleneck
    TooManyGatherers
    TooFewGatherers
    TooManyBuilders
    TooFewBuilders
    TooFewFighters
    FoodCritical
    WoodCritical
    StoneCritical

  EconomyState* = object
    snapshots*: array[EconomyTrackingWindow, ResourceSnapshot]
    snapshotIndex*: int
    snapshotCount*: int
    flowRate*: ResourceFlowRate
    currentBottleneck*: BottleneckKind

var
  teamEconomy*: array[MapRoomObjectsTeams, EconomyState]
  workerCountCacheStep = -1
  workerCountCache: array[
    MapRoomObjectsTeams,
    tuple[counts: WorkerCounts, hasEnemy: bool]
  ]

proc recordSnapshot*(teamId: int, env: Environment) =
  ## Record current stockpile levels for resource flow tracking.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return

  template st: untyped = teamEconomy[teamId]
  let idx = st.snapshotIndex
  st.snapshots[idx] = ResourceSnapshot(
    food: env.stockpileCount(teamId, ResourceFood),
    wood: env.stockpileCount(teamId, ResourceWood),
    stone: env.stockpileCount(teamId, ResourceStone),
    gold: env.stockpileCount(teamId, ResourceGold),
    step: env.currentStep
  )
  st.snapshotIndex = (idx + 1) mod EconomyTrackingWindow
  if st.snapshotCount < EconomyTrackingWindow:
    inc st.snapshotCount

proc calculateFlowRate*(teamId: int): ResourceFlowRate =
  ## Calculate resource flow rates from recent snapshots.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return ResourceFlowRate()

  let state = teamEconomy[teamId]
  if state.snapshotCount < 2:
    return ResourceFlowRate()

  let newestIdx =
    (state.snapshotIndex - 1 + EconomyTrackingWindow) mod EconomyTrackingWindow
  let oldestIdx = if state.snapshotCount >= EconomyTrackingWindow:
    state.snapshotIndex
  else:
    0

  let newest = state.snapshots[newestIdx]
  let oldest = state.snapshots[oldestIdx]
  let stepDiff = newest.step - oldest.step

  if stepDiff <= 0:
    return ResourceFlowRate()

  let divisor = float(stepDiff)
  result.foodPerStep = float(newest.food - oldest.food) / divisor
  result.woodPerStep = float(newest.wood - oldest.wood) / divisor
  result.stonePerStep = float(newest.stone - oldest.stone) / divisor
  result.goldPerStep = float(newest.gold - oldest.gold) / divisor

proc updateFlowRate*(teamId: int) =
  ## Update the cached flow rate.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  teamEconomy[teamId].flowRate = calculateFlowRate(teamId)

proc getFlowRate*(teamId: int): ResourceFlowRate =
  ## Get the current resource flow rate.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return ResourceFlowRate()
  teamEconomy[teamId].flowRate

proc countWorkersAndEnemies*(
  controller: Controller,
  env: Environment,
  teamId: int
): tuple[counts: WorkerCounts, hasEnemy: bool] =
  ## Count workers and cache enemy presence for the current step.
  if workerCountCacheStep != env.currentStep:
    workerCountCacheStep = env.currentStep
    for t in 0 ..< MapRoomObjectsTeams:
      workerCountCache[t] = (WorkerCounts(), false)
    for agent in env.agents:
      if not isAgentAlive(env, agent):
        continue
      let agentTeam = getTeamId(agent)
      if agentTeam < 0 or agentTeam >= MapRoomObjectsTeams:
        continue
      for t in 0 ..< MapRoomObjectsTeams:
        if t != agentTeam:
          workerCountCache[t].hasEnemy = true
      inc workerCountCache[agentTeam].counts.total
      let agentId = agent.agentId
      if agentId < 0 or agentId >= MapAgents or
          not controller.agentsInitialized[agentId]:
        inc workerCountCache[agentTeam].counts.gatherers
        continue
      case controller.agents[agentId].role
      of Gatherer:
        inc workerCountCache[agentTeam].counts.gatherers
      of Builder:
        inc workerCountCache[agentTeam].counts.builders
      of Fighter:
        inc workerCountCache[agentTeam].counts.fighters
      of Scripted:
        inc workerCountCache[agentTeam].counts.gatherers
  if teamId >= 0 and teamId < MapRoomObjectsTeams:
    return workerCountCache[teamId]
  (WorkerCounts(), false)

proc countWorkers*(
  controller: Controller,
  env: Environment,
  teamId: int
): WorkerCounts =
  ## Count agents by role for a team.
  countWorkersAndEnemies(controller, env, teamId).counts

proc detectBottleneck*(
  controller: Controller,
  env: Environment,
  teamId: int
): BottleneckKind =
  ## Detect economic bottlenecks for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return NoBottleneck

  let gameProgress = if env.config.maxSteps > 0:
    env.currentStep.float / env.config.maxSteps.float
  else:
    0.5
  let critFood =
    if gameProgress < EarlyGameThreshold:
      CriticalFoodLevel + 2
    else:
      CriticalFoodLevel
  let critWood =
    if gameProgress < EarlyGameThreshold:
      CriticalWoodLevel + 3
    else:
      CriticalWoodLevel

  if env.stockpileCount(teamId, ResourceFood) < critFood:
    return FoodCritical
  if env.stockpileCount(teamId, ResourceWood) < critWood:
    return WoodCritical

  let (counts, hasEnemy) = countWorkersAndEnemies(controller, env, teamId)
  if counts.total == 0:
    return NoBottleneck

  let total = float(counts.total)
  let fighterRatio = float(counts.fighters) / total

  if hasEnemy and fighterRatio < MinFightersRatio:
    return TooFewFighters

  let gathererRatio = float(counts.gatherers) / total
  if gathererRatio > MaxGatherersRatio:
    return TooManyGatherers
  if gathererRatio < MinGatherersRatio:
    return TooFewGatherers

  let builderRatio = float(counts.builders) / total
  if builderRatio > MaxBuildersRatio:
    return TooManyBuilders
  if builderRatio < MinBuildersRatio:
    return TooFewBuilders

  NoBottleneck

proc updateBottleneck*(controller: Controller, env: Environment, teamId: int) =
  ## Update the current bottleneck state.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  teamEconomy[teamId].currentBottleneck = detectBottleneck(controller, env, teamId)

proc getCurrentBottleneck*(teamId: int): BottleneckKind =
  ## Get the current bottleneck for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return NoBottleneck
  teamEconomy[teamId].currentBottleneck

proc updateEconomy*(controller: Controller, env: Environment, teamId: int) =
  ## Update one team's economy state for the current step.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return

  let step = env.currentStep

  if step mod 5 == 0:
    recordSnapshot(teamId, env)

  if step mod 10 == 0:
    updateFlowRate(teamId)

  if step mod 3 == 0:
    updateBottleneck(controller, env, teamId)

proc resetEconomy*() =
  ## Reset all economy state.
  zeroMem(addr teamEconomy, sizeof(teamEconomy))
  workerCountCacheStep = -1

const
  TributeCheckInterval* = 50
  TributeSurplusThreshold* = 8
  TributeDeficitThreshold* = 3
  TributeAmountFraction* = 0.25

proc evaluateTribute*(env: Environment, teamId: int) =
  ## Transfer surplus resources to the most resource-starved team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return

  for res in [ResourceFood, ResourceWood, ResourceGold, ResourceStone]:
    let ownStock = env.stockpileCount(teamId, res)
    if ownStock <= TributeSurplusThreshold:
      continue

    var bestTarget = -1
    var lowestStock = TributeDeficitThreshold
    for otherTeam in 0 ..< MapRoomObjectsTeams:
      if otherTeam == teamId:
        continue
      let otherStock = env.stockpileCount(otherTeam, res)
      if otherStock < lowestStock:
        lowestStock = otherStock
        bestTarget = otherTeam

    if bestTarget < 0:
      continue

    let surplus = ownStock - TributeSurplusThreshold
    let tributeAmount =
      max(TributeMinAmount, int(float(surplus) * TributeAmountFraction))

    discard env.tributeResources(teamId, bestTarget, res, tributeAmount)
