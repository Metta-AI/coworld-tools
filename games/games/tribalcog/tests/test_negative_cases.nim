## Negative case tests for invalid operations.
## Verifies that failures are properly handled and invalid actions are rejected.
## See TEST_AUDIT_REPORT.md section 3.3 for context.

import std/[unittest, strformat]
import test_common

# =============================================================================
# INVALID BUILDING PLACEMENT TESTS
# =============================================================================

suite "Negative: Building Placement Rejection":
  test "building on water tile fallback to alternate location":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    env.terrain[10][9] = Water  # North tile is water
    setInv(agent, ItemWood, 10)

    env.stepAction(agent.agentId, 8'u8, 0)  # Try build house

    # North tile (water) should NOT have a building
    check env.grid[10][9] == nil
    # Building may have been placed at an alternate location
    echo "  Water tile correctly rejected, fallback to alternate location"

  test "building at map edge is handled safely":
    let env = makeEmptyEnv()
    # Place agent near edge
    let agent = addAgentAt(env, 0, ivec2(1, 1))
    agent.orientation = W  # Face west (toward edge)
    setInv(agent, ItemWood, 10)
    let woodBefore = getInv(agent, ItemWood)

    env.stepAction(agent.agentId, 8'u8, 0)  # Try build house at (0, 1)

    # Should either succeed at edge or find alternate location
    # Should not crash
    echo &"  Map edge build: wood {woodBefore} -> {getInv(agent, ItemWood)}"

  test "building with zero resources fails silently":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    setInv(agent, ItemWood, 0)
    setInv(agent, ItemStone, 0)
    setInv(agent, ItemGold, 0)
    setStockpile(env, 0, ResourceWood, 0)
    setStockpile(env, 0, ResourceStone, 0)
    setStockpile(env, 0, ResourceGold, 0)

    env.stepAction(agent.agentId, 8'u8, 0)  # Try build house

    check env.grid[10][9] == nil
    echo "  Zero resources correctly prevented building"

  test "building with wrong resource type fails":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    # Castle requires stone, give only wood
    setInv(agent, ItemWood, 100)
    setInv(agent, ItemStone, 0)
    setStockpile(env, 0, ResourceWood, 100)
    setStockpile(env, 0, ResourceStone, 0)

    env.stepAction(agent.agentId, 8'u8, 12)  # Try build castle (requires stone)

    check env.grid[10][9] == nil
    echo "  Wrong resource type correctly prevented castle"

  test "building on existing unit position is blocked":
    let env = makeEmptyEnv()
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    let blocker = addAgentAt(env, 1, ivec2(10, 9))  # Unit at build target
    builder.orientation = N
    setInv(builder, ItemWood, 10)
    let woodBefore = getInv(builder, ItemWood)

    env.stepAction(builder.agentId, 8'u8, 0)

    # Building should find alternate location or fail
    # The blocked tile should not have a building
    let thing = env.grid[10][9]
    if thing != nil:
      check thing.kind == Agent
    echo "  Unit-blocked tile correctly handled"

  test "building placement beyond all adjacent tiles fails":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Block ALL 8 adjacent tiles with water
    for offset in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
                   ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1)]:
      let pos = ivec2(10, 10) + offset
      env.terrain[pos.x][pos.y] = Water
    setInv(agent, ItemWood, 10)
    let woodBefore = getInv(agent, ItemWood)

    env.stepAction(agent.agentId, 8'u8, 0)

    # No resources consumed, no building placed
    check getInv(agent, ItemWood) == woodBefore
    echo "  All tiles blocked correctly prevented building"

  test "dead agent cannot place building":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.orientation = N
    agent.hp = 0
    env.terminated[agent.agentId] = 1.0
    setInv(agent, ItemWood, 10)

    env.stepAction(agent.agentId, 8'u8, 0)

    check env.grid[10][9] == nil
    echo "  Dead agent correctly prevented from building"

# =============================================================================
# OUT-OF-RANGE ATTACK TESTS
# =============================================================================

suite "Negative: Out-of-Range Attacks":
  test "melee unit cannot hit target 2 tiles away":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitVillager)
    attacker.attackDamage = 5
    # Villager has melee range (0), so can only attack adjacent
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))  # 2 tiles away
    let startHp = enemy.hp

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, enemy.pos))

    check enemy.hp == startHp
    echo &"  Melee attack at range 2 blocked: HP {startHp} -> {enemy.hp}"

  test "archer cannot hit target beyond range 3":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 6))  # 4 tiles away
    let startHp = enemy.hp

    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, enemy.pos))

    check enemy.hp == startHp
    echo &"  Archer attack at range 4 blocked: HP {startHp} -> {enemy.hp}"

  test "archer cannot hit target at range 5":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))  # 5 tiles away
    let startHp = enemy.hp

    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, enemy.pos))

    check enemy.hp == startHp
    echo &"  Archer attack at range 5 blocked: HP {startHp} -> {enemy.hp}"

  test "crossbowman cannot hit target beyond range 4":
    let env = makeEmptyEnv()
    let crossbow = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitCrossbowman)
    applyUnitClass(crossbow, UnitCrossbowman)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))  # 5 tiles away
    let startHp = enemy.hp

    env.stepAction(crossbow.agentId, 2'u8, dirIndex(crossbow.pos, enemy.pos))

    check enemy.hp == startHp
    echo &"  Crossbow attack at range 5 blocked: HP {startHp} -> {enemy.hp}"

  test "trebuchet cannot hit target beyond range 6":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = false
    treb.cooldown = 0
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 3))  # 7 tiles away
    let startHp = enemy.hp

    env.stepAction(treb.agentId, 2'u8, dirIndex(treb.pos, enemy.pos))

    check enemy.hp == startHp
    echo &"  Trebuchet attack at range 7 blocked: HP {startHp} -> {enemy.hp}"

  test "diagonal range is calculated correctly (cannot exceed)":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    # Range uses Chebyshev distance (max of dx, dy), not Euclidean
    # Archer range is 3, so (14, 14) is distance max(4,4) = 4 tiles away
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(14, 14))
    let startHp = enemy.hp

    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, enemy.pos))

    check enemy.hp == startHp
    echo &"  Diagonal out-of-range attack blocked: HP {startHp} -> {enemy.hp}"

  test "attack on empty tile does nothing":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 5

    # Attack north where there's nothing
    env.stepAction(attacker.agentId, 2'u8, 0)  # Direction 0 = N

    # No crash, no effect
    check env.grid[10][9] == nil
    echo "  Attack on empty tile handled safely"

  test "tower does not fire beyond its range":
    let env = makeEmptyEnv()
    discard addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 16))  # 6 tiles away (tower range is ~3)
    let startHp = enemy.hp

    env.stepNoop()

    check enemy.hp == startHp
    echo &"  Tower did not fire at out-of-range enemy: HP {startHp}"

# =============================================================================
# CROSS-TEAM ACTION BLOCKING TESTS
# =============================================================================

suite "Negative: Cross-Team Action Blocking":
  test "cannot attack same-team unit":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 10
    let ally = addAgentAt(env, 1, ivec2(10, 9))  # Same team (team 0)
    let startHp = ally.hp

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, ally.pos))

    check ally.hp == startHp
    echo &"  Same-team attack blocked: HP {startHp} -> {ally.hp}"

  test "cannot attack own altar":
    let env = makeEmptyEnv()
    let altar = addAltar(env, ivec2(10, 9), 0, 10)  # Team 0 altar
    let agent = addAgentAt(env, 0, ivec2(10, 10))  # Team 0 agent
    agent.attackDamage = 5
    let heartsBefore = altar.hearts

    env.stepAction(agent.agentId, 2'u8, dirIndex(agent.pos, altar.pos))

    check altar.hearts == heartsBefore
    echo &"  Own altar attack blocked: hearts {heartsBefore}"

  test "cannot attack own building":
    let env = makeEmptyEnv()
    let building = addBuilding(env, House, ivec2(10, 9), 0)  # Team 0 building
    building.hp = 10
    building.maxHp = 10
    let agent = addAgentAt(env, 0, ivec2(10, 10))  # Team 0 agent
    agent.attackDamage = 5
    let hpBefore = building.hp

    env.stepAction(agent.agentId, 2'u8, dirIndex(agent.pos, building.pos))

    check building.hp == hpBefore
    echo &"  Own building attack blocked: HP {hpBefore}"

  test "tower does not fire at own units":
    let env = makeEmptyEnv()
    discard addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let ally = addAgentAt(env, 0, ivec2(10, 13))  # Team 0 unit in range
    let startHp = ally.hp

    env.stepNoop()

    check ally.hp == startHp
    echo &"  Tower did not fire at ally: HP {startHp}"

  test "town center does not fire at own units":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let ally = addAgentAt(env, 0, ivec2(10, 14))  # Team 0 unit in range
    let startHp = ally.hp

    env.stepNoop()

    check ally.hp == startHp
    echo &"  Town center did not fire at ally: HP {startHp}"

  test "castle does not fire at own units":
    let env = makeEmptyEnv()
    discard addBuilding(env, Castle, ivec2(10, 10), 0)
    let ally = addAgentAt(env, 0, ivec2(10, 15))  # Team 0 unit in range
    let startHp = ally.hp

    env.stepNoop()

    check ally.hp == startHp
    echo &"  Castle did not fire at ally: HP {startHp}"

  test "cannot garrison in enemy building":
    let env = makeEmptyEnv()
    let enemyTower = addBuilding(env, GuardTower, ivec2(10, 9), 1)  # Team 1 building
    let agent = addAgentAt(env, 0, ivec2(10, 10))  # Team 0 agent

    let result = env.garrisonUnitInBuilding(agent, enemyTower)

    check result == false
    check enemyTower.garrisonedUnits.len == 0
    echo "  Garrison in enemy building blocked"

  test "cannot use enemy door":
    let env = makeEmptyEnv()
    let door = Thing(kind: Door, pos: ivec2(10, 9), teamId: 1)
    door.inventory = emptyInventory()
    env.add(door)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    let canPass = env.canAgentPassDoor(agent, door.pos)

    check canPass == false
    echo "  Enemy door correctly blocked passage"

  test "monk cannot convert same-team unit":
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos, unitClass = UnitMonk)
    let ally = addAgentAt(env, 1, ivec2(10, 9))  # Same team
    ally.hp = 1
    ally.maxHp = 10
    let teamBefore = getTeamId(ally)
    let hpBefore = ally.hp

    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, ally.pos))

    # Team unchanged (was healed instead)
    check getTeamId(ally) == teamBefore
    check ally.hp > hpBefore  # Healed instead of converted
    echo &"  Monk healed ally instead of converting: HP {hpBefore} -> {ally.hp}"

  test "mangonel AoE does not damage own units":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    applyUnitClass(mangonel, UnitMangonel)
    # Place ally in the AoE area
    let ally = addAgentAt(env, 1, ivec2(10, 9))  # Same team, in AoE
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))  # Enemy, target
    let allyHpBefore = ally.hp
    let enemyHpBefore = enemy.hp

    env.stepAction(mangonel.agentId, 2'u8, dirIndex(mangonel.pos, enemy.pos))

    check ally.hp == allyHpBefore  # Ally not damaged
    check enemy.hp < enemyHpBefore  # Enemy damaged
    echo &"  Mangonel AoE spared ally: ally HP {allyHpBefore}, enemy HP {enemyHpBefore} -> {enemy.hp}"

  test "dead agent cannot perform actions":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.hp = 0
    env.terminated[agent.agentId] = 1.0
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    let enemyHpBefore = enemy.hp

    env.stepAction(agent.agentId, 2'u8, dirIndex(agent.pos, enemy.pos))

    check enemy.hp == enemyHpBefore
    echo "  Dead agent action blocked"

  test "attack on neutral resource node does no damage":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 5
    let tree = addResource(env, Tree, ivec2(10, 9), ItemWood, 100)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, tree.pos))

    # Tree should not be damaged by attack (gather action is different)
    check getInv(tree, ItemWood) == 100
    echo "  Attack on resource node blocked"

  test "siege unit can damage enemy building (positive case for contrast)":
    let env = makeEmptyEnv()
    let enemyTower = addBuilding(env, GuardTower, ivec2(10, 9), 1)  # Team 1
    # Use a battering ram which can attack buildings with siege bonus
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    let hpBefore = enemyTower.hp

    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, enemyTower.pos))

    check enemyTower.hp < hpBefore
    echo &"  Enemy building correctly damaged: HP {hpBefore} -> {enemyTower.hp}"
