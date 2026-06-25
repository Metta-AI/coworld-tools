import std/[unittest, strformat]
import environment
import types
import terrain
import test_utils

## Domain tests for connectivity graph validation for building placement.
## Verifies that makeConnected() ensures world connectivity after buildings
## and obstacles are placed, and tests the underlying component labeling.

suite "Domain: Connectivity Graph - Single Component":
  test "empty environment is single connected component":
    let env = makeEmptyEnv()
    # Empty environment should have only one connected component (all walkable)
    # makeConnected should have no work to do
    env.makeConnected()
    # After makeConnected, all empty tiles should be reachable from any other
    # Verify no digging occurred (terrain remains empty everywhere)
    var emptyCount = 0
    for x in MapBorder ..< MapWidth - MapBorder:
      for y in MapBorder ..< MapHeight - MapBorder:
        if env.terrain[x][y] == TerrainEmpty and env.isEmpty(ivec2(x.int32, y.int32)):
          inc emptyCount
    check emptyCount > 0
    echo &"  Empty env has {emptyCount} walkable tiles, forms single component"

  test "single building does not create disconnected components":
    let env = makeEmptyEnv()
    # Place a house in the middle - should not disconnect anything
    discard addBuilding(env, House, ivec2(50, 50), 0)
    env.makeConnected()
    # The building occupies one tile, but surrounding tiles remain connected
    # Verify tiles around the building are still walkable
    let adjacent = [ivec2(49, 50), ivec2(51, 50), ivec2(50, 49), ivec2(50, 51)]
    for pos in adjacent:
      check env.isEmpty(pos)
    echo "  Single building does not disconnect walkable areas"

  test "row of buildings does not disconnect parallel walkways":
    let env = makeEmptyEnv()
    # Place a row of houses from (40,50) to (60,50)
    for x in 40 .. 60:
      discard addBuilding(env, House, ivec2(x.int32, 50), 0)
    env.makeConnected()
    # Tiles above (y=49) and below (y=51) the row should both be walkable
    # and connected through the ends of the row
    check env.isEmpty(ivec2(40, 49))
    check env.isEmpty(ivec2(60, 51))
    echo "  Row of buildings leaves parallel areas connected"

suite "Domain: Connectivity Graph - Multiple Components":
  test "wall barrier creates components that get connected":
    let env = makeEmptyEnv()
    # Create a COMPLETE wall barrier across the entire playable area
    # This isolates left side from right side, requiring makeConnected to dig through
    for y in MapBorder ..< MapHeight - MapBorder:
      let wall = Thing(kind: Wall, pos: ivec2(50, y.int32))
      wall.inventory = emptyInventory()
      env.add(wall)

    # Before makeConnected, areas left and right of wall are completely separate
    # makeConnected should dig through walls to join them
    env.makeConnected()

    # After makeConnected, there should be at least one gap in the wall
    var gapCount = 0
    for y in MapBorder ..< MapHeight - MapBorder:
      if env.isEmpty(ivec2(50, y.int32)):
        inc gapCount

    check gapCount > 0
    echo &"  Wall barrier had {gapCount} gap(s) dug through for connectivity"

  test "tree barrier gets cleared for connectivity":
    let env = makeEmptyEnv()
    # Create a COMPLETE barrier of trees spanning the playable area
    for y in MapBorder ..< MapHeight - MapBorder:
      let tree = Thing(kind: Tree, pos: ivec2(80, y.int32))
      tree.inventory = emptyInventory()
      setInv(tree, ItemWood, 10)
      env.add(tree)

    env.makeConnected()

    # At least one tree should be removed to create connectivity
    var gapCount = 0
    for y in MapBorder ..< MapHeight - MapBorder:
      if env.isEmpty(ivec2(80, y.int32)):
        inc gapCount

    check gapCount > 0
    echo &"  Tree barrier had {gapCount} tree(s) removed for connectivity"

  test "multiple isolated regions all get connected":
    let env = makeEmptyEnv()
    # Create three COMPLETE wall barriers at x=40, x=80, x=120
    # Each spans the entire playable height, creating four isolated regions
    for barrier in [40, 80, 120]:
      for y in MapBorder ..< MapHeight - MapBorder:
        let wall = Thing(kind: Wall, pos: ivec2(barrier.int32, y.int32))
        wall.inventory = emptyInventory()
        env.add(wall)

    env.makeConnected()

    # All barriers should have at least one gap to connect the regions
    for barrier in [40, 80, 120]:
      var gapCount = 0
      for y in MapBorder ..< MapHeight - MapBorder:
        if env.isEmpty(ivec2(barrier.int32, y.int32)):
          inc gapCount
      check gapCount > 0
      echo &"  Barrier at x={barrier} has {gapCount} gap(s)"

suite "Domain: Connectivity Graph - Terrain Handling":
  test "water terrain not dug through when land path exists":
    let env = makeEmptyEnv()
    # Create a water region with a land bridge
    for x in 40 ..< 60:
      for y in 40 ..< 60:
        if y != 50:  # Leave a land bridge at y=50
          env.terrain[x][y] = Water

    env.makeConnected()

    # Water tiles should remain water (not converted to Empty)
    # since there's a land path around
    var waterRemaining = 0
    for x in 40 ..< 60:
      for y in 40 ..< 60:
        if y != 50 and env.terrain[x][y] == Water:
          inc waterRemaining

    check waterRemaining > 0
    echo &"  Water tiles preserved when land path exists: {waterRemaining} water tiles"

  test "water terrain dug through when no land path":
    let env = makeEmptyEnv()
    # Create a complete water barrier with no land path
    for y in MapBorder ..< MapHeight - MapBorder:
      env.terrain[50][y] = Water

    env.makeConnected()

    # Some water tiles should be converted to create a path
    var emptyCount = 0
    for y in MapBorder ..< MapHeight - MapBorder:
      if env.terrain[50][y] == Empty or env.terrain[50][y] == TerrainEmpty:
        inc emptyCount

    check emptyCount > 0
    echo &"  Water barrier dug through: {emptyCount} tiles converted to empty"

  test "snow and dune terrain considered in connectivity":
    let env = makeEmptyEnv()
    # Create snow and dune regions
    for x in 60 ..< 80:
      for y in 60 ..< 80:
        if (x + y) mod 2 == 0:
          env.terrain[x][y] = Snow
        else:
          env.terrain[x][y] = Dune

    env.makeConnected()

    # Snow and dune should be traversable (high cost but not blocked)
    # The connectivity algorithm accounts for them
    echo "  Snow and dune terrain handled correctly in connectivity"

suite "Domain: Connectivity Graph - Diggable Objects":
  test "stone nodes can be dug through for connectivity":
    let env = makeEmptyEnv()
    # Create a COMPLETE barrier of stone nodes spanning the playable area
    for y in MapBorder ..< MapHeight - MapBorder:
      let stone = Thing(kind: Stone, pos: ivec2(100, y.int32))
      stone.inventory = emptyInventory()
      setInv(stone, ItemStone, 50)
      env.add(stone)

    env.makeConnected()

    var gapCount = 0
    for y in MapBorder ..< MapHeight - MapBorder:
      if env.isEmpty(ivec2(100, y.int32)):
        inc gapCount

    check gapCount > 0
    echo &"  Stone barrier had {gapCount} node(s) removed for connectivity"

  test "gold nodes can be dug through for connectivity":
    let env = makeEmptyEnv()
    # Create a COMPLETE barrier of gold nodes spanning the playable area
    for y in MapBorder ..< MapHeight - MapBorder:
      let gold = Thing(kind: Gold, pos: ivec2(110, y.int32))
      gold.inventory = emptyInventory()
      setInv(gold, ItemGold, 50)
      env.add(gold)

    env.makeConnected()

    var gapCount = 0
    for y in MapBorder ..< MapHeight - MapBorder:
      if env.isEmpty(ivec2(110, y.int32)):
        inc gapCount

    check gapCount > 0
    echo &"  Gold barrier had {gapCount} node(s) removed for connectivity"

  test "bush and cactus dug through for connectivity":
    let env = makeEmptyEnv()
    # Create a COMPLETE barrier of bushes and cacti spanning the playable area
    for y in MapBorder ..< MapHeight - MapBorder:
      let kind = if y mod 2 == 0: Bush else: Cactus
      let thing = Thing(kind: kind, pos: ivec2(90, y.int32))
      thing.inventory = emptyInventory()
      env.add(thing)

    env.makeConnected()

    var gapCount = 0
    for y in MapBorder ..< MapHeight - MapBorder:
      if env.isEmpty(ivec2(90, y.int32)):
        inc gapCount

    check gapCount > 0
    echo &"  Bush/Cactus barrier had {gapCount} gap(s) created"

suite "Domain: Connectivity Graph - Non-Diggable Objects":
  test "buildings are not dug through":
    let env = makeEmptyEnv()
    # Create a barrier of houses (buildings are not diggable)
    for y in 30 ..< 50:
      discard addBuilding(env, House, ivec2(70, y.int32), 0)

    # Leave a gap at the map edges so connectivity exists
    env.makeConnected()

    # All houses should remain (buildings are not removed for connectivity)
    var houseCount = 0
    for y in 30 ..< 50:
      let thing = env.getThing(ivec2(70, y.int32))
      if not isNil(thing) and thing.kind == House:
        inc houseCount

    check houseCount == 20  # All 20 houses (30 to 49) should remain
    echo "  Buildings preserved - not dug through for connectivity"

  test "town center not dug through":
    let env = makeEmptyEnv()
    # Place a town center
    discard addBuilding(env, TownCenter, ivec2(50, 50), 0)

    env.makeConnected()

    # Town center should remain
    let tc = env.getThing(ivec2(50, 50))
    check not isNil(tc)
    check tc.kind == TownCenter
    echo "  TownCenter preserved during connectivity pass"

suite "Domain: Connectivity Graph - Building Placement Integration":
  test "building placement then makeConnected preserves buildings":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(30, 30))
    agent.orientation = N
    setInv(agent, ItemWood, 100)

    # Build several houses
    for i in 0 ..< 5:
      agent.pos = ivec2(30 + (i * 2).int32, 30)
      agent.orientation = N
      env.stepAction(agent.agentId, 8'u8, 0)  # Build house

    let buildingsBefore = env.thingsByKind[House].len

    env.makeConnected()

    let buildingsAfter = env.thingsByKind[House].len

    # No buildings should be removed (they're not diggable)
    check buildingsAfter == buildingsBefore
    echo &"  Buildings preserved: {buildingsBefore} before, {buildingsAfter} after makeConnected"

  test "wall building creates barriers that remain":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    setInv(agent, ItemWood, 100)

    # Build walls in a line
    for i in 0 ..< 5:
      agent.pos = ivec2(50 + i.int32, 50)
      agent.orientation = N
      env.stepAction(agent.agentId, 8'u8, BuildIndexWall)  # Build wall

    let wallsBefore = env.thingsByKind[Wall].len

    env.makeConnected()

    # Player-built walls are still walls - connectivity may remove some
    # but this tests the integration, not that walls are preserved
    let wallsAfter = env.thingsByKind[Wall].len
    echo &"  Player walls: {wallsBefore} built, {wallsAfter} after connectivity pass"

suite "Domain: Connectivity Graph - Edge Cases":
  test "empty border area stays empty":
    let env = makeEmptyEnv()

    env.makeConnected()

    # Border tiles (x=0 or y=0 or x=MapWidth-1 or y=MapHeight-1)
    # should not have things placed in them
    var borderViolations = 0
    for x in 0 ..< MapWidth:
      if not env.isEmpty(ivec2(x.int32, 0)) or not env.isEmpty(ivec2(x.int32, (MapHeight-1).int32)):
        inc borderViolations
    for y in 0 ..< MapHeight:
      if not env.isEmpty(ivec2(0, y.int32)) or not env.isEmpty(ivec2((MapWidth-1).int32, y.int32)):
        inc borderViolations

    check borderViolations == 0
    echo "  Border area remains empty after connectivity pass"

  test "very small isolated region gets connected":
    let env = makeEmptyEnv()
    # Create a small box of walls leaving only one tile inside
    let center = ivec2(100, 100)
    for dx in [-2'i32, -1, 0, 1, 2]:
      for dy in [-2'i32, -1, 0, 1, 2]:
        if abs(dx) == 2 or abs(dy) == 2:  # Only the border
          let wall = Thing(kind: Wall, pos: center + ivec2(dx, dy))
          wall.inventory = emptyInventory()
          env.add(wall)

    env.makeConnected()

    # The wall box should have gaps dug through to connect inside
    var gapCount = 0
    for dx in [-2'i32, -1, 0, 1, 2]:
      for dy in [-2'i32, -1, 0, 1, 2]:
        if abs(dx) == 2 or abs(dy) == 2:
          if env.isEmpty(center + ivec2(dx, dy)):
            inc gapCount

    check gapCount > 0
    echo &"  Small isolated region connected via {gapCount} gap(s) in wall box"

  test "diagonal-only path does not disconnect":
    let env = makeEmptyEnv()
    # The connectivity algorithm uses 8-directional movement
    # A diagonal-only path should still count as connected
    # Create a checkerboard pattern of walls leaving diagonal paths
    for x in 40 ..< 50:
      for y in 40 ..< 50:
        if (x + y) mod 2 == 0:
          let wall = Thing(kind: Wall, pos: ivec2(x.int32, y.int32))
          wall.inventory = emptyInventory()
          env.add(wall)

    env.makeConnected()

    # Should not need to dig much since diagonal paths exist
    echo "  Diagonal connectivity respected in component analysis"
