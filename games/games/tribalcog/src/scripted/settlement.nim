## Town split AI: detects overcrowding and initiates settler groups.
## Also handles town founding when settlers arrive at their target.

import ai_core
export ai_core

const SettlerFoundingQuorum = 5  ## Minimum arrived settlers to found a town

proc checkTownSplitCondition*(controller: Controller, env: Environment,
                               teamId: int, altarPos: IVec2): bool =
  ## Returns true if the town at altarPos has grown too large and should split.
  ## Checks: population threshold, resource affordability, cooldown.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false

  # Cooldown check: don't trigger if a split happened recently for this team
  let lastSplit = controller.townSplitLastStep[teamId]
  if lastSplit > 0 and (env.currentStep.int32 - lastSplit) < TownSplitCooldownSteps:
    return false

  # Population check: count villagers at this altar
  var popCount = 0
  for agent in env.teamAliveAgents(teamId):
    if agent.homeAltar == altarPos:
      inc popCount
  if popCount < TownSplitPopulationThreshold:
    return false

  # Resource check: team needs enough wood for a town center (14 wood)
  let woodCount = env.stockpileCount(teamId, ResourceWood)
  if woodCount < 14:
    return false

  true

proc selectSettlerGroup*(controller: Controller, env: Environment,
                          teamId: int, altarPos: IVec2): seq[int] =
  ## Pick TownSplitSettlerCount villagers near the altar for the settler group.
  ## Prefers idle villagers over busy ones, excludes existing settlers.
  result = @[]

  # Collect candidates: living villagers at this altar who aren't already settlers
  type Candidate = tuple[agentId: int, dist: int32, isIdle: bool]
  var candidates: seq[Candidate] = @[]

  for agent in env.teamAliveAgents(teamId):
    if agent.homeAltar != altarPos:
      continue
    if agent.isSettler:
      continue
    # Only pick villagers (not military units)
    if agent.unitClass != UnitVillager:
      continue
    let dist = chebyshevDist(agent.pos, altarPos)
    candidates.add((agentId: agent.agentId, dist: dist, isIdle: agent.isIdle))

  if candidates.len == 0:
    return @[]

  # Sort: idle villagers first, then by distance to altar (closest first)
  # Simple insertion sort since candidate count is small
  for i in 1 ..< candidates.len:
    let key = candidates[i]
    var j = i - 1
    while j >= 0:
      let swap = if key.isIdle and not candidates[j].isIdle:
        true
      elif key.isIdle == candidates[j].isIdle and key.dist < candidates[j].dist:
        true
      else:
        false
      if not swap:
        break
      candidates[j + 1] = candidates[j]
      dec j
    candidates[j + 1] = key

  # Select up to TownSplitSettlerCount villagers
  let count = min(TownSplitSettlerCount, candidates.len)
  for i in 0 ..< count:
    let agentId = candidates[i].agentId
    if agentId < 0 or agentId >= env.agents.len:
      continue
    let agent = env.agents[agentId]
    agent.isSettler = true
    result.add(agentId)

proc findNewTownSite*(controller: Controller, env: Environment,
                       teamId: int, altarPos: IVec2): IVec2 =
  ## Search for a suitable new town location in a ring around the altar.
  ## Prefers locations near resources with enough open space.
  result = ivec2(-1, -1)
  var bestScore = -1

  # Spiral outward from preferred distance (midpoint of min/max range)
  let preferredDist = (TownSplitMinDistance + TownSplitMaxDistance) div 2

  # Scan positions in the ring between min and max distance
  let scanMin = max(0, altarPos.x.int - TownSplitMaxDistance)
  let scanMaxX = min(MapWidth - 1, altarPos.x.int + TownSplitMaxDistance)
  let scanMinY = max(0, altarPos.y.int - TownSplitMaxDistance)
  let scanMaxY = min(MapHeight - 1, altarPos.y.int + TownSplitMaxDistance)

  for x in scanMin .. scanMaxX:
    for y in scanMinY .. scanMaxY:
      let pos = ivec2(x.int32, y.int32)
      let dist = chebyshevDist(pos, altarPos).int

      # Must be within the ring
      if dist < TownSplitMinDistance or dist > TownSplitMaxDistance:
        continue

      # Must be inside playable area (away from borders)
      if pos.x < (MapBorder + 2).int32 or pos.x >= (MapWidth - MapBorder - 2).int32 or
         pos.y < (MapBorder + 2).int32 or pos.y >= (MapHeight - MapBorder - 2).int32:
        continue

      # Must have enough open space (3x3 area centered on pos)
      var openSpace = true
      for dx in -TownSplitOpenSpaceRadius .. TownSplitOpenSpaceRadius:
        for dy in -TownSplitOpenSpaceRadius .. TownSplitOpenSpaceRadius:
          let checkPos = ivec2(pos.x + dx.int32, pos.y + dy.int32)
          if not isValidPos(checkPos) or not env.isEmpty(checkPos):
            openSpace = false
            break
          # Also check terrain isn't water or otherwise blocked
          if isBlockedTerrain(env.terrain[checkPos.x][checkPos.y]) or
             env.terrain[checkPos.x][checkPos.y] == Water:
            openSpace = false
            break
        if not openSpace:
          break
      if not openSpace:
        continue

      # Must not overlap with existing altars.
      var tooCloseToAltar = false
      for altar in env.thingsByKind[Altar]:
        if altar.teamId < 0 or (altar.teamId == teamId and altar.pos == altarPos):
          continue
        let minAltarDist = (if altar.teamId == teamId:
                              TownSplitMinDistance
                            else:
                              TownSplitMinDistance div 2)
        if chebyshevDist(pos, altar.pos) < minAltarDist:
          tooCloseToAltar = true
          break
      if tooCloseToAltar:
        continue

      # Score the location: prefer nearness to resources and optimal distance
      var score = 0

      # Score for nearby resources (trees, stone, gold within radius 8)
      let resourceRadius = 8
      let rMinX = max(0, x - resourceRadius)
      let rMaxX = min(MapWidth - 1, x + resourceRadius)
      let rMinY = max(0, y - resourceRadius)
      let rMaxY = min(MapHeight - 1, y + resourceRadius)
      for rx in rMinX .. rMaxX:
        for ry in rMinY .. rMaxY:
          let thing = env.grid[rx][ry]
          if not thing.isNil:
            case thing.kind
            of Tree, Stump: score += 2
            of Stone, Stalagmite: score += 3
            of Gold: score += 4
            else: discard

      # Prefer distance closer to the preferred range midpoint
      let distPenalty = abs(dist - preferredDist)
      score -= distPenalty * 2

      if score > bestScore:
        bestScore = score
        result = pos

proc placeTownCenter(env: Environment, center: IVec2, teamId: int): IVec2 =
  ## Place a town center near a new altar. Follows the same pattern as
  ## placeStartingTownCenter in spawn.nim.
  for radius in 1 .. 3:
    for dx in -radius .. radius:
      for dy in -radius .. radius:
        if max(abs(dx), abs(dy)) != radius:
          continue
        let pos = center + ivec2(dx.int32, dy.int32)
        if not isValidPos(pos):
          continue
        if env.terrain[pos.x][pos.y] == Water:
          continue
        if env.hasDoor(pos) or not env.isEmpty(pos):
          continue
        env.add(Thing(kind: TownCenter, pos: pos, teamId: teamId))
        return pos
  # Fallback: place directly east
  let fallback = center + ivec2(1, 0)
  if isValidPos(fallback) and env.isEmpty(fallback) and
      env.terrain[fallback.x][fallback.y] != Water and not env.hasDoor(fallback):
    env.add(Thing(kind: TownCenter, pos: fallback, teamId: teamId))
    return fallback
  center

proc foundNewTown(env: Environment, teamId: int, site: IVec2,
                   settlers: seq[int]) =
  ## Found a new town at the given site: place Altar + TownCenter,
  ## register in altarColors, reassign settlers' homeAltar, clear flags,
  ## and deduct resources.

  # 1. Find a clear position at or near the site for the altar
  var altarPos = site
  if not env.isEmpty(site):
    # Search nearby for an empty spot
    altarPos = ivec2(-1, -1)
    for radius in 1 .. 3:
      for dx in -radius .. radius:
        for dy in -radius .. radius:
          if max(abs(dx), abs(dy)) != radius:
            continue
          let pos = site + ivec2(dx.int32, dy.int32)
          if isValidPos(pos) and env.isEmpty(pos) and
              env.terrain[pos.x][pos.y] != Water:
            altarPos = pos
            break
        if altarPos.x >= 0: break
      if altarPos.x >= 0: break
    if altarPos.x < 0:
      return  # Cannot place altar, abort founding

  let altar = Thing(
    kind: Altar,
    pos: altarPos,
    teamId: teamId
  )
  altar.inventory = emptyInventory()
  altar.hearts = MapObjectAltarInitialHearts
  env.add(altar)

  # 2. Register altar color (use the team's color)
  if teamId < env.teamColors.len:
    env.altarColors[altarPos] = env.teamColors[teamId]

  # 3. Place a town center nearby (only deduct resources if placement succeeds)
  let tcPos = placeTownCenter(env, altarPos, teamId)
  let tcPlaced = tcPos != altarPos  # Returns altarPos on failure

  # 4. Reassign settlers' homeAltar to the new altar and clear flags
  for agentId in settlers:
    if agentId < 0 or agentId >= env.agents.len:
      continue
    let agent = env.agents[agentId]
    if not isAgentAlive(env, agent):
      continue
    agent.homeAltar = altarPos
    agent.isSettler = false
    agent.settlerTarget = ivec2(-1, -1)
    agent.settlerArrived = false

  # 5. Deduct wood for the town center (only if TC was actually placed)
  if tcPlaced:
    let woodCost = 14
    env.teamStockpiles[teamId].counts[ResourceWood] =
      max(0, env.teamStockpiles[teamId].counts[ResourceWood] - woodCost)

proc checkSettlerArrivals*(controller: Controller, env: Environment) =
  ## Check if any settler groups have enough members arrived to found a town.
  ## Called periodically from updateController alongside checkAndTriggerTownSplit.

  # Only check at the configured interval (same as split checks)
  if env.currentStep.int32 mod TownSplitCheckInterval != 0:
    return

  for teamId in 0 ..< MapRoomObjectsTeams:
    # Collect settlers by target site
    var settlersByTarget: seq[(IVec2, seq[int])] = @[]

    for agent in env.teamAliveAgents(teamId):
      if not agent.isSettler or agent.settlerTarget.x < 0:
        continue

      # Find or create entry for this target
      var found = false
      for entry in settlersByTarget.mitems:
        if entry[0] == agent.settlerTarget:
          if agent.settlerArrived:
            entry[1].add(agent.agentId)
          found = true
          break
      if not found and agent.settlerArrived:
        settlersByTarget.add((agent.settlerTarget, @[agent.agentId]))

    # For each target site, check if enough settlers have arrived
    for (site, arrivedSettlers) in settlersByTarget:
      if arrivedSettlers.len < SettlerFoundingQuorum:
        continue

      # Collect ALL settlers targeting this site (arrived or not) for reassignment
      var allSettlers: seq[int] = @[]
      for agent in env.teamAliveAgents(teamId):
        if agent.isSettler and agent.settlerTarget == site:
          allSettlers.add(agent.agentId)

      # Found the new town
      foundNewTown(env, teamId, site, allSettlers)

proc checkAndTriggerTownSplit*(controller: Controller, env: Environment) =
  ## Called periodically from updateController to check all teams for town splits.
  let currentStep = env.currentStep.int32

  # Only check at the configured interval
  if currentStep mod TownSplitCheckInterval != 0:
    return

  for teamId in 0 ..< MapRoomObjectsTeams:
    # Check each altar for this team
    for altar in env.thingsByKind[Altar]:
      if altar.teamId != teamId:
        continue

      if not checkTownSplitCondition(controller, env, teamId, altar.pos):
        continue

      # Find a new town site
      let newSite = findNewTownSite(controller, env, teamId, altar.pos)
      if newSite.x < 0:
        continue

      # Select settlers
      let settlers = selectSettlerGroup(controller, env, teamId, altar.pos)
      if settlers.len == 0:
        continue

      # Mark settlers with their target position
      for agentId in settlers:
        if agentId < 0 or agentId >= env.agents.len:
          continue
        let agent = env.agents[agentId]
        agent.settlerTarget = newSite

      # Record the split for cooldown
      controller.townSplitLastStep[teamId] = currentStep

      # Only one split per team per check
      break
