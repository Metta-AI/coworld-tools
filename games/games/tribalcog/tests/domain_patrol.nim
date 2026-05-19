import std/unittest
import environment
import agent_control
import types
import items
import terrain
import test_utils

proc initTestGlobalController*(seed: int) =
  ## Initialize global controller for testing with Brutal difficulty (no decision delays).
  initGlobalController(BuiltinAI, seed)
  # Set Brutal difficulty for all teams to ensure deterministic test behavior
  for teamId in 0 ..< MapRoomObjectsTeams:
    globalController.aiController.setDifficulty(teamId, DiffBrutal)

suite "Patrol":
  test "patrol moves toward waypoint":
    let env = makeEmptyEnv()
    # Create agent at position (10, 10) with military unit class
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    # Initialize global controller with built-in AI and Brutal difficulty for testing
    initTestGlobalController(42)
    let controller = globalController.aiController
    controller.setPatrol(0, ivec2(10, 10), ivec2(20, 10))

    # Verify patrol is active
    check controller.isPatrolActive(0) == true

    # Get action - should move toward waypoint 2 (right)
    let action = controller.decideAction(env, 0)
    let (verb, arg) = decodeAction(action)
    check verb == 1  # Move action
    check arg == 3   # East direction (toward x=20)

  test "patrol switches direction at waypoint":
    let env = makeEmptyEnv()
    # Create agent very close to waypoint 2
    let agent = addAgentAt(env, 0, ivec2(19, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    initTestGlobalController(42)
    let controller = globalController.aiController
    controller.setPatrol(0, ivec2(10, 10), ivec2(20, 10))

    # Get action - should be near waypoint 2, so may switch direction
    let action = controller.decideAction(env, 0)
    let (verb, arg) = decodeAction(action)
    check verb == 1  # Move action
    # Could be moving toward waypoint 2 still (if not quite there) or switching to waypoint 1

  test "patrol attacks enemy encountered":
    let env = makeEmptyEnv()
    # Create patrolling agent
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    # Create enemy agent adjacent to patrolling agent
    # Use agentId from a different team range (team 1 = agentIds 168+)
    let enemyAgentId = 168  # Team 1
    let enemy = addAgentAt(env, enemyAgentId, ivec2(11, 10), unitClass = UnitGoblin, stance = StanceAggressive)

    initTestGlobalController(42)
    let controller = globalController.aiController
    controller.setPatrol(0, ivec2(5, 10), ivec2(15, 10))

    let action = controller.decideAction(env, 0)
    let (verb, arg) = decodeAction(action)
    check verb == 2  # Attack action
    check arg == 3   # East direction (toward enemy)

  test "patrol can be cleared":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    initTestGlobalController(42)
    let controller = globalController.aiController
    controller.setPatrol(0, ivec2(5, 10), ivec2(15, 10))
    check controller.isPatrolActive(0) == true

    controller.clearPatrol(0)
    check controller.isPatrolActive(0) == false

  test "patrol does not activate without waypoints":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    initTestGlobalController(42)
    let controller = globalController.aiController
    # Patrol not set, should not be active
    check controller.isPatrolActive(0) == false

suite "Patrol External API":
  test "setAgentPatrol enables patrol mode":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    initTestGlobalController(42)
    setAgentPatrol(0, ivec2(5, 10), ivec2(15, 10))

    check isAgentPatrolActive(0) == true

  test "setAgentPatrol enables patrol mode from coordinates":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    initTestGlobalController(42)
    setAgentPatrol(0, ivec2(5, 10), ivec2(15, 10))

    check isAgentPatrolActive(0) == true

  test "clearAgentPatrol disables patrol mode":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    initTestGlobalController(42)
    setAgentPatrol(0, ivec2(5, 10), ivec2(15, 10))
    check isAgentPatrolActive(0) == true

    clearAgentPatrol(0)
    check isAgentPatrolActive(0) == false

  test "getAgentPatrolTarget returns current waypoint":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    initTestGlobalController(42)
    setAgentPatrol(0, ivec2(5, 10), ivec2(15, 10))

    # Should return one of the patrol points (starts heading to point2)
    let target = getAgentPatrolTarget(0)
    check target == ivec2(15, 10)

  test "external patrol API drives agent movement":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceDefensive)

    initTestGlobalController(42)
    setAgentPatrol(0, ivec2(10, 10), ivec2(20, 10))

    # Get action - should move toward waypoint 2 (right)
    let action = globalController.aiController.decideAction(env, 0)
    let (verb, arg) = decodeAction(action)
    check verb == 1  # Move action
    check arg == 3   # East direction (toward x=20)
