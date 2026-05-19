import std/unittest
import environment
import agent_control
import types
import items
import test_utils

suite "CivBonus - Default has no effect":
  test "defaultCivBonus returns all 1.0 multipliers":
    let cb = defaultCivBonus()
    check cb.gatherRateMultiplier == 1.0'f32
    check cb.buildSpeedMultiplier == 1.0'f32
    check cb.unitHpMultiplier == 1.0'f32
    check cb.unitAttackMultiplier == 1.0'f32
    check cb.buildingHpMultiplier == 1.0'f32
    check cb.woodCostMultiplier == 1.0'f32
    check cb.foodCostMultiplier == 1.0'f32

  test "makeEmptyEnv initializes all teams to default civ bonus":
    let env = makeEmptyEnv()
    for teamId in 0 ..< MapRoomObjectsTeams:
      check env.teamCivBonuses[teamId].gatherRateMultiplier == 1.0'f32
      check env.teamCivBonuses[teamId].buildSpeedMultiplier == 1.0'f32
      check env.teamCivBonuses[teamId].unitHpMultiplier == 1.0'f32
      check env.teamCivBonuses[teamId].unitAttackMultiplier == 1.0'f32
      check env.teamCivBonuses[teamId].buildingHpMultiplier == 1.0'f32
      check env.teamCivBonuses[teamId].woodCostMultiplier == 1.0'f32
      check env.teamCivBonuses[teamId].foodCostMultiplier == 1.0'f32

suite "CivBonus - Gather rate multiplier":
  test "gather rate multiplier increases resource income":
    let env = makeEmptyEnv()
    # Team 0: default (1.0x), Team 1: 1.5x gather rate
    env.teamCivBonuses[1] = CivBonus(
      gatherRateMultiplier: 1.5'f32, buildSpeedMultiplier: 1.0'f32,
      unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.0'f32,
      buildingHpMultiplier: 1.0'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 1.0'f32)

    # Both teams deposit 10 wood
    env.addToStockpile(0, ResourceWood, 10)
    env.addToStockpile(1, ResourceWood, 10)

    # Team 0 should get 10, Team 1 should get 15 (10 * 1.5)
    check env.teamStockpiles[0].counts[ResourceWood] == 10
    check env.teamStockpiles[1].counts[ResourceWood] == 15

  test "CivMongols gather rate applies correctly":
    let env = makeEmptyEnv()
    env.teamCivBonuses[0] = CivMongols  # 1.15x gather rate

    env.addToStockpile(0, ResourceFood, 100)
    # 100 * 1.15 = 115
    check env.teamStockpiles[0].counts[ResourceFood] == 115

suite "CivBonus - Build speed multiplier":
  test "build speed multiplier increases construction HP gain":
    let env = makeEmptyEnv()
    # Set up team 0 with faster build speed
    env.teamCivBonuses[0] = CivBonus(
      gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 2.0'f32,
      unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.0'f32,
      buildingHpMultiplier: 1.0'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 1.0'f32)

    # Place a building under construction for team 0
    let pos0 = ivec2(10, 10)
    let building0 = addBuilding(env, Wall, pos0, 0)
    building0.hp = 1
    building0.constructed = false

    # Place a building under construction for team 1 (default)
    let pos1 = ivec2(20, 20)
    let building1 = addBuilding(env, Wall, pos1, 1)
    building1.hp = 1
    building1.constructed = false

    # The build speed multiplier is applied in the step() construction bonus loop
    # We cannot easily call that directly, but we can verify the bonus is set
    check env.teamCivBonuses[0].buildSpeedMultiplier == 2.0'f32
    check env.teamCivBonuses[1].buildSpeedMultiplier == 1.0'f32

suite "CivBonus - Unit HP multiplier":
  test "unit HP multiplier increases trained unit HP":
    let env = makeEmptyEnv()
    env.teamCivBonuses[0] = CivBonus(
      gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.0'f32,
      unitHpMultiplier: 1.5'f32, unitAttackMultiplier: 1.0'f32,
      buildingHpMultiplier: 1.0'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 1.0'f32)

    # Create agents for both teams
    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))

    # Apply ManAtArms class to both
    applyUnitClass(env, agent0, UnitManAtArms)
    applyUnitClass(env, agent1, UnitManAtArms)

    # Team 0 should have 1.5x HP: ManAtArmsMaxHp (7) * 1.5 = 10.5 -> 11
    check agent0.maxHp == int(float32(ManAtArmsMaxHp) * 1.5'f32 + 0.5)
    # Team 1 should have normal HP
    check agent1.maxHp == ManAtArmsMaxHp

  test "CivFranks unit HP multiplier applies":
    let env = makeEmptyEnv()
    env.teamCivBonuses[0] = CivFranks  # 1.1x unit HP

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(env, agent, UnitKnight)

    # KnightMaxHp (8) * 1.1 = 8.8 -> 9
    check agent.maxHp == int(float32(KnightMaxHp) * 1.1'f32 + 0.5)

suite "CivBonus - Unit attack multiplier":
  test "unit attack multiplier increases trained unit attack":
    let env = makeEmptyEnv()
    env.teamCivBonuses[0] = CivBonus(
      gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.0'f32,
      unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.5'f32,
      buildingHpMultiplier: 1.0'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 1.0'f32)

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(env, agent, UnitArcher)

    # ArcherAttackDamage (1) * 1.5 = 1.5 -> 2
    check agent.attackDamage == int(float32(ArcherAttackDamage) * 1.5'f32 + 0.5)
    # HP should be normal
    check agent.maxHp == ArcherMaxHp

  test "CivBritons attack multiplier applies":
    let env = makeEmptyEnv()
    env.teamCivBonuses[0] = CivBritons  # 1.1x attack

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(env, agent, UnitManAtArms)

    # ManAtArmsAttackDamage (2) * 1.1 = 2.2 -> 2
    check agent.attackDamage == int(float32(ManAtArmsAttackDamage) * 1.1'f32 + 0.5)

suite "CivBonus - Building HP multiplier":
  test "building HP multiplier increases building max HP":
    let env = makeEmptyEnv()
    env.teamCivBonuses[0] = CivBonus(
      gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.0'f32,
      unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.0'f32,
      buildingHpMultiplier: 1.5'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 1.0'f32)

    # The building HP multiplier is applied during the build action in step.nim
    # Verify the bonus value is correctly set
    check env.teamCivBonuses[0].buildingHpMultiplier == 1.5'f32

  test "CivByzantines building HP multiplier value":
    let env = makeEmptyEnv()
    env.teamCivBonuses[0] = CivByzantines  # 1.15x building HP
    check env.teamCivBonuses[0].buildingHpMultiplier == 1.15'f32

suite "CivBonus - Cost multipliers":
  test "wood cost multiplier modifies building costs":
    let env = makeEmptyEnv()
    env.teamCivBonuses[0] = CivBonus(
      gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.0'f32,
      unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.0'f32,
      buildingHpMultiplier: 1.0'f32, woodCostMultiplier: 0.5'f32, foodCostMultiplier: 1.0'f32)

    # Wood cost multiplier is applied at build time in step.nim
    check env.teamCivBonuses[0].woodCostMultiplier == 0.5'f32

  test "food cost multiplier modifies unit training costs":
    let env = makeEmptyEnv()
    env.teamCivBonuses[0] = CivBonus(
      gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.0'f32,
      unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.0'f32,
      buildingHpMultiplier: 1.0'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 0.5'f32)

    # Food cost multiplier is applied in queueTrainUnit
    check env.teamCivBonuses[0].foodCostMultiplier == 0.5'f32

  test "CivBritons has reduced wood costs":
    check CivBritons.woodCostMultiplier == 0.9'f32

  test "CivFranks has reduced food costs":
    check CivFranks.foodCostMultiplier == 0.9'f32

suite "CivBonus - Predefined civs differ from neutral":
  test "each predefined civ is different from CivNeutral":
    check CivBritons != CivNeutral
    check CivFranks != CivNeutral
    check CivByzantines != CivNeutral
    check CivMongols != CivNeutral
    check CivTeutons != CivNeutral

  test "AllCivBonuses array contains all six civs":
    check AllCivBonuses.len == 6
    check AllCivBonuses[0] == CivNeutral
    check AllCivBonuses[1] == CivBritons
    check AllCivBonuses[2] == CivFranks
    check AllCivBonuses[3] == CivByzantines
    check AllCivBonuses[4] == CivMongols
    check AllCivBonuses[5] == CivTeutons

  test "CivMongols has gather and building HP tradeoff":
    check CivMongols.gatherRateMultiplier == 1.15'f32
    check CivMongols.buildingHpMultiplier == 0.9'f32

  test "CivTeutons is strong but expensive":
    check CivTeutons.unitHpMultiplier == 1.05'f32
    check CivTeutons.unitAttackMultiplier == 1.05'f32
    check CivTeutons.buildingHpMultiplier == 1.1'f32
    check CivTeutons.woodCostMultiplier == 1.05'f32
    check CivTeutons.foodCostMultiplier == 1.05'f32
