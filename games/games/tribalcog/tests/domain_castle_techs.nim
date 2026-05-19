import std/unittest
import environment
import items
import test_utils

suite "Castle Unique Tech Research":
  test "castle tech research costs resources (Castle Age)":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Castle Age tech costs: 4 food + 3 gold
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    # Verify no techs researched initially
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))

    # Castle Age tech should have been researched
    check env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Resources spent: 4 food + 3 gold
    check env.stockpileCount(0, ResourceFood) == 16  # 20 - 4
    check env.stockpileCount(0, ResourceGold) == 17  # 20 - 3

  test "castle tech research costs more for Imperial Age":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Pre-research Castle Age tech
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    env.teamCastleTechs[0].researched[castleAge] = true

    # Imperial Age tech costs: 8 food + 6 gold
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))

    # Imperial Age tech should have been researched
    check env.teamCastleTechs[0].researched[imperialAge]

    # Resources spent: 8 food + 6 gold
    check env.stockpileCount(0, ResourceFood) == 12  # 20 - 8
    check env.stockpileCount(0, ResourceGold) == 14  # 20 - 6

  test "castle tech fails without resources":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Not enough resources
    setStockpile(env, 0, ResourceFood, 1)
    setStockpile(env, 0, ResourceGold, 1)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))

    let (castleAge, imperialAge) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

  test "castle tech requires Castle Age before Imperial Age":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # First research should always be Castle Age
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))
    check env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Wait for cooldown
    for i in 0 ..< 15:
      env.stepNoop()

    # Second research should be Imperial Age
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))
    check env.teamCastleTechs[0].researched[imperialAge]

  test "only villagers can research castle techs":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(agent, UnitManAtArms)
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))

    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

  test "cannot research enemy castle techs":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 1)  # Team 1's castle
    let agent = addAgentAt(env, 0, ivec2(10, 10))  # Team 0's villager
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))

    let (castleAge0, _) = castleTechsForTeam(0)
    let (castleAge1, _) = castleTechsForTeam(1)
    check not env.teamCastleTechs[0].researched[castleAge0]
    check not env.teamCastleTechs[1].researched[castleAge1]

  test "no research when both techs already researched":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Pre-research both techs
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    env.teamCastleTechs[0].researched[castleAge] = true
    env.teamCastleTechs[0].researched[imperialAge] = true
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))

    # Both techs still researched (no change), but Castle falls through to train
    check env.teamCastleTechs[0].researched[castleAge]
    check env.teamCastleTechs[0].researched[imperialAge]
    # Train costs 4 food + 2 gold (Castle training cost for unique unit)
    check env.stockpileCount(0, ResourceFood) == 96   # 100 - 4 (training)
    check env.stockpileCount(0, ResourceGold) == 98    # 100 - 2 (training)

  test "teams have independent castle techs":
    let env = makeEmptyEnv()
    let castle0 = addBuilding(env, Castle, ivec2(10, 9), 0)
    let castle1 = addBuilding(env, Castle, ivec2(20, 9), 1)
    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, 125, ivec2(20, 10))  # Team 1 agent
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)
    setStockpile(env, 1, ResourceFood, 100)
    setStockpile(env, 1, ResourceGold, 100)

    # Only team 0 researches
    env.stepAction(agent0.agentId, 3'u8, dirIndex(agent0.pos, castle0.pos))

    let (castleAge0, _) = castleTechsForTeam(0)
    let (castleAge1, _) = castleTechsForTeam(1)
    check env.teamCastleTechs[0].researched[castleAge0]
    check not env.teamCastleTechs[1].researched[castleAge1]

suite "Castle Unique Tech Bonuses":
  test "Yeomen (Team 0 Castle) increases archer attack":
    let env = makeEmptyEnv()
    # Research Yeomen for team 0
    env.teamCastleTechs[0].researched[CastleTechYeomen] = true
    env.applyCastleTechBonuses(0, CastleTechYeomen)

    # Create archer for team 0 with modifiers applied
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer, UnitArcher)

    # Archer should have +1 attack from Yeomen
    check archer.attackDamage == ArcherAttackDamage + 1

  test "Logistica (Team 1 Castle) increases infantry attack":
    let env = makeEmptyEnv()
    env.teamCastleTechs[1].researched[CastleTechLogistica] = true
    env.applyCastleTechBonuses(1, CastleTechLogistica)

    let maa = addAgentAt(env, 125, ivec2(10, 10), unitClass = UnitManAtArms)
    env.applyUnitClass(maa, UnitManAtArms)

    check maa.attackDamage == ManAtArmsAttackDamage + 1

  test "Anarchy (Team 3 Castle) increases infantry HP":
    let env = makeEmptyEnv()
    env.teamCastleTechs[3].researched[CastleTechAnarchy] = true
    env.applyCastleTechBonuses(3, CastleTechAnarchy)

    let maa = addAgentAt(env, 375, ivec2(10, 10), unitClass = UnitManAtArms)
    env.applyUnitClass(maa, UnitManAtArms)

    check maa.maxHp == ManAtArmsMaxHp + 1
    check maa.hp == maa.maxHp

  test "Zealotry (Team 6 Castle) increases cavalry HP":
    let env = makeEmptyEnv()
    env.teamCastleTechs[6].researched[CastleTechZealotry] = true
    env.applyCastleTechBonuses(6, CastleTechZealotry)

    let knight = addAgentAt(env, 750, ivec2(10, 10), unitClass = UnitKnight)
    env.applyUnitClass(knight, UnitKnight)

    check knight.maxHp == KnightMaxHp + 2
    check knight.hp == knight.maxHp

  test "Sipahi (Team 7 Castle) increases archer HP":
    let env = makeEmptyEnv()
    env.teamCastleTechs[7].researched[CastleTechSipahi] = true
    env.applyCastleTechBonuses(7, CastleTechSipahi)

    let archer = addAgentAt(env, 875, ivec2(10, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer, UnitArcher)

    check archer.maxHp == ArcherMaxHp + 2
    check archer.hp == archer.maxHp

  test "FurorCeltica (Team 2 Imperial) increases siege attack":
    let env = makeEmptyEnv()
    env.teamCastleTechs[2].researched[CastleTechFurorCeltica] = true
    env.applyCastleTechBonuses(2, CastleTechFurorCeltica)

    let ram = addAgentAt(env, 250, ivec2(10, 10), unitClass = UnitBatteringRam)
    env.applyUnitClass(ram, UnitBatteringRam)

    check ram.attackDamage == BatteringRamAttackDamage + 2

  test "Ironclad (Team 4 Castle) increases siege HP":
    let env = makeEmptyEnv()
    env.teamCastleTechs[4].researched[CastleTechIronclad] = true
    env.applyCastleTechBonuses(4, CastleTechIronclad)

    let ram = addAgentAt(env, 500, ivec2(10, 10), unitClass = UnitBatteringRam)
    env.applyUnitClass(ram, UnitBatteringRam)

    check ram.maxHp == BatteringRamMaxHp + 3

  test "Berserkergang (Team 5 Castle) increases infantry HP":
    let env = makeEmptyEnv()
    env.teamCastleTechs[5].researched[CastleTechBerserkergang] = true
    env.applyCastleTechBonuses(5, CastleTechBerserkergang)

    let maa = addAgentAt(env, 625, ivec2(10, 10), unitClass = UnitManAtArms)
    env.applyUnitClass(maa, UnitManAtArms)

    check maa.maxHp == ManAtArmsMaxHp + 2

  test "Kataparuto (Team 0 Imperial) increases trebuchet attack":
    let env = makeEmptyEnv()
    env.teamCastleTechs[0].researched[CastleTechKataparuto] = true
    env.applyCastleTechBonuses(0, CastleTechKataparuto)

    let treb = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitTrebuchet)
    env.applyUnitClass(treb, UnitTrebuchet)

    check treb.attackDamage == TrebuchetAttackDamage + 3

  test "Perfusion (Team 3 Imperial) increases military attack":
    let env = makeEmptyEnv()
    env.teamCastleTechs[3].researched[CastleTechPerfusion] = true
    env.applyCastleTechBonuses(3, CastleTechPerfusion)

    let maa = addAgentAt(env, 375, ivec2(10, 10), unitClass = UnitManAtArms)
    env.applyUnitClass(maa, UnitManAtArms)
    let archer = addAgentAt(env, 376, ivec2(12, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer, UnitArcher)

    check maa.attackDamage == ManAtArmsAttackDamage + 2
    check archer.attackDamage == ArcherAttackDamage + 2

  test "Chieftains (Team 5 Imperial) increases cavalry attack":
    let env = makeEmptyEnv()
    env.teamCastleTechs[5].researched[CastleTechChieftains] = true
    env.applyCastleTechBonuses(5, CastleTechChieftains)

    let scout = addAgentAt(env, 625, ivec2(10, 10), unitClass = UnitScout)
    env.applyUnitClass(scout, UnitScout)

    check scout.attackDamage == ScoutAttackDamage + 1

  test "castleTechsForTeam returns correct pairs":
    for teamId in 0 ..< 8:
      let (castleAge, imperialAge) = castleTechsForTeam(teamId)
      check ord(castleAge) == teamId * 2
      check ord(imperialAge) == teamId * 2 + 1
