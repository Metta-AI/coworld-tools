import std/[unittest]
import environment
import common
import types
import test_utils

suite "Rally Point - Set Rally Point":
  test "set rally point on adjacent friendly building":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Agent at (10,10), barracks at (10,9) -> direction N (index 0)
    env.stepAction(agent.agentId, 10'u8, dirIndex(agent.pos, barracks.pos))
    check barracks.hasRallyPoint()
    check barracks.rallyPoint == agent.pos

  test "set rally point fails on empty tile":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    env.stepAction(agent.agentId, 10'u8, 0)  # Direction N, no building there
    # No crash, action is just invalid

  test "set rally point fails on enemy building":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 1)  # Team 1 building
    let agent = addAgentAt(env, 0, ivec2(10, 10))  # Team 0 agent

    env.stepAction(agent.agentId, 10'u8, dirIndex(agent.pos, barracks.pos))
    check not barracks.hasRallyPoint()

  test "rally point can be updated":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(10, 8))  # Team 0, north of barracks

    # Set first rally point from agent1
    env.stepAction(agent1.agentId, 10'u8, dirIndex(agent1.pos, barracks.pos))
    check barracks.rallyPoint == ivec2(10, 10)

    # Set new rally point from agent2 (north of barracks)
    env.stepAction(agent2.agentId, 10'u8, dirIndex(agent2.pos, barracks.pos))
    check barracks.rallyPoint == ivec2(10, 8)

suite "Rally Point - Trained Unit Rally":
  test "trained unit receives rally target from building":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 3)
    setStockpile(env, 0, ResourceGold, 1)

    # Set rally point on barracks
    barracks.setRallyPoint(ivec2(15, 15))

    # Queue and wait for training (unitTrainTime ticks via processProductionQueue each step)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    for i in 0 ..< unitTrainTime(UnitManAtArms) - 1:
      env.stepNoop()

    # Convert villager - should get rally target
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    check agent.unitClass == UnitManAtArms
    check agent.rallyTarget == ivec2(15, 15)

  test "trained unit has no rally target when building has no rally point":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 3)
    setStockpile(env, 0, ResourceGold, 1)

    # Queue and wait for training (no rally point set)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    for i in 0 ..< unitTrainTime(UnitManAtArms) - 1:
      env.stepNoop()

    # Convert villager - should have no rally target
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    check agent.unitClass == UnitManAtArms
    # Default rallyTarget is (-1,-1) - no rally point assigned
    check agent.rallyTarget.x == -1
    check agent.rallyTarget.y == -1

suite "Rally Point - Building Helpers":
  test "hasRallyPoint returns false for default":
    let building = Thing(kind: Barracks, pos: ivec2(10, 10))
    # Default IVec2 is (0,0), which is a valid position
    # Only negative coordinates mean "no rally point"
    building.rallyPoint = ivec2(-1, -1)
    check not building.hasRallyPoint()

  test "hasRallyPoint returns true after setting":
    let building = Thing(kind: Barracks, pos: ivec2(10, 10))
    building.setRallyPoint(ivec2(15, 15))
    check building.hasRallyPoint()
    check building.rallyPoint == ivec2(15, 15)

  test "clearRallyPoint removes rally point":
    let building = Thing(kind: Barracks, pos: ivec2(10, 10))
    building.setRallyPoint(ivec2(15, 15))
    check building.hasRallyPoint()
    building.clearRallyPoint()
    check not building.hasRallyPoint()
