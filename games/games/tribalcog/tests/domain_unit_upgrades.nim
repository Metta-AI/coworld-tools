import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import registry
import test_utils

suite "Unit Upgrades - Research Costs":
  test "infantry upgrade research costs resources":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, UnitUpgradeTier2FoodCost)
    setStockpile(env, 0, ResourceGold, UnitUpgradeTier2GoldCost)

    check env.tryResearchUnitUpgrade(agent, barracks)
    check env.teamStockpiles[0].counts[ResourceFood] == 0
    check env.teamStockpiles[0].counts[ResourceGold] == 0
    check env.hasUnitUpgrade(0, UpgradeLongSwordsman)

  test "tier 3 upgrade costs more than tier 2":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Research tier 2 first
    env.teamUnitUpgrades[0].researched[UpgradeLongSwordsman] = true
    barracks.cooldown = 0
    setStockpile(env, 0, ResourceFood, UnitUpgradeTier3FoodCost)
    setStockpile(env, 0, ResourceGold, UnitUpgradeTier3GoldCost)

    check env.tryResearchUnitUpgrade(agent, barracks)
    check env.teamStockpiles[0].counts[ResourceFood] == 0
    check env.teamStockpiles[0].counts[ResourceGold] == 0
    check env.hasUnitUpgrade(0, UpgradeChampion)

  test "upgrade fails without resources":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # No resources set

    check not env.tryResearchUnitUpgrade(agent, barracks)
    check not env.hasUnitUpgrade(0, UpgradeLongSwordsman)

suite "Unit Upgrades - Prerequisites":
  test "tier 3 requires tier 2 prerequisite":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Give enough for tier 3 but don't research tier 2
    setStockpile(env, 0, ResourceFood, UnitUpgradeTier3FoodCost)
    setStockpile(env, 0, ResourceGold, UnitUpgradeTier3GoldCost)

    # Should research tier 2 first (not tier 3)
    check env.tryResearchUnitUpgrade(agent, barracks)
    check env.hasUnitUpgrade(0, UpgradeLongSwordsman)
    check not env.hasUnitUpgrade(0, UpgradeChampion)

  test "cavalry upgrade chain works":
    let env = makeEmptyEnv()
    let stable = addBuilding(env, Stable, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    # Research tier 2
    check env.tryResearchUnitUpgrade(agent, stable)
    check env.hasUnitUpgrade(0, UpgradeLightCavalry)
    # Research tier 3
    stable.cooldown = 0
    check env.tryResearchUnitUpgrade(agent, stable)
    check env.hasUnitUpgrade(0, UpgradeHussar)

  test "archer upgrade chain works":
    let env = makeEmptyEnv()
    let archeryRange = addBuilding(env, ArcheryRange, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    # Research tier 2
    check env.tryResearchUnitUpgrade(agent, archeryRange)
    check env.hasUnitUpgrade(0, UpgradeCrossbowman)
    # Research tier 3
    archeryRange.cooldown = 0
    check env.tryResearchUnitUpgrade(agent, archeryRange)
    check env.hasUnitUpgrade(0, UpgradeArbalester)

suite "Unit Upgrades - Only Villagers Can Research":
  test "only villagers can research upgrades":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let soldier = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    check not env.tryResearchUnitUpgrade(soldier, barracks)
    check not env.hasUnitUpgrade(0, UpgradeLongSwordsman)

  test "cannot research at enemy building":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 1)  # Team 1
    let agent = addAgentAt(env, 0, ivec2(10, 10))  # Team 0
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    check not env.tryResearchUnitUpgrade(agent, barracks)

suite "Unit Upgrades - Existing Unit Promotion":
  test "upgrade promotes existing units of that class":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    let soldier = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitManAtArms)
    soldier.hp = ManAtArmsMaxHp
    soldier.maxHp = ManAtArmsMaxHp
    soldier.attackDamage = ManAtArmsAttackDamage
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    check env.tryResearchUnitUpgrade(villager, barracks)
    # Soldier should now be a LongSwordsman
    check soldier.unitClass == UnitLongSwordsman
    check soldier.maxHp == LongSwordsmanMaxHp
    check soldier.attackDamage == LongSwordsmanAttackDamage

  test "upgrade preserves HP ratio":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    let soldier = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitManAtArms)
    soldier.hp = ManAtArmsMaxHp div 2  # Half HP
    soldier.maxHp = ManAtArmsMaxHp
    soldier.attackDamage = ManAtArmsAttackDamage
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    check env.tryResearchUnitUpgrade(villager, barracks)
    check soldier.unitClass == UnitLongSwordsman
    check soldier.maxHp == LongSwordsmanMaxHp
    # HP should be roughly proportional (half of new max)
    check soldier.hp > 0
    check soldier.hp <= LongSwordsmanMaxHp

  test "upgrade does not affect other team units":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    # Team 1 soldier (agentId 125+ would be team 1)
    let enemySoldier = addAgentAt(env, MapAgentsPerTeam, ivec2(14, 10), unitClass = UnitManAtArms)
    enemySoldier.hp = ManAtArmsMaxHp
    enemySoldier.maxHp = ManAtArmsMaxHp
    enemySoldier.attackDamage = ManAtArmsAttackDamage
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    check env.tryResearchUnitUpgrade(villager, barracks)
    # Enemy should NOT be upgraded
    check enemySoldier.unitClass == UnitManAtArms
    check enemySoldier.maxHp == ManAtArmsMaxHp

suite "Unit Upgrades - Effective Train Unit":
  test "barracks trains upgraded unit after research":
    let env = makeEmptyEnv()
    # Research LongSwordsman
    env.teamUnitUpgrades[0].researched[UpgradeLongSwordsman] = true

    check env.effectiveTrainUnit(Barracks, 0) == UnitLongSwordsman

  test "barracks trains champion after both upgrades":
    let env = makeEmptyEnv()
    env.teamUnitUpgrades[0].researched[UpgradeLongSwordsman] = true
    env.teamUnitUpgrades[0].researched[UpgradeChampion] = true

    check env.effectiveTrainUnit(Barracks, 0) == UnitChampion

  test "stable trains upgraded unit after research":
    let env = makeEmptyEnv()
    env.teamUnitUpgrades[0].researched[UpgradeLightCavalry] = true

    check env.effectiveTrainUnit(Stable, 0) == UnitLightCavalry

  test "archery range trains upgraded unit after research":
    let env = makeEmptyEnv()
    env.teamUnitUpgrades[0].researched[UpgradeCrossbowman] = true
    env.teamUnitUpgrades[0].researched[UpgradeArbalester] = true

    check env.effectiveTrainUnit(ArcheryRange, 0) == UnitArbalester

  test "unupgraded building trains base unit":
    let env = makeEmptyEnv()
    check env.effectiveTrainUnit(Barracks, 0) == UnitManAtArms
    check env.effectiveTrainUnit(Stable, 0) == UnitScout
    check env.effectiveTrainUnit(ArcheryRange, 0) == UnitArcher

suite "Unit Upgrades - Team Independence":
  test "teams have independent upgrades":
    let env = makeEmptyEnv()
    let barracks0 = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let barracks1 = addBuilding(env, Barracks, ivec2(20, 9), 1)
    let villager0 = addAgentAt(env, 0, ivec2(10, 10))
    let villager1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 10))
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    check env.tryResearchUnitUpgrade(villager0, barracks0)
    check env.hasUnitUpgrade(0, UpgradeLongSwordsman)
    check not env.hasUnitUpgrade(1, UpgradeLongSwordsman)

  test "no research when all upgrades done":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    env.teamUnitUpgrades[0].researched[UpgradeLongSwordsman] = true
    env.teamUnitUpgrades[0].researched[UpgradeChampion] = true
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)

    check not env.tryResearchUnitUpgrade(agent, barracks)

suite "Unit Upgrades - Stats Verification":
  test "LongSwordsman has correct stats":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitLongSwordsman)
    check agent.maxHp == LongSwordsmanMaxHp
    check agent.attackDamage == LongSwordsmanAttackDamage
    check agent.unitClass == UnitLongSwordsman

  test "Champion has correct stats":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitChampion)
    check agent.maxHp == ChampionMaxHp
    check agent.attackDamage == ChampionAttackDamage

  test "LightCavalry has correct stats":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitLightCavalry)
    check agent.maxHp == LightCavalryMaxHp
    check agent.attackDamage == LightCavalryAttackDamage

  test "Hussar has correct stats":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitHussar)
    check agent.maxHp == HussarMaxHp
    check agent.attackDamage == HussarAttackDamage

  test "Crossbowman has correct stats":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitCrossbowman)
    check agent.maxHp == CrossbowmanMaxHp
    check agent.attackDamage == CrossbowmanAttackDamage

  test "Arbalester has correct stats":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitArbalester)
    check agent.maxHp == ArbalesterMaxHp
    check agent.attackDamage == ArbalesterAttackDamage

suite "Unit Upgrades - Blacksmith Category":
  test "upgraded infantry units receive blacksmith bonuses":
    let env = makeEmptyEnv()
    check getUnitCategory(UnitLongSwordsman) == CategoryInfantry
    check getUnitCategory(UnitChampion) == CategoryInfantry

  test "upgraded cavalry units receive blacksmith bonuses":
    let env = makeEmptyEnv()
    check getUnitCategory(UnitLightCavalry) == CategoryCavalry
    check getUnitCategory(UnitHussar) == CategoryCavalry

  test "upgraded archers receive blacksmith bonuses":
    let env = makeEmptyEnv()
    check getUnitCategory(UnitCrossbowman) == CategoryArcher
    check getUnitCategory(UnitArbalester) == CategoryArcher
