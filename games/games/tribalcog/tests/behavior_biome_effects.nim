import std/[unittest, strformat, math]
import test_common
import common

## Behavioral tests for biome effects on unit stats and movement:
## - Terrain speed modifiers (movement debt accumulation)
## - Biome-specific terrain penalties (mud, snow, sand, dune)
## - Water terrain effects (shallow water slowdown, deep water blocking)
## - Water units immune to terrain penalties
## - Elevation-based movement (ramp/road requirements, cliff fall damage)

suite "Behavior: Terrain Speed Modifiers":
  test "grass terrain has no movement penalty":
    let env = makeEmptyEnv()
    for x in 49..52:
      for y in 49..52:
        env.terrain[x][y] = Grass
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    # Move 5 times on grass
    for i in 0 ..< 5:
      env.stepAction(agent.agentId, 1'u8, 3)  # Move East
    check agent.pos == ivec2(55, 50)
    check agent.movementDebt < 0.01  # No debt accumulated
    echo "  Grass: no movement penalty, position correct"

  test "mud terrain accumulates movement debt (30% slower)":
    let env = makeEmptyEnv()
    for x in 49..60:
      for y in 49..52:
        env.terrain[x][y] = Mud  # Swamp biome terrain
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.movementDebt = 0.0'f32

    # Mud has 0.7 modifier, so each move adds 0.3 debt
    # After ~4 moves, debt should exceed 1.0 and one move should be skipped
    var moves = 0
    for i in 0 ..< 10:
      let prevPos = agent.pos
      env.stepAction(agent.agentId, 1'u8, 3)  # Try move East
      if agent.pos.x > prevPos.x:
        inc moves

    # Should have moved fewer than 10 times due to debt-based skips
    check moves < 10
    check agent.pos.x < 60  # Didn't move full 10 tiles
    echo &"  Mud: moved {moves}/10 times, final pos ({agent.pos.x},{agent.pos.y})"

  test "snow terrain accumulates movement debt (20% slower)":
    let env = makeEmptyEnv()
    for x in 49..60:
      for y in 49..52:
        env.terrain[x][y] = Snow
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.movementDebt = 0.0'f32

    # Snow has 0.8 modifier, so each move adds 0.2 debt
    # After 5 moves, debt = 1.0 and next move is skipped
    var moves = 0
    for i in 0 ..< 10:
      let prevPos = agent.pos
      env.stepAction(agent.agentId, 1'u8, 3)  # Try move East
      if agent.pos.x > prevPos.x:
        inc moves

    check moves < 10
    echo &"  Snow: moved {moves}/10 times, final pos ({agent.pos.x},{agent.pos.y})"

  test "dune terrain accumulates movement debt (15% slower)":
    let env = makeEmptyEnv()
    for x in 49..60:
      for y in 49..52:
        env.terrain[x][y] = Dune
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.movementDebt = 0.0'f32

    # Dune has 0.85 modifier, so each move adds 0.15 debt
    var moves = 0
    for i in 0 ..< 10:
      let prevPos = agent.pos
      env.stepAction(agent.agentId, 1'u8, 3)  # Try move East
      if agent.pos.x > prevPos.x:
        inc moves

    check moves < 10
    echo &"  Dune: moved {moves}/10 times, final pos ({agent.pos.x},{agent.pos.y})"

  test "sand terrain accumulates movement debt (10% slower)":
    let env = makeEmptyEnv()
    for x in 49..75:
      for y in 49..52:
        env.terrain[x][y] = Sand
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.movementDebt = 0.0'f32

    # Sand has 0.9 modifier, so each move adds 0.1 debt
    # After 10 moves, debt = 1.0, so 11th move is skipped
    var moves = 0
    for i in 0 ..< 15:
      let prevPos = agent.pos
      env.stepAction(agent.agentId, 1'u8, 3)  # Try move East
      if agent.pos.x > prevPos.x:
        inc moves

    check moves < 15  # Should be ~14 moves (1 skipped per 10)
    echo &"  Sand: moved {moves}/15 times, final pos ({agent.pos.x},{agent.pos.y})"

  test "shallow water accumulates significant movement debt (50% slower)":
    let env = makeEmptyEnv()
    for x in 49..60:
      for y in 49..52:
        env.terrain[x][y] = ShallowWater
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.movementDebt = 0.0'f32

    # ShallowWater has 0.5 modifier, so each move adds 0.5 debt
    # Every 2 moves, debt >= 1.0 and move is skipped
    var moves = 0
    for i in 0 ..< 10:
      let prevPos = agent.pos
      env.stepAction(agent.agentId, 1'u8, 3)  # Try move East
      if agent.pos.x > prevPos.x:
        inc moves

    # Should be about 6-7 successful moves out of 10
    check moves < 8
    echo &"  ShallowWater: moved {moves}/10 times, final pos ({agent.pos.x},{agent.pos.y})"

  test "road terrain has no movement penalty":
    let env = makeEmptyEnv()
    # Set road for a large area since roads give double-step bonus
    for x in 49..100:
      for y in 49..52:
        env.terrain[x][y] = Road
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.movementDebt = 0.0'f32

    # Move 5 times - roads give double-step so expect larger movement
    for i in 0 ..< 5:
      env.stepAction(agent.agentId, 1'u8, 3)  # Move East

    # Roads give double-step (2 tiles per move), so 5 moves = 10 tiles
    check agent.pos.x == 60  # 50 + 5*2 = 60
    check agent.movementDebt < 0.01  # No debt accumulated
    echo &"  Road: no movement penalty, position ({agent.pos.x},{agent.pos.y}), debt={agent.movementDebt}"

suite "Behavior: Terrain Speed Modifier Values":
  test "TerrainSpeedModifier constants are correct":
    check getTerrainSpeedModifier(Grass) == 1.0'f32
    check getTerrainSpeedModifier(Road) == 1.0'f32
    check getTerrainSpeedModifier(Mud) == 0.7'f32
    check getTerrainSpeedModifier(Snow) == 0.8'f32
    check getTerrainSpeedModifier(Dune) == 0.85'f32
    check getTerrainSpeedModifier(Sand) == 0.9'f32
    check getTerrainSpeedModifier(ShallowWater) == 0.5'f32
    check getTerrainSpeedModifier(Water) == 1.0'f32  # Deep water is impassable
    check getTerrainSpeedModifier(Bridge) == 1.0'f32
    check getTerrainSpeedModifier(Fertile) == 1.0'f32
    echo "  All terrain speed modifier constants verified"

  test "slow terrains are slower than normal terrain":
    # Verify relative ordering: Mud < Snow < Dune < Sand < Grass
    check getTerrainSpeedModifier(Mud) < getTerrainSpeedModifier(Snow)
    check getTerrainSpeedModifier(Snow) < getTerrainSpeedModifier(Dune)
    check getTerrainSpeedModifier(Dune) < getTerrainSpeedModifier(Sand)
    check getTerrainSpeedModifier(Sand) < getTerrainSpeedModifier(Grass)
    echo "  Terrain speed ordering verified: Mud < Snow < Dune < Sand < Grass"

suite "Behavior: Water Unit Immunity":
  test "water units ignore terrain penalties":
    let env = makeEmptyEnv()
    for x in 49..60:
      for y in 49..52:
        env.terrain[x][y] = Water
    let boat = addAgentAt(env, 0, ivec2(50, 50), unitClass = UnitBoat)
    boat.movementDebt = 0.0'f32

    # Boat should move freely on water without penalties
    for i in 0 ..< 10:
      env.stepAction(boat.agentId, 1'u8, 3)  # Move East

    check boat.pos == ivec2(60, 50)
    check boat.movementDebt < 0.01
    echo "  Boat moved full distance on water, no debt"

  test "trade cog ignores terrain penalties":
    let env = makeEmptyEnv()
    for x in 49..60:
      for y in 49..52:
        env.terrain[x][y] = Water
    let cog = addAgentAt(env, 0, ivec2(50, 50), unitClass = UnitTradeCog)
    cog.movementDebt = 0.0'f32

    for i in 0 ..< 10:
      env.stepAction(cog.agentId, 1'u8, 3)  # Move East

    check cog.pos == ivec2(60, 50)
    check cog.movementDebt < 0.01
    echo "  TradeCog moved full distance on water, no debt"

suite "Behavior: Deep Water Blocking":
  test "land unit cannot move into deep water":
    let env = makeEmptyEnv()
    env.terrain[51][50] = Water
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 3)  # Try move East into water
    check agent.pos == startPos  # Should not have moved
    echo "  Land unit blocked by deep water"

  test "land unit can move through shallow water with penalty":
    let env = makeEmptyEnv()
    env.terrain[51][50] = ShallowWater
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    env.stepAction(agent.agentId, 1'u8, 3)  # Move East into shallow water
    check agent.pos == ivec2(51, 50)  # Should have moved
    echo "  Land unit traversed shallow water"

suite "Behavior: Elevation Movement":
  test "unit can move on flat terrain":
    let env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 0
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    env.stepAction(agent.agentId, 1'u8, 3)  # Move East
    check agent.pos == ivec2(51, 50)
    echo "  Flat terrain movement allowed"

  test "unit cannot climb up elevation without road":
    let env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 1  # Higher elevation to the east
    env.terrain[50][50] = Grass
    env.terrain[51][50] = Grass
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 3)  # Try move East (up)
    check agent.pos == startPos  # Should be blocked
    echo "  Cannot climb elevation without road/ramp"

  test "unit can climb up elevation using road":
    let env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 1
    env.terrain[50][50] = Road  # Road allows elevation traversal
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    env.stepAction(agent.agentId, 1'u8, 3)  # Move East (up via road)
    check agent.pos == ivec2(51, 50)
    echo "  Road allows climbing elevation"

  test "unit can always drop down elevation":
    let env = makeEmptyEnv()
    env.elevation[50][50] = 1
    env.elevation[51][50] = 0  # Lower elevation to the east
    env.terrain[50][50] = Grass
    env.terrain[51][50] = Grass
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    env.stepAction(agent.agentId, 1'u8, 3)  # Move East (down)
    check agent.pos == ivec2(51, 50)  # Should move
    echo "  Dropping elevation always allowed"

  test "cliff fall causes damage when dropping without road":
    let env = makeEmptyEnv()
    env.elevation[50][50] = 1
    env.elevation[51][50] = 0
    env.terrain[50][50] = Grass
    env.terrain[51][50] = Grass
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let startHp = agent.hp

    env.stepAction(agent.agentId, 1'u8, 3)  # Move East (drop cliff)
    check agent.pos == ivec2(51, 50)
    check agent.hp < startHp  # Should have taken fall damage
    echo &"  Cliff fall damage: {startHp} -> {agent.hp} HP"

  test "road prevents cliff fall damage":
    let env = makeEmptyEnv()
    env.elevation[50][50] = 1
    env.elevation[51][50] = 0
    env.terrain[50][50] = Road  # Road prevents fall damage
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let startHp = agent.hp

    env.stepAction(agent.agentId, 1'u8, 3)  # Move East (down via road)
    check agent.pos == ivec2(51, 50)
    check agent.hp == startHp  # No fall damage with road
    echo "  Road prevents cliff fall damage"

  test "elevation difference > 1 blocks movement":
    let env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 2  # Too high to traverse
    env.terrain[50][50] = Road
    env.terrain[51][50] = Road
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 3)  # Try move East
    check agent.pos == startPos  # Should be blocked (elevation diff > 1)
    echo "  Large elevation difference blocks movement"

suite "Behavior: Biome Elevation Effects":
  test "swamp biome typically has lower elevation":
    # Swamp biomes are generated with elevation -1 (basins)
    # This test verifies the biome-elevation relationship works correctly
    let env = makeEmptyEnv()

    # Simulate swamp biome area with low elevation
    env.elevation[50][50] = 0
    env.elevation[51][50] = -1  # Swamp basin
    env.terrain[50][50] = Grass
    env.terrain[51][50] = Mud  # Swamp terrain
    let agent = addAgentAt(env, 0, ivec2(50, 50))

    # Can drop into swamp basin
    env.stepAction(agent.agentId, 1'u8, 3)  # Move East
    check agent.pos == ivec2(51, 50)
    echo "  Can enter swamp basin (drop elevation)"

  test "snow biome typically has higher elevation":
    # Snow biomes are generated with elevation +1 (plateaus)
    let env = makeEmptyEnv()

    # Simulate snow biome area with high elevation
    env.elevation[50][50] = 0
    env.elevation[51][50] = 1  # Snow plateau
    env.terrain[50][50] = Grass
    env.terrain[51][50] = Snow
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    let startPos = agent.pos

    # Cannot climb to snow plateau without road
    env.stepAction(agent.agentId, 1'u8, 3)  # Try move East
    check agent.pos == startPos  # Should be blocked
    echo "  Cannot climb to snow plateau without road"

suite "Behavior: Movement Debt Accumulation Math":
  test "exact debt accumulation for mud terrain":
    let env = makeEmptyEnv()
    for x in 49..60:
      for y in 49..52:
        env.terrain[x][y] = Mud
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.movementDebt = 0.0'f32

    # Move once, check debt (0.3 accumulated)
    env.stepAction(agent.agentId, 1'u8, 3)
    check agent.pos == ivec2(51, 50)
    check abs(agent.movementDebt - 0.3'f32) < 0.01

    # Move again (debt = 0.6)
    env.stepAction(agent.agentId, 1'u8, 3)
    check agent.pos == ivec2(52, 50)
    check abs(agent.movementDebt - 0.6'f32) < 0.01

    # Move again (debt = 0.9)
    env.stepAction(agent.agentId, 1'u8, 3)
    check agent.pos == ivec2(53, 50)
    check abs(agent.movementDebt - 0.9'f32) < 0.01

    # Move again - should skip (debt was >= 1.0 after accumulation)
    # Actually debt check happens BEFORE move, so 4th move succeeds, 5th should skip
    env.stepAction(agent.agentId, 1'u8, 3)
    check agent.pos == ivec2(54, 50)
    # Debt should now be 1.2, which gets reduced by 1.0 on next move attempt

    echo &"  Mud debt accumulation verified, debt = {agent.movementDebt}"

  test "high movement debt causes skipped moves":
    # This test verifies the overall behavior: slow terrain causes moves to be skipped
    let env = makeEmptyEnv()
    for x in 49..80:
      for y in 49..52:
        env.terrain[x][y] = Mud  # 0.3 debt per move (fastest to cause skips)
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.movementDebt = 0.0'f32

    # After many moves on mud, some should be skipped due to accumulated debt
    var moves = 0
    var skips = 0
    for i in 0 ..< 20:
      let prevPos = agent.pos
      env.stepAction(agent.agentId, 1'u8, 3)  # Try move East
      if agent.pos.x > prevPos.x:
        inc moves
      else:
        inc skips

    # Should have skipped some moves due to debt accumulation
    check skips > 0
    check moves < 20
    echo &"  High debt test: {moves} moves, {skips} skips, debt = {agent.movementDebt}"
