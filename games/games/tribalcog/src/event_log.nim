## Human-readable event logging for selected gameplay events.

when defined(eventLog):
  import
    std/[os, strutils],
    constants

  type
    EventCategory* = enum
      ecSpawn         ## Agent spawned.
      ecDeath         ## Agent died.
      ecBuildStart    ## Building construction started.
      ecBuildDone     ## Building construction completed.
      ecBuildDestroy  ## Building destroyed.
      ecGather        ## Resource gathered.
      ecDeposit       ## Resource deposited.
      ecCombat        ## Combat hit.
      ecConversion    ## Monk conversion.
      ecResearch      ## Technology researched.
      ecTrade         ## Market trade.

    GameEvent* = object
      step*: int
      category*: EventCategory
      teamId*: int
      message*: string

    EventLogState* = object
      enabled*: bool
      filter*: set[EventCategory]
      summaryMode*: bool
      events*: seq[GameEvent]
      currentStep*: int

  const
    AllEventCategories = {
      ecSpawn, ecDeath, ecBuildStart, ecBuildDone, ecBuildDestroy,
      ecGather, ecDeposit, ecCombat, ecConversion, ecResearch, ecTrade
    }
    EventSummaryDivider = "========================"
    EventSummaryDisabledValues = ["", "0", "false"]

  var
    eventLogState*: EventLogState
    eventLogInitialized = false

  proc categoryFromString(text: string): EventCategory =
    ## Parse one event-category filter token.
    case text.toLowerAscii()
    of "spawn":
      ecSpawn
    of "death":
      ecDeath
    of "buildstart", "building_start":
      ecBuildStart
    of "builddone", "building_done", "building":
      ecBuildDone
    of "builddestroy", "building_destroy":
      ecBuildDestroy
    of "gather":
      ecGather
    of "deposit":
      ecDeposit
    of "combat", "hit":
      ecCombat
    of "conversion", "convert":
      ecConversion
    of "research", "tech":
      ecResearch
    of "trade", "market":
      ecTrade
    else:
      ecCombat

  proc parseFilter(filterText: string): set[EventCategory] =
    ## Parse the event-category filter string from the environment.
    if filterText.len == 0 or
      filterText == "*" or
      filterText.toLowerAscii() == "all":
        return AllEventCategories

    result = {}
    for part in filterText.split(','):
      let trimmed = part.strip()
      if trimmed.len > 0:
        result.incl(categoryFromString(trimmed))

  proc categoryLabel(category: EventCategory): string =
    ## Return the summary label for one event category.
    case category
    of ecSpawn:
      "Spawns"
    of ecDeath:
      "Deaths"
    of ecBuildStart:
      "Buildings Started"
    of ecBuildDone:
      "Buildings Completed"
    of ecBuildDestroy:
      "Buildings Destroyed"
    of ecGather:
      "Resources Gathered"
    of ecDeposit:
      "Resources Deposited"
    of ecCombat:
      "Combat Hits"
    of ecConversion:
      "Conversions"
    of ecResearch:
      "Tech Researched"
    of ecTrade:
      "Market Trades"

  proc initEventLog*() =
    ## Initialize event logging from environment settings.
    let
      filterText = getEnv("TV_EVENT_FILTER", "")
      summaryText = getEnv("TV_EVENT_SUMMARY", "")
    eventLogState = EventLogState(
      enabled: true,
      filter: parseFilter(filterText),
      summaryMode: summaryText notin EventSummaryDisabledValues,
      events: @[],
      currentStep: 0
    )
    eventLogInitialized = true

  proc ensureEventLogInit*() =
    ## Initialize event logging on first use.
    if not eventLogInitialized:
      initEventLog()

  proc formatEvent(event: GameEvent): string =
    ## Format one game event as a human-readable log line.
    "[Step " & $event.step & "] " &
      teamColorName(event.teamId) & " " & event.message

  proc logEvent*(
    category: EventCategory,
    teamId: int,
    message: string,
    step: int
  ) =
    ## Record or print one game event.
    ensureEventLogInit()
    if category notin eventLogState.filter:
      return

    let event = GameEvent(
      step: step,
      category: category,
      teamId: teamId,
      message: message
    )
    if eventLogState.summaryMode:
      eventLogState.events.add(event)
    else:
      echo formatEvent(event)

  proc flushEventSummary*(step: int) =
    ## Print and clear the current step summary batch.
    ensureEventLogInit()
    if not eventLogState.summaryMode or eventLogState.events.len == 0:
      return

    echo "=== Step ", step, " Events ==="
    var categoryCounts: array[EventCategory, int]
    for event in eventLogState.events:
      inc categoryCounts[event.category]
    for category in EventCategory:
      if categoryCounts[category] > 0:
        echo "  ", categoryLabel(category), ": ", categoryCounts[category]
    for event in eventLogState.events:
      echo "  ", formatEvent(event)
    echo EventSummaryDivider
    eventLogState.events.setLen(0)

  proc logCombatHit*(
    attackerTeam: int,
    targetTeam: int,
    attackerUnit: string,
    targetUnit: string,
    damage: int,
    step: int
  ) =
    ## Log one combat-hit event.
    let message =
      attackerUnit & " hit " & teamColorName(targetTeam) & " " &
      targetUnit & " for " & $damage & " damage"
    logEvent(ecCombat, attackerTeam, message, step)

  proc logConversion*(
    monkTeam: int,
    targetTeam: int,
    targetUnit: string,
    step: int
  ) =
    ## Log one monk-conversion event.
    let message =
      "Monk converted " & teamColorName(targetTeam) & " " & targetUnit
    logEvent(ecConversion, monkTeam, message, step)

  proc logTechResearched*(teamId: int, techName: string, step: int) =
    ## Log one technology research event.
    logEvent(ecResearch, teamId, "Researched " & techName, step)

  proc logMarketTrade*(
    teamId: int,
    action: string,
    resource: string,
    amount: int,
    goldAmount: int,
    step: int
  ) =
    ## Log one market trade event.
    let message =
      action & " " & $amount & " " & resource & " for " &
      $goldAmount & " gold"
    logEvent(ecTrade, teamId, message, step)
