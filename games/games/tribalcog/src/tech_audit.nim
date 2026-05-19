## Technology research and upgrade tracking.

when defined(techAudit):
  import
    std/[strformat, strutils, tables],
    constants, envconfig, types

  const
    TechAuditSummaryInterval* = 100  ## Print tech status every N steps
    TechSummaryDivider = "================================"

  type
    TechResearchEvent* = object
      step*: int
      teamId*: int
      techName*: string
      costs*: seq[tuple[resource: string, amount: int]]

    UpgradeApplicationEvent* = object
      step*: int
      teamId*: int
      upgradeName*: string
      unitsAffected*: int
      attackDelta*: int
      armorDelta*: int
      hpDelta*: int

    TechAuditState* = object
      researchEvents*: seq[TechResearchEvent]
      upgradeEvents*: seq[UpgradeApplicationEvent]
      totalSpentByTeam*: array[MapRoomObjectsTeams, Table[string, int]]
      lastSummaryStep*: int

  var techAuditState*: TechAuditState
  var
    techAuditInitialized = false

  proc initTechAudit*() =
    ## Initializes technology audit state.
    techAuditState = TechAuditState(
      researchEvents: @[],
      upgradeEvents: @[],
      lastSummaryStep: 0
    )
    for teamId in 0 ..< MapRoomObjectsTeams:
      techAuditState.totalSpentByTeam[teamId] = initStringIntTable()
    techAuditInitialized = true

  proc ensureTechAuditInit*() =
    ## Initializes technology audit state on first use.
    if not techAuditInitialized:
      initTechAudit()

  proc formatCosts(
    costs: openArray[tuple[resource: string, amount: int]]
  ): string =
    ## Formats one research cost list for log output.
    var parts: seq[string]
    for cost in costs:
      parts.add(&"{cost.amount} {cost.resource}")
    if parts.len > 0:
      result = parts.join(", ")
    else:
      result = "free"

  proc resourceName(res: StockpileResource): string =
    ## Returns the lowercase display name for one resource.
    case res
    of ResourceFood: "food"
    of ResourceWood: "wood"
    of ResourceGold: "gold"
    of ResourceStone: "stone"
    of ResourceWater: "water"
    of ResourceNone: "none"

  proc addSpentCosts(
    teamId: int,
    costs: openArray[tuple[resource: string, amount: int]]
  ) =
    ## Accumulates research spending totals for one team.
    for cost in costs:
      if cost.resource notin techAuditState.totalSpentByTeam[teamId]:
        techAuditState.totalSpentByTeam[teamId][cost.resource] = 0
      techAuditState.totalSpentByTeam[teamId][cost.resource] += cost.amount

  proc logTechResearch*(
    teamId: int,
    techName: string,
    step: int,
    costs: seq[tuple[resource: string, amount: int]]
  ) =
    ## Logs one research event and its total cost.
    ensureTechAuditInit()
    let ev = TechResearchEvent(
      step: step,
      teamId: teamId,
      techName: techName,
      costs: costs
    )
    techAuditState.researchEvents.add(ev)
    addSpentCosts(teamId, costs)

    echo &"[Step {step}] {teamColorName(teamId)} researched {techName} (cost: {formatCosts(costs)})"

  proc logBlacksmithUpgrade*(
    teamId: int,
    upgradeType: BlacksmithUpgradeType,
    newLevel: int,
    step: int
  ) =
    ## Logs one blacksmith upgrade purchase.
    let costMultiplier = newLevel
    let foodCost = BlacksmithUpgradeFoodCost * costMultiplier
    let goldCost = BlacksmithUpgradeGoldCost * costMultiplier
    let techName = &"Blacksmith {upgradeType} Level {newLevel}"
    let costs = @[("food", foodCost), ("gold", goldCost)]
    logTechResearch(teamId, techName, step, costs)

  proc logUniversityTech*(teamId: int, techType: UniversityTechType, step: int) =
    ## Logs one university technology purchase.
    let techIndex = ord(techType) + 1
    let foodCost = UniversityTechFoodCost * techIndex
    let goldCost = UniversityTechGoldCost * techIndex
    let woodCost = UniversityTechWoodCost * techIndex
    let techName = &"University {techType}"
    let costs = @[("food", foodCost), ("gold", goldCost), ("wood", woodCost)]
    logTechResearch(teamId, techName, step, costs)

  proc logCastleTech*(
    teamId: int,
    techType: CastleTechType,
    isImperial: bool,
    step: int
  ) =
    ## Logs one castle technology purchase.
    let foodCost = if isImperial: CastleTechImperialFoodCost else: CastleTechFoodCost
    let goldCost = if isImperial: CastleTechImperialGoldCost else: CastleTechGoldCost
    let techName = &"Castle {techType}"
    let costs = @[("food", foodCost), ("gold", goldCost)]
    logTechResearch(teamId, techName, step, costs)

  proc logUnitUpgrade*(
    teamId: int,
    upgradeType: UnitUpgradeType,
    step: int,
    costs: seq[tuple[res: StockpileResource, count: int]]
  ) =
    ## Logs one unit upgrade purchase.
    let techName = &"Unit Upgrade {upgradeType}"
    var formattedCosts: seq[tuple[resource: string, amount: int]]
    for cost in costs:
      formattedCosts.add((resourceName(cost.res), cost.count))
    logTechResearch(teamId, techName, step, formattedCosts)

  proc logUpgradeApplication*(
    teamId: int,
    upgradeName: string,
    unitsAffected: int,
    attackDelta,
    armorDelta,
    hpDelta: int,
    step: int
  ) =
    ## Logs one upgrade application event.
    ensureTechAuditInit()
    let ev = UpgradeApplicationEvent(
      step: step,
      teamId: teamId,
      upgradeName: upgradeName,
      unitsAffected: unitsAffected,
      attackDelta: attackDelta,
      armorDelta: armorDelta,
      hpDelta: hpDelta
    )
    techAuditState.upgradeEvents.add(ev)

    var deltaStr = ""
    if attackDelta != 0:
      deltaStr &= &" attack={attackDelta:+d}"
    if armorDelta != 0:
      deltaStr &= &" armor={armorDelta:+d}"
    if hpDelta != 0:
      deltaStr &= &" hp={hpDelta:+d}"
    if deltaStr == "":
      deltaStr = " (stat bonuses applied)"

    echo &"[Step {step}] {teamColorName(teamId)} upgrade applied: {upgradeName} to {unitsAffected} units{deltaStr}"

  proc printTeamTechStatus*(env: Environment, teamId: int) =
    ## Print detailed tech status for a team.
    echo &"  Team {teamId} ({teamColorName(teamId)}):"

    var bsUpgrades: seq[string]
    for upType in BlacksmithUpgradeType:
      let level = env.teamBlacksmithUpgrades[teamId].levels[upType]
      if level > 0:
        bsUpgrades.add(&"{upType} L{level}")
    if bsUpgrades.len > 0:
      echo &"    Blacksmith: {bsUpgrades.join(\", \")}"

    var uniTechs: seq[string]
    for techType in UniversityTechType:
      if env.teamUniversityTechs[teamId].researched[techType]:
        uniTechs.add($techType)
    if uniTechs.len > 0:
      echo &"    University: {uniTechs.join(\", \")}"

    var castleTechs: seq[string]
    for techType in CastleTechType:
      if env.teamCastleTechs[teamId].researched[techType]:
        castleTechs.add($techType)
    if castleTechs.len > 0:
      echo &"    Castle: {castleTechs.join(\", \")}"

    var unitUpgrades: seq[string]
    for upType in UnitUpgradeType:
      if env.teamUnitUpgrades[teamId].researched[upType]:
        unitUpgrades.add($upType)
    if unitUpgrades.len > 0:
      echo &"    Units: {unitUpgrades.join(\", \")}"

    var econTechs: seq[string]
    for techType in EconomyTechType:
      if env.teamEconomyTechs[teamId].researched[techType]:
        econTechs.add($techType)
    if econTechs.len > 0:
      echo &"    Economy: {econTechs.join(\", \")}"

    if techAuditState.totalSpentByTeam[teamId].len > 0:
      var spentParts: seq[string]
      for res, amount in techAuditState.totalSpentByTeam[teamId]:
        spentParts.add(&"{amount} {res}")
      echo &"    Total spent: {spentParts.join(\", \")}"

  proc maybePrintTechSummary*(env: Environment, step: int) =
    ## Print per-team tech status every TechAuditSummaryInterval steps.
    ensureTechAuditInit()
    if step > 0 and step mod TechAuditSummaryInterval == 0 and
       step != techAuditState.lastSummaryStep:
      techAuditState.lastSummaryStep = step
      echo TechSummaryDivider
      echo &"Tech Status at Step {step}"
      echo TechSummaryDivider
      for teamId in 0 ..< MapRoomObjectsTeams:
        printTeamTechStatus(env, teamId)
      echo TechSummaryDivider

  proc resetTechAudit*() =
    ## Reset tech audit state for game reset.
    techAuditState.researchEvents.setLen(0)
    techAuditState.upgradeEvents.setLen(0)
    techAuditState.lastSummaryStep = 0
    for teamId in 0 ..< MapRoomObjectsTeams:
      techAuditState.totalSpentByTeam[teamId].clear()
