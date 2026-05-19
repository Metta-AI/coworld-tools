import std/[unittest, strformat]
import test_common

## Behavioral tests for siege unit mechanics: battering rams target buildings
## preferentially, trebuchets use minimum range and area damage, siege units
## have correct stats, pack/unpack mechanics work correctly, and siege units
## are countered by appropriate unit types.

suite "Behavior: Battering Ram Building Targeting":
  test "battering ram deals siege multiplied damage to wall":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)

    let startHp = wall.hp
    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))

    let expectedDamage = BatteringRamAttackDamage * SiegeStructureMultiplier
    check wall.hp == startHp - expectedDamage
    echo &"  Ram dealt {expectedDamage} damage to wall (base {BatteringRamAttackDamage} x{SiegeStructureMultiplier})"

  test "battering ram deals siege multiplied damage to guard tower":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    let tower = addBuilding(env, GuardTower, ivec2(10, 9), 1)
    let startHp = tower.hp

    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, tower.pos))

    let expectedDamage = BatteringRamAttackDamage * SiegeStructureMultiplier
    check tower.hp == startHp - expectedDamage
    echo &"  Ram dealt {expectedDamage} damage to tower (HP: {startHp} -> {tower.hp})"

  test "battering ram destroys wall over sustained attack":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)

    var hits = 0
    while wall.hp > 0 and hits < 50:
      env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))
      inc hits

    check wall.hp <= 0
    check env.grid[10][9] == nil  # Wall removed from grid
    echo &"  Ram destroyed wall in {hits} hits"

  test "battering ram deals normal damage to enemy unit":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    let startHp = enemy.hp

    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, enemy.pos))

    # Against units, siege multiplier does NOT apply - only base damage
    let damageTaken = startHp - enemy.hp
    check damageTaken == BatteringRamAttackDamage
    echo &"  Ram dealt {damageTaken} to unit (no siege bonus)"

suite "Behavior: Battering Ram Stats":
  test "battering ram has correct HP":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)

    check ram.hp == BatteringRamMaxHp
    check ram.maxHp == BatteringRamMaxHp
    echo &"  Battering ram HP: {ram.hp}/{ram.maxHp} (expected {BatteringRamMaxHp})"

  test "battering ram has correct attack damage":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)

    check ram.attackDamage == BatteringRamAttackDamage
    echo &"  Battering ram attack: {ram.attackDamage} (expected {BatteringRamAttackDamage})"

  test "battering ram has extended melee range of 2 tiles":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    # Enemy 2 tiles away - within ram's extended melee range (like Scout)
    let nearEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    let startHp = nearEnemy.hp

    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, nearEnemy.pos))
    check nearEnemy.hp < startHp  # Ram hits at range 2
    echo &"  Ram hit at range 2 (enemy HP: {startHp} -> {nearEnemy.hp})"

  test "battering ram cannot hit beyond range 2":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    # Enemy 3 tiles away - beyond ram range
    let farEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 7))
    let startHp = farEnemy.hp

    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, farEnemy.pos))
    check farEnemy.hp == startHp  # No damage at range 3
    echo &"  Ram cannot hit at range 3 (enemy HP unchanged: {farEnemy.hp})"

suite "Behavior: Trebuchet Pack/Unpack Mechanics":
  test "trebuchet starts packed and cannot attack":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = true
    treb.cooldown = 0
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))
    let startHp = enemy.hp

    env.stepAction(treb.agentId, 2'u8, dirIndex(treb.pos, enemy.pos))
    check enemy.hp == startHp  # Cannot attack while packed
    echo &"  Packed trebuchet cannot attack (enemy HP unchanged: {enemy.hp})"

  test "unpacked trebuchet attacks at long range":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = false
    treb.cooldown = 0
    # Enemy within trebuchet range (6 tiles)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 4))
    let startHp = enemy.hp

    env.stepAction(treb.agentId, 2'u8, dirIndex(treb.pos, enemy.pos))
    check enemy.hp < startHp
    echo &"  Unpacked trebuchet hit at range 6 (HP: {startHp} -> {enemy.hp})"

  test "trebuchet cannot move when unpacked":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = false
    treb.cooldown = 0

    env.stepAction(treb.agentId, 1'u8, 0)  # Try move north
    check treb.pos == ivec2(10, 10)  # Position unchanged
    echo &"  Unpacked trebuchet cannot move (stayed at {treb.pos})"

  test "packed trebuchet can move":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = true
    treb.cooldown = 0

    env.stepAction(treb.agentId, 1'u8, 0)  # Move north
    check treb.pos == ivec2(10, 9)
    echo &"  Packed trebuchet moved north to {treb.pos}"

  test "pack/unpack toggle uses action verb 3 argument 8":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = true
    treb.cooldown = 0

    # Initiate pack/unpack transition
    env.stepAction(treb.agentId, 3'u8, 8)
    check treb.cooldown == TrebuchetPackDuration - 1  # Decremented by 1 during step
    echo &"  Pack/unpack initiated, cooldown: {treb.cooldown}"

  test "pack/unpack transition completes after duration":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = true
    treb.cooldown = 0
    let startPacked = treb.packed

    # Initiate pack/unpack
    env.stepAction(treb.agentId, 3'u8, 8)

    # Step through the transition
    for i in 0 ..< TrebuchetPackDuration:
      env.stepNoop()

    check treb.packed != startPacked  # State toggled
    check treb.cooldown == 0  # Transition complete
    echo &"  Pack state toggled: {startPacked} -> {treb.packed} after {TrebuchetPackDuration} steps"

  test "trebuchet cannot attack during pack/unpack transition":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = false
    treb.cooldown = 0
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))

    # Start transition (unpack -> pack)
    env.stepAction(treb.agentId, 3'u8, 8)
    let startHp = enemy.hp

    # Try to attack during transition
    env.stepAction(treb.agentId, 2'u8, dirIndex(treb.pos, enemy.pos))
    check enemy.hp == startHp  # Cannot attack with cooldown > 0
    echo &"  Trebuchet cannot attack during transition (enemy HP unchanged: {enemy.hp})"

  test "trebuchet cannot move during pack/unpack transition":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = true
    treb.cooldown = 0

    # Start transition
    env.stepAction(treb.agentId, 3'u8, 8)

    # Try to move during transition
    env.stepAction(treb.agentId, 1'u8, 0)
    check treb.pos == ivec2(10, 10)  # Cannot move with cooldown > 0
    echo &"  Trebuchet cannot move during transition (stayed at {treb.pos})"

suite "Behavior: Trebuchet Stats":
  test "trebuchet has correct HP":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)

    check treb.hp == TrebuchetMaxHp
    check treb.maxHp == TrebuchetMaxHp
    echo &"  Trebuchet HP: {treb.hp}/{treb.maxHp} (expected {TrebuchetMaxHp})"

  test "trebuchet has correct attack damage":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)

    check treb.attackDamage == TrebuchetAttackDamage
    echo &"  Trebuchet attack: {treb.attackDamage} (expected {TrebuchetAttackDamage})"

  test "trebuchet deals siege multiplied damage to building":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = false
    treb.cooldown = 0
    let wall = Thing(kind: Wall, pos: ivec2(10, 5), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)
    let startHp = wall.hp

    env.stepAction(treb.agentId, 2'u8, dirIndex(treb.pos, wall.pos))

    let expectedDamage = TrebuchetAttackDamage * SiegeStructureMultiplier
    check wall.hp == startHp - expectedDamage
    echo &"  Trebuchet dealt {expectedDamage} siege damage to wall (base {TrebuchetAttackDamage} x{SiegeStructureMultiplier})"

suite "Behavior: Mangonel AoE Damage":
  test "mangonel hits enemies along forward line":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    applyUnitClass(mangonel, UnitMangonel)
    # Place enemies in the forward line (north)
    let enemy1 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))      # 1 tile north
    let enemy2 = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(10, 8))  # 2 tiles north
    let enemy3 = addAgentAt(env, MapAgentsPerTeam + 2, ivec2(10, 7))  # 3 tiles north
    let hp1 = enemy1.hp
    let hp2 = enemy2.hp
    let hp3 = enemy3.hp

    env.stepAction(mangonel.agentId, 2'u8, dirIndex(mangonel.pos, enemy1.pos))

    check enemy1.hp < hp1
    check enemy2.hp < hp2
    check enemy3.hp < hp3
    echo &"  Mangonel hit 3 enemies in line: [{hp1}->{enemy1.hp}, {hp2}->{enemy2.hp}, {hp3}->{enemy3.hp}]"

  test "mangonel hits enemies on side prongs":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    applyUnitClass(mangonel, UnitMangonel)
    # Place enemies on the side prongs (1 tile left and right of forward line)
    # Forward line is north (delta: 0, -1), left is (-1, 0), right is (1, 0)
    let enemyLeft = addAgentAt(env, MapAgentsPerTeam, ivec2(9, 9))   # Left prong at step 1
    let enemyRight = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(11, 9))  # Right prong at step 1
    let hpL = enemyLeft.hp
    let hpR = enemyRight.hp

    env.stepAction(mangonel.agentId, 2'u8, 0)  # Attack north

    check enemyLeft.hp < hpL
    check enemyRight.hp < hpR
    echo &"  Mangonel hit side prongs: left {hpL}->{enemyLeft.hp}, right {hpR}->{enemyRight.hp}"

  test "mangonel AoE extends MangonelAoELength tiles forward":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    applyUnitClass(mangonel, UnitMangonel)
    # Place enemy at max AoE range (MangonelAoELength = 5 tiles north)
    let farEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 10 - MangonelAoELength.int32))
    let startHp = farEnemy.hp

    env.stepAction(mangonel.agentId, 2'u8, 0)  # Attack north

    check farEnemy.hp < startHp
    echo &"  Mangonel hit enemy at max AoE range ({MangonelAoELength} tiles)"

  test "mangonel deals siege multiplied damage to building":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    applyUnitClass(mangonel, UnitMangonel)
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)
    let startHp = wall.hp

    env.stepAction(mangonel.agentId, 2'u8, dirIndex(mangonel.pos, wall.pos))

    let expectedDamage = MangonelAttackDamage * SiegeStructureMultiplier
    check wall.hp == startHp - expectedDamage
    echo &"  Mangonel dealt {expectedDamage} siege damage to wall (base {MangonelAttackDamage} x{SiegeStructureMultiplier})"

suite "Behavior: Mangonel Stats":
  test "mangonel has correct HP":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    applyUnitClass(mangonel, UnitMangonel)

    check mangonel.hp == MangonelMaxHp
    check mangonel.maxHp == MangonelMaxHp
    echo &"  Mangonel HP: {mangonel.hp}/{mangonel.maxHp} (expected {MangonelMaxHp})"

  test "mangonel has correct attack damage":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    applyUnitClass(mangonel, UnitMangonel)

    check mangonel.attackDamage == MangonelAttackDamage
    echo &"  Mangonel attack: {mangonel.attackDamage} (expected {MangonelAttackDamage})"

suite "Behavior: Siege Unit Countering":
  test "melee units deal sustained damage to battering ram":
    let env = makeEmptyEnv()
    let knight = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight, stance = StanceAggressive)
    applyUnitClass(knight, UnitKnight)
    let ram = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11), unitClass = UnitBatteringRam, stance = StanceAggressive)
    applyUnitClass(ram, UnitBatteringRam)
    let ramStartHp = ram.hp

    # Knight attacks ram over multiple rounds
    var rounds = 0
    while ram.hp > 0 and rounds < 50:
      env.stepAction(knight.agentId, 2'u8, dirIndex(knight.pos, ram.pos))
      inc rounds

    # Knight should be able to kill the ram eventually
    check ram.hp <= 0
    echo &"  Knight killed ram in {rounds} hits (ram HP: {ramStartHp} -> {ram.hp})"

  test "man-at-arms can damage siege units":
    let env = makeEmptyEnv()
    let maa = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(maa, UnitManAtArms)
    let ram = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    let startHp = ram.hp

    env.stepAction(maa.agentId, 2'u8, dirIndex(maa.pos, ram.pos))

    check ram.hp < startHp
    echo &"  ManAtArms dealt {startHp - ram.hp} damage to ram"

  test "siege units default to defensive stance":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(ram, UnitBatteringRam)
    let mangonel = addAgentAt(env, 1, ivec2(12, 10))
    applyUnitClass(mangonel, UnitMangonel)
    let treb = addAgentAt(env, 2, ivec2(14, 10))
    applyUnitClass(treb, UnitTrebuchet)

    check ram.stance == StanceDefensive
    check mangonel.stance == StanceDefensive
    check treb.stance == StanceDefensive
    echo &"  All siege units default to defensive stance"

suite "Behavior: Siege vs Siege":
  test "mangonel AoE can damage multiple siege units":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    applyUnitClass(mangonel, UnitMangonel)
    # Enemy siege clustered together
    let enemyRam = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitBatteringRam)
    applyUnitClass(enemyRam, UnitBatteringRam)
    let enemyRam2 = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(9, 9), unitClass = UnitBatteringRam)
    applyUnitClass(enemyRam2, UnitBatteringRam)
    let hpR1 = enemyRam.hp
    let hpR2 = enemyRam2.hp

    env.stepAction(mangonel.agentId, 2'u8, dirIndex(mangonel.pos, enemyRam.pos))

    check enemyRam.hp < hpR1
    check enemyRam2.hp < hpR2
    echo &"  Mangonel AoE hit 2 siege units: [{hpR1}->{enemyRam.hp}, {hpR2}->{enemyRam2.hp}]"

  test "trebuchet outranges mangonel":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = false
    treb.cooldown = 0
    # Enemy mangonel at range 5 (beyond mangonel range 3, within trebuchet range 6)
    let enemyMangonel = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5), unitClass = UnitMangonel)
    applyUnitClass(enemyMangonel, UnitMangonel)
    let startHp = enemyMangonel.hp

    env.stepAction(treb.agentId, 2'u8, dirIndex(treb.pos, enemyMangonel.pos))

    check enemyMangonel.hp < startHp
    echo &"  Trebuchet (range {TrebuchetBaseRange}) hit mangonel at distance 5 (mangonel range {MangonelBaseRange})"
