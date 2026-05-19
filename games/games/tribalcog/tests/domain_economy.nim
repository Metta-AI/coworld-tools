import std/unittest
import environment
import agent_control
import types
import items
import test_utils

# Note: Economy types and procs are included via agent_control
# which includes ai_defaults.nim which includes economy.nim

# Helper to initialize agent in controller by calling decideAction
proc initControllerAgent(controller: Controller, env: Environment, agentId: int, role: AgentRole = Gatherer) =
  # Call decideAction to trigger lazy initialization
  discard controller.decideAction(env, agentId)
  # Set the role directly
  controller.agents[agentId].role = role

suite "Economy - Resource Snapshots":
  test "recordSnapshot stores resource levels":
    resetEconomy()
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceWood, 50)
    setStockpile(env, 0, ResourceStone, 25)
    setStockpile(env, 0, ResourceGold, 10)
    env.currentStep = 100

    recordSnapshot(0, env)

    check teamEconomy[0].snapshotCount == 1
    check teamEconomy[0].snapshots[0].food == 100
    check teamEconomy[0].snapshots[0].wood == 50
    check teamEconomy[0].snapshots[0].stone == 25
    check teamEconomy[0].snapshots[0].gold == 10
    check teamEconomy[0].snapshots[0].step == 100

  test "recordSnapshot uses circular buffer":
    resetEconomy()
    let env = makeEmptyEnv()

    # Fill buffer beyond capacity
    for i in 0 ..< EconomyTrackingWindow + 10:
      setStockpile(env, 0, ResourceFood, i)
      env.currentStep = i
      recordSnapshot(0, env)

    # Should cap at EconomyTrackingWindow
    check teamEconomy[0].snapshotCount == EconomyTrackingWindow

  test "recordSnapshot handles invalid team":
    resetEconomy()
    let env = makeEmptyEnv()
    recordSnapshot(-1, env)  # Should not crash
    recordSnapshot(MapRoomObjectsTeams, env)  # Should not crash

suite "Economy - Flow Rate Calculation":
  test "calculateFlowRate computes resource change per step":
    resetEconomy()
    let env = makeEmptyEnv()

    # First snapshot at step 0
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceWood, 50)
    env.currentStep = 0
    recordSnapshot(0, env)

    # Second snapshot at step 10 with more resources
    setStockpile(env, 0, ResourceFood, 120)  # +20 over 10 steps = 2.0 per step
    setStockpile(env, 0, ResourceWood, 40)   # -10 over 10 steps = -1.0 per step
    env.currentStep = 10
    recordSnapshot(0, env)

    let flow = calculateFlowRate(0)
    check flow.foodPerStep > 1.9 and flow.foodPerStep < 2.1
    check flow.woodPerStep > -1.1 and flow.woodPerStep < -0.9

  test "calculateFlowRate returns zero with insufficient snapshots":
    resetEconomy()
    let flow = calculateFlowRate(0)
    check flow.foodPerStep == 0.0
    check flow.woodPerStep == 0.0

  test "calculateFlowRate handles same step snapshots":
    resetEconomy()
    let env = makeEmptyEnv()
    env.currentStep = 100

    # Two snapshots at same step
    recordSnapshot(0, env)
    recordSnapshot(0, env)

    let flow = calculateFlowRate(0)
    check flow.foodPerStep == 0.0  # Should handle division by zero

  test "updateFlowRate caches the result":
    resetEconomy()
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 100)
    env.currentStep = 0
    recordSnapshot(0, env)

    setStockpile(env, 0, ResourceFood, 150)
    env.currentStep = 50
    recordSnapshot(0, env)

    updateFlowRate(0)
    let cached = getFlowRate(0)
    check cached.foodPerStep == 1.0  # (150-100)/50

suite "Economy - Worker Counting":
  test "countWorkers counts by role":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    # Add agents and initialize them via decideAction
    discard addAgentAt(env, 0, ivec2(10, 10))
    discard addAgentAt(env, 1, ivec2(11, 10))
    discard addAgentAt(env, 2, ivec2(12, 10))
    discard addAgentAt(env, 3, ivec2(13, 10))

    # Initialize controller state and set roles
    initControllerAgent(controller, env, 0, Gatherer)
    initControllerAgent(controller, env, 1, Gatherer)
    initControllerAgent(controller, env, 2, Builder)
    initControllerAgent(controller, env, 3, Fighter)

    let counts = countWorkers(controller, env, 0)
    check counts.total == 4
    check counts.gatherers == 2
    check counts.builders == 1
    check counts.fighters == 1

  test "countWorkers ignores dead agents":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    discard addAgentAt(env, 0, ivec2(10, 10))
    let dead = addAgentAt(env, 1, ivec2(11, 10))
    # Mark agent as terminated (isAgentAlive checks env.terminated)
    env.terminated[dead.agentId] = 1.0

    initControllerAgent(controller, env, 0)
    # Don't initialize dead agent - it won't be counted anyway

    let counts = countWorkers(controller, env, 0)
    check counts.total == 1

  test "countWorkers separates teams":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    # Team 0 agent
    discard addAgentAt(env, 0, ivec2(10, 10))
    initControllerAgent(controller, env, 0)

    # Team 1 agent (agent IDs >= MapAgentsPerTeam are on team 1)
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    initControllerAgent(controller, env, MapAgentsPerTeam)

    let counts0 = countWorkers(controller, env, 0)
    let counts1 = countWorkers(controller, env, 1)
    check counts0.total == 1
    check counts1.total == 1

suite "Economy - Bottleneck Detection":
  test "detectBottleneck returns FoodCritical when food low":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    discard addAgentAt(env, 0, ivec2(10, 10))
    initControllerAgent(controller, env, 0)

    setStockpile(env, 0, ResourceFood, CriticalFoodLevel - 1)
    setStockpile(env, 0, ResourceWood, 100)

    let bottleneck = detectBottleneck(controller, env, 0)
    check bottleneck == FoodCritical

  test "detectBottleneck returns WoodCritical when wood low":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    discard addAgentAt(env, 0, ivec2(10, 10))
    initControllerAgent(controller, env, 0)

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceWood, CriticalWoodLevel - 1)

    let bottleneck = detectBottleneck(controller, env, 0)
    check bottleneck == WoodCritical

  test "detectBottleneck returns TooFewFighters when enemies present":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    # Add 10 gatherers for team 0
    for i in 0 ..< 10:
      discard addAgentAt(env, i, ivec2(10 + i.int32, 10))
      initControllerAgent(controller, env, i, Gatherer)

    # No fighters assigned, all are gatherers by default

    # Add enemy from team 1
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(30, 30))

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceWood, 100)

    let bottleneck = detectBottleneck(controller, env, 0)
    check bottleneck == TooFewFighters

  test "detectBottleneck returns TooManyGatherers":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    # Add 10 agents, all gatherers (> 70%)
    for i in 0 ..< 10:
      discard addAgentAt(env, i, ivec2(10 + i.int32, 10))
      initControllerAgent(controller, env, i, Gatherer)

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceWood, 100)

    let bottleneck = detectBottleneck(controller, env, 0)
    check bottleneck == TooManyGatherers

  test "detectBottleneck returns NoBottleneck when balanced":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    # Add 10 agents with balanced roles
    # 5 gatherers (50%), 3 builders (30%), 2 fighters (20%)
    for i in 0 ..< 5:
      discard addAgentAt(env, i, ivec2(10 + i.int32, 10))
      initControllerAgent(controller, env, i, Gatherer)
    for i in 5 ..< 8:
      discard addAgentAt(env, i, ivec2(10 + i.int32, 11))
      initControllerAgent(controller, env, i, Builder)
    for i in 8 ..< 10:
      discard addAgentAt(env, i, ivec2(10 + i.int32, 12))
      initControllerAgent(controller, env, i, Fighter)

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceWood, 100)

    let bottleneck = detectBottleneck(controller, env, 0)
    check bottleneck == NoBottleneck

  test "detectBottleneck handles invalid team":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    check detectBottleneck(controller, env, -1) == NoBottleneck
    check detectBottleneck(controller, env, MapRoomObjectsTeams) == NoBottleneck

suite "Economy - Update Integration":
  test "updateEconomy records snapshots periodically":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    discard addAgentAt(env, 0, ivec2(10, 10))
    initControllerAgent(controller, env, 0)

    setStockpile(env, 0, ResourceFood, 100)

    # Step 0 - should record (0 mod 5 == 0)
    env.currentStep = 0
    updateEconomy(controller, env, 0)
    check teamEconomy[0].snapshotCount == 1

    # Step 3 - should not record
    env.currentStep = 3
    updateEconomy(controller, env, 0)
    check teamEconomy[0].snapshotCount == 1

    # Step 5 - should record
    env.currentStep = 5
    updateEconomy(controller, env, 0)
    check teamEconomy[0].snapshotCount == 2

  test "updateEconomy updates flow rate periodically":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    discard addAgentAt(env, 0, ivec2(10, 10))
    initControllerAgent(controller, env, 0)

    setStockpile(env, 0, ResourceFood, 100)
    env.currentStep = 0
    updateEconomy(controller, env, 0)

    setStockpile(env, 0, ResourceFood, 150)
    env.currentStep = 10
    updateEconomy(controller, env, 0)

    let flow = getFlowRate(0)
    check flow.foodPerStep == 5.0  # (150-100)/10

  test "updateEconomy updates bottleneck state":
    resetEconomy()
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    discard addAgentAt(env, 0, ivec2(10, 10))
    initControllerAgent(controller, env, 0)

    setStockpile(env, 0, ResourceFood, 1)  # Critical
    setStockpile(env, 0, ResourceWood, 100)
    env.currentStep = 0
    updateEconomy(controller, env, 0)

    check getCurrentBottleneck(0) == FoodCritical

  test "resetEconomy clears all state":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    env.currentStep = 100
    recordSnapshot(0, env)

    check teamEconomy[0].snapshotCount > 0

    resetEconomy()

    check teamEconomy[0].snapshotCount == 0
    check teamEconomy[0].snapshotIndex == 0
    check teamEconomy[0].currentBottleneck == NoBottleneck
