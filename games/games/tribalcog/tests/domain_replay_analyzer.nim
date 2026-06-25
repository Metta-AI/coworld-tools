## Domain checks for replay analyzer scoring and feedback helpers.

import
  replay_analyzer, common_types

proc checkActionProfile() =
  ## Verify action-profile normalization behavior.
  echo "Testing replay analyzer action profile"

  var strategy = TeamStrategy(teamId: 0, agentCount: 1)
  strategy.actionDist.counts[ActionAttack] = 50
  strategy.actionDist.counts[ActionUse] = 30
  strategy.actionDist.counts[ActionBuild] = 20
  strategy.actionDist.total = 100
  let profile = actionProfile(strategy)
  doAssert abs(profile[ActionAttack] - 0.5) < 0.001
  doAssert abs(profile[ActionUse] - 0.3) < 0.001
  doAssert abs(profile[ActionBuild] - 0.2) < 0.001

  strategy = TeamStrategy(teamId: 0, agentCount: 1)
  strategy.actionDist.total = 0
  let zeroProfile = actionProfile(strategy)
  for verb in 0 ..< ActionVerbCount:
    doAssert zeroProfile[verb] == 0.0

  strategy = TeamStrategy(teamId: 0, agentCount: 1)
  strategy.actionDist.counts[0] = 10
  strategy.actionDist.counts[1] = 20
  strategy.actionDist.counts[ActionAttack] = 30
  strategy.actionDist.counts[ActionUse] = 40
  strategy.actionDist.total = 100
  let summedProfile = actionProfile(strategy)
  var total: float32 = 0.0
  for verb in 0 ..< ActionVerbCount:
    total += summedProfile[verb]
  doAssert abs(total - 1.0) < 0.01

proc checkCombatEfficiency() =
  ## Verify combat-efficiency scoring behavior.
  echo "Testing replay analyzer combat efficiency"

  var strategy = TeamStrategy(teamId: 0)
  strategy.combat.attacks = 100
  strategy.combat.hits = 75
  doAssert abs(combatEfficiency(strategy) - 0.75) < 0.001

  strategy = TeamStrategy(teamId: 0)
  strategy.combat.attacks = 0
  doAssert combatEfficiency(strategy) == 0.0

  strategy = TeamStrategy(teamId: 0)
  strategy.combat.attacks = 50
  strategy.combat.hits = 50
  doAssert abs(combatEfficiency(strategy) - 1.0) < 0.001

proc checkEconomyScore() =
  ## Verify economy-score ratios and fallbacks.
  echo "Testing replay analyzer economy score"

  var strategy = TeamStrategy(teamId: 0)
  strategy.resources.gatherActions = 80
  strategy.resources.buildActions = 20
  doAssert abs(economyScore(strategy) - 0.8) < 0.001

  strategy = TeamStrategy(teamId: 0)
  doAssert economyScore(strategy) == 0.0

  strategy = TeamStrategy(teamId: 0)
  strategy.resources.gatherActions = 100
  doAssert abs(economyScore(strategy) - 1.0) < 0.001

  strategy = TeamStrategy(teamId: 0)
  strategy.resources.buildActions = 100
  doAssert economyScore(strategy) == 0.0

proc checkStrategyScore() =
  ## Verify composite strategy scoring and winner bonuses.
  echo "Testing replay analyzer strategy score"

  var strategy = TeamStrategy(teamId: 0, agentCount: 1)
  strategy.finalReward = 10.0
  strategy.won = true
  strategy.combat.attacks = 100
  strategy.combat.hits = 100
  let clampedScore = strategyScore(strategy)
  doAssert clampedScore >= 0.0
  doAssert clampedScore <= 1.0

  var winnerStrategy = TeamStrategy(teamId: 0, agentCount: 1)
  winnerStrategy.finalReward = 0.5
  winnerStrategy.won = true

  var loserStrategy = TeamStrategy(teamId: 1, agentCount: 1)
  loserStrategy.finalReward = 0.5
  loserStrategy.won = false
  doAssert strategyScore(winnerStrategy) > strategyScore(loserStrategy)

  strategy = TeamStrategy(teamId: 0, agentCount: 1)
  doAssert strategyScore(strategy) == 0.0

  var noCombat = TeamStrategy(teamId: 0, agentCount: 1)
  noCombat.finalReward = 0.5
  var withCombat = TeamStrategy(teamId: 0, agentCount: 1)
  withCombat.finalReward = 0.5
  withCombat.combat.attacks = 100
  withCombat.combat.hits = 80
  doAssert strategyScore(withCombat) > strategyScore(noCombat)

proc checkDominantActionVerb() =
  ## Verify dominant action extraction from sequences.
  echo "Testing replay analyzer dominant action verb"

  let attackSeq = ActionSequence(
    verbs: @[ActionAttack, ActionAttack, ActionAttack, ActionUse, ActionBuild],
    teamReward: 1.0
  )
  doAssert dominantActionVerb(attackSeq) == ActionAttack

  let buildSeq = ActionSequence(verbs: @[ActionBuild], teamReward: 0.5)
  doAssert dominantActionVerb(buildSeq) == ActionBuild

  let emptySeq = ActionSequence(verbs: @[], teamReward: 0.0)
  doAssert dominantActionVerb(emptySeq) == 0

proc checkReplayFeedback() =
  ## Verify replay feedback updates role fitness as expected.
  echo "Testing replay analyzer feedback"

  var catalog = initRoleCatalog()
  let opt = OptionDef(name: "TestBehavior")
  discard catalog.addBehavior(opt, BehaviorCustom)

  var role = newRoleDef(catalog, "TestRole", @[], "test")
  role.games = 5
  role.fitness = 0.3
  discard registerRole(catalog, role)

  var analysis = ReplayAnalysis()
  var teamStrategy = TeamStrategy(
    teamId: 0,
    agentCount: 2,
    finalReward: 1.0,
    won: true
  )
  teamStrategy.combat.attacks = 50
  teamStrategy.combat.hits = 30
  analysis.teams.add(teamStrategy)
  analysis.winningTeamId = 0

  let fitnessBefore = catalog.roles[0].fitness
  applyReplayFeedback(catalog, analysis)
  doAssert catalog.roles[0].fitness != fitnessBefore

  var emptyCatalog = initRoleCatalog()
  var emptyRole = newRoleDef(emptyCatalog, "TestRole", @[], "test")
  emptyRole.games = 5
  emptyRole.fitness = 0.5
  discard registerRole(emptyCatalog, emptyRole)

  let emptyAnalysis = ReplayAnalysis()
  let emptyFitnessBefore = emptyCatalog.roles[0].fitness
  applyReplayFeedback(emptyCatalog, emptyAnalysis)
  doAssert emptyCatalog.roles[0].fitness == emptyFitnessBefore

proc checkWinnerBoost() =
  ## Verify winner boosts only affect sufficiently fit roles.
  echo "Testing replay analyzer winner boost"

  var catalog = initRoleCatalog()

  var lowRole = newRoleDef(catalog, "LowRole", @[], "test")
  lowRole.games = 5
  lowRole.fitness = 0.2
  discard registerRole(catalog, lowRole)

  var highRole = newRoleDef(catalog, "HighRole", @[], "test")
  highRole.games = 5
  highRole.fitness = 0.6
  discard registerRole(catalog, highRole)

  var analysis = ReplayAnalysis(winningTeamId: 0)
  var teamStrategy = TeamStrategy(
    teamId: 0,
    agentCount: 1,
    finalReward: 1.0,
    won: true
  )
  teamStrategy.combat.attacks = 20
  teamStrategy.combat.hits = 15
  analysis.teams.add(teamStrategy)

  let
    lowBefore = catalog.roles[0].fitness
    highBefore = catalog.roles[1].fitness
  applyWinnerBoost(catalog, analysis)
  doAssert catalog.roles[0].fitness == lowBefore
  doAssert catalog.roles[1].fitness != highBefore

checkActionProfile()
checkCombatEfficiency()
checkEconomyScore()
checkStrategyScore()
checkDominantActionVerb()
checkReplayFeedback()
checkWinnerBoost()

echo "Replay analyzer domain checks passed"
