# Population respawn - Altar respawn and temple hybrid spawn
# This file is included by step.nim

# ============================================================================
# Population Respawn
# ============================================================================

proc stepPopRespawn*(env: Environment) =
  ## Handle population respawn: dead agents at altars and temple hybrid spawning.
  ## Called once per step from the main step() function.

  # Catch any agents that were reduced to zero HP during the step
  env.enforceZeroHpDeaths()

  # Reuse pre-computed team population counts from step() (env.stepTeamPopCounts).
  # We mutate these in-place as agents respawn — safe because step() recalculates
  # them fresh at the start of each step before any actions are processed.

  # -------------------------------------------------------------------------
  # Respawn dead agents at their altars
  # -------------------------------------------------------------------------
  for agentId in 0 ..< MapAgents:
    let agent = env.agents[agentId]

    # Check if agent is dead and has a home altar
    if env.terminated[agentId] == 1.0 and agent.homeAltar.x >= 0:
      let teamId = getTeamId(agent)
      if teamId < 0 or teamId >= MapRoomObjectsTeams:
        continue
      if env.stepTeamPopCounts[teamId] >= env.stepTeamPopCaps[teamId]:
        continue
      # Find the altar via direct grid lookup (avoids O(things) scan)
      let altarThing = env.getThing(agent.homeAltar)

      # Respawn if altar exists and has at least one heart to spend
      if not isNil(altarThing) and altarThing.kind == ThingKind.Altar and
          altarThing.hearts >= MapObjectAltarRespawnCost:
        # Find first empty position around altar (no allocation)
        let respawnPos = env.findFirstEmptyPositionAround(altarThing.pos, 2)
        if respawnPos.x >= 0:
          # Deduct heart only after confirming a valid respawn position exists
          altarThing.hearts = altarThing.hearts - MapObjectAltarRespawnCost
          env.updateObservations(altarHeartsLayer, altarThing.pos, altarThing.hearts)
          # Respawn the agent
          let oldPos = agent.pos
          agent.pos = respawnPos
          agent.inventory = emptyInventory()
          agent.frozen = 0
          applyUnitClass(env, agent, UnitVillager)
          env.terminated[agentId] = 0.0
          when defined(eventLog):
            logEvent(
              ecSpawn,
              teamId,
              "Spawned " & $agent.unitClass & " at (" & $respawnPos.x & "," & $respawnPos.y & ")",
              env.currentStep,
            )

          # Update grid
          env.grid[agent.pos.x][agent.pos.y] = agent
          inc env.stepTeamPopCounts[teamId]
          updateSpatialIndex(env, agent, oldPos)

          # Update observations
          env.updateObservations(AgentLayer, agent.pos, getTeamId(agent) + 1)
          env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)

  # -------------------------------------------------------------------------
  # Temple hybrid spawn: two adjacent agents + heart -> spawn a new villager
  # -------------------------------------------------------------------------
  for temple in env.thingsByKind[Temple]:
    if temple.cooldown > 0:
      continue
    var parentA: Thing = nil
    var parentB: Thing = nil
    var teamId = -1
    for d in AdjacentOffsets8:
      let pos = temple.pos + d
      if not isValidPos(pos):
        continue
      let candidate = env.grid[pos.x][pos.y]
      if isNil(candidate) or candidate.kind != Agent:
        continue
      if not isAgentAlive(env, candidate):
        continue
      if candidate.unitClass == UnitGoblin:
        continue
      let candTeam = getTeamId(candidate)
      if candTeam < 0 or candTeam >= MapRoomObjectsTeams:
        continue
      if parentA.isNil:
        parentA = candidate
        teamId = candTeam
      elif candTeam == teamId and candidate.agentId != parentA.agentId:
        parentB = candidate
        break
    if parentA.isNil or parentB.isNil:
      continue
    if env.stepTeamPopCounts[teamId] >= env.stepTeamPopCaps[teamId]:
      continue
    # Find a dormant agent slot for this team.
    let teamStart = teamId * MapAgentsPerTeam
    let teamEnd = teamStart + MapAgentsPerTeam
    var childId = -1
    for id in teamStart ..< teamEnd:
      if env.terminated[id] == 1.0:
        childId = id
        break
    if childId < 0:
      continue
    let spawnPos = env.findFirstEmptyPositionAround(temple.pos, 2)
    if spawnPos.x < 0:
      continue
    let altarThing = env.getThing(parentA.homeAltar)
    if isNil(altarThing) or altarThing.kind != ThingKind.Altar:
      continue
    if altarThing.hearts < MapObjectAltarRespawnCost:
      continue
    # Consume heart and spawn the child.
    altarThing.hearts = altarThing.hearts - MapObjectAltarRespawnCost
    env.updateObservations(altarHeartsLayer, altarThing.pos, altarThing.hearts)
    let child = env.agents[childId]
    let childOldPos = child.pos
    child.pos = spawnPos
    child.inventory = emptyInventory()
    child.frozen = 0
    applyUnitClass(env, child, UnitVillager)
    env.terminated[childId] = 0.0
    when defined(eventLog):
      logEvent(
        ecSpawn,
        teamId,
        "Spawned " & $child.unitClass & " at (" & $spawnPos.x & "," & $spawnPos.y & ")",
        env.currentStep,
      )
    env.grid[child.pos.x][child.pos.y] = child
    inc env.stepTeamPopCounts[teamId]
    updateSpatialIndex(env, child, childOldPos)
    env.updateObservations(AgentLayer, child.pos, getTeamId(child) + 1)
    env.updateObservations(AgentOrientationLayer, child.pos, child.orientation.int)
    env.templeHybridRequests.add TempleHybridRequest(
      parentA: parentA.agentId,
      parentB: parentB.agentId,
      childId: childId,
      teamId: teamId,
      pos: temple.pos
    )
    temple.cooldown = TempleHybridCooldown
