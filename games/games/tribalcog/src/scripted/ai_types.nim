import
  std/[heapqueue, macros],
  vmath,
  ../[entropy, environment, types],
  cache_wrapper

export IVec2, Rand, types, heapqueue, environment, cache_wrapper

const
  MaxPathNodes* = 512
  MaxPathLength* = 256
  MaxPathGoals* = 10
  MaxThreatEntries* = 64
  MaxDamagedBuildingsPerTeam* = 32
  MaxUnlitBuildingsPerTeam* = 64
  MaxCommandQueueSize* = 8

type
  ## Shared threat map entry for team coordination.
  ThreatEntry* = object
    pos*: IVec2
    strength*: int32
    lastSeen*: int32
    agentId*: int32
    isStructure*: bool

  ## Shared threat map for a team.
  ThreatMap* = object
    entries*: array[MaxThreatEntries, ThreatEntry]
    count*: int32
    lastUpdateStep*: int32

  ## Heap node for A* priority queue ordering.
  PathHeapNode* = object
    fScore*: int32
    pos*: IVec2

  ## Pre-allocated pathfinding scratch space to avoid per-call allocations.
  ## Uses generation counters for O(1) validity checks without clearing arrays.
  PathfindingCache* = object
    generation*: int32
    closedGen*: array[MapWidth, array[MapHeight, int32]]
    gScoreGen*: array[MapWidth, array[MapHeight, int32]]
    gScoreVal*: array[MapWidth, array[MapHeight, int32]]
    cameFromGen*: array[MapWidth, array[MapHeight, int32]]
    cameFromVal*: array[MapWidth, array[MapHeight, IVec2]]
    openHeap*: HeapQueue[PathHeapNode]
    goals*: array[MaxPathGoals, IVec2]
    goalsLen*: int
    path*: array[MaxPathLength, IVec2]
    pathLen*: int

proc `<`*(a, b: PathHeapNode): bool =
  ## Compare path heap nodes by `fScore`.
  a.fScore < b.fScore

type
  AgentRole* = enum
    Gatherer
    Builder
    Fighter
    Scripted

  GathererTask* = enum
    TaskFood
    TaskWood
    TaskStone
    TaskGold
    TaskHearts

  QueuedCommandType* = enum
    CmdAttackMove
    CmdPatrol
    CmdFollow
    CmdGuard
    CmdHoldPosition

  QueuedCommand* = object
    cmdType*: QueuedCommandType
    targetPos*: IVec2
    targetAgentId*: int32

  AgentState* = object
    role*: AgentRole
    roleId*: int
    activeOptionId*: int
    activeOptionTicks*: int
    gathererTask*: GathererTask
    fighterEnemyAgentId*: int
    fighterEnemyStep*: int
    spiralStepsInArc*: int
    spiralArcsCompleted*: int
    spiralClockwise*: bool
    basePosition*: IVec2
    lastSearchPosition*: IVec2
    lastPosition*: IVec2
    recentPositions*: array[12, IVec2]
    recentPosIndex*: int
    recentPosCount*: int
    escapeMode*: bool
    escapeStepsRemaining*: int
    escapeDirection*: IVec2
    lastActionVerb*: int
    lastActionArg*: int
    blockedMoveDir*: int
    blockedMoveSteps*: int
    cachedThingPos*: array[ThingKind, IVec2]
    cachedThingStep*: array[ThingKind, int]
    cachedWaterPos*: IVec2
    cachedWaterStep*: int
    closestFoodPos*: IVec2
    closestWoodPos*: IVec2
    closestStonePos*: IVec2
    closestGoldPos*: IVec2
    closestWaterPos*: IVec2
    closestMagmaPos*: IVec2
    buildTarget*: IVec2
    buildStand*: IVec2
    buildIndex*: int
    buildLockSteps*: int
    plannedTarget*: IVec2
    plannedPath*: seq[IVec2]
    plannedPathIndex*: int
    pathBlockedTarget*: IVec2
    patrolPoint1*: IVec2
    patrolPoint2*: IVec2
    patrolToSecondPoint*: bool
    patrolActive*: bool
    patrolWaypoints*: array[8, IVec2]
    patrolWaypointCount*: int
    patrolCurrentWaypoint*: int
    attackMoveTarget*: IVec2
    scoutExploreRadius*: int32
    scoutLastEnemySeenStep*: int32
    scoutActive*: bool
    holdPositionActive*: bool
    holdPositionTarget*: IVec2
    followTargetAgentId*: int
    followActive*: bool
    guardTargetAgentId*: int
    guardTargetPos*: IVec2
    guardActive*: bool
    stoppedActive*: bool
    stoppedUntilStep*: int32
    pendingStance*: AgentStance
    stanceModified*: bool
    gathererPriorityResource*: StockpileResource
    gathererPriorityActive*: bool
    rallyArrivalStep*: int
    commandQueue*: array[MaxCommandQueueSize, QueuedCommand]
    commandQueueCount*: int

  DifficultyLevel* = enum
    DiffEasy
    DiffNormal
    DiffHard
    DiffBrutal

  DifficultyConfig* = object
    level*: DifficultyLevel
    decisionDelayChance*: float32
    threatResponseEnabled*: bool
    advancedTargetingEnabled*: bool
    coordinationEnabled*: bool
    optimalBuildOrderEnabled*: bool
    adaptive*: bool
    adaptiveTarget*: float32
    lastAdaptiveCheck*: int32

  Controller* = ref object
    rng*: Rand
    agents*: array[MapAgents, AgentState]
    agentsInitialized*: array[MapAgents, bool]
    buildingCountsStep*: int
    buildingCounts*: array[MapRoomObjectsTeams, array[ThingKind, int]]
    claimedBuildings*: array[MapRoomObjectsTeams, set[ThingKind]]
    teamPopCountsStep*: int
    teamPopCounts*: array[MapRoomObjectsTeams, int]
    pathCache*: PathfindingCache
    threatMaps*: array[MapRoomObjectsTeams, ThreatMap]
    difficulty*: array[MapRoomObjectsTeams, DifficultyConfig]
    allyThreatCacheStep*: array[MapRoomObjectsTeams, int]
    allyThreatCache*: array[MapRoomObjectsTeams, array[MapAgents, int8]]
    damagedBuildingCacheStep*: int
    damagedBuildingPositions*: array[
      MapRoomObjectsTeams,
      array[MaxDamagedBuildingsPerTeam, IVec2]
    ]
    damagedBuildingCounts*: array[MapRoomObjectsTeams, int]
    unlitBuildingCacheStep*: array[MapRoomObjectsTeams, int]
    unlitBuildingPositions*: array[
      MapRoomObjectsTeams,
      array[MaxUnlitBuildingsPerTeam, IVec2]
    ]
    unlitBuildingCounts*: array[MapRoomObjectsTeams, int]
    fogLastRevealPos*: array[MapAgents, IVec2]
    fogLastRevealStep*: array[MapAgents, int32]
    townSplitLastStep*: array[MapRoomObjectsTeams, int32]
    townBellAutoCheckStep*: array[MapRoomObjectsTeams, int32]
    teamEconomyFocus*: array[MapRoomObjectsTeams, StockpileResource]
    teamEconomyFocusActive*: array[MapRoomObjectsTeams, bool]
    agentLifecycle*: AgentStateLifecycle

proc defaultDifficultyConfig*(level: DifficultyLevel): DifficultyConfig =
  ## Create the default difficulty settings for one level.
  result = DifficultyConfig(
    level: level,
    adaptive: false,
    adaptiveTarget: 0.5,
    lastAdaptiveCheck: 0
  )
  case level
  of DiffEasy:
    result.decisionDelayChance = 0.30
  of DiffNormal:
    result.decisionDelayChance = 0.10
    result.threatResponseEnabled = true
    result.coordinationEnabled = true
    result.optimalBuildOrderEnabled = true
  of DiffHard:
    result.decisionDelayChance = 0.02
    result.threatResponseEnabled = true
    result.advancedTargetingEnabled = true
    result.coordinationEnabled = true
    result.optimalBuildOrderEnabled = true
  of DiffBrutal:
    result.threatResponseEnabled = true
    result.advancedTargetingEnabled = true
    result.coordinationEnabled = true
    result.optimalBuildOrderEnabled = true

proc newController*(seed: int): Controller =
  ## Create a controller with default caches and team difficulty settings.
  result = Controller(
    rng: initRand(seed),
    buildingCountsStep: -1,
    teamPopCountsStep: -1,
    damagedBuildingCacheStep: -1
  )
  for teamId in 0 ..< MapRoomObjectsTeams:
    result.difficulty[teamId] = defaultDifficultyConfig(DiffNormal)
  for agentId in 0 ..< MapAgents:
    result.fogLastRevealPos[agentId] = ivec2(-1, -1)
    result.fogLastRevealStep[agentId] = 0
  result.agentLifecycle.init()

proc resetAgentState*(state: var AgentState) =
  ## Reset one agent state back to defaults.
  state.role = Gatherer
  state.roleId = 0
  state.activeOptionId = -1
  state.activeOptionTicks = 0
  state.gathererTask = TaskFood
  state.fighterEnemyAgentId = -1
  state.fighterEnemyStep = 0
  state.spiralStepsInArc = 0
  state.spiralArcsCompleted = 0
  state.spiralClockwise = false
  state.basePosition = ivec2(-1, -1)
  state.lastSearchPosition = ivec2(-1, -1)
  state.lastPosition = ivec2(-1, -1)
  for i in 0 ..< state.recentPositions.len:
    state.recentPositions[i] = ivec2(-1, -1)
  state.recentPosIndex = 0
  state.recentPosCount = 0
  state.escapeMode = false
  state.escapeStepsRemaining = 0
  state.escapeDirection = ivec2(0, 0)
  state.lastActionVerb = 0
  state.lastActionArg = 0
  state.blockedMoveDir = -1
  state.blockedMoveSteps = 0
  for kind in ThingKind:
    state.cachedThingPos[kind] = ivec2(-1, -1)
    state.cachedThingStep[kind] = 0
  state.cachedWaterPos = ivec2(-1, -1)
  state.cachedWaterStep = 0
  state.closestFoodPos = ivec2(-1, -1)
  state.closestWoodPos = ivec2(-1, -1)
  state.closestStonePos = ivec2(-1, -1)
  state.closestGoldPos = ivec2(-1, -1)
  state.closestWaterPos = ivec2(-1, -1)
  state.closestMagmaPos = ivec2(-1, -1)
  state.buildTarget = ivec2(-1, -1)
  state.buildStand = ivec2(-1, -1)
  state.buildIndex = -1
  state.buildLockSteps = 0
  state.plannedTarget = ivec2(-1, -1)
  state.plannedPath = @[]
  state.plannedPathIndex = 0
  state.pathBlockedTarget = ivec2(-1, -1)
  state.patrolPoint1 = ivec2(-1, -1)
  state.patrolPoint2 = ivec2(-1, -1)
  state.patrolToSecondPoint = false
  state.patrolActive = false
  for i in 0 ..< state.patrolWaypoints.len:
    state.patrolWaypoints[i] = ivec2(-1, -1)
  state.patrolWaypointCount = 0
  state.patrolCurrentWaypoint = 0
  state.attackMoveTarget = ivec2(-1, -1)
  state.scoutExploreRadius = 0
  state.scoutLastEnemySeenStep = 0
  state.scoutActive = false
  state.holdPositionActive = false
  state.holdPositionTarget = ivec2(-1, -1)
  state.followTargetAgentId = -1
  state.followActive = false
  state.guardTargetAgentId = -1
  state.guardTargetPos = ivec2(-1, -1)
  state.guardActive = false
  state.stoppedActive = false
  state.stoppedUntilStep = 0
  state.pendingStance = StanceAggressive
  state.stanceModified = false
  state.gathererPriorityResource = ResourceNone
  state.gathererPriorityActive = false
  state.commandQueueCount = 0

proc resetControllerCaches*(controller: Controller, currentStep: int) =
  ## Reset step-scoped controller caches for a new tick.
  if controller.buildingCountsStep != currentStep:
    controller.buildingCountsStep = -1

  if controller.teamPopCountsStep != currentStep:
    controller.teamPopCountsStep = -1

  if controller.damagedBuildingCacheStep != currentStep:
    controller.damagedBuildingCacheStep = -1

  for teamId in 0 ..< MapRoomObjectsTeams:
    if controller.allyThreatCacheStep[teamId] != currentStep:
      controller.allyThreatCacheStep[teamId] = -1
    if controller.unlitBuildingCacheStep[teamId] != currentStep:
      controller.unlitBuildingCacheStep[teamId] = -1

  inc controller.pathCache.generation

  for teamId in 0 ..< MapRoomObjectsTeams:
    controller.claimedBuildings[teamId] = {}

proc cleanupAgentState*(controller: Controller, agentId: int) =
  ## Reset one dead or despawned agent and mark it inactive.
  if agentId < 0 or agentId >= MapAgents:
    return
  controller.agents[agentId].resetAgentState()
  controller.agentsInitialized[agentId] = false
  controller.agentLifecycle.markInactive(agentId)

proc markAgentActive*(controller: Controller, agentId: int, currentStep: int32) =
  ## Mark one agent active for lifecycle tracking.
  if agentId < 0 or agentId >= MapAgents:
    return
  controller.agentLifecycle.markActive(agentId, currentStep)

proc processAgentCleanup*(controller: Controller): seq[int] =
  ## Apply pending lifecycle cleanups and return cleaned agent ids.
  result = controller.agentLifecycle.getAgentsNeedingCleanup()
  for agentId in result:
    controller.agents[agentId].resetAgentState()
    controller.agentsInitialized[agentId] = false
    controller.agentLifecycle.clearCleanupFlag(agentId)

type
  ControllerInitResult* = object
    ## Result of `initializeToEnvironment`.
    success*: bool
    message*: string
    numAgents*: int
    numTeams*: int
    mapWidth*: int
    mapHeight*: int

proc initializeToEnvironment*(controller: Controller, numAgents, numTeams,
                              mapWidth, mapHeight: int): ControllerInitResult =
  ## Validate runtime environment dimensions against the controller layout.
  result.numAgents = numAgents
  result.numTeams = numTeams
  result.mapWidth = mapWidth
  result.mapHeight = mapHeight

  if numAgents != MapAgents:
    result.success = false
    result.message = "Agent count mismatch: runtime=" & $numAgents &
      " vs compile-time=" & $MapAgents
    return

  if numTeams != MapRoomObjectsTeams:
    result.success = false
    result.message = "Team count mismatch: runtime=" & $numTeams &
      " vs compile-time=" & $MapRoomObjectsTeams
    return

  if mapWidth != MapWidth:
    result.success = false
    result.message =
      "Map width mismatch: runtime=" & $mapWidth &
      " vs compile-time=" & $MapWidth
    return

  if mapHeight != MapHeight:
    result.success = false
    result.message =
      "Map height mismatch: runtime=" & $mapHeight &
      " vs compile-time=" & $MapHeight
    return

  result.success = true
  result.message = "Controller initialized for " & $numAgents & " agents, " &
                   $numTeams & " teams, " & $mapWidth & "x" & $mapHeight & " map"

proc initializeToEnvironmentDefault*(controller: Controller): ControllerInitResult =
  ## Initialize the controller with compile-time default dimensions.
  controller.initializeToEnvironment(
    MapAgents,
    MapRoomObjectsTeams,
    MapWidth,
    MapHeight
  )

type
  OptionDef* = object
    name*: string
    canStart*: proc(controller: Controller, env: Environment, agent: Thing,
                    agentId: int, state: var AgentState): bool
    shouldTerminate*: proc(controller: Controller, env: Environment, agent: Thing,
                           agentId: int, state: var AgentState): bool
    act*: proc(controller: Controller, env: Environment, agent: Thing,
               agentId: int, state: var AgentState): uint16
    interruptible*: bool

proc optionsAlwaysCanStart*(controller: Controller, env: Environment, agent: Thing,
                            agentId: int, state: var AgentState): bool =
  ## Return true for options without a start predicate.
  true

proc optionsAlwaysTerminate*(controller: Controller, env: Environment, agent: Thing,
                             agentId: int, state: var AgentState): bool =
  ## Return true for options that should terminate immediately.
  true

template resetActiveOption(state: var AgentState) =
  ## Clear the active option and its accumulated tick count.
  state.activeOptionId = -1
  state.activeOptionTicks = 0

template resetActiveOptionKeepTicks(state: var AgentState) =
  ## Reset the active option but preserve tick count for idle detection.
  state.activeOptionId = -1

proc runOptions*(controller: Controller, env: Environment, agent: Thing,
                 agentId: int, state: var AgentState,
                 roleOptions: openArray[OptionDef]): uint16 =
  ## Run the option list with continuation, preemption, and rescans.
  let optionCount = roleOptions.len
  if state.activeOptionId in 0 ..< optionCount:
    let activeIdx = state.activeOptionId
    if roleOptions[activeIdx].interruptible:
      for i in 0 ..< activeIdx:
        if roleOptions[i].canStart(controller, env, agent, agentId, state):
          state.activeOptionId = i
          state.activeOptionTicks = 0
          break
    inc state.activeOptionTicks
    let action = roleOptions[state.activeOptionId].act(
      controller, env, agent, agentId, state)
    if action != 0'u16:
      if roleOptions[state.activeOptionId].shouldTerminate(
          controller, env, agent, agentId, state):
        resetActiveOption(state)
      return action
    resetActiveOptionKeepTicks(state)

  for i, opt in roleOptions:
    if not opt.canStart(controller, env, agent, agentId, state):
      continue
    state.activeOptionId = i
    state.activeOptionTicks = max(state.activeOptionTicks, 1)
    let action = opt.act(controller, env, agent, agentId, state)
    if action != 0'u16:
      if opt.shouldTerminate(controller, env, agent, agentId, state):
        resetActiveOption(state)
      return action
    resetActiveOptionKeepTicks(state)

  return 0'u16

template optionGuard*(canName, termName: untyped, body: untyped) {.dirty.} =
  ## Generate inverse start and terminate predicates from one expression.
  proc canName(controller: Controller, env: Environment, agent: Thing,
               agentId: int, state: var AgentState): bool = body
  proc termName(controller: Controller, env: Environment, agent: Thing,
                agentId: int, state: var AgentState): bool = not (body)

template optionGuardExported*(canName, termName: untyped, body: untyped) {.dirty.} =
  ## Export inverse predicates for shared option checks.
  proc canName*(controller: Controller, env: Environment, agent: Thing,
                agentId: int, state: var AgentState): bool = body
  proc termName*(controller: Controller, env: Environment, agent: Thing,
                 agentId: int, state: var AgentState): bool = not (body)

macro defineBehavior*(name: static[string], body: untyped): untyped =
  ## Generate a behavior's start, terminate, act, and option definitions.
  var canStartBody: NimNode = nil
  var shouldTerminateBody: NimNode = nil
  var actBody: NimNode = nil
  var interruptibleVal = true

  for child in body:
    if child.kind == nnkCall and child.len == 2:
      let label = $child[0]
      case label
      of "canStart":
        canStartBody = child[1]
      of "shouldTerminate":
        shouldTerminateBody = child[1]
      of "act":
        actBody = child[1]
      of "interruptible":
        if child[1].kind == nnkIdent:
          interruptibleVal = $child[1] == "true"
        elif child[1].kind in {nnkStmtList, nnkStmtListExpr} and child[1].len > 0:
          interruptibleVal = $child[1][0] == "true"

  if canStartBody.isNil:
    error("defineBehavior requires a 'canStart' section", body)
  if actBody.isNil:
    error("defineBehavior requires an 'act' section", body)

  if shouldTerminateBody.isNil:
    shouldTerminateBody = newTree(nnkPrefix, ident("not"),
      newTree(nnkPar, canStartBody.copyNimTree))

  let canStartName = ident("canStart" & name)
  let shouldTerminateName = ident("shouldTerminate" & name)
  let optName = ident("opt" & name)
  let optionName = ident(name & "Option")

  let controllerParam = ident("controller")
  let envParam = ident("env")
  let agentParam = ident("agent")
  let agentIdParam = ident("agentId")
  let stateParam = ident("state")

  let boolParams = newTree(nnkFormalParams,
    ident("bool"),
    newIdentDefs(controllerParam, ident("Controller")),
    newIdentDefs(envParam, ident("Environment")),
    newIdentDefs(agentParam, ident("Thing")),
    newIdentDefs(agentIdParam, ident("int")),
    newIdentDefs(stateParam, newTree(nnkVarTy, ident("AgentState")))
  )

  let uint8Params = newTree(nnkFormalParams,
    ident("uint8"),
    newIdentDefs(ident("controller"), ident("Controller")),
    newIdentDefs(ident("env"), ident("Environment")),
    newIdentDefs(ident("agent"), ident("Thing")),
    newIdentDefs(ident("agentId"), ident("int")),
    newIdentDefs(ident("state"), newTree(nnkVarTy, ident("AgentState")))
  )

  let canStartProc = newTree(nnkProcDef,
    newTree(nnkPostfix, ident("*"), canStartName),
    newEmptyNode(),
    newEmptyNode(),
    boolParams.copyNimTree,
    newEmptyNode(),
    newEmptyNode(),
    canStartBody
  )

  let shouldTerminateProc = newTree(nnkProcDef,
    newTree(nnkPostfix, ident("*"), shouldTerminateName),
    newEmptyNode(),
    newEmptyNode(),
    boolParams.copyNimTree,
    newEmptyNode(),
    newEmptyNode(),
    shouldTerminateBody
  )

  let actProc = newTree(nnkProcDef,
    newTree(nnkPostfix, ident("*"), optName),
    newEmptyNode(),
    newEmptyNode(),
    uint8Params,
    newEmptyNode(),
    newEmptyNode(),
    actBody
  )

  let interruptibleIdent = if interruptibleVal: ident("true") else: ident("false")
  let optionDefExpr = newTree(nnkObjConstr,
    ident("OptionDef"),
    newTree(nnkExprColonExpr, ident("name"), newStrLitNode(name)),
    newTree(nnkExprColonExpr, ident("canStart"), canStartName),
    newTree(nnkExprColonExpr, ident("shouldTerminate"), shouldTerminateName),
    newTree(nnkExprColonExpr, ident("act"), optName),
    newTree(nnkExprColonExpr, ident("interruptible"), interruptibleIdent)
  )

  let optionLet = newTree(nnkLetSection,
    newTree(nnkIdentDefs,
      newTree(nnkPostfix, ident("*"), optionName),
      newEmptyNode(),
      optionDefExpr
    )
  )

  result = newStmtList(canStartProc, shouldTerminateProc, actProc, optionLet)

template behaviorGuard*(nameBase, canName, termName: untyped,
                        condition: untyped, actBody: untyped,
                        interruptibleVal: bool = true) {.dirty.} =
  ## Generate a simple inverse-guard behavior and its option definition.
  proc canName(controller: Controller, env: Environment, agent: Thing,
               agentId: int, state: var AgentState): bool = condition
  proc termName(controller: Controller, env: Environment, agent: Thing,
                agentId: int, state: var AgentState): bool = not (condition)
  proc `opt nameBase`(controller: Controller, env: Environment, agent: Thing,
                      agentId: int, state: var AgentState): uint16 = actBody
  let `nameBase Option`* = OptionDef(
    name: astToStr(nameBase),
    canStart: canName,
    shouldTerminate: termName,
    act: `opt nameBase`,
    interruptible: interruptibleVal
  )

proc stockpileResourceToGathererTask*(resource: StockpileResource): GathererTask =
  ## Map a stockpile resource to its gatherer task.
  case resource
  of ResourceFood: TaskFood
  of ResourceWood: TaskWood
  of ResourceGold: TaskGold
  of ResourceStone: TaskStone
  of ResourceWater, ResourceNone: TaskFood

proc setGathererPriority*(
  controller: Controller,
  agentId: int,
  resource: StockpileResource
) =
  ## Set one gatherer's manual resource priority.
  if agentId < 0 or agentId >= MapAgents:
    return
  controller.agents[agentId].gathererPriorityResource = resource
  controller.agents[agentId].gathererPriorityActive = true

proc clearGathererPriority*(controller: Controller, agentId: int) =
  ## Clear one gatherer's manual resource priority.
  if agentId < 0 or agentId >= MapAgents:
    return
  controller.agents[agentId].gathererPriorityActive = false

proc getGathererPriority*(controller: Controller, agentId: int): StockpileResource =
  ## Return one agent's gatherer priority or `ResourceNone`.
  if agentId < 0 or agentId >= MapAgents:
    return ResourceNone
  if not controller.agents[agentId].gathererPriorityActive:
    return ResourceNone
  controller.agents[agentId].gathererPriorityResource

proc isGathererPriorityActive*(controller: Controller, agentId: int): bool =
  ## Check if an individual gatherer priority is active.
  if agentId < 0 or agentId >= MapAgents:
    return false
  controller.agents[agentId].gathererPriorityActive

proc setTeamEconomyFocus*(
  controller: Controller,
  teamId: int,
  resource: StockpileResource
) =
  ## Set the team-wide economy focus resource.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  controller.teamEconomyFocus[teamId] = resource
  controller.teamEconomyFocusActive[teamId] = true

proc clearTeamEconomyFocus*(controller: Controller, teamId: int) =
  ## Clear the team-wide economy focus.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  controller.teamEconomyFocusActive[teamId] = false

proc getTeamEconomyFocus*(controller: Controller, teamId: int): StockpileResource =
  ## Return the active team economy focus or `ResourceNone`.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return ResourceNone
  if not controller.teamEconomyFocusActive[teamId]:
    return ResourceNone
  controller.teamEconomyFocus[teamId]

proc isTeamEconomyFocusActive*(controller: Controller, teamId: int): bool =
  ## Check if a team economy focus is active.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false
  controller.teamEconomyFocusActive[teamId]
