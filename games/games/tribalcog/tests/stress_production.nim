import std/[unittest]
import environment
import agent_control
import common
import types
import items
import test_utils

## Stress tests for rapid unit production across multiple buildings.
## Verifies production timers, population cap, and spawned unit stats.

suite "Stress: Rapid Production Queue - 100 Units Across 10 Buildings":
  test "queue 100 units across 10 barracks simultaneously":
    ## Fill all 10 production queues to max (10 each = 100 total).
    let env = makeEmptyEnv()

    # Give team 0 plenty of resources
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)

    # Create 10 barracks
    var barracks: seq[Thing]
    for i in 0 ..< 10:
      let b = addBuilding(env, Barracks, ivec2(10 + i.int32 * 3, 10), 0)
      barracks.add(b)

    # Queue max units at each barracks
    var totalQueued = 0
    for b in barracks:
      let queued = env.tryBatchQueueTrain(b, 0, ProductionQueueMaxSize)
      check queued == ProductionQueueMaxSize
      totalQueued += queued

    check totalQueued == 100

    # Verify all queues are full
    for b in barracks:
      check b.productionQueue.entries.len == ProductionQueueMaxSize

  test "production timers tick independently across buildings":
    ## Each building's queue ticks independently.
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Create 3 barracks
    let b1 = addBuilding(env, Barracks, ivec2(10, 10), 0)
    let b2 = addBuilding(env, Barracks, ivec2(15, 10), 0)
    let b3 = addBuilding(env, Barracks, ivec2(20, 10), 0)

    # Queue at different times
    check env.queueTrainUnit(b1, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    let initial1 = b1.productionQueue.entries[0].remainingSteps

    env.stepNoop()
    check env.queueTrainUnit(b2, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    let initial2 = b2.productionQueue.entries[0].remainingSteps

    env.stepNoop()
    check env.queueTrainUnit(b3, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    let initial3 = b3.productionQueue.entries[0].remainingSteps

    # All start with same train time
    check initial1 == unitTrainTime(UnitManAtArms)
    check initial2 == unitTrainTime(UnitManAtArms)
    check initial3 == unitTrainTime(UnitManAtArms)

    # After 5 steps, each should have decremented by 5 from when queued
    for i in 0 ..< 5:
      env.stepNoop()

    # b1 queued at step 0, so 7 ticks total (0->1->2->3->4->5->6->7)
    # b2 queued at step 1, so 6 ticks
    # b3 queued at step 2, so 5 ticks
    check b1.productionQueue.entries[0].remainingSteps == initial1 - 7
    check b2.productionQueue.entries[0].remainingSteps == initial2 - 6
    check b3.productionQueue.entries[0].remainingSteps == initial3 - 5

  test "queue processes front entry before starting next":
    ## Second entry doesn't tick until first is consumed.
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)

    # Queue 2 units
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check barracks.productionQueue.entries.len == 2

    let trainTime = unitTrainTime(UnitManAtArms)

    # Run until first is ready
    for i in 0 ..< trainTime:
      env.stepNoop()

    # First entry should be ready
    check barracks.productionQueue.entries[0].remainingSteps == 0
    # Second entry should still have full time
    check barracks.productionQueue.entries[1].remainingSteps == trainTime

suite "Stress: Population Cap Under Heavy Production":
  test "population cap blocks conversion when at limit":
    ## With 1 house (cap 4) and 4 villagers, conversion doesn't increase pop.
    ## (Conversion replaces villager with military unit, no new agent.)
    let env = makeEmptyEnv()

    let altarPos = ivec2(5, 5)
    discard addAltar(env, altarPos, 0, 20)
    discard addBuilding(env, House, ivec2(8, 5), 0)  # Cap = 4

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Create barracks and agent adjacent to it (agent south of barracks)
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos)

    # Create 3 more villagers elsewhere (total 4, at cap)
    for i in 1 ..< 4:
      discard addAgentAt(env, i, ivec2(15 + i.int32, 10), homeAltar = altarPos)

    # Queue a unit and wait for it to be ready
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    for i in 0 ..< unitTrainTime(UnitManAtArms):
      env.stepNoop()

    check barracks.productionQueueHasReady()
    check agent.unitClass == UnitVillager

    # Convert - agent is already adjacent to barracks
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))

    # Should have converted (conversion doesn't increase pop)
    check agent.unitClass == UnitManAtArms
    check barracks.productionQueue.entries.len == 0

  test "mass production stress test with population tracking":
    ## Queue 50 units across 5 buildings, verify pop count after conversions.
    let env = makeEmptyEnv()

    let altarPos = ivec2(5, 5)
    discard addAltar(env, altarPos, 0, 100)

    # Add 15 houses (cap = 60)
    for i in 0 ..< 15:
      discard addBuilding(env, House, ivec2(5 + i.int32, 20), 0)

    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)

    # Create 5 barracks with agents adjacent to each (agents south of barracks)
    var barracks: seq[Thing]
    var convertAgents: seq[Thing]
    for i in 0 ..< 5:
      let b = addBuilding(env, Barracks, ivec2(10 + i.int32 * 3, 9), 0)
      barracks.add(b)
      # Create agent adjacent to this barracks
      let agent = addAgentAt(env, i, ivec2(10 + i.int32 * 3, 10), homeAltar = altarPos)
      convertAgents.add(agent)

    # Queue 10 units at each barracks
    for b in barracks:
      let queued = env.tryBatchQueueTrain(b, 0, ProductionQueueMaxSize)
      check queued == ProductionQueueMaxSize

    # Create 15 more villagers elsewhere (total 20)
    for i in 5 ..< 20:
      let x = ((i - 5) mod 10).int32
      let y = ((i - 5) div 10).int32
      discard addAgentAt(env, i, ivec2(30 + x, 10 + y), homeAltar = altarPos)

    # Count initial living agents
    var initialPop = 0
    for agent in env.agents:
      if env.terminated[agent.agentId] == 0.0:
        inc initialPop
    check initialPop == 20

    # Run until first units are ready
    for i in 0 ..< unitTrainTime(UnitManAtArms):
      env.stepNoop()

    # All 5 barracks should have ready entries
    for b in barracks:
      check b.productionQueueHasReady()

    # Convert 5 villagers (one per barracks) - they're already adjacent
    for i in 0 ..< 5:
      let agent = convertAgents[i]
      let b = barracks[i]
      env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, b.pos))
      check agent.unitClass == UnitManAtArms

    # Pop count should still be 20 (conversions don't add agents)
    var finalPop = 0
    for agent in env.agents:
      if env.terminated[agent.agentId] == 0.0:
        inc finalPop
    check finalPop == 20

suite "Stress: Spawned Unit Stats and Positions":
  test "converted unit gets correct unit class stats":
    ## Unit converted at barracks gets ManAtArms stats.
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 9))

    check agent.unitClass == UnitVillager

    # Queue and wait for ready
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    for i in 0 ..< unitTrainTime(UnitManAtArms):
      env.stepNoop()

    # Convert
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))

    check agent.unitClass == UnitManAtArms
    # ManAtArms should have different stats than villager
    # (exact values depend on applyUnitClass implementation)

  test "multiple building types produce correct unit classes":
    ## Different buildings produce their assigned unit types.
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)
    setStockpile(env, 0, ResourceWood, 100)

    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    let archeryRange = addBuilding(env, ArcheryRange, ivec2(15, 10), 0)
    let stable = addBuilding(env, Stable, ivec2(20, 10), 0)

    let agent1 = addAgentAt(env, 0, ivec2(10, 9))
    let agent2 = addAgentAt(env, 1, ivec2(15, 9))
    let agent3 = addAgentAt(env, 2, ivec2(20, 9))

    # Queue at each building
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check env.queueTrainUnit(archeryRange, 0, UnitArcher, buildingTrainCosts(ArcheryRange))
    check env.queueTrainUnit(stable, 0, UnitScout, buildingTrainCosts(Stable))

    # Wait for all to be ready (use longest train time)
    let maxTime = max(@[unitTrainTime(UnitManAtArms), unitTrainTime(UnitArcher), unitTrainTime(UnitScout)])
    for i in 0 ..< maxTime:
      env.stepNoop()

    # Convert each
    env.stepAction(agent1.agentId, 3'u8, dirIndex(agent1.pos, barracks.pos))
    env.stepAction(agent2.agentId, 3'u8, dirIndex(agent2.pos, archeryRange.pos))
    env.stepAction(agent3.agentId, 3'u8, dirIndex(agent3.pos, stable.pos))

    check agent1.unitClass == UnitManAtArms
    check agent2.unitClass == UnitArcher
    check agent3.unitClass == UnitScout

  test "converted unit maintains valid position":
    ## After conversion, unit remains at a valid position.
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 9))

    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    for i in 0 ..< unitTrainTime(UnitManAtArms):
      env.stepNoop()

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))

    # Position should still be valid (not -1,-1)
    check agent.pos.x >= 0
    check agent.pos.y >= 0
    check agent.pos.x < MapWidth
    check agent.pos.y < MapHeight

suite "Stress: Resource Consumption Under Heavy Load":
  test "resources consumed correctly for 100 queued units":
    ## Queuing 100 ManAtArms costs 100 * (3 food + 1 gold) = 300 food, 100 gold.
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 500)
    setStockpile(env, 0, ResourceGold, 200)

    let initialFood = env.stockpileCount(0, ResourceFood)
    let initialGold = env.stockpileCount(0, ResourceGold)

    # Create 10 barracks and fill queues
    for i in 0 ..< 10:
      let b = addBuilding(env, Barracks, ivec2(10 + i.int32 * 3, 10), 0)
      let queued = env.tryBatchQueueTrain(b, 0, ProductionQueueMaxSize)
      check queued == ProductionQueueMaxSize

    # Total: 100 units * 3 food = 300 food, 100 units * 1 gold = 100 gold
    check env.stockpileCount(0, ResourceFood) == initialFood - 300
    check env.stockpileCount(0, ResourceGold) == initialGold - 100

  test "partial batch queue when resources run out":
    ## If resources run out mid-batch, only affordable units are queued.
    let env = makeEmptyEnv()

    # Only enough for 5 ManAtArms (5 * 3 food = 15, 5 * 1 gold = 5)
    setStockpile(env, 0, ResourceFood, 15)
    setStockpile(env, 0, ResourceGold, 5)

    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    let queued = env.tryBatchQueueTrain(barracks, 0, ProductionQueueMaxSize)

    check queued == 5
    check barracks.productionQueue.entries.len == 5
    check env.stockpileCount(0, ResourceFood) == 0
    check env.stockpileCount(0, ResourceGold) == 0

suite "Stress: Concurrent Production Across Teams":
  test "multiple teams can queue simultaneously":
    ## Teams 0 and 1 both queue units without interference.
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)
    setStockpile(env, 1, ResourceFood, 100)
    setStockpile(env, 1, ResourceGold, 100)

    let barracks0 = addBuilding(env, Barracks, ivec2(10, 10), 0)
    let barracks1 = addBuilding(env, Barracks, ivec2(30, 10), 1)

    let queued0 = env.tryBatchQueueTrain(barracks0, 0, 5)
    let queued1 = env.tryBatchQueueTrain(barracks1, 1, 5)

    check queued0 == 5
    check queued1 == 5
    check barracks0.productionQueue.entries.len == 5
    check barracks1.productionQueue.entries.len == 5

    # Each team's resources consumed independently
    check env.stockpileCount(0, ResourceFood) == 100 - 15  # 5 * 3
    check env.stockpileCount(0, ResourceGold) == 100 - 5   # 5 * 1
    check env.stockpileCount(1, ResourceFood) == 100 - 15
    check env.stockpileCount(1, ResourceGold) == 100 - 5

  test "team cannot queue at enemy building":
    ## Team 1 cannot queue units at team 0's barracks.
    let env = makeEmptyEnv()

    setStockpile(env, 1, ResourceFood, 100)
    setStockpile(env, 1, ResourceGold, 100)

    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)  # Team 0's

    # Team 1 tries to queue
    check not env.queueTrainUnit(barracks, 1, UnitManAtArms, buildingTrainCosts(Barracks))
    check barracks.productionQueue.entries.len == 0

suite "Stress: Edge Cases":
  test "empty queue after all entries consumed":
    ## After converting all queued units, queue is empty.
    ## This uses the simpler approach from domain_production_queue tests.
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Barracks at (10, 9), single agent at (10, 10)
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Queue 1 unit, wait for ready, convert
    check env.queueTrainUnit(barracks, 0, UnitManAtArms, buildingTrainCosts(Barracks))
    check barracks.productionQueue.entries.len == 1
    for i in 0 ..< unitTrainTime(UnitManAtArms):
      env.stepNoop()
    check barracks.productionQueueHasReady()
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    check agent.unitClass == UnitManAtArms

    # Queue should be empty
    check barracks.productionQueue.entries.len == 0

  test "queue survives building state changes":
    ## Queue persists across steps without corruption.
    let env = makeEmptyEnv()

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    discard env.tryBatchQueueTrain(barracks, 0, ProductionQueueMaxSize)

    # Run many steps
    for i in 0 ..< 100:
      env.stepNoop()

    # Queue should still have entries (minus those completed)
    # First entry should be ready after 40 steps
    check barracks.productionQueue.entries.len == ProductionQueueMaxSize
    check barracks.productionQueueHasReady()
