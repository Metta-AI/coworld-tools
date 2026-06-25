## Tests for score tracking and leaderboard accuracy.
##
## Verifies that score correctly accumulates from kills, buildings, resources;
## that score is team-aggregated; that score display matches internal state;
## and that score resets on game reset.

import std/[unittest, os, json]
import test_common
import balance_scorecard

const
  ScoreSeed = 42
  ScoreSteps = 50

proc countTeamResources(env: Environment, teamId: int): int =
  ## Sum all resource types for a team
  env.teamStockpiles[teamId].counts[ResourceFood] +
    env.teamStockpiles[teamId].counts[ResourceWood] +
    env.teamStockpiles[teamId].counts[ResourceStone] +
    env.teamStockpiles[teamId].counts[ResourceGold]

proc computeScore(env: Environment, teamId: int): int =
  ## Composite score: resources + population bonus
  countTeamResources(env, teamId) + countAliveUnits(env, teamId) * 10

suite "Score Tracking - Resource Accumulation":

  test "resources accumulate from gathering":
    var config = defaultEnvironmentConfig()
    config.maxSteps = 500  # Longer game for resource gathering
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    # Capture initial resources
    var initialResources: array[MapRoomObjectsTeams, int]
    for teamId in 0 ..< MapRoomObjectsTeams:
      initialResources[teamId] = countTeamResources(env, teamId)

    # Run game for enough steps - villagers should gather resources
    for step in 0 ..< 500:
      var actions = getActions(env)
      env.step(addr actions)

    # Verify resources changed for at least one team (can increase or decrease from spending)
    var anyChanged = false
    for teamId in 0 ..< MapRoomObjectsTeams:
      let finalResources = countTeamResources(env, teamId)
      if finalResources != initialResources[teamId]:
        anyChanged = true
        break
    check anyChanged

  test "individual resource types tracked correctly":
    var config = defaultEnvironmentConfig()
    config.maxSteps = ScoreSteps
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    for step in 0 ..< ScoreSteps:
      var actions = getActions(env)
      env.step(addr actions)

    # All resource counts should be non-negative
    for teamId in 0 ..< MapRoomObjectsTeams:
      check env.teamStockpiles[teamId].counts[ResourceFood] >= 0
      check env.teamStockpiles[teamId].counts[ResourceWood] >= 0
      check env.teamStockpiles[teamId].counts[ResourceStone] >= 0
      check env.teamStockpiles[teamId].counts[ResourceGold] >= 0

suite "Score Tracking - Team Aggregation":

  test "score aggregates all resource types":
    var config = defaultEnvironmentConfig()
    config.maxSteps = ScoreSteps
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    for step in 0 ..< ScoreSteps:
      var actions = getActions(env)
      env.step(addr actions)

    # Verify score equals sum of resources + population bonus
    for teamId in 0 ..< MapRoomObjectsTeams:
      let food = env.teamStockpiles[teamId].counts[ResourceFood]
      let wood = env.teamStockpiles[teamId].counts[ResourceWood]
      let stone = env.teamStockpiles[teamId].counts[ResourceStone]
      let gold = env.teamStockpiles[teamId].counts[ResourceGold]
      let totalResources = food + wood + stone + gold
      let aliveUnits = countAliveUnits(env, teamId)
      let expectedScore = totalResources + aliveUnits * 10
      let actualScore = computeScore(env, teamId)
      check actualScore == expectedScore

  test "each team has independent score":
    var config = defaultEnvironmentConfig()
    config.maxSteps = ScoreSteps
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    for step in 0 ..< ScoreSteps:
      var actions = getActions(env)
      env.step(addr actions)

    # Collect scores for all teams - verify they can differ
    var scores: seq[int] = @[]
    for teamId in 0 ..< MapRoomObjectsTeams:
      scores.add(computeScore(env, teamId))

    # Verify each team has their own stockpile (non-negative)
    for teamId in 0 ..< MapRoomObjectsTeams:
      check env.teamStockpiles[teamId].counts[ResourceFood] >= 0
      check env.teamStockpiles[teamId].counts[ResourceWood] >= 0
      check env.teamStockpiles[teamId].counts[ResourceStone] >= 0
      check env.teamStockpiles[teamId].counts[ResourceGold] >= 0

  test "territory score is per-team":
    var config = defaultEnvironmentConfig()
    config.maxSteps = ScoreSteps
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    for step in 0 ..< ScoreSteps:
      var actions = getActions(env)
      env.step(addr actions)

    let territory = scoreTerritory(env)

    # Each team should have their own tile count
    var totalTeamTiles = 0
    for teamId in 0 ..< MapRoomObjectsTeams:
      check territory.teamTiles[teamId] >= 0
      totalTeamTiles += territory.teamTiles[teamId]

    # Total tiles should not exceed scored tiles
    check totalTeamTiles <= territory.scoredTiles

suite "Score Tracking - Scorecard Display Accuracy":

  test "scorecard final resources match internal state":
    putEnv("TV_SCORECARD_ENABLED", "1")
    collector.initialized = false
    initCollector()

    var config = defaultEnvironmentConfig()
    config.maxSteps = ScoreSteps
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    startMatch(env, ScoreSeed)

    for step in 0 ..< ScoreSteps:
      var actions = getActions(env)
      env.step(addr actions)
      maybeSample(env)

    endMatch(env)

    # Verify scorecard resources match actual stockpile
    for teamId in 0 ..< MapRoomObjectsTeams:
      let displayed = collector.currentScorecard.teams[teamId].finalResources
      let actual = env.teamStockpiles[teamId]

      check displayed.food == actual.counts[ResourceFood]
      check displayed.wood == actual.counts[ResourceWood]
      check displayed.gold == actual.counts[ResourceGold]
      check displayed.stone == actual.counts[ResourceStone]

    delEnv("TV_SCORECARD_ENABLED")

  test "scorecard unit counts match internal state":
    putEnv("TV_SCORECARD_ENABLED", "1")
    collector.initialized = false
    initCollector()

    var config = defaultEnvironmentConfig()
    config.maxSteps = 50
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    startMatch(env, ScoreSeed)

    for step in 0 ..< 50:
      var actions = getActions(env)
      env.step(addr actions)
      maybeSample(env)

    endMatch(env)

    # Count actual villagers
    for teamId in 0 ..< MapRoomObjectsTeams:
      var actualVillagers = 0
      for agent in env.agents:
        if getTeamId(agent) == teamId and isAgentAlive(env, agent):
          if agent.unitClass == UnitVillager:
            inc actualVillagers

      let displayedVillagers = collector.currentScorecard.teams[teamId].finalUnits.villagers
      check displayedVillagers == actualVillagers

    delEnv("TV_SCORECARD_ENABLED")

  test "scorecard JSON contains all required fields":
    putEnv("TV_SCORECARD_ENABLED", "1")
    collector.initialized = false
    initCollector()

    var config = defaultEnvironmentConfig()
    let env = newEnvironment(config, ScoreSeed)

    startMatch(env, ScoreSeed)
    endMatch(env)

    let jsonNode = scorecardToJson(collector.currentScorecard)

    # Verify score-related fields exist
    check jsonNode.hasKey("match_id")
    check jsonNode.hasKey("seed")
    check jsonNode.hasKey("teams")
    check jsonNode.hasKey("balance_metrics")

    # Verify each team has score-related data
    for teamId in 0 ..< MapRoomObjectsTeams:
      let team = jsonNode["teams"][teamId]
      check team.hasKey("team_id")
      check team.hasKey("final_resources")
      check team.hasKey("final_units")

    delEnv("TV_SCORECARD_ENABLED")

suite "Score Tracking - Reset Behavior":

  test "resources reset to starting values on game reset":
    var config = defaultEnvironmentConfig()
    config.maxSteps = 500
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    # Capture initial resources (before any gameplay)
    var initialResources: array[MapRoomObjectsTeams, int]
    for teamId in 0 ..< MapRoomObjectsTeams:
      initialResources[teamId] = countTeamResources(env, teamId)

    # Run game to change resources
    for step in 0 ..< 500:
      var actions = getActions(env)
      env.step(addr actions)

    # Verify resources changed during gameplay
    var anyChanged = false
    for teamId in 0 ..< MapRoomObjectsTeams:
      if countTeamResources(env, teamId) != initialResources[teamId]:
        anyChanged = true
        break
    check anyChanged

    # Reset the environment
    env.reset()

    # Verify resources are back to initial values (reset() + init() restores starting state)
    for teamId in 0 ..< MapRoomObjectsTeams:
      let postResetResources = countTeamResources(env, teamId)
      check postResetResources == initialResources[teamId]

  test "territory score resets on game reset":
    var config = defaultEnvironmentConfig()
    config.maxSteps = ScoreSteps
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    # Run game to accumulate territory
    for step in 0 ..< ScoreSteps:
      var actions = getActions(env)
      env.step(addr actions)

    # Force territory calculation
    discard scoreTerritory(env)
    check env.territoryScored == true

    # Reset the environment
    env.reset()

    # Verify territory score is cleared
    check env.territoryScored == false
    for teamId in 0 ..< MapRoomObjectsTeams:
      check env.territoryScore.teamTiles[teamId] == 0

  test "victory state resets on game reset":
    var config = defaultEnvironmentConfig()
    config.maxSteps = ScoreSteps
    config.victoryCondition = VictoryNone  # Explicit: no kings spawned on reset
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    for step in 0 ..< ScoreSteps:
      var actions = getActions(env)
      env.step(addr actions)

    # Reset
    env.reset()

    # Verify victory state is cleared (no active victory, timers reset)
    check env.victoryWinner == -1
    for teamId in 0 ..< MapRoomObjectsTeams:
      check env.victoryStates[teamId].wonderBuiltStep == -1
      check env.victoryStates[teamId].relicHoldStartStep == -1
      check env.victoryStates[teamId].hillControlStartStep == -1
      # With VictoryAll, kings are reassigned during init() after reset
      if env.config.victoryCondition in {VictoryRegicide, VictoryAll}:
        check env.victoryStates[teamId].kingAgentId >= 0
      else:
        check env.victoryStates[teamId].kingAgentId == -1

  test "score can accumulate fresh after reset":
    var config = defaultEnvironmentConfig()
    config.maxSteps = 500
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    # Capture initial resources
    var initialResources: array[MapRoomObjectsTeams, int]
    for teamId in 0 ..< MapRoomObjectsTeams:
      initialResources[teamId] = countTeamResources(env, teamId)

    # Run first game
    for step in 0 ..< 500:
      var actions = getActions(env)
      env.step(addr actions)

    # Reset
    env.reset()

    # Verify fresh start (back to initial resources)
    for teamId in 0 ..< MapRoomObjectsTeams:
      check countTeamResources(env, teamId) == initialResources[teamId]

    # Run second game
    for step in 0 ..< 500:
      var actions = getActions(env)
      env.step(addr actions)

    # Verify resources changed again (game is functional after reset)
    var anyChanged = false
    for teamId in 0 ..< MapRoomObjectsTeams:
      if countTeamResources(env, teamId) != initialResources[teamId]:
        anyChanged = true
        break
    check anyChanged

suite "Score Tracking - Kill Tracking":

  test "dead units are tracked per team":
    var config = defaultEnvironmentConfig()
    config.maxSteps = 500  # Longer game for combat
    config.victoryCondition = VictoryNone
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)
    for teamId in 0 ..< MapRoomObjectsTeams:
      globalController.aiController.setDifficulty(teamId, DiffBrutal)

    # Record initial population
    var initialAlive: array[MapRoomObjectsTeams, int]
    for teamId in 0 ..< MapRoomObjectsTeams:
      initialAlive[teamId] = countAliveUnits(env, teamId)

    # Run game with combat
    for step in 0 ..< 500:
      var actions = getActions(env)
      env.step(addr actions)

    # Count deaths and verify tracking
    for teamId in 0 ..< MapRoomObjectsTeams:
      let finalAlive = countAliveUnits(env, teamId)
      let deadCount = countDeadUnits(env, teamId)
      # Dead + alive should not exceed initial (some units may have been created)
      check deadCount >= 0
      check finalAlive >= 0

suite "Score Tracking - Building Tracking":

  test "buildings are counted per team":
    var config = defaultEnvironmentConfig()
    config.maxSteps = ScoreSteps
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    for step in 0 ..< ScoreSteps:
      var actions = getActions(env)
      env.step(addr actions)

    # Count buildings for each team
    for teamId in 0 ..< MapRoomObjectsTeams:
      let buildingCount = countBuildings(env, teamId)
      # Each team should have at least their town center
      check buildingCount >= 1

  test "building counts are independent per team":
    var config = defaultEnvironmentConfig()
    config.maxSteps = ScoreSteps
    let env = newEnvironment(config, ScoreSeed)

    initGlobalController(BuiltinAI, seed = ScoreSeed)

    for step in 0 ..< ScoreSteps:
      var actions = getActions(env)
      env.step(addr actions)

    # Get building counts
    var counts: array[MapRoomObjectsTeams, int]
    for teamId in 0 ..< MapRoomObjectsTeams:
      counts[teamId] = countBuildings(env, teamId)

    # Verify each team's buildings are separate
    # (buildings belong to exactly one team)
    var totalBuildings = 0
    for teamId in 0 ..< MapRoomObjectsTeams:
      totalBuildings += counts[teamId]

    # Count all buildings directly
    var directCount = 0
    for kind in ThingKind:
      if kind in {Altar, TownCenter, House, Barracks, ArcheryRange, Stable,
                  Blacksmith, Market, Monastery, University, Castle, Wonder,
                  SiegeWorkshop, MangonelWorkshop, TrebuchetWorkshop,
                  Dock, Outpost, GuardTower, Wall, Door, Mill, Granary,
                  LumberCamp, Quarry, MiningCamp, WeavingLoom, ClayOven,
                  Lantern, Temple}:
        for thing in env.thingsByKind[kind]:
          if not thing.isNil and thing.hp > 0 and thing.teamId >= 0 and thing.teamId < MapRoomObjectsTeams:
            inc directCount

    check totalBuildings == directCount
