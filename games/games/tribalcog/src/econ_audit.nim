## Resource economy flow tracker and dashboard.

when defined(econAudit):
  import
    std/strformat,
    constants, envconfig, types

  const
    EconAuditDashboardInterval* = 100  ## Print dashboard every N steps
    EconAuditWindowSize* = 100         ## Steps to average rates over
    ResourceOrder = [ResourceFood, ResourceWood, ResourceGold, ResourceStone]

  type
    ResourceFlowSource* = enum
      ## Categories of resource income/spending
      rfsGathering       ## Villager gathering from resource nodes
      rfsDeposit         ## Depositing gathered resources at storage
      rfsBuildingCost    ## Building construction costs
      rfsUnitTraining    ## Unit training costs
      rfsTechResearch    ## Technology research costs
      rfsMarketBuy       ## Market purchase (spend gold, gain resource)
      rfsMarketSell      ## Market sale (spend resource, gain gold)
      rfsRelicGold       ## Relic gold generation from monastery
      rfsTradeShip       ## Trade ship (cog) gold generation
      rfsFarmReseed      ## Farm reseed wood cost
      rfsRefund          ## Cancelled queue refunds

    TeamResourceStats* = object
      totalGained*: array[StockpileResource, int]
      totalSpent*: array[StockpileResource, int]
      gainedBySource*: array[ResourceFlowSource, array[StockpileResource, int]]
      recentGains*: array[StockpileResource, int]
      recentSpends*: array[StockpileResource, int]
      windowStartStep*: int

    EconAuditState* = object
      verboseMode*: bool
      teamStats*: array[MapRoomObjectsTeams, TeamResourceStats]
      lastDashboardStep*: int
      initialized*: bool

  var econAuditState*: EconAuditState

  proc resourceName(res: StockpileResource): string =
    ## Returns the lowercase display name for one resource.
    case res
    of ResourceFood: "food"
    of ResourceWood: "wood"
    of ResourceGold: "gold"
    of ResourceStone: "stone"
    of ResourceWater: "water"
    of ResourceNone: "none"

  proc sourceName(source: ResourceFlowSource): string =
    ## Returns the lowercase display name for one flow source.
    case source
    of rfsGathering: "gathered"
    of rfsDeposit: "deposited"
    of rfsBuildingCost: "building"
    of rfsUnitTraining: "training"
    of rfsTechResearch: "research"
    of rfsMarketBuy: "market_buy"
    of rfsMarketSell: "market_sell"
    of rfsRelicGold: "relic"
    of rfsTradeShip: "trade_ship"
    of rfsFarmReseed: "farm_reseed"
    of rfsRefund: "refund"

  proc resetRecentFlows(stats: var TeamResourceStats) =
    ## Clears the sliding-window counters for one team.
    for res in StockpileResource:
      stats.recentGains[res] = 0
      stats.recentSpends[res] = 0

  proc initEconAudit*() =
    ## Initializes economy audit state from environment settings.
    econAuditState = EconAuditState(
      verboseMode: parseEnvBool("TV_ECON_VERBOSE", false),
      lastDashboardStep: 0,
      initialized: true
    )
    for teamId in 0 ..< MapRoomObjectsTeams:
      econAuditState.teamStats[teamId] = TeamResourceStats(
        windowStartStep: 0
      )

  proc ensureEconAuditInit*() =
    ## Initializes economy audit state on first use.
    if not econAuditState.initialized:
      initEconAudit()

  proc recordFlow*(
    teamId: int,
    res: StockpileResource,
    amount: int,
    source: ResourceFlowSource,
    step: int
  ) =
    ## Record a resource flow event.
    ## Positive amount = income, negative = spending.
    ensureEconAuditInit()
    if teamId < 0 or teamId >= MapRoomObjectsTeams:
      return
    if res == ResourceNone:
      return

    var stats = addr econAuditState.teamStats[teamId]

    if step - stats.windowStartStep >= EconAuditWindowSize:
      resetRecentFlows(stats[])
      stats.windowStartStep = step

    if amount > 0:
      stats.totalGained[res] += amount
      stats.recentGains[res] += amount
      stats.gainedBySource[source][res] += amount
    else:
      let absAmount = -amount
      stats.totalSpent[res] += absAmount
      stats.recentSpends[res] += absAmount

    if econAuditState.verboseMode:
      let sign = if amount > 0: "+" else: ""
      echo(
        &"[Step {step}] {teamColorName(teamId)} {sign}{amount} " &
        &"{resourceName(res)} ({sourceName(source)})"
      )

  proc recordResearchCost*(
    teamId: int,
    costs: openArray[tuple[res: StockpileResource, count: int]],
    step: int
  ) =
    ## Records one batch of research costs.
    for cost in costs:
      recordFlow(teamId, cost.res, -cost.count, rfsTechResearch, step)

  proc printEconDashboard*(env: Environment, step: int) =
    ## Print economy dashboard for all teams.
    echo ""
    echo "======================================================================"
    echo &"  ECONOMY DASHBOARD - Step {step}"
    echo "======================================================================"
    echo "Team       |       Food |       Wood |       Gold |      Stone"
    echo "----------------------------------------------------------------------"

    for teamId in 0 ..< MapRoomObjectsTeams:
      let stats = econAuditState.teamStats[teamId]
      var stockLine = &"{teamColorName(teamId):<10} |"
      for res in ResourceOrder:
        let stock = env.teamStockpiles[teamId].counts[res]
        stockLine &= &" {stock:>10} |"
      echo stockLine

      let windowSteps = max(1, step - stats.windowStartStep)
      let rateMultiplier = 100.0 / float(windowSteps)

      var incomeRate = &"  +income  |"
      for res in ResourceOrder:
        let rate = int(float(stats.recentGains[res]) * rateMultiplier)
        if rate > 0:
          incomeRate &= &" {rate:>+10} |"
        else:
          incomeRate &= &" {\"\":>10} |"
      echo incomeRate

      var spendRate = &"  -spend   |"
      for res in ResourceOrder:
        let rate = int(float(stats.recentSpends[res]) * rateMultiplier)
        if rate > 0:
          spendRate &= &" {-rate:>10} |"
        else:
          spendRate &= &" {\"\":>10} |"
      echo spendRate

      var netFlow = &"  =net     |"
      for res in ResourceOrder:
        let gain = int(float(stats.recentGains[res]) * rateMultiplier)
        let spend = int(float(stats.recentSpends[res]) * rateMultiplier)
        let net = gain - spend
        if net != 0:
          netFlow &= &" {net:>+10} |"
        else:
          netFlow &= &" {\"\":>10} |"
      echo netFlow

      echo "----------------------------------------------------------------------"

    echo ""
    echo "======================================================================"
    echo "  TOTALS (All Time)"
    echo "======================================================================"
    echo "Team       |   F-Gained |   W-Gained |   G-Gained |   S-Gained"
    echo "----------------------------------------------------------------------"

    for teamId in 0 ..< MapRoomObjectsTeams:
      let stats = econAuditState.teamStats[teamId]
      var line = &"{teamColorName(teamId):<10} |"
      for res in ResourceOrder:
        line &= &" {stats.totalGained[res]:>10} |"
      echo line

    echo "Team       |    F-Spent |    W-Spent |    G-Spent |    S-Spent"
    echo "----------------------------------------------------------------------"

    for teamId in 0 ..< MapRoomObjectsTeams:
      let stats = econAuditState.teamStats[teamId]
      var line = &"{teamColorName(teamId):<10} |"
      for res in ResourceOrder:
        line &= &" {stats.totalSpent[res]:>10} |"
      echo line

    if parseEnvBool("TV_ECON_DETAILED", false):
      echo ""
      echo "======================================================================"
      echo "  INCOME BY SOURCE"
      echo "======================================================================"
      for teamId in 0 ..< MapRoomObjectsTeams:
        let stats = econAuditState.teamStats[teamId]
        echo &"\n{teamColorName(teamId)}:"
        for source in ResourceFlowSource:
          var hasData = false
          for res in ResourceOrder:
            if stats.gainedBySource[source][res] > 0:
              hasData = true
              break
          if hasData:
            var line = &"  {sourceName(source):<12}:"
            for res in ResourceOrder:
              let amt = stats.gainedBySource[source][res]
              if amt > 0:
                line &= &" {resourceName(res)}={amt}"
            echo line

    echo "======================================================================\n"

  proc maybePrintEconDashboard*(env: Environment, step: int) =
    ## Print dashboard every EconAuditDashboardInterval steps.
    ensureEconAuditInit()
    if step > 0 and step mod EconAuditDashboardInterval == 0 and
       step != econAuditState.lastDashboardStep:
      econAuditState.lastDashboardStep = step
      printEconDashboard(env, step)

  proc resetEconAudit*() =
    ## Reset econ audit state for game reset.
    for teamId in 0 ..< MapRoomObjectsTeams:
      econAuditState.teamStats[teamId] = TeamResourceStats(
        windowStartStep: 0
      )
    econAuditState.lastDashboardStep = 0
