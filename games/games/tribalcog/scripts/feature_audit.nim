## feature_audit.nim - AoE2 Feature Coverage Audit
## Runs a multi-thousand-step episode and reports which implemented features
## actually show up in gameplay.
##
## Usage:
##   nim c -r -d:release --path:src scripts/feature_audit.nim
##
## Environment variables:
##   TV_AUDIT_STEPS  - Total steps to run (default: 3000)
##   TV_AUDIT_SEED   - Random seed (default: 42)

import std/[strutils, strformat, tables, algorithm, sets, monotimes]
import envconfig
import environment
import agent_control
import types
import items
import registry
import scripted/ai_types

const Teams = MapRoomObjectsTeams  # 8

proc main() =
  let totalSteps = parseEnvInt("TV_AUDIT_STEPS", 3000)
  let seed = parseEnvInt("TV_AUDIT_SEED", 42)

  echo "╔══════════════════════════════════════════════════════════╗"
  echo "║         AoE2 FEATURE COVERAGE AUDIT                    ║"
  echo "╚══════════════════════════════════════════════════════════╝"
  echo &"  Steps: {totalSteps}, Seed: {seed}"
  echo ""

  initGlobalController(BuiltinAI, seed = seed)
  var env = newEnvironment()

  # --- Tracking state ---
  # Per-team unit class counts (accumulated births)
  var unitsTrained: array[Teams, array[AgentUnitClass, int]]
  # Per-team building counts at end
  # Per-team combat deaths
  var teamDeaths: array[Teams, int]
  var teamKills: array[Teams, int]  # approximated from deaths

  # Track initial state for delta
  var prevTerminated: array[MapAgents, float32]
  var prevUnitClass: array[MapAgents, AgentUnitClass]
  for id in 0 ..< MapAgents:
    prevTerminated[id] = env.terminated[id]
    if env.terminated[id] == 0.0:
      let agent = env.agents[id]
      if agent != nil:
        prevUnitClass[id] = agent.unitClass

  # Track first-time events
  var firstBuildingStep: Table[string, int]  # "Team X: BuildingKind" -> step
  var firstUnitStep: Table[string, int]  # "Team X: UnitClass" -> step
  var firstTechStep: Table[string, int]  # "Team X: TechName" -> step

  # Previous tech state for change detection
  var prevBlacksmith: array[Teams, BlacksmithUpgrades]
  var prevUniTechs: array[Teams, UniversityTechs]
  var prevCastleTechs: array[Teams, CastleTechs]
  var prevUnitUpgrades: array[Teams, UnitUpgrades]
  var prevEconTechs: array[Teams, EconomyTechs]
  for t in 0 ..< Teams:
    prevBlacksmith[t] = env.teamBlacksmithUpgrades[t]
    prevUniTechs[t] = env.teamUniversityTechs[t]
    prevCastleTechs[t] = env.teamCastleTechs[t]
    prevUnitUpgrades[t] = env.teamUnitUpgrades[t]
    prevEconTechs[t] = env.teamEconomyTechs[t]

  # Market price tracking
  var marketTraded = false
  var prevMarketPrices: array[Teams, MarketPrices]
  for t in 0 ..< Teams:
    prevMarketPrices[t] = env.teamMarketPrices[t]

  # Resource sampling: track min/max/avg stockpiles over time
  var resourceSamples: array[Teams, array[StockpileResource, seq[int]]]
  const SampleInterval = 100  # Sample every 100 steps

  # Production queue tracking
  var totalQueued: array[Teams, int]  # Total units ever queued
  var totalProduced: array[Teams, int]  # Total units that finished production

  # AI role distribution tracking
  var roleCounts: array[AgentRole, int]

  let startTime = getMonoTime()

  # --- Main simulation loop ---
  for step in 0 ..< totalSteps:
    var actions = getActions(env)
    env.step(addr actions)

    # Periodic resource sampling
    if step mod SampleInterval == 0:
      for t in 0 ..< Teams:
        for res in StockpileResource:
          resourceSamples[t][res].add(env.teamStockpiles[t].counts[res])

    # Track births (new agents appearing)
    for id in 0 ..< MapAgents:
      let nowAlive = env.terminated[id] == 0.0
      let wasAlive = prevTerminated[id] == 0.0
      if nowAlive and not wasAlive:
        # Birth/respawn
        let agent = env.agents[id]
        if agent != nil:
          let teamId = getTeamId(id)
          if teamId >= 0 and teamId < Teams:
            unitsTrained[teamId][agent.unitClass] += 1
            let key = &"Team {teamId}: {agent.unitClass}"
            if key notin firstUnitStep:
              firstUnitStep[key] = step
      elif wasAlive and not nowAlive:
        # Death
        let teamId = getTeamId(id)
        if teamId >= 0 and teamId < Teams:
          teamDeaths[teamId] += 1
      # Track unit class changes (upgrades)
      if nowAlive:
        let agent = env.agents[id]
        if agent != nil and agent.unitClass != prevUnitClass[id]:
          let teamId = getTeamId(id)
          if teamId >= 0 and teamId < Teams:
            unitsTrained[teamId][agent.unitClass] += 1
            let key = &"Team {teamId}: {agent.unitClass}"
            if key notin firstUnitStep:
              firstUnitStep[key] = step
          prevUnitClass[id] = agent.unitClass
      prevTerminated[id] = env.terminated[id]

    # Detect tech research events
    for t in 0 ..< Teams:
      # Blacksmith
      for upgrade in BlacksmithUpgradeType:
        if env.teamBlacksmithUpgrades[t].levels[upgrade] != prevBlacksmith[t].levels[upgrade]:
          let key = &"Team {t}: Blacksmith {upgrade} L{env.teamBlacksmithUpgrades[t].levels[upgrade]}"
          if key notin firstTechStep:
            firstTechStep[key] = step
      prevBlacksmith[t] = env.teamBlacksmithUpgrades[t]

      # University
      for tech in UniversityTechType:
        if env.teamUniversityTechs[t].researched[tech] and not prevUniTechs[t].researched[tech]:
          let key = &"Team {t}: University {tech}"
          if key notin firstTechStep:
            firstTechStep[key] = step
      prevUniTechs[t] = env.teamUniversityTechs[t]

      # Castle techs
      for tech in CastleTechType:
        if env.teamCastleTechs[t].researched[tech] and not prevCastleTechs[t].researched[tech]:
          let key = &"Team {t}: Castle {tech}"
          if key notin firstTechStep:
            firstTechStep[key] = step
      prevCastleTechs[t] = env.teamCastleTechs[t]

      # Unit upgrades
      for upgrade in UnitUpgradeType:
        if env.teamUnitUpgrades[t].researched[upgrade] and not prevUnitUpgrades[t].researched[upgrade]:
          let key = &"Team {t}: UnitUpgrade {upgrade}"
          if key notin firstTechStep:
            firstTechStep[key] = step
      prevUnitUpgrades[t] = env.teamUnitUpgrades[t]

      # Economy techs
      for tech in EconomyTechType:
        if env.teamEconomyTechs[t].researched[tech] and not prevEconTechs[t].researched[tech]:
          let key = &"Team {t}: Economy {tech}"
          if key notin firstTechStep:
            firstTechStep[key] = step
      prevEconTechs[t] = env.teamEconomyTechs[t]

      # Market price changes (detect trading)
      for res in StockpileResource:
        if env.teamMarketPrices[t].prices[res] != prevMarketPrices[t].prices[res]:
          marketTraded = true
      prevMarketPrices[t] = env.teamMarketPrices[t]

  let elapsed = (getMonoTime().ticks - startTime.ticks).float64 / 1_000_000_000.0

  # ═══════════════════════════════════════════════════════════
  # FINAL STATE ANALYSIS
  # ═══════════════════════════════════════════════════════════

  echo &"Completed {totalSteps} steps in {elapsed:.2f}s ({float64(totalSteps)/elapsed:.0f} SPS)"
  echo ""

  # --- 1. BUILDINGS PER TEAM ---
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  1. BUILDINGS (per team, end-of-game snapshot)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  var teamBuildingCounts: array[Teams, CountTable[ThingKind]]
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      let t = env.grid[x][y]
      if t != nil and isBuildingKind(t.kind):
        let teamId = t.teamId
        if teamId >= 0 and teamId < Teams:
          teamBuildingCounts[teamId].inc(t.kind)
      let bg = env.backgroundGrid[x][y]
      if bg != nil and isBuildingKind(bg.kind):
        let teamId = bg.teamId
        if teamId >= 0 and teamId < Teams:
          teamBuildingCounts[teamId].inc(bg.kind)

  # Aggregate across all teams
  var globalBuildingCounts: CountTable[ThingKind]
  for t in 0 ..< Teams:
    for kind, count in teamBuildingCounts[t]:
      globalBuildingCounts.inc(kind, count)

  # Sort by count
  var buildPairs: seq[(int, ThingKind)]
  for kind, count in globalBuildingCounts:
    buildPairs.add((count, kind))
  buildPairs.sort(proc(a, b: (int, ThingKind)): int = cmp(b[0], a[0]))

  echo "  Global building totals (all teams):"
  for (count, kind) in buildPairs:
    echo &"    {kind:<24s} {count:>5d}"
  echo ""

  # Per-team summary (only interesting teams)
  for t in 0 ..< Teams:
    var total = 0
    for kind, count in teamBuildingCounts[t]:
      total += count
    if total > 0:
      var pairs: seq[(int, string)]
      for kind, count in teamBuildingCounts[t]:
        pairs.add((count, $kind))
      pairs.sort(proc(a, b: (int, string)): int = cmp(b[0], a[0]))
      var items: seq[string]
      for (c, k) in pairs:
        items.add(&"{k}:{c}")
      echo &"  Team {t} ({total} total): {items.join(\", \")}"
  echo ""

  # --- 2. UNIT COMPOSITION ---
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  2. UNIT COMPOSITION (alive at end + trained during game)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # Current alive unit composition
  var aliveByTeam: array[Teams, CountTable[AgentUnitClass]]
  var aliveTotal: array[Teams, int]
  for id in 0 ..< MapAgents:
    if env.terminated[id] == 0.0:
      let agent = env.agents[id]
      if agent != nil:
        let teamId = getTeamId(id)
        if teamId >= 0 and teamId < Teams:
          aliveByTeam[teamId].inc(agent.unitClass)
          aliveTotal[teamId] += 1

  echo "  Alive unit counts by class (all teams combined):"
  var globalUnits: CountTable[AgentUnitClass]
  for t in 0 ..< Teams:
    for cls, count in aliveByTeam[t]:
      globalUnits.inc(cls, count)
  var unitPairs: seq[(int, AgentUnitClass)]
  for cls, count in globalUnits:
    unitPairs.add((count, cls))
  unitPairs.sort(proc(a, b: (int, AgentUnitClass)): int = cmp(b[0], a[0]))
  for (count, cls) in unitPairs:
    echo &"    {cls:<28s} {count:>5d}"
  echo ""

  # Units trained during game (births by class)
  echo "  Units trained/born during game (all teams):"
  var trainedGlobal: CountTable[AgentUnitClass]
  for t in 0 ..< Teams:
    for cls in AgentUnitClass:
      if unitsTrained[t][cls] > 0:
        trainedGlobal.inc(cls, unitsTrained[t][cls])
  var trainPairs: seq[(int, AgentUnitClass)]
  for cls, count in trainedGlobal:
    trainPairs.add((count, cls))
  trainPairs.sort(proc(a, b: (int, AgentUnitClass)): int = cmp(b[0], a[0]))
  for (count, cls) in trainPairs:
    echo &"    {cls:<28s} {count:>5d}"
  echo ""

  # --- 3. TECHNOLOGY RESEARCH ---
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  3. TECHNOLOGY RESEARCH"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if firstTechStep.len == 0:
    echo "  ❌ NO technologies researched during this game!"
  else:
    var techEvents: seq[(int, string)]
    for key, step in firstTechStep:
      techEvents.add((step, key))
    techEvents.sort(proc(a, b: (int, string)): int = cmp(a[0], b[0]))
    echo &"  {techEvents.len} tech events:"
    for (step, key) in techEvents:
      echo &"    Step {step:>5d}: {key}"

  # Summary per category
  echo ""
  var blacksmithCount, uniCount, castleCount, unitUpgradeCount, econCount = 0
  for t in 0 ..< Teams:
    for upgrade in BlacksmithUpgradeType:
      blacksmithCount += env.teamBlacksmithUpgrades[t].levels[upgrade]
    for tech in UniversityTechType:
      if env.teamUniversityTechs[t].researched[tech]: inc uniCount
    for tech in CastleTechType:
      if env.teamCastleTechs[t].researched[tech]: inc castleCount
    for upgrade in UnitUpgradeType:
      if env.teamUnitUpgrades[t].researched[upgrade]: inc unitUpgradeCount
    for tech in EconomyTechType:
      if env.teamEconomyTechs[t].researched[tech]: inc econCount

  echo &"  Summary: Blacksmith:{blacksmithCount} levels, University:{uniCount}, Castle:{castleCount}, UnitUpgrade:{unitUpgradeCount}, Economy:{econCount}"
  echo ""

  # --- 4. ECONOMY ---
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  4. ECONOMY (end-of-game stockpiles)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  for t in 0 ..< Teams:
    var hasResources = false
    for res in StockpileResource:
      if env.teamStockpiles[t].counts[res] > 0:
        hasResources = true
        break
    if hasResources or aliveTotal[t] > 0:
      var resStr: seq[string]
      for res in StockpileResource:
        let c = env.teamStockpiles[t].counts[res]
        if c > 0:
          resStr.add(&"{res}:{c}")
      if resStr.len > 0:
        echo &"  Team {t}: {resStr.join(\", \")}"
      else:
        echo &"  Team {t}: (empty stockpile)"
  echo ""

  # Market trading
  echo &"  Market trading detected: {(if marketTraded: \"YES\" else: \"NO\")}"
  if marketTraded:
    for t in 0 ..< Teams:
      var changed = false
      for res in StockpileResource:
        if env.teamMarketPrices[t].prices[res] != 100:  # 100 = default base price
          changed = true
      if changed:
        var priceStr: seq[string]
        for res in StockpileResource:
          let p = env.teamMarketPrices[t].prices[res]
          if p != 100:
            priceStr.add(&"{res}:{p}")
        echo &"    Team {t} prices: {priceStr.join(\", \")}"
  echo ""

  # Resource trends (min/avg/max over game)
  echo "  Resource trends (sampled every 100 steps):"
  for t in 0 ..< min(Teams, 3):  # Show first 3 teams
    var parts: seq[string]
    for res in StockpileResource:
      let samples = resourceSamples[t][res]
      if samples.len > 0:
        var minVal = samples[0]
        var maxVal = samples[0]
        var sum = 0
        for s in samples:
          if s < minVal: minVal = s
          if s > maxVal: maxVal = s
          sum += s
        let avg = sum div samples.len
        if maxVal > 0:
          parts.add(&"{res}: {minVal}/{avg}/{maxVal}")
    if parts.len > 0:
      echo &"    Team {t} (min/avg/max): {parts.join(\", \")}"
  echo ""

  # Tribute
  var tributeActivity = false
  for t in 0 ..< Teams:
    if env.teamTributesSent[t] > 0 or env.teamTributesReceived[t] > 0:
      tributeActivity = true
      echo &"  Tribute: Team {t} sent={env.teamTributesSent[t]}, received={env.teamTributesReceived[t]}"
  if not tributeActivity:
    echo "  Tribute: No tribute activity"
  echo ""

  # --- 5. COMBAT ---
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  5. COMBAT (deaths per team)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  var totalCombatDeaths = 0
  for t in 0 ..< Teams:
    if teamDeaths[t] > 0:
      echo &"  Team {t}: {teamDeaths[t]} deaths"
      totalCombatDeaths += teamDeaths[t]
  echo &"  Total deaths: {totalCombatDeaths}"
  echo ""

  # --- 6. VICTORY STATE ---
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  6. VICTORY CONDITIONS"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  echo &"  Victory mode: {env.config.victoryCondition}"
  for t in 0 ..< Teams:
    let vs = env.victoryStates[t]
    var flags: seq[string]
    if vs.wonderBuiltStep >= 0:
      flags.add(&"Wonder at step {vs.wonderBuiltStep}")
    if vs.relicHoldStartStep >= 0:
      flags.add(&"Relic hold since step {vs.relicHoldStartStep}")
    if vs.kingAgentId >= 0:
      let alive = env.terminated[vs.kingAgentId] == 0.0
      flags.add(&"King id={vs.kingAgentId} alive={alive}")
    if vs.hillControlStartStep >= 0:
      flags.add(&"Hill control since step {vs.hillControlStartStep}")
    if flags.len > 0:
      echo &"  Team {t}: {flags.join(\", \")}"
  echo ""

  # --- 7. SPECIAL FEATURES ---
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  7. SPECIAL FEATURES CHECK"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # Count relics on map vs in monasteries
  # Relics are BackgroundThingKinds so they live in backgroundGrid, not grid.
  # Monasteries are blocking buildings so they live in grid.
  var relicsOnMap = 0
  var monasteryCount = 0
  var relicsGarrisoned = 0
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      let bg = env.backgroundGrid[x][y]
      if bg != nil and bg.kind == Relic:
        inc relicsOnMap
      let t = env.grid[x][y]
      if t != nil and t.kind == Monastery:
        inc monasteryCount
        relicsGarrisoned += t.garrisonedRelics

  # Count naval units
  var navalUnits = 0
  var monkUnits = 0
  var siegeUnits = 0
  var uniqueUnits = 0
  for id in 0 ..< MapAgents:
    if env.terminated[id] == 0.0:
      let agent = env.agents[id]
      if agent != nil:
        case agent.unitClass
        of UnitBoat, UnitGalley, UnitFireShip, UnitFishingShip,
           UnitTransportShip, UnitDemoShip, UnitCannonGalleon, UnitTradeCog:
          inc navalUnits
        of UnitMonk:
          inc monkUnits
        of UnitBatteringRam, UnitMangonel, UnitTrebuchet, UnitScorpion:
          inc siegeUnits
        of UnitSamurai, UnitLongbowman, UnitCataphract, UnitWoadRaider,
           UnitTeutonicKnight, UnitHuskarl, UnitMameluke, UnitJanissary:
          inc uniqueUnits
        else:
          discard

  # Count docks and wonders
  var dockCount = 0
  var wonderCount = 0
  var universityCount = 0
  var castleCount2 = 0
  var marketCount = 0
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      let t = env.grid[x][y]
      if t != nil:
        case t.kind
        of Wonder: inc wonderCount
        of University: inc universityCount
        of Castle: inc castleCount2
        of Market: inc marketCount
        else: discard
      # Dock is in BackgroundThingKinds, so check backgroundGrid
      let bg = env.backgroundGrid[x][y]
      if bg != nil and bg.kind == Dock:
        inc dockCount

  # Count walls and doors
  var wallCount = 0
  var doorCount = 0
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      let t = env.grid[x][y]
      if t != nil and t.kind == Wall: inc wallCount
      let bg = env.backgroundGrid[x][y]
      if bg != nil and bg.kind == Door: inc doorCount

  # Feature presence check
  proc check(name: string, present: bool, detail: string = "") =
    let icon = if present: "✅" else: "❌"
    if detail.len > 0:
      echo &"  {icon} {name:<30s} {detail}"
    else:
      echo &"  {icon} {name}"

  check("Walls built", wallCount > 0, &"({wallCount} walls, {doorCount} doors)")
  check("Castles built", castleCount2 > 0, &"({castleCount2} castles)")
  check("Markets built", marketCount > 0, &"({marketCount} markets)")
  check("Market trading", marketTraded)
  check("Universities built", universityCount > 0, &"({universityCount} universities)")
  check("Docks built", dockCount > 0, &"({dockCount} docks)")
  check("Wonders built", wonderCount > 0, &"({wonderCount} wonders)")
  check("Naval units alive", navalUnits > 0, &"({navalUnits} naval)")
  check("Monks alive", monkUnits > 0, &"({monkUnits} monks)")
  check("Siege units alive", siegeUnits > 0, &"({siegeUnits} siege)")
  check("Unique castle units", uniqueUnits > 0, &"({uniqueUnits} unique)")
  check("Relics on map", relicsOnMap > 0, &"({relicsOnMap} relics)")
  check("Relics garrisoned", relicsGarrisoned > 0, &"({relicsGarrisoned} in monasteries)")
  check("Monasteries built", monasteryCount > 0, &"({monasteryCount} monasteries)")
  check("Blacksmith upgrades", blacksmithCount > 0, &"({blacksmithCount} levels)")
  check("University techs", uniCount > 0, &"({uniCount} researched)")
  check("Castle techs", castleCount > 0, &"({castleCount} researched)")
  check("Unit upgrades", unitUpgradeCount > 0, &"({unitUpgradeCount} researched)")
  check("Economy techs", econCount > 0, &"({econCount} researched)")
  check("Tribute activity", tributeActivity)

  echo ""

  # --- 8. FIRST-EVENT TIMELINE ---
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  8. FIRST-EVENT TIMELINE (first occurrence of buildings)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if firstBuildingStep.len > 0 or firstUnitStep.len > 0:
    var allEvents: seq[(int, string)]
    for key, step in firstBuildingStep:
      allEvents.add((step, key))
    for key, step in firstUnitStep:
      allEvents.add((step, key))
    allEvents.sort(proc(a, b: (int, string)): int = cmp(a[0], b[0]))
    for (step, key) in allEvents[0 ..< min(30, allEvents.len)]:
      echo &"    Step {step:>5d}: {key}"
  else:
    echo "    (no first-event data captured for buildings)"

  # --- 9. AI ROLE DISTRIBUTION ---
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  9. AI ROLE DISTRIBUTION (end-of-game)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  for id in 0 ..< MapAgents:
    if env.terminated[id] == 0.0:
      let role = globalController.aiController.getAgentRole(id)
      roleCounts[role] += 1

  for role in AgentRole:
    if roleCounts[role] > 0:
      echo &"    {role:<20s} {roleCounts[role]:>5d}"

  # Count fighter villagers vs fighter military
  var fighterVillagers = 0
  var fighterMilitary = 0
  for id in 0 ..< MapAgents:
    if env.terminated[id] == 0.0:
      let role = globalController.aiController.getAgentRole(id)
      if role == Fighter:
        let agent = env.agents[id]
        if agent != nil:
          if agent.unitClass == UnitVillager:
            inc fighterVillagers
          else:
            inc fighterMilitary
  echo ""
  echo &"    Fighter breakdown: {fighterVillagers} villagers, {fighterMilitary} military"

  # Check if Barracks training is affordable right now
  echo ""
  echo "  Can-train check (current stockpiles):"
  for t in 0 ..< Teams:
    let canBarracks = env.canSpendStockpile(t, @[(res: ResourceFood, count: 3), (res: ResourceGold, count: 1)])
    let canArchery = env.canSpendStockpile(t, @[(res: ResourceWood, count: 2), (res: ResourceGold, count: 2)])
    let canStable = env.canSpendStockpile(t, @[(res: ResourceFood, count: 3)])
    echo &"    Team {t}: Barracks={canBarracks}, ArcheryRange={canArchery}, Stable={canStable}"
  echo ""

  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "  AUDIT COMPLETE"
  echo "═══════════════════════════════════════════════════════════"

main()
