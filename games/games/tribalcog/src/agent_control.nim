import
  std/[os, strutils],
  formations, scripted/ai_defaults

export ai_defaults, formations

when defined(stepTiming):
  import std/[algorithm, monotimes]
  import envconfig

  let
    aiTimingEnabled = parseEnvBool("TV_AI_TIMING", false)
    aiTimingInterval = parseEnvInt("TV_AI_TIMING_INTERVAL", 100)
    aiTimingTopN = parseEnvInt("TV_AI_TIMING_TOP_N", 10)

  var
    aiTimingCumTotal: float64 = 0.0
    aiTimingCumMax: float64 = 0.0
    aiTimingStepCount: int = 0
    aiTimingAgentCum: array[MapAgents, float64]
    aiTimingAgentMax: array[MapAgents, float64]
    aiTimingAgentCount: array[MapAgents, int]

  proc aiMsBetween(a, b: MonoTime): float64 =
    ## Return the elapsed time in milliseconds between two timestamps.
    (b.ticks - a.ticks).float64 / 1_000_000.0

  proc resetAiTimingCounters() =
    ## Clear accumulated AI timing counters.
    aiTimingCumTotal = 0.0
    aiTimingCumMax = 0.0
    aiTimingStepCount = 0
    for i in 0 ..< MapAgents:
      aiTimingAgentCum[i] = 0.0
      aiTimingAgentMax[i] = 0.0
      aiTimingAgentCount[i] = 0

  proc printAiTimingReport(currentStep: int) =
    ## Print the aggregated AI timing report for the current window.
    if aiTimingStepCount == 0:
      return
    let n = aiTimingStepCount.float64

    type AgentTimingEntry =
      tuple[agentId: int, cumMs: float64, maxMs: float64, count: int]

    var entries: seq[AgentTimingEntry] = @[]
    for i in 0 ..< MapAgents:
      if aiTimingAgentCount[i] > 0:
        entries.add((
          agentId: i,
          cumMs: aiTimingAgentCum[i],
          maxMs: aiTimingAgentMax[i],
          count: aiTimingAgentCount[i]
        ))

    entries.sort(proc(a, b: AgentTimingEntry): int =
      if a.cumMs > b.cumMs:
        -1
      elif a.cumMs < b.cumMs:
        1
      else:
        0
    )

    echo ""
    echo(
      "=== AI Decision Timing Report (steps ",
      currentStep - aiTimingStepCount + 1,
      "-",
      currentStep,
      ", n=",
      aiTimingStepCount,
      ") ==="
    )
    echo(
      "Total AI decision time: avg=",
      formatFloat(aiTimingCumTotal / n, ffDecimal, 4),
      "ms, max=",
      formatFloat(aiTimingCumMax, ffDecimal, 4),
      "ms"
    )
    echo ""
    echo "Top ", aiTimingTopN, " slowest agents (by cumulative time):"
    echo(
      align("Agent", 8),
      " | ",
      align("Avg ms", 10),
      " | ",
      align("Max ms", 10),
      " | ",
      align("Decisions", 10)
    )
    echo(
      repeat("-", 8),
      "-+-",
      repeat("-", 10),
      "-+-",
      repeat("-", 10),
      "-+-",
      repeat("-", 10)
    )

    let showCount = min(aiTimingTopN, entries.len)
    for i in 0 ..< showCount:
      let e = entries[i]
      let avgMs = e.cumMs / e.count.float64
      echo align($e.agentId, 8), " | ",
           align(formatFloat(avgMs, ffDecimal, 4), 10), " | ",
           align(formatFloat(e.maxMs, ffDecimal, 4), 10), " | ",
           align($e.count, 10)
    echo ""
    resetAiTimingCounters()

const
  ActionsFile = "actions.tmp"

template withBuiltinAI(body: untyped) =
  ## Run `body` only when the global controller uses built-in AI state.
  if not isNil(globalController) and globalController.controllerType in {BuiltinAI, HybridAI}:
    body

proc lookupAliveAgent(env: Environment, agentId: int): Thing =
  ## Return the live agent for `agentId`, or nil when unavailable.
  if agentId < 0 or agentId >= env.agents.len:
    return nil
  result = env.agents[agentId]
  if not isAgentAlive(env, result):
    return nil

proc lookupBuilding(env: Environment, buildingX, buildingY: int32): Thing =
  ## Return the building at the given position, or nil when absent.
  let pos = ivec2(buildingX, buildingY)
  if not isValidPos(pos):
    return nil
  result = env.grid[pos.x][pos.y]
  if isNil(result) or not isBuildingKind(result.kind):
    return nil

proc lookupTrainRequest(env: Environment, buildingX, buildingY, teamId,
                        unitClass: int32, building: var Thing,
                        requestedClass: var AgentUnitClass): bool =
  ## Validate a training request and return the resolved building and unit.
  building = lookupBuilding(env, buildingX, buildingY)
  if isNil(building) or not buildingHasTrain(building.kind):
    return false
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return false
  requestedClass = AgentUnitClass(unitClass)
  if teamId >= 0 and teamId < MapRoomObjectsTeams and
      requestedClass in env.teamModifiers[teamId].disabledUnits:
    return false
  requestedClass == buildingTrainUnit(building.kind, teamId.int)

type
  ControllerType* = enum
    BuiltinAI,
    ExternalNN,
    HybridAI

  AgentController* = ref object
    controllerType*: ControllerType
    aiController*: Controller
    externalActionCallback*: proc(): array[MapAgents, uint16]

var globalController*: AgentController

proc initGlobalController*(controllerType: ControllerType, seed: int = int(nowSeconds() * 1000)) =
  ## Initialize the global agent controller for the selected backend.
  initAuditLog()
  case controllerType:
  of BuiltinAI:
    globalController = AgentController(
      controllerType: BuiltinAI,
      aiController: newController(seed),
      externalActionCallback: nil
    )
  of ExternalNN:
    globalController = AgentController(
      controllerType: ExternalNN,
      aiController: nil,
      externalActionCallback: nil
    )
    play = true
  of HybridAI:
    globalController = AgentController(
      controllerType: HybridAI,
      aiController: newController(seed),
      externalActionCallback: nil
    )
    play = true

proc setExternalActionCallback*(callback: proc(): array[MapAgents, uint16]) =
  ## Register the external callback used by non-built-in controllers.
  if not isNil(globalController) and
      globalController.controllerType in {ExternalNN, HybridAI}:
    globalController.externalActionCallback = callback

proc getActions*(env: Environment): array[MapAgents, uint16] =
  ## Return actions for all agents using the configured controller.
  case globalController.controllerType
  of BuiltinAI:
    var actions: array[MapAgents, uint16]
    let controller = globalController.aiController

    when defined(stepTiming):
      var tLoopStart, tAgentStart, tAgentEnd: MonoTime
      var tLoopTotalMs: float64 = 0.0
      if aiTimingEnabled:
        tLoopStart = getMonoTime()

    for i in 0 ..< env.agents.len:
      when defined(stepTiming):
        if aiTimingEnabled:
          tAgentStart = getMonoTime()

      setAuditBranch(BranchInactive)
      actions[i] = controller.decideAction(env, i)

      when defined(stepTiming):
        if aiTimingEnabled:
          tAgentEnd = getMonoTime()
          let agentMs = aiMsBetween(tAgentStart, tAgentEnd)
          aiTimingAgentCum[i] += agentMs
          if agentMs > aiTimingAgentMax[i]:
            aiTimingAgentMax[i] = agentMs
          inc aiTimingAgentCount[i]

      when defined(aiAudit):
        let agent = env.agents[i]
        let teamId = if not agent.isNil: getTeamId(agent) else: -1
        let role =
          if controller.agentsInitialized[i]:
            controller.agents[i].role
          else:
            Gatherer
        recordAuditDecision(i, teamId, role, actions[i])

    when defined(stepTiming):
      if aiTimingEnabled:
        let tLoopEnd = getMonoTime()
        tLoopTotalMs = aiMsBetween(tLoopStart, tLoopEnd)
        aiTimingCumTotal += tLoopTotalMs
        if tLoopTotalMs > aiTimingCumMax:
          aiTimingCumMax = tLoopTotalMs
        inc aiTimingStepCount
        if aiTimingStepCount >= aiTimingInterval:
          printAiTimingReport(env.currentStep.int)

    controller.updateController(env)
    printAuditSummary(env.currentStep.int)
    return actions
  of ExternalNN:
    if not isNil(globalController.externalActionCallback):
      return globalController.externalActionCallback()

    if fileExists(ActionsFile):
      try:
        let lines = readFile(ActionsFile)
          .replace("\r", "")
          .replace("\n\n", "\n")
          .split("\n")
        if lines.len >= MapAgents:
          var fileActions: array[MapAgents, uint16]
          for i in 0 ..< MapAgents:
            let parts = lines[i].split(',')
            if parts.len >= 2:
              fileActions[i] = encodeAction(
                parseInt(parts[0]).uint16,
                parseInt(parts[1]).uint16
              )
            elif parts.len == 1 and parts[0].len > 0:
              fileActions[i] = parseInt(parts[0]).uint16

          discard tryRemoveFile(ActionsFile)

          return fileActions
      except IOError, OSError, ValueError:
        discard

    echo "ExternalNN controller has no callback or actions file."
    echo "Python must call setExternalActionCallback() or provide " &
      ActionsFile & "."
    raise newException(
      ValueError,
      "ExternalNN controller has no actions; Python communication failed."
    )
  of HybridAI:
    var actions: array[MapAgents, uint16]
    let controller = globalController.aiController

    for i in 0 ..< env.agents.len:
      setAuditBranch(BranchInactive)
      actions[i] = controller.decideAction(env, i)

    controller.updateController(env)
    printAuditSummary(env.currentStep.int)
    return actions

proc setAgentAttackMoveTarget*(agentId: int, target: IVec2) =
  ## Set an attack-move target for an agent.
  ## The agent will move toward the target while engaging enemies along the way.
  ## Requires BuiltinAI controller. Clears any stopped state.
  withBuiltinAI:
    if agentId >= 0 and agentId < MapAgents:
      globalController.aiController.clearAgentStop(agentId)
      globalController.aiController.agents[agentId].attackMoveTarget = target

proc clearAgentAttackMoveTarget*(agentId: int) =
  ## Clear the attack-move target for an agent, stopping attack-move behavior.
  withBuiltinAI:
    if agentId >= 0 and agentId < MapAgents:
      globalController.aiController.agents[agentId].attackMoveTarget = ivec2(-1, -1)

proc getAgentAttackMoveTarget*(agentId: int): IVec2 =
  ## Get the current attack-move target for an agent.
  ## Returns (-1, -1) if no attack-move is active.
  withBuiltinAI:
    if agentId >= 0 and agentId < MapAgents:
      return globalController.aiController.agents[agentId].attackMoveTarget
  ivec2(-1, -1)

proc isAgentAttackMoveActive*(agentId: int): bool =
  ## Check if an agent currently has an active attack-move target.
  let target = getAgentAttackMoveTarget(agentId)
  target.x >= 0

proc setAgentPatrol*(agentId: int, point1, point2: IVec2) =
  ## Set patrol waypoints for an agent. Enables patrol mode.
  ## The agent will walk between the two points, attacking any enemies encountered.
  ## Requires BuiltinAI controller. Clears any stopped state.
  withBuiltinAI:
    globalController.aiController.clearAgentStop(agentId)
    globalController.aiController.setPatrol(agentId, point1, point2)

proc clearAgentPatrol*(agentId: int) =
  ## Clear the patrol for an agent, disabling patrol mode.
  withBuiltinAI:
    globalController.aiController.clearPatrol(agentId)

proc getAgentPatrolTarget*(agentId: int): IVec2 =
  ## Get the current patrol target waypoint for an agent.
  ## Returns (-1, -1) if no patrol is active.
  withBuiltinAI:
    return globalController.aiController.getPatrolTarget(agentId)
  ivec2(-1, -1)

proc isAgentPatrolActive*(agentId: int): bool =
  ## Check if an agent currently has patrol mode active.
  withBuiltinAI:
    return globalController.aiController.isPatrolActive(agentId)
  false

proc setAgentStance*(agentId: int, stance: AgentStance) =
  ## Set the combat stance for an agent (deferred).
  ## The stance will be applied on the next decideAction call.
  ## Requires BuiltinAI controller.
  withBuiltinAI:
    globalController.aiController.setAgentStanceDeferred(agentId, stance)

proc getAgentStance*(agentId: int): AgentStance =
  ## Get the pending combat stance for an agent.
  ## Returns the pending stance if one has been set via setAgentStance(agentId, stance).
  ## Returns StanceDefensive if no stance has been set or if not using BuiltinAI.
  ## Note: To get the agent's current actual stance, use getAgentStance(env, agentId).
  withBuiltinAI:
    return globalController.aiController.getAgentPendingStance(agentId)
  StanceDefensive

proc setAgentStance*(env: Environment, agentId: int, stance: AgentStance) =
  ## Set the combat stance for an agent (immediate, requires env).
  let agent = lookupAliveAgent(env, agentId)
  if not isNil(agent):
    agent.stance = stance

proc getAgentStance*(env: Environment, agentId: int): AgentStance =
  ## Get the current combat stance for an agent (requires env).
  let agent = lookupAliveAgent(env, agentId)
  if not isNil(agent):
    return agent.stance
  StanceDefensive

proc garrisonAgentInBuilding*(env: Environment, agentId: int, buildingX, buildingY: int32): bool =
  ## Garrison an agent into the building at the given position.
  ## Returns true if successful.
  let agent = lookupAliveAgent(env, agentId)
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(agent) or isNil(thing):
    return false
  garrisonUnitInBuilding(env, agent, thing)

proc ungarrisonAllFromBuilding*(env: Environment, buildingX, buildingY: int32): int32 =
  ## Ungarrison all units from the building at the given position.
  ## Returns the number of units ungarrisoned.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return 0
  let units = ungarrisonAllUnits(env, thing)
  units.len.int32

proc getGarrisonCount*(env: Environment, buildingX, buildingY: int32): int32 =
  ## Get the number of units garrisoned in the building at the given position.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return 0
  thing.garrisonedUnits.len.int32

proc isAgentGarrisoned*(env: Environment, agentId: int): bool =
  ## Check if an agent is currently garrisoned inside a building.
  ## Note: Garrisoned agents are NOT on the grid (pos is -1,-1), so we check
  ## terminated status directly rather than isAgentAlive (which requires grid presence).
  if agentId < 0 or agentId >= env.agents.len:
    return false
  if env.terminated[agentId] != 0.0:
    return false
  let agent = env.agents[agentId]
  agent.isGarrisoned

proc queueUnitTraining*(env: Environment, buildingX, buildingY: int32, teamId: int32): bool =
  ## Queue a unit for training at the building at the given position.
  ## The unit type and cost are determined by the building type.
  ## Returns true if successfully queued.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return false
  if not buildingHasTrain(thing.kind):
    return false
  let unitClass = buildingTrainUnit(thing.kind, teamId)
  let costs = buildingTrainCosts(thing.kind)
  queueTrainUnit(env, thing, teamId, unitClass, costs)

proc cancelLastQueuedUnit*(env: Environment, buildingX, buildingY: int32): bool =
  ## Cancel the last unit in the production queue at the given building.
  ## Returns true if a unit was cancelled.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return false
  cancelLastQueued(env, thing)

proc getProductionQueueSize*(env: Environment, buildingX, buildingY: int32): int32 =
  ## Get the number of units in the production queue at the given building.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return 0
  thing.productionQueue.entries.len.int32

proc getProductionQueueEntryProgress*(env: Environment, buildingX,
                                      buildingY: int32,
                                      index: int32): int32 =
  ## Get the remaining steps for a production queue entry.
  ## Returns -1 if invalid.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return -1
  if index < 0 or index >= thing.productionQueue.entries.len.int32:
    return -1
  thing.productionQueue.entries[index].remainingSteps.int32

proc canBuildingTrainUnit*(env: Environment, buildingX, buildingY: int32,
                           unitClass: int32, teamId: int32): bool =
  ## Check if a building can train the specified unit class.
  ## Returns true if the building supports training this unit type.
  var thing: Thing
  var requestedClass: AgentUnitClass
  lookupTrainRequest(env, buildingX, buildingY, teamId, unitClass, thing, requestedClass)

proc queueUnitTrainingWithClass*(env: Environment, buildingX, buildingY: int32,
                                 teamId: int32,
                                 unitClass: int32): bool =
  ## Queue a specific unit class for training at the building.
  ## Validates that the building can produce the requested unit class.
  ## Returns true if successfully queued.
  var thing: Thing
  var requestedClass: AgentUnitClass
  if not lookupTrainRequest(env, buildingX, buildingY, teamId, unitClass, thing, requestedClass):
    return false
  var costs = buildingTrainCosts(thing.kind)
  # Apply per-unit cost multiplier
  if teamId >= 0 and teamId < MapRoomObjectsTeams:
    let mult = env.teamModifiers[teamId].trainCostMultiplier[requestedClass]
    if mult != 0.0'f32 and mult != 1.0'f32:
      for i in 0 ..< costs.len:
        costs[i] = (
          res: costs[i].res,
          count: max(1, int(float32(costs[i].count) * mult + 0.5))
        )
  queueTrainUnit(env, thing, teamId.int, requestedClass, costs)

proc cancelAllTrainingQueue*(env: Environment, buildingX, buildingY: int32): int32 =
  ## Cancel all units in the production queue at the given building.
  ## Returns the number of units cancelled (resources are refunded for each).
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return 0
  var cancelled: int32 = 0
  while thing.productionQueue.entries.len > 0:
    if cancelLastQueued(env, thing):
      inc cancelled
    else:
      break
  cancelled

proc getProductionQueueEntryUnitClass*(env: Environment, buildingX,
                                       buildingY: int32,
                                       index: int32): int32 =
  ## Get the unit class for a production queue entry.
  ## Returns -1 if invalid, otherwise the AgentUnitClass enum ordinal.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return -1
  if index < 0 or index >= thing.productionQueue.entries.len.int32:
    return -1
  ord(thing.productionQueue.entries[index].unitClass).int32

proc getProductionQueueEntryTotalSteps*(env: Environment, buildingX,
                                        buildingY: int32,
                                        index: int32): int32 =
  ## Get the total training steps for a production queue entry.
  ## Returns -1 if invalid.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return -1
  if index < 0 or index >= thing.productionQueue.entries.len.int32:
    return -1
  thing.productionQueue.entries[index].totalSteps.int32

proc isProductionQueueReady*(env: Environment, buildingX, buildingY: int32): bool =
  ## Check if the building has a queue entry ready for unit conversion.
  ## Returns true if the front entry has completed training.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return false
  productionQueueHasReady(thing)

proc researchBlacksmithUpgrade*(env: Environment, agentId: int, buildingX, buildingY: int32): bool =
  ## Research the next blacksmith upgrade at the given building.
  ## The agent must be a villager at the building.
  let agent = lookupAliveAgent(env, agentId)
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(agent) or isNil(thing) or thing.kind != Blacksmith:
    return false
  tryResearchBlacksmithUpgrade(env, agent, thing)

proc researchUniversityTech*(env: Environment, agentId: int, buildingX, buildingY: int32): bool =
  ## Research the next university technology at the given building.
  let agent = lookupAliveAgent(env, agentId)
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(agent) or isNil(thing) or thing.kind != University:
    return false
  tryResearchUniversityTech(env, agent, thing)

proc researchCastleTech*(env: Environment, agentId: int, buildingX, buildingY: int32): bool =
  ## Research the next castle unique technology at the given building.
  let agent = lookupAliveAgent(env, agentId)
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(agent) or isNil(thing) or thing.kind != Castle:
    return false
  tryResearchCastleTech(env, agent, thing)

proc researchUnitUpgrade*(env: Environment, agentId: int, buildingX, buildingY: int32): bool =
  ## Research the next unit upgrade at the given building.
  let agent = lookupAliveAgent(env, agentId)
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(agent) or isNil(thing):
    return false
  tryResearchUnitUpgrade(env, agent, thing)

proc hasBlacksmithUpgrade*(env: Environment, teamId: int, upgradeType: int32): int32 =
  ## Get the current level of a blacksmith upgrade for a team.
  ## upgradeType: 0=MeleeAttack, 1=ArcherAttack, 2=InfantryArmor, 3=CavalryArmor, 4=ArcherArmor
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if upgradeType < 0 or upgradeType > ord(BlacksmithUpgradeType.high).int32:
    return 0
  env.teamBlacksmithUpgrades[teamId].levels[BlacksmithUpgradeType(upgradeType)].int32

proc hasUniversityTechResearched*(env: Environment, teamId: int, techType: int32): bool =
  ## Check if a university tech has been researched for a team.
  ## techType: 0=Ballistics, 1=MurderHoles, 2=Masonry, etc.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  if techType < 0 or techType > ord(UniversityTechType.high).int32:
    return false
  hasUniversityTech(env, teamId, UniversityTechType(techType))

proc hasCastleTechResearched*(env: Environment, teamId: int, techType: int32): bool =
  ## Check if a castle tech has been researched for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  if techType < 0 or techType > ord(CastleTechType.high).int32:
    return false
  hasCastleTech(env, teamId, CastleTechType(techType))

proc hasUnitUpgradeResearched*(env: Environment, teamId: int, upgradeType: int32): bool =
  ## Check if a unit upgrade has been researched for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  if upgradeType < 0 or upgradeType > ord(UnitUpgradeType.high).int32:
    return false
  hasUnitUpgrade(env, teamId, UnitUpgradeType(upgradeType))

proc setAgentScoutMode*(agentId: int, active: bool) =
  ## Enable or disable scout mode for an agent.
  ## Requires BuiltinAI controller. Clears any stopped state when enabling.
  withBuiltinAI:
    if active:
      globalController.aiController.clearAgentStop(agentId)
    globalController.aiController.setScoutMode(agentId, active)

proc isAgentScoutModeActive*(agentId: int): bool =
  ## Check if an agent has scout mode active.
  withBuiltinAI:
    return globalController.aiController.isScoutModeActive(agentId)
  false

proc getAgentScoutExploreRadius*(agentId: int): int32 =
  ## Get the current scout exploration radius for an agent.
  withBuiltinAI:
    return globalController.aiController.getScoutExploreRadius(agentId)
  0

proc setBuildingRallyPoint*(env: Environment, buildingX, buildingY: int32, rallyX, rallyY: int32) =
  ## Set the rally point for a building.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return
  setRallyPoint(thing, ivec2(rallyX, rallyY))

proc clearBuildingRallyPoint*(env: Environment, buildingX, buildingY: int32) =
  ## Clear the rally point for a building.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return
  clearRallyPoint(thing)

proc getBuildingRallyPoint*(env: Environment, buildingX, buildingY: int32): IVec2 =
  ## Get the rally point for a building. Returns (-1, -1) if no rally point is set.
  let thing = lookupBuilding(env, buildingX, buildingY)
  if isNil(thing):
    return ivec2(-1, -1)
  if hasRallyPoint(thing):
    return thing.rallyPoint
  ivec2(-1, -1)

proc setAgentHoldPosition*(agentId: int, pos: IVec2) =
  ## Set hold position for an agent. The agent stays at the given position,
  ## attacks enemies in range, but won't chase.
  ## Requires BuiltinAI controller. Clears any stopped state.
  withBuiltinAI:
    globalController.aiController.clearAgentStop(agentId)
    globalController.aiController.setHoldPosition(agentId, pos)

proc clearAgentHoldPosition*(agentId: int) =
  ## Clear hold position for an agent.
  withBuiltinAI:
    globalController.aiController.clearHoldPosition(agentId)

proc getAgentHoldPosition*(agentId: int): IVec2 =
  ## Get the hold position target. Returns (-1, -1) if not active.
  withBuiltinAI:
    return globalController.aiController.getHoldPosition(agentId)
  ivec2(-1, -1)

proc isAgentHoldPositionActive*(agentId: int): bool =
  ## Check if hold position is active for an agent.
  withBuiltinAI:
    return globalController.aiController.isHoldPositionActive(agentId)
  false

proc setAgentFollowTarget*(agentId: int, targetAgentId: int) =
  ## Set an agent to follow another agent.
  ## Requires BuiltinAI controller. Clears any stopped state.
  withBuiltinAI:
    globalController.aiController.clearAgentStop(agentId)
    globalController.aiController.setFollowTarget(agentId, targetAgentId)

proc clearAgentFollowTarget*(agentId: int) =
  ## Clear follow target for an agent.
  withBuiltinAI:
    globalController.aiController.clearFollowTarget(agentId)

proc getAgentFollowTargetId*(agentId: int): int =
  ## Get the follow target agent ID. Returns -1 if not active.
  withBuiltinAI:
    return globalController.aiController.getFollowTargetId(agentId)
  -1

proc isAgentFollowActive*(agentId: int): bool =
  ## Check if follow mode is active for an agent.
  withBuiltinAI:
    return globalController.aiController.isFollowActive(agentId)
  false

proc setAgentGuard*(agentId: int, targetAgentId: int) =
  ## Set an agent to guard another agent.
  ## The guarding agent stays within GuardRadius (5 tiles) of the target,
  ## attacks any enemies that enter range, and returns to guard position after combat.
  ## Requires BuiltinAI controller. Clears any stopped state.
  withBuiltinAI:
    globalController.aiController.clearAgentStop(agentId)
    globalController.aiController.setGuardTarget(agentId, targetAgentId)

proc setAgentGuardPosition*(agentId: int, pos: IVec2) =
  ## Set an agent to guard a specific position.
  ## The guarding agent stays within GuardRadius (5 tiles) of the position,
  ## attacks any enemies that enter range, and returns to guard position after combat.
  ## Requires BuiltinAI controller. Clears any stopped state.
  withBuiltinAI:
    globalController.aiController.clearAgentStop(agentId)
    globalController.aiController.setGuardPosition(agentId, pos)

proc clearAgentGuard*(agentId: int) =
  ## Clear guard mode for an agent.
  withBuiltinAI:
    globalController.aiController.clearGuard(agentId)

proc getAgentGuardTargetId*(agentId: int): int =
  ## Get the guard target agent ID. Returns -1 if guarding a position or not active.
  withBuiltinAI:
    return globalController.aiController.getGuardTargetId(agentId)
  -1

proc getAgentGuardPosition*(agentId: int): IVec2 =
  ## Get the guard target position. Returns (-1, -1) if guarding an agent or not active.
  withBuiltinAI:
    return globalController.aiController.getGuardPosition(agentId)
  ivec2(-1, -1)

proc isAgentGuarding*(agentId: int): bool =
  ## Check if guard mode is active for an agent.
  withBuiltinAI:
    return globalController.aiController.isGuardActive(agentId)
  false

proc stopAgent*(agentId: int) =
  ## Stop an agent completely: clears all orders, path, and active option.
  ## Agent will remain idle until given a new command or until StopIdleSteps passes.
  withBuiltinAI:
    globalController.aiController.stopAgentDeferred(agentId)

proc clearAgentStop*(agentId: int) =
  ## Clear the stopped state for an agent, allowing normal behavior to resume.
  ## Called automatically when issuing new movement commands.
  withBuiltinAI:
    globalController.aiController.clearAgentStop(agentId)

proc isAgentStopped*(agentId: int): bool =
  ## Check if an agent is currently in stopped state.
  withBuiltinAI:
    return globalController.aiController.isAgentStopped(agentId)
  false

proc getAgentStoppedUntilStep*(agentId: int): int32 =
  ## Get the step at which the stopped state will expire.
  ## Returns 0 if not stopped or -1 if deferred (not yet initialized).
  withBuiltinAI:
    return globalController.aiController.getAgentStoppedUntilStep(agentId)
  0

proc clearAgentCommandQueue*(agentId: int) =
  ## Clear all queued commands for an agent.
  withBuiltinAI:
    globalController.aiController.clearCommandQueue(agentId)

proc queueAgentAttackMove*(agentId: int, target: IVec2) =
  ## Queue an attack-move command for shift-queue.
  withBuiltinAI:
    globalController.aiController.queueAttackMove(agentId, target)

proc queueAgentFollow*(agentId: int, targetAgentId: int) =
  ## Queue a follow command for shift-queue.
  withBuiltinAI:
    globalController.aiController.queueFollow(agentId, targetAgentId)

proc setControlGroupFormation*(groupIndex: int, formationType: int32) =
  ## Set formation type for a control group.
  ## formationType: 0=None, 1=Line, 2=Box, 3=Wedge, 4=Scatter
  if formationType >= 0 and formationType <= ord(FormationType.high):
    setFormation(groupIndex, FormationType(formationType))

proc getControlGroupFormation*(groupIndex: int): int32 =
  ## Get formation type for a control group.
  ## Returns: 0=None, 1=Line, 2=Box, 3=Wedge, 4=Scatter
  ord(getFormation(groupIndex)).int32

proc findAvailableControlGroup*(): int =
  ## Find an empty control group index, or return the last one (9) as fallback.
  ## Used by setFormationForAgents to allocate a group.
  for i in 0 ..< ControlGroupCount:
    if controlGroups[i].len == 0:
      return i
  # All groups in use - use the last one
  ControlGroupCount - 1

proc setFormationForAgents*(env: Environment, agentIds: seq[int], formationType: FormationType) =
  ## Set formation for a group of agents by their IDs.
  ## This creates a control group containing the specified agents and sets the formation.
  ## If no empty control group is available, uses control group 9 (overwriting it).
  if agentIds.len == 0:
    return
  let groupIndex = findAvailableControlGroup()
  # Assign agents to the control group
  controlGroups[groupIndex] = @[]
  for agentId in agentIds:
    if agentId >= 0 and agentId < env.agents.len:
      let agent = env.agents[agentId]
      if isAgentAlive(env, agent):
        controlGroups[groupIndex].add(agent)
  # Set the formation
  setFormation(groupIndex, formationType)

proc setFormationForAgentsWithRotation*(env: Environment, agentIds: seq[int],
                                         formationType: FormationType, rotation: int) =
  ## Set formation and rotation for a group of agents by their IDs.
  if agentIds.len == 0:
    return
  let groupIndex = findAvailableControlGroup()
  controlGroups[groupIndex] = @[]
  for agentId in agentIds:
    if agentId >= 0 and agentId < env.agents.len:
      let agent = env.agents[agentId]
      if isAgentAlive(env, agent):
        controlGroups[groupIndex].add(agent)
  setFormation(groupIndex, formationType)
  setFormationRotation(groupIndex, rotation)

proc clearFormationForAgents*(agentIds: seq[int]) =
  ## Clear formation for the specified agents.
  ## Finds which control group(s) contain the agents and clears their formations.
  for agentId in agentIds:
    let groupIdx = findAgentControlGroup(agentId)
    if groupIdx >= 0:
      clearFormation(groupIdx)

proc selectUnits*(env: Environment, agentIds: seq[int]) =
  ## Replace current selection with the specified agents.
  selection = @[]
  for agentId in agentIds:
    if agentId >= 0 and agentId < env.agents.len:
      let agent = env.agents[agentId]
      if isAgentAlive(env, agent):
        selection.add(agent)

proc addToSelection*(env: Environment, agentId: int) =
  ## Add a single agent to the current selection (if alive and not already selected).
  if agentId >= 0 and agentId < env.agents.len:
    let agent = env.agents[agentId]
    if isAgentAlive(env, agent):
      for s in selection:
        if s.agentId == agentId:
          return
      selection.add(agent)

proc removeFromSelection*(agentId: int) =
  ## Remove a single agent from the current selection.
  for i in countdown(selection.len - 1, 0):
    if selection[i].agentId == agentId:
      selection.delete(i)
      return

proc clearSelection*() =
  ## Clear the current selection.
  selection = @[]

proc getSelectionCount*(): int =
  ## Get the number of currently selected units.
  selection.len

proc getSelectedAgentId*(index: int): int =
  ## Get the agent ID of a selected unit by index. Returns -1 if invalid index.
  if index >= 0 and index < selection.len:
    selection[index].agentId
  else:
    -1

proc createControlGroup*(env: Environment, groupIndex: int, agentIds: seq[int]) =
  ## Assign agents to a control group (0-9).
  if groupIndex < 0 or groupIndex >= ControlGroupCount:
    return
  controlGroups[groupIndex] = @[]
  for agentId in agentIds:
    if agentId >= 0 and agentId < env.agents.len:
      let agent = env.agents[agentId]
      if isAgentAlive(env, agent):
        controlGroups[groupIndex].add(agent)

proc recallControlGroup*(env: Environment, groupIndex: int) =
  ## Recall a control group into the current selection.
  if groupIndex < 0 or groupIndex >= ControlGroupCount:
    return
  # Filter out dead units
  var alive: seq[Thing] = @[]
  for thing in controlGroups[groupIndex]:
    if isAgentAlive(env, thing):
      alive.add(thing)
  controlGroups[groupIndex] = alive
  selection = alive

proc getControlGroupCount*(groupIndex: int): int =
  ## Get the number of units in a control group. Returns 0 if invalid index.
  if groupIndex >= 0 and groupIndex < ControlGroupCount:
    controlGroups[groupIndex].len
  else:
    0

proc getControlGroupAgentId*(groupIndex: int, index: int): int =
  ## Get the agent ID at a position in a control group. Returns -1 if invalid.
  if groupIndex >= 0 and groupIndex < ControlGroupCount and
     index >= 0 and index < controlGroups[groupIndex].len:
    controlGroups[groupIndex][index].agentId
  else:
    -1

proc issueCommandToSelection*(env: Environment, commandType: int32, targetX, targetY: int32) =
  ## Issue a command to all selected units.
  ## commandType: 0=attack-move, 1=patrol, 2=stop, 3=hold position.
  ## 4=follow target agent, 5=guard target agent, 6=guard position.
  let target = ivec2(targetX, targetY)
  for thing in selection:
    if isAgentAlive(env, thing):
      let agentId = thing.agentId
      case commandType
      of 0:
        setAgentAttackMoveTarget(agentId, target)
      of 1:
        setAgentPatrol(agentId, thing.pos, target)
      of 2:
        stopAgent(agentId)
      of 3:
        setAgentHoldPosition(agentId, thing.pos)
      of 4:
        setAgentFollowTarget(agentId, targetX.int)
      of 5:
        setAgentGuard(agentId, targetX.int)
      of 6:
        setAgentGuardPosition(agentId, target)
      else:
        discard

proc setGathererPriority*(agentId: int, resource: StockpileResource) =
  ## Set an individual gatherer to prioritize collecting a specific resource.
  ## Overrides automatic task selection for this gatherer.
  ## resource: ResourceFood, ResourceWood, ResourceGold, or ResourceStone
  withBuiltinAI:
    globalController.aiController.setGathererPriority(agentId, resource)

proc clearGathererPriority*(agentId: int) =
  ## Clear the individual gatherer priority override.
  ## Returns the gatherer to automatic task selection.
  withBuiltinAI:
    globalController.aiController.clearGathererPriority(agentId)

proc getGathererPriority*(agentId: int): StockpileResource =
  ## Get the current gatherer priority for an agent.
  ## Returns ResourceNone if no priority is set.
  withBuiltinAI:
    return globalController.aiController.getGathererPriority(agentId)
  ResourceNone

proc isGathererPriorityActive*(agentId: int): bool =
  ## Check if an individual gatherer priority is active.
  withBuiltinAI:
    return globalController.aiController.isGathererPriorityActive(agentId)
  false

proc setTeamEconomyFocus*(teamId: int, resource: StockpileResource) =
  ## Set a team-level economy focus to bias all gatherers toward a resource.
  ## This affects all gatherers on the team that don't have individual overrides.
  ## resource: ResourceFood, ResourceWood, ResourceGold, or ResourceStone
  withBuiltinAI:
    globalController.aiController.setTeamEconomyFocus(teamId, resource)

proc clearTeamEconomyFocus*(teamId: int) =
  ## Clear the team-level economy focus.
  ## Returns all gatherers to automatic task selection.
  withBuiltinAI:
    globalController.aiController.clearTeamEconomyFocus(teamId)

proc getTeamEconomyFocus*(teamId: int): StockpileResource =
  ## Get the current team economy focus.
  ## Returns ResourceNone if no focus is set.
  withBuiltinAI:
    return globalController.aiController.getTeamEconomyFocus(teamId)
  ResourceNone

proc isTeamEconomyFocusActive*(teamId: int): bool =
  ## Check if a team economy focus is active.
  withBuiltinAI:
    return globalController.aiController.isTeamEconomyFocusActive(teamId)
  false
