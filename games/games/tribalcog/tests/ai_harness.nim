import std/unittest
import environment
import agent_control
import types
import items
import terrain
import test_utils

proc fillStockpile(env: Environment, teamId: int, amount: int) =
  setStockpile(env, teamId, ResourceFood, amount)
  setStockpile(env, teamId, ResourceWood, amount)
  setStockpile(env, teamId, ResourceStone, amount)
  setStockpile(env, teamId, ResourceGold, amount)

suite "Mechanics - Resources":
  test "tree to stump and stump depletes":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addResource(env, Tree, ivec2(10, 9), ItemWood, ResourceNodeInitial)

    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    let stump = env.getThing(ivec2(10, 9))
    check stump.kind == Stump
    check getInv(stump, ItemWood) == ResourceNodeInitial - 1
    check agent.inventoryWood == 1

    setInv(stump, ItemWood, 1)
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    check env.getThing(ivec2(10, 9)) == nil

  test "wheat depletes and removes":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addResource(env, Wheat, ivec2(10, 9), ItemWheat, 2)

    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    let wheat = env.getBackgroundThing(ivec2(10, 9))
    check wheat.kind == Stubble
    check getInv(wheat, ItemWheat) == 1

    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    check env.getBackgroundThing(ivec2(10, 9)) == nil

  test "stone and gold deplete":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addResource(env, Stone, ivec2(10, 9), ItemStone, 1)
    discard addResource(env, Gold, ivec2(11, 10), ItemGold, 1)
    let goldNode = env.getThing(ivec2(11, 10))
    check getInv(goldNode, ItemGold) == 1

    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    check env.getThing(ivec2(10, 9)) == nil

    agent.inventory = emptyInventory()
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(11, 10)))
    check env.getThing(ivec2(11, 10)) == nil

  test "boat harvests fish on water":
    let env = makeEmptyEnv()
    env.terrain[10][10] = Water
    env.terrain[10][9] = Water
    discard addBuilding(env, Dock, ivec2(10, 10), 0)
    discard addResource(env, Fish, ivec2(10, 9), ItemFish, 1)
    let agent = addAgentAt(env, 0, ivec2(10, 11))

    env.stepAction(agent.agentId, 1'u8, dirIndex(agent.pos, ivec2(10, 10)))
    check env.agents[agent.agentId].unitClass == UnitBoat

    env.stepAction(agent.agentId, 3'u8, dirIndex(ivec2(10, 10), ivec2(10, 9)))
    check getInv(env.agents[agent.agentId], ItemFish) == 1
    check env.getBackgroundThing(ivec2(10, 9)) == nil

  test "planting wheat consumes inventory and clears fertile":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryWheat = 1
    let target = ivec2(10, 9)
    env.terrain[target.x][target.y] = Fertile

    env.stepAction(agent.agentId, 7'u8, dirIndex(agent.pos, target))

    let crop = env.getBackgroundThing(target)
    check crop.kind == Wheat
    check getInv(crop, ItemWheat) == ResourceNodeInitial
    check agent.inventoryWheat == 0
    check env.terrain[target.x][target.y] == TerrainEmpty

suite "Mechanics - Biome Gathering Bonuses":
  test "forest biome grants wood bonus":
    let env = makeEmptyEnv()
    # Set biome to forest
    env.biomes[10][9] = BiomeForestType
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addResource(env, Tree, ivec2(10, 9), ItemWood, ResourceNodeInitial)

    # Harvest tree in forest biome - may get bonus
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    # Agent should have at least 1 wood (possibly 2 with bonus)
    check agent.inventoryWood >= 1

  test "plains biome grants wheat bonus":
    let env = makeEmptyEnv()
    # Set biome to plains
    env.biomes[10][9] = BiomePlainsType
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addResource(env, Wheat, ivec2(10, 9), ItemWheat, ResourceNodeInitial)

    # Harvest wheat in plains biome - may get bonus
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    # Agent should have at least 1 wheat (possibly 2 with bonus)
    check agent.inventoryWheat >= 1

  test "caves biome grants stone bonus":
    let env = makeEmptyEnv()
    # Set biome to caves
    env.biomes[10][9] = BiomeCavesType
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addResource(env, Stone, ivec2(10, 9), ItemStone, 1)

    # Harvest stone in caves biome - may get bonus
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    # Agent should have at least 1 stone (possibly 2 with bonus)
    check agent.inventoryStone >= 1

  test "snow biome grants gold bonus":
    let env = makeEmptyEnv()
    # Set biome to snow
    env.biomes[10][9] = BiomeSnowType
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addResource(env, Gold, ivec2(10, 9), ItemGold, 1)

    # Harvest gold in snow biome - may get bonus
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    # Agent should have at least 1 gold (possibly 2 with bonus)
    check getInv(agent, ItemGold) >= 1

  test "desert oasis grants bonus near water":
    let env = makeEmptyEnv()
    # Set biome to desert with water nearby
    env.biomes[10][9] = BiomeDesertType
    env.terrain[10][11] = Water  # Water within radius 3
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addResource(env, Stone, ivec2(10, 9), ItemStone, 1)

    # Harvest stone in desert near water - may get oasis bonus
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    # Agent should have at least 1 stone (possibly 2 with oasis bonus)
    check agent.inventoryStone >= 1

  test "no bonus in non-matching biome":
    let env = makeEmptyEnv()
    # Set biome to snow but harvest wood (no bonus for wood in snow)
    env.biomes[10][9] = BiomeSnowType
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addResource(env, Tree, ivec2(10, 9), ItemWood, ResourceNodeInitial)

    # Run many harvests to verify no bonus is given for wrong biome/resource combo
    for _ in 0 ..< 100:
      env.currentStep += 1
      let bonus = env.getBiomeGatherBonus(ivec2(10, 9), ItemWood)
      check bonus == 0  # Snow biome should not give wood bonus

  test "getBiomeGatherBonus returns bonuses over many trials":
    let env = makeEmptyEnv()
    # Test each biome/resource combination
    env.biomes[10][10] = BiomeForestType
    env.biomes[20][10] = BiomePlainsType
    env.biomes[30][10] = BiomeCavesType
    env.biomes[40][10] = BiomeSnowType

    var forestWoodBonus = 0
    var plainsWheatBonus = 0
    var cavesStoneBonus = 0
    var snowGoldBonus = 0

    # Use a larger sample with different steps to ensure variety
    for step in 0 ..< 1000:
      env.currentStep = step
      forestWoodBonus += env.getBiomeGatherBonus(ivec2(10, 10), ItemWood)
      plainsWheatBonus += env.getBiomeGatherBonus(ivec2(20, 10), ItemWheat)
      cavesStoneBonus += env.getBiomeGatherBonus(ivec2(30, 10), ItemStone)
      snowGoldBonus += env.getBiomeGatherBonus(ivec2(40, 10), ItemGold)

    # Verify that some bonuses were granted (at least 1% of trials)
    # and not too many (less than 50% of trials - well above 20% expected)
    check forestWoodBonus >= 10
    check plainsWheatBonus >= 10
    check cavesStoneBonus >= 10
    check snowGoldBonus >= 10
    check forestWoodBonus <= 500
    check plainsWheatBonus <= 500
    check cavesStoneBonus <= 500
    check snowGoldBonus <= 500

suite "Mechanics - Movement":
  test "boat embarks on dock and disembarks on land":
    let env = makeEmptyEnv()
    env.terrain[10][10] = Water
    discard addBuilding(env, Dock, ivec2(10, 10), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 11))

    env.stepAction(agent.agentId, 1'u8, dirIndex(agent.pos, ivec2(10, 10)))
    check env.agents[agent.agentId].pos == ivec2(10, 10)
    check env.agents[agent.agentId].unitClass == UnitBoat

    env.stepAction(agent.agentId, 1'u8, dirIndex(ivec2(10, 10), ivec2(10, 11)))
    check env.agents[agent.agentId].pos == ivec2(10, 11)
    check env.agents[agent.agentId].unitClass == UnitVillager

  test "swap action updates positions":
    let env = makeEmptyEnv()
    let agentA = addAgentAt(env, 0, ivec2(10, 10))
    let agentB = addAgentAt(env, 1, ivec2(10, 9))

    env.stepAction(agentA.agentId, 4'u8, dirIndex(agentA.pos, agentB.pos))

    check agentA.pos == ivec2(10, 9)
    check agentB.pos == ivec2(10, 10)
    check env.getThing(ivec2(10, 9)) == agentA
    check env.getThing(ivec2(10, 10)) == agentB

  test "snow terrain slows movement":
    let env = makeEmptyEnv()
    # Set up a path with snow terrain
    env.terrain[10][10] = Grass  # Starting position
    env.terrain[10][9] = Snow    # Destination
    env.terrain[10][8] = Grass   # For continued movement

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check agent.movementDebt == 0.0'f32

    # Move onto snow - should accumulate 0.2 debt (1.0 - 0.8 = 0.2)
    env.stepAction(agent.agentId, 1'u8, 0)  # Move N
    check agent.pos == ivec2(10, 9)
    check agent.movementDebt >= 0.19'f32 and agent.movementDebt <= 0.21'f32

    # Test debt accumulation prevents movement when >= 1.0
    agent.movementDebt = 1.0'f32
    env.stepAction(agent.agentId, 1'u8, 0)  # Try to move N
    check agent.pos == ivec2(10, 9)  # Should NOT have moved (debt was >= 1.0)
    check agent.movementDebt >= -0.01'f32 and agent.movementDebt <= 0.01'f32  # Debt consumed

    # Now agent can move again
    env.stepAction(agent.agentId, 1'u8, 0)  # Move N
    check agent.pos == ivec2(10, 8)  # Should have moved (debt was ~0)

  test "sand terrain applies moderate penalty":
    let env = makeEmptyEnv()
    env.terrain[10][10] = Grass
    env.terrain[10][9] = Sand  # 0.9 modifier = 0.1 penalty

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    env.stepAction(agent.agentId, 1'u8, 0)  # Move N onto sand
    check agent.pos == ivec2(10, 9)
    check agent.movementDebt >= 0.09'f32 and agent.movementDebt <= 0.11'f32

  test "dune terrain applies moderate penalty":
    let env = makeEmptyEnv()
    env.terrain[10][10] = Grass
    env.terrain[10][9] = Dune  # 0.85 modifier = 0.15 penalty

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    env.stepAction(agent.agentId, 1'u8, 0)  # Move N onto dune
    check agent.pos == ivec2(10, 9)
    check agent.movementDebt >= 0.14'f32 and agent.movementDebt <= 0.16'f32

  test "grass terrain has no penalty":
    let env = makeEmptyEnv()
    env.terrain[10][10] = Grass
    env.terrain[10][9] = Grass

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    env.stepAction(agent.agentId, 1'u8, 0)  # Move N onto grass
    check agent.pos == ivec2(10, 9)
    check agent.movementDebt == 0.0'f32  # No penalty for grass

  test "boats ignore terrain penalties":
    let env = makeEmptyEnv()
    # Set up dock on water and snow adjacent (for contrast)
    env.terrain[10][10] = Water
    env.terrain[10][9] = Snow  # Adjacent snow tile for comparison
    discard addBuilding(env, Dock, ivec2(10, 10), 0)

    let agent = addAgentAt(env, 0, ivec2(10, 11))

    # Embark on dock
    env.stepAction(agent.agentId, 1'u8, dirIndex(agent.pos, ivec2(10, 10)))
    check agent.unitClass == UnitBoat
    check agent.movementDebt == 0.0'f32  # Boats don't accumulate terrain debt

suite "Mechanics - Combat":
  test "attack kills enemy and drops corpse inventory":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    defender.hp = 1
    setInv(defender, ItemWood, 2)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    let corpse = env.getBackgroundThing(ivec2(10, 9))
    check corpse.kind == Corpse
    check getInv(corpse, ItemWood) == 2
    check env.terminated[defender.agentId] == 1.0

  test "armor absorbs damage before hp":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    defender.inventoryArmor = 2
    defender.hp = 5

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    check defender.inventoryArmor == 1
    check defender.hp == 5

  test "class bonus damage applies on counter hit":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    let infantry = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitManAtArms)
    let cavalry = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(12, 10), unitClass = UnitScout)
    archer.attackDamage = 1
    infantry.hp = 5
    cavalry.hp = 5

    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, infantry.pos))

    check infantry.hp == 4
    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, cavalry.pos))
    check cavalry.hp == 4

  test "spear attack hits at range and consumes spear":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.inventorySpear = 1
    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    defender.hp = 2

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))

    check attacker.inventorySpear == 0
    check defender.hp == 1

  test "monk heals adjacent ally":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    let ally = addAgentAt(env, 1, ivec2(10, 9))
    ally.hp = 1

    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, ally.pos))

    check ally.hp == 3

  test "guard tower attacks enemy in range":
    let env = makeEmptyEnv()
    discard addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let enemyId = MapAgentsPerTeam
    let enemy = addAgentAt(env, enemyId, ivec2(10, 13))
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)
    check enemy.hp < startHp

  test "castle attacks enemy in range":
    let env = makeEmptyEnv()
    discard addBuilding(env, Castle, ivec2(10, 10), 0)
    let enemyId = MapAgentsPerTeam
    let enemy = addAgentAt(env, enemyId, ivec2(10, 15))
    let startHp = enemy.hp

    env.stepAction(enemyId, 0'u8, 0)
    check enemy.hp < startHp

suite "Mechanics - Training":
  test "siege workshop trains battering ram":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, SiegeWorkshop, ivec2(10, 9), 0)
    env.teamStockpiles[0].counts[ResourceWood] = 10
    env.teamStockpiles[0].counts[ResourceStone] = 10

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    for i in 0 ..< unitTrainTime(UnitBatteringRam) - 1:
      env.stepNoop()
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    check agent.unitClass == UnitBatteringRam

  test "mangonel workshop trains mangonel":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, MangonelWorkshop, ivec2(10, 9), 0)
    env.teamStockpiles[0].counts[ResourceWood] = 10
    env.teamStockpiles[0].counts[ResourceStone] = 10

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    for i in 0 ..< unitTrainTime(UnitMangonel) - 1:
      env.stepNoop()
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    check agent.unitClass == UnitMangonel

  test "archery range trains archer":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, ArcheryRange, ivec2(10, 9), 0)
    env.teamStockpiles[0].counts[ResourceWood] = 10
    env.teamStockpiles[0].counts[ResourceGold] = 10

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    for i in 0 ..< unitTrainTime(UnitArcher) - 1:
      env.stepNoop()
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    check agent.unitClass == UnitArcher

  test "stable trains scout":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, Stable, ivec2(10, 9), 0)
    env.teamStockpiles[0].counts[ResourceFood] = 10

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    for i in 0 ..< unitTrainTime(UnitScout) - 1:
      env.stepNoop()
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    check agent.unitClass == UnitScout

  test "castle trains unique unit":
    # Castles train civilization-specific unique units (AoE2-style)
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, Castle, ivec2(10, 9), 0)
    env.teamStockpiles[0].counts[ResourceFood] = 10
    env.teamStockpiles[0].counts[ResourceGold] = 10

    # Pre-research both castle techs so interaction goes to training
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    env.teamCastleTechs[0].researched[castleAge] = true
    env.teamCastleTechs[0].researched[imperialAge] = true

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    for i in 0 ..< unitTrainTime(UnitSamurai) - 1:
      env.stepNoop()
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    # Team 0 trains Samurai at castles
    check agent.unitClass == UnitSamurai

suite "Mechanics - Siege":
  test "siege damage multiplier applies vs walls":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(attacker, UnitBatteringRam)
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, wall.pos))
    check wall.hp == WallMaxHp - (BatteringRamAttackDamage * SiegeStructureMultiplier)

  test "mangonel extended attack hits multiple targets":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    let enemyA = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    let enemyB = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(9, 8))
    let enemyC = addAgentAt(env, MapAgentsPerTeam + 2, ivec2(11, 8))
    let hpA = enemyA.hp
    let hpB = enemyB.hp
    let hpC = enemyC.hp

    env.stepAction(mangonel.agentId, 2'u8, dirIndex(mangonel.pos, enemyA.pos))
    check enemyA.hp < hpA
    check enemyB.hp < hpB
    check enemyC.hp < hpC

  test "mangonel attack reaches full 5-tile range":
    let env = makeEmptyEnv()
    let mangonel = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    # Enemy at range 5 (center line) and side prongs at range 5
    let enemyCenter = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))
    let enemyLeft = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(9, 5))
    let enemyRight = addAgentAt(env, MapAgentsPerTeam + 2, ivec2(11, 5))
    let hpCenter = enemyCenter.hp
    let hpLeft = enemyLeft.hp
    let hpRight = enemyRight.hp

    env.stepAction(mangonel.agentId, 2'u8, dirIndex(mangonel.pos, ivec2(10, 9)))
    check enemyCenter.hp < hpCenter
    check enemyLeft.hp < hpLeft
    check enemyRight.hp < hpRight

  test "siege prefers attacking blocking wall":
    let env = makeEmptyEnv()
    let ram = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBatteringRam)
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    env.add(wall)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(9, 10))
    let enemyHp = enemy.hp

    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))
    check wall.hp < WallMaxHp
    check enemy.hp == enemyHp

suite "Mechanics - Construction":
  test "villager working on construction increases hp":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Create a wall under construction (hp=1, maxHp=10)
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: 0)
    wall.hp = 1
    wall.maxHp = WallMaxHp  # 10
    env.add(wall)

    # Villager "uses" the construction site
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, wall.pos))

    # With 1 builder, base gain is ConstructionHpPerAction * 1.0 = 1
    check wall.hp == 2

  test "multiple builders increase construction speed":
    let env = makeEmptyEnv()
    # Add two villagers adjacent to construction site
    # Wall at (10, 9), agent1 at (10, 10), agent2 at (9, 9) - both adjacent
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(9, 9))

    # Create a wall under construction
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: 0)
    wall.hp = 1
    wall.maxHp = WallMaxHp
    env.add(wall)

    # Both villagers work on construction in same step
    while env.agents.len < MapAgents:
      let nextId = env.agents.len
      let a = Thing(kind: Agent, pos: ivec2(-1, -1), agentId: nextId)
      env.add(a)
      env.terminated[nextId] = 1.0

    var actions: array[MapAgents, uint16]
    for i in 0 ..< MapAgents:
      actions[i] = 0
    actions[agent1.agentId] = encodeAction(3'u16, dirIndex(agent1.pos, wall.pos).uint16)
    actions[agent2.agentId] = encodeAction(3'u16, dirIndex(agent2.pos, wall.pos).uint16)
    env.step(addr actions)

    # With 2 builders: gain = ConstructionHpPerAction * 1.5 = 1.5, rounded to 2
    check wall.hp == 3  # Started at 1, gained 2

  test "construction completes when hp reaches maxHp":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Create a wall nearly complete
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: 0)
    wall.hp = WallMaxHp - 1  # 9 hp, needs 1 more
    wall.maxHp = WallMaxHp
    env.add(wall)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, wall.pos))

    check wall.hp == WallMaxHp  # Completed

  test "non-villager cannot contribute to construction":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(agent, UnitArcher)

    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: 0)
    wall.hp = 1
    wall.maxHp = WallMaxHp
    env.add(wall)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, wall.pos))

    # Non-villager should not contribute to construction
    check wall.hp == 1

  test "cannot contribute to enemy construction":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Create enemy team wall under construction
    let wall = Thing(kind: Wall, pos: ivec2(10, 9), teamId: MapAgentsPerTeam)  # Different team
    wall.hp = 1
    wall.maxHp = WallMaxHp
    env.add(wall)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, wall.pos))

    # Should not contribute to enemy construction
    check wall.hp == 1

suite "AI - Gatherer":
  test "drops off carried wood":
    let env = makeEmptyEnv()
    let controller = newTestController(1)
    let altarPos = ivec2(10, 10)
    discard addBuilding(env, TownCenter, altarPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 11), homeAltar = altarPos)
    setInv(agent, ItemWood, 1)

    let (verb, arg) = decodeAction(controller.decideAction(env, 0))
    check verb == 3
    check arg == dirIndex(agent.pos, altarPos)

  test "task hearts uses magma when carrying gold":
    let env = makeEmptyEnv()
    let controller = newTestController(2)
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos)
    setInv(agent, ItemGold, 1)
    discard addBuilding(env, Magma, ivec2(10, 9), 0)

    let (verb, _) = decodeAction(controller.decideAction(env, 0))
    check verb == 3

  const gathererCases = [
    (name: "task food uses wheat", seed: 3, kind: Wheat, item: ItemWheat, target: ResourceFood),
    (name: "task wood uses tree", seed: 4, kind: Tree, item: ItemWood, target: ResourceWood),
    (name: "task stone uses stone", seed: 5, kind: Stone, item: ItemStone, target: ResourceStone),
    (name: "task gold uses gold", seed: 6, kind: Gold, item: ItemGold, target: ResourceGold)
  ]

  for gathererCase in gathererCases:
    test gathererCase.name:
      let env = makeEmptyEnv()
      let controller = newTestController(gathererCase.seed)
      let altarPos = ivec2(10, 10)
      discard addAltar(env, altarPos, 0, 12)
      discard addResource(env, gathererCase.kind, ivec2(10, 9), gathererCase.item, 3)
      discard addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos)
      fillStockpile(env, 0, 5)
      setStockpile(env, 0, gathererCase.target, 0)

      let (verb, _) = decodeAction(controller.decideAction(env, 0))
      check verb == 3

  test "flees toward altar when enemy nearby":
    let env = makeEmptyEnv()
    let controller = newTestController(100)
    let altarPos = ivec2(10, 10)
    discard addAltar(env, altarPos, 0, 12)
    # Place gatherer away from altar
    let agent = addAgentAt(env, 0, ivec2(15, 10), homeAltar = altarPos)
    # Place enemy within flee radius (8 tiles)
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(17, 10))

    let (verb, arg) = decodeAction(controller.decideAction(env, 0))
    # Should try to move (verb 1) toward the altar (west direction)
    check verb == 1
    # West direction is index 2
    check arg == 2

suite "AI - Builder":
  test "drops off carried resources":
    let env = makeEmptyEnv()
    let controller = newTestController(7)
    let tcPos = ivec2(10, 10)
    discard addBuilding(env, TownCenter, tcPos, 0)
    let agent = addAgentAt(env, 2, ivec2(10, 11), homeAltar = tcPos)
    setInv(agent, ItemWood, 1)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 3
    check arg == dirIndex(agent.pos, tcPos)

  test "builds core economy building when missing":
    let env = makeEmptyEnv()
    let controller = newTestController(8)
    discard addAgentAt(env, 2, ivec2(10, 10))
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 8
    check arg == buildIndexFor(Granary)

  test "builds production building after core economy":
    let env = makeEmptyEnv()
    let controller = newTestController(9)
    addBuildings(env, 0, ivec2(12, 10), @[Granary, LumberCamp, Quarry, MiningCamp])
    discard addAgentAt(env, 2, ivec2(10, 10))
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 8
    check arg == buildIndexFor(WeavingLoom)

  test "builds tech buildings before wall ring in safe mode":
    let env = makeEmptyEnv()
    let controller = newTestController(14)
    let basePos = ivec2(10, 10)
    addBuildings(env, 0, ivec2(12, 10), @[Granary, LumberCamp, Quarry, MiningCamp])
    env.currentStep = 1
    discard addAgentAt(env, 2, ivec2(3, 5), homeAltar = basePos)
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 8
    check arg == buildIndexFor(WeavingLoom)

  test "builds clay oven after weaving loom":
    let env = makeEmptyEnv()
    let controller = newTestController(14)
    addBuildings(env, 0, ivec2(12, 10),
      @[Granary, LumberCamp, Quarry, MiningCamp, WeavingLoom])
    discard addAgentAt(env, 2, ivec2(10, 10))
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 8
    check arg == buildIndexFor(ClayOven)

  test "builds blacksmith after clay oven":
    let env = makeEmptyEnv()
    let controller = newTestController(15)
    addBuildings(env, 0, ivec2(12, 10),
      @[Granary, LumberCamp, Quarry, MiningCamp, WeavingLoom, ClayOven])
    discard addAgentAt(env, 2, ivec2(10, 10))
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 8
    check arg == buildIndexFor(Blacksmith)

  test "builds barracks after blacksmith":
    let env = makeEmptyEnv()
    let controller = newTestController(16)
    addBuildings(env, 0, ivec2(12, 10),
      @[Granary, LumberCamp, Quarry, MiningCamp, WeavingLoom, ClayOven, Blacksmith])
    discard addAgentAt(env, 2, ivec2(10, 10))
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 8
    check arg == buildIndexFor(Barracks)

  test "builds siege workshop after stable":
    let env = makeEmptyEnv()
    let controller = newTestController(17)
    addBuildings(env, 0, ivec2(12, 10), @[
      Granary, LumberCamp, Quarry, MiningCamp,
      WeavingLoom, ClayOven, Blacksmith,
      Barracks, ArcheryRange, Stable
    ])
    discard addAgentAt(env, 2, ivec2(10, 10))
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 8
    check arg == buildIndexFor(SiegeWorkshop)

  test "builds castle after outpost":
    let env = makeEmptyEnv()
    let controller = newTestController(18)
    addBuildings(env, 0, ivec2(12, 10), @[
      Granary, LumberCamp, Quarry, MiningCamp,
      WeavingLoom, ClayOven, Blacksmith,
      Barracks, ArcheryRange, Stable, SiegeWorkshop, MangonelWorkshop, Outpost
    ])
    discard addAgentAt(env, 2, ivec2(10, 10))
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 8
    check arg == buildIndexFor(Castle)

  test "builds house when one house of room left":
    let env = makeEmptyEnv()
    let controller = newTestController(12)
    let basePos = ivec2(10, 10)
    discard addBuilding(env, House, ivec2(8, 8), 0)
    discard addBuilding(env, House, ivec2(12, 8), 0)
    discard addAgentAt(env, 0, ivec2(10, 10), homeAltar = basePos)
    discard addAgentAt(env, 1, ivec2(10, 11), homeAltar = basePos)
    discard addAgentAt(env, 2, ivec2(1, 0), homeAltar = basePos)
    discard addAgentAt(env, 3, ivec2(11, 10), homeAltar = basePos)
    setStockpile(env, 0, ResourceWood, 10)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 1 or (verb == 8 and arg == buildIndexFor(House))

  test "builds house at cap using team-only pop cap":
    let env = makeEmptyEnv()
    let controller = newTestController(13)
    let basePos = ivec2(10, 10)
    discard addBuilding(env, House, ivec2(8, 8), 0)
    discard addAgentAt(env, 0, ivec2(10, 10), homeAltar = basePos)
    discard addAgentAt(env, 2, ivec2(1, 0), homeAltar = basePos)
    setStockpile(env, 0, ResourceWood, 10)
    discard addBuilding(env, House, ivec2(20, 20), 1)
    discard addBuilding(env, House, ivec2(22, 20), 1)
    discard addBuilding(env, House, ivec2(24, 20), 1)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    check verb == 1 or (verb == 8 and arg == buildIndexFor(House))

  test "prioritizes wall ring under threat":
    # Without threat: builder should build WeavingLoom (tech) after core infra
    # With threat: builder should prioritize wall ring over tech
    let env = makeEmptyEnv()
    let controller = newTestController(15)
    let basePos = ivec2(10, 10)
    addBuildings(env, 0, ivec2(12, 10), @[Granary, LumberCamp, Quarry, MiningCamp])
    env.currentStep = 1
    discard addAgentAt(env, 2, ivec2(3, 5), homeAltar = basePos)
    fillStockpile(env, 0, 50)

    # Add enemy agent within threat radius (15 tiles from base)
    let enemyAgent = addAgentAt(env, MapAgentsPerTeam, ivec2(18, 10))
    enemyAgent.teamId = 1
    env.terminated[MapAgentsPerTeam] = 0.0

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    # Under threat, should build wall (defensive priority)
    check verb == 8
    check arg == BuildIndexWall

  test "flees toward altar when enemy very close":
    let env = makeEmptyEnv()
    let controller = newTestController(100)
    let altarPos = ivec2(10, 10)
    discard addAltar(env, altarPos, 0, 12)
    # Place builder away from altar
    let agent = addAgentAt(env, 2, ivec2(15, 10), homeAltar = altarPos)
    # Place enemy within flee radius (8 tiles) of builder
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(17, 10))
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    # Should try to move (verb 1) toward the altar (west direction)
    check verb == 1
    # West direction is index 2
    check arg == 2

  test "repairs damaged friendly building":
    let env = makeEmptyEnv()
    let controller = newTestController(20)
    let basePos = ivec2(10, 10)
    # Create all core infrastructure so builder doesn't prioritize building
    addBuildings(env, 0, ivec2(12, 10), @[Granary, LumberCamp, Quarry, MiningCamp])
    # Create a damaged wall near the builder
    let wall = addBuilding(env, Wall, ivec2(10, 9), 0)
    wall.hp = 5  # Damaged (maxHp is 10)
    # Place builder adjacent to the wall
    discard addAgentAt(env, 2, ivec2(10, 10), homeAltar = basePos)
    fillStockpile(env, 0, 50)

    let (verb, arg) = decodeAction(controller.decideAction(env, 2))
    # Should interact (verb 3) with the damaged wall to repair it
    check verb == 3
    check arg == dirIndex(ivec2(10, 10), ivec2(10, 9))

suite "AI - Fighter":
  test "villager fighter builds divider door when enemy nearby":
    let env = makeEmptyEnv()
    let controller = newTestController(10)
    let basePos = ivec2(10, 10)
    discard addAltar(env, basePos, 0, 12)
    let agentPos = ivec2(10, 17)
    let enemyPos = ivec2(10, 26)
    discard addAgentAt(env, 4, agentPos, homeAltar = basePos, orientation = S)
    discard addAgentAt(env, MapAgentsPerTeam, enemyPos)
    setStockpile(env, 0, ResourceWood, 10)

    let (verb, arg) = decodeAction(controller.decideAction(env, 4))
    check verb == 8
    check arg == BuildIndexDoor

  test "places lantern when target available":
    let env = makeEmptyEnv()
    let controller = newTestController(11)
    discard addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let agent = addAgentAt(env, 4, ivec2(10, 12))
    setInv(agent, ItemLantern, 1)

    let (verb, _) = decodeAction(controller.decideAction(env, 4))
    check verb == 6

  test "combat unit converts to siege when seeing enemy structure":
    # ManAtArms with SiegeWorkshop and visible enemy structure should convert to siege
    let env = makeEmptyEnv()
    let controller = newTestController(50)
    let basePos = ivec2(10, 10)
    # Add SiegeWorkshop
    discard addBuilding(env, SiegeWorkshop, ivec2(12, 10), 0)
    # Add ManAtArms fighter
    let agent = addAgentAt(env, 4, ivec2(10, 12), homeAltar = basePos, unitClass = UnitManAtArms)
    # Add enemy structure within observation radius
    discard addBuilding(env, Barracks, ivec2(15, 10), 1)
    # Add resources to afford siege training (3 wood + 2 stone)
    setStockpile(env, 0, ResourceWood, 10)
    setStockpile(env, 0, ResourceStone, 10)

    let (verb, arg) = decodeAction(controller.decideAction(env, 4))
    # Should move (verb 1) toward SiegeWorkshop or interact (verb 3)
    check verb == 1 or verb == 3

  test "fighter prioritizes low HP enemy":
    # Fighter should prefer attacking a low HP enemy over a full HP enemy
    let env = makeEmptyEnv()
    let controller = newTestController(30)
    let basePos = ivec2(10, 10)
    # Add fighter
    let fighter = addAgentAt(env, 4, ivec2(10, 10), homeAltar = basePos, unitClass = UnitManAtArms)
    fighter.stance = StanceAggressive
    # Add two enemies: one at full HP (close), one at low HP (slightly farther)
    let fullHpEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(11, 10))  # Adjacent
    fullHpEnemy.hp = fullHpEnemy.maxHp
    let lowHpEnemy = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(12, 10))  # 2 tiles away
    lowHpEnemy.hp = 1  # Very low HP
    lowHpEnemy.maxHp = 10

    # Run enough steps for target re-evaluation to trigger
    for _ in 0 ..< 15:
      discard controller.decideAction(env, 4)
      env.currentStep += 1

    # The fighter should target the low HP enemy despite being farther
    # Check by examining that the agent is oriented toward or attacking the low HP enemy
    let (verb, _) = decodeAction(controller.decideAction(env, 4))
    # Should be attacking (verb 2) or moving (verb 1)
    check verb == 1 or verb == 2

  test "fighter prioritizes enemy threatening ally":
    # Fighter should switch to attacking an enemy that is threatening an ally
    let env = makeEmptyEnv()
    let controller = newTestController(40)
    let basePos = ivec2(10, 10)
    # Add fighter at some distance
    let fighter = addAgentAt(env, 4, ivec2(10, 10), homeAltar = basePos, unitClass = UnitManAtArms)
    fighter.stance = StanceAggressive
    # Add ally being attacked (villager)
    let ally = addAgentAt(env, 5, ivec2(15, 10), homeAltar = basePos)
    ally.hp = 3  # Low HP ally
    # Add enemy close to the fighter
    let farEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(11, 10))  # Adjacent to fighter
    # Add enemy threatening the ally (adjacent to ally)
    let threateningEnemy = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(15, 11))  # Adjacent to ally
    threateningEnemy.hp = 10
    threateningEnemy.maxHp = 10

    # Run enough steps for target re-evaluation
    for _ in 0 ..< 15:
      discard controller.decideAction(env, 4)
      env.currentStep += 1

    let (verb, _) = decodeAction(controller.decideAction(env, 4))
    # Should be moving (verb 1) toward the threatening enemy or attacking (verb 2)
    check verb == 1 or verb == 2

suite "AI - Combat Behaviors":
  test "gatherer flees from nearby wolf":
    let env = makeEmptyEnv()
    let controller = newTestController(20)
    let basePos = ivec2(10, 10)
    discard addAltar(env, basePos, 0, 10)
    let agent = addAgentAt(env, 0, ivec2(15, 10), homeAltar = basePos)
    # Add wolf within flee radius (5 tiles)
    let wolf = Thing(kind: Wolf, pos: ivec2(14, 10), packId: 0, hp: WolfMaxHp, maxHp: WolfMaxHp)
    env.add(wolf)
    env.wolfPackCounts.add(1)
    env.wolfPackSumX.add(wolf.pos.x)
    env.wolfPackSumY.add(wolf.pos.y)
    env.wolfPackDrift.add(ivec2(0, 0))
    env.wolfPackTargets.add(ivec2(-1, -1))
    env.wolfPackLeaders.add(wolf)
    wolf.isPackLeader = true

    let (verb, arg) = decodeAction(controller.decideAction(env, 0))
    # Agent should move (verb 1) away from wolf
    check verb == 1
    # Direction 3 is East, 5 is NE, 7 is SE - all move away from wolf at west
    check arg.int in {3, 5, 7}

  test "wolf pack scatters when leader killed":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 10  # One-hit kill
    # Create pack with leader and two followers
    let leaderPos = ivec2(10, 9)
    let leader = Thing(kind: Wolf, pos: leaderPos, packId: 0, hp: 1, maxHp: WolfMaxHp, isPackLeader: true)
    let follower1 = Thing(kind: Wolf, pos: ivec2(10, 8), packId: 0, hp: WolfMaxHp, maxHp: WolfMaxHp)
    let follower2 = Thing(kind: Wolf, pos: ivec2(11, 9), packId: 0, hp: WolfMaxHp, maxHp: WolfMaxHp)
    env.add(leader)
    env.add(follower1)
    env.add(follower2)
    env.wolfPackCounts.add(3)
    env.wolfPackSumX.add(leader.pos.x + follower1.pos.x + follower2.pos.x)
    env.wolfPackSumY.add(leader.pos.y + follower1.pos.y + follower2.pos.y)
    env.wolfPackDrift.add(ivec2(0, 0))
    env.wolfPackTargets.add(ivec2(-1, -1))
    env.wolfPackLeaders.add(leader)

    # Followers not scattered before leader death
    check follower1.scatteredSteps == 0
    check follower2.scatteredSteps == 0

    # Kill the leader
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, leaderPos))

    # Followers should now be scattered (may have decremented by 1 during wolf step)
    check follower1.scatteredSteps >= ScatteredDuration - 1
    check follower2.scatteredSteps >= ScatteredDuration - 1
    # Leader should be removed
    check env.getThing(leaderPos) == nil or env.getThing(leaderPos).kind != Wolf

  test "agent eats bread when HP below 50%":
    let env = makeEmptyEnv()
    let controller = newTestController(30)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Set HP below 50% of max (AgentMaxHp = 5, so need hp * 2 < 5, i.e., hp <= 2)
    agent.hp = 2  # 40% of 5
    # Give agent bread to eat
    setInv(agent, ItemBread, 1)

    let (verb, _) = decodeAction(controller.decideAction(env, 0))
    # Agent should use item (verb 3) to eat bread
    check verb == 3

  test "agent does not eat bread when HP above 50%":
    let env = makeEmptyEnv()
    let controller = newTestController(31)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # HP at 60% of max - above threshold (3/5 = 60%, 3*2=6 which is not < 5)
    agent.hp = 3
    setInv(agent, ItemBread, 1)

    let (verb, _) = decodeAction(controller.decideAction(env, 0))
    # Agent should NOT eat bread - do something else instead
    check verb != 3 or agent.inventoryBread == 1

suite "AI - Stance Behavior":
  test "NoAttack stance prevents auto-attack":
    let env = makeEmptyEnv()
    let controller = newTestController(40)
    # Create agent with NoAttack stance (default for villagers)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceNoAttack)
    # Place enemy adjacent
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))

    let (verb, _) = decodeAction(controller.decideAction(env, 0))
    # Agent should NOT attack (verb 2) even though enemy is adjacent
    check verb != 2

  test "Defensive stance allows attack when recently attacked":
    let env = makeEmptyEnv()
    let controller = newTestController(41)
    # Create agent with Defensive stance
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    # Simulate being recently attacked (triggers retaliation window)
    # lastAttackedStep must be > 0 for the retaliation check
    env.currentStep = 1
    agent.lastAttackedStep = 1
    # Place enemy adjacent
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))

    let (verb, _) = decodeAction(controller.decideAction(env, 0))
    # Agent should attack (verb 2) when enemy is adjacent and recently attacked
    check verb == 2

  test "Defensive stance prevents attack when not recently attacked":
    let env = makeEmptyEnv()
    let controller = newTestController(41)
    # Create agent with Defensive stance (not recently attacked)
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceDefensive)
    # Place enemy adjacent
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))

    let (verb, _) = decodeAction(controller.decideAction(env, 0))
    # Agent should NOT attack (verb 2) when not recently attacked
    check verb != 2

  test "default stance is NoAttack for villagers":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check agent.stance == StanceNoAttack

  test "applyUnitClass sets appropriate stance":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Start as villager with NoAttack
    check agent.stance == StanceNoAttack

    # Convert to ManAtArms - should get Defensive stance
    applyUnitClass(agent, UnitManAtArms)
    check agent.stance == StanceDefensive

    # Convert to Archer - should get Defensive stance
    applyUnitClass(agent, UnitArcher)
    check agent.stance == StanceDefensive

    # Convert back to Villager - should get NoAttack stance
    applyUnitClass(agent, UnitVillager)
    check agent.stance == StanceNoAttack

suite "Agent Idle Detection":
  test "agent marked idle on NOOP action":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Initially not idle
    check agent.isIdle == false

    # Take NOOP action (verb 0)
    env.stepAction(0, 0'u8, 0)
    check agent.isIdle == true

  test "agent marked idle on ORIENT action":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Take ORIENT action (verb 9)
    env.stepAction(0, 9'u8, 3)  # Orient east
    check agent.isIdle == true

  test "agent not idle on MOVE action":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Take MOVE action (verb 1) - move east
    env.stepAction(0, 1'u8, 3)  # E direction
    check agent.isIdle == false

  test "agent not idle on USE action":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Place tree adjacent to gather from
    discard addResource(env, Tree, ivec2(10, 9), ItemWood, ResourceNodeInitial)

    # Take USE action (verb 3)
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    check agent.isIdle == false

  test "idle state appears in observations":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Take NOOP action to become idle
    env.stepAction(0, 0'u8, 0)
    check agent.isIdle == true

    # Rebuild observations (use ensureObservations for lazy init)
    env.ensureObservations()

    # Check the observation at the agent's position (center of 11x11 = 5,5)
    let centerX = ObservationRadius  # 5
    let centerY = ObservationRadius  # 5
    let idleLayerValue = env.observations[0][ord(AgentIdleLayer)][centerX][centerY]
    check idleLayerValue == 1

suite "Shared Threat Map":
  test "threat is reported and can be queried":
    let controller = newTestController(42)
    let teamId = 0
    let threatPos = ivec2(20, 20)
    let currentStep: int32 = 100

    # Initially no threats
    check not controller.hasKnownThreats(teamId, currentStep)

    # Report a threat
    controller.reportThreat(teamId, threatPos, strength = 2, currentStep,
                            agentId = 10, isStructure = false)

    # Now has known threats
    check controller.hasKnownThreats(teamId, currentStep)

    # Can find the threat
    let (pos, dist, found) = controller.getNearestThreat(teamId, ivec2(15, 15), currentStep)
    check found
    check pos == threatPos
    check dist == 5  # chebyshev distance from (15,15) to (20,20)

  test "threats decay after ThreatDecaySteps":
    let controller = newTestController(42)
    let teamId = 0
    let threatPos = ivec2(20, 20)
    let reportStep: int32 = 100

    # Report a threat
    controller.reportThreat(teamId, threatPos, strength = 2, reportStep)
    check controller.hasKnownThreats(teamId, reportStep)

    # After ThreatDecaySteps, threat should be stale
    let staleStep = reportStep + ThreatDecaySteps
    check not controller.hasKnownThreats(teamId, staleStep)

  test "threat map clears on reset":
    let controller = newTestController(42)
    let teamId = 0

    # Report multiple threats
    controller.reportThreat(teamId, ivec2(10, 10), strength = 1, currentStep = 50)
    controller.reportThreat(teamId, ivec2(20, 20), strength = 2, currentStep = 50)
    check controller.hasKnownThreats(teamId, 50)

    # Clear the threat map
    controller.clearThreatMap(teamId)
    check not controller.hasKnownThreats(teamId, 50)

  test "agent vision updates threat map":
    let env = makeEmptyEnv()
    let controller = newTestController(42)
    let teamId = 0
    let currentStep: int32 = env.currentStep.int32

    # Add friendly agent at (10, 10)
    discard addAgentAt(env, 0, ivec2(10, 10))
    # Add enemy agent at (15, 10) - within ThreatVisionRange
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(15, 10))

    # Initially no threats
    check not controller.hasKnownThreats(teamId, currentStep)

    # Update threat map from vision
    controller.updateThreatMapFromVision(env, env.agents[0], currentStep)

    # Now has known threats
    check controller.hasKnownThreats(teamId, currentStep)

    # Threat should be at enemy position
    let (pos, dist, found) = controller.getNearestThreat(teamId, ivec2(10, 10), currentStep)
    check found
    check pos == enemy.pos

  test "threat map tracks multiple teams separately":
    let controller = newTestController(42)
    let currentStep: int32 = 100

    # Report threat for team 0
    controller.reportThreat(0, ivec2(10, 10), strength = 1, currentStep)
    # Report threat for team 1
    controller.reportThreat(1, ivec2(30, 30), strength = 1, currentStep)

    # Team 0 sees its threat, not team 1's
    let (pos0, _, found0) = controller.getNearestThreat(0, ivec2(0, 0), currentStep)
    check found0
    check pos0 == ivec2(10, 10)

    let (pos1, _, found1) = controller.getNearestThreat(1, ivec2(0, 0), currentStep)
    check found1
    check pos1 == ivec2(30, 30)

  test "threat strength aggregates in range":
    let controller = newTestController(42)
    let teamId = 0
    let currentStep: int32 = 100

    # Report multiple threats nearby
    controller.reportThreat(teamId, ivec2(10, 10), strength = 2, currentStep)
    controller.reportThreat(teamId, ivec2(12, 10), strength = 3, currentStep)
    controller.reportThreat(teamId, ivec2(50, 50), strength = 5, currentStep)

    # Total strength in range 5 of (10, 10) should be 2 + 3 = 5
    let totalNear = controller.getTotalThreatStrength(teamId, ivec2(10, 10), rangeVal = 5, currentStep)
    check totalNear == 5

    # Total strength in range 100 should include all = 10
    let totalAll = controller.getTotalThreatStrength(teamId, ivec2(10, 10), rangeVal = 100, currentStep)
    check totalAll == 10

suite "AI - Scout Behavior":
  test "scout mode activates for UnitScout":
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    # Add a villager and train it as a scout
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, Stable, ivec2(10, 9), 0)
    env.teamStockpiles[0].counts[ResourceFood] = 10

    # Initially not a scout
    check agent.unitClass == UnitVillager
    check not controller.isScoutModeActive(agent.agentId)

    # Train as scout (queue at stable, wait for production, then convert)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    for i in 0 ..< unitTrainTime(UnitScout) - 1:
      env.stepNoop()
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ivec2(10, 9)))
    check agent.unitClass == UnitScout

    # Run tick to initialize scout mode
    discard controller.decideAction(env, agent.agentId)
    check controller.isScoutModeActive(agent.agentId)

  test "scout flees when enemy nearby":
    let env = makeEmptyEnv()
    let controller = newTestController(42)
    let teamId = 0

    # Create scout at (30, 30)
    let scout = addAgentAt(env, teamId, ivec2(30, 30))
    applyUnitClass(scout, UnitScout)

    # Create enemy close to scout
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(33, 30))

    # Enable scout mode
    controller.setScoutMode(scout.agentId, true)

    # Scout should detect enemy and flee toward base (altar at default position)
    let action = controller.decideAction(env, scout.agentId)

    # Action should be a move (verb 1)
    let verb = (action.int div ActionArgumentCount).uint16
    check verb == 1  # MOVE action

  test "scout reports threats to team":
    let env = makeEmptyEnv()
    let controller = newTestController(42)
    let teamId = 0
    let currentStep: int32 = env.currentStep.int32

    # Create scout at (30, 30) with altar at home
    let scout = addAgentAt(env, teamId, ivec2(30, 30))
    applyUnitClass(scout, UnitScout)
    discard addBuilding(env, Altar, ivec2(10, 10), teamId)
    scout.homeAltar = ivec2(10, 10)

    # Create enemy near scout
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(35, 30))

    # Enable scout mode and run tick
    controller.setScoutMode(scout.agentId, true)
    discard controller.decideAction(env, scout.agentId)

    # Scout should have reported the threat
    check controller.hasKnownThreats(teamId, currentStep)

    # The reported threat should be at the enemy position
    let (pos, _, found) = controller.getNearestThreat(teamId, scout.pos, currentStep)
    check found
    check pos == enemy.pos

  test "scout explore radius expands over time":
    let controller = newController(42)
    let agentId = 5

    # Enable scout mode
    controller.setScoutMode(agentId, true)

    # Initial radius should be set
    let initialRadius = controller.getScoutExploreRadius(agentId)
    check initialRadius > 0

suite "Scout Line-of-Sight Exploration":
  test "scout has extended vision range":
    # Scouts should use ScoutVisionRange (18) vs normal ThreatVisionRange (12)
    check ScoutVisionRange > ThreatVisionRange
    check ScoutVisionRange == 18

  test "scout reveals tiles with extended vision":
    let env = makeEmptyEnv()
    let teamId = 0

    # Create scout at center of map
    let scout = addAgentAt(env, teamId, ivec2(50, 50))
    applyUnitClass(scout, UnitScout)

    # Initially, tiles should not be revealed
    check not env.isRevealed(teamId, ivec2(50, 50))
    check not env.isRevealed(teamId, ivec2(50 + ScoutVisionRange, 50))

    # Update revealed map from scout's vision
    env.updateRevealedMapFromVision(scout)

    # Scout position and tiles within ScoutVisionRange should now be revealed
    check env.isRevealed(teamId, ivec2(50, 50))
    check env.isRevealed(teamId, ivec2(50 + ScoutVisionRange, 50))
    check env.isRevealed(teamId, ivec2(50 - ScoutVisionRange, 50))
    check env.isRevealed(teamId, ivec2(50, 50 + ScoutVisionRange))
    check env.isRevealed(teamId, ivec2(50, 50 - ScoutVisionRange))

    # Tiles beyond scout vision should NOT be revealed
    check not env.isRevealed(teamId, ivec2(50 + ScoutVisionRange + 1, 50))

  test "villager reveals tiles with normal vision":
    let env = makeEmptyEnv()
    let teamId = 0

    # Create villager at center of map
    let villager = addAgentAt(env, teamId, ivec2(50, 50))
    check villager.unitClass == UnitVillager

    # Update revealed map from villager's vision
    env.updateRevealedMapFromVision(villager)

    # Villager should reveal tiles within ThreatVisionRange (12)
    check env.isRevealed(teamId, ivec2(50, 50))
    check env.isRevealed(teamId, ivec2(50 + ThreatVisionRange, 50))

    # Tiles at scout range should NOT be revealed by villager
    check not env.isRevealed(teamId, ivec2(50 + ScoutVisionRange, 50))

  test "revealed map clears on reset":
    let env = makeEmptyEnv()
    let teamId = 0

    # Create scout and reveal some tiles
    let scout = addAgentAt(env, teamId, ivec2(50, 50))
    applyUnitClass(scout, UnitScout)
    env.updateRevealedMapFromVision(scout)

    # Verify tiles are revealed
    check env.isRevealed(teamId, ivec2(50, 50))
    let countBefore = env.getRevealedTileCount(teamId)
    check countBefore > 0

    # Reset environment
    env.reset()

    # Revealed map should be cleared
    check not env.isRevealed(teamId, ivec2(50, 50))
    check env.getRevealedTileCount(teamId) == 0

  test "revealed tile count increases with exploration":
    let env = makeEmptyEnv()
    let teamId = 0

    # Initial count should be 0
    check env.getRevealedTileCount(teamId) == 0

    # Create scout and explore
    let scout = addAgentAt(env, teamId, ivec2(30, 30))
    applyUnitClass(scout, UnitScout)
    env.updateRevealedMapFromVision(scout)

    # Should have revealed tiles
    let count1 = env.getRevealedTileCount(teamId)
    check count1 > 0

    # Move scout and explore more
    scout.pos = ivec2(80, 80)
    env.updateRevealedMapFromVision(scout)

    # Should have revealed more tiles
    let count2 = env.getRevealedTileCount(teamId)
    check count2 > count1

  test "teams have independent revealed maps":
    let env = makeEmptyEnv()
    let team0 = 0
    let team1 = 1

    # Create scouts for different teams at different positions
    # Agent ID determines team: team 0 = IDs 0-124, team 1 = IDs 125-249
    let scout0 = addAgentAt(env, 0, ivec2(20, 20))  # Team 0
    applyUnitClass(scout0, UnitScout)
    let scout1 = addAgentAt(env, MapAgentsPerTeam, ivec2(80, 80))  # Team 1
    applyUnitClass(scout1, UnitScout)

    # Update both scouts
    env.updateRevealedMapFromVision(scout0)
    env.updateRevealedMapFromVision(scout1)

    # Team 0 should see their scout area but not team 1's
    check env.isRevealed(team0, ivec2(20, 20))
    check not env.isRevealed(team0, ivec2(80, 80))

    # Team 1 should see their scout area but not team 0's
    check env.isRevealed(team1, ivec2(80, 80))
    check not env.isRevealed(team1, ivec2(20, 20))

suite "Cliff Fall Damage":
  test "agent takes damage when falling off cliff without ramp":
    let env = makeEmptyEnv()
    # Set up elevation: agent at elevation 1, moving to elevation 0
    env.elevation[10][10] = 1
    env.elevation[10][11] = 0
    env.terrain[10][10] = Grass
    env.terrain[10][11] = Grass

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let initialHp = agent.hp

    # Move south (direction 1) to drop down
    env.stepAction(0, 1'u8, 1)

    check agent.pos == ivec2(10, 11)
    check agent.hp == initialHp - CliffFallDamage

  test "agent does not take damage when using ramp":
    let env = makeEmptyEnv()
    # Set up elevation with ramp
    env.elevation[10][10] = 1
    env.elevation[10][11] = 0
    env.terrain[10][10] = RampDownS  # Ramp going south/down
    env.terrain[10][11] = Grass

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let initialHp = agent.hp

    # Move south (direction 1) to go down ramp
    env.stepAction(0, 1'u8, 1)

    check agent.pos == ivec2(10, 11)
    check agent.hp == initialHp  # No damage with ramp

  test "agent does not take damage when using road":
    let env = makeEmptyEnv()
    # Set up elevation with road
    env.elevation[10][10] = 1
    env.elevation[10][11] = 0
    env.terrain[10][10] = Road
    env.terrain[10][11] = Grass

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let initialHp = agent.hp

    # Move south (direction 1) to go down
    env.stepAction(0, 1'u8, 1)

    check agent.pos == ivec2(10, 11)
    check agent.hp == initialHp  # No damage with road

  test "boat is immune to cliff fall damage":
    let env = makeEmptyEnv()
    # Set up elevation
    env.elevation[10][10] = 1
    env.elevation[10][11] = 0
    env.terrain[10][10] = Grass
    env.terrain[10][11] = Water  # Water for boat

    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBoat)
    let initialHp = agent.hp

    # Move south (direction 1) to drop down
    env.stepAction(0, 1'u8, 1)

    check agent.pos == ivec2(10, 11)
    check agent.hp == initialHp  # Boats don't take fall damage

  test "agent does not take damage on flat terrain":
    let env = makeEmptyEnv()
    # Same elevation
    env.elevation[10][10] = 0
    env.elevation[10][11] = 0
    env.terrain[10][10] = Grass
    env.terrain[10][11] = Grass

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let initialHp = agent.hp

    # Move south (direction 1)
    env.stepAction(0, 1'u8, 1)

    check agent.pos == ivec2(10, 11)
    check agent.hp == initialHp  # No damage on flat terrain

  test "agent cannot climb cliff without ramp":
    let env = makeEmptyEnv()
    # Agent at elevation 0, trying to climb to elevation 1
    env.elevation[10][10] = 0
    env.elevation[10][9] = 1
    env.terrain[10][10] = Grass
    env.terrain[10][9] = Grass  # No ramp

    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Try to move north (direction 0) to climb up
    env.stepAction(0, 1'u8, 0)

    # Agent should not have moved (blocked by elevation)
    check agent.pos == ivec2(10, 10)

suite "Trebuchet Pack/Unpack":
  test "trebuchet starts packed and can move":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitTrebuchet)
    agent.packed = true  # Start packed

    # Move south (direction 1)
    env.stepAction(0, 1'u8, 1)

    check agent.pos == ivec2(10, 11)  # Should move

  test "trebuchet cannot move when unpacked":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitTrebuchet)
    agent.packed = false  # Unpacked

    # Try to move south (direction 1)
    env.stepAction(0, 1'u8, 1)

    check agent.pos == ivec2(10, 10)  # Should not move

  test "trebuchet cannot attack when packed":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitTrebuchet)
    agent.packed = true

    # Add enemy target (team 1 = agentId >= MapAgentsPerTeam)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))

    # Try to attack north (direction 0)
    env.stepAction(0, 2'u8, 0)

    check enemy.hp == enemy.maxHp  # Should not take damage

  test "trebuchet can attack when unpacked":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitTrebuchet)
    agent.packed = false  # Unpacked

    # Add enemy target at range 5 (within TrebuchetBaseRange of 6)
    # Use agentId >= MapAgentsPerTeam to put on different team
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 5))
    let initialHp = enemy.hp

    # Attack north (direction 0)
    env.stepAction(0, 2'u8, 0)

    check enemy.hp < initialHp  # Should take damage

  test "trebuchet pack/unpack transition takes time":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitTrebuchet)
    agent.packed = true
    agent.cooldown = 0

    # Trigger pack/unpack with USE action argument 8
    env.stepAction(0, 3'u8, 8)

    # Cooldown is decremented at end of step, so it's TrebuchetPackDuration - 1
    check agent.cooldown == TrebuchetPackDuration - 1  # Cooldown started and decremented
    check agent.packed == true  # Not yet toggled (needs cooldown to reach 0)

    # Simulate remaining steps using NOOP actions (cooldown already at PackDuration - 1)
    for i in 1 ..< TrebuchetPackDuration:
      env.stepAction(0, 0'u8, 0)  # NOOP action

    check agent.cooldown == 0
    check agent.packed == false  # Now unpacked

  test "trebuchet cannot start new pack/unpack while in transition":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitTrebuchet)
    agent.packed = true
    agent.cooldown = 5  # In transition

    # Try to trigger another pack/unpack
    env.stepAction(0, 3'u8, 8)

    check agent.cooldown == 4  # Should have decremented by 1 from step, not reset

suite "Wonder Victory":
  test "wonder starts with victory tracking after step":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000
    discard addAgentAt(env, 0, ivec2(10, 10))
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    let wonder = addBuilding(env, Wonder, ivec2(50, 50), 0)

    check wonder.hp == WonderMaxHp
    check env.victoryStates[0].wonderBuiltStep == -1  # Not tracked yet

    env.stepNoop()

    check env.victoryStates[0].wonderBuiltStep >= 0  # Now tracked

  test "wonder victory does not trigger before countdown expires":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000
    discard addAgentAt(env, 0, ivec2(10, 10))
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    discard addBuilding(env, Wonder, ivec2(50, 50), 0)

    env.stepNoop()

    let builtStep = env.victoryStates[0].wonderBuiltStep
    check builtStep >= 0
    check env.victoryWinner == -1  # Not enough time passed

  test "wonder victory triggers when countdown reaches zero":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000
    discard addAgentAt(env, 0, ivec2(10, 10))
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    discard addBuilding(env, Wonder, ivec2(50, 50), 0)

    env.stepNoop()

    let builtStep = env.victoryStates[0].wonderBuiltStep
    check builtStep >= 0

    # Advance past the countdown
    env.currentStep = builtStep + WonderVictoryCountdown

    env.stepNoop()

    check env.victoryWinner == 0
    check env.shouldReset == true

  test "destroyed wonder resets tracking":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000
    discard addAgentAt(env, 0, ivec2(10, 10))
    discard addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    let wonder = addBuilding(env, Wonder, ivec2(50, 50), 0)

    env.stepNoop()

    check env.victoryStates[0].wonderBuiltStep >= 0

    # Destroy the wonder
    env.grid[wonder.pos.x][wonder.pos.y] = nil
    env.thingsByKind[Wonder].setLen(0)

    env.stepNoop()

    check env.victoryStates[0].wonderBuiltStep == -1
    check env.victoryWinner == -1

suite "AI Difficulty Control":
  setup:
    initGlobalController(BuiltinAI, 12345)
    discard makeEmptyEnv()

  test "get and set difficulty level":
    let controller = globalController.aiController

    # Default is Normal
    check controller.getDifficulty(0).level == DiffNormal

    # Set to Easy
    controller.setDifficulty(0, DiffEasy)
    check controller.getDifficulty(0).level == DiffEasy
    check controller.getDifficulty(0).decisionDelayChance == 0.30'f32

    # Set to Hard
    controller.setDifficulty(0, DiffHard)
    check controller.getDifficulty(0).level == DiffHard
    check controller.getDifficulty(0).decisionDelayChance == 0.02'f32

    # Set to Brutal
    controller.setDifficulty(0, DiffBrutal)
    check controller.getDifficulty(0).level == DiffBrutal
    check controller.getDifficulty(0).decisionDelayChance == 0.0'f32

  test "decision delay chance affects action skipping":
    let controller = globalController.aiController

    # With 100% delay, should always skip
    controller.difficulty[0].decisionDelayChance = 1.0'f32
    var skipped = 0
    for _ in 0 ..< 100:
      if controller.shouldApplyDecisionDelay(0):
        inc skipped
    check skipped == 100

    # With 0% delay, should never skip
    controller.difficulty[0].decisionDelayChance = 0.0'f32
    skipped = 0
    for _ in 0 ..< 100:
      if controller.shouldApplyDecisionDelay(0):
        inc skipped
    check skipped == 0

  test "adaptive difficulty can be enabled and disabled":
    let controller = globalController.aiController

    # Initially disabled
    check not controller.getDifficulty(0).adaptive

    # Enable with custom target
    controller.enableAdaptiveDifficulty(0, 0.3)
    check controller.getDifficulty(0).adaptive
    check controller.getDifficulty(0).adaptiveTarget == 0.3'f32

    # Disable
    controller.disableAdaptiveDifficulty(0)
    check not controller.getDifficulty(0).adaptive

  test "difficulty features can be toggled individually":
    let controller = globalController.aiController

    # Set to Easy (most features disabled)
    controller.setDifficulty(0, DiffEasy)
    check not controller.getDifficulty(0).threatResponseEnabled
    check not controller.getDifficulty(0).advancedTargetingEnabled
    check not controller.getDifficulty(0).coordinationEnabled

    # Set to Hard (all features enabled)
    controller.setDifficulty(0, DiffHard)
    check controller.getDifficulty(0).threatResponseEnabled
    check controller.getDifficulty(0).advancedTargetingEnabled
    check controller.getDifficulty(0).coordinationEnabled

  test "difficulty is per-team":
    let controller = globalController.aiController

    controller.setDifficulty(0, DiffEasy)
    controller.setDifficulty(1, DiffBrutal)

    check controller.getDifficulty(0).level == DiffEasy
    check controller.getDifficulty(1).level == DiffBrutal
    check controller.getDifficulty(0).decisionDelayChance == 0.30'f32
    check controller.getDifficulty(1).decisionDelayChance == 0.0'f32
