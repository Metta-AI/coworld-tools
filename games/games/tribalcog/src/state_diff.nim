## Step-by-step environment diff logging for state mutation debugging.

when defined(stateDiff):
  import
    std/strformat,
    items, types

  type
    TeamSnapshot* = object
      ## Snapshot of one team's tracked state.
      agentCount*: int
      aliveCount*: int
      deadCount*: int
      food*: int
      wood*: int
      gold*: int
      stone*: int
      water*: int
      villagerCount*: int
      archerCount*: int
      knightCount*: int
      manAtArmsCount*: int
      monkCount*: int

    StateSnapshot* = object
      ## Snapshot of key environment fields for diffing.
      step*: int
      victoryWinner*: int
      thingCount*: int
      agentCount*: int
      projectileCount*: int
      teams*: array[MapRoomObjectsTeams, TeamSnapshot]
      houseCount*: int
      altarCount*: int
      towerCount*: int
      wallCount*: int
      marketCount*: int
      castleCount*: int

    StateDiffState* = object
      ## Cached state used by the diff logger.
      prevSnapshot*: StateSnapshot
      hasSnapshot*: bool

  var
    diffState*: StateDiffState
    diffInitialized* = false

  proc initStateDiff*() =
    ## Reset state-diff tracking.
    diffState = StateDiffState(hasSnapshot: false)
    diffInitialized = true

  proc ensureStateDiffInit*() =
    ## Initialize state-diff tracking on first use.
    if not diffInitialized:
      initStateDiff()

  proc captureSnapshot*(env: Environment): StateSnapshot =
    ## Capture the current environment state into a snapshot.
    result.step = env.currentStep
    result.victoryWinner = env.victoryWinner
    result.thingCount = env.things.len
    result.agentCount = env.agents.len
    result.projectileCount = env.projectiles.len

    for thing in env.things:
      if thing.isNil:
        continue
      case thing.kind
      of House:
        inc result.houseCount
      of Altar:
        inc result.altarCount
      of GuardTower, Outpost:
        inc result.towerCount
      of Wall:
        inc result.wallCount
      of Market:
        inc result.marketCount
      of Castle:
        inc result.castleCount
      else:
        discard

    for teamId in 0 ..< MapRoomObjectsTeams:
      var teamSnapshot: TeamSnapshot
      teamSnapshot.food = env.teamStockpiles[teamId].counts[ResourceFood]
      teamSnapshot.wood = env.teamStockpiles[teamId].counts[ResourceWood]
      teamSnapshot.gold = env.teamStockpiles[teamId].counts[ResourceGold]
      teamSnapshot.stone = env.teamStockpiles[teamId].counts[ResourceStone]
      teamSnapshot.water = env.teamStockpiles[teamId].counts[ResourceWater]
      result.teams[teamId] = teamSnapshot

    for agent in env.liveAgents:
      let teamId = agent.getTeamId()
      if teamId < 0 or teamId >= MapRoomObjectsTeams:
        continue

      inc result.teams[teamId].agentCount
      if env.terminated[agent.agentId] == 0.0:
        inc result.teams[teamId].aliveCount
        case agent.unitClass
        of UnitVillager:
          inc result.teams[teamId].villagerCount
        of UnitArcher:
          inc result.teams[teamId].archerCount
        of UnitKnight:
          inc result.teams[teamId].knightCount
        of UnitManAtArms:
          inc result.teams[teamId].manAtArmsCount
        of UnitMonk:
          inc result.teams[teamId].monkCount
        else:
          discard
      else:
        inc result.teams[teamId].deadCount

  proc teamChanged(oldTeam, newTeam: TeamSnapshot): bool =
    ## Return true when any tracked team field changed.
    oldTeam.aliveCount != newTeam.aliveCount or
      oldTeam.deadCount != newTeam.deadCount or
      oldTeam.food != newTeam.food or
      oldTeam.wood != newTeam.wood or
      oldTeam.gold != newTeam.gold or
      oldTeam.stone != newTeam.stone or
      oldTeam.water != newTeam.water or
      oldTeam.villagerCount != newTeam.villagerCount or
      oldTeam.archerCount != newTeam.archerCount or
      oldTeam.knightCount != newTeam.knightCount or
      oldTeam.manAtArmsCount != newTeam.manAtArmsCount or
      oldTeam.monkCount != newTeam.monkCount

  proc snapshotChanged(oldSnap, newSnap: StateSnapshot): bool =
    ## Return true when any tracked snapshot field changed.
    if oldSnap.victoryWinner != newSnap.victoryWinner or
      oldSnap.thingCount != newSnap.thingCount or
      oldSnap.projectileCount != newSnap.projectileCount or
      oldSnap.houseCount != newSnap.houseCount or
      oldSnap.altarCount != newSnap.altarCount or
      oldSnap.towerCount != newSnap.towerCount or
      oldSnap.wallCount != newSnap.wallCount or
      oldSnap.marketCount != newSnap.marketCount or
      oldSnap.castleCount != newSnap.castleCount:
        return true
    for teamId in 0 ..< MapRoomObjectsTeams:
      if teamChanged(oldSnap.teams[teamId], newSnap.teams[teamId]):
        return true
    false

  proc logDiff(name: string, oldVal, newVal: int) =
    ## Log one integer field diff when the value changed.
    if oldVal != newVal:
      let
        delta = newVal - oldVal
        sign =
          if delta > 0:
            "+"
          else:
            ""
      echo &"  {name}: {oldVal} -> {newVal} ({sign}{delta})"

  proc logTeamDiff(teamId: int, oldTeam, newTeam: TeamSnapshot) =
    ## Log diffs for one team snapshot.
    if not teamChanged(oldTeam, newTeam):
      return

    echo &"  Team {teamId}:"
    logDiff("    alive", oldTeam.aliveCount, newTeam.aliveCount)
    logDiff("    dead", oldTeam.deadCount, newTeam.deadCount)
    logDiff("    villagers", oldTeam.villagerCount, newTeam.villagerCount)
    logDiff("    archers", oldTeam.archerCount, newTeam.archerCount)
    logDiff("    knights", oldTeam.knightCount, newTeam.knightCount)
    logDiff(
      "    manAtArms",
      oldTeam.manAtArmsCount,
      newTeam.manAtArmsCount
    )
    logDiff("    monks", oldTeam.monkCount, newTeam.monkCount)
    logDiff("    food", oldTeam.food, newTeam.food)
    logDiff("    wood", oldTeam.wood, newTeam.wood)
    logDiff("    gold", oldTeam.gold, newTeam.gold)
    logDiff("    stone", oldTeam.stone, newTeam.stone)
    logDiff("    water", oldTeam.water, newTeam.water)

  proc compareAndLog*(oldSnap, newSnap: StateSnapshot) =
    ## Compare two snapshots and log all differences.
    if not snapshotChanged(oldSnap, newSnap):
      return

    echo &"[StateDiff] Step {oldSnap.step} -> {newSnap.step}:"
    logDiff("  victoryWinner", oldSnap.victoryWinner, newSnap.victoryWinner)
    logDiff("  things", oldSnap.thingCount, newSnap.thingCount)
    logDiff("  projectiles", oldSnap.projectileCount, newSnap.projectileCount)
    logDiff("  houses", oldSnap.houseCount, newSnap.houseCount)
    logDiff("  altars", oldSnap.altarCount, newSnap.altarCount)
    logDiff("  towers", oldSnap.towerCount, newSnap.towerCount)
    logDiff("  walls", oldSnap.wallCount, newSnap.wallCount)
    logDiff("  markets", oldSnap.marketCount, newSnap.marketCount)
    logDiff("  castles", oldSnap.castleCount, newSnap.castleCount)
    for teamId in 0 ..< MapRoomObjectsTeams:
      logTeamDiff(teamId, oldSnap.teams[teamId], newSnap.teams[teamId])

  proc capturePreStep*(env: Environment) =
    ## Capture the pre-step snapshot.
    ensureStateDiffInit()
    diffState.prevSnapshot = captureSnapshot(env)
    diffState.hasSnapshot = true

  proc comparePostStep*(env: Environment) =
    ## Compare the post-step state against the previous snapshot.
    ensureStateDiffInit()
    if not diffState.hasSnapshot:
      return
    let newSnapshot = captureSnapshot(env)
    compareAndLog(diffState.prevSnapshot, newSnapshot)
    diffState.prevSnapshot = newSnapshot

when not defined(stateDiff):
  ## Initialize state-diff tracking in non-stateDiff builds.
  template ensureStateDiffInit*() =
    discard

  ## Capture a pre-step snapshot in non-stateDiff builds.
  template capturePreStep*(env: untyped) =
    discard

  ## Compare post-step state in non-stateDiff builds.
  template comparePostStep*(env: untyped) =
    discard
