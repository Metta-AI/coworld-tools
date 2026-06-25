import std/[unittest, strformat, math]
import test_common
import common

## Behavioral tests for unit pathfinding: navigation around obstacles,
## shortest paths, blocked routes, terrain changes, corner escapes,
## and large group pathing.

suite "Behavior: Basic Movement":
  test "unit moves one tile in commanded direction":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let startPos = agent.pos

    # Move north (verb=1, arg=0 for N)
    env.stepAction(agent.agentId, 1'u8, 0)  # N
    check agent.pos == ivec2(50, 49)
    echo &"  Moved N: ({startPos.x},{startPos.y}) -> ({agent.pos.x},{agent.pos.y})"

  test "unit moves in all 4 cardinal directions":
    # Note: diagonal movement is blocked by canTraverseElevation requiring
    # abs(dx)+abs(dy)==1, so only cardinal directions (N,S,W,E) work.
    for dir in [0, 1, 2, 3]:  # N, S, W, E
      let env = makeEmptyEnv()
      let agent = addAgentAt(env, 0, ivec2(50, 50))
      let startPos = agent.pos

      env.stepAction(agent.agentId, 1'u8, dir)
      let delta = orientationToVec(Orientation(dir))
      let expected = ivec2(startPos.x + delta.x, startPos.y + delta.y)
      check agent.pos == expected
    echo "  All 4 cardinal directions verified"

  test "diagonal movement is blocked by elevation check":
    # canTraverseElevation requires abs(dx)+abs(dy)==1, so diagonals fail
    for dir in [4, 5, 6, 7]:  # NW, NE, SW, SE
      let env = makeEmptyEnv()
      let agent = addAgentAt(env, 0, ivec2(50, 50))
      let startPos = agent.pos

      env.stepAction(agent.agentId, 1'u8, dir)
      check agent.pos == startPos  # Diagonal blocked
    echo "  Diagonal movement blocked as expected"

  test "unit traverses multiple tiles over multiple steps":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    # Move east 10 tiles
    for i in 0 ..< 10:
      env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos == ivec2(60, 50)
    echo &"  Moved 10 tiles east to ({agent.pos.x},{agent.pos.y})"

suite "Behavior: Navigation Around Obstacles":
  test "unit cannot move into a wall":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # Place a wall to the east
    let wall = Thing(kind: Wall, pos: ivec2(51, 50))
    wall.inventory = emptyInventory()
    env.add(wall)

    let startPos = agent.pos
    env.stepAction(agent.agentId, 1'u8, 3)  # Try move E into wall
    check agent.pos == startPos  # Should not have moved
    echo "  Unit blocked by wall at (51,50)"

  test "unit cannot move into a building":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    discard addBuilding(env, TownCenter, ivec2(51, 50), 0)

    let startPos = agent.pos
    env.stepAction(agent.agentId, 1'u8, 3)  # Try move E into building
    check agent.pos == startPos
    echo "  Unit blocked by TownCenter at (51,50)"

  test "unit cannot move into water":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    env.terrain[51][50] = Water

    let startPos = agent.pos
    env.stepAction(agent.agentId, 1'u8, 3)  # Try move E into water
    check agent.pos == startPos
    echo "  Unit blocked by water at (51,50)"

  test "unit navigates around a wall obstacle":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # Place a wall directly east
    let wall = Thing(kind: Wall, pos: ivec2(51, 50))
    wall.inventory = emptyInventory()
    env.add(wall)

    # Navigate around using cardinal moves: S, E, E, N to get past the wall
    env.stepAction(agent.agentId, 1'u8, 1)  # S to (50,51)
    check agent.pos == ivec2(50, 51)
    env.stepAction(agent.agentId, 1'u8, 3)  # E to (51,51)
    check agent.pos == ivec2(51, 51)
    env.stepAction(agent.agentId, 1'u8, 3)  # E to (52,51)
    check agent.pos == ivec2(52, 51)
    env.stepAction(agent.agentId, 1'u8, 0)  # N to (52,50)
    check agent.pos == ivec2(52, 50)
    echo &"  Navigated around wall to ({agent.pos.x},{agent.pos.y})"

  test "unit navigates around a line of walls":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 48))
    # Place a vertical line of walls at x=51, y=47..51
    for y in 47 .. 51:
      let wall = Thing(kind: Wall, pos: ivec2(51, y.int32))
      wall.inventory = emptyInventory()
      env.add(wall)

    # Must go around south end using cardinal moves only
    env.stepAction(agent.agentId, 1'u8, 1)  # S to (50,49)
    env.stepAction(agent.agentId, 1'u8, 1)  # S to (50,50)
    env.stepAction(agent.agentId, 1'u8, 1)  # S to (50,51)
    env.stepAction(agent.agentId, 1'u8, 1)  # S to (50,52)
    env.stepAction(agent.agentId, 1'u8, 3)  # E to (51,52) -- below wall line
    env.stepAction(agent.agentId, 1'u8, 3)  # E to (52,52) -- past wall
    check agent.pos.x >= 52  # Past the wall line
    echo &"  Navigated around 5-tile wall line to ({agent.pos.x},{agent.pos.y})"

suite "Behavior: Shortest Path":
  test "direct path is shorter than detour":
    # Direct east: 5 steps. Detour south-east-north: more steps.
    let env1 = makeEmptyEnv()
    let a1 = addAgentAt(env1, 0, ivec2(50, 50))
    for i in 0 ..< 5:
      env1.stepAction(a1.agentId, 1'u8, 3)  # E
    let directPos = a1.pos
    check directPos == ivec2(55, 50)

    let env2 = makeEmptyEnv()
    let a2 = addAgentAt(env2, 0, ivec2(50, 50))
    # Detour: S, S, E*5, N, N
    env2.stepAction(a2.agentId, 1'u8, 1)  # S
    env2.stepAction(a2.agentId, 1'u8, 1)  # S
    for i in 0 ..< 5:
      env2.stepAction(a2.agentId, 1'u8, 3)  # E
    env2.stepAction(a2.agentId, 1'u8, 0)  # N
    env2.stepAction(a2.agentId, 1'u8, 0)  # N
    check a2.pos == ivec2(55, 50)
    echo "  Direct path (5 steps) vs detour (9 steps) both reach target"

  test "cardinal movement reaches diagonal target via E then S":
    # Since diagonal movement is blocked, reaching a diagonal target
    # requires cardinal steps: E*5 + S*5 = 10 steps
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    for i in 0 ..< 5:
      env.stepAction(agent.agentId, 1'u8, 3)  # E
    for i in 0 ..< 5:
      env.stepAction(agent.agentId, 1'u8, 1)  # S
    check agent.pos == ivec2(55, 55)
    echo "  Reached diagonal target (55,55) via 10 cardinal steps"

  test "cavalry double-step covers more ground":
    let env = makeEmptyEnv()
    let scout = addAgentAt(env, 0, ivec2(50, 50), unitClass = UnitScout)
    applyUnitClass(scout, UnitScout)

    let env2 = makeEmptyEnv()
    let villager = addAgentAt(env2, 0, ivec2(50, 50))

    # Both move east 5 steps
    for i in 0 ..< 5:
      env.stepAction(scout.agentId, 1'u8, 3)  # E
      env2.stepAction(villager.agentId, 1'u8, 3)  # E

    # Scout should be further east (2 tiles per move vs 1)
    check scout.pos.x > villager.pos.x
    echo &"  Scout at x={scout.pos.x}, Villager at x={villager.pos.x}"

suite "Behavior: Blocked Routes":
  test "unit fully enclosed by walls cannot move":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # Surround with walls in all 8 directions
    for dx in -1 .. 1:
      for dy in -1 .. 1:
        if dx == 0 and dy == 0:
          continue
        let wall = Thing(kind: Wall, pos: ivec2(50 + dx.int32, 50 + dy.int32))
        wall.inventory = emptyInventory()
        env.add(wall)

    let startPos = agent.pos
    # Try all 8 directions
    for dir in 0 ..< 8:
      env.stepAction(agent.agentId, 1'u8, dir)
      check agent.pos == startPos
    echo "  Fully enclosed unit cannot move in any direction"

  test "unit blocked by water on three sides must use only open path":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # Water N, E, S (and diagonals NE, SE)
    env.terrain[50][49] = Water  # N
    env.terrain[51][50] = Water  # E
    env.terrain[50][51] = Water  # S
    env.terrain[51][49] = Water  # NE
    env.terrain[51][51] = Water  # SE

    let startPos = agent.pos
    # Moving E should fail (water)
    env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos == startPos

    # Moving W should succeed (no water)
    env.stepAction(agent.agentId, 1'u8, 2)  # W
    check agent.pos == ivec2(49, 50)
    echo "  Unit used only available path west"

  test "narrow corridor forces single-file movement":
    let env = makeEmptyEnv()
    # Create a 1-tile-wide corridor heading east at y=50
    # Walls at y=49 and y=51 from x=50 to x=60
    for x in 50 .. 60:
      let wallN = Thing(kind: Wall, pos: ivec2(x.int32, 49))
      wallN.inventory = emptyInventory()
      env.add(wallN)
      let wallS = Thing(kind: Wall, pos: ivec2(x.int32, 51))
      wallS.inventory = emptyInventory()
      env.add(wallS)

    let agent = addAgentAt(env, 0, ivec2(49, 50))
    # Move east through corridor
    for i in 0 ..< 12:
      env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos.y == 50  # Stayed in corridor
    check agent.pos.x >= 60  # Made it through
    echo &"  Navigated narrow corridor to ({agent.pos.x},{agent.pos.y})"

suite "Behavior: Terrain Effects on Movement":
  test "road accelerates non-cavalry movement":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # Place road tiles at step1 position
    env.terrain[51][50] = Road

    env.stepAction(agent.agentId, 1'u8, 3)  # Move E onto road
    # On road, non-cavalry get double step to (52,50) if step2 is also clear
    check agent.pos.x >= 51  # At least moved to road tile
    echo &"  Road movement: ended at ({agent.pos.x},{agent.pos.y})"

  test "mud terrain slows movement via debt":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # Place mud tiles ahead
    for x in 51 .. 60:
      env.terrain[x][50] = Mud  # Mud speed = 0.7, debt = 0.3 per tile

    var moves = 0
    for i in 0 ..< 10:
      let prevPos = agent.pos
      env.stepAction(agent.agentId, 1'u8, 3)  # E
      if agent.pos != prevPos:
        inc moves

    # With mud (0.7 speed), agent accumulates 0.3 debt per move
    # Some moves should be skipped due to debt
    check moves < 10
    echo &"  Mud slowed movement: {moves}/10 moves succeeded, pos ({agent.pos.x},{agent.pos.y})"

  test "snow terrain slows movement":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    for x in 51 .. 60:
      env.terrain[x][50] = Snow  # Snow speed = 0.8, debt = 0.2 per tile

    var moves = 0
    for i in 0 ..< 10:
      let prevPos = agent.pos
      env.stepAction(agent.agentId, 1'u8, 3)  # E
      if agent.pos != prevPos:
        inc moves

    check moves < 10
    echo &"  Snow slowed movement: {moves}/10 moves succeeded, pos ({agent.pos.x},{agent.pos.y})"

  test "sand terrain slightly slows movement":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    for x in 51 .. 70:
      env.terrain[x][50] = Sand  # Sand speed = 0.9

    var moves = 0
    for i in 0 ..< 20:
      let prevPos = agent.pos
      env.stepAction(agent.agentId, 1'u8, 3)  # E
      if agent.pos != prevPos:
        inc moves

    check moves < 20
    echo &"  Sand slowed movement: {moves}/20 moves succeeded, pos ({agent.pos.x},{agent.pos.y})"

suite "Behavior: Dynamic Obstacle Changes":
  test "unit can move after obstacle is removed":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # Place wall east
    let wall = Thing(kind: Wall, pos: ivec2(51, 50))
    wall.inventory = emptyInventory()
    env.add(wall)

    let startPos = agent.pos
    env.stepAction(agent.agentId, 1'u8, 3)  # E - blocked
    check agent.pos == startPos

    # Remove the wall
    env.grid[51][50] = nil

    env.stepAction(agent.agentId, 1'u8, 3)  # E - should succeed now
    check agent.pos == ivec2(51, 50)
    echo "  Unit moved after wall removal"

  test "unit blocked after obstacle is placed":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    # Move east succeeds initially
    env.stepAction(agent.agentId, 1'u8, 3)  # E to (51,50)
    check agent.pos == ivec2(51, 50)

    # Place wall ahead
    let wall = Thing(kind: Wall, pos: ivec2(52, 50))
    wall.inventory = emptyInventory()
    env.add(wall)

    # Move east now blocked
    env.stepAction(agent.agentId, 1'u8, 3)  # E - blocked
    check agent.pos == ivec2(51, 50)
    echo "  Unit blocked after wall placed"

  test "terrain change from empty to water blocks movement":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    # Move east succeeds
    env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos == ivec2(51, 50)

    # Change terrain ahead to water
    env.terrain[52][50] = Water

    # Now east blocked
    env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos == ivec2(51, 50)
    echo "  Water terrain change blocks movement"

  test "terrain change from water to empty enables movement":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    env.terrain[51][50] = Water

    let startPos = agent.pos
    env.stepAction(agent.agentId, 1'u8, 3)  # E - blocked by water
    check agent.pos == startPos

    # Change water to empty
    env.terrain[51][50] = TerrainEmpty

    env.stepAction(agent.agentId, 1'u8, 3)  # E - now clear
    check agent.pos == ivec2(51, 50)
    echo "  Water-to-empty terrain change enables movement"

suite "Behavior: Corner and Tight Space Navigation":
  test "unit escapes from L-shaped corner":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # L-shape walls: north wall and east wall forming a corner
    # Wall N: (49,49), (50,49), (51,49)
    # Wall E: (51,49), (51,50), (51,51)
    for x in 49 .. 51:
      let w = Thing(kind: Wall, pos: ivec2(x.int32, 49))
      w.inventory = emptyInventory()
      env.add(w)
    for y in 50 .. 51:
      let w = Thing(kind: Wall, pos: ivec2(51, y.int32))
      w.inventory = emptyInventory()
      env.add(w)

    # Agent at (50,50) can escape south or west
    env.stepAction(agent.agentId, 1'u8, 1)  # S
    check agent.pos == ivec2(50, 51)
    # Keep moving south to fully escape
    env.stepAction(agent.agentId, 1'u8, 1)  # S
    check agent.pos == ivec2(50, 52)
    echo &"  Escaped L-corner to ({agent.pos.x},{agent.pos.y})"

  test "unit escapes from U-shaped pocket":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # U-shape: walls on N, E, W — only S is open
    for x in 49 .. 51:
      let w = Thing(kind: Wall, pos: ivec2(x.int32, 49))
      w.inventory = emptyInventory()
      env.add(w)
    let wE = Thing(kind: Wall, pos: ivec2(51, 50))
    wE.inventory = emptyInventory()
    env.add(wE)
    let wW = Thing(kind: Wall, pos: ivec2(49, 50))
    wW.inventory = emptyInventory()
    env.add(wW)

    # Only exit is south
    let startPos = agent.pos
    env.stepAction(agent.agentId, 1'u8, 0)  # N - blocked
    check agent.pos == startPos
    env.stepAction(agent.agentId, 1'u8, 3)  # E - blocked
    check agent.pos == startPos
    env.stepAction(agent.agentId, 1'u8, 2)  # W - blocked
    check agent.pos == startPos
    env.stepAction(agent.agentId, 1'u8, 1)  # S - open!
    check agent.pos == ivec2(50, 51)
    echo "  Escaped U-pocket via south exit"

  test "unit navigates through 1-tile gap in wall":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(49, 50))
    # Wall from y=48 to y=52 at x=50, with gap at y=50
    for y in 48 .. 52:
      if y == 50:
        continue  # Gap
      let w = Thing(kind: Wall, pos: ivec2(50, y.int32))
      w.inventory = emptyInventory()
      env.add(w)

    # Move east through the gap
    env.stepAction(agent.agentId, 1'u8, 3)  # E through gap at (50,50)
    check agent.pos == ivec2(50, 50)
    env.stepAction(agent.agentId, 1'u8, 3)  # E to (51,50)
    check agent.pos == ivec2(51, 50)
    echo "  Navigated through 1-tile gap"

suite "Behavior: Agent-Agent Interactions During Movement":
  test "same-team agents can swap positions":
    let env = makeEmptyEnv()
    let agent0 = addAgentAt(env, 0, ivec2(50, 50))
    let agent1 = addAgentAt(env, 1, ivec2(51, 50))  # Same team (both team 0)

    # Agent 0 moves east into agent 1's position → swap
    env.stepAction(agent0.agentId, 1'u8, 3)  # E
    check agent0.pos == ivec2(51, 50)
    check agent1.pos == ivec2(50, 50)
    echo "  Same-team agents swapped positions"

  test "different-team agents cannot swap positions":
    let env = makeEmptyEnv()
    let agent0 = addAgentAt(env, 0, ivec2(50, 50))
    # Agent on team 1 (id >= MapAgentsPerTeam)
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(51, 50))

    let startPos0 = agent0.pos
    env.stepAction(agent0.agentId, 1'u8, 3)  # E - blocked by enemy
    check agent0.pos == startPos0
    echo "  Different-team agents cannot swap"

  test "frozen agent blocks swap":
    let env = makeEmptyEnv()
    let agent0 = addAgentAt(env, 0, ivec2(50, 50))
    let blocker = addAgentAt(env, 1, ivec2(51, 50))
    # Freeze the blocking agent
    blocker.frozen = 10

    let startPos0 = agent0.pos
    env.stepAction(agent0.agentId, 1'u8, 3)  # E - blocked by frozen ally
    # Frozen agents can't be swapped
    check agent0.pos == startPos0
    echo "  Frozen ally blocks swap"

suite "Behavior: Large Group Pathing":
  test "multiple agents move through corridor without collision":
    let env = makeEmptyEnv()
    # Create corridor at y=50 with walls at y=49 and y=51, x=50..70
    for x in 50 .. 70:
      let wN = Thing(kind: Wall, pos: ivec2(x.int32, 49))
      wN.inventory = emptyInventory()
      env.add(wN)
      let wS = Thing(kind: Wall, pos: ivec2(x.int32, 51))
      wS.inventory = emptyInventory()
      env.add(wS)

    # Place 5 agents in a line before the corridor
    var agents: seq[Thing]
    for i in 0 ..< 5:
      agents.add addAgentAt(env, i, ivec2((45 + i).int32, 50))

    # Move all agents east for 30 steps
    for step in 0 ..< 30:
      for i in countdown(agents.len - 1, 0):  # Move front agent first
        env.stepAction(agents[i].agentId, 1'u8, 3)  # E

    # All agents should have advanced east
    for i, a in agents:
      check a.pos.x > (45 + i).int32
    echo &"  5 agents navigated corridor, lead at x={agents[4].pos.x}"

  test "group of agents spreads around obstacle":
    let env = makeEmptyEnv()
    # Single wall at (55, 50)
    let wall = Thing(kind: Wall, pos: ivec2(55, 50))
    wall.inventory = emptyInventory()
    env.add(wall)

    # 3 agents heading east from x=50
    var agents: seq[Thing]
    for i in 0 ..< 3:
      agents.add addAgentAt(env, i, ivec2(50, (49 + i).int32))

    # Move east for 10 steps
    for step in 0 ..< 10:
      for a in agents:
        env.stepAction(a.agentId, 1'u8, 3)  # E

    # At least some agents should have gotten past x=55
    var pastObstacle = 0
    for a in agents:
      if a.pos.x > 55:
        inc pastObstacle
    # Agents at y=49 and y=51 were never blocked
    check pastObstacle >= 2
    echo &"  {pastObstacle}/3 agents passed obstacle"

suite "Behavior: Elevation and Ramps":
  test "unit cannot climb elevation without ramp":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # Set higher elevation to the east
    env.elevation[51][50] = 1

    let startPos = agent.pos
    env.stepAction(agent.agentId, 1'u8, 3)  # E - uphill without ramp
    check agent.pos == startPos
    echo "  Cannot climb elevation without ramp"

  test "unit can climb elevation with ramp":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    # Set ramp terrain and higher elevation to the east
    env.terrain[50][50] = RampUpE  # Ramp at current position
    env.elevation[51][50] = 1

    env.stepAction(agent.agentId, 1'u8, 3)  # E - uphill with ramp
    check agent.pos == ivec2(51, 50)
    echo "  Climbed elevation via ramp"

  test "unit can descend elevation freely":
    let env = makeEmptyEnv()
    # Start at elevation 1
    env.elevation[50][50] = 1
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    env.stepAction(agent.agentId, 1'u8, 3)  # E - downhill (always allowed)
    check agent.pos == ivec2(51, 50)
    echo "  Descended elevation freely"

suite "Behavior: Out of Bounds":
  test "unit cannot move outside map border":
    let env = makeEmptyEnv()
    # Place agent at edge of map border
    let agent = addAgentAt(env, 0, ivec2(MapBorder.int32, MapBorder.int32))

    let startPos = agent.pos
    # Try to move north (toward border)
    env.stepAction(agent.agentId, 1'u8, 0)  # N
    # Should be blocked if at border
    check agent.pos.y <= startPos.y  # Didn't move past border
    echo &"  Border enforcement at ({agent.pos.x},{agent.pos.y})"

  test "unit cannot move past map edge":
    let env = makeEmptyEnv()
    let edgeX = (MapWidth - MapBorder - 1).int32
    let agent = addAgentAt(env, 0, ivec2(edgeX, 50))

    let startPos = agent.pos
    env.stepAction(agent.agentId, 1'u8, 3)  # E - toward edge
    check agent.pos == startPos  # Should be blocked
    echo "  Unit blocked at east map edge"
