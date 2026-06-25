import std/[unittest, sequtils, strformat]
import test_common
import spatial_index
import common

## Unit tests for spatial_index.nim - the most critical performance module.
## Covers index maintenance (add/remove/update/rebuild), all query functions,
## edge cases (empty cells, boundaries), and performance sanity.

# ============================================================================
# Helper: create a Tumor thing for tumor-related tests
# ============================================================================
proc addTumor(env: Environment, pos: IVec2, claimed: bool = false): Thing =
  let tumor = Thing(kind: Tumor, pos: pos)
  tumor.inventory = emptyInventory()
  tumor.hasClaimedTerritory = claimed
  env.add(tumor)
  tumor

# ============================================================================
# 1. Cell coordinate computation
# ============================================================================

suite "Unit: cellCoords":
  test "origin maps to cell (0, 0)":
    let (cx, cy) = cellCoords(ivec2(0, 0))
    check cx == 0
    check cy == 0

  test "position within first cell":
    let (cx, cy) = cellCoords(ivec2(10, 5))
    check cx == 0
    check cy == 0

  test "position at cell boundary":
    let (cx, cy) = cellCoords(ivec2(SpatialCellSize.int32, SpatialCellSize.int32))
    check cx == 1
    check cy == 1

  test "position in middle of map":
    let pos = ivec2(100, 80)
    let (cx, cy) = cellCoords(pos)
    check cx == 100 div SpatialCellSize
    check cy == 80 div SpatialCellSize

  test "position at map edge clamps to last cell":
    let (cx, cy) = cellCoords(ivec2((MapWidth - 1).int32, (MapHeight - 1).int32))
    check cx == SpatialCellsX - 1 or cx < SpatialCellsX
    check cy == SpatialCellsY - 1 or cy < SpatialCellsY

  test "negative position clamps to zero":
    let (cx, cy) = cellCoords(ivec2(-5, -10))
    check cx == 0
    check cy == 0

# ============================================================================
# 2. Index maintenance: add, remove, update, rebuild
# ============================================================================

suite "Unit: addToSpatialIndex / removeFromSpatialIndex":
  test "adding a thing makes it findable":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(50, 50), ItemWood)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 10)
    check found == tree

  test "removing a thing makes it unfindable":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(50, 50), ItemWood)
    env.rebuildSpatialIndex()

    env.removeFromSpatialIndex(tree)
    let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 10)
    check found == nil

  test "add and remove nil does not crash":
    let env = makeEmptyEnv()
    env.rebuildSpatialIndex()
    env.addToSpatialIndex(nil)
    env.removeFromSpatialIndex(nil)
    # No crash = pass

  test "add thing with invalid position is silently skipped":
    let env = makeEmptyEnv()
    env.rebuildSpatialIndex()
    let badThing = Thing(kind: Tree, pos: ivec2(-5, -5))
    badThing.inventory = emptyInventory()
    env.addToSpatialIndex(badThing)
    let found = env.findNearestThingSpatial(ivec2(0, 0), Tree, 100)
    check found == nil

  test "remove thing not in index does not crash":
    let env = makeEmptyEnv()
    env.rebuildSpatialIndex()
    let tree = Thing(kind: Tree, pos: ivec2(50, 50))
    tree.inventory = emptyInventory()
    # Never added, but try to remove
    env.removeFromSpatialIndex(tree)
    # No crash = pass

suite "Unit: updateSpatialIndex":
  test "moved thing is found at new position":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(50, 50), ItemWood)
    env.rebuildSpatialIndex()

    let oldPos = tree.pos
    tree.pos = ivec2(100, 100)
    env.updateSpatialIndex(tree, oldPos)

    let foundOld = env.findNearestThingSpatial(ivec2(50, 50), Tree, 5)
    let foundNew = env.findNearestThingSpatial(ivec2(100, 100), Tree, 5)
    check foundOld == nil
    check foundNew == tree

  test "update within same cell does not break index":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(50, 50), ItemWood)
    env.rebuildSpatialIndex()

    let oldPos = tree.pos
    # Move within same cell (small movement)
    tree.pos = ivec2(51, 51)
    env.updateSpatialIndex(tree, oldPos)

    let found = env.findNearestThingSpatial(ivec2(51, 51), Tree, 5)
    check found == tree

  test "update nil thing does not crash":
    let env = makeEmptyEnv()
    env.rebuildSpatialIndex()
    env.updateSpatialIndex(nil, ivec2(0, 0))

suite "Unit: rebuildSpatialIndex":
  test "rebuild correctly indexes all things":
    let env = makeEmptyEnv()
    let t1 = addResource(env, Tree, ivec2(20, 20), ItemWood)
    let t2 = addResource(env, Tree, ivec2(80, 80), ItemWood)
    let t3 = addResource(env, Tree, ivec2(150, 50), ItemWood)

    env.rebuildSpatialIndex()

    check env.findNearestThingSpatial(ivec2(20, 20), Tree, 5) == t1
    check env.findNearestThingSpatial(ivec2(80, 80), Tree, 5) == t2
    check env.findNearestThingSpatial(ivec2(150, 50), Tree, 5) == t3

  test "rebuild after adding more things includes new things":
    let env = makeEmptyEnv()
    let t1 = addResource(env, Tree, ivec2(50, 50), ItemWood)
    env.rebuildSpatialIndex()

    let t2 = addResource(env, Tree, ivec2(100, 100), ItemWood)
    env.rebuildSpatialIndex()

    check env.findNearestThingSpatial(ivec2(50, 50), Tree, 5) == t1
    check env.findNearestThingSpatial(ivec2(100, 100), Tree, 5) == t2

  test "rebuild on empty environment does not crash":
    let env = makeEmptyEnv()
    env.rebuildSpatialIndex()
    let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 100)
    check found == nil

# ============================================================================
# 3. collectThingsInRangeSpatial (hottest function - 83% of queries)
# ============================================================================

suite "Unit: collectThingsInRangeSpatial":
  test "collects all trees within range":
    let env = makeEmptyEnv()
    let t1 = addResource(env, Tree, ivec2(50, 50), ItemWood)
    let t2 = addResource(env, Tree, ivec2(55, 50), ItemWood)
    let t3 = addResource(env, Tree, ivec2(60, 50), ItemWood)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectThingsInRangeSpatial(ivec2(50, 50), Tree, 15, targets)
    check targets.len == 3
    check t1 in targets
    check t2 in targets
    check t3 in targets

  test "excludes trees outside range":
    let env = makeEmptyEnv()
    let near = addResource(env, Tree, ivec2(50, 50), ItemWood)
    let far = addResource(env, Tree, ivec2(200, 200), ItemWood)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectThingsInRangeSpatial(ivec2(50, 50), Tree, 20, targets)
    check near in targets
    check far notin targets

  test "empty result when no things of kind in range":
    let env = makeEmptyEnv()
    discard addResource(env, Gold, ivec2(50, 50), ItemGold)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectThingsInRangeSpatial(ivec2(50, 50), Tree, 100, targets)
    check targets.len == 0

  test "collects from multiple cells":
    let env = makeEmptyEnv()
    # Place trees across different cells (cell size = 16)
    let t1 = addResource(env, Tree, ivec2(10, 10), ItemWood)
    let t2 = addResource(env, Tree, ivec2(30, 10), ItemWood)
    let t3 = addResource(env, Tree, ivec2(50, 10), ItemWood)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectThingsInRangeSpatial(ivec2(30, 10), Tree, 50, targets)
    check t1 in targets
    check t2 in targets
    check t3 in targets

  test "large population in range":
    let env = makeEmptyEnv()
    var expected: seq[Thing] = @[]
    for i in 0 ..< 20:
      let t = addResource(env, Tree, ivec2((40 + i * 2).int32, 50), ItemWood)
      expected.add(t)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectThingsInRangeSpatial(ivec2(60, 50), Tree, 50, targets)
    check targets.len == expected.len

# ============================================================================
# 4. findNearestThingOfKindsSpatial (multi-kind queries)
# ============================================================================

suite "Unit: findNearestThingOfKindsSpatial":
  test "finds nearest among multiple kinds":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(60, 50), ItemWood)
    let gold = addResource(env, Gold, ivec2(52, 50), ItemGold)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingOfKindsSpatial(ivec2(50, 50), {Tree, Gold}, 100)
    check found == gold  # gold is closer

  test "returns nil when no matching kinds in range":
    let env = makeEmptyEnv()
    discard addResource(env, Stone, ivec2(50, 50), ItemStone)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingOfKindsSpatial(ivec2(50, 50), {Tree, Gold}, 100)
    check found == nil

  test "single kind set behaves like findNearestThingSpatial":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(55, 50), ItemWood)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingOfKindsSpatial(ivec2(50, 50), {Tree}, 100)
    check found == tree

# ============================================================================
# 5. findNearestEnemyInRangeSpatial (range band queries)
# ============================================================================

suite "Unit: findNearestEnemyInRangeSpatial":
  test "finds enemy in range band":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(60, 50))
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyInRangeSpatial(ivec2(50, 50), 0, 5, 20)
    check found == enemy

  test "ignores enemy below min range":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(52, 50))  # Too close
    let farEnemy = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(60, 50))
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyInRangeSpatial(ivec2(50, 50), 0, 5, 20)
    check found == farEnemy

  test "returns nil when no enemy in band":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(52, 50))  # Too close (dist 2, min 5)
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyInRangeSpatial(ivec2(50, 50), 0, 5, 20)
    check found == nil

# ============================================================================
# 6. findNearestEnemyBuildingSpatial
# ============================================================================

suite "Unit: findNearestEnemyBuildingSpatial":
  test "finds nearest enemy building":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    let enemyHouse = addBuilding(env, House, ivec2(60, 50), 1)
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyBuildingSpatial(ivec2(50, 50), 0)
    check found == enemyHouse

  test "ignores friendly buildings":
    let env = makeEmptyEnv()
    discard addBuilding(env, House, ivec2(55, 50), 0)  # Friendly
    let enemyHouse = addBuilding(env, House, ivec2(70, 50), 1)
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyBuildingSpatial(ivec2(50, 50), 0)
    check found == enemyHouse

  test "returns nil when no enemy buildings":
    let env = makeEmptyEnv()
    discard addBuilding(env, House, ivec2(55, 50), 0)  # Friendly only
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyBuildingSpatial(ivec2(50, 50), 0)
    check found == nil

# ============================================================================
# 7. findNearestEnemyPresenceSpatial (agents + buildings)
# ============================================================================

suite "Unit: findNearestEnemyPresenceSpatial":
  test "finds nearest enemy agent":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))
    env.rebuildSpatialIndex()

    let (target, dist) = env.findNearestEnemyPresenceSpatial(ivec2(50, 50), 0)
    check target == enemy.pos
    check dist == 5

  test "finds nearest enemy building when closer than agent":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(70, 50))
    let enemyHouse = addBuilding(env, House, ivec2(55, 50), 1)
    env.rebuildSpatialIndex()

    let (target, dist) = env.findNearestEnemyPresenceSpatial(ivec2(50, 50), 0)
    check target == enemyHouse.pos
    check dist == 5

  test "returns (-1,-1) when no enemies":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    env.rebuildSpatialIndex()

    let (target, dist) = env.findNearestEnemyPresenceSpatial(ivec2(50, 50), 0)
    check target.x == -1
    check target.y == -1

# ============================================================================
# 8. collectAgentsByClassInRange
# ============================================================================

suite "Unit: collectAgentsByClassInRange":
  test "collects agents of matching class":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(50, 50), unitClass = UnitArcher)
    let villager = addAgentAt(env, 1, ivec2(55, 50), unitClass = UnitVillager)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectAgentsByClassInRange(ivec2(50, 50), 0, {UnitArcher}, 20, targets)
    check archer in targets
    check villager notin targets

  test "teamId -1 collects from all teams":
    let env = makeEmptyEnv()
    let friendly = addAgentAt(env, 0, ivec2(50, 50), unitClass = UnitKnight)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50), unitClass = UnitKnight)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectAgentsByClassInRange(ivec2(50, 50), -1, {UnitKnight}, 20, targets)
    check targets.len == 2
    check friendly in targets
    check enemy in targets

  test "specific teamId filters to that team only":
    let env = makeEmptyEnv()
    let friendly = addAgentAt(env, 0, ivec2(50, 50), unitClass = UnitKnight)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50), unitClass = UnitKnight)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectAgentsByClassInRange(ivec2(50, 50), 0, {UnitKnight}, 20, targets)
    check friendly in targets
    check enemy notin targets

  test "empty when no matching class":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50), unitClass = UnitVillager)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectAgentsByClassInRange(ivec2(50, 50), 0, {UnitKnight}, 20, targets)
    check targets.len == 0

# ============================================================================
# 9. countUnclaimedTumorsInRangeSpatial
# ============================================================================

suite "Unit: countUnclaimedTumorsInRangeSpatial":
  test "counts unclaimed tumors only":
    let env = makeEmptyEnv()
    discard addTumor(env, ivec2(50, 50), claimed = false)
    discard addTumor(env, ivec2(55, 50), claimed = false)
    discard addTumor(env, ivec2(60, 50), claimed = true)  # Should be excluded
    env.rebuildSpatialIndex()

    let count = env.countUnclaimedTumorsInRangeSpatial(ivec2(50, 50), 20)
    check count == 2

  test "returns 0 when all tumors are claimed":
    let env = makeEmptyEnv()
    discard addTumor(env, ivec2(50, 50), claimed = true)
    env.rebuildSpatialIndex()

    let count = env.countUnclaimedTumorsInRangeSpatial(ivec2(50, 50), 20)
    check count == 0

  test "returns 0 when no tumors in range":
    let env = makeEmptyEnv()
    discard addTumor(env, ivec2(200, 200), claimed = false)
    env.rebuildSpatialIndex()

    let count = env.countUnclaimedTumorsInRangeSpatial(ivec2(50, 50), 20)
    check count == 0

# ============================================================================
# 10. findNearestPredatorTargetSpatial (priority: tumor > fighter > villager)
# ============================================================================

suite "Unit: findNearestPredatorTargetSpatial":
  test "prefers unclaimed tumor over agents":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(52, 50), unitClass = UnitVillager)
    discard addTumor(env, ivec2(55, 50), claimed = false)
    env.rebuildSpatialIndex()

    let target = env.findNearestPredatorTargetSpatial(ivec2(50, 50), 100)
    check target == ivec2(55, 50)

  test "prefers fighter over villager":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(52, 50), unitClass = UnitVillager)
    discard addAgentAt(env, 1, ivec2(55, 50), unitClass = UnitManAtArms)
    env.rebuildSpatialIndex()

    let target = env.findNearestPredatorTargetSpatial(ivec2(50, 50), 100)
    check target == ivec2(55, 50)

  test "returns villager when no tumors or fighters":
    let env = makeEmptyEnv()
    let villager = addAgentAt(env, 0, ivec2(55, 50), unitClass = UnitVillager)
    env.rebuildSpatialIndex()

    let target = env.findNearestPredatorTargetSpatial(ivec2(50, 50), 100)
    check target == villager.pos

  test "returns (-1,-1) when no targets":
    let env = makeEmptyEnv()
    env.rebuildSpatialIndex()

    let target = env.findNearestPredatorTargetSpatial(ivec2(50, 50), 100)
    check target.x == -1
    check target.y == -1

  test "ignores claimed tumors":
    let env = makeEmptyEnv()
    discard addTumor(env, ivec2(55, 50), claimed = true)
    let villager = addAgentAt(env, 0, ivec2(60, 50), unitClass = UnitVillager)
    env.rebuildSpatialIndex()

    let target = env.findNearestPredatorTargetSpatial(ivec2(50, 50), 100)
    check target == villager.pos

# ============================================================================
# 11. Edge cases: boundary positions, cross-cell queries
# ============================================================================

suite "Unit: Spatial Index Edge Cases":
  test "query from map corner (0, 0) area":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(MapBorder.int32 + 2, MapBorder.int32 + 2), ItemWood)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingSpatial(ivec2(MapBorder.int32, MapBorder.int32), Tree, 10)
    check found == tree

  test "query from max map corner":
    let env = makeEmptyEnv()
    let maxX = (MapWidth - MapBorder - 1).int32
    let maxY = (MapHeight - MapBorder - 1).int32
    let tree = addResource(env, Tree, ivec2(maxX - 3, maxY - 3), ItemWood)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingSpatial(ivec2(maxX, maxY), Tree, 10)
    check found == tree

  test "things at exact same position":
    let env = makeEmptyEnv()
    let t1 = addResource(env, Tree, ivec2(50, 50), ItemWood)
    let t2 = addResource(env, Tree, ivec2(50, 50), ItemWood)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectThingsInRangeSpatial(ivec2(50, 50), Tree, 5, targets)
    check targets.len == 2
    check t1 in targets
    check t2 in targets

  test "different kinds in same cell don't interfere":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(50, 50), ItemWood)
    let gold = addResource(env, Gold, ivec2(52, 52), ItemGold)
    env.rebuildSpatialIndex()

    let foundTree = env.findNearestThingSpatial(ivec2(50, 50), Tree, 10)
    let foundGold = env.findNearestThingSpatial(ivec2(50, 50), Gold, 10)
    check foundTree == tree
    check foundGold == gold

    var treeTargets: seq[Thing] = @[]
    env.collectThingsInRangeSpatial(ivec2(50, 50), Tree, 10, treeTargets)
    check treeTargets.len == 1
    check treeTargets[0] == tree

# ============================================================================
# 12. Lookup table correctness
# ============================================================================

suite "Unit: distToCellRadius16 lookup":
  test "distance 0 gives radius 0":
    check distToCellRadius16(0) == 0

  test "distance 1 gives radius 1":
    check distToCellRadius16(1) == 1

  test "distance exactly cell size gives radius 1":
    check distToCellRadius16(SpatialCellSize) == 1

  test "distance cell size + 1 gives radius 2":
    check distToCellRadius16(SpatialCellSize + 1) == 2

  test "lookup matches arithmetic for various distances":
    for d in [0, 1, 8, 15, 16, 17, 32, 64, 100, 200, 300, 511]:
      let expected = (d + SpatialCellSize - 1) div SpatialCellSize
      let actual = distToCellRadius16(d)
      check actual == expected

  test "large distance clamps to MaxLookupDist - 1":
    let result = distToCellRadius16(999999)
    check result == DistToCellRadius16[MaxLookupDist - 1].int

# ============================================================================
# 13. NeighborOffsets correctness
# ============================================================================

suite "Unit: NeighborOffsets pre-computed tables":
  test "radius 0 has exactly 1 offset (0,0)":
    check NeighborOffsets[0].len == 1
    check NeighborOffsets[0][0].dx == 0
    check NeighborOffsets[0][0].dy == 0

  test "radius 1 has 9 offsets":
    check NeighborOffsets[1].len == 9
    check NeighborOffsetCounts[1] == 9

  test "radius 2 has 25 offsets":
    check NeighborOffsets[2].len == 25
    check NeighborOffsetCounts[2] == 25

  test "offset counts match formula (2r+1)^2":
    for r in 0 .. min(5, MaxPrecomputedRadius):
      let expected = (2 * r + 1) * (2 * r + 1)
      check NeighborOffsets[r].len == expected
      check NeighborOffsetCounts[r] == expected

  test "offsets are sorted by Chebyshev distance":
    for r in [1, 3, 5]:
      var lastDist = 0
      for offset in NeighborOffsets[r]:
        let dist = max(abs(offset.dx.int), abs(offset.dy.int))
        check dist >= lastDist
        lastDist = dist

# ============================================================================
# 14. findNearestThingSpatial (dedicated tests)
# ============================================================================

suite "Unit: findNearestThingSpatial":
  test "finds nearest tree of multiple":
    let env = makeEmptyEnv()
    let far = addResource(env, Tree, ivec2(80, 50), ItemWood)
    let near = addResource(env, Tree, ivec2(55, 50), ItemWood)
    let mid = addResource(env, Tree, ivec2(65, 50), ItemWood)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 100)
    check found == near

  test "returns nil when kind not present":
    let env = makeEmptyEnv()
    discard addResource(env, Gold, ivec2(55, 50), ItemGold)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 100)
    check found == nil

  test "returns nil when all outside maxDist":
    let env = makeEmptyEnv()
    discard addResource(env, Tree, ivec2(200, 200), ItemWood)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 50)
    check found == nil

  test "finds thing at exact maxDist boundary":
    let env = makeEmptyEnv()
    # Manhattan distance: |60-50| + |50-50| = 10
    let tree = addResource(env, Tree, ivec2(60, 50), ItemWood)
    env.rebuildSpatialIndex()

    # maxDist is exclusive, so 10 should NOT be found at maxDist=10
    let notFound = env.findNearestThingSpatial(ivec2(50, 50), Tree, 10)
    check notFound == nil

    # But should be found at maxDist=11
    let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 11)
    check found == tree

  test "finds thing across cell boundary":
    let env = makeEmptyEnv()
    # Place tree in different cell (SpatialCellSize=16)
    let tree = addResource(env, Tree, ivec2(70, 50), ItemWood)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 50)
    check found == tree

  test "handles query from edge of map":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(MapBorder.int32 + 5, MapBorder.int32 + 5), ItemWood)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingSpatial(ivec2(MapBorder.int32, MapBorder.int32), Tree, 20)
    check found == tree

# ============================================================================
# 15. findNearestFriendlyThingSpatial
# ============================================================================

suite "Unit: findNearestFriendlyThingSpatial":
  test "finds nearest friendly building":
    let env = makeEmptyEnv()
    let farFriendly = addBuilding(env, House, ivec2(80, 50), 0)
    let nearFriendly = addBuilding(env, House, ivec2(55, 50), 0)
    discard addBuilding(env, House, ivec2(52, 50), 1)  # Enemy, even closer
    env.rebuildSpatialIndex()

    let found = env.findNearestFriendlyThingSpatial(ivec2(50, 50), 0, House, 100)
    check found == nearFriendly

  test "ignores enemy buildings":
    let env = makeEmptyEnv()
    discard addBuilding(env, House, ivec2(55, 50), 1)  # Enemy
    let friendly = addBuilding(env, House, ivec2(70, 50), 0)  # Friendly but farther
    env.rebuildSpatialIndex()

    let found = env.findNearestFriendlyThingSpatial(ivec2(50, 50), 0, House, 100)
    check found == friendly

  test "returns nil when no friendly buildings in range":
    let env = makeEmptyEnv()
    discard addBuilding(env, House, ivec2(55, 50), 1)  # Enemy only
    env.rebuildSpatialIndex()

    let found = env.findNearestFriendlyThingSpatial(ivec2(50, 50), 0, House, 100)
    check found == nil

  test "finds friendly resource node (unowned)":
    let env = makeEmptyEnv()
    # Resources have teamId = 0 by default (Thing default), which means
    # team 0 can find them as "friendly" since team mask matches
    let tree = addResource(env, Tree, ivec2(55, 50), ItemWood)
    env.rebuildSpatialIndex()

    # Tree has default teamId=0, so team 0 finds it as friendly
    let found = env.findNearestFriendlyThingSpatial(ivec2(50, 50), 0, Tree, 100)
    check found == tree  # Default teamId is 0, so it's found as friendly

    # Team 1 should NOT find it since teamId=0
    let notFound = env.findNearestFriendlyThingSpatial(ivec2(50, 50), 1, Tree, 100)
    check notFound == nil

  test "works with Altar kind":
    let env = makeEmptyEnv()
    let altar = addAltar(env, ivec2(60, 50), 0, 3)
    discard addAltar(env, ivec2(55, 50), 1, 3)  # Enemy altar closer
    env.rebuildSpatialIndex()

    let found = env.findNearestFriendlyThingSpatial(ivec2(50, 50), 0, Altar, 100)
    check found == altar

  test "respects maxDist limit":
    let env = makeEmptyEnv()
    discard addBuilding(env, House, ivec2(100, 50), 0)  # Friendly but far
    env.rebuildSpatialIndex()

    let found = env.findNearestFriendlyThingSpatial(ivec2(50, 50), 0, House, 30)
    check found == nil

# ============================================================================
# 16. findNearestEnemyAgentSpatial
# ============================================================================

suite "Unit: findNearestEnemyAgentSpatial":
  test "finds nearest enemy agent":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))  # Query origin (team 0)
    # Create agents in ascending order to avoid dummy creation issues
    let nearEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))
    let farEnemy = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(70, 50))
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 100)
    check found == nearEnemy

  test "ignores friendly agents":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))  # Team 0
    discard addAgentAt(env, 1, ivec2(52, 50))  # Team 0, very close
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(60, 50))  # Team 1
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 100)
    check found == enemy

  test "returns nil when no enemies":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    discard addAgentAt(env, 1, ivec2(55, 50))  # Same team
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 100)
    check found == nil

  test "ignores dead enemy agents":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    # Create in ascending order; mark first one as dead
    let deadEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(52, 50))
    deadEnemy.hp = 0  # Mark as dead
    env.terminated[MapAgentsPerTeam] = 1.0  # Also mark terminated
    let aliveEnemy = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(60, 50))
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 100)
    check found == aliveEnemy

  test "uses Chebyshev distance":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    # Chebyshev: max(|55-50|, |55-50|) = 5 (diagonal)
    let diag = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 55))
    # Chebyshev: max(|56-50|, |50-50|) = 6 (horizontal)
    let horiz = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(56, 50))
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 100)
    check found == diag  # Diagonal is closer in Chebyshev

  test "respects maxDist limit":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(100, 50))  # Too far
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 30)
    check found == nil

  test "finds enemy at exact maxDist":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(60, 50))  # Chebyshev dist = 10
    env.rebuildSpatialIndex()

    let found = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 10)
    check found == enemy  # Should be found at exactly maxDist

# ============================================================================
# 17. collectEnemiesInRangeSpatial (extended coverage)
# ============================================================================

suite "Unit: collectEnemiesInRangeSpatial":
  test "collects all enemies in range":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))  # Team 0 origin
    let e1 = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))
    let e2 = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(52, 55))
    let e3 = addAgentAt(env, MapAgentsPerTeam + 2, ivec2(58, 50))
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectEnemiesInRangeSpatial(ivec2(50, 50), 0, 20, targets)
    check targets.len == 3
    check e1 in targets
    check e2 in targets
    check e3 in targets

  test "excludes friendlies":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    discard addAgentAt(env, 1, ivec2(52, 50))  # Friendly
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectEnemiesInRangeSpatial(ivec2(50, 50), 0, 20, targets)
    check targets.len == 1
    check enemy in targets

  test "excludes dead enemies":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    # Create in ascending order; mark first one as dead
    let dead = addAgentAt(env, MapAgentsPerTeam, ivec2(52, 50))
    dead.hp = 0
    env.terminated[MapAgentsPerTeam] = 1.0  # Also mark terminated
    let alive = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(55, 50))
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectEnemiesInRangeSpatial(ivec2(50, 50), 0, 20, targets)
    check targets.len == 1
    check alive in targets
    check dead notin targets

  test "empty when no enemies in range":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(200, 200))  # Far away
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectEnemiesInRangeSpatial(ivec2(50, 50), 0, 20, targets)
    check targets.len == 0

  test "appends to existing sequence":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[nil, nil]  # Pre-existing items
    env.collectEnemiesInRangeSpatial(ivec2(50, 50), 0, 20, targets)
    check targets.len == 3
    check enemy in targets

  test "works across cell boundaries":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))
    # Place enemies in different cells (cell size = 16)
    let e1 = addAgentAt(env, MapAgentsPerTeam, ivec2(30, 50))
    let e2 = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(70, 50))
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectEnemiesInRangeSpatial(ivec2(50, 50), 0, 30, targets)
    check targets.len == 2
    check e1 in targets
    check e2 in targets

# ============================================================================
# 18. collectAlliesInRangeSpatial
# ============================================================================

suite "Unit: collectAlliesInRangeSpatial":
  test "collects all allies in range":
    let env = makeEmptyEnv()
    let origin = addAgentAt(env, 0, ivec2(50, 50))  # Team 0 origin
    let a1 = addAgentAt(env, 1, ivec2(55, 50))  # Same team
    let a2 = addAgentAt(env, 2, ivec2(52, 55))  # Same team
    env.rebuildSpatialIndex()

    var allies: seq[Thing] = @[]
    env.collectAlliesInRangeSpatial(ivec2(50, 50), 0, 20, allies)
    check allies.len == 3  # Including the origin agent
    check origin in allies
    check a1 in allies
    check a2 in allies

  test "excludes enemies":
    let env = makeEmptyEnv()
    # Create in ascending order (team 0 agents first, then team 1)
    let origin = addAgentAt(env, 0, ivec2(50, 50))
    let ally = addAgentAt(env, 1, ivec2(55, 50))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(52, 50))  # Enemy
    env.rebuildSpatialIndex()

    var allies: seq[Thing] = @[]
    env.collectAlliesInRangeSpatial(ivec2(50, 50), 0, 20, allies)
    check origin in allies
    check ally in allies
    check enemy notin allies
    check allies.len == 2

  test "excludes dead allies":
    let env = makeEmptyEnv()
    let alive = addAgentAt(env, 0, ivec2(50, 50))
    let dead = addAgentAt(env, 1, ivec2(52, 50))
    dead.hp = 0
    env.terminated[1] = 1.0  # Also mark terminated
    env.rebuildSpatialIndex()

    var allies: seq[Thing] = @[]
    env.collectAlliesInRangeSpatial(ivec2(50, 50), 0, 20, allies)
    check allies.len == 1
    check alive in allies
    check dead notin allies

  test "empty when no allies in range":
    let env = makeEmptyEnv()
    let origin = addAgentAt(env, 0, ivec2(50, 50))
    discard addAgentAt(env, 1, ivec2(200, 200))  # Far away
    env.rebuildSpatialIndex()

    var allies: seq[Thing] = @[]
    env.collectAlliesInRangeSpatial(ivec2(50, 50), 0, 5, allies)
    check allies.len == 1  # Only the origin agent is in range
    check origin in allies

  test "works across cell boundaries":
    let env = makeEmptyEnv()
    let origin = addAgentAt(env, 0, ivec2(50, 50))
    let a1 = addAgentAt(env, 1, ivec2(30, 50))
    let a2 = addAgentAt(env, 2, ivec2(70, 50))
    env.rebuildSpatialIndex()

    var allies: seq[Thing] = @[]
    env.collectAlliesInRangeSpatial(ivec2(50, 50), 0, 30, allies)
    check origin in allies
    check a1 in allies
    check a2 in allies

# ============================================================================
# 19. Entity movement between cells
# ============================================================================

suite "Unit: Entity Movement Between Cells":
  test "entity found after moving to different cell":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(10, 10), ItemWood)
    env.rebuildSpatialIndex()

    # Verify found at original position
    let found1 = env.findNearestThingSpatial(ivec2(10, 10), Tree, 5)
    check found1 == tree

    # Move to a different cell (cell size = 16, so 10 -> 50 crosses cells)
    let oldPos = tree.pos
    tree.pos = ivec2(50, 50)
    env.updateSpatialIndex(tree, oldPos)

    # Should NOT be found at old position
    let found2 = env.findNearestThingSpatial(ivec2(10, 10), Tree, 5)
    check found2 == nil

    # Should be found at new position
    let found3 = env.findNearestThingSpatial(ivec2(50, 50), Tree, 5)
    check found3 == tree

  test "multiple entities moving between cells":
    let env = makeEmptyEnv()
    let t1 = addResource(env, Tree, ivec2(10, 10), ItemWood)
    let t2 = addResource(env, Tree, ivec2(20, 10), ItemWood)
    env.rebuildSpatialIndex()

    # Move both to different cells
    let old1 = t1.pos
    let old2 = t2.pos
    t1.pos = ivec2(50, 50)
    t2.pos = ivec2(80, 80)
    env.updateSpatialIndex(t1, old1)
    env.updateSpatialIndex(t2, old2)

    # Verify they're found at new positions
    var targets: seq[Thing] = @[]
    env.collectThingsInRangeSpatial(ivec2(65, 65), Tree, 50, targets)
    check t1 in targets
    check t2 in targets

  test "agent movement updates spatial index":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))  # Team 0
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))  # Team 1
    env.rebuildSpatialIndex()

    # Found at original position
    let found1 = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 100)
    check found1 == enemy

    # Move enemy far away - also update the grid (use valid map coords < 192)
    let oldPos = enemy.pos
    env.grid[oldPos.x][oldPos.y] = nil
    enemy.pos = ivec2(150, 150)  # Still within map bounds (192x192)
    env.grid[enemy.pos.x][enemy.pos.y] = enemy
    env.updateSpatialIndex(enemy, oldPos)

    # Not found in small range
    let found2 = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 50)
    check found2 == nil

    # Found in large range
    let found3 = env.findNearestEnemyAgentSpatial(ivec2(50, 50), 0, 150)
    check found3 == enemy

  test "movement within same cell preserves findability":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(50, 50), ItemWood)
    env.rebuildSpatialIndex()

    # Small move within same cell (cell size = 16)
    let oldPos = tree.pos
    tree.pos = ivec2(51, 51)
    env.updateSpatialIndex(tree, oldPos)

    let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 10)
    check found == tree

# ============================================================================
# 20. Performance sanity: queries on populated index
# ============================================================================

suite "Unit: Spatial Index Performance Sanity":
  test "findNearestThingSpatial with many trees completes":
    let env = makeEmptyEnv()
    # Scatter 100 trees across the map
    for i in 0 ..< 100:
      let x = (MapBorder + 10 + (i * 7) mod (MapWidth - 2 * MapBorder - 20)).int32
      let y = (MapBorder + 10 + (i * 13) mod (MapHeight - 2 * MapBorder - 20)).int32
      discard addResource(env, Tree, ivec2(x, y), ItemWood)
    env.rebuildSpatialIndex()

    let found = env.findNearestThingSpatial(ivec2(100, 100), Tree, 200)
    check found != nil

  test "collectThingsInRangeSpatial with many items completes":
    let env = makeEmptyEnv()
    for i in 0 ..< 50:
      let x = (40 + i mod 10 * 3).int32
      let y = (40 + i div 10 * 3).int32
      discard addResource(env, Tree, ivec2(x, y), ItemWood)
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectThingsInRangeSpatial(ivec2(55, 50), Tree, 50, targets)
    check targets.len > 0

  test "collectEnemiesInRangeSpatial with multiple enemies":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(50, 50))  # Team 0 origin

    # Add 3 enemies on team 1 close to origin
    let e1 = addAgentAt(env, MapAgentsPerTeam, ivec2(52, 50))
    let e2 = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(54, 50))
    let e3 = addAgentAt(env, MapAgentsPerTeam + 2, ivec2(56, 50))
    env.rebuildSpatialIndex()

    var targets: seq[Thing] = @[]
    env.collectEnemiesInRangeSpatial(ivec2(50, 50), 0, 30, targets)
    check targets.len == 3
    check e1 in targets
    check e2 in targets
    check e3 in targets

  test "repeated rebuild does not leak or corrupt":
    let env = makeEmptyEnv()
    discard addResource(env, Tree, ivec2(50, 50), ItemWood)

    for i in 0 ..< 5:
      env.rebuildSpatialIndex()
      let found = env.findNearestThingSpatial(ivec2(50, 50), Tree, 10)
      check found != nil
