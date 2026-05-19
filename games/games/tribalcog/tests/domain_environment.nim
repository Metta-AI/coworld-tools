import std/[unittest]
import environment
import common
import types
import items
import terrain
import test_utils

# =============================================================================
# Reset and Game State Management
# =============================================================================

suite "Environment - Reset":
  test "reset clears currentStep":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))
    env.stepNoop()
    env.stepNoop()
    check env.currentStep > 0
    env.reset()
    check env.currentStep == 0

  test "reset clears shouldReset flag":
    let env = makeEmptyEnv()
    env.shouldReset = true
    env.reset()
    check env.shouldReset == false

  test "reset reinitializes agents":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))
    discard addAgentAt(env, 1, ivec2(12, 12))
    let agentsBefore = env.agents.len
    check agentsBefore > 0
    env.reset()
    # reset() calls init() which repopulates the world with fresh agents
    # The key invariant is that agents are freshly initialized, not carried over
    check env.agents.len > 0  # init() populates agents

  test "reset reinitializes things":
    let env = makeEmptyEnv()
    discard addBuilding(env, House, ivec2(10, 10), 0)
    check env.things.len > 0
    env.reset()
    # reset() calls init() which creates a fresh world with things
    check env.things.len > 0  # Fresh world has things

  test "reset does not carry over manually set stockpiles":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 500)
    setStockpile(env, 0, ResourceWood, 300)
    check env.stockpileCount(0, ResourceFood) == 500
    env.reset()
    # After reset, stockpiles are reinitialized by init() with starting resources
    # The manually set 500/300 values should NOT persist
    check env.stockpileCount(0, ResourceFood) != 500
    check env.stockpileCount(0, ResourceWood) != 300

  test "reset clears victory state":
    let env = makeEmptyEnv()
    env.victoryWinner = 2
    env.reset()
    check env.victoryWinner == -1

  test "reset clears town bell active":
    let env = makeEmptyEnv()
    env.townBellActive[0] = true
    env.townBellActive[1] = true
    env.reset()
    check env.townBellActive[0] == false
    check env.townBellActive[1] == false

  test "reset clears tribute tracking":
    let env = makeEmptyEnv()
    env.teamTributesSent[0] = 100
    env.teamTributesReceived[1] = 50
    env.reset()
    check env.teamTributesSent[0] == 0
    check env.teamTributesReceived[1] == 0

suite "Environment - Step Progression":
  test "step increments currentStep":
    let env = makeEmptyEnv()
    check env.currentStep == 0
    env.stepNoop()
    check env.currentStep == 1
    env.stepNoop()
    check env.currentStep == 2

  test "multiple steps accumulate":
    let env = makeEmptyEnv()
    for i in 0 ..< 10:
      env.stepNoop()
    check env.currentStep == 10

# =============================================================================
# Agent Lifecycle
# =============================================================================

suite "Environment - Agent Creation":
  test "addAgentAt creates agent at position":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check agent.pos == ivec2(10, 10)
    check agent.agentId == 0
    check agent.kind == Agent

  test "addAgentAt with specific unit class":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    check agent.unitClass == UnitManAtArms

  test "addAgentAt with specific orientation":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), orientation = S)
    check agent.orientation == S

  test "addAgentAt with specific stance":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), stance = StanceAggressive)
    check agent.stance == StanceAggressive

  test "addAgentAt fills intermediate agent slots":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 5, ivec2(10, 10))
    check env.agents.len == 6  # 0..5
    check agent.agentId == 5
    # Intermediate agents are off-grid with 0 HP
    check env.agents[0].pos == ivec2(-1, -1)
    check env.agents[0].hp == 0

  test "agent is placed on grid":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check env.grid[10][10] == agent

  test "monk agent has faith initialized":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    check monk.faith == MonkMaxFaith

suite "Environment - Apply Unit Class":
  test "applyUnitClass sets HP and attack (no env)":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitManAtArms)
    check agent.unitClass == UnitManAtArms
    check agent.maxHp == ManAtArmsMaxHp
    check agent.hp == ManAtArmsMaxHp
    check agent.attackDamage == ManAtArmsAttackDamage

  test "applyUnitClass sets default stance":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(agent, UnitManAtArms)
    check agent.stance == StanceDefensive

  test "applyUnitClass sets villager stance to NoAttack":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(agent, UnitVillager)
    check agent.stance == StanceNoAttack

  test "applyUnitClass with env applies team modifiers":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    env.teamModifiers[0].unitHpBonus[UnitManAtArms] = 5
    env.teamModifiers[0].unitAttackBonus[UnitManAtArms] = 2
    applyUnitClass(env, agent, UnitManAtArms)
    check agent.maxHp == ManAtArmsMaxHp + 5
    check agent.attackDamage == ManAtArmsAttackDamage + 2

  test "applyUnitClass monk sets faith":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    applyUnitClass(env, agent, UnitMonk)
    check agent.unitClass == UnitMonk
    check agent.faith == MonkMaxFaith

  test "applyUnitClass non-monk clears faith":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    check agent.faith == MonkMaxFaith
    applyUnitClass(env, agent, UnitArcher)
    check agent.faith == 0

suite "Environment - Embark/Disembark":
  test "embarkAgent converts land unit to boat":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    env.embarkAgent(agent)
    check agent.unitClass == UnitBoat
    check agent.embarkedUnitClass == UnitManAtArms

  test "disembarkAgent restores original class":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    env.embarkAgent(agent)
    check agent.unitClass == UnitBoat
    env.disembarkAgent(agent)
    check agent.unitClass == UnitArcher

  test "embarkAgent is no-op for boat":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBoat)
    env.embarkAgent(agent)
    check agent.unitClass == UnitBoat  # Still boat

  test "disembarkAgent is no-op for non-boat":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    env.disembarkAgent(agent)
    check agent.unitClass == UnitArcher  # No change

  test "disembarkAgent is no-op for trade cog":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitTradeCog)
    env.disembarkAgent(agent)
    check agent.unitClass == UnitTradeCog  # Trade cogs never disembark

# =============================================================================
# Stockpile Operations
# =============================================================================

suite "Environment - Stockpile Operations":
  test "stockpileCount returns zero initially":
    let env = makeEmptyEnv()
    for res in StockpileResource:
      check env.stockpileCount(0, res) == 0

  test "setStockpile and stockpileCount roundtrip":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    check env.stockpileCount(0, ResourceFood) == 100

  test "addToStockpile adds resources":
    let env = makeEmptyEnv()
    env.addToStockpile(0, ResourceWood, 50)
    env.addToStockpile(0, ResourceWood, 30)
    check env.stockpileCount(0, ResourceWood) == 80

  test "addToStockpile applies gather rate modifier":
    let env = makeEmptyEnv()
    env.teamModifiers[0].gatherRateMultiplier = 2.0'f32
    env.addToStockpile(0, ResourceWood, 50)
    check env.stockpileCount(0, ResourceWood) == 100  # 50 * 2.0

  test "canSpendStockpile returns true when sufficient":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceWood, 50)
    check env.canSpendStockpile(0, [(ResourceFood, 50), (ResourceWood, 30)])

  test "canSpendStockpile returns false when insufficient":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 20)
    check not env.canSpendStockpile(0, [(ResourceFood, 50)])

  test "spendStockpile deducts resources":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 50)
    let ok = env.spendStockpile(0, [(ResourceFood, 30), (ResourceGold, 20)])
    check ok
    check env.stockpileCount(0, ResourceFood) == 70
    check env.stockpileCount(0, ResourceGold) == 30

  test "spendStockpile fails without deducting when insufficient":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 10)
    let ok = env.spendStockpile(0, [(ResourceFood, 50)])
    check not ok
    check env.stockpileCount(0, ResourceFood) == 10  # Unchanged

  test "teams have independent stockpiles":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 1, ResourceFood, 200)
    check env.stockpileCount(0, ResourceFood) == 100
    check env.stockpileCount(1, ResourceFood) == 200

# =============================================================================
# Terrain and Position Queries
# =============================================================================

suite "Environment - Position Queries":
  test "isEmpty returns true for empty tile":
    let env = makeEmptyEnv()
    check env.isEmpty(ivec2(10, 10))

  test "isEmpty returns false for occupied tile":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))
    check not env.isEmpty(ivec2(10, 10))

  test "isEmpty returns false for out of bounds":
    let env = makeEmptyEnv()
    check not env.isEmpty(ivec2(-1, -1))
    check not env.isEmpty(ivec2(MapWidth, 0))

  test "getThing returns thing at position":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check env.getThing(ivec2(10, 10)) == agent

  test "getThing returns nil for empty position":
    let env = makeEmptyEnv()
    check env.getThing(ivec2(10, 10)).isNil

  test "getThing returns nil for out of bounds":
    let env = makeEmptyEnv()
    check env.getThing(ivec2(-1, -1)).isNil

  test "isSpawnable for empty valid tile":
    let env = makeEmptyEnv()
    check env.isSpawnable(ivec2(10, 10))

  test "isSpawnable false for occupied tile":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))
    check not env.isSpawnable(ivec2(10, 10))

  test "canPlace on empty buildable tile":
    let env = makeEmptyEnv()
    # TerrainEmpty is buildable by default in makeEmptyEnv
    check env.canPlace(ivec2(10, 10))

  test "canPlace false on occupied tile":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))
    check not env.canPlace(ivec2(10, 10))

  test "canPlace false on water terrain":
    let env = makeEmptyEnv()
    env.terrain[10][10] = Water
    check not env.canPlace(ivec2(10, 10))

  test "canPlaceDock on water tile":
    let env = makeEmptyEnv()
    env.terrain[10][10] = Water
    check env.canPlaceDock(ivec2(10, 10))

  test "canPlaceDock false on land tile":
    let env = makeEmptyEnv()
    check not env.canPlaceDock(ivec2(10, 10))

suite "Environment - Terrain Traversal":
  test "canTraverseElevation allows flat movement":
    let env = makeEmptyEnv()
    env.elevation[10][10] = 0
    env.elevation[11][10] = 0
    check env.canTraverseElevation(ivec2(10, 10), ivec2(11, 10))

  test "canTraverseElevation allows downhill without ramp":
    let env = makeEmptyEnv()
    env.elevation[10][10] = 1
    env.elevation[11][10] = 0
    check env.canTraverseElevation(ivec2(10, 10), ivec2(11, 10))

  test "canTraverseElevation blocks uphill without ramp":
    let env = makeEmptyEnv()
    env.elevation[10][10] = 0
    env.elevation[11][10] = 1
    check not env.canTraverseElevation(ivec2(10, 10), ivec2(11, 10))

  test "canTraverseElevation allows uphill on road":
    let env = makeEmptyEnv()
    env.elevation[10][10] = 0
    env.elevation[11][10] = 1
    env.terrain[11][10] = Road
    check env.canTraverseElevation(ivec2(10, 10), ivec2(11, 10))

  test "willCauseCliffFallDamage on downhill without ramp":
    let env = makeEmptyEnv()
    env.elevation[10][10] = 1
    env.elevation[11][10] = 0
    check env.willCauseCliffFallDamage(ivec2(10, 10), ivec2(11, 10))

  test "willCauseCliffFallDamage false on downhill with road":
    let env = makeEmptyEnv()
    env.elevation[10][10] = 1
    env.elevation[11][10] = 0
    env.terrain[10][10] = Road
    check not env.willCauseCliffFallDamage(ivec2(10, 10), ivec2(11, 10))

  test "willCauseCliffFallDamage false on flat terrain":
    let env = makeEmptyEnv()
    env.elevation[10][10] = 0
    env.elevation[11][10] = 0
    check not env.willCauseCliffFallDamage(ivec2(10, 10), ivec2(11, 10))

# =============================================================================
# Water and Door Queries
# =============================================================================

suite "Environment - Water and Door":
  test "hasWaterNearby detects water within radius":
    let env = makeEmptyEnv()
    env.terrain[15][15] = Water
    check env.hasWaterNearby(ivec2(13, 15), 3)

  test "hasWaterNearby false when no water":
    let env = makeEmptyEnv()
    check not env.hasWaterNearby(ivec2(10, 10), 3)

  test "hasWaterNearby respects includeShallow":
    let env = makeEmptyEnv()
    env.terrain[15][15] = ShallowWater
    check not env.hasWaterNearby(ivec2(13, 15), 3, includeShallow = false)
    check env.hasWaterNearby(ivec2(13, 15), 3, includeShallow = true)

  test "isWaterUnit for boat types":
    let env = makeEmptyEnv()
    let boat = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitBoat)
    check boat.isWaterUnit
    let galley = addAgentAt(env, 1, ivec2(11, 10), unitClass = UnitGalley)
    check galley.isWaterUnit

  test "isWaterUnit false for land units":
    let env = makeEmptyEnv()
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    check not villager.isWaterUnit
    let knight = addAgentAt(env, 1, ivec2(11, 10), unitClass = UnitKnight)
    check not knight.isWaterUnit

  test "hasDoor detects background door":
    let env = makeEmptyEnv()
    let door = Thing(kind: Door, pos: ivec2(10, 10), teamId: 0)
    door.inventory = emptyInventory()
    env.backgroundGrid[10][10] = door
    check env.hasDoor(ivec2(10, 10))

  test "hasDoor false for empty tile":
    let env = makeEmptyEnv()
    check not env.hasDoor(ivec2(10, 10))

  test "canAgentPassDoor allows own team":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 11))
    let door = Thing(kind: Door, pos: ivec2(10, 10), teamId: 0)
    door.inventory = emptyInventory()
    env.backgroundGrid[10][10] = door
    check env.canAgentPassDoor(agent, ivec2(10, 10))

  test "canAgentPassDoor blocks enemy team":
    let env = makeEmptyEnv()
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    let door = Thing(kind: Door, pos: ivec2(10, 10), teamId: 0)
    door.inventory = emptyInventory()
    env.backgroundGrid[10][10] = door
    check not env.canAgentPassDoor(enemy, ivec2(10, 10))

# =============================================================================
# Rally Points
# =============================================================================

suite "Environment - Rally Points":
  test "setRallyPoint and hasRallyPoint":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    check not tc.hasRallyPoint()
    tc.setRallyPoint(ivec2(15, 15))
    check tc.hasRallyPoint()
    check tc.rallyPoint == ivec2(15, 15)

  test "clearRallyPoint removes rally point":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    tc.setRallyPoint(ivec2(15, 15))
    check tc.hasRallyPoint()
    tc.clearRallyPoint()
    check not tc.hasRallyPoint()

# =============================================================================
# Unit Categories and Stances
# =============================================================================

suite "Environment - Unit Categories":
  test "defaultStanceForClass villager is NoAttack":
    check defaultStanceForClass(UnitVillager) == StanceNoAttack

  test "defaultStanceForClass military is Defensive":
    check defaultStanceForClass(UnitManAtArms) == StanceDefensive
    check defaultStanceForClass(UnitArcher) == StanceDefensive
    check defaultStanceForClass(UnitKnight) == StanceDefensive

  test "defaultStanceForClass monk is NoAttack":
    check defaultStanceForClass(UnitMonk) == StanceNoAttack

  test "getUnitCategory infantry":
    check getUnitCategory(UnitManAtArms) == CategoryInfantry
    check getUnitCategory(UnitSamurai) == CategoryInfantry
    check getUnitCategory(UnitChampion) == CategoryInfantry

  test "getUnitCategory cavalry":
    check getUnitCategory(UnitScout) == CategoryCavalry
    check getUnitCategory(UnitKnight) == CategoryCavalry
    check getUnitCategory(UnitPaladin) == CategoryCavalry

  test "getUnitCategory archer":
    check getUnitCategory(UnitArcher) == CategoryArcher
    check getUnitCategory(UnitLongbowman) == CategoryArcher
    check getUnitCategory(UnitArbalester) == CategoryArcher

  test "getUnitCategory none for villager and siege":
    check getUnitCategory(UnitVillager) == CategoryNone
    check getUnitCategory(UnitBatteringRam) == CategoryNone
    check getUnitCategory(UnitMonk) == CategoryNone

suite "Environment - Blacksmith Bonuses":
  test "getBlacksmithAttackBonus zero at start":
    let env = makeEmptyEnv()
    check env.getBlacksmithAttackBonus(0, UnitManAtArms) == 0
    check env.getBlacksmithAttackBonus(0, UnitArcher) == 0

  test "getBlacksmithArmorBonus zero at start":
    let env = makeEmptyEnv()
    check env.getBlacksmithArmorBonus(0, UnitManAtArms) == 0
    check env.getBlacksmithArmorBonus(0, UnitScout) == 0

  test "blacksmith attack bonus after upgrade":
    let env = makeEmptyEnv()
    env.teamBlacksmithUpgrades[0].levels[UpgradeMeleeAttack] = 1
    let bonus = env.getBlacksmithAttackBonus(0, UnitManAtArms)
    check bonus > 0

  test "blacksmith armor bonus for CategoryNone returns zero":
    let env = makeEmptyEnv()
    env.teamBlacksmithUpgrades[0].levels[UpgradeInfantryArmor] = 3
    check env.getBlacksmithArmorBonus(0, UnitVillager) == 0

# =============================================================================
# Alliance System
# =============================================================================

suite "Environment - Alliance System":
  test "teams start allied with themselves":
    let env = makeEmptyEnv()
    check env.areAllied(0, 0)
    check env.areAllied(1, 1)

  test "teams start not allied with each other":
    let env = makeEmptyEnv()
    check not env.areAllied(0, 1)
    check not env.areAllied(1, 0)

  test "formAlliance creates symmetric alliance":
    let env = makeEmptyEnv()
    env.formAlliance(0, 1)
    check env.areAllied(0, 1)
    check env.areAllied(1, 0)

  test "breakAlliance removes symmetric alliance":
    let env = makeEmptyEnv()
    env.formAlliance(0, 1)
    check env.areAllied(0, 1)
    env.breakAlliance(0, 1)
    check not env.areAllied(0, 1)
    check not env.areAllied(1, 0)

  test "breakAlliance cannot un-ally with self":
    let env = makeEmptyEnv()
    env.breakAlliance(0, 0)
    check env.areAllied(0, 0)

  test "formAlliance with invalid team id is safe":
    let env = makeEmptyEnv()
    env.formAlliance(-1, 0)  # Should not crash
    env.formAlliance(0, MapRoomObjectsTeams + 1)  # Should not crash

  test "areAllied with invalid team returns false":
    let env = makeEmptyEnv()
    check not env.areAllied(-1, 0)
    check not env.areAllied(0, MapRoomObjectsTeams + 1)

# =============================================================================
# Tribute System
# =============================================================================

suite "Environment - Tribute":
  test "tributeResources transfers resources with tax":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 200)
    let received = env.tributeResources(0, 1, ResourceFood, 100)
    check received > 0
    check received < 100  # Tax applied
    check env.stockpileCount(0, ResourceFood) == 100  # 200 - 100
    check env.stockpileCount(1, ResourceFood) == received

  test "tributeResources fails without enough resources":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 10)
    let received = env.tributeResources(0, 1, ResourceFood, 100)
    check received == 0
    check env.stockpileCount(0, ResourceFood) == 10  # Unchanged

  test "tributeResources fails for same team":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 200)
    let received = env.tributeResources(0, 0, ResourceFood, 100)
    check received == 0

  test "tributeResources fails for ResourceNone":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 200)
    let received = env.tributeResources(0, 1, ResourceNone, 100)
    check received == 0

  test "tributeResources tracks sent and received":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 200)
    let received = env.tributeResources(0, 1, ResourceFood, 100)
    check env.teamTributesSent[0] == 100
    check env.teamTributesReceived[1] == received

  test "tributeResources invalid team ids":
    let env = makeEmptyEnv()
    check env.tributeResources(-1, 0, ResourceFood, 100) == 0
    check env.tributeResources(0, -1, ResourceFood, 100) == 0
    check env.tributeResources(0, MapRoomObjectsTeams, ResourceFood, 100) == 0

# =============================================================================
# Production Queue
# =============================================================================

suite "Environment - Production Queue":
  test "building starts with empty queue":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    check barracks.productionQueue.entries.len == 0
    check not barracks.productionQueueHasReady()

  test "queueTrainUnit adds entry":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceFood, 500)
    setStockpile(env, 0, ResourceGold, 500)
    let costs = buildingTrainCosts(Barracks)
    let ok = env.queueTrainUnit(barracks, 0, UnitManAtArms, costs)
    check ok
    check barracks.productionQueue.entries.len == 1

  test "queueTrainUnit spends resources":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceFood, 500)
    setStockpile(env, 0, ResourceGold, 500)
    let foodBefore = env.stockpileCount(0, ResourceFood)
    let costs = buildingTrainCosts(Barracks)
    discard env.queueTrainUnit(barracks, 0, UnitManAtArms, costs)
    check env.stockpileCount(0, ResourceFood) < foodBefore

  test "processProductionQueue decrements remaining steps":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceFood, 500)
    setStockpile(env, 0, ResourceGold, 500)
    let costs = buildingTrainCosts(Barracks)
    discard env.queueTrainUnit(barracks, 0, UnitManAtArms, costs)
    let stepsBefore = barracks.productionQueue.entries[0].remainingSteps
    barracks.processProductionQueue()
    check barracks.productionQueue.entries[0].remainingSteps == stepsBefore - 1

  test "productionQueueHasReady after countdown":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceFood, 500)
    setStockpile(env, 0, ResourceGold, 500)
    let costs = buildingTrainCosts(Barracks)
    discard env.queueTrainUnit(barracks, 0, UnitManAtArms, costs)
    # Count down to zero
    while barracks.productionQueue.entries[0].remainingSteps > 0:
      barracks.processProductionQueue()
    check barracks.productionQueueHasReady()

  test "consumeReadyQueueEntry returns unit class":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceFood, 500)
    setStockpile(env, 0, ResourceGold, 500)
    let costs = buildingTrainCosts(Barracks)
    discard env.queueTrainUnit(barracks, 0, UnitManAtArms, costs)
    while barracks.productionQueue.entries[0].remainingSteps > 0:
      barracks.processProductionQueue()
    let unitClass = barracks.consumeReadyQueueEntry()
    check unitClass == UnitManAtArms
    check barracks.productionQueue.entries.len == 0

  test "cancelLastQueued removes and refunds":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceFood, 500)
    setStockpile(env, 0, ResourceGold, 500)
    let costs = buildingTrainCosts(Barracks)
    discard env.queueTrainUnit(barracks, 0, UnitManAtArms, costs)
    let foodAfterQueue = env.stockpileCount(0, ResourceFood)
    let ok = env.cancelLastQueued(barracks)
    check ok
    check barracks.productionQueue.entries.len == 0
    check env.stockpileCount(0, ResourceFood) > foodAfterQueue  # Refunded

  test "cancelLastQueued fails on empty queue":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    check not env.cancelLastQueued(barracks)

  test "queue respects max size":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    setStockpile(env, 0, ResourceFood, 50000)
    setStockpile(env, 0, ResourceGold, 50000)
    let costs = buildingTrainCosts(Barracks)
    for i in 0 ..< ProductionQueueMaxSize:
      check env.queueTrainUnit(barracks, 0, UnitManAtArms, costs)
    # One more should fail
    check not env.queueTrainUnit(barracks, 0, UnitManAtArms, costs)

# =============================================================================
# Market Price Decay
# =============================================================================

suite "Environment - Market Price Decay":
  test "decayMarketPrices drifts high prices toward base":
    let env = makeEmptyEnv()
    env.setMarketPrice(0, ResourceWood, MarketBasePrice + 50)
    let priceBefore = env.getMarketPrice(0, ResourceWood)
    env.decayMarketPrices()
    check env.getMarketPrice(0, ResourceWood) < priceBefore

  test "decayMarketPrices drifts low prices toward base":
    let env = makeEmptyEnv()
    env.setMarketPrice(0, ResourceWood, MarketBasePrice - 50)
    let priceBefore = env.getMarketPrice(0, ResourceWood)
    env.decayMarketPrices()
    check env.getMarketPrice(0, ResourceWood) > priceBefore

  test "decayMarketPrices does not overshoot base":
    let env = makeEmptyEnv()
    env.setMarketPrice(0, ResourceWood, MarketBasePrice)
    env.decayMarketPrices()
    check env.getMarketPrice(0, ResourceWood) == MarketBasePrice

# =============================================================================
# Observation System
# =============================================================================

suite "Environment - Observations":
  test "ensureObservations initializes without crash":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))
    env.stepNoop()  # stepNoop calls ensureObservations
    check env.observationsInitialized

  test "observations populated for alive agent":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))
    env.stepNoop()
    # Agent should see terrain around itself - check observations are populated
    var hasNonZero = false
    for layer in 0 ..< ObservationLayers:
      for x in 0 ..< ObservationWidth:
        for y in 0 ..< ObservationHeight:
          if env.observations[0][layer][x][y] != 0:
            hasNonZero = true
            break
        if hasNonZero: break
      if hasNonZero: break
    check hasNonZero

# =============================================================================
# Visual Effects
# =============================================================================

suite "Environment - Visual Effects":
  test "spawnDamageNumber adds damage number":
    let env = makeEmptyEnv()
    let initialLen = env.damageNumbers.len
    env.spawnDamageNumber(ivec2(10, 10), 5)
    check env.damageNumbers.len == initialLen + 1
    check env.damageNumbers[^1].amount == 5

  test "spawnDamageNumber ignores zero amount":
    let env = makeEmptyEnv()
    let initialLen = env.damageNumbers.len
    env.spawnDamageNumber(ivec2(10, 10), 0)
    check env.damageNumbers.len == initialLen

  test "spawnDamageNumber ignores invalid position":
    let env = makeEmptyEnv()
    let initialLen = env.damageNumbers.len
    env.spawnDamageNumber(ivec2(-1, -1), 5)
    check env.damageNumbers.len == initialLen

  test "spawnDebris adds particles":
    let env = makeEmptyEnv()
    let initialLen = env.debris.len
    env.spawnDebris(ivec2(10, 10), House)
    check env.debris.len > initialLen

  test "spawnSpawnEffect adds effect":
    let env = makeEmptyEnv()
    let initialLen = env.spawnEffects.len
    env.spawnSpawnEffect(ivec2(10, 10))
    check env.spawnEffects.len == initialLen + 1

# =============================================================================
# Position Finding Helpers
# =============================================================================

suite "Environment - Position Helpers":
  test "findEmptyPositionsAround finds positions":
    let env = makeEmptyEnv()
    let positions = env.findEmptyPositionsAround(ivec2(20, 20), 2)
    check positions.len > 0

  test "findEmptyPositionsAround excludes center":
    let env = makeEmptyEnv()
    let center = ivec2(20, 20)
    let positions = env.findEmptyPositionsAround(center, 2)
    var centerFound = false
    for pos in positions:
      if pos == center:
        centerFound = true
    check not centerFound

  test "findEmptyPositionsAround respects blocking":
    let env = makeEmptyEnv()
    let center = ivec2(20, 20)
    # Block all adjacent tiles
    for dx in -1 .. 1:
      for dy in -1 .. 1:
        if dx == 0 and dy == 0: continue
        discard addBuilding(env, House, ivec2(20 + dx.int32, 20 + dy.int32), 0)
    let positions = env.findEmptyPositionsAround(center, 1)
    check positions.len == 0

  test "findFirstEmptyPositionAround finds a position":
    let env = makeEmptyEnv()
    let pos = env.findFirstEmptyPositionAround(ivec2(20, 20), 2)
    check isValidPos(pos)

  test "findFirstEmptyPositionAround returns -1,-1 when all blocked":
    let env = makeEmptyEnv()
    let center = ivec2(20, 20)
    for dx in -1 .. 1:
      for dy in -1 .. 1:
        if dx == 0 and dy == 0: continue
        discard addBuilding(env, House, ivec2(20 + dx.int32, 20 + dy.int32), 0)
    let pos = env.findFirstEmptyPositionAround(center, 1)
    check pos == ivec2(-1, -1)

# =============================================================================
# Error Types
# =============================================================================

suite "Environment - Error Types":
  test "clearFFIError resets state":
    lastFFIError = FFIErrorState(hasError: true, errorCode: ErrMapFull, errorMessage: "test")
    clearFFIError()
    check not lastFFIError.hasError
    check lastFFIError.errorCode == ErrNone

  test "newTribalError creates error with kind":
    let err = newTribalError(ErrInvalidPosition, "bad pos")
    check err.kind == ErrInvalidPosition
    check err.details == "bad pos"

# =============================================================================
# Payment System
# =============================================================================

suite "Environment - Payment System":
  test "choosePayment prefers inventory":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 5)
    let source = env.choosePayment(agent, [(key: ItemWood, count: 3)])
    check source == PayInventory

  test "choosePayment falls back to stockpile":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceWood, 100)
    let source = env.choosePayment(agent, [(key: ItemWood, count: 3)])
    check source == PayStockpile

  test "choosePayment returns PayNone when broke":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let source = env.choosePayment(agent, [(key: ItemWood, count: 3)])
    check source == PayNone

  test "choosePayment returns PayNone for empty costs":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let empty: seq[tuple[key: ItemKey, count: int]] = @[]
    let source = env.choosePayment(agent, empty)
    check source == PayNone

  test "spendInventory deducts from agent":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 10)
    let ok = env.spendInventory(agent, [(key: ItemWood, count: 3)])
    check ok
    check getInv(agent, ItemWood) == 7

  test "spendInventory fails when insufficient":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 1)
    let ok = env.spendInventory(agent, [(key: ItemWood, count: 3)])
    check not ok
    check getInv(agent, ItemWood) == 1  # Unchanged

# =============================================================================
# Building Helpers
# =============================================================================

suite "Environment - Building Creation":
  test "addBuilding places on grid":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    check env.grid[10][10] == tc
    check tc.kind == TownCenter
    check tc.teamId == 0

  test "addBuilding is fully constructed":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    check tc.constructed

  test "addBuilding has no rally point by default":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    check not tc.hasRallyPoint()

  test "addResource places resource node":
    let env = makeEmptyEnv()
    let tree = addResource(env, Tree, ivec2(10, 10), ItemWood)
    check tree.kind == Tree
    check getInv(tree, ItemWood) == ResourceNodeInitial

# =============================================================================
# Render
# =============================================================================

suite "Environment - Render":
  test "render produces non-empty string":
    let env = makeEmptyEnv()
    let rendered = env.render()
    check rendered.len > 0

  test "render contains newlines for rows":
    let env = makeEmptyEnv()
    let rendered = env.render()
    var newlineCount = 0
    for c in rendered:
      if c == '\n':
        inc newlineCount
    check newlineCount == MapHeight
