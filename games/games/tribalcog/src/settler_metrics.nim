## settler_metrics.nim - Per-step metrics tracking for settler migration
##
## Gated behind -d:settlerMetrics compile flag. Zero-cost when disabled.
## Tracks settlement counts, villager distribution, and migration state.
##
## Metrics are updated each step (or every N steps) to provide a real-time
## view of settlement expansion and villager distribution.

when defined(settlerMetrics):
  import std/tables
  import envconfig
  import types

  type
    SettlerMetricsState* = object
      ## Per-team building counts
      townCenterCount*: array[MapRoomObjectsTeams, int]
      altarCount*: array[MapRoomObjectsTeams, int]
      ## Villagers per altar position
      villagersPerAltar*: Table[IVec2, int]

  var settlerMetrics*: SettlerMetricsState
  var settlerMetricsInitialized = false
  var metricsUpdateInterval = 10  # Update every N steps

  proc initSettlerMetrics*() =
    settlerMetrics = SettlerMetricsState(
      villagersPerAltar: initTable[IVec2, int]()
    )
    metricsUpdateInterval = parseEnvInt("TV_SETTLER_METRICS_INTERVAL", 10)
    if metricsUpdateInterval < 1:
      metricsUpdateInterval = 1
    settlerMetricsInitialized = true

  proc ensureSettlerMetricsInit*() =
    if not settlerMetricsInitialized:
      initSettlerMetrics()

  proc updateSettlerMetrics*(env: Environment) =
    ## Recalculate settlement metrics from current game state.
    ## Call this every step or every N steps from the step loop.
    ensureSettlerMetricsInit()

    # Reset counters
    for i in 0 ..< MapRoomObjectsTeams:
      settlerMetrics.townCenterCount[i] = 0
      settlerMetrics.altarCount[i] = 0
    settlerMetrics.villagersPerAltar.clear()

    # Count town centers per team
    for thing in env.thingsByKind[TownCenter]:
      if not thing.isNil and thing.teamId >= 0 and thing.teamId < MapRoomObjectsTeams:
        inc settlerMetrics.townCenterCount[thing.teamId]

    # Count altars per team
    for thing in env.thingsByKind[Altar]:
      if not thing.isNil and thing.teamId >= 0 and thing.teamId < MapRoomObjectsTeams:
        inc settlerMetrics.altarCount[thing.teamId]

    # Count villagers per altar based on homeAltar assignments
    for agent in env.liveAgents:
      if env.terminated[agent.agentId] != 0.0:
        continue
      if agent.homeAltar.x >= 0:
        settlerMetrics.villagersPerAltar.mgetOrPut(agent.homeAltar, 0) += 1

  proc shouldUpdateMetrics*(step: int): bool =
    ensureSettlerMetricsInit()
    step mod metricsUpdateInterval == 0
