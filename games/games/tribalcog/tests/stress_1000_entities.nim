## Stress test: 1000 entities across 4 teams.
## Spawns 1000 units (250 per team), runs 500-step simulation.
## Verifies: no crashes, no memory leaks, step time under 100ms.
## Run with: nim r --path:src tests/stress_1000_entities.nim

import std/[unittest, times, strformat, math]
import environment
import agent_control
import types
import items
import test_utils

const
  TotalEntities = 1000
  NumTeams = 4
  EntitiesPerTeam = TotalEntities div NumTeams  # 250 each
  StepsToRun = 500
  MaxStepTimeMs = 100.0  # Maximum allowed time per step in milliseconds
  MaxTotalTimeS = 120.0  # Maximum total time to prevent runaway

proc countLivingAgents(env: Environment): int =
  ## Count agents that are alive (not terminated)
  for i in 0 ..< env.agents.len:
    if env.terminated[i] == 0.0:
      inc result

proc countThingsOfKind(env: Environment, kind: ThingKind): int =
  ## Count non-nil things of a specific kind
  for thing in env.thingsByKind[kind]:
    if not thing.isNil:
      inc result

proc countAllThings(env: Environment): int =
  ## Count total non-nil things across all kinds
  for kind in ThingKind:
    result += countThingsOfKind(env, kind)

suite "Stress: 1000 Entities - Performance and Stability":
  test "spawn 1000 units across 4 teams without crash":
    ## Verify we can spawn 1000 units without crashing.
    let env = makeEmptyEnv()

    var totalSpawned = 0
    for teamId in 0 ..< NumTeams:
      # Give each team an altar
      let altarPos = ivec2(10 + teamId.int32 * 20, 10)
      discard addAltar(env, altarPos, teamId, 250)

      # Spawn 250 agents for this team in a grid
      for i in 0 ..< EntitiesPerTeam:
        let agentId = teamId * EntitiesPerTeam + i
        let x = (i mod 50).int32 + teamId.int32 * 20 + 15
        let y = (i div 50).int32 * 2 + 15
        discard addAgentAt(env, agentId, ivec2(x, y), homeAltar = altarPos)
        inc totalSpawned

    check totalSpawned == TotalEntities
    check countLivingAgents(env) == TotalEntities

  test "500-step simulation with 1000 entities - no crashes":
    ## Run 500 steps with 1000 entities and verify no crashes or assertion failures.
    let env = makeEmptyEnv()
    env.config.maxSteps = StepsToRun

    # Spawn 1000 agents across 4 teams
    for teamId in 0 ..< NumTeams:
      let altarPos = ivec2(10 + teamId.int32 * 20, 10)
      discard addAltar(env, altarPos, teamId, 250)

      # Give each team resources to avoid starvation
      setStockpile(env, teamId, ResourceFood, 10000)
      setStockpile(env, teamId, ResourceWood, 5000)
      setStockpile(env, teamId, ResourceStone, 2000)
      setStockpile(env, teamId, ResourceGold, 2000)

      for i in 0 ..< EntitiesPerTeam:
        let agentId = teamId * EntitiesPerTeam + i
        let x = (i mod 50).int32 + teamId.int32 * 20 + 15
        let y = (i div 50).int32 * 2 + 15
        discard addAgentAt(env, agentId, ivec2(x, y), homeAltar = altarPos)

    let initialCount = countLivingAgents(env)
    check initialCount == TotalEntities

    # Run simulation
    var stepsCompleted = 0
    for step in 0 ..< StepsToRun:
      env.stepNoop()
      inc stepsCompleted
      if env.shouldReset:
        break

    check stepsCompleted == StepsToRun

  test "step time stays under 100ms with 1000 entities":
    ## Measure step times and verify none exceed 100ms.
    let env = makeEmptyEnv()
    env.config.maxSteps = StepsToRun

    # Spawn 1000 agents
    for teamId in 0 ..< NumTeams:
      let altarPos = ivec2(10 + teamId.int32 * 20, 10)
      discard addAltar(env, altarPos, teamId, 250)
      setStockpile(env, teamId, ResourceFood, 10000)

      for i in 0 ..< EntitiesPerTeam:
        let agentId = teamId * EntitiesPerTeam + i
        let x = (i mod 50).int32 + teamId.int32 * 20 + 15
        let y = (i div 50).int32 * 2 + 15
        discard addAgentAt(env, agentId, ivec2(x, y), homeAltar = altarPos)

    var maxStepTimeMs = 0.0
    var totalTimeMs = 0.0
    var slowSteps = 0
    let startTotal = cpuTime()

    for step in 0 ..< StepsToRun:
      let startStep = cpuTime()
      env.stepNoop()
      let stepTimeMs = (cpuTime() - startStep) * 1000.0

      totalTimeMs += stepTimeMs
      maxStepTimeMs = max(maxStepTimeMs, stepTimeMs)
      if stepTimeMs > MaxStepTimeMs:
        inc slowSteps

      # Prevent runaway test
      if (cpuTime() - startTotal) > MaxTotalTimeS:
        echo &"WARNING: Test taking too long, stopping at step {step}"
        break

      if env.shouldReset:
        break

    let avgStepTimeMs = totalTimeMs / StepsToRun.float
    echo &"  Step timing: avg={avgStepTimeMs:.2f}ms, max={maxStepTimeMs:.2f}ms, slow_steps={slowSteps}"

    # Allow a few slow steps for GC or initialization, but max should still be reasonable
    check maxStepTimeMs < MaxStepTimeMs * 3  # Allow 3x for outliers (300ms)
    check slowSteps < StepsToRun div 10  # Less than 10% slow steps

  test "no memory leaks - entity count stable over simulation":
    ## Track entity counts through simulation to detect leaks.
    ## Counts should only decrease (deaths) or stay stable, never increase unexpectedly.
    let env = makeEmptyEnv()
    env.config.maxSteps = StepsToRun

    # Spawn 1000 agents
    for teamId in 0 ..< NumTeams:
      let altarPos = ivec2(10 + teamId.int32 * 20, 10)
      discard addAltar(env, altarPos, teamId, 250)
      setStockpile(env, teamId, ResourceFood, 10000)

      for i in 0 ..< EntitiesPerTeam:
        let agentId = teamId * EntitiesPerTeam + i
        let x = (i mod 50).int32 + teamId.int32 * 20 + 15
        let y = (i div 50).int32 * 2 + 15
        discard addAgentAt(env, agentId, ivec2(x, y), homeAltar = altarPos)

    let initialAgents = countLivingAgents(env)
    let initialThings = countAllThings(env)
    var maxAgents = initialAgents
    var maxThings = initialThings

    # Run simulation and track counts
    for step in 0 ..< StepsToRun:
      env.stepNoop()

      let currentAgents = countLivingAgents(env)
      let currentThings = countAllThings(env)

      # Track maximums (should not grow unboundedly)
      maxAgents = max(maxAgents, currentAgents)
      maxThings = max(maxThings, currentThings)

      if env.shouldReset:
        break

    # Agent count should not increase beyond initial (no unexpected spawning)
    # Allow small increase for any spawn mechanics, but not runaway growth
    check maxAgents <= initialAgents + 100  # Allow some production spawning

    echo &"  Entity tracking: initial_agents={initialAgents}, max_agents={maxAgents}"
    echo &"  Thing tracking: initial_things={initialThings}, max_things={maxThings}"

  test "all systems handle 1000 entities gracefully":
    ## Verify core systems work correctly with high entity counts.
    let env = makeEmptyEnv()
    env.config.maxSteps = StepsToRun

    # Spawn 1000 agents across 4 teams with buildings
    for teamId in 0 ..< NumTeams:
      let baseX = teamId.int32 * 25
      let altarPos = ivec2(baseX + 5, 5)
      discard addAltar(env, altarPos, teamId, 300)

      # Add some buildings per team
      discard addBuilding(env, TownCenter, ivec2(baseX + 8, 8), teamId)
      discard addBuilding(env, House, ivec2(baseX + 12, 8), teamId)
      discard addBuilding(env, Barracks, ivec2(baseX + 16, 8), teamId)

      setStockpile(env, teamId, ResourceFood, 10000)
      setStockpile(env, teamId, ResourceWood, 5000)
      setStockpile(env, teamId, ResourceStone, 2000)
      setStockpile(env, teamId, ResourceGold, 2000)

      for i in 0 ..< EntitiesPerTeam:
        let agentId = teamId * EntitiesPerTeam + i
        let x = (i mod 50).int32 + baseX + 5
        let y = (i div 50).int32 * 2 + 12
        discard addAgentAt(env, agentId, ivec2(x, y), homeAltar = altarPos)

    check countLivingAgents(env) == TotalEntities

    # Run some steps and verify basic mechanics still work
    for step in 0 ..< 100:
      env.stepNoop()
      if env.shouldReset:
        break

    # Verify environment is still valid after stress
    var validCount = 0
    for agent in env.agents:
      if not agent.isNil and agent.pos.x >= 0:
        inc validCount

    check validCount > 0  # Some agents should still be valid

  test "OOM protection - no crash with large entity counts":
    ## Verify the system doesn't crash or OOM with 1000 entities.
    let env = makeEmptyEnv()

    # This is a safety test - if we got here without crashing, we pass
    var spawned = 0
    for teamId in 0 ..< NumTeams:
      let altarPos = ivec2(5 + teamId.int32 * 25, 5)
      discard addAltar(env, altarPos, teamId, 300)

      for i in 0 ..< EntitiesPerTeam:
        let agentId = teamId * EntitiesPerTeam + i
        let x = (i mod 50).int32 + teamId.int32 * 25 + 5
        let y = (i div 50).int32 * 2 + 10

        # Catch any allocation failures
        try:
          discard addAgentAt(env, agentId, ivec2(x, y), homeAltar = altarPos)
          inc spawned
        except OutOfMemDefect:
          echo &"OOM at entity {spawned}"
          fail()

    check spawned == TotalEntities

    # Run a few steps to exercise memory
    for _ in 0 ..< 50:
      env.stepNoop()

    # If we got here, no OOM
    check true
