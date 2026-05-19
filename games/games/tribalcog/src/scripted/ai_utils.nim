import
  vmath,
  ../[common_types, environment, types]

export common_types, environment, types

const
  DefensiveRetaliationWindow* = 30
  MaxNavalPerTeam* = 5

type
  StanceBehavior* = enum
    BehaviorAutoAttack
    BehaviorChase
    BehaviorMovementToAttack

  AgentUnitClassFilter* = enum
    FilterExclude
    FilterInclude

proc stanceAllows*(env: Environment, agent: Thing,
                   behavior: StanceBehavior): bool =
  ## Return whether the agent's stance permits the requested behavior.
  case behavior
  of BehaviorAutoAttack:
    case agent.stance
    of StanceAggressive, StanceStandGround: true
    of StanceDefensive:
      agent.lastAttackedStep > 0 and
        (env.currentStep - agent.lastAttackedStep) <=
        DefensiveRetaliationWindow
    of StanceNoAttack: false
  of BehaviorChase, BehaviorMovementToAttack:
    case agent.stance
    of StanceAggressive: true
    of StanceDefensive:
      agent.lastAttackedStep > 0 and
        (env.currentStep - agent.lastAttackedStep) <=
        DefensiveRetaliationWindow
    of StanceStandGround, StanceNoAttack: false

proc findNearestEnemyImpl(
  env: Environment,
  agent: Thing,
  radius: int,
  classes: set[AgentUnitClass] = {},
  filterType: AgentUnitClassFilter = FilterExclude,
  useClassFilter = false,
  requireWaterUnit = false
): Thing =
  ## Return the nearest matching enemy using the spatial index.
  let
    teamMask = getTeamMask(agent)
    (cx, cy) = cellCoords(agent.pos)
    clampedMax =
      min(radius, max(SpatialCellsX, SpatialCellsY) * SpatialCellSize)
    cellRadius = distToCellRadius16(clampedMax)
  var
    bestEnemy: Thing = nil
    bestDist = int.high

  for ddx in -cellRadius .. cellRadius:
    for ddy in -cellRadius .. cellRadius:
      let
        nx = cx + ddx
        ny = cy + ddy
      if nx < 0 or nx >= SpatialCellsX or ny < 0 or ny >= SpatialCellsY:
        continue
      for other in env.spatialIndex.kindCells[Agent][nx][ny]:
        if other.isNil or other.agentId == agent.agentId:
          continue
        if not isAgentAlive(env, other):
          continue
        if (getTeamMask(other) and teamMask) != 0:
          continue
        if requireWaterUnit and not other.isWaterUnit:
          continue
        if useClassFilter:
          case filterType
          of FilterExclude:
            if other.unitClass in classes:
              continue
          of FilterInclude:
            if other.unitClass notin classes:
              continue
        let dist = int(chebyshevDist(agent.pos, other.pos))
        if dist > radius:
          continue
        if dist < bestDist:
          bestDist = dist
          bestEnemy = other

  bestEnemy

proc findNearestEnemy*(
  env: Environment,
  agent: Thing,
  radius: int,
  requireWaterUnit = false
): Thing =
  ## Find the nearest enemy within radius.
  findNearestEnemyImpl(
    env,
    agent,
    radius,
    requireWaterUnit = requireWaterUnit,
  )

proc findNearestEnemyOfClass*(
  env: Environment,
  agent: Thing,
  radius: int,
  classes: set[AgentUnitClass],
  filterType: AgentUnitClassFilter
): Thing =
  ## Find the nearest enemy within radius that matches the class filter.
  findNearestEnemyImpl(
    env,
    agent,
    radius,
    classes = classes,
    filterType = filterType,
    useClassFilter = true,
  )

iterator teamAliveAgents*(env: Environment, teamId: int): Thing =
  ## Iterate alive agents on a team.
  for agent in env.agents:
    if isAgentAlive(env, agent) and getTeamId(agent) == teamId:
      yield agent

proc countTeamAgentsByClass*(
  env: Environment,
  teamId: int,
  classes: set[AgentUnitClass]
): int =
  ## Count alive team agents matching any listed unit class.
  for agent in env.teamAliveAgents(teamId):
    if agent.unitClass in classes:
      inc result

proc countTeamNavalAgents*(env: Environment, teamId: int): int =
  ## Count alive naval units for a team.
  for agent in env.teamAliveAgents(teamId):
    if agent.isWaterUnit:
      inc result
