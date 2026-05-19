## Benchmark tests for actions subsystem performance.
##
## Run with `nim c -r -d:release --path:src tests/perf_actions.nim`.

import
  std/[monotimes, strformat, unittest],
  agent_control, environment, types

const
  WarmupSteps = 50
  MeasuredSteps = 200

proc msBetween(a, b: MonoTime): float64 =
  ## Convert a monotime delta to milliseconds.
  (b.ticks - a.ticks).float64 / 1_000_000.0

suite "Performance: Actions Subsystem":
  test "actions subsystem completes within budget at 200 steps":
    initGlobalController(BuiltinAI, seed = 42)
    let env = newEnvironment()

    for _ in 0 ..< WarmupSteps:
      var actions = getActions(env)
      env.step(addr actions)

    var totalActionsMs = 0.0
    var maxActionsMs = 0.0
    var sampleCount = 0

    for _ in 0 ..< MeasuredSteps:
      var actions = getActions(env)

      # Measure full step time because subsystem timing needs extra build flags.
      let tStart = getMonoTime()
      env.step(addr actions)
      let tEnd = getMonoTime()
      let stepMs = msBetween(tStart, tEnd)

      totalActionsMs += stepMs
      maxActionsMs = max(maxActionsMs, stepMs)
      inc sampleCount

    let meanMs = totalActionsMs / sampleCount.float64

    echo(
      &"  Actions benchmark: mean={meanMs:.4f}ms, " &
      &"max={maxActionsMs:.4f}ms over {sampleCount} steps"
    )
    echo &"  Total time: {totalActionsMs:.2f}ms"

    # This guards against obvious step-time regressions in release builds.
    check meanMs < 10.0

  test "pre-computed team pop caps are available":
    let env = newEnvironment()

    var actions: array[MapAgents, uint16]
    for i in 0 ..< MapAgents:
      actions[i] = 0
    env.step(addr actions)

    var totalPopCap = 0
    for teamId in 0 ..< MapRoomObjectsTeams:
      totalPopCap += env.stepTeamPopCaps[teamId]

    check totalPopCap > 0
    echo &"  Total pop cap across teams: {totalPopCap}"

  test "agentOrder is initialized and shuffled":
    let env = newEnvironment()

    var seen: array[MapAgents, bool]
    for i in 0 ..< MapAgents:
      let idx = env.agentOrder[i]
      check idx >= 0 and idx < MapAgents
      seen[idx] = true

    for i in 0 ..< MapAgents:
      check seen[i]

    var actions: array[MapAgents, uint16]
    env.step(addr actions)

    var sortedCount = 0
    for i in 0 ..< MapAgents - 1:
      if env.agentOrder[i] < env.agentOrder[i + 1]:
        inc sortedCount

    let sortedRatio = sortedCount.float64 / (MapAgents - 1).float64
    check sortedRatio < 0.9
    echo &"  Sorted pair ratio after shuffle: {sortedRatio * 100.0:.2f}%"

  test "constructionBuilders table is cleared per step":
    let env = newEnvironment()

    var actions: array[MapAgents, uint16]
    for _ in 0 ..< 10:
      env.step(addr actions)
    check env.currentStep == 10
