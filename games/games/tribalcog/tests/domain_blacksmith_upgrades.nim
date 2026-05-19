import std/unittest
import environment
import items
import test_utils

suite "Blacksmith Upgrades":
  test "blacksmith upgrade research costs resources":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Cost for first upgrade: 3 food + 2 gold
    setStockpile(env, 0, ResourceFood, 10)
    setStockpile(env, 0, ResourceGold, 10)

    # Initial upgrade level should be 0
    check env.teamBlacksmithUpgrades[0].levels[UpgradeMeleeAttack] == 0

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, blacksmith.pos))

    # Upgrade should have been researched
    # Should have researched something (first available upgrade)
    var totalLevels = 0
    for upgradeType in BlacksmithUpgradeType:
      totalLevels += env.teamBlacksmithUpgrades[0].levels[upgradeType]
    check totalLevels == 1

    # Resources should have been spent (3 food + 2 gold for level 0->1)
    check env.stockpileCount(0, ResourceFood) == 7  # 10 - 3
    check env.stockpileCount(0, ResourceGold) == 8  # 10 - 2

  test "blacksmith upgrade fails without resources":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Not enough resources
    setStockpile(env, 0, ResourceFood, 1)
    setStockpile(env, 0, ResourceGold, 1)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, blacksmith.pos))

    # No upgrade should have been researched
    var totalLevels = 0
    for upgradeType in BlacksmithUpgradeType:
      totalLevels += env.teamBlacksmithUpgrades[0].levels[upgradeType]
    check totalLevels == 0

  test "blacksmith upgrade max level is respected":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Set all upgrades to max level
    for upgradeType in BlacksmithUpgradeType:
      env.teamBlacksmithUpgrades[0].levels[upgradeType] = BlacksmithUpgradeMaxLevel
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, blacksmith.pos))

    # No resources should have been spent
    check env.stockpileCount(0, ResourceFood) == 100
    check env.stockpileCount(0, ResourceGold) == 100

  test "blacksmith melee attack upgrade increases infantry damage":
    let env = makeEmptyEnv()
    # Set up melee attack upgrade to level 2 (Iron Casting: cumulative +2)
    env.teamBlacksmithUpgrades[0].levels[UpgradeMeleeAttack] = 2
    # Create a man-at-arms (infantry) and apply unit class stats
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(attacker, UnitManAtArms)
    # Create an enemy target
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    defender.hp = 10
    defender.maxHp = 10

    # Attack
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage is 2, +2 from Iron Casting = 4 damage
    check defender.hp == 6

  test "blast furnace gives extra attack bonus at level 3":
    let env = makeEmptyEnv()
    # Set up melee attack upgrade to level 3 (Blast Furnace: cumulative +4)
    env.teamBlacksmithUpgrades[0].levels[UpgradeMeleeAttack] = 3
    # Create a man-at-arms (infantry)
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(attacker, UnitManAtArms)
    # Create an enemy target
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    defender.hp = 20
    defender.maxHp = 20

    # Attack
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage is 2, +4 from Blast Furnace = 6 damage
    check defender.hp == 14

  test "blacksmith armor upgrade reduces damage":
    let env = makeEmptyEnv()
    # Set up infantry armor upgrade for the defender's team (level 2 = Chain Mail: +2 armor)
    env.teamBlacksmithUpgrades[1].levels[UpgradeInfantryArmor] = 2
    # Create attacker on team 0
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 6
    # Create a man-at-arms (infantry) defender on team 1 and apply unit class
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitManAtArms)
    applyUnitClass(defender, UnitManAtArms)
    defender.hp = 10
    defender.maxHp = 10

    # Attack
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage is 6, ManAtArms aura halves to (6+1)/2 = 3, -2 Chain Mail armor = 1 damage
    check defender.hp == 9

  test "plate mail gives extra armor at level 3":
    let env = makeEmptyEnv()
    # Set up infantry armor to level 3 (Plate Mail: cumulative +4 armor)
    env.teamBlacksmithUpgrades[1].levels[UpgradeInfantryArmor] = 3
    # Create attacker on team 0
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 8
    # Create a man-at-arms defender on team 1
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitManAtArms)
    applyUnitClass(defender, UnitManAtArms)
    defender.hp = 10
    defender.maxHp = 10

    # Attack
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage is 8, ManAtArms aura halves to (8+1)/2 = 4, -4 Plate Mail armor = 0,
    # but minimum damage is 1 (AoE2 rule)
    check defender.hp == 9

  test "melee attack upgrade applies to cavalry":
    let env = makeEmptyEnv()
    # Melee attack (Forging line) applies to both infantry AND cavalry
    env.teamBlacksmithUpgrades[0].levels[UpgradeMeleeAttack] = 3
    # Create a scout (cavalry) and apply unit class
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitScout)
    applyUnitClass(attacker, UnitScout)
    # Create an enemy target
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    defender.hp = 10
    defender.maxHp = 10

    # Attack
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage is 1, +4 from Blast Furnace = 5 damage
    check defender.hp == 5

  test "archer attack upgrade applies to archers":
    let env = makeEmptyEnv()
    # Set up archer attack upgrade (Fletching line)
    env.teamBlacksmithUpgrades[0].levels[UpgradeArcherAttack] = 1
    # Create an archer and apply unit class
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(attacker, UnitArcher)
    # Create an enemy target at range
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    defender.hp = 10
    defender.maxHp = 10

    # Attack
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage is 1, +1 from Fletching = 2 damage
    check defender.hp == 8

  test "archer attack max level gives +3":
    let env = makeEmptyEnv()
    # Bracer (level 3) gives cumulative +3 (not +4 like melee)
    env.teamBlacksmithUpgrades[0].levels[UpgradeArcherAttack] = 3
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(attacker, UnitArcher)
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    defender.hp = 10
    defender.maxHp = 10

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage is 1, +3 from Bracer = 4 damage
    check defender.hp == 6

  test "villager does not receive upgrade bonuses":
    let env = makeEmptyEnv()
    # Set up all upgrades
    for upgradeType in BlacksmithUpgradeType:
      env.teamBlacksmithUpgrades[0].levels[upgradeType] = 3
    # Create a villager
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    check attacker.unitClass == UnitVillager
    # Create an enemy target
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    defender.hp = 10
    defender.maxHp = 10

    # Attack
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage is 1, no upgrades for villagers
    check defender.hp == 9

  test "only villagers can research upgrades":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    # Create a man-at-arms (not a villager) and apply unit class
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(agent, UnitManAtArms)
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, blacksmith.pos))

    # No upgrade should have been researched
    var totalLevels = 0
    for upgradeType in BlacksmithUpgradeType:
      totalLevels += env.teamBlacksmithUpgrades[0].levels[upgradeType]
    check totalLevels == 0

  test "teams have independent upgrades":
    let env = makeEmptyEnv()
    # Set up different upgrade levels for teams
    env.teamBlacksmithUpgrades[0].levels[UpgradeMeleeAttack] = 1  # Forging: +1
    env.teamBlacksmithUpgrades[1].levels[UpgradeMeleeAttack] = 3  # Blast Furnace: +4

    # Create two man-at-arms from different teams attacking each other
    let attacker0 = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(attacker0, UnitManAtArms)
    let attacker1 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitManAtArms)
    applyUnitClass(attacker1, UnitManAtArms)
    attacker0.hp = 20
    attacker0.maxHp = 20
    attacker1.hp = 20
    attacker1.maxHp = 20

    # Team 0 attacks team 1: base 2 + 1 (Forging) = 3, halved by ManAtArms aura = 2 damage
    env.stepAction(attacker0.agentId, 2'u8, dirIndex(attacker0.pos, attacker1.pos))
    check attacker1.hp == 18

    # Team 1 attacks team 0: base 2 + 4 (Blast Furnace) = 6, halved by aura = 3 damage
    env.stepAction(attacker1.agentId, 2'u8, dirIndex(attacker1.pos, attacker0.pos))
    check attacker0.hp == 17

  test "cavalry armor upgrade reduces damage to cavalry":
    let env = makeEmptyEnv()
    # Set up cavalry armor (Plate Barding: level 3 = +4 armor)
    env.teamBlacksmithUpgrades[1].levels[UpgradeCavalryArmor] = 3
    # Create attacker on team 0
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 5
    # Create a scout (cavalry) defender on team 1
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitScout)
    applyUnitClass(defender, UnitScout)
    defender.hp = 10
    defender.maxHp = 10

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage 5, -4 Plate Barding = 1 damage
    check defender.hp == 9

  test "archer armor upgrade reduces damage to archers":
    let env = makeEmptyEnv()
    # Set up archer armor (Ring Archer: level 3 = +4 armor)
    env.teamBlacksmithUpgrades[1].levels[UpgradeArcherArmor] = 3
    # Create attacker on team 0
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 5
    # Create an archer defender on team 1
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitArcher)
    applyUnitClass(defender, UnitArcher)
    defender.hp = 10
    defender.maxHp = 10

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    # Base damage 5, -4 Ring Archer armor = 1 damage
    check defender.hp == 9
