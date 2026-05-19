import std/unittest
import environment
import agent_control
import common
import types
import items
import terrain
import spatial_index
import test_utils
import scripted/ai_core

# =============================================================================
# Pure Geometry Functions
# =============================================================================

suite "AI Core - vecToOrientation":
  test "north maps to 0":
    check vecToOrientation(ivec2(0, -1)) == 0
  test "south maps to 1":
    check vecToOrientation(ivec2(0, 1)) == 1
  test "west maps to 2":
    check vecToOrientation(ivec2(-1, 0)) == 2
  test "east maps to 3":
    check vecToOrientation(ivec2(1, 0)) == 3
  test "northwest maps to 4":
    check vecToOrientation(ivec2(-1, -1)) == 4
  test "northeast maps to 5":
    check vecToOrientation(ivec2(1, -1)) == 5
  test "southwest maps to 6":
    check vecToOrientation(ivec2(-1, 1)) == 6
  test "southeast maps to 7":
    check vecToOrientation(ivec2(1, 1)) == 7
  test "zero vector maps to 0":
    check vecToOrientation(ivec2(0, 0)) == 0

suite "AI Core - signi":
  test "positive returns 1":
    check signi(5) == 1
  test "negative returns -1":
    check signi(-3) == -1
  test "zero returns 0":
    check signi(0) == 0
  test "large positive":
    check signi(int32.high) == 1
  test "large negative":
    check signi(int32.low) == -1

suite "AI Core - isAdjacent":
  test "horizontally adjacent":
    check isAdjacent(ivec2(10, 10), ivec2(11, 10)) == true
  test "vertically adjacent":
    check isAdjacent(ivec2(10, 10), ivec2(10, 11)) == true
  test "diagonally adjacent":
    check isAdjacent(ivec2(10, 10), ivec2(11, 11)) == true
  test "same position is not adjacent":
    check isAdjacent(ivec2(10, 10), ivec2(10, 10)) == false
  test "distance 2 is not adjacent":
    check isAdjacent(ivec2(10, 10), ivec2(12, 10)) == false

suite "AI Core - clampToPlayable":
  test "position inside bounds unchanged":
    let pos = ivec2(20, 20)
    let clamped = clampToPlayable(pos)
    check clamped == pos
  test "clamps low coordinates":
    let pos = ivec2(0, 0)
    let clamped = clampToPlayable(pos)
    check clamped.x >= MapBorder
    check clamped.y >= MapBorder
  test "clamps high coordinates":
    let pos = ivec2(MapWidth.int32, MapHeight.int32)
    let clamped = clampToPlayable(pos)
    check clamped.x < MapWidth - MapBorder
    check clamped.y < MapHeight - MapBorder

suite "AI Core - neighborDirIndex":
  test "north neighbor":
    check neighborDirIndex(ivec2(10, 10), ivec2(10, 9)) == 0
  test "south neighbor":
    check neighborDirIndex(ivec2(10, 10), ivec2(10, 11)) == 1
  test "west neighbor":
    check neighborDirIndex(ivec2(10, 10), ivec2(9, 10)) == 2
  test "east neighbor":
    check neighborDirIndex(ivec2(10, 10), ivec2(11, 10)) == 3
  test "northwest neighbor":
    check neighborDirIndex(ivec2(10, 10), ivec2(9, 9)) == 4
  test "northeast neighbor":
    check neighborDirIndex(ivec2(10, 10), ivec2(11, 9)) == 5
  test "southwest neighbor":
    check neighborDirIndex(ivec2(10, 10), ivec2(9, 11)) == 6
  test "southeast neighbor":
    check neighborDirIndex(ivec2(10, 10), ivec2(11, 11)) == 7

suite "AI Core - radiusBounds":
  test "returns correct bounds for center of map":
    let (sx, ex, sy, ey) = radiusBounds(ivec2(20, 20), 5)
    check sx == 15
    check ex == 25
    check sy == 15
    check ey == 25
  test "clamps to map edges":
    let (sx, ex, sy, ey) = radiusBounds(ivec2(2, 2), 5)
    check sx == 0
    check sy == 0
    check ex == 7
    check ey == 7

# =============================================================================
# hasHarvestableResource
# =============================================================================

suite "AI Core - hasHarvestableResource":
  test "nil thing returns false":
    check hasHarvestableResource(nil) == false

  test "stump with wood is harvestable":
    let stump = Thing(kind: Stump, pos: ivec2(10, 10))
    stump.inventory = emptyInventory()
    setInv(stump, ItemWood, 5)
    check hasHarvestableResource(stump) == true

  test "stump without wood is not harvestable":
    let stump = Thing(kind: Stump, pos: ivec2(10, 10))
    stump.inventory = emptyInventory()
    check hasHarvestableResource(stump) == false

  test "stubble with wheat is harvestable":
    let stubble = Thing(kind: Stubble, pos: ivec2(10, 10))
    stubble.inventory = emptyInventory()
    setInv(stubble, ItemWheat, 3)
    check hasHarvestableResource(stubble) == true

  test "stone with stone is harvestable":
    let stone = Thing(kind: Stone, pos: ivec2(10, 10))
    stone.inventory = emptyInventory()
    setInv(stone, ItemStone, 10)
    check hasHarvestableResource(stone) == true

  test "gold with gold is harvestable":
    let gold = Thing(kind: Gold, pos: ivec2(10, 10))
    gold.inventory = emptyInventory()
    setInv(gold, ItemGold, 5)
    check hasHarvestableResource(gold) == true

  test "tree is always harvestable":
    let tree = Thing(kind: Tree, pos: ivec2(10, 10))
    tree.inventory = emptyInventory()
    check hasHarvestableResource(tree) == true

  test "cow is always harvestable":
    let cow = Thing(kind: Cow, pos: ivec2(10, 10))
    cow.inventory = emptyInventory()
    check hasHarvestableResource(cow) == true

  test "empty corpse is not harvestable":
    let corpse = Thing(kind: Corpse, pos: ivec2(10, 10))
    corpse.inventory = emptyInventory()
    check hasHarvestableResource(corpse) == false

  test "corpse with items is harvestable":
    let corpse = Thing(kind: Corpse, pos: ivec2(10, 10))
    corpse.inventory = emptyInventory()
    setInv(corpse, ItemMeat, 2)
    check hasHarvestableResource(corpse) == true

  test "fish with fish is harvestable":
    let fish = Thing(kind: Fish, pos: ivec2(10, 10))
    fish.inventory = emptyInventory()
    setInv(fish, ItemFish, 3)
    check hasHarvestableResource(fish) == true

# =============================================================================
# stanceAllowsAutoAttack
# =============================================================================

suite "AI Core - stanceAllowsAutoAttack":
  test "aggressive stance always allows auto-attack":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)
    check stanceAllowsAutoAttack(env, agent) == true

  test "stand ground stance always allows auto-attack":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceStandGround)
    check stanceAllowsAutoAttack(env, agent) == true

  test "no attack stance never allows auto-attack":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceNoAttack)
    check stanceAllowsAutoAttack(env, agent) == false

  test "defensive stance allows when recently attacked":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    env.currentStep = 100
    agent.lastAttackedStep = 90  # Within retaliation window
    check stanceAllowsAutoAttack(env, agent) == true

  test "defensive stance denies when not recently attacked":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    env.currentStep = 100
    agent.lastAttackedStep = 50  # Outside retaliation window
    check stanceAllowsAutoAttack(env, agent) == false

  test "defensive stance denies when never attacked":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    env.currentStep = 100
    agent.lastAttackedStep = 0
    check stanceAllowsAutoAttack(env, agent) == false

# =============================================================================
# Difficulty Configuration
# =============================================================================

suite "AI Core - Difficulty":
  test "getDifficulty returns default for invalid team":
    let controller = newTestController(42)
    let diff = controller.getDifficulty(-1)
    check diff.level == DiffNormal

  test "setDifficulty changes difficulty level":
    let controller = newTestController(42)
    controller.setDifficulty(0, DiffEasy)
    check controller.getDifficulty(0).level == DiffEasy

  test "setDifficulty to Brutal":
    let controller = newTestController(42)
    controller.setDifficulty(0, DiffBrutal)
    check controller.getDifficulty(0).level == DiffBrutal
    check controller.getDifficulty(0).decisionDelayChance == 0.0

  test "enableAdaptiveDifficulty sets adaptive flag":
    let controller = newTestController(42)
    controller.enableAdaptiveDifficulty(0, 0.4)
    check controller.getDifficulty(0).adaptive == true
    check controller.getDifficulty(0).adaptiveTarget == 0.4f32

  test "disableAdaptiveDifficulty clears flag":
    let controller = newTestController(42)
    controller.enableAdaptiveDifficulty(0)
    controller.disableAdaptiveDifficulty(0)
    check controller.getDifficulty(0).adaptive == false

  test "shouldApplyDecisionDelay false for Brutal":
    let controller = newTestController(42)
    controller.setDifficulty(0, DiffBrutal)
    # Brutal has 0% delay chance
    check controller.shouldApplyDecisionDelay(0) == false

  test "shouldApplyDecisionDelay false for invalid team":
    let controller = newTestController(42)
    check controller.shouldApplyDecisionDelay(-1) == false

# =============================================================================
# Fog of War / Revealed Map
# =============================================================================

suite "AI Core - Fog of War":
  test "revealTilesInRange reveals tiles":
    let env = makeEmptyEnv()
    env.revealTilesInRange(0, ivec2(10, 10), 2)
    check env.isRevealed(0, ivec2(10, 10)) == true
    check env.isRevealed(0, ivec2(11, 11)) == true
    check env.isRevealed(0, ivec2(12, 12)) == true

  test "isRevealed false for unrevealed tile":
    let env = makeEmptyEnv()
    check env.isRevealed(0, ivec2(20, 20)) == false

  test "isRevealed false for invalid team":
    let env = makeEmptyEnv()
    check env.isRevealed(-1, ivec2(10, 10)) == false

  test "isRevealed false for invalid position":
    let env = makeEmptyEnv()
    check env.isRevealed(0, ivec2(-1, -1)) == false

  test "clearRevealedMap clears all reveals":
    let env = makeEmptyEnv()
    env.revealTilesInRange(0, ivec2(10, 10), 3)
    check env.getRevealedTileCount(0) > 0
    env.clearRevealedMap(0)
    check env.getRevealedTileCount(0) == 0

  test "getRevealedTileCount counts correctly":
    let env = makeEmptyEnv()
    env.revealTilesInRange(0, ivec2(10, 10), 1)
    # Radius 1 reveals a 3x3 area = 9 tiles
    check env.getRevealedTileCount(0) == 9

  test "getRevealedTileCount 0 for invalid team":
    let env = makeEmptyEnv()
    check env.getRevealedTileCount(-1) == 0

# =============================================================================
# Threat Map
# =============================================================================

suite "AI Core - Threat Map":
  test "hasKnownThreats false with no threats":
    let controller = newTestController(42)
    check controller.hasKnownThreats(0, 100) == false

  test "reportThreat and hasKnownThreats":
    let controller = newTestController(42)
    controller.reportThreat(0, ivec2(20, 20), 3, 100)
    check controller.hasKnownThreats(0, 100) == true

  test "clearThreatMap removes all threats":
    let controller = newTestController(42)
    controller.reportThreat(0, ivec2(20, 20), 3, 100)
    controller.clearThreatMap(0)
    check controller.hasKnownThreats(0, 100) == false

  test "getNearestThreat returns closest":
    let controller = newTestController(42)
    controller.reportThreat(0, ivec2(30, 30), 2, 100)
    controller.reportThreat(0, ivec2(12, 12), 1, 100)
    let (pos, dist, found) = controller.getNearestThreat(0, ivec2(10, 10), 100)
    check found == true
    check pos == ivec2(12, 12)

  test "getNearestThreat not found when empty":
    let controller = newTestController(42)
    let (pos, dist, found) = controller.getNearestThreat(0, ivec2(10, 10), 100)
    check found == false

  test "getThreatsInRange filters by distance":
    let controller = newTestController(42)
    controller.reportThreat(0, ivec2(12, 12), 1, 100)  # Close
    controller.reportThreat(0, ivec2(50, 50), 2, 100)  # Far
    let threats = controller.getThreatsInRange(0, ivec2(10, 10), 5, 100)
    check threats.len == 1

  test "getTotalThreatStrength sums within range":
    let controller = newTestController(42)
    controller.reportThreat(0, ivec2(12, 12), 3, 100)
    controller.reportThreat(0, ivec2(11, 11), 2, 100)
    controller.reportThreat(0, ivec2(50, 50), 5, 100)  # Out of range
    let total = controller.getTotalThreatStrength(0, ivec2(10, 10), 5, 100)
    check total == 5  # 3 + 2

  test "decayThreats removes stale entries":
    let controller = newTestController(42)
    controller.reportThreat(0, ivec2(20, 20), 3, 10)  # Old threat
    # ThreatDecaySteps later, the threat should be stale
    controller.decayThreats(0, 10 + ThreatDecaySteps + 1)
    check controller.hasKnownThreats(0, 10 + ThreatDecaySteps + 1) == false

  test "decayThreats keeps fresh entries":
    let controller = newTestController(42)
    controller.reportThreat(0, ivec2(20, 20), 3, 100)
    controller.decayThreats(0, 105)  # Only 5 steps later
    check controller.hasKnownThreats(0, 105) == true

  test "reportThreat updates existing entry":
    let controller = newTestController(42)
    controller.reportThreat(0, ivec2(20, 20), 3, 100)
    controller.reportThreat(0, ivec2(20, 20), 5, 110)  # Same position, higher strength
    let threats = controller.getThreatsInRange(0, ivec2(20, 20), 1, 110)
    check threats.len == 1
    check threats[0].strength == 5

# =============================================================================
# Patrol Behavior
# =============================================================================

suite "AI Core - Patrol":
  test "setPatrol enables patrol":
    let controller = newTestController(42)
    controller.setPatrol(0, ivec2(10, 10), ivec2(20, 20))
    check controller.isPatrolActive(0) == true

  test "clearPatrol disables patrol":
    let controller = newTestController(42)
    controller.setPatrol(0, ivec2(10, 10), ivec2(20, 20))
    controller.clearPatrol(0)
    check controller.isPatrolActive(0) == false

  test "getPatrolTarget returns second point initially":
    let controller = newTestController(42)
    controller.setPatrol(0, ivec2(10, 10), ivec2(20, 20))
    check controller.getPatrolTarget(0) == ivec2(20, 20)

  test "isPatrolActive false for unset agent":
    let controller = newTestController(42)
    check controller.isPatrolActive(0) == false

  test "setMultiWaypointPatrol with 3 waypoints":
    let controller = newTestController(42)
    let waypoints = [ivec2(10, 10), ivec2(20, 20), ivec2(30, 10)]
    controller.setMultiWaypointPatrol(0, waypoints)
    check controller.isPatrolActive(0) == true
    check controller.getPatrolWaypointCount(0) == 3
    check controller.getPatrolCurrentWaypointIndex(0) == 0
    check controller.getPatrolTarget(0) == ivec2(10, 10)

  test "advancePatrolWaypoint cycles through waypoints":
    let controller = newTestController(42)
    let waypoints = [ivec2(10, 10), ivec2(20, 20), ivec2(30, 10)]
    controller.setMultiWaypointPatrol(0, waypoints)
    controller.advancePatrolWaypoint(0)
    check controller.getPatrolCurrentWaypointIndex(0) == 1
    check controller.getPatrolTarget(0) == ivec2(20, 20)
    controller.advancePatrolWaypoint(0)
    check controller.getPatrolCurrentWaypointIndex(0) == 2
    check controller.getPatrolTarget(0) == ivec2(30, 10)
    controller.advancePatrolWaypoint(0)
    check controller.getPatrolCurrentWaypointIndex(0) == 0  # Wraps

  test "setMultiWaypointPatrol requires at least 2 points":
    let controller = newTestController(42)
    controller.setMultiWaypointPatrol(0, [ivec2(10, 10)])
    check controller.isPatrolActive(0) == false  # Not set

  test "clearPatrol clears multi-waypoint patrol":
    let controller = newTestController(42)
    let waypoints = [ivec2(10, 10), ivec2(20, 20), ivec2(30, 10)]
    controller.setMultiWaypointPatrol(0, waypoints)
    controller.clearPatrol(0)
    check controller.isPatrolActive(0) == false
    check controller.getPatrolWaypointCount(0) == 0

# =============================================================================
# Scout Behavior
# =============================================================================

suite "AI Core - Scout":
  test "setScoutMode enables scouting":
    let controller = newTestController(42)
    controller.setScoutMode(0)
    check controller.isScoutModeActive(0) == true

  test "clearScoutMode disables scouting":
    let controller = newTestController(42)
    controller.setScoutMode(0)
    controller.clearScoutMode(0)
    check controller.isScoutModeActive(0) == false

  test "scout explore radius initialized":
    let controller = newTestController(42)
    controller.setScoutMode(0)
    check controller.getScoutExploreRadius(0) > 0

  test "recordScoutEnemySighting sets step":
    let controller = newTestController(42)
    controller.setScoutMode(0)
    controller.recordScoutEnemySighting(0, 500)
    # Verify by checking the agent state directly
    check controller.agents[0].scoutLastEnemySeenStep == 500

  test "isScoutModeActive false for unset agent":
    let controller = newTestController(42)
    check controller.isScoutModeActive(0) == false

# =============================================================================
# Hold Position
# =============================================================================

suite "AI Core - Hold Position":
  test "setHoldPosition enables hold":
    let controller = newTestController(42)
    controller.setHoldPosition(0, ivec2(15, 15))
    check controller.isHoldPositionActive(0) == true
    check controller.getHoldPosition(0) == ivec2(15, 15)

  test "clearHoldPosition disables hold":
    let controller = newTestController(42)
    controller.setHoldPosition(0, ivec2(15, 15))
    controller.clearHoldPosition(0)
    check controller.isHoldPositionActive(0) == false
    check controller.getHoldPosition(0) == ivec2(-1, -1)

  test "isHoldPositionActive false for unset agent":
    let controller = newTestController(42)
    check controller.isHoldPositionActive(0) == false

  test "getHoldPosition returns zero for unset agent":
    let controller = newTestController(42)
    check controller.getHoldPosition(0) == ivec2(0, 0)

  test "getHoldPosition returns (-1,-1) for invalid agent":
    let controller = newTestController(42)
    check controller.getHoldPosition(-1) == ivec2(-1, -1)

# =============================================================================
# Follow Behavior
# =============================================================================

suite "AI Core - Follow":
  test "setFollowTarget enables follow":
    let controller = newTestController(42)
    controller.setFollowTarget(0, 5)
    check controller.isFollowActive(0) == true
    check controller.getFollowTargetId(0) == 5

  test "clearFollowTarget disables follow":
    let controller = newTestController(42)
    controller.setFollowTarget(0, 5)
    controller.clearFollowTarget(0)
    check controller.isFollowActive(0) == false
    check controller.getFollowTargetId(0) == -1

  test "isFollowActive false for unset agent":
    let controller = newTestController(42)
    check controller.isFollowActive(0) == false

  test "setFollowTarget rejects invalid target":
    let controller = newTestController(42)
    controller.setFollowTarget(0, -1)
    check controller.isFollowActive(0) == false

# =============================================================================
# Guard Behavior
# =============================================================================

suite "AI Core - Guard":
  test "setGuardTarget enables guard on agent":
    let controller = newTestController(42)
    controller.setGuardTarget(0, 3)
    check controller.isGuardActive(0) == true
    check controller.getGuardTargetId(0) == 3
    check controller.getGuardPosition(0) == ivec2(-1, -1)  # Not guarding position

  test "setGuardPosition enables guard on position":
    let controller = newTestController(42)
    controller.setGuardPosition(0, ivec2(25, 25))
    check controller.isGuardActive(0) == true
    check controller.getGuardTargetId(0) == -1  # Not guarding agent
    check controller.getGuardPosition(0) == ivec2(25, 25)

  test "clearGuard disables guard":
    let controller = newTestController(42)
    controller.setGuardTarget(0, 3)
    controller.clearGuard(0)
    check controller.isGuardActive(0) == false
    check controller.getGuardTargetId(0) == -1
    check controller.getGuardPosition(0) == ivec2(-1, -1)

  test "isGuardActive false for unset agent":
    let controller = newTestController(42)
    check controller.isGuardActive(0) == false

# =============================================================================
# Stop Behavior
# =============================================================================

suite "AI Core - Stop":
  test "stopAgentFull enables stopped state":
    let controller = newTestController(42)
    controller.stopAgentFull(0, 100)
    check controller.isAgentStopped(0) == true
    check controller.getAgentStoppedUntilStep(0) == 100 + StopIdleSteps

  test "stopAgentDeferred uses sentinel step":
    let controller = newTestController(42)
    controller.stopAgentDeferred(0)
    check controller.isAgentStopped(0) == true
    check controller.getAgentStoppedUntilStep(0) == -1

  test "clearAgentStop clears stopped state":
    let controller = newTestController(42)
    controller.stopAgentFull(0, 100)
    controller.clearAgentStop(0)
    check controller.isAgentStopped(0) == false

  test "stopAgentFull clears other modes":
    let controller = newTestController(42)
    controller.setPatrol(0, ivec2(10, 10), ivec2(20, 20))
    controller.setScoutMode(0)
    controller.stopAgentFull(0, 100)
    check controller.isPatrolActive(0) == false
    check controller.isScoutModeActive(0) == false

  test "isAgentStopped false for unset agent":
    let controller = newTestController(42)
    check controller.isAgentStopped(0) == false

# =============================================================================
# Stance API
# =============================================================================

suite "AI Core - Stance":
  test "setAgentStanceDeferred sets pending stance":
    let controller = newTestController(42)
    controller.setAgentStanceDeferred(0, StanceAggressive)
    check controller.isAgentStanceModified(0) == true
    check controller.getAgentPendingStance(0) == StanceAggressive

  test "clearAgentStanceModified clears flag":
    let controller = newTestController(42)
    controller.setAgentStanceDeferred(0, StanceAggressive)
    controller.clearAgentStanceModified(0)
    check controller.isAgentStanceModified(0) == false

  test "getAgentPendingStance returns Defensive when unmodified":
    let controller = newTestController(42)
    check controller.getAgentPendingStance(0) == StanceDefensive

  test "isAgentStanceModified false initially":
    let controller = newTestController(42)
    check controller.isAgentStanceModified(0) == false

# =============================================================================
# Command Queue
# =============================================================================

suite "AI Core - Command Queue":
  test "empty queue has 0 count":
    let controller = newTestController(42)
    check controller.getCommandQueueCount(0) == 0
    check controller.hasQueuedCommands(0) == false

  test "queueCommand adds to queue":
    let controller = newTestController(42)
    controller.queueAttackMove(0, ivec2(20, 20))
    check controller.getCommandQueueCount(0) == 1
    check controller.hasQueuedCommands(0) == true

  test "multiple queue commands":
    let controller = newTestController(42)
    controller.queueAttackMove(0, ivec2(20, 20))
    controller.queuePatrol(0, ivec2(30, 30))
    controller.queueFollow(0, 5)
    check controller.getCommandQueueCount(0) == 3

  test "peekNextCommand returns first without removing":
    let controller = newTestController(42)
    controller.queueAttackMove(0, ivec2(20, 20))
    controller.queuePatrol(0, ivec2(30, 30))
    let cmd = controller.peekNextCommand(0)
    check cmd.cmdType == CmdAttackMove
    check cmd.targetPos == ivec2(20, 20)
    check controller.getCommandQueueCount(0) == 2  # Not removed

  test "popNextCommand removes first":
    let controller = newTestController(42)
    controller.queueAttackMove(0, ivec2(20, 20))
    controller.queuePatrol(0, ivec2(30, 30))
    let cmd = controller.popNextCommand(0)
    check cmd.cmdType == CmdAttackMove
    check controller.getCommandQueueCount(0) == 1
    let cmd2 = controller.peekNextCommand(0)
    check cmd2.cmdType == CmdPatrol

  test "clearCommandQueue empties queue":
    let controller = newTestController(42)
    controller.queueAttackMove(0, ivec2(20, 20))
    controller.queuePatrol(0, ivec2(30, 30))
    controller.clearCommandQueue(0)
    check controller.getCommandQueueCount(0) == 0

  test "queueGuardAgent sets correct command type":
    let controller = newTestController(42)
    controller.queueGuardAgent(0, 3)
    let cmd = controller.peekNextCommand(0)
    check cmd.cmdType == CmdGuard
    check cmd.targetAgentId == 3

  test "queueGuardPosition sets correct command type":
    let controller = newTestController(42)
    controller.queueGuardPosition(0, ivec2(15, 15))
    let cmd = controller.peekNextCommand(0)
    check cmd.cmdType == CmdGuard
    check cmd.targetPos == ivec2(15, 15)
    check cmd.targetAgentId == -1

  test "queueHoldPosition sets correct command type":
    let controller = newTestController(42)
    controller.queueHoldPosition(0, ivec2(25, 25))
    let cmd = controller.peekNextCommand(0)
    check cmd.cmdType == CmdHoldPosition
    check cmd.targetPos == ivec2(25, 25)

  test "executeQueuedCommand applies attack move":
    let controller = newTestController(42)
    controller.queueAttackMove(0, ivec2(20, 20))
    controller.executeQueuedCommand(0, ivec2(10, 10))
    check controller.agents[0].attackMoveTarget == ivec2(20, 20)
    check controller.getCommandQueueCount(0) == 0

  test "executeQueuedCommand applies patrol":
    let controller = newTestController(42)
    controller.queuePatrol(0, ivec2(30, 30))
    controller.executeQueuedCommand(0, ivec2(10, 10))
    check controller.isPatrolActive(0) == true

  test "executeQueuedCommand applies hold position":
    let controller = newTestController(42)
    controller.queueHoldPosition(0, ivec2(25, 25))
    controller.executeQueuedCommand(0, ivec2(10, 10))
    check controller.isHoldPositionActive(0) == true
    check controller.agents[0].holdPositionTarget == ivec2(25, 25)

# =============================================================================
# Agent State
# =============================================================================

suite "AI Core - Agent State":
  test "isAgentInitialized false initially":
    let controller = newTestController(42)
    check controller.isAgentInitialized(0) == false

  test "isAgentInitialized false for invalid id":
    let controller = newTestController(42)
    check controller.isAgentInitialized(-1) == false
    check controller.isAgentInitialized(MapAgents + 1) == false

  test "getAgentRole returns Gatherer for uninitialized":
    let controller = newTestController(42)
    check controller.getAgentRole(0) == Gatherer

# =============================================================================
# Building Management
# =============================================================================

suite "AI Core - Building Count":
  test "getBuildingCount returns 0 for empty env":
    let env = makeEmptyEnv()
    let controller = newTestController(42)
    check controller.getBuildingCount(env, 0, TownCenter) == 0

  test "getBuildingCount counts team buildings":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(10, 10), 0)
    discard addBuilding(env, Barracks, ivec2(15, 15), 0)
    discard addBuilding(env, TownCenter, ivec2(30, 30), 1)  # Different team
    let controller = newTestController(42)
    check controller.getBuildingCount(env, 0, TownCenter) == 1
    check controller.getBuildingCount(env, 0, Barracks) == 1
    check controller.getBuildingCount(env, 1, TownCenter) == 1

  test "getBuildingCountNear counts within radius":
    let env = makeEmptyEnv()
    discard addBuilding(env, Barracks, ivec2(10, 10), 0)
    discard addBuilding(env, Barracks, ivec2(50, 50), 0)  # Far away
    check getBuildingCountNear(env, 0, Barracks, ivec2(12, 12), 5) == 1

  test "anyMissingBuildingNear detects missing":
    let env = makeEmptyEnv()
    discard addBuilding(env, Barracks, ivec2(10, 10), 0)
    check anyMissingBuildingNear(env, 0, [Barracks, Stable], ivec2(10, 10)) == true  # Stable missing

  test "anyMissingBuildingNear false when all present":
    let env = makeEmptyEnv()
    discard addBuilding(env, Barracks, ivec2(10, 10), 0)
    discard addBuilding(env, Stable, ivec2(12, 10), 0)
    check anyMissingBuildingNear(env, 0, [Barracks, Stable], ivec2(10, 10)) == false

# =============================================================================
# Passability
# =============================================================================

suite "AI Core - Passability":
  test "isPassable on empty terrain":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check isPassable(env, agent, ivec2(15, 15)) == true

  test "isPassable false on water":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    env.terrain[15][15] = Water
    check isPassable(env, agent, ivec2(15, 15)) == false

  test "isPassable false on occupied tile":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, Wall, ivec2(15, 15), 0)
    check isPassable(env, agent, ivec2(15, 15)) == false

  test "isPassable false on invalid position":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check isPassable(env, agent, ivec2(-1, -1)) == false

# =============================================================================
# Spiral Search
# =============================================================================

suite "AI Core - getNextSpiralPoint":
  test "advances deterministically":
    var state = AgentState()
    state.basePosition = ivec2(20, 20)
    state.lastSearchPosition = ivec2(20, 20)
    let p1 = getNextSpiralPoint(state)
    let p2 = getNextSpiralPoint(state)
    # Each call should return different positions
    check p1 != p2

  test "spiral stays near base":
    var state = AgentState()
    state.basePosition = ivec2(20, 20)
    state.lastSearchPosition = ivec2(20, 20)
    for i in 0 ..< 10:
      let pos = getNextSpiralPoint(state)
      let dist = max(abs(pos.x - 20), abs(pos.y - 20))
      check dist < SearchRadius

# =============================================================================
# Lantern Helpers
# =============================================================================

suite "AI Core - Lantern Placement":
  test "isLanternPlacementValid on empty terrain":
    let env = makeEmptyEnv()
    check isLanternPlacementValid(env, ivec2(20, 20)) == true

  test "isLanternPlacementValid false on water":
    let env = makeEmptyEnv()
    env.terrain[20][20] = Water
    check isLanternPlacementValid(env, ivec2(20, 20)) == false

  test "isLanternPlacementValid false on occupied tile":
    let env = makeEmptyEnv()
    discard addBuilding(env, Wall, ivec2(20, 20), 0)
    check isLanternPlacementValid(env, ivec2(20, 20)) == false

  test "hasTeamLanternNear false when no lanterns":
    let env = makeEmptyEnv()
    check hasTeamLanternNear(env, 0, ivec2(20, 20)) == false

  test "hasTeamLanternNear true when lantern nearby":
    let env = makeEmptyEnv()
    let lantern = Thing(kind: Lantern, pos: ivec2(21, 21), teamId: 0)
    lantern.inventory = emptyInventory()
    lantern.lanternHealthy = true
    env.add(lantern)
    check hasTeamLanternNear(env, 0, ivec2(20, 20)) == true

# =============================================================================
# Water Finding
# =============================================================================

suite "AI Core - findNearestWater":
  test "finds water tile":
    let env = makeEmptyEnv()
    env.terrain[15][15] = Water
    let result = findNearestWater(env, ivec2(10, 10))
    check result == ivec2(15, 15)

  test "returns invalid when no water":
    let env = makeEmptyEnv()
    let result = findNearestWater(env, ivec2(10, 10))
    check result.x < 0

# =============================================================================
# Cache Infrastructure
# =============================================================================

suite "AI Core - PerAgentCache":
  test "invalidateIfStale clears all valid flags":
    var cache: PerAgentCache[int]
    cache.cacheStep = 0
    cache.valid[0] = true
    cache.valid[1] = true
    cache.invalidateIfStale(1)
    check cache.valid[0] == false
    check cache.valid[1] == false
    check cache.cacheStep == 1

  test "invalidateIfStale noop for same step":
    var cache: PerAgentCache[int]
    cache.cacheStep = 5
    cache.valid[0] = true
    cache.invalidateIfStale(5)
    check cache.valid[0] == true  # Not cleared

# =============================================================================
# isOscillating
# =============================================================================

suite "AI Core - isOscillating":
  test "not oscillating with empty history":
    var state = AgentState()
    check isOscillating(state) == false

  test "not oscillating with few positions":
    var state = AgentState()
    state.recentPosCount = 2
    state.recentPositions[0] = ivec2(10, 10)
    state.recentPositions[1] = ivec2(11, 10)
    check isOscillating(state) == false
