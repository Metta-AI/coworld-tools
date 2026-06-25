## Balance scorecard checks.

import
  std/[json, os, strutils],
  agent_control, balance_scorecard, environment, types

const
  BalanceSeed = 42
  BalanceSteps = 100

proc clearScorecardEnv() =
  ## Clear scorecard-related environment variables.
  delEnv("TV_SCORECARD_ENABLED")
  delEnv("TV_SCORECARD_INTERVAL")
  delEnv("TV_SCORECARD_DIR")

proc resetCollectorState() =
  ## Reset the global scorecard collector state.
  collector = ScorecardCollector()

proc newBalanceEnv(maxSteps: int = BalanceSteps): Environment =
  ## Create a test environment for balance scorecard checks.
  var config = defaultEnvironmentConfig()
  config.maxSteps = maxSteps
  newEnvironment(config, BalanceSeed)

proc runSampledMatch(env: Environment, steps: int) =
  ## Advance the environment and sample the scorecard each step.
  initGlobalController(BuiltinAI, seed = BalanceSeed)
  for _ in 0 ..< steps:
    var actions = getActions(env)
    env.step(addr actions)
    maybeSample(env)

proc checkCollectorInit() =
  ## Verify collector initialization reads environment variables.
  echo "Testing scorecard collector initialization"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  putEnv("TV_SCORECARD_INTERVAL", "10")
  putEnv("TV_SCORECARD_DIR", "/tmp/test_scorecards/")
  initCollector()

  doAssert collector.enabled
  doAssert collector.sampleInterval == 10
  doAssert collector.outputDir == "/tmp/test_scorecards/"

proc checkCollectorDisabledByDefault() =
  ## Verify the collector is disabled by default.
  echo "Testing scorecard disabled by default"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  initCollector()
  doAssert not collector.enabled

proc checkStartMatchInit() =
  ## Verify match start initializes the scorecard state.
  echo "Testing scorecard startMatch initialization"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  initCollector()

  let env = newBalanceEnv()
  startMatch(env, BalanceSeed)

  doAssert collector.currentScorecard.seed == BalanceSeed
  doAssert collector.currentScorecard.matchId.len > 0
  for teamId in 0 ..< MapRoomObjectsTeams:
    doAssert collector.currentScorecard.teams[teamId].teamId == teamId

proc checkMaybeSampleCollectsData() =
  ## Verify sampling collects scorecard data at the configured interval.
  echo "Testing scorecard interval sampling"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  putEnv("TV_SCORECARD_INTERVAL", "10")
  initCollector()

  let env = newBalanceEnv()
  startMatch(env, BalanceSeed)
  runSampledMatch(env, 25)

  doAssert collector.currentScorecard.teams[0].resourceCurve.len >= 2

proc checkResourceSamples() =
  ## Verify final resource samples are captured.
  echo "Testing scorecard resource sampling"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  initCollector()

  let env = newBalanceEnv()
  startMatch(env, BalanceSeed)
  runSampledMatch(env, 50)
  endMatch(env)

  for teamId in 0 ..< MapRoomObjectsTeams:
    let resources = collector.currentScorecard.teams[teamId].finalResources
    doAssert resources.food >= 0
    doAssert resources.wood >= 0
    doAssert resources.gold >= 0
    doAssert resources.stone >= 0

proc checkUnitComposition() =
  ## Verify unit composition sampling captures villagers.
  echo "Testing scorecard unit composition"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  initCollector()

  let env = newBalanceEnv()
  startMatch(env, BalanceSeed)
  runSampledMatch(env, 20)
  endMatch(env)

  var totalVillagers = 0
  for teamId in 0 ..< MapRoomObjectsTeams:
    totalVillagers +=
      collector.currentScorecard.teams[teamId].finalUnits.villagers
  doAssert totalVillagers > 0

proc checkTechProgress() =
  ## Verify tech progress starts at zero.
  echo "Testing scorecard tech progress"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  initCollector()

  let env = newBalanceEnv()
  startMatch(env, BalanceSeed)

  let initialTech = collector.currentScorecard.teams[0].finalTech
  doAssert initialTech.blacksmithLevels == 0
  doAssert initialTech.universityTechs == 0
  doAssert initialTech.castleTechs == 0

proc checkScorecardToJson() =
  ## Verify JSON output has the expected shape.
  echo "Testing scorecard JSON output"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  initCollector()

  let env = newBalanceEnv()
  startMatch(env, BalanceSeed)
  endMatch(env)

  let jsonNode = scorecardToJson(collector.currentScorecard)
  doAssert jsonNode.hasKey("match_id")
  doAssert jsonNode.hasKey("seed")
  doAssert jsonNode.hasKey("teams")
  doAssert jsonNode.hasKey("balance_metrics")
  doAssert jsonNode["teams"].len == MapRoomObjectsTeams

proc checkGenerateSummary() =
  ## Verify summary output contains the expected sections.
  echo "Testing scorecard summary output"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  initCollector()

  let env = newBalanceEnv()
  startMatch(env, BalanceSeed)
  endMatch(env)

  let summary = generateSummary(collector.currentScorecard)
  doAssert summary.contains("GAME BALANCE SCORECARD")
  doAssert summary.contains("BALANCE METRICS")
  doAssert summary.contains("PER-TEAM SUMMARY")
  doAssert summary.contains("FINAL RESOURCES")
  doAssert summary.contains("FINAL UNIT COMPOSITION")
  doAssert summary.contains("TECHNOLOGY PROGRESS")

proc checkBalanceMetrics() =
  ## Verify aggregate balance metrics stay within the expected range.
  echo "Testing scorecard balance metrics"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  initCollector()

  let env = newBalanceEnv(100)
  startMatch(env, BalanceSeed)
  runSampledMatch(env, 100)
  endMatch(env)

  let scorecard = collector.currentScorecard
  doAssert scorecard.resourceParity >= 0.0
  doAssert scorecard.resourceParity <= 1.0
  doAssert scorecard.militaryBalance >= 0.0
  doAssert scorecard.militaryBalance <= 1.0
  doAssert scorecard.techParity >= 0.0
  doAssert scorecard.techParity <= 1.0

proc checkIdleVillagerPct() =
  ## Verify idle villager percentages stay within valid bounds.
  echo "Testing scorecard idle villager percentage"
  defer:
    clearScorecardEnv()
    resetCollectorState()

  putEnv("TV_SCORECARD_ENABLED", "1")
  initCollector()

  let env = newBalanceEnv(50)
  startMatch(env, BalanceSeed)
  runSampledMatch(env, 50)
  endMatch(env)

  for teamId in 0 ..< MapRoomObjectsTeams:
    let idle = collector.currentScorecard.teams[teamId].idleVillagerPct
    doAssert idle >= 0.0
    doAssert idle <= 100.0

checkCollectorInit()
checkCollectorDisabledByDefault()
checkStartMatchInit()
checkMaybeSampleCollectsData()
checkResourceSamples()
checkUnitComposition()
checkTechProgress()
checkScorecardToJson()
checkGenerateSummary()
checkBalanceMetrics()
checkIdleVillagerPct()
