## Tick helpers and optional timing utilities for step.nim.

when defined(rewardBatch):
  import std/monotimes

  const
    RewardBatchReportInterval = 500

  var
    rewardBatchOps = 0
    rewardBatchCumMs = 0.0
    rewardBatchSteps = 0

  proc rewardBatchMsBetween(a, b: MonoTime): float64 =
    ## Convert two monotonic timestamps into elapsed milliseconds.
    (b.ticks - a.ticks).float64 / 1_000_000.0

  proc reportRewardBatch() =
    ## Print the aggregated reward-batch timing report.
    if rewardBatchSteps == 0:
      return

    let
      avgOps = rewardBatchOps.float64 / rewardBatchSteps.float64
      avgMs = rewardBatchCumMs / rewardBatchSteps.float64
    echo(
      "[rewardBatch] steps=", rewardBatchSteps,
      " avgOps/step=", avgOps,
      " avgMs/step=", avgMs
    )
    rewardBatchOps = 0
    rewardBatchCumMs = 0.0
    rewardBatchSteps = 0

when defined(stepTiming):
  import std/monotimes

  const
    TimingSystemCount = 11
    TimingSystemNames: array[TimingSystemCount, string] = [
      "actionTint", "shields", "preDeaths", "actions", "things",
      "tumors", "tumorDamage", "auras", "popRespawn", "survival",
      "tintObs"
    ]

  let
    stepTimingTarget = parseEnvInt("TV_STEP_TIMING", -1)
    stepTimingWindow = parseEnvInt("TV_STEP_TIMING_WINDOW", 0)
    stepTimingInterval = parseEnvInt("TV_TIMING_INTERVAL", 100)

  var
    timingCumSum: array[TimingSystemCount, float64]
    timingCumMax: array[TimingSystemCount, float64]
    timingCumTotal = 0.0
    timingStepCount = 0

  proc msBetween(a, b: MonoTime): float64 =
    ## Convert two monotonic timestamps into elapsed milliseconds.
    (b.ticks - a.ticks).float64 / 1_000_000.0

  proc resetTimingCounters() =
    ## Reset the aggregated step-timing counters.
    for i in 0 ..< TimingSystemCount:
      timingCumSum[i] = 0.0
      timingCumMax[i] = 0.0
    timingCumTotal = 0.0
    timingStepCount = 0

  proc recordTimingSample(idx: int, ms: float64) =
    ## Record one subsystem timing sample.
    timingCumSum[idx] += ms
    if ms > timingCumMax[idx]:
      timingCumMax[idx] = ms

  proc printTimingReport(currentStep: int) =
    ## Print the aggregated step-timing report.
    if timingStepCount == 0:
      return

    let
      stepCount = timingStepCount.float64
      firstStep = currentStep - timingStepCount + 1
    echo ""
    echo(
      "=== Step Timing Report (steps ", firstStep, "-", currentStep,
      ", n=", timingStepCount, ") ==="
    )
    echo(
      align("System", 14), " | ",
      align("Avg ms", 10), " | ",
      align("Max ms", 10), " | ",
      align("% Total", 8)
    )
    echo(
      repeat("-", 14), "-+-",
      repeat("-", 10), "-+-",
      repeat("-", 10), "-+-",
      repeat("-", 8)
    )
    for i in 0 ..< TimingSystemCount:
      let
        avg = timingCumSum[i] / stepCount
        maxMs = timingCumMax[i]
        pct =
          if timingCumTotal > 0.0:
            timingCumSum[i] / timingCumTotal * 100.0
          else:
            0.0
      echo(
        align(TimingSystemNames[i], 14), " | ",
        align(formatFloat(avg, ffDecimal, 4), 10), " | ",
        align(formatFloat(maxMs, ffDecimal, 4), 10), " | ",
        align(formatFloat(pct, ffDecimal, 1), 8)
      )
    let totalAvg = timingCumTotal / stepCount
    echo(
      repeat("-", 14), "-+-",
      repeat("-", 10), "-+-",
      repeat("-", 10), "-+-",
      repeat("-", 8)
    )
    echo(
      align("TOTAL", 14), " | ",
      align(formatFloat(totalAvg, ffDecimal, 4), 10), " | ",
      align("", 10), " | ",
      align("100.0", 8)
    )
    echo ""
    resetTimingCounters()

when defined(perfRegression):
  include "perf_regression"

  proc msBetweenPerfTiming(a, b: MonoTime): float64 =
    ## Convert two monotonic timestamps into elapsed milliseconds.
    (b.ticks - a.ticks).float64 / 1_000_000.0

when defined(flameGraph):
  include "flame_graph"

proc stepApplySurvivalPenalty(env: Environment) =
  ## Apply the per-step survival penalty to all living agents.
  if env.config.survivalPenalty == 0.0:
    return

  let penalty = env.config.survivalPenalty
  when defined(rewardBatch):
    # Apply the penalty to contiguous rewards for SIMD-friendly access.
    for i in 0 ..< MapAgents:
      if env.terminated[i] == 0.0 and env.truncated[i] == 0.0:
        env.rewards[i] += penalty
  else:
    for agent in env.agents:
      if isAgentAlive(env, agent):
        env.rewards[agent.agentId] += penalty

proc isOutOfBounds(pos: IVec2): bool {.inline.} =
  ## Return whether the position is outside the playable map area.
  pos.x < MapBorder.int32 or
    pos.x >= (MapWidth - MapBorder).int32 or
    pos.y < MapBorder.int32 or
    pos.y >= (MapHeight - MapBorder).int32

proc applyFertileRadius(env: Environment, center: IVec2, radius: int) =
  ## Apply fertile terrain in a Chebyshev radius around the center.
  for dx in -radius .. radius:
    for dy in -radius .. radius:
      if dx == 0 and dy == 0:
        continue
      if max(abs(dx), abs(dy)) > radius:
        continue

      let pos = center + ivec2(dx.int32, dy.int32)
      if not isValidPos(pos):
        continue
      if not env.isEmpty(pos) or
        env.hasDoor(pos) or
        isBlockedTerrain(env.terrain[pos.x][pos.y]) or
        isTileFrozen(pos, env):
          continue

      let terrain = env.terrain[pos.x][pos.y]
      if terrain notin BuildableTerrain:
        continue
      env.terrain[pos.x][pos.y] = Fertile
      env.resetTileColor(pos)
      env.updateObservations(ThingAgentLayer, pos, 0)

proc findAdjacentFriendlyBuilding*(
  env: Environment,
  pos: IVec2,
  teamId: int,
  kindPredicate: proc(k: ThingKind): bool
): Thing =
  ## Find an adjacent building of the given kind for the given team.
  for dy in -1 .. 1:
    for dx in -1 .. 1:
      let checkPos = pos + ivec2(dx.int32, dy.int32)
      if not isValidPos(checkPos):
        continue
      let building = env.getThing(checkPos)
      if not building.isNil and
        kindPredicate(building.kind) and
        building.teamId == teamId:
          return building
  nil

# `isGarrisonableBuilding` and `isTownCenterKind` are defined later in
# `step.nim` after `building_combat.nim` because they depend on
# `garrisonCapacity`.
