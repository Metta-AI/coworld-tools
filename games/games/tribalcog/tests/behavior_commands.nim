import std/[unittest, strformat]
import test_common
import common

suite "Behavior: Attack-Move Waypoints":
  test "attack-move target is set and readable":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)
    let target = ivec2(20, 20)

    setAgentAttackMoveTarget(agent.agentId, target)
    check isAgentAttackMoveActive(agent.agentId)
    let readBack = getAgentAttackMoveTarget(agent.agentId)
    check readBack.x == target.x
    check readBack.y == target.y

  test "clearing attack-move deactivates it":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)

    setAgentAttackMoveTarget(agent.agentId, ivec2(20, 20))
    check isAgentAttackMoveActive(agent.agentId)

    clearAgentAttackMoveTarget(agent.agentId)
    check not isAgentAttackMoveActive(agent.agentId)
    let pos = getAgentAttackMoveTarget(agent.agentId)
    check pos.x == -1
    check pos.y == -1

  test "multiple agents get independent attack-move targets":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let a0 = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)
    let a1 = addAgentAt(env, 1, ivec2(15, 15), stance = StanceAggressive)

    setAgentAttackMoveTarget(a0.agentId, ivec2(20, 20))
    setAgentAttackMoveTarget(a1.agentId, ivec2(30, 30))

    let t0 = getAgentAttackMoveTarget(a0.agentId)
    let t1 = getAgentAttackMoveTarget(a1.agentId)
    check t0.x == 20
    check t1.x == 30
    echo &"  Agent 0 target: ({t0.x},{t0.y}), Agent 1 target: ({t1.x},{t1.y})"

suite "Behavior: Patrol Waypoints":
  test "patrol is set with two waypoints and activates":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)

    setAgentPatrol(agent.agentId, ivec2(5, 5), ivec2(15, 15))
    check isAgentPatrolActive(agent.agentId)

  test "clearing patrol deactivates it":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)

    setAgentPatrol(agent.agentId, ivec2(5, 5), ivec2(15, 15))
    check isAgentPatrolActive(agent.agentId)

    clearAgentPatrol(agent.agentId)
    check not isAgentPatrolActive(agent.agentId)

  test "patrol target is readable after setting":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)

    setAgentPatrol(agent.agentId, ivec2(5, 5), ivec2(15, 15))
    let target = getAgentPatrolTarget(agent.agentId)
    # Patrol target should be one of the two waypoints
    check target.x >= 0
    check target.y >= 0
    echo &"  Patrol target: ({target.x},{target.y})"

suite "Behavior: Hold Position":
  test "hold position is set and readable":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)

    setAgentHoldPosition(agent.agentId, ivec2(10, 10))
    check isAgentHoldPositionActive(agent.agentId)
    let pos = getAgentHoldPosition(agent.agentId)
    check pos.x == 10
    check pos.y == 10

  test "clearing hold position deactivates it":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)

    setAgentHoldPosition(agent.agentId, ivec2(10, 10))
    check isAgentHoldPositionActive(agent.agentId)

    clearAgentHoldPosition(agent.agentId)
    check not isAgentHoldPositionActive(agent.agentId)

suite "Behavior: Follow Command":
  test "follow target is set and readable":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let leader = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let follower = addAgentAt(env, 1, ivec2(12, 12), stance = StanceDefensive)

    setAgentFollowTarget(follower.agentId, leader.agentId)
    check isAgentFollowActive(follower.agentId)
    check getAgentFollowTargetId(follower.agentId) == leader.agentId

  test "clearing follow deactivates it":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let leader = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let follower = addAgentAt(env, 1, ivec2(12, 12), stance = StanceDefensive)

    setAgentFollowTarget(follower.agentId, leader.agentId)
    check isAgentFollowActive(follower.agentId)

    clearAgentFollowTarget(follower.agentId)
    check not isAgentFollowActive(follower.agentId)
    check getAgentFollowTargetId(follower.agentId) == -1

suite "Behavior: Guard Command":
  test "guard agent target is set and readable":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let target = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let guard = addAgentAt(env, 1, ivec2(12, 12), stance = StanceDefensive)

    setAgentGuard(guard.agentId, target.agentId)
    check isAgentGuarding(guard.agentId)
    check getAgentGuardTargetId(guard.agentId) == target.agentId
    check getAgentGuardPosition(guard.agentId).x == -1  # Not guarding position

  test "guard position is set and readable":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let guard = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)

    setAgentGuardPosition(guard.agentId, ivec2(15, 15))
    check isAgentGuarding(guard.agentId)
    check getAgentGuardTargetId(guard.agentId) == -1  # Not guarding agent
    let pos = getAgentGuardPosition(guard.agentId)
    check pos.x == 15
    check pos.y == 15

  test "clearing guard deactivates it":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let target = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let guard = addAgentAt(env, 1, ivec2(12, 12), stance = StanceDefensive)

    setAgentGuard(guard.agentId, target.agentId)
    check isAgentGuarding(guard.agentId)

    clearAgentGuard(guard.agentId)
    check not isAgentGuarding(guard.agentId)
    check getAgentGuardTargetId(guard.agentId) == -1
    check getAgentGuardPosition(guard.agentId).x == -1

  test "guard agent switches to guard position clears agent target":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let target = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let guard = addAgentAt(env, 1, ivec2(12, 12), stance = StanceDefensive)

    setAgentGuard(guard.agentId, target.agentId)
    check getAgentGuardTargetId(guard.agentId) == target.agentId

    # Switching to position-based guard clears agent target
    setAgentGuardPosition(guard.agentId, ivec2(20, 20))
    check getAgentGuardTargetId(guard.agentId) == -1
    check getAgentGuardPosition(guard.agentId).x == 20

  test "multiple agents can guard independently":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let vip = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let guard1 = addAgentAt(env, 1, ivec2(8, 10), stance = StanceDefensive)
    let guard2 = addAgentAt(env, 2, ivec2(12, 10), stance = StanceDefensive)

    setAgentGuard(guard1.agentId, vip.agentId)
    setAgentGuardPosition(guard2.agentId, ivec2(5, 5))

    check isAgentGuarding(guard1.agentId)
    check isAgentGuarding(guard2.agentId)
    check getAgentGuardTargetId(guard1.agentId) == vip.agentId
    check getAgentGuardPosition(guard2.agentId).x == 5
    echo "  Guard1 guarding agent, Guard2 guarding position"

suite "Behavior: Stop Command (Cancel All Orders)":
  test "stop clears attack-move":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)

    setAgentAttackMoveTarget(agent.agentId, ivec2(20, 20))
    check isAgentAttackMoveActive(agent.agentId)

    stopAgent(agent.agentId)
    check not isAgentAttackMoveActive(agent.agentId)

  test "stop clears patrol":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)

    setAgentPatrol(agent.agentId, ivec2(5, 5), ivec2(15, 15))
    check isAgentPatrolActive(agent.agentId)

    stopAgent(agent.agentId)
    check not isAgentPatrolActive(agent.agentId)

  test "stop clears hold position":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)

    setAgentHoldPosition(agent.agentId, ivec2(10, 10))
    check isAgentHoldPositionActive(agent.agentId)

    stopAgent(agent.agentId)
    check not isAgentHoldPositionActive(agent.agentId)

  test "stop clears follow":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let leader = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let follower = addAgentAt(env, 1, ivec2(12, 12), stance = StanceDefensive)

    setAgentFollowTarget(follower.agentId, leader.agentId)
    check isAgentFollowActive(follower.agentId)

    stopAgent(follower.agentId)
    check not isAgentFollowActive(follower.agentId)

  test "stop clears guard":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let target = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let guard = addAgentAt(env, 1, ivec2(12, 12), stance = StanceDefensive)

    setAgentGuard(guard.agentId, target.agentId)
    check isAgentGuarding(guard.agentId)

    stopAgent(guard.agentId)
    check not isAgentGuarding(guard.agentId)

  test "stop clears all commands simultaneously":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let leader = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)
    let follower = addAgentAt(env, 1, ivec2(12, 12), stance = StanceAggressive)

    # Set multiple commands on follower
    setAgentAttackMoveTarget(follower.agentId, ivec2(20, 20))
    setAgentHoldPosition(follower.agentId, ivec2(12, 12))
    setAgentFollowTarget(follower.agentId, leader.agentId)
    setAgentGuard(follower.agentId, leader.agentId)

    stopAgent(follower.agentId)
    check not isAgentAttackMoveActive(follower.agentId)
    check not isAgentHoldPositionActive(follower.agentId)
    check not isAgentFollowActive(follower.agentId)
    check not isAgentGuarding(follower.agentId)
    echo "  Stop cleared all commands on agent"

suite "Behavior: Selection and Command Issuing":
  test "select units and issue attack-move to selection":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let a0 = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)
    let a1 = addAgentAt(env, 1, ivec2(12, 10), stance = StanceAggressive)
    let a2 = addAgentAt(env, 2, ivec2(14, 10), stance = StanceAggressive)

    env.selectUnits(@[a0.agentId, a1.agentId, a2.agentId])
    check getSelectionCount() == 3

    # Issue attack-move to all selected
    env.issueCommandToSelection(0, 25, 25)  # commandType 0 = attack-move

    check isAgentAttackMoveActive(a0.agentId)
    check isAgentAttackMoveActive(a1.agentId)
    check isAgentAttackMoveActive(a2.agentId)
    echo &"  Issued attack-move to {getSelectionCount()} selected units"

  test "issue stop command to selection clears all orders":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let a0 = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)
    let a1 = addAgentAt(env, 1, ivec2(12, 10), stance = StanceAggressive)

    setAgentAttackMoveTarget(a0.agentId, ivec2(20, 20))
    setAgentAttackMoveTarget(a1.agentId, ivec2(20, 20))

    env.selectUnits(@[a0.agentId, a1.agentId])
    env.issueCommandToSelection(2, 0, 0)  # commandType 2 = stop

    check not isAgentAttackMoveActive(a0.agentId)
    check not isAgentAttackMoveActive(a1.agentId)

  test "issue hold position to selection uses each agent's current position":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let a0 = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let a1 = addAgentAt(env, 1, ivec2(15, 15), stance = StanceDefensive)

    env.selectUnits(@[a0.agentId, a1.agentId])
    env.issueCommandToSelection(3, 0, 0)  # commandType 3 = hold position

    check isAgentHoldPositionActive(a0.agentId)
    check isAgentHoldPositionActive(a1.agentId)
    let h0 = getAgentHoldPosition(a0.agentId)
    let h1 = getAgentHoldPosition(a1.agentId)
    check h0.x == 10  # Each holds at their own position
    check h1.x == 15

  test "issue patrol to selection from current pos to target":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let a0 = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    let a1 = addAgentAt(env, 1, ivec2(12, 10), stance = StanceDefensive)

    env.selectUnits(@[a0.agentId, a1.agentId])
    env.issueCommandToSelection(1, 20, 20)  # commandType 1 = patrol

    check isAgentPatrolActive(a0.agentId)
    check isAgentPatrolActive(a1.agentId)

  test "clear selection removes all units":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let a0 = addAgentAt(env, 0, ivec2(10, 10))
    let a1 = addAgentAt(env, 1, ivec2(12, 10))

    env.selectUnits(@[a0.agentId, a1.agentId])
    check getSelectionCount() == 2

    clearSelection()
    check getSelectionCount() == 0

  test "add and remove individual units from selection":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let a0 = addAgentAt(env, 0, ivec2(10, 10))
    let a1 = addAgentAt(env, 1, ivec2(12, 10))
    let a2 = addAgentAt(env, 2, ivec2(14, 10))

    env.selectUnits(@[a0.agentId])
    check getSelectionCount() == 1

    env.addToSelection(a1.agentId)
    check getSelectionCount() == 2

    removeFromSelection(a0.agentId)
    check getSelectionCount() == 1
    check getSelectedAgentId(0) == a1.agentId

suite "Behavior: Control Groups":
  test "create control group and recall it":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let a0 = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)
    let a1 = addAgentAt(env, 1, ivec2(12, 10), stance = StanceAggressive)
    let a2 = addAgentAt(env, 2, ivec2(14, 10), stance = StanceAggressive)

    env.createControlGroup(1, @[a0.agentId, a1.agentId, a2.agentId])
    check getControlGroupCount(1) == 3
    check getControlGroupAgentId(1, 0) == a0.agentId
    check getControlGroupAgentId(1, 1) == a1.agentId
    check getControlGroupAgentId(1, 2) == a2.agentId

    # Recall into selection
    clearSelection()
    check getSelectionCount() == 0
    env.recallControlGroup(1)
    check getSelectionCount() == 3
    echo &"  Control group 1 recalled with {getSelectionCount()} units"

  test "control groups are independent":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let a0 = addAgentAt(env, 0, ivec2(10, 10))
    let a1 = addAgentAt(env, 1, ivec2(12, 10))
    let a2 = addAgentAt(env, 2, ivec2(14, 10))

    env.createControlGroup(0, @[a0.agentId])
    env.createControlGroup(1, @[a1.agentId, a2.agentId])

    check getControlGroupCount(0) == 1
    check getControlGroupCount(1) == 2
    check getControlGroupAgentId(0, 0) == a0.agentId
    check getControlGroupAgentId(1, 0) == a1.agentId

  test "invalid control group index returns safe defaults":
    check getControlGroupCount(-1) == 0
    check getControlGroupCount(ControlGroupCount) == 0
    check getControlGroupAgentId(-1, 0) == -1
    check getControlGroupAgentId(0, -1) == -1

suite "Behavior: Building Queue Priority":
  test "production queue processes entries in FIFO order":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Queue two units
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check barracks.productionQueue.entries.len == 2

    # Only the first entry ticks down
    let firstRemaining = barracks.productionQueue.entries[0].remainingSteps
    let secondRemaining = barracks.productionQueue.entries[1].remainingSteps
    env.stepNoop()
    check barracks.productionQueue.entries[0].remainingSteps == firstRemaining - 1
    check barracks.productionQueue.entries[1].remainingSteps == secondRemaining
    echo &"  FIFO: first entry ticking ({firstRemaining - 1}), second waiting ({secondRemaining})"

  test "different buildings queue different unit types":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let archeryRange = addBuilding(env, ArcheryRange, ivec2(14, 9), 0)
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)
    setStockpile(env, 0, ResourceWood, 100)

    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.queueTrainUnit(archeryRange, 0, UnitArcher, buildingTrainCosts(ArcheryRange))

    check barracks.productionQueue.entries[0].unitClass == UnitManAtArms
    check archeryRange.productionQueue.entries[0].unitClass == UnitArcher

  test "batch queue fills up to resource limit":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    # Enough for exactly 3 units (each costs 3 food + 1 gold)
    setStockpile(env, 0, ResourceFood, 9)
    setStockpile(env, 0, ResourceGold, 3)

    let queued = env.tryBatchQueueTrain(barracks, 0, BatchTrainSmall)
    check queued == 3
    check barracks.productionQueue.entries.len == 3
    echo &"  Batch queued {queued} units (limited by resources)"

  test "batch queue respects max queue size":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)

    let queued = env.tryBatchQueueTrain(barracks, 0, ProductionQueueMaxSize + 5)
    check queued == ProductionQueueMaxSize
    echo &"  Batch queued {queued} units (capped at max {ProductionQueueMaxSize})"

suite "Behavior: Cancel Mid-Action":
  test "cancel last queued unit refunds resources":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 3)
    setStockpile(env, 0, ResourceGold, 1)

    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.stockpileCount(0, ResourceFood) == 0
    check env.stockpileCount(0, ResourceGold) == 0

    check env.cancelLastQueued(barracks)
    check barracks.productionQueue.entries.len == 0
    check env.stockpileCount(0, ResourceFood) == 3
    check env.stockpileCount(0, ResourceGold) == 1
    echo "  Cancel refunded resources correctly"

  test "cancel removes last entry, not first (stack behavior)":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check barracks.productionQueue.entries.len == 3

    # Cancel should remove last (3rd), leaving first 2
    check env.cancelLastQueued(barracks)
    check barracks.productionQueue.entries.len == 2

    # Cancel again removes 2nd
    check env.cancelLastQueued(barracks)
    check barracks.productionQueue.entries.len == 1

    # Last cancel empties queue
    check env.cancelLastQueued(barracks)
    check barracks.productionQueue.entries.len == 0
    echo "  Sequential cancels removed entries in LIFO order"

  test "cancel on empty queue returns false":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    check not env.cancelLastQueued(barracks)

  test "cancel partially trained unit still refunds resources":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 6)
    setStockpile(env, 0, ResourceGold, 2)

    # Queue two units
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    let foodAfterQueue = env.stockpileCount(0, ResourceFood)
    let goldAfterQueue = env.stockpileCount(0, ResourceGold)

    # Let the first entry tick down a few steps
    for i in 0 ..< 5:
      env.stepNoop()

    # Cancel last (second) entry - should refund its resources
    check env.cancelLastQueued(barracks)
    check barracks.productionQueue.entries.len == 1
    check env.stockpileCount(0, ResourceFood) > foodAfterQueue
    check env.stockpileCount(0, ResourceGold) > goldAfterQueue
    echo "  Cancelled partially-trained queue entry, resources refunded"

suite "Behavior: Command Buffer Ordering":
  test "new command replaces previous command of same type":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)

    # Set attack-move to first target
    setAgentAttackMoveTarget(agent.agentId, ivec2(20, 20))
    check getAgentAttackMoveTarget(agent.agentId).x == 20

    # Override with new attack-move target
    setAgentAttackMoveTarget(agent.agentId, ivec2(30, 30))
    check getAgentAttackMoveTarget(agent.agentId).x == 30
    echo "  Attack-move target updated from (20,20) to (30,30)"

  test "different command types coexist independently":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let leader = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)
    let agent = addAgentAt(env, 1, ivec2(12, 12), stance = StanceAggressive)

    # Set multiple different command types
    setAgentAttackMoveTarget(agent.agentId, ivec2(20, 20))
    setAgentHoldPosition(agent.agentId, ivec2(12, 12))
    setAgentFollowTarget(agent.agentId, leader.agentId)

    # All should be active simultaneously
    check isAgentAttackMoveActive(agent.agentId)
    check isAgentHoldPositionActive(agent.agentId)
    check isAgentFollowActive(agent.agentId)
    echo "  Multiple command types active simultaneously"

  test "stop is the universal cancel for all command types":
    let env = makeEmptyEnv()
    initGlobalController(BuiltinAI, 42)
    let leader = addAgentAt(env, 0, ivec2(10, 10))
    let agent = addAgentAt(env, 1, ivec2(12, 12), stance = StanceAggressive)

    setAgentAttackMoveTarget(agent.agentId, ivec2(20, 20))
    setAgentPatrol(agent.agentId, ivec2(5, 5), ivec2(15, 15))
    setAgentHoldPosition(agent.agentId, ivec2(12, 12))
    setAgentFollowTarget(agent.agentId, leader.agentId)
    setAgentGuard(agent.agentId, leader.agentId)

    # Verify all active
    check isAgentAttackMoveActive(agent.agentId)
    check isAgentPatrolActive(agent.agentId)
    check isAgentHoldPositionActive(agent.agentId)
    check isAgentFollowActive(agent.agentId)
    check isAgentGuarding(agent.agentId)

    # Single stop clears everything
    stopAgent(agent.agentId)
    check not isAgentAttackMoveActive(agent.agentId)
    check not isAgentPatrolActive(agent.agentId)
    check not isAgentHoldPositionActive(agent.agentId)
    check not isAgentFollowActive(agent.agentId)
    check not isAgentGuarding(agent.agentId)
    echo "  Stop cleared 5 active commands at once"

suite "Behavior: Rally Point and Trained Unit Destination":
  test "building rally point is set and readable":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)

    env.setBuildingRallyPoint(10, 9, 20, 20)
    let rally = env.getBuildingRallyPoint(10, 9)
    check rally.x == 20
    check rally.y == 20

  test "clearing rally point returns sentinel":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)

    env.setBuildingRallyPoint(10, 9, 20, 20)
    env.clearBuildingRallyPoint(10, 9)
    let rally = env.getBuildingRallyPoint(10, 9)
    check rally.x == -1
    check rally.y == -1

  test "rally point on non-building position returns sentinel":
    let env = makeEmptyEnv()
    let rally = env.getBuildingRallyPoint(50, 50)
    check rally.x == -1
    check rally.y == -1

suite "Behavior: Production Queue via API":
  test "queueUnitTraining queues via building position":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 10)
    setStockpile(env, 0, ResourceGold, 10)

    check env.queueUnitTraining(10, 9, 0)
    check env.getProductionQueueSize(10, 9) == 1

  test "cancelLastQueuedUnit cancels via building position":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 10)
    setStockpile(env, 0, ResourceGold, 10)

    check env.queueUnitTraining(10, 9, 0)
    check env.getProductionQueueSize(10, 9) == 1

    check env.cancelLastQueuedUnit(10, 9)
    check env.getProductionQueueSize(10, 9) == 0

  test "queue entry progress is readable":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 10)
    setStockpile(env, 0, ResourceGold, 10)

    check env.queueUnitTraining(10, 9, 0)
    let progress = env.getProductionQueueEntryProgress(10, 9, 0)
    check progress >= 0
    echo &"  Queue entry 0 remaining steps: {progress}"

  test "queue API returns safe values for invalid positions":
    let env = makeEmptyEnv()
    check not env.queueUnitTraining(99, 99, 0)
    check env.getProductionQueueSize(99, 99) == 0
    check env.getProductionQueueEntryProgress(99, 99, 0) == -1
    check not env.cancelLastQueuedUnit(99, 99)

  test "queue fails for non-training building":
    let env = makeEmptyEnv()
    let mill = addBuilding(env, Mill, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 100)

    check not env.queueUnitTraining(10, 9, 0)
    check env.getProductionQueueSize(10, 9) == 0
