## Team balance verification tests across multiple game seeds.
## Runs N games with different seeds, collects per-team metrics,
## and verifies no team has a systematic advantage.

import std/[unittest, math, strformat, strutils, sequtils]
import test_common

const
  NumSeeds = 16
  StepsPerGame = VeryLongSimSteps
  MaxWinRate = 0.80  # Fail if one team wins >80% of games (13/16)
  # Use more seeds for better statistical coverage
  Seeds = [42, 137, 256, 500, 777, 1024, 1337, 2048,
           3141, 4096, 5555, 6789, 7777, 8192, 9001, 9999]

type
  TeamMetrics = object
    totalResources: int
    unitsKilled: int      # Dead agents on THIS team (killed by others)
    buildingsBuilt: int
    aliveUnits: int
    territoryTiles: int

  GameResult = object
    seed: int
    winnerTeam: int  # team with highest score, or -1
    metrics: array[MapRoomObjectsTeams, TeamMetrics]

proc collectMetrics(env: Environment): array[MapRoomObjectsTeams, TeamMetrics] =
  for teamId in 0 ..< MapRoomObjectsTeams:
    result[teamId].totalResources = getTotalStockpile(env, teamId)
    result[teamId].aliveUnits = countAliveUnits(env, teamId)
    result[teamId].unitsKilled = countDeadUnits(env, teamId)
    result[teamId].buildingsBuilt = countBuildings(env, teamId)

  let territory = scoreTerritory(env)
  for teamId in 0 ..< MapRoomObjectsTeams:
    result[teamId].territoryTiles = territory.teamTiles[teamId]

proc computeScore(m: TeamMetrics): int =
  ## Composite score: resources + population (territory excluded for position-independence)
  m.totalResources + m.aliveUnits * 10

proc runGame(seed: int): GameResult =
  var config = defaultEnvironmentConfig()
  config.maxSteps = StepsPerGame
  config.victoryCondition = VictoryNone  # Let all games run to completion
  let env = newEnvironment(config, seed)

  # Use different seed for AI to break correlation between map layout and AI decisions
  initGlobalController(BuiltinAI, seed = seed xor 0x12345678)
  for teamId in 0 ..< MapRoomObjectsTeams:
    globalController.aiController.setDifficulty(teamId, DiffBrutal)

  for step in 0 ..< StepsPerGame:
    var actions = getActions(env)
    env.step(addr actions)
    if env.shouldReset:
      break

  result.seed = seed
  result.metrics = collectMetrics(env)

  # Determine winner by composite score
  var bestScore = -1
  var bestTeam = -1
  for teamId in 0 ..< MapRoomObjectsTeams:
    let score = computeScore(result.metrics[teamId])
    if score > bestScore:
      bestScore = score
      bestTeam = teamId
  result.winnerTeam = bestTeam

proc stddev(values: seq[float]): float =
  if values.len <= 1: return 0.0
  let mean = values.foldl(a + b, 0.0) / values.len.float
  var sumSqDiff = 0.0
  for v in values:
    sumSqDiff += (v - mean) * (v - mean)
  sqrt(sumSqDiff / (values.len.float - 1.0))

proc printBalanceReport(results: seq[GameResult]) =
  echo ""
  echo "=" .repeat(80)
  echo "TEAM BALANCE REPORT"
  echo "=" .repeat(80)
  echo &"Games: {results.len} | Steps per game: {StepsPerGame}"
  echo "-" .repeat(80)

  # Per-seed winner
  echo "\nPer-seed results:"
  for r in results:
    echo &"  Seed {r.seed:>5}: Winner = Team {r.winnerTeam}"

  # Win counts
  var winCounts: array[MapRoomObjectsTeams, int]
  for r in results:
    if r.winnerTeam >= 0:
      inc winCounts[r.winnerTeam]

  echo "\nWin distribution:"
  for teamId in 0 ..< MapRoomObjectsTeams:
    let pct = if results.len > 0: winCounts[teamId].float / results.len.float * 100.0 else: 0.0
    let bar = "#" .repeat(winCounts[teamId] * 5)
    echo &"  Team {teamId}: {winCounts[teamId]:>2} wins ({pct:5.1f}%) {bar}"

  # Aggregate stats per team
  echo "\nAggregate metrics (mean across seeds):"
  echo "    Team  Resources  Killed  Buildings  Population  Territory    Score"
  echo "  " & "-" .repeat(70)

  var allScores: seq[seq[float]] = newSeq[seq[float]](MapRoomObjectsTeams)
  for teamId in 0 ..< MapRoomObjectsTeams:
    allScores[teamId] = newSeq[float](results.len)

  for teamId in 0 ..< MapRoomObjectsTeams:
    var totalRes, totalKilled, totalBld, totalPop, totalTerr, totalScore: float
    for i, r in results:
      let m = r.metrics[teamId]
      totalRes += m.totalResources.float
      totalKilled += m.unitsKilled.float
      totalBld += m.buildingsBuilt.float
      totalPop += m.aliveUnits.float
      totalTerr += m.territoryTiles.float
      allScores[teamId][i] = computeScore(m).float
      totalScore += computeScore(m).float
    let n = results.len.float
    echo &"  {teamId:>6} {totalRes/n:>10.1f} {totalKilled/n:>7.1f} {totalBld/n:>10.1f} {totalPop/n:>11.1f} {totalTerr/n:>10.1f} {totalScore/n:>8.1f}"

  # Standard deviation of scores
  echo "\nScore standard deviation across seeds:"
  for teamId in 0 ..< MapRoomObjectsTeams:
    let sd = stddev(allScores[teamId])
    echo &"  Team {teamId}: {sd:>8.1f}"

  echo "=" .repeat(80)

suite "Balance - Team fairness across seeds":
  var results: seq[GameResult]

  setup:
    if results.len == 0:
      for i in 0 ..< NumSeeds:
        results.add(runGame(Seeds[i]))
      printBalanceReport(results)

  test "no team wins more than 80% of games":
    var winCounts: array[MapRoomObjectsTeams, int]
    for r in results:
      if r.winnerTeam >= 0:
        inc winCounts[r.winnerTeam]

    for teamId in 0 ..< MapRoomObjectsTeams:
      let winRate = winCounts[teamId].float / NumSeeds.float
      check winRate <= MaxWinRate

  test "all teams gather some resources across seeds":
    for teamId in 0 ..< MapRoomObjectsTeams:
      var totalRes = 0
      for r in results:
        totalRes += r.metrics[teamId].totalResources
      check totalRes > 0

  test "all teams have surviving units across seeds":
    for teamId in 0 ..< MapRoomObjectsTeams:
      var totalAlive = 0
      for r in results:
        totalAlive += r.metrics[teamId].aliveUnits
      check totalAlive > 0

  test "territory is distributed (no team holds >50% avg)":
    for teamId in 0 ..< MapRoomObjectsTeams:
      var totalTerr = 0
      var totalAllTeams = 0
      for r in results:
        totalTerr += r.metrics[teamId].territoryTiles
        for t in 0 ..< MapRoomObjectsTeams:
          totalAllTeams += r.metrics[t].territoryTiles
      if totalAllTeams > 0:
        let share = totalTerr.float / totalAllTeams.float
        check share <= 0.50

  test "resource gathering variance is bounded":
    # No team should gather more than 5x the average
    for r in results:
      var totalRes = 0
      for teamId in 0 ..< MapRoomObjectsTeams:
        totalRes += r.metrics[teamId].totalResources
      let avg = totalRes.float / MapRoomObjectsTeams.float
      if avg > 0:
        for teamId in 0 ..< MapRoomObjectsTeams:
          let ratio = r.metrics[teamId].totalResources.float / avg
          check ratio < 5.0
