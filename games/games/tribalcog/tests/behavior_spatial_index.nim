import std/[unittest, strformat]
import test_common
import spatial_index
import common

## Behavioral tests for spatial index operations.
## Verifies that spatial queries handle edge cases like invalid positions
## without triggering OverflowDefect or other crashes.

suite "Behavior: Spatial Index Position Validation":
  test "findNearestThingSpatial handles valid positions":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let resource = addResource(env, Tree, ivec2(55, 50), ItemWood)

    env.rebuildSpatialIndex()
    let nearest = env.findNearestThingSpatial(agent.pos, Tree, 100)
    check nearest == resource
    echo "  Found nearest tree at valid position"

  test "findNearestThingSpatial returns nil when no things found":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    env.rebuildSpatialIndex()
    let nearest = env.findNearestThingSpatial(agent.pos, Tree, 100)
    check nearest == nil
    echo "  Returns nil when no trees in range"

  test "findNearestThingSpatial skips things with positions outside map bounds":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    # Create a thing and manually set invalid position (simulating corruption)
    let resource = Thing(kind: Tree, pos: ivec2(-10, -10))  # Invalid position
    resource.inventory = emptyInventory()
    setInv(resource, ItemWood, 10)
    env.things.add(resource)
    env.thingsByKind[Tree].add(resource)

    # Add a valid tree
    let validTree = addResource(env, Tree, ivec2(55, 50), ItemWood)

    env.rebuildSpatialIndex()

    # The invalid tree should not cause an overflow; only valid tree should be found
    let nearest = env.findNearestThingSpatial(agent.pos, Tree, 100)
    check nearest == validTree
    echo "  Skipped tree with invalid position, found valid tree"

  test "findNearestEnemyAgentSpatial handles agents with invalid positions":
    let env = makeEmptyEnv()
    let teamId = 0
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    # Add a valid enemy
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))

    env.rebuildSpatialIndex()

    # Should find the valid enemy without overflow
    let nearest = env.findNearestEnemyAgentSpatial(agent.pos, teamId, 100)
    check nearest == enemy
    echo "  Found enemy agent at valid position"

  test "collectEnemiesInRangeSpatial handles mixed valid/invalid positions":
    let env = makeEmptyEnv()
    let teamId = 0
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    # Add valid enemies at different distances
    let enemy1 = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))
    let enemy2 = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(52, 52))

    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectEnemiesInRangeSpatial(agent.pos, teamId, 10, targets)

    check targets.len == 2
    check enemy1 in targets
    check enemy2 in targets
    echo &"  Collected {targets.len} enemies in range"

  test "collectAlliesInRangeSpatial handles boundary positions":
    let env = makeEmptyEnv()
    let teamId = 0
    let agent = addAgentAt(env, 0, ivec2(MapBorder.int32, MapBorder.int32))  # Corner position

    # Add ally near the corner
    let ally = addAgentAt(env, 1, ivec2(MapBorder.int32 + 3, MapBorder.int32 + 3))

    env.rebuildSpatialIndex()

    var allies: seq[Thing] = @[]
    env.collectAlliesInRangeSpatial(agent.pos, teamId, 10, allies)

    check ally in allies
    echo "  Collected ally near map corner"

suite "Behavior: Spatial Index Robustness":
  test "spatial queries at map boundaries do not overflow":
    let env = makeEmptyEnv()

    # Test at all four corners
    let corners = [
      ivec2(MapBorder.int32, MapBorder.int32),  # NW
      ivec2((MapWidth - MapBorder - 1).int32, MapBorder.int32),  # NE
      ivec2(MapBorder.int32, (MapHeight - MapBorder - 1).int32),  # SW
      ivec2((MapWidth - MapBorder - 1).int32, (MapHeight - MapBorder - 1).int32)  # SE
    ]

    for i, corner in corners:
      discard addAgentAt(env, i, corner)

    env.rebuildSpatialIndex()

    # Query from each corner - should not crash
    for corner in corners:
      let nearest = env.findNearestThingSpatial(corner, Tree, 100)
      check nearest == nil  # No trees added

    echo "  Spatial queries at all four corners succeeded"

  test "large search radius does not overflow":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let tree = addResource(env, Tree, ivec2(200, 150), ItemWood)

    env.rebuildSpatialIndex()

    # Use a very large search radius
    let nearest = env.findNearestThingSpatial(agent.pos, Tree, int.high div 2)
    check nearest == tree
    echo "  Large search radius handled correctly"

  test "empty spatial index returns nil":
    let env = makeEmptyEnv()
    env.rebuildSpatialIndex()

    let result = env.findNearestThingSpatial(ivec2(50, 50), Tree, 100)
    check result == nil
    echo "  Empty spatial index returns nil"

  test "findNearestFriendlyThingSpatial with valid team":
    let env = makeEmptyEnv()
    let teamId = 0
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let house = addBuilding(env, House, ivec2(55, 50), teamId)

    env.rebuildSpatialIndex()

    let nearest = env.findNearestFriendlyThingSpatial(agent.pos, teamId, House, 100)
    check nearest == house
    echo "  Found friendly building"

  test "findNearestFriendlyThingSpatial ignores enemy buildings":
    let env = makeEmptyEnv()
    let teamId = 0
    let enemyTeamId = 1
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    # Add enemy building closer than friendly building
    let enemyHouse = addBuilding(env, House, ivec2(52, 50), enemyTeamId)
    let friendlyHouse = addBuilding(env, House, ivec2(60, 50), teamId)

    env.rebuildSpatialIndex()

    let nearest = env.findNearestFriendlyThingSpatial(agent.pos, teamId, House, 100)
    check nearest == friendlyHouse
    check nearest != enemyHouse
    echo "  Correctly ignored enemy building, found friendly building"

when defined(spatialAutoTune):
  suite "Behavior: Spatial Index Auto-Tuning":
    test "maybeTuneSpatialIndex initializes dynamic grid lazily":
      let env = makeEmptyEnv()
      env.rebuildSpatialIndex()

      # Dynamic grid should be initialized after rebuild
      check env.spatialIndex.activeCellSize > 0
      check env.spatialIndex.activeCellsX > 0
      check env.spatialIndex.activeCellsY > 0
      echo "  Dynamic grid initialized with cell size ", env.spatialIndex.activeCellSize

    test "analyzeCellDensity returns correct statistics":
      let env = makeEmptyEnv()

      # Add agents clustered in one area
      for i in 0 ..< 10:
        discard addAgentAt(env, i, ivec2(50 + i.int32, 50))

      env.rebuildSpatialIndex()
      let (maxCount, totalCount, nonEmpty) = env.spatialIndex.analyzeCellDensity()

      check totalCount == 10
      check maxCount >= 1
      check nonEmpty >= 1
      echo &"  Density: max={maxCount}, total={totalCount}, cells={nonEmpty}"

    test "computeOptimalCellSize recommends smaller cells for dense clusters":
      let env = makeEmptyEnv()

      # Add many agents in a very small area to create density hotspot
      for i in 0 ..< 50:
        discard addAgentAt(env, i mod MapAgentsPerTeam, ivec2(50 + (i mod 5).int32, 50 + (i div 5).int32))

      env.rebuildSpatialIndex()
      let initial = env.spatialIndex.activeCellSize
      let optimal = env.spatialIndex.computeOptimalCellSize()

      # With high density, should recommend smaller or equal cell size
      check optimal <= initial
      echo &"  Initial cell size: {initial}, optimal: {optimal}"

    test "maybeTuneSpatialIndex respects interval":
      let env = makeEmptyEnv()
      env.rebuildSpatialIndex()

      let initialLastTune = env.spatialIndex.lastTuneStep

      # Call at step 1 (should not tune yet if initial was 0)
      env.maybeTuneSpatialIndex(1)
      let afterFirstCall = env.spatialIndex.lastTuneStep

      # Call at step 50 (within interval, should not update lastTuneStep)
      env.maybeTuneSpatialIndex(50)
      let afterSecondCall = env.spatialIndex.lastTuneStep

      # lastTuneStep should remain at afterFirstCall since interval not reached
      check afterSecondCall == afterFirstCall
      echo &"  Tuning interval respected: lastTune stayed at {afterSecondCall}"

    test "queries still work after auto-tune resize":
      let env = makeEmptyEnv()
      let agent = addAgentAt(env, 0, ivec2(50, 50))
      let tree = addResource(env, Tree, ivec2(55, 50), ItemWood)

      env.rebuildSpatialIndex()

      # Force a tune check (this will initialize tracking)
      env.maybeTuneSpatialIndex(0)

      # Query should still work regardless of cell size
      let nearest = env.findNearestThingSpatial(agent.pos, Tree, 100)
      check nearest == tree
      echo "  Queries work correctly after auto-tune"

    test "density-based tuning: empty map uses large cells":
      # With no entities, should use maximum cell size to minimize overhead
      let optimal = computeOptimalCellSizeFromDensity(0)
      check optimal == SpatialMaxCellSize
      echo &"  Empty map optimal cell size: {optimal}"

    test "density-based tuning: few entities use large cells":
      # With very few entities, should still use large cells
      let optimal = computeOptimalCellSizeFromDensity(10)
      check optimal >= SpatialCellSize  # At least default size
      echo &"  10 entities optimal cell size: {optimal}"

    test "density-based tuning: many entities use smaller cells":
      # With many entities, should use smaller cells
      let optimal = computeOptimalCellSizeFromDensity(1000)
      check optimal <= SpatialCellSize  # At most default size
      check optimal >= SpatialMinCellSize
      echo &"  1000 entities optimal cell size: {optimal}"

    test "density-based tuning: scales with entity count":
      # More entities should result in smaller or equal cell size
      let opt100 = computeOptimalCellSizeFromDensity(100)
      let opt500 = computeOptimalCellSizeFromDensity(500)
      let opt2000 = computeOptimalCellSizeFromDensity(2000)

      check opt100 >= opt500
      check opt500 >= opt2000
      echo &"  Scaling: 100->{opt100}, 500->{opt500}, 2000->{opt2000}"

    test "density-based tuning: respects cell size bounds":
      # Should never exceed bounds
      let optMin = computeOptimalCellSizeFromDensity(100000)
      let optMax = computeOptimalCellSizeFromDensity(1)

      check optMin >= SpatialMinCellSize
      check optMax <= SpatialMaxCellSize
      echo &"  Bounds respected: min={optMin}, max={optMax}"
