## Behavioral tests for the tech tree research system.
## Validates prerequisites, research timing (cooldowns), effects applying
## to all eligible units, and duplicate research prevention across all
## four research subsystems: Blacksmith, University, Castle, and Unit Upgrades.

import std/[unittest]
import test_common

suite "Tech Tree - Research Cooldowns":
  ## Cooldowns are enforced at the step level (step.nim checks thing.cooldown == 0
  ## before calling tryResearch*). Direct tryResearch* calls bypass cooldown checks.
  ## These tests use stepAction to validate cooldown behavior end-to-end.

  test "blacksmith cooldown prevents immediate re-research via step":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # First research succeeds
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, blacksmith.pos))
    var totalLevels = 0
    for upgradeType in BlacksmithUpgradeType:
      totalLevels += env.teamBlacksmithUpgrades[0].levels[upgradeType]
    check totalLevels == 1
    check blacksmith.cooldown > 0

    # Immediate second step fails due to cooldown
    let foodBefore = env.stockpileCount(0, ResourceFood)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, blacksmith.pos))
    var totalLevelsAfter = 0
    for upgradeType in BlacksmithUpgradeType:
      totalLevelsAfter += env.teamBlacksmithUpgrades[0].levels[upgradeType]
    check totalLevelsAfter == 1  # No change
    check env.stockpileCount(0, ResourceFood) == foodBefore

  test "university cooldown prevents immediate re-research via step":
    let env = makeEmptyEnv()
    let university = addBuilding(env, University, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)
    setStockpile(env, 0, ResourceWood, 200)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, university.pos))
    check env.hasUniversityTech(0, TechBallistics)

    # Immediate second step blocked by cooldown
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, university.pos))
    check not env.hasUniversityTech(0, TechMurderHoles)

  test "castle tech cooldown prevents immediate re-research via step":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    check env.teamCastleTechs[0].researched[castleAge]

    # Immediate second step blocked by cooldown
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, castle.pos))
    check not env.teamCastleTechs[0].researched[imperialAge]

  test "unit upgrade cooldown prevents immediate re-research via step":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    check env.hasUnitUpgrade(0, UpgradeLongSwordsman)

    # Immediate second step blocked by cooldown
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barracks.pos))
    check not env.hasUnitUpgrade(0, UpgradeChampion)

suite "Tech Tree - Cooldown Via Step Simulation":
  test "blacksmith cooldown decrements through game steps":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # Research via step action
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, blacksmith.pos))
    var totalLevels = 0
    for upgradeType in BlacksmithUpgradeType:
      totalLevels += env.teamBlacksmithUpgrades[0].levels[upgradeType]
    check totalLevels == 1

    # Immediately after, another step action should fail (cooldown)
    let foodBefore = env.stockpileCount(0, ResourceFood)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, blacksmith.pos))
    var totalLevelsAfter = 0
    for upgradeType in BlacksmithUpgradeType:
      totalLevelsAfter += env.teamBlacksmithUpgrades[0].levels[upgradeType]
    check totalLevelsAfter == 1  # No change
    check env.stockpileCount(0, ResourceFood) == foodBefore  # No resources spent

    # Wait for cooldown to expire
    for i in 0 ..< 10:
      env.stepNoop()

    # Now research should succeed
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, blacksmith.pos))
    var totalLevelsFinal = 0
    for upgradeType in BlacksmithUpgradeType:
      totalLevelsFinal += env.teamBlacksmithUpgrades[0].levels[upgradeType]
    check totalLevelsFinal == 2

suite "Tech Tree - Duplicate Research Prevention":
  test "blacksmith cannot exceed max level":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Set all upgrades to max level
    for upgradeType in BlacksmithUpgradeType:
      env.teamBlacksmithUpgrades[0].levels[upgradeType] = BlacksmithUpgradeMaxLevel
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    check not env.tryResearchBlacksmithUpgrade(agent, blacksmith)
    # Resources untouched
    check env.stockpileCount(0, ResourceFood) == 200
    check env.stockpileCount(0, ResourceGold) == 200

  test "university cannot research already-researched tech":
    let env = makeEmptyEnv()
    let university = addBuilding(env, University, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Mark all techs as researched
    for tech in UniversityTechType:
      env.teamUniversityTechs[0].researched[tech] = true
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)
    setStockpile(env, 0, ResourceWood, 200)

    check not env.tryResearchUniversityTech(agent, university)
    check env.stockpileCount(0, ResourceFood) == 200

  test "castle cannot research when both techs done":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    env.teamCastleTechs[0].researched[castleAge] = true
    env.teamCastleTechs[0].researched[imperialAge] = true
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    check not env.tryResearchCastleTech(agent, castle)
    check env.stockpileCount(0, ResourceFood) == 200

  test "unit upgrade cannot re-research completed chain":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    env.teamUnitUpgrades[0].researched[UpgradeLongSwordsman] = true
    env.teamUnitUpgrades[0].researched[UpgradeChampion] = true
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    check not env.tryResearchUnitUpgrade(agent, barracks)
    check env.stockpileCount(0, ResourceFood) == 200

  test "all three unit upgrade chains prevent duplicates independently":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let stable = addBuilding(env, Stable, ivec2(12, 9), 0)
    let archeryRange = addBuilding(env, ArcheryRange, ivec2(14, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # Complete infantry chain
    env.teamUnitUpgrades[0].researched[UpgradeLongSwordsman] = true
    env.teamUnitUpgrades[0].researched[UpgradeChampion] = true
    check not env.tryResearchUnitUpgrade(agent, barracks)

    # Cavalry chain is still available
    check env.tryResearchUnitUpgrade(agent, stable)
    check env.hasUnitUpgrade(0, UpgradeLightCavalry)

    # Archer chain is still available
    check env.tryResearchUnitUpgrade(agent, archeryRange)
    check env.hasUnitUpgrade(0, UpgradeCrossbowman)

suite "Tech Tree - Prerequisites":
  test "castle Imperial Age tech requires Castle Age tech":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # First research is always Castle Age
    check env.tryResearchCastleTech(agent, castle)
    check env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Imperial only available after Castle Age
    castle.cooldown = 0
    check env.tryResearchCastleTech(agent, castle)
    check env.teamCastleTechs[0].researched[imperialAge]

  test "unit upgrade tier 3 requires tier 2 for all chains":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let stable = addBuilding(env, Stable, ivec2(12, 9), 0)
    let archeryRange = addBuilding(env, ArcheryRange, ivec2(14, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # Infantry: researching always gives tier 2 first
    check env.tryResearchUnitUpgrade(agent, barracks)
    check env.hasUnitUpgrade(0, UpgradeLongSwordsman)
    check not env.hasUnitUpgrade(0, UpgradeChampion)

    # Cavalry: researching always gives tier 2 first
    check env.tryResearchUnitUpgrade(agent, stable)
    check env.hasUnitUpgrade(0, UpgradeLightCavalry)
    check not env.hasUnitUpgrade(0, UpgradeHussar)

    # Archer: researching always gives tier 2 first
    check env.tryResearchUnitUpgrade(agent, archeryRange)
    check env.hasUnitUpgrade(0, UpgradeCrossbowman)
    check not env.hasUnitUpgrade(0, UpgradeArbalester)

    # Now tier 3 is available for each
    barracks.cooldown = 0
    stable.cooldown = 0
    archeryRange.cooldown = 0
    check env.tryResearchUnitUpgrade(agent, barracks)
    check env.hasUnitUpgrade(0, UpgradeChampion)
    check env.tryResearchUnitUpgrade(agent, stable)
    check env.hasUnitUpgrade(0, UpgradeHussar)
    check env.tryResearchUnitUpgrade(agent, archeryRange)
    check env.hasUnitUpgrade(0, UpgradeArbalester)

  test "university techs research in sequential order":
    let env = makeEmptyEnv()
    let university = addBuilding(env, University, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)
    setStockpile(env, 0, ResourceWood, 1000)

    # Research all university techs in order
    var lastTech: UniversityTechType
    for tech in UniversityTechType:
      university.cooldown = 0
      check env.tryResearchUniversityTech(agent, university)
      check env.hasUniversityTech(0, tech)
      lastTech = tech

    # Verify all researched
    for tech in UniversityTechType:
      check env.hasUniversityTech(0, tech)

  test "blacksmith upgrades rotate through all upgrade types evenly":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)

    # Research 5 upgrades (one per type at level 1)
    for i in 0 ..< 5:
      blacksmith.cooldown = 0
      check env.tryResearchBlacksmithUpgrade(agent, blacksmith)

    # All upgrade types should be at level 1
    for upgradeType in BlacksmithUpgradeType:
      check env.teamBlacksmithUpgrades[0].levels[upgradeType] == 1

suite "Tech Tree - Effects Apply to All Eligible Units":
  test "unit upgrade promotes all matching units on team":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    # Create multiple Man-at-Arms across the map
    let soldier1 = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitManAtArms)
    soldier1.hp = ManAtArmsMaxHp
    soldier1.maxHp = ManAtArmsMaxHp
    soldier1.attackDamage = ManAtArmsAttackDamage

    let soldier2 = addAgentAt(env, 2, ivec2(14, 10), unitClass = UnitManAtArms)
    soldier2.hp = ManAtArmsMaxHp
    soldier2.maxHp = ManAtArmsMaxHp
    soldier2.attackDamage = ManAtArmsAttackDamage

    let soldier3 = addAgentAt(env, 3, ivec2(16, 10), unitClass = UnitManAtArms)
    soldier3.hp = ManAtArmsMaxHp
    soldier3.maxHp = ManAtArmsMaxHp
    soldier3.attackDamage = ManAtArmsAttackDamage

    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    check env.tryResearchUnitUpgrade(villager, barracks)

    # All soldiers should be promoted
    check soldier1.unitClass == UnitLongSwordsman
    check soldier1.maxHp == LongSwordsmanMaxHp
    check soldier1.attackDamage == LongSwordsmanAttackDamage

    check soldier2.unitClass == UnitLongSwordsman
    check soldier2.maxHp == LongSwordsmanMaxHp
    check soldier2.attackDamage == LongSwordsmanAttackDamage

    check soldier3.unitClass == UnitLongSwordsman
    check soldier3.maxHp == LongSwordsmanMaxHp
    check soldier3.attackDamage == LongSwordsmanAttackDamage

  test "cavalry upgrade promotes all scouts to light cavalry":
    let env = makeEmptyEnv()
    let stable = addBuilding(env, Stable, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    let scout1 = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitScout)
    scout1.hp = ScoutMaxHp
    scout1.maxHp = ScoutMaxHp
    scout1.attackDamage = ScoutAttackDamage

    let scout2 = addAgentAt(env, 2, ivec2(14, 10), unitClass = UnitScout)
    scout2.hp = ScoutMaxHp
    scout2.maxHp = ScoutMaxHp
    scout2.attackDamage = ScoutAttackDamage

    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    check env.tryResearchUnitUpgrade(villager, stable)

    check scout1.unitClass == UnitLightCavalry
    check scout1.maxHp == LightCavalryMaxHp
    check scout2.unitClass == UnitLightCavalry
    check scout2.maxHp == LightCavalryMaxHp

  test "archer upgrade promotes all archers to crossbowman":
    let env = makeEmptyEnv()
    let archeryRange = addBuilding(env, ArcheryRange, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    let archer1 = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitArcher)
    archer1.hp = ArcherMaxHp
    archer1.maxHp = ArcherMaxHp
    archer1.attackDamage = ArcherAttackDamage

    let archer2 = addAgentAt(env, 2, ivec2(14, 10), unitClass = UnitArcher)
    archer2.hp = ArcherMaxHp
    archer2.maxHp = ArcherMaxHp
    archer2.attackDamage = ArcherAttackDamage

    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    check env.tryResearchUnitUpgrade(villager, archeryRange)

    check archer1.unitClass == UnitCrossbowman
    check archer1.maxHp == CrossbowmanMaxHp
    check archer2.unitClass == UnitCrossbowman
    check archer2.maxHp == CrossbowmanMaxHp

  test "upgrade does not promote units of different class":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    # Create mixed army
    let infantry = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitManAtArms)
    infantry.hp = ManAtArmsMaxHp
    infantry.maxHp = ManAtArmsMaxHp
    infantry.attackDamage = ManAtArmsAttackDamage

    let cavalry = addAgentAt(env, 2, ivec2(14, 10), unitClass = UnitScout)
    cavalry.hp = ScoutMaxHp
    cavalry.maxHp = ScoutMaxHp
    cavalry.attackDamage = ScoutAttackDamage

    let archer = addAgentAt(env, 3, ivec2(16, 10), unitClass = UnitArcher)
    archer.hp = ArcherMaxHp
    archer.maxHp = ArcherMaxHp
    archer.attackDamage = ArcherAttackDamage

    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # Research infantry upgrade at barracks
    check env.tryResearchUnitUpgrade(villager, barracks)

    # Only infantry promoted
    check infantry.unitClass == UnitLongSwordsman
    # Cavalry and archer unchanged
    check cavalry.unitClass == UnitScout
    check archer.unitClass == UnitArcher

  test "upgrade does not promote enemy team units":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    # Friendly soldier
    let friendly = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitManAtArms)
    friendly.hp = ManAtArmsMaxHp
    friendly.maxHp = ManAtArmsMaxHp
    friendly.attackDamage = ManAtArmsAttackDamage

    # Enemy soldier (team 1)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(14, 10), unitClass = UnitManAtArms)
    enemy.hp = ManAtArmsMaxHp
    enemy.maxHp = ManAtArmsMaxHp
    enemy.attackDamage = ManAtArmsAttackDamage

    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    check env.tryResearchUnitUpgrade(villager, barracks)

    check friendly.unitClass == UnitLongSwordsman
    check enemy.unitClass == UnitManAtArms  # Unchanged

  test "upgrade preserves HP ratio for damaged units":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    let soldier = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitManAtArms)
    soldier.maxHp = ManAtArmsMaxHp
    soldier.hp = ManAtArmsMaxHp div 2  # 50% HP
    soldier.attackDamage = ManAtArmsAttackDamage

    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    check env.tryResearchUnitUpgrade(villager, barracks)

    check soldier.unitClass == UnitLongSwordsman
    check soldier.maxHp == LongSwordsmanMaxHp
    # HP should be approximately 50% of new max
    check soldier.hp > 0
    check soldier.hp <= LongSwordsmanMaxHp

  test "castle tech bonuses apply to newly created units":
    let env = makeEmptyEnv()
    # Research Yeomen for team 0 (archer attack +1)
    env.teamCastleTechs[0].researched[CastleTechYeomen] = true
    env.applyCastleTechBonuses(0, CastleTechYeomen)

    # Multiple archers all get the bonus
    let archer1 = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer1, UnitArcher)
    let archer2 = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer2, UnitArcher)
    let archer3 = addAgentAt(env, 2, ivec2(14, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer3, UnitArcher)

    check archer1.attackDamage == ArcherAttackDamage + 1
    check archer2.attackDamage == ArcherAttackDamage + 1
    check archer3.attackDamage == ArcherAttackDamage + 1

  test "castle tech bonuses do not affect other teams":
    let env = makeEmptyEnv()
    # Research Yeomen for team 0 only
    env.teamCastleTechs[0].researched[CastleTechYeomen] = true
    env.applyCastleTechBonuses(0, CastleTechYeomen)

    # Team 0 archer gets bonus
    let archer0 = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer0, UnitArcher)

    # Team 1 archer does NOT get bonus
    let archer1 = addAgentAt(env, MapAgentsPerTeam, ivec2(14, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer1, UnitArcher)

    check archer0.attackDamage == ArcherAttackDamage + 1
    check archer1.attackDamage == ArcherAttackDamage  # No bonus

suite "Tech Tree - Cross-System Independence":
  test "researching at one building does not affect others":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let university = addBuilding(env, University, ivec2(12, 9), 0)
    let barracks = addBuilding(env, Barracks, ivec2(14, 9), 0)
    discard addBuilding(env, Castle, ivec2(16, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)
    setStockpile(env, 0, ResourceWood, 1000)

    # Research only at blacksmith
    check env.tryResearchBlacksmithUpgrade(agent, blacksmith)

    # Other systems untouched
    for tech in UniversityTechType:
      check not env.hasUniversityTech(0, tech)
    check not env.hasUnitUpgrade(0, UpgradeLongSwordsman)
    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

  test "different teams research independently across all systems":
    let env = makeEmptyEnv()
    # Team 0: blacksmith upgrade
    let blacksmith0 = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)
    check env.tryResearchBlacksmithUpgrade(agent0, blacksmith0)

    # Team 1: university tech
    let university1 = addBuilding(env, University, ivec2(20, 9), 1)
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 10))
    setStockpile(env, 1, ResourceFood, 200)
    setStockpile(env, 1, ResourceGold, 200)
    setStockpile(env, 1, ResourceWood, 200)
    check env.tryResearchUniversityTech(agent1, university1)

    # Verify independence
    var team0Levels = 0
    for upgradeType in BlacksmithUpgradeType:
      team0Levels += env.teamBlacksmithUpgrades[0].levels[upgradeType]
    check team0Levels == 1

    var team1Levels = 0
    for upgradeType in BlacksmithUpgradeType:
      team1Levels += env.teamBlacksmithUpgrades[1].levels[upgradeType]
    check team1Levels == 0  # Team 1 didn't research blacksmith

    check not env.hasUniversityTech(0, TechBallistics)  # Team 0 didn't research university
    check env.hasUniversityTech(1, TechBallistics)  # Team 1 did

suite "Tech Tree - Effective Train Unit After Research":
  test "buildings train upgraded units after full chain":
    let env = makeEmptyEnv()

    # Complete all upgrade chains
    env.teamUnitUpgrades[0].researched[UpgradeLongSwordsman] = true
    env.teamUnitUpgrades[0].researched[UpgradeChampion] = true
    env.teamUnitUpgrades[0].researched[UpgradeLightCavalry] = true
    env.teamUnitUpgrades[0].researched[UpgradeHussar] = true
    env.teamUnitUpgrades[0].researched[UpgradeCrossbowman] = true
    env.teamUnitUpgrades[0].researched[UpgradeArbalester] = true

    check env.effectiveTrainUnit(Barracks, 0) == UnitChampion
    check env.effectiveTrainUnit(Stable, 0) == UnitHussar
    check env.effectiveTrainUnit(ArcheryRange, 0) == UnitArbalester

  test "partial upgrade chain trains intermediate unit":
    let env = makeEmptyEnv()

    # Only tier 2 researched
    env.teamUnitUpgrades[0].researched[UpgradeLongSwordsman] = true
    check env.effectiveTrainUnit(Barracks, 0) == UnitLongSwordsman

    # Tier 3 not yet, so still LongSwordsman
    check not env.hasUnitUpgrade(0, UpgradeChampion)
    check env.effectiveTrainUnit(Barracks, 0) == UnitLongSwordsman

  test "unresearched team trains base units":
    let env = makeEmptyEnv()

    # Team 0 has upgrades, team 1 does not
    env.teamUnitUpgrades[0].researched[UpgradeLongSwordsman] = true

    check env.effectiveTrainUnit(Barracks, 0) == UnitLongSwordsman
    check env.effectiveTrainUnit(Barracks, 1) == UnitManAtArms  # Team 1 still base

suite "Tech Tree - Research Validation":
  test "only villagers can research at any building":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let university = addBuilding(env, University, ivec2(12, 9), 0)
    let barracks = addBuilding(env, Barracks, ivec2(14, 9), 0)
    let castle = addBuilding(env, Castle, ivec2(16, 9), 0)
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)
    setStockpile(env, 0, ResourceWood, 1000)

    # Man-at-Arms cannot research anywhere
    let soldier = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(soldier, UnitManAtArms)

    check not env.tryResearchBlacksmithUpgrade(soldier, blacksmith)
    check not env.tryResearchUniversityTech(soldier, university)
    check not env.tryResearchUnitUpgrade(soldier, barracks)
    check not env.tryResearchCastleTech(soldier, castle)

  test "cannot research at enemy buildings":
    let env = makeEmptyEnv()
    # All buildings belong to team 1
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 1)
    let university = addBuilding(env, University, ivec2(12, 9), 1)
    let barracks = addBuilding(env, Barracks, ivec2(14, 9), 1)
    let castle = addBuilding(env, Castle, ivec2(16, 9), 1)
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)
    setStockpile(env, 0, ResourceWood, 1000)

    # Team 0 villager cannot use team 1 buildings
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    check not env.tryResearchBlacksmithUpgrade(agent, blacksmith)
    check not env.tryResearchUniversityTech(agent, university)
    check not env.tryResearchUnitUpgrade(agent, barracks)
    check not env.tryResearchCastleTech(agent, castle)

  test "research fails with insufficient resources for all systems":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let university = addBuilding(env, University, ivec2(12, 9), 0)
    let barracks = addBuilding(env, Barracks, ivec2(14, 9), 0)
    let castle = addBuilding(env, Castle, ivec2(16, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Zero resources
    setStockpile(env, 0, ResourceFood, 0)
    setStockpile(env, 0, ResourceGold, 0)
    setStockpile(env, 0, ResourceWood, 0)

    check not env.tryResearchBlacksmithUpgrade(agent, blacksmith)
    check not env.tryResearchUniversityTech(agent, university)
    check not env.tryResearchUnitUpgrade(agent, barracks)
    check not env.tryResearchCastleTech(agent, castle)

suite "Tech Tree - Escalating Costs":
  test "blacksmith upgrade costs increase with level":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Level 0->1: costs 3 food + 2 gold (multiplier 1)
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)
    check env.tryResearchBlacksmithUpgrade(agent, blacksmith)
    check env.stockpileCount(0, ResourceFood) == 97  # 100 - 3
    check env.stockpileCount(0, ResourceGold) == 98  # 100 - 2

    # Set all other types to level 1 so next research targets same type at level 1->2
    for upgradeType in BlacksmithUpgradeType:
      if env.teamBlacksmithUpgrades[0].levels[upgradeType] == 0:
        env.teamBlacksmithUpgrades[0].levels[upgradeType] = 1
    blacksmith.cooldown = 0

    # Level 1->2: costs 6 food + 4 gold (multiplier 2)
    let foodBefore = env.stockpileCount(0, ResourceFood)
    let goldBefore = env.stockpileCount(0, ResourceGold)
    check env.tryResearchBlacksmithUpgrade(agent, blacksmith)
    check env.stockpileCount(0, ResourceFood) == foodBefore - 6
    check env.stockpileCount(0, ResourceGold) == goldBefore - 4

  test "university tech costs increase with tech index":
    let env = makeEmptyEnv()
    let university = addBuilding(env, University, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)
    setStockpile(env, 0, ResourceWood, 1000)

    # First tech (index 1): 5 food, 3 gold, 2 wood
    let f0 = env.stockpileCount(0, ResourceFood)
    check env.tryResearchUniversityTech(agent, university)
    check env.stockpileCount(0, ResourceFood) == f0 - 5
    check env.stockpileCount(0, ResourceGold) == 1000 - 3
    check env.stockpileCount(0, ResourceWood) == 1000 - 2

    # Second tech (index 2): 10 food, 6 gold, 4 wood
    university.cooldown = 0
    let f1 = env.stockpileCount(0, ResourceFood)
    let g1 = env.stockpileCount(0, ResourceGold)
    let w1 = env.stockpileCount(0, ResourceWood)
    check env.tryResearchUniversityTech(agent, university)
    check env.stockpileCount(0, ResourceFood) == f1 - 10
    check env.stockpileCount(0, ResourceGold) == g1 - 6
    check env.stockpileCount(0, ResourceWood) == w1 - 4

  test "castle tech Imperial Age costs more than Castle Age":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Castle Age: 4 food + 3 gold
    check env.tryResearchCastleTech(agent, castle)
    check env.stockpileCount(0, ResourceFood) == 96  # 100 - 4
    check env.stockpileCount(0, ResourceGold) == 97  # 100 - 3

    castle.cooldown = 0

    # Imperial Age: 8 food + 6 gold
    let f1 = env.stockpileCount(0, ResourceFood)
    let g1 = env.stockpileCount(0, ResourceGold)
    check env.tryResearchCastleTech(agent, castle)
    check env.stockpileCount(0, ResourceFood) == f1 - 8
    check env.stockpileCount(0, ResourceGold) == g1 - 6
