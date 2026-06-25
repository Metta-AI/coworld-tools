# This file is included by src/step.nim
# Victory condition procs for AoE2-style game modes

# ============================================================================
# Victory Conditions (AoE2-style)
# ============================================================================

proc teamHasUnitsOrBuildings(env: Environment, teamId: int): bool =
  ## Check if a team has any living agents or owned buildings.
  for agent in env.liveAgents:
    if getTeamId(agent) == teamId and isAgentAlive(env, agent):
      return true
  for kind in TeamOwnedKinds:
    if kind == Agent:
      continue
    for thing in env.thingsByKind[kind]:
      if thing.hasValue and thing.teamId == teamId:
        return true
  false

proc computeAlliedWinners(env: Environment, primaryWinner: int): TeamMask {.inline.} =
  ## Given a primary winner team, compute the full bitmask of all winning teams
  ## by including all teams allied with the winner.
  if primaryWinner < 0 or primaryWinner >= MapRoomObjectsTeams:
    return NoTeamMask
  env.teamAlliances[primaryWinner]

proc checkConquestVictory(env: Environment): int =
  ## Returns the winning team ID if only one allied side remains, else -1.
  ## Allied teams are treated as one side: if only allied teams survive,
  ## the first surviving team is the primary winner and all allies share victory.
  var survivingMask: TeamMask = NoTeamMask
  var firstSurvivor = -1
  for teamId in 0 ..< MapRoomObjectsTeams:
    if env.teamHasUnitsOrBuildings(teamId):
      survivingMask = survivingMask or getTeamMask(teamId)
      if firstSurvivor < 0:
        firstSurvivor = teamId
  if survivingMask == NoTeamMask:
    return -1  # No survivors (draw)
  # Check if all surviving teams are allied with the first survivor
  let firstSurvivorAllies = env.teamAlliances[firstSurvivor]
  if (survivingMask and (not firstSurvivorAllies)) == NoTeamMask:
    # All surviving teams are within the first survivor's alliance
    return firstSurvivor
  -1

proc checkWonderVictory(env: Environment): int =
  ## Returns the winning team ID if a Wonder has survived its countdown, else -1.
  for teamId in 0 ..< MapRoomObjectsTeams:
    let builtStep = env.victoryStates[teamId].wonderBuiltStep
    if builtStep >= 0:
      # Check if the Wonder still exists
      var wonderAlive = false
      for wonder in env.thingsByKind[Wonder]:
        if not wonder.isNil and wonder.teamId == teamId:
          wonderAlive = true
          break
      if wonderAlive:
        if env.currentStep - builtStep >= WonderVictoryCountdown:
          return teamId
      else:
        # Wonder was destroyed, reset countdown
        env.victoryStates[teamId].wonderBuiltStep = -1
  -1

proc checkRelicVictory(env: Environment): int =
  ## Returns the winning team ID if one team (or allied group) holds all relics
  ## long enough, else -1. A relic is "held" when garrisoned in a Monastery.
  if TotalRelicsOnMap <= 0:
    return -1
  # Count garrisoned relics per team
  var teamRelics: array[MapRoomObjectsTeams, int]
  for monastery in env.thingsByKind[Monastery]:
    if monastery.isNil:
      continue
    let teamId = monastery.teamId
    if teamId >= 0 and teamId < MapRoomObjectsTeams:
      teamRelics[teamId] += monastery.garrisonedRelics
  # Check if any alliance group holds all relics (sum across allied teams)
  for teamId in 0 ..< MapRoomObjectsTeams:
    var allianceRelics = 0
    for otherTeam in 0 ..< MapRoomObjectsTeams:
      if (getTeamMask(otherTeam) and env.teamAlliances[teamId]) != NoTeamMask:
        allianceRelics += teamRelics[otherTeam]
    if allianceRelics >= TotalRelicsOnMap:
      let holdStart = env.victoryStates[teamId].relicHoldStartStep
      if holdStart < 0:
        env.victoryStates[teamId].relicHoldStartStep = env.currentStep
      elif env.currentStep - holdStart >= RelicVictoryCountdown:
        return teamId
    else:
      # Reset hold timer if alliance doesn't hold all relics
      env.victoryStates[teamId].relicHoldStartStep = -1
  -1

proc checkRegicideVictory(env: Environment): int =
  ## Returns winning team ID if only one allied group's king(s) survive, else -1.
  ## Teams without a king assigned are ignored (not playing regicide).
  var survivingMask: TeamMask = NoTeamMask
  var firstSurvivor = -1
  var participatingTeams = 0
  for teamId in 0 ..< MapRoomObjectsTeams:
    let kingId = env.victoryStates[teamId].kingAgentId
    if kingId < 0:
      continue  # Team has no king, not participating
    inc participatingTeams
    if isAgentAlive(env, env.agents[kingId]):
      survivingMask = survivingMask or getTeamMask(teamId)
      if firstSurvivor < 0:
        firstSurvivor = teamId
  if participatingTeams < 2:
    return -1  # Need at least 2 teams with kings
  if survivingMask == NoTeamMask:
    return -1  # All kings dead (draw)
  # Check if all surviving kings belong to the same alliance group
  let firstSurvivorAllies = env.teamAlliances[firstSurvivor]
  if (survivingMask and (not firstSurvivorAllies)) == NoTeamMask:
    return firstSurvivor
  -1

proc checkKingOfTheHillVictory(env: Environment): int =
  ## Returns the winning team ID if a team has controlled the hill for long enough, else -1.
  ## Control means having the most living units within HillControlRadius of a ControlPoint.
  ## Allied teams' units are combined. Tie between unallied groups means contested.
  for cp in env.thingsByKind[ControlPoint]:
    if cp.isNil:
      continue
    # Count living agents per team within the control radius using spatial query
    var teamUnits: array[MapRoomObjectsTeams, int]
    env.tempTowerTargets.setLen(0)
    collectThingsInRangeSpatial(env, cp.pos, Agent, HillControlRadius, env.tempTowerTargets)
    for agent in env.tempTowerTargets:
      if not isAgentAlive(env, agent):
        continue
      let teamId = getTeamId(agent)
      if teamId >= 0 and teamId < MapRoomObjectsTeams:
        inc teamUnits[teamId]
    # Aggregate allied teams' unit counts
    var allianceUnits: array[MapRoomObjectsTeams, int]
    for teamId in 0 ..< MapRoomObjectsTeams:
      for otherTeam in 0 ..< MapRoomObjectsTeams:
        if (getTeamMask(otherTeam) and env.teamAlliances[teamId]) != NoTeamMask:
          allianceUnits[teamId] += teamUnits[otherTeam]
    # Find the alliance group with the most units (tie only between unallied groups)
    var bestTeam = -1
    var bestCount = 0
    var tied = false
    for teamId in 0 ..< MapRoomObjectsTeams:
      if allianceUnits[teamId] > bestCount:
        bestTeam = teamId
        bestCount = allianceUnits[teamId]
        tied = false
      elif allianceUnits[teamId] == bestCount and bestCount > 0:
        # Only tied if from a different alliance
        if bestTeam >= 0 and (getTeamMask(teamId) and env.teamAlliances[bestTeam]) == NoTeamMask:
          tied = true
    if tied or bestTeam < 0:
      # Contested or empty - reset all timers
      for teamId in 0 ..< MapRoomObjectsTeams:
        env.victoryStates[teamId].hillControlStartStep = -1
    else:
      # bestTeam's alliance controls the hill
      if env.victoryStates[bestTeam].hillControlStartStep < 0:
        env.victoryStates[bestTeam].hillControlStartStep = env.currentStep
      elif env.currentStep - env.victoryStates[bestTeam].hillControlStartStep >= HillVictoryCountdown:
        return bestTeam
      # Reset all non-allied teams
      for teamId in 0 ..< MapRoomObjectsTeams:
        if (getTeamMask(teamId) and env.teamAlliances[bestTeam]) == NoTeamMask:
          env.victoryStates[teamId].hillControlStartStep = -1
  -1

proc updateWonderTracking(env: Environment) =
  ## Track when Wonders are first fully constructed (for countdown).
  ## Only starts countdown when wonder reaches full HP (construction complete).
  for teamId in 0 ..< MapRoomObjectsTeams:
    if env.victoryStates[teamId].wonderBuiltStep >= 0:
      continue  # Already tracking
    for wonder in env.thingsByKind[Wonder]:
      if not wonder.isNil and wonder.teamId == teamId and
          wonder.maxHp > 0 and wonder.hp >= wonder.maxHp:
        env.victoryStates[teamId].wonderBuiltStep = env.currentStep
        break

proc checkVictoryConditions(env: Environment) =
  ## Check all active victory conditions and set victoryWinner if met.
  ## When a winner is found, also compute victoryWinners mask including allies.
  let cond = env.config.victoryCondition

  # Update Wonder tracking regardless of condition
  if cond in {VictoryWonder, VictoryAll}:
    env.updateWonderTracking()

  # Conquest check
  if cond in {VictoryConquest, VictoryAll}:
    let winner = env.checkConquestVictory()
    if winner >= 0:
      env.victoryWinner = winner
      env.victoryWinners = computeAlliedWinners(env, winner)
      return

  # Wonder check
  if cond in {VictoryWonder, VictoryAll}:
    let winner = env.checkWonderVictory()
    if winner >= 0:
      env.victoryWinner = winner
      env.victoryWinners = computeAlliedWinners(env, winner)
      return

  # Relic check
  if cond in {VictoryRelic, VictoryAll}:
    let winner = env.checkRelicVictory()
    if winner >= 0:
      env.victoryWinner = winner
      env.victoryWinners = computeAlliedWinners(env, winner)
      return

  # Regicide check
  if cond in {VictoryRegicide, VictoryAll}:
    let winner = env.checkRegicideVictory()
    if winner >= 0:
      env.victoryWinner = winner
      env.victoryWinners = computeAlliedWinners(env, winner)
      return

  # King of the Hill check
  if cond in {VictoryKingOfTheHill, VictoryAll}:
    let winner = env.checkKingOfTheHillVictory()
    if winner >= 0:
      env.victoryWinner = winner
      env.victoryWinners = computeAlliedWinners(env, winner)
      return
