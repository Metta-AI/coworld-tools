## Game balance metric collection and reporting.

import
  std/[json, math, os, strformat, strutils, times],
  envconfig, environment, items, types

const
  DefaultSampleInterval = 50
  DefaultOutputDir = "./scorecards/"

type
  ResourceSample* = object
    ## Resource snapshot at a point in time.
    step*: int
    food*: int
    wood*: int
    gold*: int
    stone*: int

  UnitComposition* = object
    ## Unit counts by category at a point in time.
    step*: int
    villagers*: int
    infantry*: int      ## Infantry units.
    archers*: int       ## Archer units.
    cavalry*: int       ## Cavalry units.
    siege*: int         ## Siege units.
    monks*: int
    unique*: int        ## Unique units.
    total*: int

  TechProgress* = object
    ## Technology research state at a point in time.
    step*: int
    blacksmithLevels*: int    ## Sum of all blacksmith upgrade levels.
    universityTechs*: int     ## Count of researched university techs.
    castleTechs*: int         ## Count of researched castle techs.
    unitUpgrades*: int        ## Count of researched unit upgrades.

  SpendingRecord* = object
    ## Cumulative spending tracking.
    economySpend*: int        ## Economy spending.
    militarySpend*: int       ## Military spending.

  TeamScorecard* = object
    ## Complete metrics for one team across the match.
    teamId*: int

    # Time-series data.
    resourceCurve*: seq[ResourceSample]
    unitTimeline*: seq[UnitComposition]
    techTimeline*: seq[TechProgress]

    # Final state.
    finalResources*: ResourceSample
    finalUnits*: UnitComposition
    finalTech*: TechProgress

    # Match outcome.
    won*: bool
    finalScore*: int          ## Composite score.
    aliveUnits*: int
    deadUnits*: int
    buildingsBuilt*: int
    territoryTiles*: int

    # Efficiency metrics.
    idleVillagerPct*: float32      ## Percentage of villagers that were idle.
    economyMilitaryRatio*: float32 ## Economy spend over total spend.

    # Spending data.
    spending*: SpendingRecord

  BalanceScorecard* = object
    ## Complete match scorecard.
    matchId*: string
    seed*: int
    startTime*: DateTime
    endTime*: DateTime
    totalSteps*: int
    victoryWinner*: int
    victoryCondition*: string

    teams*: array[MapRoomObjectsTeams, TeamScorecard]

    # Aggregate balance metrics.
    winDistribution*: array[MapRoomObjectsTeams, int] ## Cumulative wins.
    resourceParity*: float32      ## Resource-balance score.
    militaryBalance*: float32     ## Military-balance score.
    techParity*: float32          ## Technology-balance score.

  ScorecardCollector* = object
    ## Stateful collector that samples during gameplay.
    enabled*: bool
    sampleInterval*: int
    outputDir*: string
    currentScorecard*: BalanceScorecard
    lastSampleStep*: int
    initialized*: bool

    # Spending snapshots between samples.
    lastTeamResources*: array[MapRoomObjectsTeams, TeamStockpile]

    # Villager activity totals.
    villagerIdleSteps*: array[MapAgents, int]
    villagerTotalSteps*: array[MapAgents, int]

var collector*: ScorecardCollector

proc initCollector*() =
  ## Initialize scorecard collector from environment variables.
  collector.enabled = parseEnvBool("TV_SCORECARD_ENABLED", false)
  collector.sampleInterval =
    parseEnvInt("TV_SCORECARD_INTERVAL", DefaultSampleInterval)
  collector.outputDir = getEnv("TV_SCORECARD_DIR", DefaultOutputDir)

  if collector.enabled:
    createDir(collector.outputDir)

  collector.initialized = true

proc ensureInit() =
  ## Initialize the scorecard collector on first use.
  if not collector.initialized:
    initCollector()

proc startMatch*(env: Environment, seed: int) =
  ## Call at match start to initialize scorecard collection.
  ensureInit()
  if not collector.enabled:
    return

  collector.currentScorecard = BalanceScorecard()
  collector.currentScorecard.seed = seed
  collector.currentScorecard.startTime = now()
  collector.currentScorecard.matchId =
    $seed & "_" & now().format("yyyyMMddHHmmss")
  collector.lastSampleStep = -1

  # Initialize team scorecards.
  for teamId in 0 ..< MapRoomObjectsTeams:
    collector.currentScorecard.teams[teamId].teamId = teamId
    collector.currentScorecard.teams[teamId].resourceCurve = @[]
    collector.currentScorecard.teams[teamId].unitTimeline = @[]
    collector.currentScorecard.teams[teamId].techTimeline = @[]

  # Initialize resource tracking.
  for teamId in 0 ..< MapRoomObjectsTeams:
    for res in StockpileResource:
      collector.lastTeamResources[teamId].counts[res] =
        env.teamStockpiles[teamId].counts[res]

  # Initialize villager tracking.
  for i in 0 ..< MapAgents:
    collector.villagerIdleSteps[i] = 0
    collector.villagerTotalSteps[i] = 0

proc classifyUnit(unitClass: AgentUnitClass): string =
  ## Classify unit into category for composition tracking.
  case unitClass
  of UnitVillager: "villager"
  of UnitManAtArms, UnitLongSwordsman, UnitChampion, UnitWoadRaider,
     UnitTeutonicKnight, UnitHuskarl: "infantry"
  of UnitArcher, UnitCrossbowman, UnitArbalester, UnitLongbowman, UnitJanissary,
     UnitSkirmisher, UnitEliteSkirmisher, UnitHandCannoneer: "archers"
  of UnitScout, UnitKnight, UnitLightCavalry, UnitHussar, UnitCataphract, UnitMameluke,
     UnitCavalier, UnitPaladin, UnitCamel, UnitHeavyCamel, UnitImperialCamel,
     UnitCavalryArcher, UnitHeavyCavalryArcher: "cavalry"
  of UnitBatteringRam, UnitMangonel, UnitTrebuchet, UnitScorpion: "siege"
  of UnitMonk: "monks"
  of UnitSamurai: "unique"
  of UnitGoblin, UnitBoat, UnitTradeCog, UnitKing, UnitGalley, UnitFireShip,
     UnitFishingShip, UnitTransportShip, UnitDemoShip, UnitCannonGalleon: "other"

proc sampleResources(env: Environment, teamId: int, step: int): ResourceSample =
  ## Sample one team's current stockpile resources.
  result.step = step
  result.food = env.teamStockpiles[teamId].counts[ResourceFood]
  result.wood = env.teamStockpiles[teamId].counts[ResourceWood]
  result.gold = env.teamStockpiles[teamId].counts[ResourceGold]
  result.stone = env.teamStockpiles[teamId].counts[ResourceStone]

proc sampleUnitComposition(env: Environment, teamId: int, step: int): UnitComposition =
  ## Sample one team's current unit composition.
  result.step = step

  for agent in env.liveAgents:
    if agent.getTeamId() != teamId:
      continue
    if not isAgentAlive(env, agent):
      continue  # Dead or not on grid

    inc result.total
    case classifyUnit(agent.unitClass)
    of "villager": inc result.villagers
    of "infantry": inc result.infantry
    of "archers": inc result.archers
    of "cavalry": inc result.cavalry
    of "siege": inc result.siege
    of "monks": inc result.monks
    of "unique": inc result.unique
    else: discard

proc sampleTechProgress(env: Environment, teamId: int, step: int): TechProgress =
  ## Sample one team's researched technology progress.
  result.step = step

  # Sum blacksmith levels.
  for upgradeType in BlacksmithUpgradeType:
    result.blacksmithLevels +=
      env.teamBlacksmithUpgrades[teamId].levels[upgradeType]

  # Count university techs.
  for techType in UniversityTechType:
    if env.teamUniversityTechs[teamId].researched[techType]:
      inc result.universityTechs

  # Count castle techs.
  for techType in CastleTechType:
    if env.teamCastleTechs[teamId].researched[techType]:
      inc result.castleTechs

  # Count unit upgrades.
  for upgradeType in UnitUpgradeType:
    if env.teamUnitUpgrades[teamId].researched[upgradeType]:
      inc result.unitUpgrades

proc countBuildings(env: Environment, teamId: int): int =
  ## Count standing buildings owned by a team.
  for kind in ThingKind:
    if kind in {Altar, TownCenter, House, Barracks, ArcheryRange, Stable,
                Blacksmith, Market, Monastery, University, Castle, Wonder,
                SiegeWorkshop, MangonelWorkshop, TrebuchetWorkshop,
                Dock, Outpost, GuardTower, Wall, Door, Mill, Granary,
                LumberCamp, Quarry, MiningCamp, WeavingLoom, ClayOven,
                Lantern, Temple}:
      for thing in env.thingsByKind[kind]:
        if not thing.isNil and thing.teamId == teamId and thing.hp > 0:
          inc result

proc updateSpending(env: Environment, teamId: int) =
  ## Track resource spending between samples.
  # This uses resource decreases as a simplified spending heuristic.
  var totalDelta = 0

  for res in [ResourceFood, ResourceWood, ResourceGold, ResourceStone]:
    let current = env.teamStockpiles[teamId].counts[res]
    let previous = collector.lastTeamResources[teamId].counts[res]
    let delta = previous - current
    if delta > 0:
      totalDelta += delta
    collector.lastTeamResources[teamId].counts[res] = current

  # Split the heuristic evenly until event-level spending hooks exist.
  collector.currentScorecard.teams[teamId].spending.economySpend += totalDelta div 2
  collector.currentScorecard.teams[teamId].spending.militarySpend += totalDelta div 2

proc updateVillagerIdleness(env: Environment) =
  ## Track villager activity for idle percentage calculation.
  ## Villagers with inventory items are treated as active.
  for agent in env.liveAgents:
    if env.terminated[agent.agentId] != 0.0:
      continue
    if agent.unitClass != UnitVillager:
      continue

    let agentId = agent.agentId
    inc collector.villagerTotalSteps[agentId]

    # Villagers without inventory items are treated as idle.
    if agent.inventory.len == 0:
      inc collector.villagerIdleSteps[agentId]

proc maybeSample*(env: Environment) =
  ## Called each step; samples if interval matches.
  ensureInit()
  if not collector.enabled:
    return

  let step = env.currentStep

  # Update villager tracking every step.
  updateVillagerIdleness(env)

  # Sample at intervals.
  if step - collector.lastSampleStep >= collector.sampleInterval:
    collector.lastSampleStep = step

    for teamId in 0 ..< MapRoomObjectsTeams:
      collector.currentScorecard.teams[teamId].resourceCurve.add(
        sampleResources(env, teamId, step))
      collector.currentScorecard.teams[teamId].unitTimeline.add(
        sampleUnitComposition(env, teamId, step))
      collector.currentScorecard.teams[teamId].techTimeline.add(
        sampleTechProgress(env, teamId, step))

      updateSpending(env, teamId)

proc computeFinalMetrics(env: Environment) =
  ## Compute final match metrics.
  let step = env.currentStep

  for teamId in 0 ..< MapRoomObjectsTeams:
    var team = addr collector.currentScorecard.teams[teamId]

    # Final state samples.
    team.finalResources = sampleResources(env, teamId, step)
    team.finalUnits = sampleUnitComposition(env, teamId, step)
    team.finalTech = sampleTechProgress(env, teamId, step)

    # Outcome totals.
    team.won = (env.victoryWinner == teamId)
    team.aliveUnits = team.finalUnits.total
    team.buildingsBuilt = countBuildings(env, teamId)

    # Count dead units.
    let startIdx = teamId * MapAgentsPerTeam
    let endIdx = min(startIdx + MapAgentsPerTeam, env.agents.len)
    for i in startIdx ..< endIdx:
      if i < env.agents.len and not env.agents[i].isNil:
        if env.terminated[i] != 0.0:
          inc team.deadUnits

    # Territory totals.
    let territory = scoreTerritory(env)
    team.territoryTiles = territory.teamTiles[teamId]

    # Composite score.
    team.finalScore =
      team.finalResources.food + team.finalResources.wood +
      team.finalResources.gold + team.finalResources.stone +
      team.territoryTiles + team.aliveUnits * 10

    # Idle villager percentage.
    var totalVillagerSteps = 0
    var totalIdleSteps = 0
    for i in startIdx ..< endIdx:
      if collector.villagerTotalSteps[i] > 0:
        totalVillagerSteps += collector.villagerTotalSteps[i]
        totalIdleSteps += collector.villagerIdleSteps[i]

    if totalVillagerSteps > 0:
      team.idleVillagerPct =
        float32(totalIdleSteps) / float32(totalVillagerSteps) * 100.0

    # Economy and military ratio.
    let totalSpend = team.spending.economySpend + team.spending.militarySpend
    if totalSpend > 0:
      team.economyMilitaryRatio =
        float32(team.spending.economySpend) / float32(totalSpend)

proc computeBalanceMetrics() =
  ## Compute aggregate balance metrics across all teams.
  var sc = addr collector.currentScorecard

  # Resource parity.
  var resources: array[MapRoomObjectsTeams, float64]
  var totalRes = 0.0
  for teamId in 0 ..< MapRoomObjectsTeams:
    let r = sc.teams[teamId].finalResources
    resources[teamId] = float64(r.food + r.wood + r.gold + r.stone)
    totalRes += resources[teamId]

  if totalRes > 0:
    # Simplified Gini: mean absolute difference / (2 * mean)
    var sumDiff = 0.0
    for i in 0 ..< MapRoomObjectsTeams:
      for j in 0 ..< MapRoomObjectsTeams:
        sumDiff += abs(resources[i] - resources[j])
    let meanRes = totalRes / float64(MapRoomObjectsTeams)
    sc.resourceParity = float32(
      1.0 - sumDiff /
      (
        2.0 *
        float64(MapRoomObjectsTeams * MapRoomObjectsTeams) *
        meanRes
      )
    )

  # Military balance.
  var military: array[MapRoomObjectsTeams, float64]
  var totalMil = 0.0
  for teamId in 0 ..< MapRoomObjectsTeams:
    let u = sc.teams[teamId].finalUnits
    military[teamId] =
      float64(
        u.infantry + u.archers + u.cavalry +
        u.siege + u.monks + u.unique
      )
    totalMil += military[teamId]

  if totalMil > 0:
    let meanMil = totalMil / float64(MapRoomObjectsTeams)
    var variance = 0.0
    for teamId in 0 ..< MapRoomObjectsTeams:
      variance += (military[teamId] - meanMil) * (military[teamId] - meanMil)
    variance /= float64(MapRoomObjectsTeams)
    let stdDev = sqrt(variance)
    sc.militaryBalance = float32(1.0 - min(1.0, stdDev / meanMil))

  # Technology parity.
  var techs: array[MapRoomObjectsTeams, float64]
  var totalTech = 0.0
  for teamId in 0 ..< MapRoomObjectsTeams:
    let t = sc.teams[teamId].finalTech
    techs[teamId] =
      float64(
        t.blacksmithLevels + t.universityTechs * 2 +
        t.castleTechs * 3 + t.unitUpgrades * 2
      )
    totalTech += techs[teamId]

  if totalTech > 0:
    let meanTech = totalTech / float64(MapRoomObjectsTeams)
    var variance = 0.0
    for teamId in 0 ..< MapRoomObjectsTeams:
      variance += (techs[teamId] - meanTech) * (techs[teamId] - meanTech)
    variance /= float64(MapRoomObjectsTeams)
    let stdDev = sqrt(variance)
    sc.techParity = float32(1.0 - min(1.0, stdDev / max(1.0, meanTech)))

proc resourceSampleToJson(sample: ResourceSample): JsonNode =
  ## Convert one resource sample into JSON.
  %*{
    "step": sample.step,
    "food": sample.food,
    "wood": sample.wood,
    "gold": sample.gold,
    "stone": sample.stone
  }

proc unitCompositionToJson(composition: UnitComposition): JsonNode =
  ## Convert one unit composition sample into JSON.
  %*{
    "step": composition.step,
    "villagers": composition.villagers,
    "infantry": composition.infantry,
    "archers": composition.archers,
    "cavalry": composition.cavalry,
    "siege": composition.siege,
    "monks": composition.monks,
    "unique": composition.unique,
    "total": composition.total
  }

proc techProgressToJson(progress: TechProgress): JsonNode =
  ## Convert one tech-progress sample into JSON.
  %*{
    "step": progress.step,
    "blacksmith_levels": progress.blacksmithLevels,
    "university_techs": progress.universityTechs,
    "castle_techs": progress.castleTechs,
    "unit_upgrades": progress.unitUpgrades
  }

proc teamScorecardToJson(teamScorecard: TeamScorecard): JsonNode =
  ## Convert one team scorecard into JSON.
  var resourceCurve = newJArray()
  for sample in teamScorecard.resourceCurve:
    resourceCurve.add(resourceSampleToJson(sample))

  var unitTimeline = newJArray()
  for composition in teamScorecard.unitTimeline:
    unitTimeline.add(unitCompositionToJson(composition))

  var techTimeline = newJArray()
  for progress in teamScorecard.techTimeline:
    techTimeline.add(techProgressToJson(progress))

  %*{
    "team_id": teamScorecard.teamId,
    "won": teamScorecard.won,
    "final_score": teamScorecard.finalScore,
    "alive_units": teamScorecard.aliveUnits,
    "dead_units": teamScorecard.deadUnits,
    "buildings_built": teamScorecard.buildingsBuilt,
    "territory_tiles": teamScorecard.territoryTiles,
    "idle_villager_pct": teamScorecard.idleVillagerPct,
    "economy_military_ratio": teamScorecard.economyMilitaryRatio,
    "spending": {
      "economy": teamScorecard.spending.economySpend,
      "military": teamScorecard.spending.militarySpend
    },
    "final_resources": resourceSampleToJson(teamScorecard.finalResources),
    "final_units": unitCompositionToJson(teamScorecard.finalUnits),
    "final_tech": techProgressToJson(teamScorecard.finalTech),
    "resource_curve": resourceCurve,
    "unit_timeline": unitTimeline,
    "tech_timeline": techTimeline
  }

proc scorecardToJson*(sc: BalanceScorecard): JsonNode =
  ## Convert the complete balance scorecard into JSON.
  var teams = newJArray()
  for teamId in 0 ..< MapRoomObjectsTeams:
    teams.add(teamScorecardToJson(sc.teams[teamId]))

  var winDist = newJArray()
  for teamId in 0 ..< MapRoomObjectsTeams:
    winDist.add(%sc.winDistribution[teamId])

  %*{
    "match_id": sc.matchId,
    "seed": sc.seed,
    "start_time": $sc.startTime,
    "end_time": $sc.endTime,
    "total_steps": sc.totalSteps,
    "victory_winner": sc.victoryWinner,
    "victory_condition": sc.victoryCondition,
    "balance_metrics": {
      "resource_parity": sc.resourceParity,
      "military_balance": sc.militaryBalance,
      "tech_parity": sc.techParity
    },
    "win_distribution": winDist,
    "teams": teams
  }

proc generateSummary*(sc: BalanceScorecard): string =
  ## Generate human-readable balance summary.
  var lines: seq[string] = @[]

  lines.add("=" .repeat(80))
  lines.add("GAME BALANCE SCORECARD")
  lines.add("=" .repeat(80))
  lines.add(&"Match: {sc.matchId} | Seed: {sc.seed}")
  lines.add(&"Duration: {sc.totalSteps} steps")
  lines.add(
    &"Winner: Team {sc.victoryWinner}" &
    (
      if sc.victoryWinner >= 0:
        " (" & sc.victoryCondition & ")"
      else:
        " (no winner)"
    )
  )
  lines.add("-" .repeat(80))

  # Balance metrics.
  lines.add("")
  lines.add("BALANCE METRICS:")
  lines.add(
    &"  Resource Parity:  {sc.resourceParity * 100:5.1f}% " &
    "(100% = perfect equality)"
  )
  lines.add(
    &"  Military Balance: {sc.militaryBalance * 100:5.1f}% " &
    "(100% = equal strength)"
  )
  lines.add(
    &"  Tech Parity:      {sc.techParity * 100:5.1f}% " &
    "(100% = equal progress)"
  )

  # Per-team summary.
  lines.add("")
  lines.add("PER-TEAM SUMMARY:")
  lines.add("  Team  Score  Alive  Dead  Buildings  Territory  Idle%  Econ/Mil  Won")
  lines.add("  " & "-" .repeat(72))

  for teamId in 0 ..< MapRoomObjectsTeams:
    let t = sc.teams[teamId]
    let wonStr = if t.won: "YES" else: "   "
    lines.add(
      &"  {teamId:>4}  {t.finalScore:>5}  {t.aliveUnits:>5} " &
      &" {t.deadUnits:>4}  {t.buildingsBuilt:>9}  " &
      &"{t.territoryTiles:>9}  {t.idleVillagerPct:>5.1f}  " &
      &"{t.economyMilitaryRatio:>7.2f}  {wonStr}"
    )

  # Final resources.
  lines.add("")
  lines.add("FINAL RESOURCES:")
  lines.add("  Team   Food   Wood   Gold  Stone   Total")
  lines.add("  " & "-" .repeat(44))

  for teamId in 0 ..< MapRoomObjectsTeams:
    let r = sc.teams[teamId].finalResources
    let total = r.food + r.wood + r.gold + r.stone
    lines.add(&"  {teamId:>4}  {r.food:>5}  {r.wood:>5}  {r.gold:>5}  {r.stone:>5}  {total:>6}")

  # Final unit composition.
  lines.add("")
  lines.add("FINAL UNIT COMPOSITION:")
  lines.add("  Team  Vill  Inf  Arch  Cav  Siege  Monk  Uniq  Total")
  lines.add("  " & "-" .repeat(56))

  for teamId in 0 ..< MapRoomObjectsTeams:
    let u = sc.teams[teamId].finalUnits
    lines.add(
      &"  {teamId:>4}  {u.villagers:>4}  {u.infantry:>3}  " &
      &"{u.archers:>4}  {u.cavalry:>3}  {u.siege:>5}  " &
      &"{u.monks:>4}  {u.unique:>4}  {u.total:>5}"
    )

  # Technology progress.
  lines.add("")
  lines.add("TECHNOLOGY PROGRESS:")
  lines.add("  Team  Blacksmith  University  Castle  UnitUpg")
  lines.add("  " & "-" .repeat(48))

  for teamId in 0 ..< MapRoomObjectsTeams:
    let t = sc.teams[teamId].finalTech
    lines.add(
      &"  {teamId:>4}  {t.blacksmithLevels:>10}  " &
      &"{t.universityTechs:>10}  {t.castleTechs:>6}  " &
      &"{t.unitUpgrades:>7}"
    )

  lines.add("=" .repeat(80))

  lines.join("\n")

proc endMatch*(env: Environment) =
  ## Call at match end to finalize and write scorecard.
  ensureInit()
  if not collector.enabled:
    return

  collector.currentScorecard.endTime = now()
  collector.currentScorecard.totalSteps = env.currentStep
  collector.currentScorecard.victoryWinner = env.victoryWinner
  collector.currentScorecard.victoryCondition = $env.config.victoryCondition

  # Compute final metrics.
  computeFinalMetrics(env)
  computeBalanceMetrics()

  # Update win distribution.
  if env.victoryWinner >= 0 and env.victoryWinner < MapRoomObjectsTeams:
    inc collector.currentScorecard.winDistribution[env.victoryWinner]

  # Write JSON.
  let jsonFilename =
    collector.outputDir /
    &"scorecard_{collector.currentScorecard.matchId}.json"
  writeFile(jsonFilename, $scorecardToJson(collector.currentScorecard))

  # Write summary.
  let summaryFilename =
    collector.outputDir /
    &"scorecard_{collector.currentScorecard.matchId}.txt"
  writeFile(summaryFilename, generateSummary(collector.currentScorecard))
