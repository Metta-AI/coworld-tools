import std/unittest
import environment
import agent_control
import types
import test_utils
import scripted/coordination

suite "Reservation - Basic Operations":
  test "reserveResource creates reservation":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    let result = reserveResource(0, 1, ivec2(10, 10), 100)
    check result == true
    check teamReservations[0].count == 1
    check teamReservations[0].reservations[0].pos == ivec2(10, 10)
    check teamReservations[0].reservations[0].agentId == 1
    check teamReservations[0].reservations[0].createdStep == 100

  test "isResourceReserved returns true for reserved position":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    discard reserveResource(0, 1, ivec2(10, 10), 100)
    check isResourceReserved(0, ivec2(10, 10)) == true
    check isResourceReserved(0, ivec2(11, 11)) == false

  test "isResourceReserved excludes own agent":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    discard reserveResource(0, 1, ivec2(10, 10), 100)
    # Agent 1 sees its own reservation as unreserved
    check isResourceReserved(0, ivec2(10, 10), excludeAgentId = 1) == false
    # Agent 2 sees it as reserved
    check isResourceReserved(0, ivec2(10, 10), excludeAgentId = 2) == true

  test "reserveResource prevents double-reservation by different agents":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    let r1 = reserveResource(0, 1, ivec2(10, 10), 100)
    check r1 == true
    let r2 = reserveResource(0, 2, ivec2(10, 10), 100)
    check r2 == false  # Already reserved by agent 1
    check teamReservations[0].count == 1

  test "reserveResource replaces existing reservation by same agent":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    discard reserveResource(0, 1, ivec2(10, 10), 100)
    check teamReservations[0].count == 1
    check teamReservations[0].reservations[0].pos == ivec2(10, 10)

    # Same agent reserves a different position - replaces old one
    discard reserveResource(0, 1, ivec2(20, 20), 110)
    check teamReservations[0].count == 1
    check teamReservations[0].reservations[0].pos == ivec2(20, 20)

  test "reserveResource handles invalid team ID":
    let r1 = reserveResource(-1, 1, ivec2(10, 10), 100)
    check r1 == false
    let r2 = reserveResource(MapRoomObjectsTeams, 1, ivec2(10, 10), 100)
    check r2 == false

suite "Reservation - Release":
  test "releaseReservation removes agent reservation":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    discard reserveResource(0, 1, ivec2(10, 10), 100)
    check teamReservations[0].count == 1

    releaseReservation(0, 1)
    check teamReservations[0].count == 0
    check isResourceReserved(0, ivec2(10, 10)) == false

  test "releaseReservation only removes specified agent":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    discard reserveResource(0, 1, ivec2(10, 10), 100)
    discard reserveResource(0, 2, ivec2(20, 20), 100)
    check teamReservations[0].count == 2

    releaseReservation(0, 1)
    check teamReservations[0].count == 1
    check isResourceReserved(0, ivec2(10, 10)) == false
    check isResourceReserved(0, ivec2(20, 20)) == true

suite "Reservation - Expiration":
  test "clearExpiredReservations removes old reservations":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    discard reserveResource(0, 1, ivec2(10, 10), 100)
    check teamReservations[0].count == 1

    let env = makeEmptyEnv()
    # Simulate step past expiration
    env.currentStep = 100 + ReservationExpirationSteps
    clearExpiredReservations(env)
    check teamReservations[0].count == 0

  test "clearExpiredReservations keeps recent reservations":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    discard reserveResource(0, 1, ivec2(10, 10), 100)
    let env = makeEmptyEnv()
    env.currentStep = 110  # Within expiration window
    clearExpiredReservations(env)
    check teamReservations[0].count == 1

  test "clearExpiredReservations removes dead agent reservations":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard reserveResource(0, agent.agentId, ivec2(15, 15), env.currentStep)
    check teamReservations[0].count == 1

    # Kill the agent by terminating it
    env.terminated[agent.agentId] = 1.0
    clearExpiredReservations(env)
    check teamReservations[0].count == 0

suite "Reservation - Capacity":
  test "reserveResource fails when at capacity":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    # Fill to capacity
    for i in 0 ..< MaxResourceReservations:
      let r = reserveResource(0, i, ivec2(i.int32, i.int32), 100)
      check r == true

    check teamReservations[0].count == MaxResourceReservations

    # Try one more - should fail
    let r = reserveResource(0, MaxResourceReservations + 1,
                            ivec2(99, 99), 100)
    check r == false

suite "Reservation - Get Position":
  test "getReservationPos returns reserved position":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    discard reserveResource(0, 1, ivec2(10, 10), 100)
    check getReservationPos(0, 1) == ivec2(10, 10)

  test "getReservationPos returns -1,-1 when no reservation":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    check getReservationPos(0, 1) == ivec2(-1, -1)

suite "Reservation - Multi-Team":
  test "reservations are team-scoped":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    # Team 0 reserves position
    discard reserveResource(0, 1, ivec2(10, 10), 100)
    # Team 1 can reserve same position (different team)
    let r = reserveResource(1, 2, ivec2(10, 10), 100)
    check r == true
    check teamReservations[0].count == 1
    check teamReservations[1].count == 1

suite "Reservation - Integration":
  test "two gatherers targeting same resource get different targets":
    for i in 0 ..< MapRoomObjectsTeams:
      teamReservations[i] = ReservationState()

    let env = makeEmptyEnv()
    let controller = newTestController(42)

    # Place two gatherers near a single tree
    let g1 = addAgentAt(env, 0, ivec2(10, 10))
    let g2 = addAgentAt(env, 1, ivec2(12, 10))
    discard addResource(env, Tree, ivec2(11, 10), ItemWood, 5)

    # First gatherer reserves the tree
    discard reserveResource(0, g1.agentId, ivec2(11, 10), env.currentStep)

    # Second gatherer should see it as reserved
    check isResourceReserved(0, ivec2(11, 10), g2.agentId) == true
    # First gatherer should not see its own reservation
    check isResourceReserved(0, ivec2(11, 10), g1.agentId) == false
