## Negative case tests for building placement and combat (tv-a3w5mw).
##
## Tests that verify failures are properly handled:
## - Building placement: blocked tiles, wrong terrain, insufficient resources
## - Combat: out of range, friendly fire prevention, dead targets
##
## See docs/TEST_AUDIT_REPORT.md section 3.3 for context.

import std/[unittest, strformat]
import test_common

suite "Negative Cases: Building Placement - Blocked Tiles":
  test "cannot place building when all 8 adjacent tiles are blocked by units":
    let env = makeEmptyEnv()
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    setInv(builder, ItemWood, 10)
    let woodBefore = getInv(builder, ItemWood)

    # Block ALL adjacent tiles with enemy units
    var idx = MapAgentsPerTeam
    for offset in [ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
                   ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1)]:
      let pos = ivec2(10, 10) + offset
      discard addAgentAt(env, idx, pos)
      inc idx

    env.stepAction(builder.agentId, 8'u8, 0)  # Try build house

    # Resources should NOT be spent - placement failed
    check getInv(builder, ItemWood) == woodBefore
    echo "  All adjacent tiles blocked by units, placement correctly failed"

  test "cannot place building on tile with tree":
    let env = makeEmptyEnv()
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    setInv(builder, ItemWood, 10)

    # Place a tree at the north tile
    let tree = Thing(kind: Tree, pos: ivec2(10, 9))
    tree.inventory = emptyInventory()
    setInv(tree, ItemWood, 10)
    env.add(tree)

    env.stepAction(builder.agentId, 8'u8, 0)  # Try build house

    # North tile has a tree, building should fall through to alternate location
    let northThing = env.grid[10][9]
    check northThing == nil or northThing.kind != House
    echo "  Tree blocks placement at that tile"

  test "cannot place building on tile with resource node":
    let env = makeEmptyEnv()
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    setInv(builder, ItemWood, 10)

    # Place a gold resource at the north tile
    let gold = Thing(kind: Gold, pos: ivec2(10, 9))
    gold.inventory = emptyInventory()
    setInv(gold, ItemGold, 100)
    env.add(gold)

    env.stepAction(builder.agentId, 8'u8, 0)  # Try build house

    # North tile has a resource, building should fall through
    let northThing = env.grid[10][9]
    check northThing == nil or northThing.kind != House
    echo "  Resource node blocks placement at that tile"

suite "Negative Cases: Building Placement - Wrong Terrain":
  test "cannot place regular building on deep water":
    let env = makeEmptyEnv()
    # Set north tile to deep water
    env.terrain[10][9] = Water
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    setInv(builder, ItemWood, 10)

    env.stepAction(builder.agentId, 8'u8, 0)  # Try build house

    # House should not be on water tile - may have fallen through to another location
    let waterThing = env.grid[10][9]
    check waterThing == nil or waterThing.kind != House
    echo "  Deep water terrain correctly rejects house placement at that tile"

  test "cannot place regular building on shallow water":
    let env = makeEmptyEnv()
    # Set north tile to shallow water
    env.terrain[10][9] = ShallowWater
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    setInv(builder, ItemWood, 10)

    env.stepAction(builder.agentId, 8'u8, 0)  # Try build house

    # House should not be on shallow water tile
    let waterThing = env.grid[10][9]
    check waterThing == nil or waterThing.kind != House
    echo "  Shallow water terrain correctly rejects house placement at that tile"

  test "dock cannot be placed on bridge terrain":
    let env = makeEmptyEnv()
    # Set north tile to bridge (not water)
    env.terrain[10][9] = Bridge
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    setInv(builder, ItemWood, 10)
    let initialWood = getInv(builder, ItemWood)

    env.stepAction(builder.agentId, 8'u8, 6)  # Try build dock

    # Dock requires water, not bridge
    let dockThing = env.getBackgroundThing(ivec2(10, 9))
    check dockThing == nil or dockThing.kind != Dock
    check getInv(builder, ItemWood) == initialWood
    echo "  Bridge terrain correctly rejects dock placement"

suite "Negative Cases: Building Placement - Insufficient Resources":
  test "cannot build barracks without enough wood":
    let env = makeEmptyEnv()
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    # Barracks costs 2 wood, give only 1
    setInv(builder, ItemWood, 1)
    env.setStockpile(0, ResourceWood, 0)  # Empty stockpile too

    env.stepAction(builder.agentId, 8'u8, 1)  # Barracks build index

    let placed = env.grid[10][9]
    check placed == nil
    check getInv(builder, ItemWood) == 1  # Resource not consumed
    echo "  Barracks correctly requires more wood than available"

  test "wall placement consumes wood correctly":
    let env = makeEmptyEnv()
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    let initialWood = 100
    setInv(builder, ItemWood, initialWood)
    env.setStockpile(0, ResourceWood, 0)

    env.stepAction(builder.agentId, 8'u8, BuildIndexWall)

    # Wall should be placed and wood consumed
    let placed = env.grid[10][9]
    check placed != nil
    check placed.kind == Wall
    check getInv(builder, ItemWood) < initialWood
    echo &"  Wall placement uses correct resource type (wood)"

  test "cannot build castle without sufficient stone in inventory AND stockpile":
    let env = makeEmptyEnv()
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    setInv(builder, ItemStone, 10)  # Some stone but not enough
    env.setStockpile(0, ResourceStone, 0)  # Empty stockpile

    env.stepAction(builder.agentId, 8'u8, 12)  # Castle build index

    let placed = env.grid[10][9]
    check placed == nil
    check getInv(builder, ItemStone) == 10  # Resource not consumed
    echo "  Castle correctly requires full stone cost"

  test "town center placement fails without wood":
    let env = makeEmptyEnv()
    let builder = addAgentAt(env, 0, ivec2(10, 10))
    builder.orientation = N
    setInv(builder, ItemWood, 0)
    setInv(builder, ItemStone, 0)
    env.setStockpile(0, ResourceWood, 0)
    env.setStockpile(0, ResourceStone, 0)

    # Town center build index = 4
    env.stepAction(builder.agentId, 8'u8, 4)

    let placed = env.grid[10][9]
    check placed == nil
    echo "  Town center correctly requires resources"

suite "Negative Cases: Combat - Friendly Fire Prevention":
  test "melee attack on same-team unit deals no damage":
    let env = makeEmptyEnv()
    # Two agents on team 0
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 10
    let ally = addAgentAt(env, 1, ivec2(10, 9))  # Agent ID 1 is also team 0
    ally.hp = 100
    ally.maxHp = 100
    let hpBefore = ally.hp

    # Attack direction north toward ally
    env.stepAction(attacker.agentId, 2'u8, 0)  # Verb 2 = attack, arg 0 = N

    # Ally should take NO damage
    check ally.hp == hpBefore
    echo "  Same-team melee attack correctly deals no damage"

  test "ranged attack on same-team unit deals no damage":
    let env = makeEmptyEnv()
    # Archer on team 0
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    # Ally 2 tiles north (within archer range 3)
    let ally = addAgentAt(env, 1, ivec2(10, 8))
    ally.hp = 100
    ally.maxHp = 100
    let hpBefore = ally.hp

    env.stepAction(archer.agentId, 2'u8, 0)  # Attack north

    # Ally should take NO damage
    check ally.hp == hpBefore
    echo "  Same-team ranged attack correctly deals no damage"

  test "siege attack on same-team building deals no damage":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    # Own team's wall
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: 0)  # Same team as ram
    wall.hp = 50
    wall.maxHp = 50
    env.add(wall)
    let hpBefore = wall.hp

    env.stepAction(ram.agentId, 2'u8, 0)  # Attack north

    # Own wall should take NO damage
    check wall.hp == hpBefore
    echo "  Same-team siege attack correctly deals no damage"

  test "monk cannot convert same-team unit":
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos, unitClass = UnitMonk)
    # Ally on same team
    let ally = addAgentAt(env, 1, ivec2(10, 9))
    let teamBefore = getTeamId(ally)

    env.stepAction(monk.agentId, 2'u8, 0)  # Attack/convert north

    # Ally should still be on same team (monk heals allies, doesn't convert them)
    check getTeamId(ally) == teamBefore
    echo "  Monk correctly heals (not converts) same-team unit"

suite "Negative Cases: Combat - Dead/Terminated Targets":
  test "attack on dead unit deals no damage":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 10
    # Create an enemy that's already dead
    let victim = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    victim.hp = 0
    env.terminated[victim.agentId] = 1.0  # Mark as terminated

    # Try to attack the dead unit
    env.stepAction(attacker.agentId, 2'u8, 0)

    # Should not crash, and terminated status should remain
    check env.terminated[victim.agentId] == 1.0
    echo "  Attack on terminated unit correctly does nothing"

  test "attack on dying unit (hp=0 but not yet terminated) is handled":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 10
    let victim = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    victim.hp = 1  # Low HP - will die from attack

    # Attack should kill the victim
    env.stepAction(attacker.agentId, 2'u8, 0)
    check victim.hp <= 0
    check env.terminated[victim.agentId] == 1.0

    # Second attack on now-dead unit should do nothing harmful
    env.stepAction(attacker.agentId, 2'u8, 0)
    check env.terminated[victim.agentId] == 1.0  # Still terminated
    echo "  Second attack on just-killed unit handled correctly"

  test "ranged attack on terminated unit does nothing":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    let victim = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 7))  # Within range
    victim.hp = 0
    env.terminated[victim.agentId] = 1.0

    env.stepAction(archer.agentId, 2'u8, 0)

    # Should not cause issues
    check env.terminated[victim.agentId] == 1.0
    echo "  Ranged attack on terminated unit correctly ignored"

suite "Negative Cases: Combat - Out of Range":
  test "melee attack at distance 2 fails without spear":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 5
    attacker.inventorySpear = 0  # No spear
    # Enemy 2 tiles north (beyond melee range of 1)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    enemy.hp = 100
    enemy.maxHp = 100
    let hpBefore = enemy.hp

    env.stepAction(attacker.agentId, 2'u8, 0)  # Attack north

    # Enemy should take NO damage (out of melee range)
    check enemy.hp == hpBefore
    echo "  Melee attack at distance 2 without spear correctly fails"

  test "melee attack at distance 2 succeeds with spear":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 5
    attacker.inventorySpear = 1  # Has spear
    # Enemy 2 tiles north
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    enemy.hp = 100
    enemy.maxHp = 100
    let hpBefore = enemy.hp

    env.stepAction(attacker.agentId, 2'u8, 0)  # Attack north

    # Enemy SHOULD take damage (spear extends range to 2)
    check enemy.hp < hpBefore
    check attacker.inventorySpear == 0  # Spear consumed
    echo "  Melee attack at distance 2 with spear correctly succeeds"

  test "archer attack at distance 4 fails (range is 3)":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    # Enemy 4 tiles north (beyond archer range of 3)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 6))
    enemy.hp = 100
    enemy.maxHp = 100
    let hpBefore = enemy.hp

    env.stepAction(archer.agentId, 2'u8, 0)

    check enemy.hp == hpBefore
    echo "  Archer attack at distance 4 correctly fails (range is 3)"

  test "trebuchet packed cannot attack":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = true  # Packed - cannot attack
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))
    enemy.hp = 100
    enemy.maxHp = 100
    let hpBefore = enemy.hp

    env.stepAction(treb.agentId, 2'u8, 0)

    # Packed trebuchet cannot attack
    check enemy.hp == hpBefore
    echo "  Packed trebuchet correctly cannot attack"

  test "trebuchet on cooldown cannot attack":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = false
    treb.cooldown = 5  # On cooldown
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))
    enemy.hp = 100
    enemy.maxHp = 100
    let hpBefore = enemy.hp

    env.stepAction(treb.agentId, 2'u8, 0)

    # Trebuchet on cooldown cannot attack
    check enemy.hp == hpBefore
    echo "  Trebuchet on cooldown correctly cannot attack"

suite "Negative Cases: Combat - Invalid Attack Direction":
  test "attack with invalid direction argument is rejected":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    enemy.hp = 100
    enemy.maxHp = 100
    let hpBefore = enemy.hp

    # Invalid direction argument (8+)
    env.stepAction(attacker.agentId, 2'u8, 9)

    # Action should be invalid, no damage dealt
    check enemy.hp == hpBefore
    echo "  Invalid attack direction correctly rejected"
