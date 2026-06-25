import std/unittest
import environment
import types
import items
import constants
import registry
import common_types
import test_utils

suite "Economy Techs - Research":
  test "hasEconomyTech returns false for unresearched tech":
    let env = makeEmptyEnv()
    check not env.hasEconomyTech(0, TechWheelbarrow)
    check not env.hasEconomyTech(0, TechDoubleBitAxe)
    check not env.hasEconomyTech(0, TechGoldMining)
    check not env.hasEconomyTech(0, TechHorseCollar)

  test "economyTechBuilding returns correct building":
    check economyTechBuilding(TechWheelbarrow) == TownCenter
    check economyTechBuilding(TechHandCart) == TownCenter
    check economyTechBuilding(TechDoubleBitAxe) == LumberCamp
    check economyTechBuilding(TechBowSaw) == LumberCamp
    check economyTechBuilding(TechTwoManSaw) == LumberCamp
    check economyTechBuilding(TechGoldMining) == MiningCamp
    check economyTechBuilding(TechGoldShaftMining) == MiningCamp
    check economyTechBuilding(TechStoneMining) == MiningCamp
    check economyTechBuilding(TechStoneShaftMining) == MiningCamp
    check economyTechBuilding(TechHorseCollar) == Mill
    check economyTechBuilding(TechHeavyPlow) == Mill
    check economyTechBuilding(TechCropRotation) == Mill

  test "economyTechPrerequisite returns correct prereq":
    # No prereq for first techs
    check economyTechPrerequisite(TechWheelbarrow) == TechWheelbarrow
    check economyTechPrerequisite(TechDoubleBitAxe) == TechDoubleBitAxe
    check economyTechPrerequisite(TechGoldMining) == TechGoldMining
    check economyTechPrerequisite(TechStoneMining) == TechStoneMining
    check economyTechPrerequisite(TechHorseCollar) == TechHorseCollar
    # Tier 2 requires tier 1
    check economyTechPrerequisite(TechHandCart) == TechWheelbarrow
    check economyTechPrerequisite(TechBowSaw) == TechDoubleBitAxe
    check economyTechPrerequisite(TechGoldShaftMining) == TechGoldMining
    check economyTechPrerequisite(TechStoneShaftMining) == TechStoneMining
    check economyTechPrerequisite(TechHeavyPlow) == TechHorseCollar
    # Tier 3 requires tier 2
    check economyTechPrerequisite(TechTwoManSaw) == TechBowSaw
    check economyTechPrerequisite(TechCropRotation) == TechHeavyPlow

suite "Economy Techs - Gathering Bonuses":
  test "getWoodGatherBonus returns 0 with no techs":
    let env = makeEmptyEnv()
    check env.getWoodGatherBonus(0) == 0

  test "getWoodGatherBonus accumulates with techs":
    let env = makeEmptyEnv()
    env.teamEconomyTechs[0].researched[TechDoubleBitAxe] = true
    check env.getWoodGatherBonus(0) == DoubleBitAxeGatherBonus
    env.teamEconomyTechs[0].researched[TechBowSaw] = true
    check env.getWoodGatherBonus(0) == DoubleBitAxeGatherBonus + BowSawGatherBonus
    env.teamEconomyTechs[0].researched[TechTwoManSaw] = true
    check env.getWoodGatherBonus(0) == DoubleBitAxeGatherBonus + BowSawGatherBonus + TwoManSawGatherBonus

  test "getGoldGatherBonus returns 0 with no techs":
    let env = makeEmptyEnv()
    check env.getGoldGatherBonus(0) == 0

  test "getGoldGatherBonus accumulates with techs":
    let env = makeEmptyEnv()
    env.teamEconomyTechs[0].researched[TechGoldMining] = true
    check env.getGoldGatherBonus(0) == GoldMiningGatherBonus
    env.teamEconomyTechs[0].researched[TechGoldShaftMining] = true
    check env.getGoldGatherBonus(0) == GoldMiningGatherBonus + GoldShaftMiningGatherBonus

  test "getStoneGatherBonus returns 0 with no techs":
    let env = makeEmptyEnv()
    check env.getStoneGatherBonus(0) == 0

  test "getStoneGatherBonus accumulates with techs":
    let env = makeEmptyEnv()
    env.teamEconomyTechs[0].researched[TechStoneMining] = true
    check env.getStoneGatherBonus(0) == StoneMiningGatherBonus
    env.teamEconomyTechs[0].researched[TechStoneShaftMining] = true
    check env.getStoneGatherBonus(0) == StoneMiningGatherBonus + StoneShaftMiningGatherBonus

suite "Economy Techs - Villager Carry Capacity":
  test "getVillagerCarryCapacity returns base capacity with no techs":
    let env = makeEmptyEnv()
    check env.getVillagerCarryCapacity(0) == ResourceCarryCapacity

  test "getVillagerCarryCapacity increases with Wheelbarrow":
    let env = makeEmptyEnv()
    env.teamEconomyTechs[0].researched[TechWheelbarrow] = true
    check env.getVillagerCarryCapacity(0) == ResourceCarryCapacity + WheelbarrowCarryBonus

  test "getVillagerCarryCapacity increases with Hand Cart":
    let env = makeEmptyEnv()
    env.teamEconomyTechs[0].researched[TechWheelbarrow] = true
    env.teamEconomyTechs[0].researched[TechHandCart] = true
    check env.getVillagerCarryCapacity(0) == ResourceCarryCapacity + WheelbarrowCarryBonus + HandCartCarryBonus

suite "Economy Techs - Farm Bonuses":
  test "getFarmFoodBonus returns 0 with no techs":
    let env = makeEmptyEnv()
    check env.getFarmFoodBonus(0) == 0

  test "getFarmFoodBonus accumulates with techs":
    let env = makeEmptyEnv()
    env.teamEconomyTechs[0].researched[TechHorseCollar] = true
    check env.getFarmFoodBonus(0) == HorseCollarFarmBonus
    env.teamEconomyTechs[0].researched[TechHeavyPlow] = true
    check env.getFarmFoodBonus(0) == HorseCollarFarmBonus + HeavyPlowFarmBonus
    env.teamEconomyTechs[0].researched[TechCropRotation] = true
    check env.getFarmFoodBonus(0) == HorseCollarFarmBonus + HeavyPlowFarmBonus + CropRotationFarmBonus

  test "canAutoReseed requires Horse Collar":
    let env = makeEmptyEnv()
    check not env.canAutoReseed(0)
    env.teamEconomyTechs[0].researched[TechHorseCollar] = true
    check env.canAutoReseed(0)

suite "Mill Farm Queue":
  test "addFarmToMillQueue adds position to queue":
    let env = makeEmptyEnv()
    let mill = Thing(kind: Mill, pos: ivec2(10, 10), teamId: 0)
    env.addFarmToMillQueue(mill, ivec2(11, 10))
    check mill.farmQueue.len == 1
    check mill.farmQueue[0] == ivec2(11, 10)

  test "addFarmToMillQueue rejects farms outside radius":
    let env = makeEmptyEnv()
    let mill = Thing(kind: Mill, pos: ivec2(10, 10), teamId: 0)
    # Mill fertile radius is 2
    env.addFarmToMillQueue(mill, ivec2(15, 15))  # Too far
    check mill.farmQueue.len == 0

  test "addFarmToMillQueue prevents duplicates":
    let env = makeEmptyEnv()
    let mill = Thing(kind: Mill, pos: ivec2(10, 10), teamId: 0)
    env.addFarmToMillQueue(mill, ivec2(11, 10))
    env.addFarmToMillQueue(mill, ivec2(11, 10))  # Duplicate
    check mill.farmQueue.len == 1

  test "findNearestMill finds mill within range":
    let env = makeEmptyEnv()
    let mill = Thing(kind: Mill, pos: ivec2(10, 10), teamId: 0)
    env.thingsByKind[Mill].add(mill)
    let found = env.findNearestMill(ivec2(11, 10), 0)
    check found == mill

  test "findNearestMill returns nil for wrong team":
    let env = makeEmptyEnv()
    let mill = Thing(kind: Mill, pos: ivec2(10, 10), teamId: 1)
    env.thingsByKind[Mill].add(mill)
    let found = env.findNearestMill(ivec2(11, 10), 0)
    check found == nil

  test "findNearestMill returns nil when out of range":
    let env = makeEmptyEnv()
    let mill = Thing(kind: Mill, pos: ivec2(10, 10), teamId: 0)
    env.thingsByKind[Mill].add(mill)
    let found = env.findNearestMill(ivec2(50, 50), 0)  # Too far
    check found == nil

suite "Mill Farm Queue - Pre-paid Reseeds":
  test "queueFarmReseed increments counter and spends wood":
    let env = makeEmptyEnv()
    let mill = addBuilding(env, Mill, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceWood, 10)

    check mill.queuedFarmReseeds == 0
    check env.queueFarmReseed(mill, 0)
    check mill.queuedFarmReseeds == 1
    check env.stockpileCount(0, ResourceWood) == 10 - FarmReseedWoodCost

  test "queueFarmReseed fails without resources":
    let env = makeEmptyEnv()
    let mill = addBuilding(env, Mill, ivec2(10, 10), 0)
    # No wood available

    check not env.queueFarmReseed(mill, 0)
    check mill.queuedFarmReseeds == 0

  test "queueFarmReseed fails for wrong team":
    let env = makeEmptyEnv()
    let mill = addBuilding(env, Mill, ivec2(10, 10), 0)  # Team 0 mill
    setStockpile(env, 1, ResourceWood, 10)

    check not env.queueFarmReseed(mill, 1)  # Team 1 tries to queue
    check mill.queuedFarmReseeds == 0

  test "multiple queueFarmReseed calls accumulate":
    let env = makeEmptyEnv()
    let mill = addBuilding(env, Mill, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceWood, 50)

    check env.queueFarmReseed(mill, 0)
    check env.queueFarmReseed(mill, 0)
    check env.queueFarmReseed(mill, 0)
    check mill.queuedFarmReseeds == 3

  test "pre-paid reseed immediately rebuilds exhausted farm":
    let env = makeEmptyEnv()
    let mill = addBuilding(env, Mill, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceWood, 10)

    # Queue a farm reseed (pre-pay)
    check env.queueFarmReseed(mill, 0)
    check mill.queuedFarmReseeds == 1

    # Create wheat field with 1 wheat (will be exhausted on next gather)
    let farmPos = ivec2(11, 10)  # Within mill fertile radius
    discard addResource(env, Wheat, farmPos, ItemWheat, 1)

    # Add a villager to harvest
    let agent = addAgentAt(env, 0, ivec2(11, 11))
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, farmPos))

    # Farm should be immediately rebuilt (no stubble)
    let thing = env.getBackgroundThing(farmPos)
    check thing != nil
    check thing.kind == Wheat
    check getInv(thing, ItemWheat) == ResourceNodeInitial
    check mill.queuedFarmReseeds == 0  # Reseed was consumed

  test "no pre-paid reseed creates stubble":
    let env = makeEmptyEnv()
    let mill = addBuilding(env, Mill, ivec2(10, 10), 0)
    # No pre-paid reseeds, but enable auto-reseed
    env.teamEconomyTechs[0].researched[TechHorseCollar] = true

    # Create wheat field with 1 wheat
    let farmPos = ivec2(11, 10)
    discard addResource(env, Wheat, farmPos, ItemWheat, 1)

    # Add a villager to harvest
    let agent = addAgentAt(env, 0, ivec2(11, 11))
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, farmPos))

    # Should create stubble since no pre-paid reseed
    let thing = env.getBackgroundThing(farmPos)
    check thing != nil
    check thing.kind == Stubble
    # Position should be added to mill's queue for delayed reseed
    check mill.farmQueue.len == 1
    check mill.farmQueue[0] == farmPos

suite "Economy Tech Research via Buildings":
  test "villager researches Double Bit Axe at Lumber Camp":
    let env = makeEmptyEnv()
    let lc = addBuilding(env, LumberCamp, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Provide resources for research cost
    setStockpile(env, 0, ResourceFood, DoubleBitAxeFoodCost)
    setStockpile(env, 0, ResourceWood, DoubleBitAxeWoodCost)

    check not env.hasEconomyTech(0, TechDoubleBitAxe)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lc.pos))
    check env.hasEconomyTech(0, TechDoubleBitAxe)

  test "villager researches Wheelbarrow at Town Center":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, WheelbarrowFoodCost)
    setStockpile(env, 0, ResourceWood, WheelbarrowWoodCost)

    check not env.hasEconomyTech(0, TechWheelbarrow)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, tc.pos))
    check env.hasEconomyTech(0, TechWheelbarrow)

  test "villager researches Gold Mining at Mining Camp":
    let env = makeEmptyEnv()
    let mc = addBuilding(env, MiningCamp, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, GoldMiningFoodCost)
    setStockpile(env, 0, ResourceWood, GoldMiningWoodCost)

    check not env.hasEconomyTech(0, TechGoldMining)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, mc.pos))
    check env.hasEconomyTech(0, TechGoldMining)

  test "villager researches Horse Collar at Mill":
    let env = makeEmptyEnv()
    let mill = addBuilding(env, Mill, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, HorseCollarFoodCost)
    setStockpile(env, 0, ResourceWood, HorseCollarWoodCost)

    check not env.hasEconomyTech(0, TechHorseCollar)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, mill.pos))
    check env.hasEconomyTech(0, TechHorseCollar)

  test "research fails without sufficient resources":
    let env = makeEmptyEnv()
    let lc = addBuilding(env, LumberCamp, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # No resources provided
    setStockpile(env, 0, ResourceFood, 0)
    setStockpile(env, 0, ResourceWood, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lc.pos))
    check not env.hasEconomyTech(0, TechDoubleBitAxe)

  test "research deducts stockpile resources":
    let env = makeEmptyEnv()
    let lc = addBuilding(env, LumberCamp, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 10)
    setStockpile(env, 0, ResourceWood, 10)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lc.pos))
    check env.hasEconomyTech(0, TechDoubleBitAxe)
    check env.stockpileCount(0, ResourceFood) == 10 - DoubleBitAxeFoodCost
    check env.stockpileCount(0, ResourceWood) == 10 - DoubleBitAxeWoodCost

  test "research respects prerequisite chain":
    let env = makeEmptyEnv()
    let lc = addBuilding(env, LumberCamp, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Give enough for Bow Saw but not Double Bit Axe researched
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceWood, 20)

    # First research should get Double Bit Axe (tier 1)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lc.pos))
    check env.hasEconomyTech(0, TechDoubleBitAxe)
    check not env.hasEconomyTech(0, TechBowSaw)

    # Wait for cooldown
    for i in 0 ..< 10:
      env.stepNoop()

    # Second research should get Bow Saw (tier 2)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lc.pos))
    check env.hasEconomyTech(0, TechBowSaw)

  test "dropoff takes priority over research":
    let env = makeEmptyEnv()
    let lc = addBuilding(env, LumberCamp, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 3)  # Agent carrying wood
    setStockpile(env, 0, ResourceFood, DoubleBitAxeFoodCost)
    setStockpile(env, 0, ResourceWood, DoubleBitAxeWoodCost)

    # Use action should drop off wood first, not research
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lc.pos))
    check agent.inventoryWood == 0  # Wood was dropped off
    check not env.hasEconomyTech(0, TechDoubleBitAxe)  # Research didn't happen

suite "Villager Carry Capacity - In-Game":
  test "villager gathers more resources with Wheelbarrow":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Place a gold resource node adjacent to agent
    let gold = addResource(env, Gold, ivec2(10, 9), ItemGold, 50)

    # Without tech: base capacity is ResourceCarryCapacity (5)
    for i in 0 ..< ResourceCarryCapacity:
      env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, gold.pos))
    check agent.inventoryGold == ResourceCarryCapacity

    # Try to gather one more - should fail (at capacity)
    let goldBefore = agent.inventoryGold
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, gold.pos))
    check agent.inventoryGold == goldBefore  # No change

  test "Wheelbarrow increases villager carry capacity":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let gold = addResource(env, Gold, ivec2(10, 9), ItemGold, 50)

    # Research Wheelbarrow
    env.teamEconomyTechs[0].researched[TechWheelbarrow] = true
    let newCap = ResourceCarryCapacity + WheelbarrowCarryBonus

    for i in 0 ..< newCap:
      env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, gold.pos))
    check agent.inventoryGold == newCap

    # One more should fail
    let goldBefore = agent.inventoryGold
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, gold.pos))
    check agent.inventoryGold == goldBefore

suite "Villager Speed Bonus":
  test "getVillagerSpeedBonus returns 0 with no techs":
    let env = makeEmptyEnv()
    check env.getVillagerSpeedBonus(0) == 0

  test "getVillagerSpeedBonus accumulates with techs":
    let env = makeEmptyEnv()
    env.teamEconomyTechs[0].researched[TechWheelbarrow] = true
    check env.getVillagerSpeedBonus(0) == WheelbarrowSpeedBonus
    env.teamEconomyTechs[0].researched[TechHandCart] = true
    check env.getVillagerSpeedBonus(0) == WheelbarrowSpeedBonus + HandCartSpeedBonus
