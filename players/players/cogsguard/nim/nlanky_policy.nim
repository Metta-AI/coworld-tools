import std/[json, options, strutils, tables]

import fidget2/measure
import jsony

import common
import nlanky_types
import nlanky_entity_map
import nlanky_obs_parser
import nlanky_nav
import nlanky_goals

type
  NlankyConfig = object
    miner: Option[int]
    scout: Option[int]
    aligner: Option[int]
    scrambler: Option[int]
    stem: Option[int]
    trace: Option[int]
    traceLevel: Option[int]
    traceAgent: Option[int]
    disableRoleSwitching: Option[bool]

  NlankyInitConfig = object
    env: PolicyConfig
    nlanky: NlankyConfig

  NlankyAgent = ref object
    agentId: int
    assignedRole: string
    role: string
    cfg: Config
    map: EntityMap
    nav: Navigator
    bb: Blackboard
    goals: seq[Goal]
    lastEpisodePct: int
    stepInEpisode: int
    myTeamId: Option[int]
    convertToScramblerAtStep: int
    infosJson: string

  NlankyPolicy* = ref object
    agents*: seq[NlankyAgent]
    obsParser: ObsParser
    disableRoleSwitching: bool
    traceEnabled: bool
    traceLevel: int
    traceAgent: int

proc updateInfosNoState(agent: NlankyAgent, roleOverride: Option[string] = none(string)) {.raises: [].} =
  ## Mirror Python Nlanky's per-step `policy.infos` metadata shape.
  let role = (if roleOverride.isSome: roleOverride.get() else: agent.role)
  let goal = agent.bb.strs.getOrDefault("_active_goal", "")

  var info = newJObject()
  info["role"] = %role
  info["goal"] = %goal
  info["cargo"] = %"0"
  agent.infosJson = $info

proc updateInfos(agent: NlankyAgent, state: StateSnapshot, roleOverride: Option[string] = none(string)) {.raises: [].} =
  ## Mirror Python Nlanky's per-step `policy.infos` metadata shape.
  let role = (if roleOverride.isSome: roleOverride.get() else: agent.role)
  let goal = agent.bb.strs.getOrDefault("_active_goal", "")
  let tgtOpt = agent.nav.cachedTarget()

  var info = newJObject()
  info["role"] = %role
  info["goal"] = %goal
  if tgtOpt.isSome:
    let tgt = tgtOpt.get()
    let relRow = tgt.y - state.position.y
    let relCol = tgt.x - state.position.x
    info["target"] = %($relRow & "," & $relCol)
  let targetResource = agent.bb.strs.getOrDefault("target_resource", "")
  if targetResource.len > 0:
    info["mining"] = %targetResource
  # Always show cargo so we can diagnose deposit-with-0-cargo issues.
  var parts: seq[string] = @[]
  if state.carbon > 0: parts.add("C" & $state.carbon)
  if state.oxygen > 0: parts.add("O" & $state.oxygen)
  if state.germanium > 0: parts.add("G" & $state.germanium)
  if state.silicon > 0: parts.add("S" & $state.silicon)
  info["cargo"] = %(if parts.len > 0: parts.join(" ") else: "0")
  agent.infosJson = $info

proc actionName(cfg: Config, actionId: int32): string =
  let idx = actionId.int
  if idx >= 0 and idx < cfg.config.actions.len:
    return cfg.config.actions[idx]
  $actionId

proc shouldTrace(policy: NlankyPolicy, agentId: int): bool =
  policy.traceEnabled and (policy.traceAgent < 0 or agentId == policy.traceAgent)

proc formatTraceLine(policy: NlankyPolicy, agent: NlankyAgent, state: StateSnapshot, actionId: int32): string =
  let goal = agent.bb.strs.getOrDefault("_active_goal", "")
  let role = agent.role
  let pos = state.position
  let hp = state.hp
  let act = actionName(agent.cfg, actionId)
  var targetStr = ""
  let tgtOpt = agent.nav.cachedTarget()
  if tgtOpt.isSome:
    let tgt = tgtOpt.get()
    let relRow = tgt.y - pos.y
    let relCol = tgt.x - pos.x
    targetStr = " target=" & $relRow & "," & $relCol

  if policy.traceLevel <= 1:
    return "[t=" & $agent.stepInEpisode & " a=" & $agent.agentId & " " & role &
      " (" & $pos.y & "," & $pos.x & ") hp=" & $hp & "] " & goal & " -> " & act & targetStr

  let cargo = $state.cargoTotal() & "/" & $state.cargoCapacity()
  "[t=" & $agent.stepInEpisode & " a=" & $agent.agentId & " " & role &
    " (" & $pos.y & "," & $pos.x & ") hp=" & $hp & " cargo=" & cargo & "] " & goal & " -> " & act & targetStr

proc updateEpisodeState(agent: NlankyAgent, episodePct: int) =
  if episodePct == -1:
    agent.stepInEpisode += 1
    return

  var newEpisode = false
  if agent.lastEpisodePct == -1:
    newEpisode = true
  elif episodePct < agent.lastEpisodePct:
    newEpisode = true
  elif agent.lastEpisodePct > 0 and episodePct == 0:
    newEpisode = true

  if newEpisode:
    agent.stepInEpisode = 0
  else:
    agent.stepInEpisode += 1
  agent.lastEpisodePct = episodePct

proc actionId(cfg: Config, act: NavAction): int =
  case act:
  of naNoop:
    cfg.actions.noop
  of naMoveNorth:
    cfg.actions.moveNorth
  of naMoveSouth:
    cfg.actions.moveSouth
  of naMoveWest:
    cfg.actions.moveWest
  of naMoveEast:
    cfg.actions.moveEast

proc newNlankyAgent(agentId: int, envJson: string, role: string): NlankyAgent =
  let cfg = parseConfig(envJson)
  NlankyAgent(
    agentId: agentId,
    assignedRole: role,
    role: role,
    cfg: cfg,
    map: newEntityMap(),
    nav: newNavigator(agentId),
    bb: newBlackboard(),
    goals: makeGoalList(role),
    lastEpisodePct: -1,
    stepInEpisode: 0,
    myTeamId: none(int),
    convertToScramblerAtStep: -1,
    infosJson: "",
  )

proc newNlankyPolicy*(environmentConfig: string): NlankyPolicy {.raises: [].} =
  # Expected input: { "env": <PolicyConfig>, "nlanky": <NlankyConfig> }.
  # We must not let exceptions escape across the generated C bindings; if parsing
  # fails, crash loudly instead of silently nooping.
  var initCfg: NlankyInitConfig
  try:
    initCfg = environmentConfig.fromJson(NlankyInitConfig)
  except jsony.JsonError, ValueError:
    echo "Error parsing Nlanky init config: ", getCurrentExceptionMsg()
    quit(QuitFailure)
  let envJson = initCfg.env.toJson()
  var agents: seq[NlankyAgent] = @[]

  # Match Python Nlanky defaults:
  # - miner/aligner/scrambler are "unset" when omitted (-1 in Python).
  # - if stem > 0 OR any explicit role is provided, treat remaining unset roles as 0
  # - else defaults: 4 miners, 4 aligners, 0 scramblers.
  var miner = (if initCfg.nlanky.miner.isSome: initCfg.nlanky.miner.get() else: -1)
  var scout = (if initCfg.nlanky.scout.isSome: initCfg.nlanky.scout.get() else: 0)
  var aligner = (if initCfg.nlanky.aligner.isSome: initCfg.nlanky.aligner.get() else: -1)
  var scrambler = (if initCfg.nlanky.scrambler.isSome: initCfg.nlanky.scrambler.get() else: -1)
  var stem = (if initCfg.nlanky.stem.isSome: initCfg.nlanky.stem.get() else: 0)
  let disableRoleSwitching =
    (if initCfg.nlanky.disableRoleSwitching.isSome: initCfg.nlanky.disableRoleSwitching.get() else: false)

  let anyExplicit = (miner >= 0) or (aligner >= 0) or (scrambler >= 0) or (scout > 0)
  if stem > 0 or anyExplicit:
    if miner == -1: miner = 0
    if aligner == -1: aligner = 0
    if scrambler == -1: scrambler = 0
  else:
    miner = 4
    aligner = 4
    scrambler = 0

  var teamRoles: seq[string] = @[]
  for _ in 0 ..< miner: teamRoles.add("miner")
  for _ in 0 ..< scout: teamRoles.add("scout")
  for _ in 0 ..< aligner: teamRoles.add("aligner")
  for _ in 0 ..< scrambler: teamRoles.add("scrambler")
  for _ in 0 ..< stem: teamRoles.add("stem")
  if teamRoles.len == 0:
    teamRoles.add("default")

  let numAgents = initCfg.env.numAgents
  var roles: seq[string] = @[]
  while roles.len < numAgents:
    for r in teamRoles:
      if roles.len >= numAgents:
        break
      roles.add(r)

  # First aligner converts to scrambler at step 1000 (unless role switching disabled).
  var firstAlignerId = -1
  if not disableRoleSwitching:
    for i, r in roles:
      if r == "aligner":
        firstAlignerId = i
        break

  for id in 0 ..< initCfg.env.numAgents:
    let a = newNlankyAgent(id, envJson, roles[id])
    if id == firstAlignerId and roles[id] == "aligner" and not disableRoleSwitching:
      a.convertToScramblerAtStep = 1000
    a.updateInfosNoState()
    agents.add(a)
  # Parser needs cfg-derived mappings; all agents share the same env config.
  let parser =
    if agents.len > 0:
      newObsParser(agents[0].cfg)
    else:
      newObsParser(parseConfig(envJson))
  let traceEnabled = (if initCfg.nlanky.trace.isSome: initCfg.nlanky.trace.get() else: 0) != 0
  let traceLevel = (if initCfg.nlanky.traceLevel.isSome: initCfg.nlanky.traceLevel.get() else: 1)
  let traceAgent = (if initCfg.nlanky.traceAgent.isSome: initCfg.nlanky.traceAgent.get() else: -1)

  NlankyPolicy(
    agents: agents,
    obsParser: parser,
    disableRoleSwitching: disableRoleSwitching,
    traceEnabled: traceEnabled,
    traceLevel: traceLevel,
    traceAgent: traceAgent,
  )

proc getInfosJson*(policy: NlankyPolicy, agentId: int): cstring {.raises: [].} =
  ## Exposed over FFI for Python to populate AgentPolicy.infos.
  if policy == nil:
    return cstring""
  if agentId < 0 or agentId >= policy.agents.len:
    return cstring""
  policy.agents[agentId].infosJson.cstring

proc stepOneImpl(
  policy: NlankyPolicy,
  agent: NlankyAgent,
  numTokens: int,
  sizeToken: int,
  rawObservation: pointer,
  agentAction: ptr int32
) {.measure.} =
  let visible = parseVisible(agent.cfg, numTokens, sizeToken, rawObservation)
  let episodePct = agent.cfg.getEpisodeCompletionPct(visible)
  agent.updateEpisodeState(episodePct)

  var lastPos = none(Location)
  if agent.bb.locs.hasKey("_last_pos"):
    lastPos = some(agent.bb.locs.getOrDefault("_last_pos", Location(x: 0, y: 0)))

  let parsed = policy.obsParser.parse(agent.cfg, visible, agent.stepInEpisode, lastPos=lastPos)
  let state = parsed.state
  agent.map.updateFromObservation(
    agentPos=state.position,
    obsHalfHeight=policy.obsParser.obsHalfHeight,
    obsHalfWidth=policy.obsParser.obsHalfWidth,
    visibleEntities=parsed.visibleEntities,
    step=agent.stepInEpisode
  )

  # Detect own team once (from nearest hub alignment).
  if agent.myTeamId.isNone:
    let hub = agent.map.findNearest(state.position, kindContains="hub")
    if hub.isSome:
      let (_, ent) = hub.get()
      if ent.alignment == alCogs:
        agent.myTeamId = some(1)
      elif ent.alignment == alClips:
        agent.myTeamId = some(0)

  # Death/respawn detection: large position jump signals a respawn event.
  if lastPos.isSome:
    let respawnDist = manhattan(state.position, lastPos.get())
    if respawnDist > 20:
      agent.nav.clearCache()
      agent.nav.clearHistory()
      agent.bb.bools["_depositing"] = false
      agent.bb.bools["_at_extractor"] = false
      agent.bb.bools["_emergency_mine_active"] = false
      agent.bb.ints["_move_fail_count"] = 0
      agent.bb.ints["_heart_hub_bumps"] = 0
      agent.bb.ints["_at_extractor_stall_count"] = 0
      if agent.bb.strs.hasKey("target_resource"):
        agent.bb.strs.del("target_resource")
      agent.map.clearFarEntities(state.position, radius=30)

  # Failed-move detection (mirrors Python Nlanky).
  let lastWasMove = agent.bb.bools.getOrDefault("_last_was_move", false)
  var moveFailCount = agent.bb.ints.getOrDefault("_move_fail_count", 0)
  if lastPos.isSome and lastWasMove and state.position == lastPos.get():
    moveFailCount += 1
    agent.bb.ints["_move_fail_count"] = moveFailCount
    if moveFailCount >= 3:
      agent.nav.clearCache()
    if moveFailCount >= 6:
      if agent.bb.strs.hasKey("target_resource"):
        agent.bb.strs.del("target_resource")
      agent.bb.ints["_move_fail_count"] = 0
  else:
    agent.bb.ints["_move_fail_count"] = 0

  agent.bb.locs["_last_pos"] = state.position

  # Role switching (vibe-driven roles) and time-based conversions.
  if not policy.disableRoleSwitching:
    if agent.convertToScramblerAtStep != -1 and agent.stepInEpisode == agent.convertToScramblerAtStep:
      # Persistently reassign the role distribution and request an immediate vibe change.
      agent.assignedRole = "scrambler"
      agent.bb.strs["change_role"] = "scrambler"

    # Miner -> aligner when team is well-stocked and miner is idle.
    if state.vibe == "miner" and state.cargoTotal() == 0:
      if state.teamCarbon > 100 and state.teamOxygen > 100 and state.teamGermanium > 100 and state.teamSilicon > 100:
        agent.bb.strs["change_role"] = "aligner"

    # Aligner -> miner when can't afford gear or hearts (and aligner is idle).
    if state.vibe == "aligner" and (not state.alignerGear) and state.heart == 0:
      let canAffordGear =
        state.teamCarbon >= 4 and state.teamOxygen >= 2 and state.teamGermanium >= 2 and state.teamSilicon >= 2
      let canAffordHearts =
        state.teamCarbon >= 8 and state.teamOxygen >= 8 and state.teamGermanium >= 8 and state.teamSilicon >= 8
      if not canAffordGear and not canAffordHearts:
        agent.bb.strs["change_role"] = "miner"

  # Apply role change request from previous tick.
  if agent.bb.strs.hasKey("change_role"):
    let newRole = agent.bb.strs.getOrDefault("change_role", "")
    agent.bb.strs.del("change_role")
    if newRole in ["miner", "scout", "aligner", "scrambler"]:
      agentAction[] = agent.cfg.vibeActionId(newRole).int32
      agent.bb.bools["_last_was_move"] = false
      agent.updateInfos(state, roleOverride=some(newRole))
      if policy.shouldTrace(agent.agentId):
        echo "[nlanky] ", policy.formatTraceLine(agent, state, agentAction[])
      return

  # Map vibe -> effective role.
  let vibe = state.vibe
  var effectiveRole = agent.role
  if vibe == "default":
    if agent.assignedRole in ["miner", "scout", "aligner", "scrambler"]:
      agentAction[] = agent.cfg.vibeActionId(agent.assignedRole).int32
      agent.bb.bools["_last_was_move"] = false
      agent.updateInfos(state, roleOverride=some(agent.assignedRole))
      if policy.shouldTrace(agent.agentId):
        echo "[nlanky] ", policy.formatTraceLine(agent, state, agentAction[])
      return
    effectiveRole = "stem"
  elif vibe == "gear":
    effectiveRole = "stem"
  elif vibe in ["miner", "scout", "aligner", "scrambler"]:
    effectiveRole = vibe
  else:
    if agent.assignedRole in ["miner", "scout", "aligner", "scrambler"]:
      agentAction[] = agent.cfg.vibeActionId(agent.assignedRole).int32
      agent.bb.bools["_last_was_move"] = false
      agent.updateInfos(state, roleOverride=some(agent.assignedRole))
      if policy.shouldTrace(agent.agentId):
        echo "[nlanky] ", policy.formatTraceLine(agent, state, agentAction[])
      return
    effectiveRole = "stem"

  if effectiveRole != agent.role:
    agent.role = effectiveRole
    agent.goals = makeGoalList(effectiveRole)

  var ctx = NlankyContext(
    state: state,
    map: agent.map,
    bb: addr agent.bb,
    nav: agent.nav,
    agentId: agent.agentId,
    step: agent.stepInEpisode,
    myTeamId: agent.myTeamId,
  )

  # If we're stuck, force exploration to refresh the map / break loops.
  let failCount = agent.bb.ints.getOrDefault("_move_fail_count", 0)
  var navAct: NavAction
  if failCount >= 6:
    let dirs = ["north", "east", "south", "west"]
    navAct = agent.nav.explore(state.position, agent.map, directionBias=dirs[agent.agentId mod 4])
    agent.bb.strs["_active_goal"] = "ForceExplore"
  else:
    navAct = evaluateGoals(agent.goals, ctx)

  agentAction[] = actionId(agent.cfg, navAct).int32
  agent.bb.bools["_last_was_move"] = navAct in [naMoveNorth, naMoveSouth, naMoveWest, naMoveEast]
  agent.updateInfos(state)
  if policy.shouldTrace(agent.agentId):
    echo "[nlanky] ", policy.formatTraceLine(agent, state, agentAction[])

proc stepOne(
  policy: NlankyPolicy,
  agent: NlankyAgent,
  numTokens: int,
  sizeToken: int,
  rawObservation: pointer,
  agentAction: ptr int32
) {.raises: [].} =
  try:
    stepOneImpl(policy, agent, numTokens, sizeToken, rawObservation, agentAction)
  except Exception:
    echo "Nlanky step error: agentId=", agent.agentId, " msg=", getCurrentExceptionMsg()
    quit(QuitFailure)

proc stepBatch*(
  policy: NlankyPolicy,
  agentIds: pointer,
  numAgentIds: int,
  numAgents: int,
  numTokens: int,
  sizeToken: int,
  rawObservations: pointer,
  numActions: int,
  rawActions: pointer
) {.raises: [].} =
  discard numActions
  let ids = cast[ptr UncheckedArray[int32]](agentIds)
  let obsArray = cast[ptr UncheckedArray[uint8]](rawObservations)
  let actionArray = cast[ptr UncheckedArray[int32]](rawActions)
  let obsStride = numTokens * sizeToken
  if policy == nil or policy.agents.len == 0:
    # When policy initialization fails, keep the process alive and produce
    # a safe default action for any requested agent ids.
    for i in 0 ..< numAgentIds:
      let idx = int(ids[i])
      if idx >= 0 and idx < numAgents:
        actionArray[idx] = 0'i32
    return

  for i in 0 ..< numAgentIds:
    let idx = int(ids[i])
    if idx < 0 or idx >= policy.agents.len:
      continue
    let obsPtr = cast[pointer](obsArray[idx * obsStride].addr)
    let actPtr = cast[ptr int32](actionArray[idx].addr)
    stepOne(policy, policy.agents[idx], numTokens, sizeToken, obsPtr, actPtr)
