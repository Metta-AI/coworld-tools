import std/unittest
import types
import common
import scripted/cache_wrapper
import scripted/ai_types

# =============================================================================
# CacheWrapper[T] - Simple Scalar Cache Tests
# =============================================================================

suite "CacheWrapper - Lifecycle":
  test "unallocated cache has phase unallocated":
    var cache: CacheWrapper[int]
    check cache.phase == phaseUnallocated

  test "alloc sets phase to allocated":
    var cache: CacheWrapper[int]
    cache.alloc()
    check cache.phase == phaseAllocated
    check cache.generation == 0
    check cache.validGen == CacheInvalid

  test "reset increments generation and sets phase active":
    var cache: CacheWrapper[int]
    cache.alloc()
    cache.reset()
    check cache.generation == 1
    check cache.phase == phaseActive

  test "cleanup sets phase to cleaned":
    var cache: CacheWrapper[int]
    cache.alloc()
    cache.reset()
    cache.cleanup()
    check cache.phase == phaseCleaned
    check cache.validGen == CacheInvalid

suite "CacheWrapper - Value Operations":
  test "isValid returns false when not set":
    var cache: CacheWrapper[int]
    cache.alloc()
    cache.reset()
    check not cache.isValid()

  test "set makes value valid":
    var cache: CacheWrapper[int]
    cache.alloc()
    cache.reset()
    cache.set(42)
    check cache.isValid()
    check cache.value == 42

  test "reset invalidates previously set value":
    var cache: CacheWrapper[int]
    cache.alloc()
    cache.reset()
    cache.set(42)
    cache.reset()
    check not cache.isValid()

  test "get computes on miss and caches":
    var cache: CacheWrapper[int]
    var computeCount = 0
    cache.alloc()
    cache.reset()

    proc compute(): int =
      inc computeCount
      return 100

    let result1 = cache.get(compute)
    check result1 == 100
    check computeCount == 1

    let result2 = cache.get(compute)
    check result2 == 100
    check computeCount == 1  # Should not recompute

  test "get recomputes after reset":
    var cache: CacheWrapper[int]
    var computeCount = 0
    cache.alloc()
    cache.reset()

    proc compute(): int =
      inc computeCount
      return computeCount * 10

    discard cache.get(compute)
    check computeCount == 1

    cache.reset()
    let result = cache.get(compute)
    check result == 20
    check computeCount == 2

  test "invalidate marks cache as invalid":
    var cache: CacheWrapper[int]
    cache.alloc()
    cache.reset()
    cache.set(42)
    check cache.isValid()
    cache.invalidate()
    check not cache.isValid()

# =============================================================================
# PerAgentCacheWrapper[T] - Per-Agent Cache Tests
# =============================================================================

suite "PerAgentCacheWrapper - Lifecycle":
  test "alloc initializes cache":
    var cache: PerAgentCacheWrapper[int]
    cache.alloc()
    check cache.phase == phaseAllocated
    check cache.stepGeneration == 0

  test "reset uses O(1) generation bump":
    var cache: PerAgentCacheWrapper[int]
    cache.alloc()
    cache.reset()
    check cache.stepGeneration == 1
    check cache.phase == phaseActive

  test "multiple resets increment generation":
    var cache: PerAgentCacheWrapper[int]
    cache.alloc()
    cache.reset()
    cache.reset()
    cache.reset()
    check cache.stepGeneration == 3

suite "PerAgentCacheWrapper - Per-Agent Values":
  test "isValid returns false for unset agent":
    var cache: PerAgentCacheWrapper[int]
    cache.alloc()
    cache.reset()
    check not cache.isValid(0)
    check not cache.isValid(5)

  test "set makes specific agent valid":
    var cache: PerAgentCacheWrapper[int]
    cache.alloc()
    cache.reset()
    cache.set(0, 100)
    cache.set(5, 500)
    check cache.isValid(0)
    check cache.isValid(5)
    check not cache.isValid(1)
    check cache.values[0] == 100
    check cache.values[5] == 500

  test "reset invalidates all agents":
    var cache: PerAgentCacheWrapper[int]
    cache.alloc()
    cache.reset()
    cache.set(0, 100)
    cache.set(5, 500)
    cache.reset()
    check not cache.isValid(0)
    check not cache.isValid(5)

  test "get computes on miss per-agent":
    var cache: PerAgentCacheWrapper[int]
    var computeCounts: array[10, int]
    cache.alloc()
    cache.reset()

    proc compute(agentId: int): int =
      inc computeCounts[agentId]
      return agentId * 10

    check cache.get(0, compute) == 0
    check cache.get(1, compute) == 10
    check cache.get(0, compute) == 0  # Cached
    check computeCounts[0] == 1
    check computeCounts[1] == 1

  test "invalidate specific agent":
    var cache: PerAgentCacheWrapper[int]
    cache.alloc()
    cache.reset()
    cache.set(0, 100)
    cache.set(1, 200)
    cache.invalidate(0)
    check not cache.isValid(0)
    check cache.isValid(1)

  test "handles invalid agent IDs gracefully":
    var cache: PerAgentCacheWrapper[int]
    cache.alloc()
    cache.reset()
    check not cache.isValid(-1)
    check not cache.isValid(MapAgents + 1)

    # Set with invalid ID should be no-op
    cache.set(-1, 999)
    cache.set(MapAgents + 1, 999)

# =============================================================================
# PerTeamCacheWrapper[T] - Per-Team Cache Tests
# =============================================================================

suite "PerTeamCacheWrapper - Basic Operations":
  test "alloc and reset work correctly":
    var cache: PerTeamCacheWrapper[int]
    cache.alloc()
    check cache.phase == phaseAllocated
    cache.reset()
    check cache.stepGeneration == 1
    check cache.phase == phaseActive

  test "per-team validity tracking":
    var cache: PerTeamCacheWrapper[int]
    cache.alloc()
    cache.reset()
    cache.set(0, 1000)
    cache.set(1, 2000)
    check cache.isValid(0)
    check cache.isValid(1)
    check not cache.isValid(2)

  test "get computes on miss per-team":
    var cache: PerTeamCacheWrapper[int]
    var computeCounts: array[MapRoomObjectsTeams, int]
    cache.alloc()
    cache.reset()

    proc compute(teamId: int): int =
      inc computeCounts[teamId]
      return teamId * 100

    check cache.get(0, compute) == 0
    check cache.get(1, compute) == 100
    check cache.get(0, compute) == 0  # Cached
    check computeCounts[0] == 1
    check computeCounts[1] == 1

# =============================================================================
# AgentStateLifecycle - Agent State Tracking Tests
# =============================================================================

suite "AgentStateLifecycle - Basic Tracking":
  test "init sets all agents inactive":
    var lifecycle: AgentStateLifecycle
    lifecycle.init()
    for i in 0 ..< MapAgents:
      check not lifecycle.isActive(i)
      check not lifecycle.needsCleanup(i)

  test "markActive tracks agent":
    var lifecycle: AgentStateLifecycle
    lifecycle.init()
    lifecycle.markActive(5, 100)
    check lifecycle.isActive(5)
    check lifecycle.lastActiveStep[5] == 100

  test "markInactive flags for cleanup":
    var lifecycle: AgentStateLifecycle
    lifecycle.init()
    lifecycle.markActive(5, 100)
    lifecycle.markInactive(5)
    check not lifecycle.isActive(5)
    check lifecycle.needsCleanup(5)

  test "markInactive on inactive agent does not flag cleanup":
    var lifecycle: AgentStateLifecycle
    lifecycle.init()
    lifecycle.markInactive(5)  # Never was active
    check not lifecycle.needsCleanup(5)

  test "clearCleanupFlag clears the flag":
    var lifecycle: AgentStateLifecycle
    lifecycle.init()
    lifecycle.markActive(5, 100)
    lifecycle.markInactive(5)
    check lifecycle.needsCleanup(5)
    lifecycle.clearCleanupFlag(5)
    check not lifecycle.needsCleanup(5)

  test "getAgentsNeedingCleanup returns flagged agents":
    var lifecycle: AgentStateLifecycle
    lifecycle.init()
    lifecycle.markActive(2, 100)
    lifecycle.markActive(7, 100)
    lifecycle.markActive(9, 100)
    lifecycle.markInactive(2)
    lifecycle.markInactive(9)
    let cleanup = lifecycle.getAgentsNeedingCleanup()
    check cleanup.len == 2
    check 2 in cleanup
    check 9 in cleanup
    check 7 notin cleanup

  test "detectStaleAgents marks inactive old agents":
    var lifecycle: AgentStateLifecycle
    lifecycle.init()
    lifecycle.markActive(0, 10)
    lifecycle.markActive(1, 50)
    lifecycle.markActive(2, 200)

    # Check at step 150 with threshold 100
    let stale = lifecycle.detectStaleAgents(150, 100)
    check stale.len == 1
    check 0 in stale  # Last active at step 10, now at 150 (140 > 100)
    check 1 notin stale  # Last active at step 50, now at 150 (100 == 100, not >)

# =============================================================================
# AgentState Reset - Coordinated State Cleanup Tests
# =============================================================================

suite "AgentState - Reset":
  test "resetAgentState clears role state":
    var state: AgentState
    state.role = Fighter
    state.roleId = 5
    state.activeOptionId = 3
    state.activeOptionTicks = 100
    state.resetAgentState()
    check state.role == Gatherer
    check state.roleId == 0
    check state.activeOptionId == -1
    check state.activeOptionTicks == 0

  test "resetAgentState clears cached positions":
    var state: AgentState
    state.closestFoodPos = ivec2(10, 10)
    state.closestWoodPos = ivec2(20, 20)
    state.cachedThingPos[Tree] = ivec2(30, 30)
    state.resetAgentState()
    check state.closestFoodPos == ivec2(-1, -1)
    check state.closestWoodPos == ivec2(-1, -1)
    check state.cachedThingPos[Tree] == ivec2(-1, -1)

  test "resetAgentState clears build state":
    var state: AgentState
    state.buildTarget = ivec2(50, 50)
    state.buildStand = ivec2(49, 50)
    state.buildIndex = 3
    state.buildLockSteps = 8
    state.resetAgentState()
    check state.buildTarget == ivec2(-1, -1)
    check state.buildStand == ivec2(-1, -1)
    check state.buildIndex == -1
    check state.buildLockSteps == 0

  test "resetAgentState clears patrol state":
    var state: AgentState
    state.patrolActive = true
    state.patrolPoint1 = ivec2(10, 10)
    state.patrolPoint2 = ivec2(20, 20)
    state.patrolWaypointCount = 4
    state.resetAgentState()
    check state.patrolActive == false
    check state.patrolPoint1 == ivec2(-1, -1)
    check state.patrolPoint2 == ivec2(-1, -1)
    check state.patrolWaypointCount == 0

  test "resetAgentState clears command queue":
    var state: AgentState
    state.commandQueueCount = 5
    state.resetAgentState()
    check state.commandQueueCount == 0

  test "resetAgentState clears all behavioral modes":
    var state: AgentState
    state.attackMoveTarget = ivec2(100, 100)
    state.scoutActive = true
    state.holdPositionActive = true
    state.followActive = true
    state.guardActive = true
    state.stoppedActive = true
    state.resetAgentState()
    check state.attackMoveTarget == ivec2(-1, -1)
    check state.scoutActive == false
    check state.holdPositionActive == false
    check state.followActive == false
    check state.guardActive == false
    check state.stoppedActive == false

# =============================================================================
# Controller Cache Management Tests
# =============================================================================

suite "Controller - Cache Lifecycle":
  test "newController initializes lifecycle":
    let controller = newController(42)
    # The lifecycle should be initialized
    for i in 0 ..< MapAgents:
      check not controller.agentLifecycle.isActive(i)

  test "resetControllerCaches invalidates step caches":
    let controller = newController(42)
    controller.buildingCountsStep = 100
    controller.teamPopCountsStep = 100
    controller.damagedBuildingCacheStep = 100

    controller.resetControllerCaches(200)

    check controller.buildingCountsStep == -1
    check controller.teamPopCountsStep == -1
    check controller.damagedBuildingCacheStep == -1

  test "resetControllerCaches increments pathfinding generation":
    let controller = newController(42)
    let gen1 = controller.pathCache.generation
    controller.resetControllerCaches(100)
    check controller.pathCache.generation == gen1 + 1

  test "resetControllerCaches clears claimed buildings":
    let controller = newController(42)
    controller.claimedBuildings[0] = {House, Mill}
    controller.resetControllerCaches(100)
    check controller.claimedBuildings[0] == {}

  test "cleanupAgentState resets agent and lifecycle":
    let controller = newController(42)
    controller.agents[5].role = Fighter
    controller.agentsInitialized[5] = true
    controller.agentLifecycle.markActive(5, 100)

    controller.cleanupAgentState(5)

    check controller.agents[5].role == Gatherer
    check controller.agentsInitialized[5] == false
    check not controller.agentLifecycle.isActive(5)

  test "markAgentActive tracks lifecycle":
    let controller = newController(42)
    controller.markAgentActive(3, 150)
    check controller.agentLifecycle.isActive(3)
    check controller.agentLifecycle.lastActiveStep[3] == 150

  test "processAgentCleanup returns and cleans flagged agents":
    let controller = newController(42)
    controller.agentLifecycle.markActive(1, 100)
    controller.agentLifecycle.markActive(4, 100)
    controller.agents[1].role = Fighter
    controller.agents[4].role = Builder
    controller.agentsInitialized[1] = true
    controller.agentsInitialized[4] = true

    controller.agentLifecycle.markInactive(1)
    controller.agentLifecycle.markInactive(4)

    let cleaned = controller.processAgentCleanup()

    check cleaned.len == 2
    check 1 in cleaned
    check 4 in cleaned
    check controller.agents[1].role == Gatherer
    check controller.agents[4].role == Gatherer
    check controller.agentsInitialized[1] == false
    check controller.agentsInitialized[4] == false
