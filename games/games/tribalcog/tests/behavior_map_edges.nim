import std/[unittest, strformat]
import test_common
import common

## Behavioral tests for map edge boundary conditions.
## Verifies that all unit types correctly handle map edges - pathfinding near
## boundaries, building placement at edges, ranged combat at map limits,
## and fog of war at corners.

suite "Behavior: Movement at Map Borders":
  test "unit blocked at north border":
    let env = makeEmptyEnv()
    let borderY = MapBorder.int32
    let agent = addAgentAt(env, 0, ivec2(50, borderY))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 0)  # N
    check agent.pos == startPos
    echo &"  Unit blocked at north border y={borderY}"

  test "unit blocked at south border":
    let env = makeEmptyEnv()
    let borderY = (MapHeight - MapBorder - 1).int32
    let agent = addAgentAt(env, 0, ivec2(50, borderY))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 1)  # S
    check agent.pos == startPos
    echo &"  Unit blocked at south border y={borderY}"

  test "unit blocked at west border":
    let env = makeEmptyEnv()
    let borderX = MapBorder.int32
    let agent = addAgentAt(env, 0, ivec2(borderX, 50))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 2)  # W
    check agent.pos == startPos
    echo &"  Unit blocked at west border x={borderX}"

  test "unit blocked at east border":
    let env = makeEmptyEnv()
    let borderX = (MapWidth - MapBorder - 1).int32
    let agent = addAgentAt(env, 0, ivec2(borderX, 50))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos == startPos
    echo &"  Unit blocked at east border x={borderX}"

  test "unit can move along border without crossing it":
    let env = makeEmptyEnv()
    let borderY = MapBorder.int32
    let agent = addAgentAt(env, 0, ivec2(50, borderY))

    # Move east along north border
    env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos == ivec2(51, borderY)
    echo "  Unit moved east along north border"

suite "Behavior: Corner Movement Constraints":
  test "unit blocked in northwest corner":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(MapBorder.int32, MapBorder.int32))
    let startPos = agent.pos

    # Try north
    env.stepAction(agent.agentId, 1'u8, 0)
    check agent.pos == startPos
    # Try west
    env.stepAction(agent.agentId, 1'u8, 2)
    check agent.pos == startPos
    echo "  NW corner blocks N and W movement"

  test "unit blocked in northeast corner":
    let env = makeEmptyEnv()
    let edgeX = (MapWidth - MapBorder - 1).int32
    let agent = addAgentAt(env, 0, ivec2(edgeX, MapBorder.int32))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 0)  # N
    check agent.pos == startPos
    env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos == startPos
    echo "  NE corner blocks N and E movement"

  test "unit blocked in southwest corner":
    let env = makeEmptyEnv()
    let edgeY = (MapHeight - MapBorder - 1).int32
    let agent = addAgentAt(env, 0, ivec2(MapBorder.int32, edgeY))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 1)  # S
    check agent.pos == startPos
    env.stepAction(agent.agentId, 1'u8, 2)  # W
    check agent.pos == startPos
    echo "  SW corner blocks S and W movement"

  test "unit blocked in southeast corner":
    let env = makeEmptyEnv()
    let edgeX = (MapWidth - MapBorder - 1).int32
    let edgeY = (MapHeight - MapBorder - 1).int32
    let agent = addAgentAt(env, 0, ivec2(edgeX, edgeY))
    let startPos = agent.pos

    env.stepAction(agent.agentId, 1'u8, 1)  # S
    check agent.pos == startPos
    env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos == startPos
    echo "  SE corner blocks S and E movement"

  test "unit can escape corner inward":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(MapBorder.int32, MapBorder.int32))

    # Move south (inward)
    env.stepAction(agent.agentId, 1'u8, 1)  # S
    check agent.pos == ivec2(MapBorder.int32, MapBorder.int32 + 1)
    echo "  Unit escaped NW corner by moving south"

suite "Behavior: All Unit Types at Map Edges":
  test "cavalry blocked at border like infantry":
    let env = makeEmptyEnv()
    let borderX = (MapWidth - MapBorder - 1).int32
    let knight = addAgentAt(env, 0, ivec2(borderX, 50), unitClass = UnitKnight)
    applyUnitClass(knight, UnitKnight)
    let startPos = knight.pos

    env.stepAction(knight.agentId, 1'u8, 3)  # E
    check knight.pos == startPos
    echo "  Knight blocked at east border"

  test "scout blocked at border despite fast movement":
    let env = makeEmptyEnv()
    let borderY = MapBorder.int32
    let scout = addAgentAt(env, 0, ivec2(50, borderY), unitClass = UnitScout)
    applyUnitClass(scout, UnitScout)
    let startPos = scout.pos

    env.stepAction(scout.agentId, 1'u8, 0)  # N
    check scout.pos == startPos
    echo "  Scout blocked at north border"

  test "siege unit blocked at border":
    let env = makeEmptyEnv()
    let borderX = MapBorder.int32
    let ram = addAgentAt(env, 0, ivec2(borderX, 50), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    let startPos = ram.pos

    env.stepAction(ram.agentId, 1'u8, 2)  # W
    check ram.pos == startPos
    echo "  Battering ram blocked at west border"

  test "villager blocked at border":
    let env = makeEmptyEnv()
    let borderY = (MapHeight - MapBorder - 1).int32
    let villager = addAgentAt(env, 0, ivec2(50, borderY), unitClass = UnitVillager)
    let startPos = villager.pos

    env.stepAction(villager.agentId, 1'u8, 1)  # S
    check villager.pos == startPos
    echo "  Villager blocked at south border"

  test "monk blocked at border":
    let env = makeEmptyEnv()
    let borderX = (MapWidth - MapBorder - 1).int32
    let monk = addAgentAt(env, 0, ivec2(borderX, 50), unitClass = UnitMonk)
    applyUnitClass(monk, UnitMonk)
    let startPos = monk.pos

    env.stepAction(monk.agentId, 1'u8, 3)  # E
    check monk.pos == startPos
    echo "  Monk blocked at east border"

suite "Behavior: Building Placement at Map Edges":
  test "can place building at border tile":
    let env = makeEmptyEnv()
    let borderY = MapBorder.int32
    # Agent one tile inside border, facing north toward border
    let agent = addAgentAt(env, 0, ivec2(50, borderY + 1))
    agent.orientation = N
    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, 0)  # Build house

    # Border tile (y=1) is still valid, building should be placed
    let targetPos = ivec2(50, borderY)
    check env.grid[targetPos.x][targetPos.y] != nil
    check env.grid[targetPos.x][targetPos.y].kind == House
    echo "  Building placed at north border tile"

  test "build at edge falls back to adjacent valid tile":
    let env = makeEmptyEnv()
    # Agent at y=0, facing north would target y=-1 (invalid)
    # Build action scans fallback offsets and finds a valid adjacent tile
    let agent = addAgentAt(env, 0, ivec2(50, 0))
    agent.orientation = N
    setInv(agent, ItemWood, 5)
    let woodBefore = getInv(agent, ItemWood)

    env.stepAction(agent.agentId, 8'u8, 0)  # Build house

    # Build succeeds on an adjacent tile (south, east, or west of agent)
    check getInv(agent, ItemWood) < woodBefore
    echo "  Build at edge fell back to adjacent valid tile"

  test "can place building just inside border":
    let env = makeEmptyEnv()
    # Agent at (50, MapBorder+2) facing north places at (50, MapBorder+1) - inside border
    let agent = addAgentAt(env, 0, ivec2(50, MapBorder.int32 + 2))
    agent.orientation = N
    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, 0)  # Build house

    let targetPos = ivec2(50, MapBorder.int32 + 1)
    check env.grid[targetPos.x][targetPos.y] != nil
    check env.grid[targetPos.x][targetPos.y].kind == House
    echo "  Building placed just inside border"

  test "can place building at east border tile":
    let env = makeEmptyEnv()
    let borderX = (MapWidth - MapBorder - 1).int32
    # Agent one tile inside, facing east toward border
    let agent = addAgentAt(env, 0, ivec2(borderX - 1, 50))
    agent.orientation = E
    setInv(agent, ItemWood, 5)

    env.stepAction(agent.agentId, 8'u8, 0)  # Build house

    let targetPos = ivec2(borderX, 50)
    check env.grid[targetPos.x][targetPos.y] != nil
    check env.grid[targetPos.x][targetPos.y].kind == House
    echo "  Building placed at east border tile"

suite "Behavior: Ranged Combat at Map Edges":
  test "archer attacks enemy at border":
    let env = makeEmptyEnv()
    let borderY = MapBorder.int32
    # Archer 3 tiles south of border, enemy at border
    let archer = addAgentAt(env, 0, ivec2(50, borderY + ArcherBaseRange.int32), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(50, borderY))
    let startHp = enemy.hp

    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, enemy.pos))
    check enemy.hp < startHp
    echo &"  Archer hit enemy at border, HP {startHp} -> {enemy.hp}"

  test "archer at border attacks enemy inland":
    let env = makeEmptyEnv()
    let borderY = MapBorder.int32
    let archer = addAgentAt(env, 0, ivec2(50, borderY), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(50, borderY + ArcherBaseRange.int32))
    let startHp = enemy.hp

    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, enemy.pos))
    check enemy.hp < startHp
    echo &"  Archer at border hit inland enemy, HP {startHp} -> {enemy.hp}"

  test "trebuchet fires toward map edge":
    let env = makeEmptyEnv()
    let borderX = (MapWidth - MapBorder - 1).int32
    let treb = addAgentAt(env, 0, ivec2(borderX - TrebuchetBaseRange.int32, 50))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = false
    treb.cooldown = 0
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(borderX, 50))
    let startHp = enemy.hp

    env.stepAction(treb.agentId, 2'u8, dirIndex(treb.pos, enemy.pos))
    check enemy.hp < startHp
    echo &"  Trebuchet hit enemy at east border, HP {startHp} -> {enemy.hp}"

  test "melee combat works at border":
    let env = makeEmptyEnv()
    let borderX = MapBorder.int32
    let attacker = addAgentAt(env, 0, ivec2(borderX + 1, 50), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(attacker, UnitManAtArms)
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(borderX, 50), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(defender, UnitManAtArms)
    let startHp = defender.hp

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))
    check defender.hp < startHp
    echo &"  Melee hit at west border, HP {startHp} -> {defender.hp}"

  test "combat between units in corner":
    let env = makeEmptyEnv()
    let cornerX = MapBorder.int32
    let cornerY = MapBorder.int32
    let attacker = addAgentAt(env, 0, ivec2(cornerX + 1, cornerY), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(attacker, UnitManAtArms)
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(cornerX, cornerY), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(defender, UnitManAtArms)
    let startHp = defender.hp

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))
    check defender.hp < startHp
    echo &"  Melee hit at NW corner, HP {startHp} -> {defender.hp}"

suite "Behavior: Fog of War at Map Edges":
  test "vision reveals tiles at map border":
    let env = makeEmptyEnv()
    let teamId = 0
    let borderY = MapBorder.int32
    let scout = addAgentAt(env, teamId, ivec2(50, borderY))
    applyUnitClass(scout, UnitScout)

    env.updateRevealedMapFromVision(scout)
    check env.isRevealed(teamId, ivec2(50, borderY))
    echo "  Tiles revealed at north border"

  test "vision at corner does not overflow map bounds":
    let env = makeEmptyEnv()
    let teamId = 0
    let scout = addAgentAt(env, teamId, ivec2(MapBorder.int32, MapBorder.int32))
    applyUnitClass(scout, UnitScout)

    # Should not crash - vision circle clips at map boundaries
    env.updateRevealedMapFromVision(scout)
    check env.isRevealed(teamId, ivec2(MapBorder.int32, MapBorder.int32))

    # Tiles inside vision range should be revealed
    check env.isRevealed(teamId, ivec2(MapBorder.int32 + 5, MapBorder.int32 + 5))
    echo "  Vision at NW corner works without overflow"

  test "vision at southeast corner clips correctly":
    let env = makeEmptyEnv()
    let teamId = 0
    let edgeX = (MapWidth - MapBorder - 1).int32
    let edgeY = (MapHeight - MapBorder - 1).int32
    let scout = addAgentAt(env, teamId, ivec2(edgeX, edgeY))
    applyUnitClass(scout, UnitScout)

    env.updateRevealedMapFromVision(scout)
    check env.isRevealed(teamId, ivec2(edgeX, edgeY))
    # Tiles inward from corner should be revealed
    check env.isRevealed(teamId, ivec2(edgeX - 5, edgeY - 5))
    echo "  Vision at SE corner clips correctly"

  test "vision reveals fewer tiles at corner than center":
    let env = makeEmptyEnv()
    let teamId = 0

    # Scout at corner
    let cornerScout = addAgentAt(env, 0, ivec2(MapBorder.int32, MapBorder.int32))
    applyUnitClass(cornerScout, UnitScout)
    env.updateRevealedMapFromVision(cornerScout)
    let cornerCount = env.getRevealedTileCount(teamId)

    # Fresh env, scout at center
    let env2 = makeEmptyEnv()
    let centerScout = addAgentAt(env2, 0, ivec2(150, 95))
    applyUnitClass(centerScout, UnitScout)
    env2.updateRevealedMapFromVision(centerScout)
    let centerCount = env2.getRevealedTileCount(teamId)

    # Corner vision is clipped so reveals fewer tiles
    check cornerCount < centerCount
    echo &"  Corner: {cornerCount} tiles, Center: {centerCount} tiles"

  test "all four corners can be revealed":
    let env = makeEmptyEnv()
    let teamId = 0
    let bx = MapBorder.int32
    let by = MapBorder.int32
    let ex = (MapWidth - MapBorder - 1).int32
    let ey = (MapHeight - MapBorder - 1).int32

    # Place scouts at all four corners
    let s1 = addAgentAt(env, 0, ivec2(bx, by))
    let s2 = addAgentAt(env, 1, ivec2(ex, by))
    let s3 = addAgentAt(env, 2, ivec2(bx, ey))
    let s4 = addAgentAt(env, 3, ivec2(ex, ey))

    for s in [s1, s2, s3, s4]:
      applyUnitClass(s, UnitScout)
      env.updateRevealedMapFromVision(s)

    check env.isRevealed(teamId, ivec2(bx, by))
    check env.isRevealed(teamId, ivec2(ex, by))
    check env.isRevealed(teamId, ivec2(bx, ey))
    check env.isRevealed(teamId, ivec2(ex, ey))
    echo "  All four corners revealed"

suite "Behavior: Pathfinding Along Map Edges":
  test "unit walks along north border":
    let env = makeEmptyEnv()
    let borderY = MapBorder.int32
    let agent = addAgentAt(env, 0, ivec2(10, borderY))

    # Walk east along the border for 10 steps
    for i in 0 ..< 10:
      env.stepAction(agent.agentId, 1'u8, 3)  # E
    check agent.pos == ivec2(20, borderY)
    echo &"  Walked 10 tiles east along north border"

  test "unit walks along east border":
    let env = makeEmptyEnv()
    let borderX = (MapWidth - MapBorder - 1).int32
    let agent = addAgentAt(env, 0, ivec2(borderX, 10))

    for i in 0 ..< 10:
      env.stepAction(agent.agentId, 1'u8, 1)  # S
    check agent.pos == ivec2(borderX, 20)
    echo &"  Walked 10 tiles south along east border"

  test "unit navigates around corner":
    let env = makeEmptyEnv()
    let borderX = (MapWidth - MapBorder - 1).int32
    let borderY = MapBorder.int32
    let agent = addAgentAt(env, 0, ivec2(borderX, borderY + 2))

    # Walk north to corner
    env.stepAction(agent.agentId, 1'u8, 0)  # N
    env.stepAction(agent.agentId, 1'u8, 0)  # N - now at corner
    check agent.pos == ivec2(borderX, borderY)

    # Try to continue north - blocked
    env.stepAction(agent.agentId, 1'u8, 0)  # N
    check agent.pos == ivec2(borderX, borderY)

    # Go west along border instead
    env.stepAction(agent.agentId, 1'u8, 2)  # W
    check agent.pos == ivec2(borderX - 1, borderY)
    echo "  Unit navigated around NE corner"

  test "multiple units can walk along same border":
    let env = makeEmptyEnv()
    let borderY = MapBorder.int32
    let unit1 = addAgentAt(env, 0, ivec2(10, borderY))
    let unit2 = addAgentAt(env, 1, ivec2(12, borderY))

    # Both walk east
    env.stepAction(unit1.agentId, 1'u8, 3)  # E
    env.stepAction(unit2.agentId, 1'u8, 3)  # E
    check unit1.pos == ivec2(11, borderY)
    check unit2.pos == ivec2(13, borderY)
    echo "  Two units walked along border independently"
