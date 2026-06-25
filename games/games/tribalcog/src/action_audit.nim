## Action distribution logging for per-step and aggregate audit output.

when defined(actionAudit):
  import
    std/strutils,
    common_types, envconfig, types

  const
    VerbCount = ActionVerbCount
    TeamCount = MapRoomObjectsTeams
    VerbNames: array[VerbCount, string] = [
      "noop", "move", "attack", "use", "swap",
      "put", "plant_lantern", "plant_resource", "build", "orient",
      "set_rally_point"
    ]

  type
    ActionAuditState* = object
      ## Per-step counters reset every step.
      stepVerbCounts: array[VerbCount, int]
      stepTeamVerbCounts: array[TeamCount, array[VerbCount, int]]
      stepTotal: int
      stepTeamTotals: array[TeamCount, int]
      ## Aggregate counters reset every report interval.
      aggVerbCounts: array[VerbCount, int]
      aggTeamVerbCounts: array[TeamCount, array[VerbCount, int]]
      aggTotal: int
      aggTeamTotals: array[TeamCount, int]
      aggStepCount: int
      reportInterval: int

  var
    actionAuditState*: ActionAuditState
    actionAuditInitialized = false

  proc initActionAudit*() =
    ## Initialize action audit state from environment settings.
    actionAuditState = ActionAuditState(
      reportInterval: max(1, parseEnvInt("TV_ACTION_AUDIT_INTERVAL", 100))
    )
    actionAuditInitialized = true

  proc ensureActionAuditInit*() =
    ## Initialize action audit state on first use.
    if not actionAuditInitialized:
      initActionAudit()

  proc resetStepCounters() =
    ## Reset the counters collected for the current step.
    for verb in 0 ..< VerbCount:
      actionAuditState.stepVerbCounts[verb] = 0
    for teamId in 0 ..< TeamCount:
      for verb in 0 ..< VerbCount:
        actionAuditState.stepTeamVerbCounts[teamId][verb] = 0
      actionAuditState.stepTeamTotals[teamId] = 0
    actionAuditState.stepTotal = 0

  proc recordAction*(agentId: int, verb: int) =
    ## Record one agent action for the current step.
    ensureActionAuditInit()
    let clampedVerb = clamp(verb, 0, VerbCount - 1)
    let teamId = agentId div MapAgentsPerTeam
    inc actionAuditState.stepVerbCounts[clampedVerb]
    inc actionAuditState.stepTotal
    if teamId >= 0 and teamId < TeamCount:
      inc actionAuditState.stepTeamVerbCounts[teamId][clampedVerb]
      inc actionAuditState.stepTeamTotals[teamId]

  proc flushStep() =
    ## Fold per-step counters into the aggregate counters.
    for verb in 0 ..< VerbCount:
      actionAuditState.aggVerbCounts[verb] +=
        actionAuditState.stepVerbCounts[verb]
    for teamId in 0 ..< TeamCount:
      for verb in 0 ..< VerbCount:
        actionAuditState.aggTeamVerbCounts[teamId][verb] +=
          actionAuditState.stepTeamVerbCounts[teamId][verb]
      actionAuditState.aggTeamTotals[teamId] +=
        actionAuditState.stepTeamTotals[teamId]
    actionAuditState.aggTotal += actionAuditState.stepTotal
    inc actionAuditState.aggStepCount
    resetStepCounters()

  proc resetAggregateCounters() =
    ## Reset the counters collected for the current report window.
    for verb in 0 ..< VerbCount:
      actionAuditState.aggVerbCounts[verb] = 0
    for teamId in 0 ..< TeamCount:
      for verb in 0 ..< VerbCount:
        actionAuditState.aggTeamVerbCounts[teamId][verb] = 0
      actionAuditState.aggTeamTotals[teamId] = 0
    actionAuditState.aggTotal = 0
    actionAuditState.aggStepCount = 0

  proc fmtPct(num, denom: int): string =
    ## Format one percentage column.
    if denom == 0:
      return "  0.0%"
    let pct = num.float64 / denom.float64 * 100.0
    align(formatFloat(pct, ffDecimal, 1) & "%", 6)

  proc fmtAvg(total, steps: int): string =
    ## Format one average-per-step value.
    if steps == 0:
      return "0.0"
    formatFloat(total.float64 / steps.float64, ffDecimal, 1)

  proc printStepSummary*(currentStep: int) =
    ## Print the per-step action summary.
    ensureActionAuditInit()
    let state = actionAuditState
    echo ""
    echo(
      "--- Action Distribution — Step ",
      currentStep,
      " (",
      state.stepTotal,
      " actions) ---"
    )
    echo alignLeft("Action", 16), align("Count", 7), align("%", 7)
    for verb in 0 ..< VerbCount:
      let count = state.stepVerbCounts[verb]
      if count > 0:
        echo(
          alignLeft(VerbNames[verb], 16),
          align($count, 7),
          " ",
          fmtPct(count, state.stepTotal)
        )

    for teamId in 0 ..< TeamCount:
      if state.stepTeamTotals[teamId] == 0:
        continue
      echo(
        "  Team ",
        teamId,
        " (",
        state.stepTeamTotals[teamId],
        " actions):"
      )
      for verb in 0 ..< VerbCount:
        let count = state.stepTeamVerbCounts[teamId][verb]
        if count > 0:
          echo(
            "    ",
            alignLeft(VerbNames[verb], 14),
            align($count, 7),
            " ",
            fmtPct(count, state.stepTeamTotals[teamId])
          )

  proc printActionAuditReport*(currentStep: int) =
    ## Print the aggregate action report when the interval elapses.
    ensureActionAuditInit()
    printStepSummary(currentStep)
    flushStep()
    if actionAuditState.aggStepCount < actionAuditState.reportInterval:
      return

    let
      stepCount = actionAuditState.aggStepCount
      stepStart = currentStep - stepCount + 1
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo(
      "  ACTION AUDIT AGGREGATE — Steps ",
      stepStart,
      "-",
      currentStep,
      " (",
      stepCount,
      " steps)"
    )
    echo "═══════════════════════════════════════════════════════════"

    var busiestVerb = 0
    for verb in 1 ..< VerbCount:
      if actionAuditState.aggVerbCounts[verb] >
        actionAuditState.aggVerbCounts[busiestVerb]:
          busiestVerb = verb

    echo "  Avg actions/step: ", fmtAvg(actionAuditState.aggTotal, stepCount)
    echo(
      "  Busiest action:   ",
      VerbNames[busiestVerb],
      " (",
      fmtPct(
        actionAuditState.aggVerbCounts[busiestVerb],
        actionAuditState.aggTotal
      ),
      ")"
    )
    echo ""

    echo(
      alignLeft("Action", 16),
      align("Total", 9),
      align("Avg/step", 10),
      align("%", 7)
    )
    echo repeat("-", 42)
    for verb in 0 ..< VerbCount:
      let count = actionAuditState.aggVerbCounts[verb]
      echo(
        alignLeft(VerbNames[verb], 16),
        align($count, 9),
        align(fmtAvg(count, stepCount), 10),
        " ",
        fmtPct(count, actionAuditState.aggTotal)
      )

    echo ""
    echo "  Per-Team Summary:"
    echo(
      alignLeft("  Team", 8),
      align("Actions", 9),
      align("Avg/step", 10),
      align("Idle%", 8),
      align("Move%", 8),
      align("Attack%", 9),
      align("Build%", 8)
    )
    echo "  ", repeat("-", 58)
    for teamId in 0 ..< TeamCount:
      if actionAuditState.aggTeamTotals[teamId] == 0:
        continue

      let total = actionAuditState.aggTeamTotals[teamId]
      let idlePct =
        (
          actionAuditState.aggTeamVerbCounts[teamId][0].float64 +
          actionAuditState.aggTeamVerbCounts[teamId][9].float64
        ) / total.float64 * 100.0
      let movePct =
        actionAuditState.aggTeamVerbCounts[teamId][1].float64 /
        total.float64 * 100.0
      let attackPct =
        actionAuditState.aggTeamVerbCounts[teamId][2].float64 /
        total.float64 * 100.0
      let buildPct =
        actionAuditState.aggTeamVerbCounts[teamId][8].float64 /
        total.float64 * 100.0
      echo(
        alignLeft("  T" & $teamId, 8),
        align($total, 9),
        align(fmtAvg(total, stepCount), 10),
        align(formatFloat(idlePct, ffDecimal, 1) & "%", 8),
        align(formatFloat(movePct, ffDecimal, 1) & "%", 8),
        align(formatFloat(attackPct, ffDecimal, 1) & "%", 9),
        align(formatFloat(buildPct, ffDecimal, 1) & "%", 8)
      )

    echo "═══════════════════════════════════════════════════════════"
    echo ""

    resetAggregateCounters()
