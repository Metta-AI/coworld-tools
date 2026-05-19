import std/[unittest]
import environment
import agent_control
import common
import types
import items
import test_utils

suite "Agent Control - Stance (env-based)":
  test "set and get agent stance":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addAgentAt(0, ivec2(50, 50))
    env.setAgentStance(0, StanceAggressive)
    check env.getAgentStance(0) == StanceAggressive

  test "stance for dead agent returns StanceDefensive":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addAgentAt(0, ivec2(50, 50))
    env.terminated[0] = 1.0
    check env.getAgentStance(0) == StanceDefensive

  test "set stance on invalid agent id is safe":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    env.setAgentStance(999, StanceAggressive)
    check env.getAgentStance(999) == StanceDefensive

suite "Agent Control - Garrison (env-based)":
  test "garrison agent in building":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(GuardTower, ivec2(50, 50), 0)
    let agent = env.addAgentAt(0, ivec2(49, 50))
    let success = env.garrisonAgentInBuilding(0, 50, 50)
    check success == true
    check agent.isGarrisoned == true
    check agent.pos == ivec2(-1, -1)
    check env.getGarrisonCount(50, 50) == 1
    check env.isAgentGarrisoned(0) == true

  test "ungarrison all from building":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(GuardTower, ivec2(50, 50), 0)
    let agent = env.addAgentAt(0, ivec2(49, 50))
    discard env.garrisonAgentInBuilding(0, 50, 50)
    check env.isAgentGarrisoned(0) == true
    let count = env.ungarrisonAllFromBuilding(50, 50)
    check count == 1
    check env.isAgentGarrisoned(0) == false
    check env.getGarrisonCount(50, 50) == 0

  test "garrison at invalid position returns false":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addAgentAt(0, ivec2(50, 50))
    check env.garrisonAgentInBuilding(0, -1, -1) == false

  test "garrison at non-building returns false":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addAgentAt(0, ivec2(50, 50))
    check env.garrisonAgentInBuilding(0, 51, 50) == false

  test "garrison count at empty position is 0":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    check env.getGarrisonCount(50, 50) == 0

suite "Agent Control - Production Queue":
  test "queue unit training at barracks":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(Barracks, ivec2(50, 50), 0)
    env.setStockpile(0, ResourceFood, 100)
    env.setStockpile(0, ResourceGold, 100)
    let success = env.queueUnitTraining(50, 50, 0)
    check success == true
    check env.getProductionQueueSize(50, 50) == 1

  test "cancel last queued unit":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(Barracks, ivec2(50, 50), 0)
    env.setStockpile(0, ResourceFood, 100)
    env.setStockpile(0, ResourceGold, 100)
    discard env.queueUnitTraining(50, 50, 0)
    check env.getProductionQueueSize(50, 50) == 1
    let cancelled = env.cancelLastQueuedUnit(50, 50)
    check cancelled == true
    check env.getProductionQueueSize(50, 50) == 0

  test "queue at invalid position returns false":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    check env.queueUnitTraining(-1, -1, 0) == false

  test "queue at non-trainable building returns false":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(Wall, ivec2(50, 50), 0)
    check env.queueUnitTraining(50, 50, 0) == false

  test "production queue size at empty position is 0":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    check env.getProductionQueueSize(50, 50) == 0

  test "cancel all training queue":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(Barracks, ivec2(50, 50), 0)
    env.setStockpile(0, ResourceFood, 100)
    env.setStockpile(0, ResourceGold, 100)
    discard env.queueUnitTraining(50, 50, 0)
    discard env.queueUnitTraining(50, 50, 0)
    check env.getProductionQueueSize(50, 50) == 2
    let count = env.cancelAllTrainingQueue(50, 50)
    check count == 2
    check env.getProductionQueueSize(50, 50) == 0

  test "queue entry unit class for barracks is ManAtArms":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(Barracks, ivec2(50, 50), 0)
    env.setStockpile(0, ResourceFood, 100)
    env.setStockpile(0, ResourceGold, 100)
    discard env.queueUnitTraining(50, 50, 0)
    check env.getProductionQueueEntryUnitClass(50, 50, 0) == ord(UnitManAtArms).int32

  test "canBuildingTrainUnit validates unit class":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(Barracks, ivec2(50, 50), 0)
    check env.canBuildingTrainUnit(50, 50, ord(UnitManAtArms).int32, 0) == true
    check env.canBuildingTrainUnit(50, 50, ord(UnitArcher).int32, 0) == false

  test "isProductionQueueReady initially false":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(Barracks, ivec2(50, 50), 0)
    check env.isProductionQueueReady(50, 50) == false

suite "Agent Control - Rally Points":
  test "set and get building rally point":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(Barracks, ivec2(50, 50), 0)
    env.setBuildingRallyPoint(50, 50, 55, 55)
    let rally = env.getBuildingRallyPoint(50, 50)
    check rally == ivec2(55, 55)

  test "clear building rally point":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    discard env.addBuilding(Barracks, ivec2(50, 50), 0)
    env.setBuildingRallyPoint(50, 50, 55, 55)
    env.clearBuildingRallyPoint(50, 50)
    let rally = env.getBuildingRallyPoint(50, 50)
    check rally == ivec2(-1, -1)

  test "rally point at empty position returns (-1, -1)":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    check env.getBuildingRallyPoint(50, 50) == ivec2(-1, -1)

  test "rally point at invalid position returns (-1, -1)":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    check env.getBuildingRallyPoint(-1, -1) == ivec2(-1, -1)

suite "Agent Control - Global Controller APIs":
  test "attack-move target set and get":
    initGlobalController(BuiltinAI, 42)
    setAgentAttackMoveTarget(0, ivec2(60, 60))
    check isAgentAttackMoveActive(0) == true
    check getAgentAttackMoveTarget(0) == ivec2(60, 60)
    clearAgentAttackMoveTarget(0)
    check isAgentAttackMoveActive(0) == false

  test "patrol set and check":
    initGlobalController(BuiltinAI, 42)
    setAgentPatrol(0, ivec2(40, 40), ivec2(60, 60))
    check isAgentPatrolActive(0) == true
    clearAgentPatrol(0)
    check isAgentPatrolActive(0) == false

  test "hold position set and check":
    initGlobalController(BuiltinAI, 42)
    setAgentHoldPosition(0, ivec2(50, 50))
    check isAgentHoldPositionActive(0) == true
    check getAgentHoldPosition(0) == ivec2(50, 50)
    clearAgentHoldPosition(0)
    check isAgentHoldPositionActive(0) == false

  test "follow target set and check":
    initGlobalController(BuiltinAI, 42)
    setAgentFollowTarget(0, 1)
    check isAgentFollowActive(0) == true
    check getAgentFollowTargetId(0) == 1
    clearAgentFollowTarget(0)
    check isAgentFollowActive(0) == false

  test "guard agent set and check":
    initGlobalController(BuiltinAI, 42)
    setAgentGuard(0, 1)
    check isAgentGuarding(0) == true
    check getAgentGuardTargetId(0) == 1
    clearAgentGuard(0)
    check isAgentGuarding(0) == false

  test "guard position set and check":
    initGlobalController(BuiltinAI, 42)
    setAgentGuardPosition(0, ivec2(50, 50))
    check isAgentGuarding(0) == true
    check getAgentGuardPosition(0) == ivec2(50, 50)
    clearAgentGuard(0)
    check isAgentGuarding(0) == false

  test "stop agent set and check":
    initGlobalController(BuiltinAI, 42)
    stopAgent(0)
    check isAgentStopped(0) == true
    clearAgentStop(0)
    check isAgentStopped(0) == false

  test "scout mode set and check":
    initGlobalController(BuiltinAI, 42)
    setAgentScoutMode(0, true)
    check isAgentScoutModeActive(0) == true
    setAgentScoutMode(0, false)
    check isAgentScoutModeActive(0) == false

  test "stance deferred set and get":
    initGlobalController(BuiltinAI, 42)
    setAgentStance(0, StanceAggressive)
    check getAgentStance(0) == StanceAggressive
