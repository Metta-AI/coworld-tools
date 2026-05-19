## Tumor spread audit logging for spawn, damage, and interval summaries.

when defined(tumorAudit):
  import
    std/strutils,
    envconfig, types

  const
    ReportDivider = "═══════════════════════════════════════════════════════"

  type
    TumorAuditState* = object
      reportInterval*: int
      lastReportStep*: int
      totalSpawned*: int
      totalBranched*: int
      totalDamageDealt*: int
      totalAgentKills*: int
      totalPredatorKills*: int
      totalTumorsDestroyed*: int
      intervalSpawned*: int
      intervalBranched*: int
      intervalDamageDealt*: int
      intervalAgentKills*: int
      intervalPredatorKills*: int
      intervalTumorsDestroyed*: int

  var
    tumorAudit*: TumorAuditState
    tumorAuditInitialized = false

  proc initTumorAudit*() =
    ## Initialize tumor audit state from environment settings.
    tumorAudit = TumorAuditState(
      reportInterval: max(1, parseEnvInt("TV_TUMOR_REPORT_INTERVAL", 100)),
      lastReportStep: 0
    )
    tumorAuditInitialized = true

  proc ensureTumorAuditInit*() =
    ## Initialize tumor audit state on first use.
    if not tumorAuditInitialized:
      initTumorAudit()

  proc resetIntervalStats() =
    ## Clears per-interval tumor counters after one report.
    tumorAudit.intervalSpawned = 0
    tumorAudit.intervalBranched = 0
    tumorAudit.intervalDamageDealt = 0
    tumorAudit.intervalAgentKills = 0
    tumorAudit.intervalPredatorKills = 0
    tumorAudit.intervalTumorsDestroyed = 0

  proc recordTumorSpawned*() =
    ## Record one tumor spawned by a spawner.
    ensureTumorAuditInit()
    inc tumorAudit.totalSpawned
    inc tumorAudit.intervalSpawned

  proc recordTumorBranched*() =
    ## Record one tumor created by branching.
    ensureTumorAuditInit()
    inc tumorAudit.totalBranched
    inc tumorAudit.intervalBranched

  proc recordTumorDamage*(killed: bool) =
    ## Record one tumor damage event and optional agent kill.
    ensureTumorAuditInit()
    inc tumorAudit.totalDamageDealt
    inc tumorAudit.intervalDamageDealt
    if killed:
      inc tumorAudit.totalAgentKills
      inc tumorAudit.intervalAgentKills

  proc recordTumorPredatorKill*() =
    ## Record one predator kill caused by tumors.
    ensureTumorAuditInit()
    inc tumorAudit.totalPredatorKills
    inc tumorAudit.intervalPredatorKills

  proc recordTumorDestroyed*() =
    ## Record one destroyed tumor.
    ensureTumorAuditInit()
    inc tumorAudit.totalTumorsDestroyed
    inc tumorAudit.intervalTumorsDestroyed

  proc printTumorReport*(env: Environment) =
    ## Print the tumor report when the reporting interval elapses.
    ensureTumorAuditInit()
    if env.currentStep - tumorAudit.lastReportStep < tumorAudit.reportInterval:
      return
    tumorAudit.lastReportStep = env.currentStep

    let
      activeTumors = env.thingsByKind[Tumor].len
      spawnerCount = env.thingsByKind[Spawner].len
      intervalSteps = tumorAudit.reportInterval
      newThisInterval = tumorAudit.intervalSpawned + tumorAudit.intervalBranched
    var
      mobileTumors = 0
      inertTumors = 0
    for tumor in env.thingsByKind[Tumor]:
      if tumor.isNil:
        continue
      if tumor.hasClaimedTerritory:
        inc inertTumors
      else:
        inc mobileTumors

    let spreadVelocity =
      if intervalSteps > 0:
        newThisInterval.float / intervalSteps.float
      else:
        0.0

    echo ReportDivider
    echo "  TUMOR REPORT — Step ", env.currentStep
    echo ReportDivider
    echo(
      "  Active tumors: ",
      activeTumors,
      " (mobile=",
      mobileTumors,
      " inert=",
      inertTumors,
      ")"
    )
    echo "  Spawners: ", spawnerCount
    echo "  --- This interval (", intervalSteps, " steps) ---"
    echo(
      "  New tumors: ",
      newThisInterval,
      " (spawned=",
      tumorAudit.intervalSpawned,
      " branched=",
      tumorAudit.intervalBranched,
      ")"
    )
    echo(
      "  Spread velocity: ",
      formatFloat(spreadVelocity, ffDecimal, 3),
      " tumors/step"
    )
    echo(
      "  Damage dealt: ",
      tumorAudit.intervalDamageDealt,
      " (agent kills=",
      tumorAudit.intervalAgentKills,
      " predator kills=",
      tumorAudit.intervalPredatorKills,
      ")"
    )
    echo "  Tumors destroyed: ", tumorAudit.intervalTumorsDestroyed
    echo "  --- Lifetime totals ---"
    echo(
      "  Total spawned: ",
      tumorAudit.totalSpawned,
      " Total branched: ",
      tumorAudit.totalBranched
    )
    echo(
      "  Total damage: ",
      tumorAudit.totalDamageDealt,
      " Agent kills: ",
      tumorAudit.totalAgentKills,
      " Predator kills: ",
      tumorAudit.totalPredatorKills
    )
    echo "  Total tumors destroyed: ", tumorAudit.totalTumorsDestroyed
    echo ReportDivider

    resetIntervalStats()
