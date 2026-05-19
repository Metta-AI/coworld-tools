import std/unittest
import environment
import agent_control
import types
import test_utils
import scripted/coordination

suite "Coordination - Request Management":
  test "addRequest creates a new request":
    # Reset coordination state
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    let result = addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    check result == true
    check teamCoordination[0].requestCount == 1
    check teamCoordination[0].requests[0].kind == RequestProtection
    check teamCoordination[0].requests[0].requesterId == 1
    check teamCoordination[0].requests[0].requesterPos == ivec2(10, 10)
    check teamCoordination[0].requests[0].threatPos == ivec2(15, 15)
    check teamCoordination[0].requests[0].createdStep == 100
    check teamCoordination[0].requests[0].fulfilled == false

  test "addRequest rejects duplicate recent requests":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    # Add initial request
    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    check teamCoordination[0].requestCount == 1

    # Try to add duplicate (same requester, same kind, within DuplicateWindowSteps)
    let result = addRequest(0, RequestProtection, 1, ivec2(11, 11), ivec2(16, 16), 105)
    check result == false
    check teamCoordination[0].requestCount == 1  # Still only 1

    # Still duplicate at step 129 (within 30 steps)
    let result2 = addRequest(0, RequestProtection, 1, ivec2(11, 11), ivec2(16, 16), 129)
    check result2 == false
    check teamCoordination[0].requestCount == 1

  test "addRequest allows duplicate after DuplicateWindowSteps":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    # Add request after 30+ steps
    let result = addRequest(0, RequestProtection, 1, ivec2(11, 11), ivec2(16, 16), 130)
    check result == true
    check teamCoordination[0].requestCount == 2

  test "addRequest handles invalid team ID":
    let result = addRequest(-1, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    check result == false

    let result2 = addRequest(MapRoomObjectsTeams, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    check result2 == false

  test "addRequest removes oldest when at capacity":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    # Fill to capacity
    for i in 0 ..< MaxCoordinationRequests:
      discard addRequest(0, RequestProtection, i, ivec2(i.int32, i.int32), ivec2(0, 0), i * 20)

    check teamCoordination[0].requestCount == MaxCoordinationRequests

    # Add one more - should remove oldest
    discard addRequest(0, RequestProtection, 99, ivec2(99, 99), ivec2(0, 0), 999)
    check teamCoordination[0].requestCount == MaxCoordinationRequests
    # First request should now be from requester 1, not 0
    check teamCoordination[0].requests[0].requesterId == 1

suite "Coordination - Request Expiration":
  test "clearExpiredRequests removes old requests":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    # Add request at step 100
    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    check teamCoordination[0].requestCount == 1

    # Clear at step 100 + RequestExpirationSteps - should remove it
    clearExpiredRequests(100 + RequestExpirationSteps)
    check teamCoordination[0].requestCount == 0

  test "clearExpiredRequests keeps recent requests":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    # Clear at step 150 (within 60 steps)
    clearExpiredRequests(150)
    check teamCoordination[0].requestCount == 1

  test "clearExpiredRequests removes fulfilled requests":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    teamCoordination[0].requests[0].fulfilled = true
    clearExpiredRequests(101)  # Still recent but fulfilled
    check teamCoordination[0].requestCount == 0

suite "Coordination - Finding Requests":
  test "findNearestProtectionRequest returns nearest":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    # Add two protection requests at different positions
    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    discard addRequest(0, RequestProtection, 2, ivec2(20, 10), ivec2(25, 15), 100)

    # Fighter at position close to first request
    let req = findNearestProtectionRequest(0, ivec2(12, 10))
    check req != nil
    check req.requesterId == 1

  test "findNearestProtectionRequest returns nil outside radius":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    # Fighter far away (beyond ProtectionResponseRadius of 15)
    let req = findNearestProtectionRequest(0, ivec2(50, 50))
    check req == nil

  test "findNearestProtectionRequest ignores fulfilled requests":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    teamCoordination[0].requests[0].fulfilled = true
    let req = findNearestProtectionRequest(0, ivec2(10, 10))
    check req == nil

  test "findNearestProtectionRequest ignores defense requests":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestDefense, 1, ivec2(10, 10), ivec2(15, 15), 100)
    let req = findNearestProtectionRequest(0, ivec2(10, 10))
    check req == nil

suite "Coordination - Defense Requests":
  test "hasUnfulfilledRequest returns true for pending defense requests":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    check hasUnfulfilledRequest(0, RequestDefense) == false
    discard addRequest(0, RequestDefense, 1, ivec2(10, 10), ivec2(15, 15), 100)
    check hasUnfulfilledRequest(0, RequestDefense) == true

  test "hasUnfulfilledRequest returns false for fulfilled defense requests":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestDefense, 1, ivec2(10, 10), ivec2(15, 15), 100)
    teamCoordination[0].requests[0].fulfilled = true
    check hasUnfulfilledRequest(0, RequestDefense) == false

  test "markRequestFulfilled marks oldest defense request":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestDefense, 1, ivec2(10, 10), ivec2(15, 15), 100)
    discard addRequest(0, RequestDefense, 2, ivec2(20, 20), ivec2(25, 25), 110)

    markRequestFulfilled(0, RequestDefense)
    check teamCoordination[0].requests[0].fulfilled == true
    check teamCoordination[0].requests[1].fulfilled == false

suite "Coordination - Siege Build Requests":
  test "hasUnfulfilledRequest returns true for pending siege requests":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    check hasUnfulfilledRequest(0, RequestSiegeBuild) == false
    discard addRequest(0, RequestSiegeBuild, 1, ivec2(10, 10), ivec2(10, 10), 100)
    check hasUnfulfilledRequest(0, RequestSiegeBuild) == true

  test "markRequestFulfilled marks oldest siege request":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestSiegeBuild, 1, ivec2(10, 10), ivec2(10, 10), 100)
    discard addRequest(0, RequestSiegeBuild, 2, ivec2(20, 20), ivec2(20, 20), 110)

    markRequestFulfilled(0, RequestSiegeBuild)
    check teamCoordination[0].requests[0].fulfilled == true
    check teamCoordination[0].requests[1].fulfilled == false

suite "Coordination - Role Integration":
  test "requestProtectionFromFighter creates protection request":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    requestProtectionFromFighter(env, agent, ivec2(15, 15))

    check teamCoordination[0].requestCount == 1
    check teamCoordination[0].requests[0].kind == RequestProtection
    check teamCoordination[0].requests[0].requesterPos == ivec2(10, 10)
    check teamCoordination[0].requests[0].threatPos == ivec2(15, 15)

  test "requestDefenseFromBuilder creates defense request":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    requestDefenseFromBuilder(env, agent, ivec2(20, 20))

    check teamCoordination[0].requestCount == 1
    check teamCoordination[0].requests[0].kind == RequestDefense
    check teamCoordination[0].requests[0].threatPos == ivec2(20, 20)

  test "requestSiegeFromBuilder creates siege build request":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    requestSiegeFromBuilder(env, agent)

    check teamCoordination[0].requestCount == 1
    check teamCoordination[0].requests[0].kind == RequestSiegeBuild

  test "hasUnfulfilledRequest returns true when defense requested":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    check hasUnfulfilledRequest(0, RequestDefense) == false
    discard addRequest(0, RequestDefense, 1, ivec2(10, 10), ivec2(15, 15), 100)
    check hasUnfulfilledRequest(0, RequestDefense) == true

  test "fighterShouldEscort returns target when protection requested":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    let env = makeEmptyEnv()
    # Add gatherer who requested protection
    let gatherer = addAgentAt(env, 0, ivec2(10, 10))
    discard addRequest(0, RequestProtection, gatherer.agentId, ivec2(10, 10), ivec2(15, 15), env.currentStep)

    # Add fighter nearby
    let fighter = addAgentAt(env, 1, ivec2(12, 10))

    let (should, target) = fighterShouldEscort(env, fighter)
    check should == true
    check target == gatherer.pos

  test "fighterShouldEscort returns false when no protection needed":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    let env = makeEmptyEnv()
    let fighter = addAgentAt(env, 0, ivec2(10, 10))

    let (should, _) = fighterShouldEscort(env, fighter)
    check should == false

suite "Coordination - Priority System":
  test "addRequest accepts priority parameter":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100, PriorityHigh)
    check teamCoordination[0].requestCount == 1
    check teamCoordination[0].requests[0].priority == PriorityHigh

  test "addRequest defaults to PriorityNormal":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestProtection, 1, ivec2(10, 10), ivec2(15, 15), 100)
    check teamCoordination[0].requests[0].priority == PriorityNormal

  test "findNearestProtectionRequest prefers higher priority":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    # Closer request with low priority
    discard addRequest(0, RequestProtection, 1, ivec2(11, 10), ivec2(15, 15), 100, PriorityLow)
    # Farther request with high priority
    discard addRequest(0, RequestProtection, 2, ivec2(14, 10), ivec2(20, 20), 100, PriorityHigh)

    let req = findNearestProtectionRequest(0, ivec2(10, 10))
    check req != nil
    check req.requesterId == 2  # Higher priority wins over closer distance

  test "findNearestProtectionRequest uses distance as tiebreaker":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    # Two requests at same priority, different distances
    discard addRequest(0, RequestProtection, 1, ivec2(14, 10), ivec2(15, 15), 100, PriorityHigh)
    discard addRequest(0, RequestProtection, 2, ivec2(11, 10), ivec2(20, 20), 100, PriorityHigh)

    let req = findNearestProtectionRequest(0, ivec2(10, 10))
    check req != nil
    check req.requesterId == 2  # Closer one wins at same priority

  test "markRequestFulfilled prefers highest priority":
    for i in 0 ..< MapRoomObjectsTeams:
      teamCoordination[i] = CoordinationState()

    discard addRequest(0, RequestDefense, 1, ivec2(10, 10), ivec2(15, 15), 100, PriorityLow)
    discard addRequest(0, RequestDefense, 2, ivec2(20, 20), ivec2(25, 25), 110, PriorityHigh)

    markRequestFulfilled(0, RequestDefense)
    check teamCoordination[0].requests[0].fulfilled == false  # Low priority not fulfilled
    check teamCoordination[0].requests[1].fulfilled == true   # High priority fulfilled first
