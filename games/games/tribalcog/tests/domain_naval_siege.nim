import std/[unittest, strformat]
import test_common

## Domain tests for Phase 6: Naval & Advanced Military
## Verifies:
## - Water combat tests pass (Galley, Fire Ship)
## - Research tree works correctly (University)
## - Siege damage calculations correct (Scorpion)

suite "Naval Combat: Galley":
  test "galley has correct HP":
    let env = makeEmptyEnv()
    let galley = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(galley, UnitGalley)

    check galley.hp == GalleyMaxHp
    check galley.maxHp == GalleyMaxHp
    echo &"  Galley HP: {galley.hp}/{galley.maxHp} (expected {GalleyMaxHp})"

  test "galley has correct attack damage":
    let env = makeEmptyEnv()
    let galley = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(galley, UnitGalley)

    check galley.attackDamage == GalleyAttackDamage
    echo &"  Galley attack: {galley.attackDamage} (expected {GalleyAttackDamage})"

  test "galley is a water unit":
    let env = makeEmptyEnv()
    let galley = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(galley, UnitGalley)

    check galley.isWaterUnit
    echo &"  Galley is water unit: {galley.isWaterUnit}"

  test "galley attacks at range":
    let env = makeEmptyEnv()
    let galley = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(galley, UnitGalley)
    # Enemy within galley range
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 7))
    let startHp = enemy.hp

    env.stepAction(galley.agentId, 2'u8, dirIndex(galley.pos, enemy.pos))

    check enemy.hp < startHp
    echo &"  Galley hit at range 3 (HP: {startHp} -> {enemy.hp})"

  test "galley benefits from ballistics tech":
    let env = makeEmptyEnv()
    let galley = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(galley, UnitGalley)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    enemy.hp = 10
    enemy.maxHp = 10

    # Attack without Ballistics
    env.stepAction(galley.agentId, 2'u8, dirIndex(galley.pos, enemy.pos))
    let damageWithout = 10 - enemy.hp

    # Reset enemy HP
    enemy.hp = 10
    # Enable Ballistics
    env.teamUniversityTechs[0].researched[TechBallistics] = true
    env.stepAction(galley.agentId, 2'u8, dirIndex(galley.pos, enemy.pos))
    let damageWith = 10 - enemy.hp

    check damageWith == damageWithout + 1
    echo &"  Galley damage without ballistics: {damageWithout}, with: {damageWith}"

suite "Naval Combat: Fire Ship":
  test "fire ship has correct HP":
    let env = makeEmptyEnv()
    let fireShip = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(fireShip, UnitFireShip)

    check fireShip.hp == FireShipMaxHp
    check fireShip.maxHp == FireShipMaxHp
    echo &"  Fire Ship HP: {fireShip.hp}/{fireShip.maxHp} (expected {FireShipMaxHp})"

  test "fire ship has correct attack damage":
    let env = makeEmptyEnv()
    let fireShip = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(fireShip, UnitFireShip)

    check fireShip.attackDamage == FireShipAttackDamage
    echo &"  Fire Ship attack: {fireShip.attackDamage} (expected {FireShipAttackDamage})"

  test "fire ship is a water unit":
    let env = makeEmptyEnv()
    let fireShip = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(fireShip, UnitFireShip)

    check fireShip.isWaterUnit
    echo &"  Fire Ship is water unit: {fireShip.isWaterUnit}"

  test "fire ship deals bonus damage to water units":
    let env = makeEmptyEnv()
    let fireShip = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(fireShip, UnitFireShip)
    # Target a galley (water unit)
    let galley = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    applyUnitClass(galley, UnitGalley)
    let startHp = galley.hp

    env.stepAction(fireShip.agentId, 2'u8, dirIndex(fireShip.pos, galley.pos))

    # Fire ship base damage (3) + bonus vs water (2) = 5
    let expectedDamage = FireShipAttackDamage + 2  # bonus vs water units
    let actualDamage = startHp - galley.hp
    check actualDamage == expectedDamage
    echo &"  Fire Ship dealt {actualDamage} to Galley (base {FireShipAttackDamage} + 2 bonus)"

  test "fire ship deals bonus damage to trade cog":
    let env = makeEmptyEnv()
    let fireShip = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(fireShip, UnitFireShip)
    let tradeCog = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    applyUnitClass(tradeCog, UnitTradeCog)
    let startHp = tradeCog.hp

    env.stepAction(fireShip.agentId, 2'u8, dirIndex(fireShip.pos, tradeCog.pos))

    let expectedDamage = FireShipAttackDamage + 2  # bonus vs water units
    let actualDamage = startHp - tradeCog.hp
    check actualDamage == expectedDamage
    echo &"  Fire Ship dealt {actualDamage} to Trade Cog (base {FireShipAttackDamage} + 2 bonus)"

suite "Siege: Scorpion":
  test "scorpion has correct HP":
    let env = makeEmptyEnv()
    let scorpion = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(scorpion, UnitScorpion)

    check scorpion.hp == ScorpionMaxHp
    check scorpion.maxHp == ScorpionMaxHp
    echo &"  Scorpion HP: {scorpion.hp}/{scorpion.maxHp} (expected {ScorpionMaxHp})"

  test "scorpion has correct attack damage":
    let env = makeEmptyEnv()
    let scorpion = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(scorpion, UnitScorpion)

    check scorpion.attackDamage == ScorpionAttackDamage
    echo &"  Scorpion attack: {scorpion.attackDamage} (expected {ScorpionAttackDamage})"

  test "scorpion attacks at range 4":
    let env = makeEmptyEnv()
    let scorpion = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(scorpion, UnitScorpion)
    # Enemy at range 4
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 6))
    let startHp = enemy.hp

    env.stepAction(scorpion.agentId, 2'u8, dirIndex(scorpion.pos, enemy.pos))

    check enemy.hp < startHp
    echo &"  Scorpion hit at range 4 (HP: {startHp} -> {enemy.hp})"

  test "scorpion deals bonus damage to infantry":
    let env = makeEmptyEnv()
    let scorpion = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(scorpion, UnitScorpion)
    # Use a Woad Raider (infantry without shield aura) to test bonus damage cleanly
    let woad = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    applyUnitClass(woad, UnitWoadRaider)
    let startHp = woad.hp

    env.stepAction(scorpion.agentId, 2'u8, dirIndex(scorpion.pos, woad.pos))

    # Scorpion base damage (2) + bonus vs infantry (2) = 4
    let expectedDamage = ScorpionAttackDamage + 2  # bonus vs infantry
    let actualDamage = startHp - woad.hp
    check actualDamage == expectedDamage
    echo &"  Scorpion dealt {actualDamage} to Woad Raider (base {ScorpionAttackDamage} + 2 bonus)"

  test "scorpion deals bonus damage to champion":
    let env = makeEmptyEnv()
    let scorpion = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(scorpion, UnitScorpion)
    let champion = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    applyUnitClass(champion, UnitChampion)
    let startHp = champion.hp

    env.stepAction(scorpion.agentId, 2'u8, dirIndex(scorpion.pos, champion.pos))

    # Scorpion base damage (2) + bonus vs infantry (2) = 4
    let expectedDamage = ScorpionAttackDamage + 2
    let actualDamage = startHp - champion.hp
    check actualDamage == expectedDamage
    echo &"  Scorpion dealt {actualDamage} to Champion (base {ScorpionAttackDamage} + 2 bonus)"

  test "scorpion benefits from siege engineers for building damage":
    let env = makeEmptyEnv()
    let scorpion = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(scorpion, UnitScorpion)
    # Build a wall - scorpion is NOT a siege unit so doesn't get bonus
    let wall = Thing(kind: Wall, pos: ivec2(10, 8), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)
    let startHp = wall.hp

    env.stepAction(scorpion.agentId, 2'u8, dirIndex(scorpion.pos, wall.pos))

    # Scorpion deals normal damage to buildings (no siege multiplier)
    let actualDamage = startHp - wall.hp
    check actualDamage == ScorpionAttackDamage
    echo &"  Scorpion dealt {actualDamage} to wall (no siege bonus - anti-infantry focus)"

  test "scorpion benefits from ballistics tech":
    let env = makeEmptyEnv()
    let scorpion = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(scorpion, UnitScorpion)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    enemy.hp = 10
    enemy.maxHp = 10

    # Attack without Ballistics
    env.stepAction(scorpion.agentId, 2'u8, dirIndex(scorpion.pos, enemy.pos))
    let damageWithout = 10 - enemy.hp

    # Reset enemy HP
    enemy.hp = 10
    # Enable Ballistics
    env.teamUniversityTechs[0].researched[TechBallistics] = true
    env.stepAction(scorpion.agentId, 2'u8, dirIndex(scorpion.pos, enemy.pos))
    let damageWith = 10 - enemy.hp

    check damageWith == damageWithout + 1
    echo &"  Scorpion damage without ballistics: {damageWithout}, with: {damageWith}"

suite "Research Tree Verification":
  test "university techs are independent per team":
    let env = makeEmptyEnv()
    env.teamUniversityTechs[0].researched[TechBallistics] = true
    env.teamUniversityTechs[1].researched[TechSiegeEngineers] = true

    check env.hasUniversityTech(0, TechBallistics)
    check not env.hasUniversityTech(0, TechSiegeEngineers)
    check not env.hasUniversityTech(1, TechBallistics)
    check env.hasUniversityTech(1, TechSiegeEngineers)
    echo "  University techs are independent per team"

  test "heated shot increases damage vs ships":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    tower.hp = tower.maxHp
    let galley = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    applyUnitClass(galley, UnitGalley)
    galley.hp = 20
    galley.maxHp = 20

    # Attack without Heated Shot
    env.stepNoop()
    let damageWithout = 20 - galley.hp

    # Reset galley HP
    galley.hp = 20
    # Enable Heated Shot
    env.teamUniversityTechs[0].researched[TechHeatedShot] = true
    env.stepNoop()
    let damageWith = 20 - galley.hp

    check damageWith == damageWithout + 2
    echo &"  Tower damage to galley: without heated shot {damageWithout}, with: {damageWith}"

suite "Siege Damage Calculations":
  test "siege multiplier applies correctly to all siege units":
    let env = makeEmptyEnv()
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)

    # Test battering ram
    let ram = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(ram, UnitBatteringRam)
    let wallHpBefore = wall.hp
    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))
    let ramDamage = wallHpBefore - wall.hp

    check ramDamage == BatteringRamAttackDamage * SiegeStructureMultiplier
    echo &"  Ram dealt {ramDamage} (expected {BatteringRamAttackDamage * SiegeStructureMultiplier})"

  test "siege engineers bonus applies to siege units":
    let env = makeEmptyEnv()
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)
    wall.hp = 100
    wall.maxHp = 100
    env.add(wall)

    let ram = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(ram, UnitBatteringRam)

    # Attack without Siege Engineers
    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))
    let damageWithout = 100 - wall.hp

    # Reset wall
    wall.hp = 100
    # Enable Siege Engineers
    env.teamUniversityTechs[0].researched[TechSiegeEngineers] = true
    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))
    let damageWith = 100 - wall.hp

    check damageWith > damageWithout
    echo &"  Ram damage without siege engineers: {damageWithout}, with: {damageWith}"
