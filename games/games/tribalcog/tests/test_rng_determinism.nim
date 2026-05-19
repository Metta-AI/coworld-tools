## RNG determinism tests verifying that identical replay seeds produce
## identical game states across multiple simulation runs.
##
## Tests three levels of determinism:
## 1. Map generation (covered by test_map_determinism.nim)
## 2. Full simulation with NOOP actions - SHOULD PASS (core sim is deterministic)
## 3. Full simulation with AI controller - MAY FAIL (see note below)
## 4. Replay with recorded actions - SHOULD PASS (validates simulation determinism)
##
## NOTE: If AI controller tests fail, this indicates non-determinism in the
## AI decision-making code (ai_core, ai_defaults), NOT in the core simulation.
## The simulation itself is deterministic when given identical action sequences.

import std/[unittest, strformat, hashes, strutils]
import environment
import agent_control
import types
import terrain
import items
import test_utils

const
  TestSeeds = [42, 137, 256, 777, 9999]
  RunsPerSeed = 3
  StepsPerRun = 100
  CheckpointSteps = [10, 25, 50, 75, 100]

type
  GameStateSnapshot = object
    step: int
    thingCount: int
    agentPosHash: uint64
    agentHpHash: uint64
    agentInventoryHash: uint64
    stockpileHash: uint64
    terrainModHash: uint64

proc hashAgentPositions(env: Environment): uint64 =
  ## Hash all agent positions for comparison
  for agent in env.agents:
    if agent.hp > 0:
      result = result xor hash((agent.agentId, agent.pos.x, agent.pos.y)).uint64

proc hashAgentHp(env: Environment): uint64 =
  ## Hash all agent HP values
  for agent in env.agents:
    result = result xor hash((agent.agentId, agent.hp)).uint64

proc hashAgentInventories(env: Environment): uint64 =
  ## Hash agent inventory states
  for agent in env.agents:
    if agent.hp > 0:
      for itemKind in ItemKind:
        let count = agent.inventory.items[itemKind]
        if count > 0:
          result = result xor hash((agent.agentId, itemKind.int, count.int)).uint64

proc hashStockpiles(env: Environment): uint64 =
  ## Hash team stockpile resources
  for teamId in 0 ..< MapRoomObjectsTeams:
    let stockpile = env.teamStockpiles[teamId]
    for res in StockpileResource:
      result = result xor hash((teamId, res.int, stockpile.counts[res])).uint64

proc hashTerrainMods(env: Environment): uint64 =
  ## Hash terrain modifications (from tumors, buildings, etc.)
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      if env.terrain[x][y] != TerrainEmpty:
        result = result xor hash((x, y, env.terrain[x][y].int)).uint64

proc takeGameSnapshot(env: Environment): GameStateSnapshot =
  result.step = env.currentStep
  result.thingCount = env.things.len
  result.agentPosHash = hashAgentPositions(env)
  result.agentHpHash = hashAgentHp(env)
  result.agentInventoryHash = hashAgentInventories(env)
  result.stockpileHash = hashStockpiles(env)
  result.terrainModHash = hashTerrainMods(env)

proc `==`(a, b: GameStateSnapshot): bool =
  a.step == b.step and
  a.thingCount == b.thingCount and
  a.agentPosHash == b.agentPosHash and
  a.agentHpHash == b.agentHpHash and
  a.agentInventoryHash == b.agentInventoryHash and
  a.stockpileHash == b.stockpileHash and
  a.terrainModHash == b.terrainModHash

proc snapshotDiff(a, b: GameStateSnapshot): string =
  ## Return human-readable diff of two snapshots
  var diffs: seq[string]
  if a.step != b.step:
    diffs.add(&"step: {a.step} vs {b.step}")
  if a.thingCount != b.thingCount:
    diffs.add(&"thingCount: {a.thingCount} vs {b.thingCount}")
  if a.agentPosHash != b.agentPosHash:
    diffs.add(&"agentPosHash: {a.agentPosHash} vs {b.agentPosHash}")
  if a.agentHpHash != b.agentHpHash:
    diffs.add(&"agentHpHash: {a.agentHpHash} vs {b.agentHpHash}")
  if a.agentInventoryHash != b.agentInventoryHash:
    diffs.add(&"agentInventoryHash: {a.agentInventoryHash} vs {b.agentInventoryHash}")
  if a.stockpileHash != b.stockpileHash:
    diffs.add(&"stockpileHash: {a.stockpileHash} vs {b.stockpileHash}")
  if a.terrainModHash != b.terrainModHash:
    diffs.add(&"terrainModHash: {a.terrainModHash} vs {b.terrainModHash}")
  if diffs.len == 0:
    "identical"
  else:
    diffs.join(", ")

proc computeAllActions(controller: Controller, env: Environment): array[MapAgents, uint16] =
  ## Compute actions for all agents using the given controller
  for i in 0 ..< env.agents.len:
    result[i] = controller.decideAction(env, i)
  controller.updateController(env)

suite "RNG Determinism: NOOP Actions":
  test "same seed produces identical game states with NOOP actions":
    for seed in TestSeeds:
      var config = defaultEnvironmentConfig()
      config.maxSteps = StepsPerRun
      config.victoryCondition = VictoryNone

      # Reference run
      let refEnv = newEnvironment(config, seed)
      var refSnapshots: seq[GameStateSnapshot]
      var noopActions: array[MapAgents, uint16]

      for step in 1 .. StepsPerRun:
        refEnv.step(addr noopActions)
        if refEnv.shouldReset:
          break
        if step in CheckpointSteps:
          refSnapshots.add(takeGameSnapshot(refEnv))

      # Comparison runs
      for run in 1 ..< RunsPerSeed:
        let env = newEnvironment(config, seed)
        var snapIdx = 0
        for step in 1 .. StepsPerRun:
          env.step(addr noopActions)
          if env.shouldReset:
            break
          if step in CheckpointSteps:
            let snap = takeGameSnapshot(env)
            if snapIdx < refSnapshots.len:
              check snap == refSnapshots[snapIdx]
              if snap != refSnapshots[snapIdx]:
                echo &"  MISMATCH at seed {seed}, step {step}, run {run}: {snapshotDiff(refSnapshots[snapIdx], snap)}"
            inc snapIdx

      echo &"  Seed {seed}: {RunsPerSeed} runs identical at {CheckpointSteps.len} checkpoints"

  test "different seeds produce different game states after simulation":
    var config = defaultEnvironmentConfig()
    config.maxSteps = StepsPerRun
    config.victoryCondition = VictoryNone

    var finalSnapshots: seq[(int, GameStateSnapshot)]
    var noopActions: array[MapAgents, uint16]

    for seed in TestSeeds:
      let env = newEnvironment(config, seed)
      for step in 1 .. StepsPerRun:
        env.step(addr noopActions)
        if env.shouldReset:
          break
      finalSnapshots.add((seed, takeGameSnapshot(env)))

    # At least some seed pairs should differ
    var diffCount = 0
    let totalPairs = finalSnapshots.len * (finalSnapshots.len - 1) div 2
    for i in 0 ..< finalSnapshots.len:
      for j in (i + 1) ..< finalSnapshots.len:
        if finalSnapshots[i][1] != finalSnapshots[j][1]:
          inc diffCount

    check diffCount > 0
    echo &"  {diffCount}/{totalPairs} seed pairs differ after {StepsPerRun} steps"

suite "RNG Determinism: AI Controller":
  test "same seed produces identical game states with AI controller":
    for seed in TestSeeds:
      var config = defaultEnvironmentConfig()
      config.maxSteps = StepsPerRun
      config.victoryCondition = VictoryNone

      # Reference run with deterministic AI
      let refEnv = newEnvironment(config, seed)
      let refController = newTestController(seed)
      var refSnapshots: seq[GameStateSnapshot]

      for step in 1 .. StepsPerRun:
        var actions: array[MapAgents, uint16]
        actions = computeAllActions(refController, refEnv)
        refEnv.step(addr actions)
        if refEnv.shouldReset:
          break
        if step in CheckpointSteps:
          refSnapshots.add(takeGameSnapshot(refEnv))

      # Comparison runs with same seed
      for run in 1 ..< RunsPerSeed:
        let env = newEnvironment(config, seed)
        let controller = newTestController(seed)
        var snapIdx = 0

        for step in 1 .. StepsPerRun:
          var actions: array[MapAgents, uint16]
          actions = computeAllActions(controller, env)
          env.step(addr actions)
          if env.shouldReset:
            break
          if step in CheckpointSteps:
            let snap = takeGameSnapshot(env)
            if snapIdx < refSnapshots.len:
              check snap == refSnapshots[snapIdx]
              if snap != refSnapshots[snapIdx]:
                echo &"  AI MISMATCH at seed {seed}, step {step}, run {run}: {snapshotDiff(refSnapshots[snapIdx], snap)}"
            inc snapIdx

      echo &"  Seed {seed}: AI {RunsPerSeed} runs identical at {CheckpointSteps.len} checkpoints"

  test "AI produces different outcomes with different seeds":
    var config = defaultEnvironmentConfig()
    config.maxSteps = StepsPerRun
    config.victoryCondition = VictoryNone

    var finalSnapshots: seq[(int, GameStateSnapshot)]

    for seed in TestSeeds:
      let env = newEnvironment(config, seed)
      let controller = newTestController(seed)

      for step in 1 .. StepsPerRun:
        var actions: array[MapAgents, uint16]
        actions = computeAllActions(controller, env)
        env.step(addr actions)
        if env.shouldReset:
          break
      finalSnapshots.add((seed, takeGameSnapshot(env)))

    var diffCount = 0
    let totalPairs = finalSnapshots.len * (finalSnapshots.len - 1) div 2
    for i in 0 ..< finalSnapshots.len:
      for j in (i + 1) ..< finalSnapshots.len:
        if finalSnapshots[i][1] != finalSnapshots[j][1]:
          inc diffCount

    check diffCount > 0
    echo &"  AI: {diffCount}/{totalPairs} seed pairs differ after {StepsPerRun} steps"

suite "RNG Determinism: Independent Environment and Controller Seeds":
  test "same env seed with different controller seeds produces different games":
    let envSeed = 42
    let controllerSeeds = [100, 200, 300]

    var config = defaultEnvironmentConfig()
    config.maxSteps = StepsPerRun
    config.victoryCondition = VictoryNone

    var finalSnapshots: seq[GameStateSnapshot]

    for ctrlSeed in controllerSeeds:
      let env = newEnvironment(config, envSeed)
      let controller = newTestController(ctrlSeed)

      for step in 1 .. StepsPerRun:
        var actions: array[MapAgents, uint16]
        actions = computeAllActions(controller, env)
        env.step(addr actions)
        if env.shouldReset:
          break
      finalSnapshots.add(takeGameSnapshot(env))

    # Different controller seeds should produce different outcomes
    var diffCount = 0
    for i in 0 ..< finalSnapshots.len:
      for j in (i + 1) ..< finalSnapshots.len:
        if finalSnapshots[i] != finalSnapshots[j]:
          inc diffCount

    check diffCount > 0
    echo &"  Same env seed {envSeed}, different controller seeds: {diffCount} pairs differ"

  test "different env seed with same controller seed produces different games":
    let controllerSeed = 42
    let envSeeds = [100, 200, 300]

    var config = defaultEnvironmentConfig()
    config.maxSteps = StepsPerRun
    config.victoryCondition = VictoryNone

    var finalSnapshots: seq[GameStateSnapshot]

    for envSeed in envSeeds:
      let env = newEnvironment(config, envSeed)
      let controller = newTestController(controllerSeed)

      for step in 1 .. StepsPerRun:
        var actions: array[MapAgents, uint16]
        actions = computeAllActions(controller, env)
        env.step(addr actions)
        if env.shouldReset:
          break
      finalSnapshots.add(takeGameSnapshot(env))

    # Different env seeds should produce different outcomes
    var diffCount = 0
    for i in 0 ..< finalSnapshots.len:
      for j in (i + 1) ..< finalSnapshots.len:
        if finalSnapshots[i] != finalSnapshots[j]:
          inc diffCount

    check diffCount > 0
    echo &"  Different env seeds with same controller seed {controllerSeed}: {diffCount} pairs differ"

suite "RNG Determinism: Replay Seed Reproducibility":
  test "game can be replayed from seed with identical action sequence":
    for seed in TestSeeds:
      var config = defaultEnvironmentConfig()
      config.maxSteps = StepsPerRun
      config.victoryCondition = VictoryNone

      # Initial run: record all actions taken
      let env1 = newEnvironment(config, seed)
      let controller = newTestController(seed)
      var recordedActions: seq[array[MapAgents, uint16]]

      for step in 1 .. StepsPerRun:
        var actions: array[MapAgents, uint16]
        actions = computeAllActions(controller, env1)
        recordedActions.add(actions)
        env1.step(addr actions)
        if env1.shouldReset:
          break

      let finalSnap1 = takeGameSnapshot(env1)

      # Replay run: use recorded actions with same seed
      let env2 = newEnvironment(config, seed)
      for i, actions in recordedActions:
        var actionsVar = actions
        env2.step(addr actionsVar)
        if env2.shouldReset:
          break

      let finalSnap2 = takeGameSnapshot(env2)

      check finalSnap1 == finalSnap2
      if finalSnap1 != finalSnap2:
        echo &"  Seed {seed} replay mismatch: {snapshotDiff(finalSnap1, finalSnap2)}"
      else:
        echo &"  Seed {seed}: replay from recorded actions matches original"
