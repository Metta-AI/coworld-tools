import
  vmath,
  ../common_types, ../environment

const
  MaxCoordinationRequests* = 16
  RequestExpirationSteps* = 60
  DuplicateWindowSteps* = 30
  ProtectionResponseRadius* = 15
  DefenseRequestRadius* = 20

type
  CoordinationRequestKind* = enum
    RequestProtection
    RequestDefense
    RequestSiegeBuild

  CoordinationPriority* = enum
    PriorityLow = 0
    PriorityNormal = 1
    PriorityHigh = 2

  CoordinationRequest* = object
    kind*: CoordinationRequestKind
    teamId*: int
    requesterId*: int
    requesterPos*: IVec2
    threatPos*: IVec2
    createdStep*: int
    fulfilled*: bool
    priority*: CoordinationPriority

  CoordinationState* = object
    requests*: array[MaxCoordinationRequests, CoordinationRequest]
    requestCount*: int

var teamCoordination*: array[MapRoomObjectsTeams, CoordinationState]

template validTeamId(teamId: int): bool =
  teamId >= 0 and teamId < MapRoomObjectsTeams

template coordState(teamId: int): var CoordinationState =
  teamCoordination[teamId]

proc hasUnfulfilledRequest*(teamId: int, kind: CoordinationRequestKind): bool =
  ## Check whether a team has an unfulfilled request of one kind.
  if not validTeamId(teamId):
    return false
  let state = addr coordState(teamId)
  for i in 0 ..< state.requestCount:
    if state.requests[i].kind == kind and not state.requests[i].fulfilled:
      return true
  false

proc markRequestFulfilled*(teamId: int, kind: CoordinationRequestKind) =
  ## Mark the highest-priority unfulfilled request as fulfilled.
  if not validTeamId(teamId):
    return
  let state = addr coordState(teamId)
  var bestIdx = -1
  var bestPriority = PriorityLow
  for i in 0 ..< state.requestCount:
    let req = addr state.requests[i]
    if req.kind == kind and not req.fulfilled:
      if bestIdx < 0 or req.priority > bestPriority:
        bestIdx = i
        bestPriority = req.priority
  if bestIdx >= 0:
    state.requests[bestIdx].fulfilled = true

proc clearExpiredRequests*(step: int) =
  ## Remove expired or fulfilled requests.
  for teamId in 0 ..< MapRoomObjectsTeams:
    let state = addr coordState(teamId)
    var writeIdx = 0
    for readIdx in 0 ..< state.requestCount:
      let req = state.requests[readIdx]
      if not req.fulfilled and (step - req.createdStep) < RequestExpirationSteps:
        state.requests[writeIdx] = req
        inc writeIdx
    state.requestCount = writeIdx

proc addRequest*(teamId: int, kind: CoordinationRequestKind,
                 requesterId: int, requesterPos, threatPos: IVec2, step: int,
                 priority: CoordinationPriority = PriorityNormal): bool =
  ## Add a coordination request. Returns true if added successfully.
  if not validTeamId(teamId):
    return false
  let state = addr coordState(teamId)
  for i in 0 ..< state.requestCount:
    let req = state.requests[i]
    if req.requesterId == requesterId and req.kind == kind and
       (step - req.createdStep) < DuplicateWindowSteps:
      return false
  if state.requestCount >= MaxCoordinationRequests:
    for i in 1 ..< MaxCoordinationRequests:
      state.requests[i - 1] = state.requests[i]
    dec state.requestCount
  let idx = state.requestCount
  state.requests[idx] = CoordinationRequest(
    kind: kind,
    teamId: teamId,
    requesterId: requesterId,
    requesterPos: requesterPos,
    threatPos: threatPos,
    createdStep: step,
    fulfilled: false,
    priority: priority
  )
  inc state.requestCount
  true

proc findNearestProtectionRequest*(
  teamId: int,
  agentPos: IVec2
): ptr CoordinationRequest =
  ## Find the nearest high-priority protection request within response range.
  if not validTeamId(teamId):
    return nil
  let state = addr coordState(teamId)
  var bestDist = int.high
  var bestPriority = PriorityLow
  var bestReq: ptr CoordinationRequest = nil
  for i in 0 ..< state.requestCount:
    let req = addr state.requests[i]
    if req.kind != RequestProtection or req.fulfilled:
      continue
    let dx = abs(agentPos.x - req.requesterPos.x)
    let dy = abs(agentPos.y - req.requesterPos.y)
    let dist = int(if dx > dy: dx else: dy)
    if dist <= ProtectionResponseRadius:
      if req.priority > bestPriority or
         (req.priority == bestPriority and dist < bestDist):
        bestDist = dist
        bestPriority = req.priority
        bestReq = req
  bestReq

proc requestProtectionFromFighter*(env: Environment, agent: Thing, threatPos: IVec2) =
  ## Queue a protection request for a fleeing gatherer.
  let teamId = getTeamId(agent)
  discard addRequest(
    teamId,
    RequestProtection,
    agent.agentId,
    agent.pos,
    threatPos,
    env.currentStep
  )

proc requestDefenseFromBuilder*(env: Environment, agent: Thing, threatPos: IVec2) =
  ## Queue a defense request when a fighter spots a threat.
  let teamId = getTeamId(agent)
  discard addRequest(
    teamId,
    RequestDefense,
    agent.agentId,
    agent.pos,
    threatPos,
    env.currentStep
  )

proc requestSiegeFromBuilder*(env: Environment, agent: Thing) =
  ## Queue a siege-build request when a fighter spots enemy structures.
  let teamId = getTeamId(agent)
  discard addRequest(
    teamId,
    RequestSiegeBuild,
    agent.agentId,
    agent.pos,
    agent.pos,
    env.currentStep
  )

proc fighterShouldEscort*(
  env: Environment,
  agent: Thing
): tuple[should: bool, target: IVec2] =
  ## Return whether a fighter should escort a protected ally.
  let teamId = getTeamId(agent)
  let req = findNearestProtectionRequest(teamId, agent.pos)
  if isNil(req):
    return (false, ivec2(-1, -1))
  if req.requesterId >= 0 and req.requesterId < MapAgents:
    let requester = env.agents[req.requesterId]
    if isAgentAlive(env, requester):
      return (true, requester.pos)
  (false, ivec2(-1, -1))

const
  MaxResourceReservations* = 64
  ReservationExpirationSteps* = 30

type
  ResourceReservation* = object
    pos*: IVec2
    agentId*: int32
    createdStep*: int32

  ReservationState* = object
    reservations*: array[MaxResourceReservations, ResourceReservation]
    count*: int

var teamReservations*: array[MapRoomObjectsTeams, ReservationState]

template resState(teamId: int): var ReservationState =
  teamReservations[teamId]

proc removeAgentReservations(state: ptr ReservationState, agentId: int32) =
  ## Remove every reservation currently owned by one agent.
  var writeIdx = 0
  for readIdx in 0 ..< state.count:
    let res = state.reservations[readIdx]
    if res.agentId == agentId:
      continue
    if writeIdx != readIdx:
      state.reservations[writeIdx] = res
    inc writeIdx
  state.count = writeIdx

proc clearExpiredReservations*(env: Environment) =
  ## Remove reservations that have expired or whose agent is dead.
  let currentStep = env.currentStep
  for teamId in 0 ..< MapRoomObjectsTeams:
    let state = addr resState(teamId)
    var writeIdx = 0
    for readIdx in 0 ..< state.count:
      let res = state.reservations[readIdx]
      let expired = (currentStep - res.createdStep) >= ReservationExpirationSteps
      let agentDead = res.agentId >= 0 and res.agentId < env.agents.len and
                      not isAgentAlive(env, env.agents[res.agentId])
      if not expired and not agentDead:
        if writeIdx != readIdx:
          state.reservations[writeIdx] = res
        inc writeIdx
    state.count = writeIdx

proc isResourceReserved*(teamId: int, pos: IVec2, excludeAgentId: int = -1): bool =
  ## Check if a resource position is reserved by another agent on this team.
  ## excludeAgentId allows the reserving agent to see its own reservation as unreserved.
  if not validTeamId(teamId):
    return false
  let state = addr resState(teamId)
  for i in 0 ..< state.count:
    let res = state.reservations[i]
    if res.pos == pos and res.agentId != excludeAgentId.int32:
      return true
  false

proc reserveResource*(teamId: int, agentId: int, pos: IVec2, step: int): bool =
  ## Reserve one resource position for an agent.
  if not validTeamId(teamId):
    return false
  let state = addr resState(teamId)
  for i in 0 ..< state.count:
    let res = state.reservations[i]
    if res.pos == pos and res.agentId != agentId.int32:
      return false
  removeAgentReservations(state, agentId.int32)
  if state.count >= MaxResourceReservations:
    return false
  let idx = state.count
  state.reservations[idx] = ResourceReservation(
    pos: pos,
    agentId: agentId.int32,
    createdStep: step.int32
  )
  inc state.count
  true

proc releaseReservation*(teamId: int, agentId: int) =
  ## Release any reservation held by this agent.
  if not validTeamId(teamId):
    return
  removeAgentReservations(addr resState(teamId), agentId.int32)

proc getReservationPos*(teamId: int, agentId: int): IVec2 =
  ## Get the reserved position for an agent, or (-1,-1) if none.
  if not validTeamId(teamId):
    return ivec2(-1, -1)
  let state = addr resState(teamId)
  for i in 0 ..< state.count:
    if state.reservations[i].agentId == agentId.int32:
      return state.reservations[i].pos
  ivec2(-1, -1)

type
  ResourcePatchKind* = enum
    PatchWood, PatchGold, PatchStone, PatchFood

proc countGatherersNearPos*(
  env: Environment,
  teamId: int,
  pos: IVec2,
  radius: int
): int =
  ## Count gatherer reservations near a position.
  if not validTeamId(teamId):
    return 0
  let rState = addr resState(teamId)
  for i in 0 ..< rState.count:
    let res = rState.reservations[i]
    let dx = abs(res.pos.x - pos.x)
    let dy = abs(res.pos.y - pos.y)
    if max(dx, dy) <= radius.int32:
      inc result

proc findNearestDropoffForResource*(env: Environment, pos: IVec2, teamId: int,
                                     patchKind: ResourcePatchKind): Thing =
  ## Find the nearest friendly drop-off building appropriate for a resource type.
  ## Returns nil if no drop-off found within search radius.
  case patchKind
  of PatchWood:
    result = findNearestFriendlyThingSpatial(
      env,
      pos,
      teamId,
      LumberCamp,
      DropoffProximityRadius
    )
    if isNil(result):
      result = findNearestFriendlyThingSpatial(
        env,
        pos,
        teamId,
        TownCenter,
        DropoffProximityRadius
      )
  of PatchGold:
    result = findNearestFriendlyThingSpatial(
      env,
      pos,
      teamId,
      MiningCamp,
      DropoffProximityRadius
    )
    if isNil(result):
      result = findNearestFriendlyThingSpatial(
        env,
        pos,
        teamId,
        TownCenter,
        DropoffProximityRadius
      )
  of PatchStone:
    result = findNearestFriendlyThingSpatial(
      env,
      pos,
      teamId,
      Quarry,
      DropoffProximityRadius
    )
    if isNil(result):
      result = findNearestFriendlyThingSpatial(
        env,
        pos,
        teamId,
        TownCenter,
        DropoffProximityRadius
      )
  of PatchFood:
    result = findNearestFriendlyThingSpatial(
      env,
      pos,
      teamId,
      Granary,
      DropoffProximityRadius
    )
    if isNil(result):
      result = findNearestFriendlyThingSpatial(
        env,
        pos,
        teamId,
        Mill,
        DropoffProximityRadius
      )
    if isNil(result):
      result = findNearestFriendlyThingSpatial(
        env,
        pos,
        teamId,
        TownCenter,
        DropoffProximityRadius
      )

proc findUnderstaffedPatchPos*(env: Environment, agentPos: IVec2, teamId: int,
                                patchKind: ResourcePatchKind): IVec2 =
  ## Find the nearest understaffed drop-off patch.
  result = ivec2(-1, -1)
  var bestDist = int.high
  template checkKind(buildingKind: ThingKind) =
    let building = findNearestFriendlyThingSpatial(
      env,
      agentPos,
      teamId,
      buildingKind,
      50
    )
    if not isNil(building):
      let gatherers = countGatherersNearPos(env, teamId, building.pos, PatchRadius)
      if gatherers < MaxGatherersPerPatch:
        let dist = int(max(
          abs(agentPos.x - building.pos.x),
          abs(agentPos.y - building.pos.y)
        ))
        if dist < bestDist:
          bestDist = dist
          result = building.pos

  case patchKind
  of PatchWood:
    checkKind(LumberCamp)
  of PatchGold:
    checkKind(MiningCamp)
  of PatchStone:
    checkKind(Quarry)
  of PatchFood:
    checkKind(Granary)
    checkKind(Mill)
  checkKind(TownCenter)
