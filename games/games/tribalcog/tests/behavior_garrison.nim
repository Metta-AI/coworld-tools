import std/[unittest, strformat]
import test_common
import agent_control

suite "Behavior: Garrison Entry":
  test "villager garrisons in TownCenter via USE action":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, tc.pos))

    check tc.garrisonedUnits.len == 1
    check villager.pos == ivec2(-1, -1)
    echo "  Villager garrisoned in TownCenter"

  test "unit garrisons in Castle via USE action":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let knight = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(knight, UnitManAtArms)

    env.stepAction(knight.agentId, 3'u8, dirIndex(knight.pos, castle.pos))

    check castle.garrisonedUnits.len == 1
    check knight.pos == ivec2(-1, -1)
    echo "  Knight garrisoned in Castle"

  test "unit garrisons in GuardTower via USE action":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 9), 0)
    let unit = addAgentAt(env, 0, ivec2(10, 10))

    env.stepAction(unit.agentId, 3'u8, dirIndex(unit.pos, tower.pos))

    check tower.garrisonedUnits.len == 1
    check unit.pos == ivec2(-1, -1)
    echo "  Unit garrisoned in GuardTower"

  test "multiple units garrison sequentially":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    for i in 0 ..< 5:
      let villager = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      discard env.garrisonUnitInBuilding(villager, tc)

    check tc.garrisonedUnits.len == 5
    for unit in tc.garrisonedUnits:
      check unit.pos == ivec2(-1, -1)
    echo &"  {tc.garrisonedUnits.len} units garrisoned in TownCenter"

suite "Behavior: Garrisoned Units Fire Arrows":
  test "garrisoned units in GuardTower increase arrow damage":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)

    # First measure base tower damage with no garrison
    let enemyBase = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 13), unitClass = UnitBatteringRam)
    applyUnitClass(enemyBase, UnitBatteringRam)
    let startHpBase = enemyBase.hp
    env.stepAction(enemyBase.agentId, 0'u8, 0)
    let baseDamage = startHpBase - enemyBase.hp

    # Now garrison 3 units and measure damage
    let env2 = makeEmptyEnv()
    let tower2 = addBuilding(env2, GuardTower, ivec2(10, 10), 0)
    for i in 0 ..< 3:
      let villager = addAgentAt(env2, i, ivec2(10 + i.int32, 11))
      discard env2.garrisonUnitInBuilding(villager, tower2)

    let enemyGarr = addAgentAt(env2, MapAgentsPerTeam + 3, ivec2(10, 13), unitClass = UnitBatteringRam)
    applyUnitClass(enemyGarr, UnitBatteringRam)
    let startHpGarr = enemyGarr.hp
    env2.stepAction(enemyGarr.agentId, 0'u8, 0)
    let garrisonDamage = startHpGarr - enemyGarr.hp

    check garrisonDamage > baseDamage
    echo &"  Tower damage: base={baseDamage}, with 3 garrisoned={garrisonDamage}"

  test "garrisoned units in TownCenter add bonus arrows":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    for i in 0 ..< 5:
      let villager = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      discard env.garrisonUnitInBuilding(villager, tc)

    let enemyId = MapAgentsPerTeam + 5
    let enemy = addAgentAt(env, enemyId, ivec2(10, 14), unitClass = UnitBatteringRam)
    applyUnitClass(enemy, UnitBatteringRam)
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)

    let damageDealt = startHp - enemy.hp
    check damageDealt > 0
    echo &"  TC with 5 garrisoned dealt {damageDealt} damage"

  test "garrisoned tower deals increasing damage per step":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    for i in 0 ..< 3:
      let villager = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      discard env.garrisonUnitInBuilding(villager, tower)

    let enemyId = MapAgentsPerTeam + 3
    let enemy = addAgentAt(env, enemyId, ivec2(10, 13), unitClass = UnitBatteringRam)
    applyUnitClass(enemy, UnitBatteringRam)  # High HP to survive multiple hits
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)

    let damageAfterOne = startHp - enemy.hp
    check damageAfterOne > 0
    echo &"  Garrisoned tower dealt {damageAfterOne} damage in 1 step (enemy started at {startHp} HP)"

suite "Behavior: Eject on Building Destruction":
  test "units eject when TownCenter is destroyed":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    var garrisoned: seq[Thing] = @[]
    for i in 0 ..< 3:
      let unit = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      discard env.garrisonUnitInBuilding(unit, tc)
      garrisoned.add(unit)

    check tc.garrisonedUnits.len == 3
    for unit in garrisoned:
      check unit.pos == ivec2(-1, -1)

    # Destroy the TC
    discard env.applyStructureDamage(tc, TownCenterMaxHp + 10)

    # All units should be ejected and alive
    for unit in garrisoned:
      check unit.pos != ivec2(-1, -1)
      check isValidPos(unit.pos)
      check unit.hp > 0
    echo &"  3 units ejected from destroyed TownCenter"

  test "units eject when Castle is destroyed":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 10), 0)
    var garrisoned: seq[Thing] = @[]
    for i in 0 ..< 5:
      let unit = addAgentAt(env, i, ivec2(5 + i.int32, 5), unitClass = UnitManAtArms)
      discard env.garrisonUnitInBuilding(unit, castle)
      garrisoned.add(unit)

    check castle.garrisonedUnits.len == 5

    discard env.applyStructureDamage(castle, CastleMaxHp + 10)

    var ejectedCount = 0
    for unit in garrisoned:
      if unit.pos != ivec2(-1, -1) and unit.hp > 0:
        inc ejectedCount
    check ejectedCount == 5
    echo &"  {ejectedCount} units ejected from destroyed Castle"

  test "units eject when GuardTower is destroyed":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let unit = addAgentAt(env, 0, ivec2(11, 11))
    discard env.garrisonUnitInBuilding(unit, tower)

    check unit.pos == ivec2(-1, -1)

    discard env.applyStructureDamage(tower, GuardTowerMaxHp + 10)

    check unit.pos != ivec2(-1, -1)
    check isValidPos(unit.pos)
    check unit.hp > 0
    echo "  Unit ejected from destroyed GuardTower"

  test "ejected units retain their inventory":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let unit = addAgentAt(env, 0, ivec2(11, 11))
    setInv(unit, ItemWood, 5)
    setInv(unit, ItemGold, 3)
    discard env.garrisonUnitInBuilding(unit, tc)

    discard env.applyStructureDamage(tc, TownCenterMaxHp + 10)

    check unit.pos != ivec2(-1, -1)
    check getInv(unit, ItemWood) == 5
    check getInv(unit, ItemGold) == 3
    echo "  Ejected unit retained wood=5 gold=3"

suite "Behavior: Garrison Capacity Limits":
  test "TownCenter enforces capacity of 15":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    for i in 0 ..< TownCenterGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(5 + (i mod 10).int32, 5 + (i div 10).int32))
      check env.garrisonUnitInBuilding(unit, tc) == true

    check tc.garrisonedUnits.len == TownCenterGarrisonCapacity

    let overflow = addAgentAt(env, TownCenterGarrisonCapacity, ivec2(20, 20))
    check env.garrisonUnitInBuilding(overflow, tc) == false
    check tc.garrisonedUnits.len == TownCenterGarrisonCapacity
    echo &"  TownCenter full at {TownCenterGarrisonCapacity}, rejected overflow"

  test "Castle enforces capacity of 20":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 10), 0)
    for i in 0 ..< CastleGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(5 + (i mod 10).int32, 5 + (i div 10).int32),
                            unitClass = UnitManAtArms)
      check env.garrisonUnitInBuilding(unit, castle) == true

    check castle.garrisonedUnits.len == CastleGarrisonCapacity

    let overflow = addAgentAt(env, CastleGarrisonCapacity, ivec2(20, 20),
                              unitClass = UnitManAtArms)
    check env.garrisonUnitInBuilding(overflow, castle) == false
    echo &"  Castle full at {CastleGarrisonCapacity}, rejected overflow"

  test "GuardTower enforces capacity of 5":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    for i in 0 ..< GuardTowerGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      check env.garrisonUnitInBuilding(unit, tower) == true

    check tower.garrisonedUnits.len == GuardTowerGarrisonCapacity

    let overflow = addAgentAt(env, GuardTowerGarrisonCapacity, ivec2(20, 20))
    check env.garrisonUnitInBuilding(overflow, tower) == false
    echo &"  GuardTower full at {GuardTowerGarrisonCapacity}, rejected overflow"

  test "enemy unit cannot garrison in opponent building":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))

    check env.garrisonUnitInBuilding(enemy, tc) == false
    check tc.garrisonedUnits.len == 0
    echo "  Enemy rejected from garrisoning"

suite "Behavior: Garrison Healing":
  test "garrisoned units preserve HP while inside":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let unit = addAgentAt(env, 0, ivec2(11, 11))
    unit.hp = 3
    let hpBefore = unit.hp
    discard env.garrisonUnitInBuilding(unit, tc)

    # Step a few times - garrisoned unit HP should not decrease
    for _ in 0 ..< 10:
      env.stepNoop()

    check unit.hp >= hpBefore
    echo &"  Garrisoned unit HP preserved: {hpBefore} -> {unit.hp}"

  test "damaged unit survives inside garrison while building stands":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let unit = addAgentAt(env, 0, ivec2(11, 11))
    unit.hp = 1  # Critically low HP
    discard env.garrisonUnitInBuilding(unit, tc)

    # Step several times with no threats - unit should stay alive inside
    for _ in 0 ..< 10:
      env.stepNoop()

    check unit.hp >= 1
    check unit.pos == ivec2(-1, -1)
    check tc.garrisonedUnits.len == 1
    echo &"  Damaged unit survived 10 steps in garrison, HP={unit.hp}"

suite "Behavior: Garrison Attack":
  test "garrisoned units in tower attack enemies in range":
    # Setup: tower with garrisoned units, enemy in range
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    for i in 0 ..< 3:
      let villager = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      discard env.garrisonUnitInBuilding(villager, tower)
    check tower.garrisonedUnits.len == 3

    # Place enemy in tower range
    let enemyId = MapAgentsPerTeam + 3
    let enemy = addAgentAt(env, enemyId, ivec2(10, 13), unitClass = UnitBatteringRam)
    applyUnitClass(enemy, UnitBatteringRam)
    let startHp = enemy.hp

    # Step - tower should attack with garrisoned units
    env.stepAction(enemyId, 0'u8, 0)

    check enemy.hp < startHp
    echo &"  Garrisoned tower attacked enemy, HP: {startHp} -> {enemy.hp}"

  test "garrison attack damage includes building bonus arrows":
    # Compare damage with and without garrison
    # Empty tower: 1 arrow * 2 damage = 2 damage per step
    # Tower with 3 units: 4 arrows * 2 damage = 8 damage per step
    let envEmpty = makeEmptyEnv()
    let towerEmpty = addBuilding(envEmpty, GuardTower, ivec2(10, 10), 0)
    let enemyEmpty = addAgentAt(envEmpty, MapAgentsPerTeam, ivec2(10, 13), unitClass = UnitBatteringRam)
    applyUnitClass(enemyEmpty, UnitBatteringRam)
    let startHpEmpty = enemyEmpty.hp
    envEmpty.stepAction(enemyEmpty.agentId, 0'u8, 0)
    let baseDamage = startHpEmpty - enemyEmpty.hp

    let envGarr = makeEmptyEnv()
    let towerGarr = addBuilding(envGarr, GuardTower, ivec2(10, 10), 0)
    for i in 0 ..< 3:
      let villager = addAgentAt(envGarr, i, ivec2(10 + i.int32, 11))
      discard envGarr.garrisonUnitInBuilding(villager, towerGarr)
    let enemyGarr = addAgentAt(envGarr, MapAgentsPerTeam + 3, ivec2(10, 13), unitClass = UnitBatteringRam)
    applyUnitClass(enemyGarr, UnitBatteringRam)
    let startHpGarr = enemyGarr.hp
    envGarr.stepAction(enemyGarr.agentId, 0'u8, 0)
    let garrisonDamage = startHpGarr - enemyGarr.hp

    # With 3 garrisoned units: 4x damage (base + 3 bonus arrows)
    check garrisonDamage > baseDamage
    check garrisonDamage == baseDamage * 4  # 1 base + 3 bonus = 4x
    echo &"  Base damage: {baseDamage}, Garrison damage: {garrisonDamage} (4x with 3 units)"

  test "units stop contributing to attack when ungarrisoned":
    # Compare damage before and after ungarrisoning using two separate environments
    # to avoid position conflicts when units are ejected

    # Environment 1: Tower with garrison
    let envGarr = makeEmptyEnv()
    let towerGarr = addBuilding(envGarr, GuardTower, ivec2(10, 10), 0)
    for i in 0 ..< 3:
      let villager = addAgentAt(envGarr, i, ivec2(10 + i.int32, 11))
      discard envGarr.garrisonUnitInBuilding(villager, towerGarr)
    let enemyGarr = addAgentAt(envGarr, MapAgentsPerTeam + 3, ivec2(10, 13), unitClass = UnitBatteringRam)
    applyUnitClass(enemyGarr, UnitBatteringRam)
    let startHpGarr = enemyGarr.hp
    envGarr.stepAction(enemyGarr.agentId, 0'u8, 0)
    let damageWithGarrison = startHpGarr - enemyGarr.hp

    # Environment 2: Tower with garrison, then ungarrison
    let envUngarr = makeEmptyEnv()
    let towerUngarr = addBuilding(envUngarr, GuardTower, ivec2(10, 10), 0)
    for i in 0 ..< 3:
      let villager = addAgentAt(envUngarr, i, ivec2(10 + i.int32, 11))
      discard envUngarr.garrisonUnitInBuilding(villager, towerUngarr)
    # Ungarrison before adding enemy
    discard envUngarr.ungarrisonAllUnits(towerUngarr)
    check towerUngarr.garrisonedUnits.len == 0
    # Place enemy at a position guaranteed not to conflict with ejected units
    let enemyUngarr = addAgentAt(envUngarr, MapAgentsPerTeam + 3, ivec2(10, 14), unitClass = UnitBatteringRam)
    applyUnitClass(enemyUngarr, UnitBatteringRam)
    let startHpUngarr = enemyUngarr.hp
    envUngarr.stepAction(enemyUngarr.agentId, 0'u8, 0)
    let damageAfterUngarrison = startHpUngarr - enemyUngarr.hp

    # After ungarrisoning, damage should return to base (no bonus arrows)
    check damageAfterUngarrison < damageWithGarrison
    check damageAfterUngarrison == damageWithGarrison div 4  # Back to 1x
    echo &"  With garrison: {damageWithGarrison}, After ungarrison: {damageAfterUngarrison}"

  test "castle garrison attack fires at enemies in range":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 10), 0)
    for i in 0 ..< 5:
      let knight = addAgentAt(env, i, ivec2(5 + i.int32, 5), unitClass = UnitManAtArms)
      discard env.garrisonUnitInBuilding(knight, castle)
    check castle.garrisonedUnits.len == 5

    # Castle range is 6, so place enemy within range (distance 6 from castle center)
    let enemyId = MapAgentsPerTeam + 5
    let enemy = addAgentAt(env, enemyId, ivec2(10, 16), unitClass = UnitBatteringRam)
    applyUnitClass(enemy, UnitBatteringRam)
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)

    check enemy.hp < startHp
    echo &"  Castle with 5 garrisoned attacked enemy, HP: {startHp} -> {enemy.hp}"

  test "town center garrison attack fires at enemies in range":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    for i in 0 ..< 5:
      let villager = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      discard env.garrisonUnitInBuilding(villager, tc)
    check tc.garrisonedUnits.len == 5

    let enemyId = MapAgentsPerTeam + 5
    let enemy = addAgentAt(env, enemyId, ivec2(10, 14), unitClass = UnitBatteringRam)
    applyUnitClass(enemy, UnitBatteringRam)
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)

    check enemy.hp < startHp
    echo &"  TC with 5 garrisoned attacked enemy, HP: {startHp} -> {enemy.hp}"

suite "Behavior: isGarrisoned Flag":
  test "isGarrisoned is set when unit enters building":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let villager = addAgentAt(env, 0, ivec2(11, 11))

    check villager.isGarrisoned == false
    discard env.garrisonUnitInBuilding(villager, tc)

    check villager.isGarrisoned == true
    check villager.pos == ivec2(-1, -1)
    echo "  isGarrisoned=true after garrison entry"

  test "isGarrisoned is cleared when units ungarrison":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let villager = addAgentAt(env, 0, ivec2(11, 11))
    discard env.garrisonUnitInBuilding(villager, tc)

    check villager.isGarrisoned == true

    let ejected = env.ungarrisonAllUnits(tc)

    check ejected.len == 1
    check villager.isGarrisoned == false
    check villager.pos != ivec2(-1, -1)
    echo "  isGarrisoned=false after ungarrison"

  test "isGarrisoned is cleared when building is destroyed":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let villager = addAgentAt(env, 0, ivec2(11, 11))
    discard env.garrisonUnitInBuilding(villager, tc)

    check villager.isGarrisoned == true

    discard env.applyStructureDamage(tc, TownCenterMaxHp + 10)

    check villager.isGarrisoned == false
    echo "  isGarrisoned=false after building destruction"

suite "Behavior: AI Garrison Under Threat":
  test "villager garrisons in TC when threatened by nearby enemy":
    # Test that garrisonUnitInBuilding works via the USE action path
    # simulating what the AI garrison option produces
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let villager = addAgentAt(env, 0, ivec2(11, 10))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(13, 10), unitClass = UnitManAtArms)
    applyUnitClass(enemy, UnitManAtArms)

    # The AI garrison option would issue: actOrMove toward building with verb 3
    # Simulate: villager is adjacent to TC, issue USE on TC
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, tc.pos))

    check tc.garrisonedUnits.len == 1
    check villager.isGarrisoned == true
    check villager.pos == ivec2(-1, -1)
    echo "  Villager garrisoned in TC when enemy nearby"

  test "garrisoned villager is protected from direct targeting":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let villager = addAgentAt(env, 0, ivec2(11, 10))
    let hpBefore = villager.hp
    discard env.garrisonUnitInBuilding(villager, tc)

    # Garrisoned unit should be off-grid and untargetable
    check villager.pos == ivec2(-1, -1)
    check villager.isGarrisoned == true

    # After multiple steps, garrisoned villager retains full HP
    for _ in 0 ..< 5:
      env.stepNoop()

    check villager.hp == hpBefore
    check villager.isGarrisoned == true
    echo "  Garrisoned villager HP preserved at {hpBefore}"

  test "garrisoned villager contributes arrows to TC defense":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    for i in 0 ..< 5:
      let villager = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      discard env.garrisonUnitInBuilding(villager, tc)

    let enemyId = MapAgentsPerTeam + 5
    let enemy = addAgentAt(env, enemyId, ivec2(10, 14), unitClass = UnitBatteringRam)
    applyUnitClass(enemy, UnitBatteringRam)
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)

    let damage = startHp - enemy.hp
    # 5 garrisoned villagers should add 5 bonus arrows plus 1 base = 12 damage
    check damage > 2  # More than base tower damage
    echo &"  Garrisoned TC with 5 villagers dealt {damage} damage to attacker"
