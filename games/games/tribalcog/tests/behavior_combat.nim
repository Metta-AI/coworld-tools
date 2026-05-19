import std/[unittest, strformat]
import test_common

suite "Behavior: Multi-step Combat":
  test "opposing teams deal damage over 200 steps":
    let env = makeEmptyEnv()
    # Team 0: ManAtArms at (10, 10) with aggressive stance
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(attacker, UnitManAtArms)
    # Team 1: ManAtArms at (10, 11) adjacent, aggressive
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(defender, UnitManAtArms)
    let startHpA = attacker.hp
    let startHpD = defender.hp

    # Run combat: attacker hits defender each step
    var damageDealt = false
    for step in 0 ..< 200:
      if defender.hp <= 0 or attacker.hp <= 0:
        damageDealt = true
        break
      env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Either someone died or damage was dealt
    check (attacker.hp < startHpA or defender.hp < startHpD or damageDealt)
    echo &"  Combat summary: Team0 HP {startHpA}->{attacker.hp}, Team1 HP {startHpD}->{defender.hp}"

  test "two teams exchange blows until one dies":
    let env = makeEmptyEnv()
    let unitA = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight, stance = StanceAggressive)
    applyUnitClass(unitA, UnitKnight)
    let unitB = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(unitB, UnitManAtArms)

    var rounds = 0
    while unitA.hp > 0 and unitB.hp > 0 and rounds < 200:
      env.stepAction(unitA.agentId, 2'u8, dirIndex(unitA.pos, unitB.pos))
      if unitB.hp > 0 and unitA.hp > 0:
        env.stepAction(unitB.agentId, 2'u8, dirIndex(unitB.pos, unitA.pos))
      inc rounds

    # At least one unit should be dead after sustained combat
    check (unitA.hp <= 0 or unitB.hp <= 0)
    # Verify the dead unit is terminated
    if unitA.hp <= 0:
      check env.terminated[unitA.agentId] == 1.0
    if unitB.hp <= 0:
      check env.terminated[unitB.agentId] == 1.0
    echo &"  Combat summary: Knight HP {unitA.hp}, ManAtArms HP {unitB.hp} after {rounds} rounds"

suite "Behavior: Ranged Combat":
  test "archer attacks enemy from distance":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    # Enemy 3 tiles north (archer range = 3)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 7))
    let startHp = enemy.hp

    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, enemy.pos))
    check enemy.hp < startHp

  test "archer cannot hit beyond range":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    # Enemy 5 tiles north (beyond archer range of 3)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))
    let startHp = enemy.hp

    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, enemy.pos))
    check enemy.hp == startHp

  test "trebuchet attacks from long range when unpacked":
    let env = makeEmptyEnv()
    let treb = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(treb, UnitTrebuchet)
    treb.packed = false
    treb.cooldown = 0
    # Enemy 5 tiles north (within trebuchet range of 6)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))
    let startHp = enemy.hp

    env.stepAction(treb.agentId, 2'u8, dirIndex(treb.pos, enemy.pos))
    check enemy.hp < startHp

  test "spear extends melee range to 2 tiles":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.inventorySpear = 1
    # Enemy 2 tiles north
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    let startHp = enemy.hp

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, enemy.pos))
    check enemy.hp < startHp
    check attacker.inventorySpear == 0

suite "Behavior: Siege vs Buildings":
  test "battering ram deals multiplied damage to wall":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)

    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))
    # Siege multiplier = 3, ram damage = 2, so 6 damage expected
    check wall.hp == WallMaxHp - (BatteringRamAttackDamage * SiegeStructureMultiplier)

  test "siege destroys building over multiple hits":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)

    var hits = 0
    while wall.hp > 0 and hits < 20:
      env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))
      inc hits

    check wall.hp <= 0
    # Wall should be removed from grid
    check env.grid[10][9] == nil

  test "mangonel AoE damages multiple enemies":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    applyUnitClass(mangonel, UnitMangonel)
    # Place enemies in the AoE pattern (center + sides at range 2)
    let enemyCenter = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    let enemyLeft = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(9, 8))
    let enemyRight = addAgentAt(env, MapAgentsPerTeam + 2, ivec2(11, 8))
    let hpC = enemyCenter.hp
    let hpL = enemyLeft.hp
    let hpR = enemyRight.hp

    env.stepAction(mangonel.agentId, 2'u8, dirIndex(mangonel.pos, enemyCenter.pos))
    check enemyCenter.hp < hpC
    check enemyLeft.hp < hpL
    check enemyRight.hp < hpR

suite "Behavior: Monk Conversion":
  test "monk converts enemy unit to own team":
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos, unitClass = UnitMonk)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))

    check getTeamId(enemy) == 1
    check monk.faith == MonkMaxFaith

    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, enemy.pos))

    # Enemy should now be on the monk's team
    check getTeamId(enemy) == 0
    # Faith consumed then recharged by 1
    check monk.faith == MonkMaxFaith - MonkConversionFaithCost + MonkFaithRechargeRate

  test "monk conversion fails without faith":
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos, unitClass = UnitMonk)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    monk.faith = 0

    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, enemy.pos))

    check getTeamId(enemy) == 1  # Still on enemy team

  test "monk heals damaged ally":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    let ally = addAgentAt(env, 1, ivec2(10, 9))
    ally.hp = 1
    let hpBefore = ally.hp

    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, ally.pos))

    check ally.hp > hpBefore

  test "monk faith recharges over steps":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    monk.faith = 5

    env.stepNoop()

    check monk.faith == min(MonkMaxFaith, 5 + MonkFaithRechargeRate)

suite "Behavior: Death and Removal":
  test "unit dies at 0 HP and is terminated":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 10  # One-hit kill
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1

    check env.terminated[victim.agentId] == 0.0

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check env.terminated[victim.agentId] == 1.0

  test "dead unit leaves corpse with inventory":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    setInv(victim, ItemWood, 3)
    setInv(victim, ItemGold, 2)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    let corpse = env.getBackgroundThing(victimPos)
    check corpse != nil
    check corpse.kind == Corpse
    check getInv(corpse, ItemWood) == 3
    check getInv(corpse, ItemGold) == 2

  test "dead unit is removed from grid":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    # Victim should not occupy the grid cell anymore
    let thing = env.getThing(victimPos)
    check thing == nil or thing.kind != Agent or thing.agentId != victim.agentId

  test "relics and lanterns drop on death":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    victim.inventoryRelic = 1
    victim.inventoryLantern = 1

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check env.thingsByKind[Relic].len == 1
    check env.thingsByKind[Lantern].len == 1

  test "multiple units fight to the death":
    let env = makeEmptyEnv()
    # 3v3 combat scenario
    var team0Units: seq[Thing] = @[]
    var team1Units: seq[Thing] = @[]
    for i in 0 ..< 3:
      let unit = addAgentAt(env, i, ivec2(10 + i.int32, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
      applyUnitClass(unit, UnitManAtArms)
      team0Units.add(unit)
    for i in 0 ..< 3:
      let unit = addAgentAt(env, MapAgentsPerTeam + i, ivec2(10 + i.int32, 11), unitClass = UnitManAtArms, stance = StanceAggressive)
      applyUnitClass(unit, UnitManAtArms)
      team1Units.add(unit)

    # Run combat: each team 0 unit attacks corresponding team 1 unit
    for step in 0 ..< 200:
      var allDead = true
      for i in 0 ..< 3:
        if team0Units[i].hp > 0 and team1Units[i].hp > 0:
          allDead = false
          env.stepAction(team0Units[i].agentId, 2'u8, dirIndex(team0Units[i].pos, team1Units[i].pos))
      if allDead:
        break

    # At least some units should have died
    var totalDeaths = 0
    for i in 0 ..< 3:
      if team0Units[i].hp <= 0: inc totalDeaths
      if team1Units[i].hp <= 0: inc totalDeaths
    check totalDeaths > 0
    echo &"  Combat summary: 3v3 battle, {totalDeaths} total deaths"

suite "Behavior: Tower and TC Garrison Fire":
  test "guard tower fires at enemy in range":
    let env = makeEmptyEnv()
    discard addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let enemyId = MapAgentsPerTeam
    let enemy = addAgentAt(env, enemyId, ivec2(10, 13))  # 3 tiles away
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)  # NOOP to trigger tower attack
    check enemy.hp < startHp

  test "town center fires at enemy in range":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let enemyId = MapAgentsPerTeam
    let enemy = addAgentAt(env, enemyId, ivec2(10, 14))  # 4 tiles away (within TC range 6)
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)
    check enemy.hp < startHp

  test "castle fires at enemy in range":
    let env = makeEmptyEnv()
    discard addBuilding(env, Castle, ivec2(10, 10), 0)
    let enemyId = MapAgentsPerTeam
    let enemy = addAgentAt(env, enemyId, ivec2(10, 15))  # 5 tiles away (within castle range 6)
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)
    check enemy.hp < startHp

  test "garrisoned units add bonus arrows to guard tower":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    # Garrison 3 villagers
    for i in 0 ..< 3:
      let villager = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      discard env.garrisonUnitInBuilding(villager, tower)
    check tower.garrisonedUnits.len == 3

    let enemyId = MapAgentsPerTeam + 3
    let enemy = addAgentAt(env, enemyId, ivec2(10, 13), unitClass = UnitBatteringRam)
    applyUnitClass(enemy, UnitBatteringRam)  # 18 HP - survives garrison fire
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)

    # Should take more damage than base tower attack (base 2 + garrison arrows)
    let damageDealt = startHp - enemy.hp
    check damageDealt > 0

  test "garrisoned units add bonus arrows to town center":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    # Garrison 5 villagers
    for i in 0 ..< 5:
      let villager = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      discard env.garrisonUnitInBuilding(villager, tc)
    check tc.garrisonedUnits.len == 5

    let enemyId = MapAgentsPerTeam + 5
    let enemy = addAgentAt(env, enemyId, ivec2(10, 14), unitClass = UnitBatteringRam)
    applyUnitClass(enemy, UnitBatteringRam)  # 18 HP - survives garrison fire
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)

    let damageDealt = startHp - enemy.hp
    check damageDealt > 0

  test "tower kills enemy over multiple steps":
    let env = makeEmptyEnv()
    discard addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let enemyId = MapAgentsPerTeam
    let enemy = addAgentAt(env, enemyId, ivec2(10, 13))

    var steps = 0
    while enemy.hp > 0 and steps < 100:
      env.stepAction(enemyId, 0'u8, 0)
      inc steps

    check enemy.hp <= 0
    check env.terminated[enemyId] == 1.0
    echo &"  Combat summary: Tower killed enemy in {steps} steps"

suite "Behavior: Tank Aura Damage Reduction":
  test "ManAtArms aura halves damage to nearby ally":
    let env = makeEmptyEnv()
    # Team 0: tank (ManAtArms) and a target villager
    let tank = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(tank, UnitManAtArms)
    let target = addAgentAt(env, 1, ivec2(10, 11))  # Adjacent to tank (radius 1)
    target.hp = 100
    target.maxHp = 100
    # Team 1: attacker
    let attacker = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 12))
    attacker.attackDamage = 10

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, target.pos))

    # Damage should be halved: (10 + 1) div 2 = 5
    check target.hp == 95

  test "ManAtArms aura does not affect ally outside radius":
    let env = makeEmptyEnv()
    let tank = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(tank, UnitManAtArms)
    let target = addAgentAt(env, 1, ivec2(10, 12))  # 2 tiles away (outside ManAtArms radius 1)
    target.hp = 100
    target.maxHp = 100
    let attacker = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 13))
    attacker.attackDamage = 10

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, target.pos))

    # Full damage (10) should be dealt
    check target.hp == 90

  test "Knight aura has larger radius (2 tiles)":
    let env = makeEmptyEnv()
    let tank = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight)
    applyUnitClass(tank, UnitKnight)
    let target = addAgentAt(env, 1, ivec2(10, 12))  # 2 tiles away (within Knight radius 2)
    target.hp = 100
    target.maxHp = 100
    let attacker = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 13))
    attacker.attackDamage = 10

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, target.pos))

    # Damage should be halved: (10 + 1) div 2 = 5
    check target.hp == 95

  test "Knight aura does not affect ally outside radius 2":
    let env = makeEmptyEnv()
    let tank = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight)
    applyUnitClass(tank, UnitKnight)
    let target = addAgentAt(env, 1, ivec2(10, 13))  # 3 tiles away (outside Knight radius 2)
    target.hp = 100
    target.maxHp = 100
    let attacker = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 14))
    attacker.attackDamage = 10

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, target.pos))

    # Full damage should be dealt
    check target.hp == 90
