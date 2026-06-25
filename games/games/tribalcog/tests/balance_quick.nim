## Quick balance smoke test - runs in <30 seconds
## For thorough balance testing, use behavior_balance.nim

import std/[unittest, math]
import test_common

const
  NumSeeds = 3          # Reduced from 10
  StepsPerGame = 100    # Reduced from 500
  MaxWinRate = 0.90     # Relaxed from 0.80 (fewer samples = more variance)
  Seeds = [42, 137, 256]

type
  GameResult = object
    seed: int
    winnerTeam: int
    aliveUnits: array[MapRoomObjectsTeams, int]

proc computeScore(env: Environment, teamId: int): int =
  let stockpile = env.teamStockpiles[teamId]
  result = stockpile.counts[ResourceFood] +
           stockpile.counts[ResourceWood] +
           stockpile.counts[ResourceStone] +
           stockpile.counts[ResourceGold] +
           countAliveUnits(env, teamId) * 10

proc runQuickGame(seed: int): GameResult =
  var config = defaultEnvironmentConfig()
  config.maxSteps = StepsPerGame
  config.victoryCondition = VictoryNone
  let env = newEnvironment(config, seed)

  # NO AI - just run steps with no-op actions for speed
  # This tests that the game engine runs without crashing
  var noopActions: array[MapAgents, uint16]
  for i in 0 ..< MapAgents:
    noopActions[i] = 0  # ActionNone

  for step in 0 ..< StepsPerGame:
    env.step(addr noopActions)
    if env.shouldReset:
      break

  result.seed = seed
  for teamId in 0 ..< MapRoomObjectsTeams:
    result.aliveUnits[teamId] = countAliveUnits(env, teamId)

  var bestScore = -1
  for teamId in 0 ..< MapRoomObjectsTeams:
    let score = computeScore(env, teamId)
    if score > bestScore:
      bestScore = score
      result.winnerTeam = teamId

suite "Balance Quick - Smoke test":
  var results: seq[GameResult]

  setup:
    if results.len == 0:
      echo "Running quick balance check (3 seeds, 100 steps each)..."
      for seed in Seeds:
        results.add(runQuickGame(seed))

  test "game runs without crash":
    check results.len == NumSeeds

  test "no team dominates all games":
    var winCounts: array[MapRoomObjectsTeams, int]
    for r in results:
      if r.winnerTeam >= 0:
        inc winCounts[r.winnerTeam]
    for teamId in 0 ..< MapRoomObjectsTeams:
      let winRate = winCounts[teamId].float / NumSeeds.float
      check winRate <= MaxWinRate

  test "all teams have some units alive":
    for teamId in 0 ..< MapRoomObjectsTeams:
      var totalAlive = 0
      for r in results:
        totalAlive += r.aliveUnits[teamId]
      # At least 1 unit alive across all seeds combined
      check totalAlive > 0
