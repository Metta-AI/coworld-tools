import std/[unittest, strformat]
import test_common

## Behavioral tests for building placement validation.
## Verifies valid/invalid placement, terrain restrictions, overlap detection,
## proximity rules, and foundation clearing match AoE2-style constraints.

suite "Behavior: Valid Building Placement":
  test "villager places house on empty buildable terrain":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    # Give wood for a house (costs 1 wood)
    setInv(agent, ItemWood, 5)
    let woodBefore = getInv(agent, ItemWood)

    # Build action = verb 8, argument = House build index (0)
    env.stepAction(agent.agentId, 8'u8, 0)

    # House should be placed at (10, 9) - north of agent
    let placed = env.grid[10][9]
    check placed != nil
    check placed.kind == House
    # Resources spent
    check getInv(agent, ItemWood) < woodBefore
    echo &"  Placed house at (10,9), wood: {woodBefore} -> {getInv(agent, ItemWood)}"

  test "villager places building in orientation direction":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = E  # Face east
    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, 0)  # Build house

    # Should place east at (11, 10)
    let placed = env.grid[11][10]
    check placed != nil
    check placed.kind == House
    echo "  Placed house east of agent per orientation"

  test "building placed on grass terrain succeeds":
    let env = makeEmptyEnv()
    env.terrain[10][9] = Grass
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, 0)

    let placed = env.grid[10][9]
    check placed != nil
    check placed.kind == House
    echo "  Grass terrain is valid for placement"

  test "building placed on sand terrain succeeds":
    let env = makeEmptyEnv()
    env.terrain[10][9] = Sand
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, 0)

    let placed = env.grid[10][9]
    check placed != nil
    check placed.kind == House
    echo "  Sand terrain is valid for placement"

suite "Behavior: Invalid Placement Locations":
  test "cannot place building on water terrain":
    let env = makeEmptyEnv()
    # Surround agent with water on all adjacent tiles
    for offset in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
                   ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1)]:
      let pos = ivec2(10, 10) + offset
      env.terrain[pos.x][pos.y] = Water

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 10)
    let woodBefore = getInv(agent, ItemWood)

    env.stepAction(agent.agentId, 8'u8, 0)  # Try build house

    # No house placed - all adjacent tiles are water (not buildable)
    var anyBuilding = false
    for offset in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
                   ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1)]:
      let pos = ivec2(10, 10) + offset
      if env.grid[pos.x][pos.y] != nil and env.grid[pos.x][pos.y].kind == House:
        anyBuilding = true
    check not anyBuilding
    # Resources not spent
    check getInv(agent, ItemWood) == woodBefore
    echo "  Water terrain correctly blocks non-dock building placement"

  test "dock requires water terrain":
    let env = makeEmptyEnv()
    # Place water north of agent
    env.terrain[10][9] = Water
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 10)

    # Dock build index = 6
    env.stepAction(agent.agentId, 8'u8, 6)

    # Dock is a BackgroundThingKind, so check backgroundGrid
    let placed = env.getBackgroundThing(ivec2(10, 9))
    check placed != nil
    check placed.kind == Dock
    echo "  Dock placed on water terrain"

  test "dock cannot be placed on land terrain":
    let env = makeEmptyEnv()
    # All adjacent tiles are empty/buildable land (default)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 10)
    let woodBefore = getInv(agent, ItemWood)

    env.stepAction(agent.agentId, 8'u8, 6)  # Dock build index

    # No dock placed - no water tiles adjacent
    var anyDock = false
    for offset in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
                   ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1)]:
      let pos = ivec2(10, 10) + offset
      let bg = env.getBackgroundThing(pos)
      if bg != nil and bg.kind == Dock:
        anyDock = true
    check not anyDock
    check getInv(agent, ItemWood) == woodBefore
    echo "  Dock correctly rejected on land terrain"

suite "Behavior: Overlap Detection":
  test "cannot place building on occupied tile":
    let env = makeEmptyEnv()
    # Place existing building north of agent
    discard addBuilding(env, House, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, 0)  # Try build house

    # Should NOT overwrite existing building - placement falls through to next offset
    let existing = env.grid[10][9]
    check existing != nil
    check existing.kind == House
    echo "  Occupied tile correctly blocked, building searched alternate location"

  test "building falls through to next valid adjacent tile":
    let env = makeEmptyEnv()
    # Block north (10,9) with existing building
    discard addBuilding(env, House, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N  # Preferred direction is north
    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, 0)  # Build house

    # North blocked, should fall through to next valid offset
    # Search order: orientation, N, E, S, W, NW, NE, SW, SE
    # Agent faces N, so first try is (10,9) = blocked
    # Next tries: E(11,10), S(10,11), W(9,10) etc.
    var placed = false
    for offset in [ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
                   ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1)]:
      let pos = ivec2(10, 10) + offset
      if env.grid[pos.x][pos.y] != nil and env.grid[pos.x][pos.y].kind == House:
        # Check this is a newly placed house (not the blocker at 10,9)
        if pos != ivec2(10, 9):
          placed = true
          echo &"  Building fell through to alternate location ({pos.x},{pos.y})"
    check placed

  test "cannot place when all adjacent tiles occupied":
    let env = makeEmptyEnv()
    # Block ALL adjacent tiles
    for offset in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
                   ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1)]:
      let pos = ivec2(10, 10) + offset
      discard addBuilding(env, House, pos, 1)

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 5)
    let woodBefore = getInv(agent, ItemWood)

    env.stepAction(agent.agentId, 8'u8, 0)

    # No resources spent - action invalid
    check getInv(agent, ItemWood) == woodBefore
    echo "  All adjacent tiles blocked, placement correctly failed"

  test "cannot place building on tile with background object":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    # Place a background thing (corpse) at the north tile
    let corpse = Thing(kind: Corpse, pos: ivec2(10, 9))
    corpse.inventory = emptyInventory()
    env.add(corpse)

    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, 0)

    # The north tile has a background object, so building should fall through
    # to another adjacent tile
    let northThing = env.grid[10][9]
    # North tile should not have a house (background blocks it)
    check northThing == nil or northThing.kind != House
    echo "  Background object correctly blocks placement at that tile"

suite "Behavior: Resource Cost Validation":
  test "building fails without sufficient resources":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    # No wood - can't build
    setInv(agent, ItemWood, 0)

    env.stepAction(agent.agentId, 8'u8, 0)  # Try build house (costs 1 wood)

    let placed = env.grid[10][9]
    check placed == nil
    echo "  Build correctly failed with no resources"

  test "building uses team stockpile when inventory empty":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 0)
    # Give team stockpile wood instead
    env.setStockpile(0, ResourceWood, 10)
    let stockBefore = env.stockpileCount(0, ResourceWood)

    env.stepAction(agent.agentId, 8'u8, 0)  # Build house

    let placed = env.grid[10][9]
    check placed != nil
    check placed.kind == House
    let stockAfter = env.stockpileCount(0, ResourceWood)
    check stockAfter < stockBefore
    echo &"  Built from stockpile: wood {stockBefore} -> {stockAfter}"

  test "castle requires stone not wood":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 100)  # Lots of wood but no stone
    setInv(agent, ItemStone, 0)

    # Castle build index = 12
    env.stepAction(agent.agentId, 8'u8, 12)

    let placed = env.grid[10][9]
    check placed == nil
    echo "  Castle correctly requires stone, not just wood"

  test "castle places with sufficient stone":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemStone, 50)  # Castle costs 33 stone

    env.stepAction(agent.agentId, 8'u8, 12)

    let placed = env.grid[10][9]
    check placed != nil
    check placed.kind == Castle
    echo &"  Castle placed with stone, remaining: {getInv(agent, ItemStone)}"

suite "Behavior: Foundation and Construction State":
  test "newly placed building starts under construction with hp=1":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 10)

    # Build a guard tower (build index = 23) which has maxHp > 0
    env.stepAction(agent.agentId, 8'u8, BuildIndexGuardTower)

    let placed = env.grid[10][9]
    check placed != nil
    check placed.kind == GuardTower
    check placed.hp == 1
    check placed.maxHp > 1
    echo &"  Building starts at hp=1, maxHp={placed.maxHp}"

  test "placed building is assigned to builder team":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 10)

    env.stepAction(agent.agentId, 8'u8, 0)

    let placed = env.grid[10][9]
    check placed != nil
    check placed.teamId == 0
    echo "  Building assigned to team 0 (builder's team)"

  test "different team gets building assigned to their team":
    let env = makeEmptyEnv()
    # Agent on team 1 (agentId = MapAgentsPerTeam)
    let agent = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 10)

    env.stepAction(agent.agentId, 8'u8, 0)

    let placed = env.grid[10][9]
    check placed != nil
    check placed.teamId == 1
    echo "  Building correctly assigned to team 1"

  test "building blocks the tile after placement":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 10)

    check env.isEmpty(ivec2(10, 9))  # Empty before
    env.stepAction(agent.agentId, 8'u8, 0)
    check not env.isEmpty(ivec2(10, 9))  # Blocked after
    echo "  Building correctly blocks grid tile"

suite "Behavior: Terrain Restrictions":
  test "buildable terrain types all accept buildings":
    # Verify each terrain in BuildableTerrain set allows placement
    for terrain in [TerrainEmpty, Grass, Sand, Snow, Mud, Dune, Road]:
      let env = makeEmptyEnv()
      env.terrain[10][9] = terrain
      let agent = addAgentAt(env, 0, ivec2(10, 10))
      agent.orientation = N
      setInv(agent, ItemWood, 5)

      env.stepAction(agent.agentId, 8'u8, 0)

      let placed = env.grid[10][9]
      check placed != nil
      check placed.kind == House
      echo &"  Terrain {terrain} accepts building placement"

  test "water terrain rejects non-dock buildings":
    let env = makeEmptyEnv()
    # Set ALL adjacent tiles to water
    for offset in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
                   ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1)]:
      let pos = ivec2(10, 10) + offset
      env.terrain[pos.x][pos.y] = Water

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 10)
    let woodBefore = getInv(agent, ItemWood)

    env.stepAction(agent.agentId, 8'u8, 0)  # House on water

    check getInv(agent, ItemWood) == woodBefore
    echo "  Water terrain correctly rejects house placement"

suite "Behavior: Proximity Rules - Auto Road Construction":
  test "mill placement creates road to town center":
    let env = makeEmptyEnv()
    # Place town center for team 0
    discard addBuilding(env, TownCenter, ivec2(15, 10), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 10)

    # Mill build index = 2
    env.stepAction(agent.agentId, 8'u8, 2)

    # Check that road was created between mill and town center
    var roadCount = 0
    for x in 10 .. 15:
      if env.terrain[x][10] == Road or env.terrain[x][9] == Road:
        inc roadCount

    check roadCount > 0
    echo &"  Mill placement created {roadCount} road tiles toward TC"

  test "lumber camp placement creates road to town center":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(15, 10), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 10)

    # LumberCamp build index = 3
    env.stepAction(agent.agentId, 8'u8, 3)

    var roadCount = 0
    for x in 10 .. 15:
      for y in 9 .. 10:
        if env.terrain[x][y] == Road:
          inc roadCount

    check roadCount > 0
    echo &"  Lumber camp placement created {roadCount} road tiles toward TC"

  test "mining camp placement creates road to town center":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(15, 10), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 10)

    # MiningCamp build index = 15
    env.stepAction(agent.agentId, 8'u8, 15)

    var roadCount = 0
    for x in 10 .. 15:
      for y in 9 .. 10:
        if env.terrain[x][y] == Road:
          inc roadCount

    check roadCount > 0
    echo &"  Mining camp placement created {roadCount} road tiles toward TC"

suite "Behavior: Wall and Road Placement":
  test "wall placement succeeds on buildable terrain":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 5)

    # Wall build index = 14
    env.stepAction(agent.agentId, 8'u8, BuildIndexWall)

    let placed = env.grid[10][9]
    check placed != nil
    check placed.kind == Wall
    echo "  Wall placed successfully"

  test "road placement changes terrain type":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 5)

    check env.terrain[10][9] != Road
    # Road build index = 15
    env.stepAction(agent.agentId, 8'u8, BuildIndexRoad)

    check env.terrain[10][9] == Road
    echo "  Road placement correctly changes terrain type"

  test "door placement succeeds":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, BuildIndexDoor)

    # Door is a BackgroundThingKind
    let placed = env.getBackgroundThing(ivec2(10, 9))
    check placed != nil
    check placed.kind == Door
    echo "  Door placed successfully"

suite "Behavior: Building HP Bonuses":
  test "masonry tech increases building max HP":
    let env = makeEmptyEnv()
    # Give team masonry tech
    env.teamUniversityTechs[0].researched[TechMasonry] = true
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 10)

    # Build a guard tower (has default maxHp)
    env.stepAction(agent.agentId, 8'u8, BuildIndexGuardTower)

    let placed = env.grid[10][9]
    check placed != nil
    check placed.kind == GuardTower
    echo &"  GuardTower with Masonry: maxHp={placed.maxHp}"

    # Build another guard tower without masonry for comparison
    let env2 = makeEmptyEnv()
    let agent2 = addAgentAt(env2, 0, ivec2(10, 10))
    agent2.orientation = N
    setInv(agent2, ItemWood, 10)
    env2.stepAction(agent2.agentId, 8'u8, BuildIndexGuardTower)
    let baseline = env2.grid[10][9]
    check baseline != nil

    check placed.maxHp > baseline.maxHp
    echo &"  Masonry bonus: {baseline.maxHp} -> {placed.maxHp}"
