import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import registry
import test_utils

suite "Production Queue - Basic Queuing":
  test "queue single unit at barracks":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 3)
    setStockpile(env, 0, ResourceGold, 1)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    check barracks.productionQueue.entries.len == 1
    check barracks.productionQueue.entries[0].unitClass == UnitManAtArms
    # Resources spent immediately on queue
    check env.stockpileCount(0, ResourceFood) == 0
    check env.stockpileCount(0, ResourceGold) == 0

  test "queue countdown ticks each step":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 3)
    setStockpile(env, 0, ResourceGold, 1)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    let initialRemaining = barracks.productionQueue.entries[0].remainingSteps
    check initialRemaining == unitTrainTime(UnitManAtArms) - 1  # One tick from the step

    env.stepNoop()
    check barracks.productionQueue.entries[0].remainingSteps == initialRemaining - 1

  test "ready queue entry converts villager on USE":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 3)
    setStockpile(env, 0, ResourceGold, 1)

    # Queue and wait for completion
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    for i in 0 ..< unitTrainTime(UnitManAtArms) - 1:
      env.stepNoop()
    check barracks.productionQueue.entries[0].remainingSteps == 0

    # Convert
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    check agent.unitClass == UnitManAtArms
    check barracks.productionQueue.entries.len == 0

  test "queue respects max size":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Fill queue to max
    for i in 0 ..< ProductionQueueMaxSize:
      check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))

    # One more should fail
    check not env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check barracks.productionQueue.entries.len == ProductionQueueMaxSize

  test "queue fails when insufficient resources":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    # No resources set

    check not env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check barracks.productionQueue.entries.len == 0

  test "queue fails for wrong team":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)  # Team 0 building
    setStockpile(env, 1, ResourceFood, 10)
    setStockpile(env, 1, ResourceGold, 10)

    check not env.queueTrainUnit(barracks, 1, UnitManAtArms, buildingTrainCosts(Barracks))

suite "Production Queue - Cancel":
  test "cancel last queued entry refunds resources":
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

  test "cancel on empty queue returns false":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    check not env.cancelLastQueued(barracks)

  test "cancel removes last entry not first":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check barracks.productionQueue.entries.len == 2

    check env.cancelLastQueued(barracks)
    check barracks.productionQueue.entries.len == 1
    # First entry still there

suite "Production Queue - Batch Training":
  test "batch queue multiple units":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 15)
    setStockpile(env, 0, ResourceGold, 5)

    let queued = env.tryBatchQueueTrain(barracks, 0, BatchTrainSmall)
    check queued == BatchTrainSmall
    check barracks.productionQueue.entries.len == BatchTrainSmall

  test "batch queue stops when resources run out":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    # Only enough for 2 units (each costs 3 food + 1 gold)
    setStockpile(env, 0, ResourceFood, 6)
    setStockpile(env, 0, ResourceGold, 2)

    let queued = env.tryBatchQueueTrain(barracks, 0, BatchTrainSmall)
    check queued == 2
    check barracks.productionQueue.entries.len == 2

  test "batch queue stops at max queue size":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)

    # Try to queue more than max
    let queued = env.tryBatchQueueTrain(barracks, 0, ProductionQueueMaxSize + 5)
    check queued == ProductionQueueMaxSize
    check barracks.productionQueue.entries.len == ProductionQueueMaxSize

  test "batch queue returns 0 for non-training building":
    let env = makeEmptyEnv()
    let mill = addBuilding(env, Mill, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 100)

    let queued = env.tryBatchQueueTrain(mill, 0, 5)
    check queued == 0

suite "Production Queue - Multiple Buildings":
  test "different buildings have independent queues":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let archeryRange = addBuilding(env, ArcheryRange, ivec2(12, 9), 0)
    setStockpile(env, 0, ResourceFood, 10)
    setStockpile(env, 0, ResourceGold, 10)
    setStockpile(env, 0, ResourceWood, 10)

    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.queueTrainUnit(archeryRange, 0, UnitArcher, buildingTrainCosts(ArcheryRange))

    check barracks.productionQueue.entries.len == 1
    check barracks.productionQueue.entries[0].unitClass == UnitManAtArms
    check archeryRange.productionQueue.entries.len == 1
    check archeryRange.productionQueue.entries[0].unitClass == UnitArcher

suite "Production Queue - Queue Count Display":
  test "queue length reflects pending units":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 30)
    setStockpile(env, 0, ResourceGold, 10)

    check barracks.productionQueue.entries.len == 0

    discard env.tryBatchQueueTrain(barracks, 0, 3)
    check barracks.productionQueue.entries.len == 3

    discard env.cancelLastQueued(barracks)
    check barracks.productionQueue.entries.len == 2
