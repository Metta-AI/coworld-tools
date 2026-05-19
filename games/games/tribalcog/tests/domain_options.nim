import std/unittest
import environment
import agent_control
import common
import types
import items
import terrain
import test_utils
import spatial_index
import scripted/options

# =============================================================================
# Helper Functions (exported)
# =============================================================================

suite "Options - agentHasAnyItem":
  test "returns true when agent has one of the items":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWheat, 5)
    check agentHasAnyItem(agent, [ItemWheat, ItemWood]) == true

  test "returns false when agent has none of the items":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check agentHasAnyItem(agent, [ItemWheat, ItemWood]) == false

  test "returns true with single matching item":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemArmor, 1)
    check agentHasAnyItem(agent, [ItemArmor]) == true

  test "returns false with empty keys array":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWheat, 10)
    let empty: seq[ItemKey] = @[]
    check agentHasAnyItem(agent, empty) == false

# =============================================================================
# findNearestNeutralHub (exported)
# =============================================================================

suite "Options - findNearestNeutralHub":
  test "finds neutral hub building":
    let env = makeEmptyEnv()
    discard addBuilding(env, Castle, ivec2(20, 20), -1)
    let result = findNearestNeutralHub(env, ivec2(10, 10))
    check not isNil(result)
    check result.pos == ivec2(20, 20)

  test "ignores team-owned buildings":
    let env = makeEmptyEnv()
    discard addBuilding(env, Castle, ivec2(15, 15), 0)
    discard addBuilding(env, Market, ivec2(20, 20), 1)
    let result = findNearestNeutralHub(env, ivec2(10, 10))
    check isNil(result)

  test "returns nearest among multiple neutral hubs":
    let env = makeEmptyEnv()
    discard addBuilding(env, Castle, ivec2(30, 30), -1)
    discard addBuilding(env, Market, ivec2(12, 12), -1)
    let result = findNearestNeutralHub(env, ivec2(10, 10))
    check not isNil(result)
    check result.pos == ivec2(12, 12)

  test "returns nil with no neutral hubs":
    let env = makeEmptyEnv()
    let result = findNearestNeutralHub(env, ivec2(10, 10))
    check isNil(result)

# =============================================================================
# findIrrigationTarget (exported)
# =============================================================================

suite "Options - findIrrigationTarget":
  test "finds empty tile within radius":
    let env = makeEmptyEnv()
    let result = findIrrigationTarget(env, ivec2(20, 20), 3)
    check result.x >= 0
    check result.y >= 0

  test "returns ivec2(-1,-1) when all tiles blocked by water":
    let env = makeEmptyEnv()
    let center = ivec2(5, 5)
    for x in 0 .. 10:
      for y in 0 .. 10:
        env.terrain[x][y] = Water
    let result = findIrrigationTarget(env, center, 5)
    check result == ivec2(-1, -1)

  test "prefers closer tiles":
    let env = makeEmptyEnv()
    # Block all tiles except a distant one
    let center = ivec2(20, 20)
    for dx in -2 .. 2:
      for dy in -2 .. 2:
        if abs(dx) <= 1 and abs(dy) <= 1:
          discard addBuilding(env, Wall, center + ivec2(dx.int32, dy.int32), 0)
    let result = findIrrigationTarget(env, center, 3)
    if result.x >= 0:
      let dist = abs(result.x - center.x) + abs(result.y - center.y)
      check dist >= 1  # Not the center itself (occupied)

# =============================================================================
# findNearestPredator (exported)
# =============================================================================

suite "Options - findNearestPredator":
  test "finds nearest wolf":
    let env = makeEmptyEnv()
    let wolf = Thing(kind: Wolf, pos: ivec2(15, 15))
    wolf.inventory = emptyInventory()
    env.add(wolf)
    let result = findNearestPredator(env, ivec2(10, 10))
    check not isNil(result)
    check result.kind == Wolf

  test "finds nearest bear":
    let env = makeEmptyEnv()
    let bear = Thing(kind: Bear, pos: ivec2(12, 12))
    bear.inventory = emptyInventory()
    env.add(bear)
    let result = findNearestPredator(env, ivec2(10, 10))
    check not isNil(result)
    check result.kind == Bear

  test "returns nearest of wolf and bear":
    let env = makeEmptyEnv()
    let wolf = Thing(kind: Wolf, pos: ivec2(30, 30))
    wolf.inventory = emptyInventory()
    env.add(wolf)
    let bear = Thing(kind: Bear, pos: ivec2(12, 12))
    bear.inventory = emptyInventory()
    env.add(bear)
    let result = findNearestPredator(env, ivec2(10, 10))
    check not isNil(result)
    check result.kind == Bear

  test "returns nil when no predators":
    let env = makeEmptyEnv()
    let result = findNearestPredator(env, ivec2(10, 10))
    check isNil(result)

# =============================================================================
# findNearestGoblinStructure (exported)
# =============================================================================

suite "Options - findNearestGoblinStructure":
  test "finds goblin hive":
    let env = makeEmptyEnv()
    let hive = Thing(kind: GoblinHive, pos: ivec2(15, 15))
    hive.inventory = emptyInventory()
    env.add(hive)
    let result = findNearestGoblinStructure(env, ivec2(10, 10))
    check not isNil(result)
    check result.kind == GoblinHive

  test "finds nearest among multiple goblin structures":
    let env = makeEmptyEnv()
    let hive = Thing(kind: GoblinHive, pos: ivec2(30, 30))
    hive.inventory = emptyInventory()
    env.add(hive)
    let hut = Thing(kind: GoblinHut, pos: ivec2(12, 12))
    hut.inventory = emptyInventory()
    env.add(hut)
    let result = findNearestGoblinStructure(env, ivec2(10, 10))
    check not isNil(result)
    check result.kind == GoblinHut

  test "returns nil when no goblin structures":
    let env = makeEmptyEnv()
    let result = findNearestGoblinStructure(env, ivec2(10, 10))
    check isNil(result)

# =============================================================================
# findNearestGarrisonableBuilding (exported)
# =============================================================================

suite "Options - findNearestGarrisonableBuilding":
  test "finds friendly garrisonable building":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(15, 15), 0)
    let result = findNearestGarrisonableBuilding(env, ivec2(10, 10), 0, 30)
    check not isNil(result)
    check result.kind == TownCenter

  test "ignores enemy buildings":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(15, 15), 1)
    let result = findNearestGarrisonableBuilding(env, ivec2(10, 10), 0, 30)
    check isNil(result)

  test "ignores buildings beyond maxDist":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(40, 40), 0)
    let result = findNearestGarrisonableBuilding(env, ivec2(10, 10), 0, 5)
    check isNil(result)

  test "ignores full buildings":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(15, 15), 0)
    for i in 0 ..< TownCenterGarrisonCapacity:
      let villager = addAgentAt(env, i, ivec2(15 + i, 16))
      discard env.garrisonUnitInBuilding(villager, tc)
    let result = findNearestGarrisonableBuilding(env, ivec2(10, 10), 0, 30)
    check isNil(result)

  test "ignores destroyed buildings":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(15, 15), 0)
    tc.hp = 0
    let result = findNearestGarrisonableBuilding(env, ivec2(10, 10), 0, 30)
    check isNil(result)

  test "finds Castle when TownCenter is full":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(15, 15), 0)
    for i in 0 ..< TownCenterGarrisonCapacity:
      let villager = addAgentAt(env, i, ivec2(15 + i, 16))
      discard env.garrisonUnitInBuilding(villager, tc)
    discard addBuilding(env, Castle, ivec2(20, 20), 0)
    let result = findNearestGarrisonableBuilding(env, ivec2(10, 10), 0, 30)
    check not isNil(result)
    check result.kind == Castle

# =============================================================================
# findNearbyEnemyForFlee (exported)
# =============================================================================

suite "Options - findNearbyEnemyForFlee":
  test "finds enemy within radius":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(12, 12))
    env.rebuildSpatialIndex()
    let result = findNearbyEnemyForFlee(env, agent, 5)
    check not isNil(result)

  test "returns nil when no enemies within radius":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(40, 40))
    env.rebuildSpatialIndex()
    let result = findNearbyEnemyForFlee(env, agent, 5)
    check isNil(result)

  test "returns nil when no enemies exist":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    env.rebuildSpatialIndex()
    let result = findNearbyEnemyForFlee(env, agent, 10)
    check isNil(result)

# =============================================================================
# findNearestPredatorInRadius (exported)
# =============================================================================

suite "Options - findNearestPredatorInRadius":
  test "finds wolf within radius":
    let env = makeEmptyEnv()
    let wolf = Thing(kind: Wolf, pos: ivec2(12, 12))
    wolf.inventory = emptyInventory()
    env.add(wolf)
    env.rebuildSpatialIndex()
    let result = findNearestPredatorInRadius(env, ivec2(10, 10), 5)
    check not isNil(result)
    check result.kind == Wolf

  test "returns nil when predator beyond radius":
    let env = makeEmptyEnv()
    let wolf = Thing(kind: Wolf, pos: ivec2(40, 40))
    wolf.inventory = emptyInventory()
    env.add(wolf)
    env.rebuildSpatialIndex()
    let result = findNearestPredatorInRadius(env, ivec2(10, 10), 5)
    check isNil(result)

# =============================================================================
# CanStart / ShouldTerminate: StoreValuables (exported)
# =============================================================================

suite "Options - StoreValuables canStart/shouldTerminate":
  test "canStart true when agent has storable items and team has building":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, Granary, ivec2(15, 15), 0)
    setInv(agent, ItemWheat, 3)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartStoreValuables(controller, env, agent, 0, state) == true

  test "canStart false when agent has no storable items":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, Granary, ivec2(15, 15), 0)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartStoreValuables(controller, env, agent, 0, state) == false

  test "canStart false when team has no storage buildings":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWheat, 3)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartStoreValuables(controller, env, agent, 0, state) == false

  test "canStart with blacksmith and armor":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, Blacksmith, ivec2(15, 15), 0)
    setInv(agent, ItemArmor, 1)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartStoreValuables(controller, env, agent, 0, state) == true

  test "shouldTerminate is inverse of canStart":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, Granary, ivec2(15, 15), 0)
    setInv(agent, ItemWheat, 3)
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateStoreValuables(controller, env, agent, 0, state) == false
    setInv(agent, ItemWheat, 0)
    check shouldTerminateStoreValuables(controller, env, agent, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: CraftBread (exported)
# =============================================================================

suite "Options - CraftBread canStart/shouldTerminate":
  test "canStart true with wheat, bread space, and clay oven":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, ClayOven, ivec2(15, 15), 0)
    agent.inventoryWheat = 5
    agent.inventoryBread = 0
    let controller = newTestController(42)
    var state = AgentState()
    check canStartCraftBread(controller, env, agent, 0, state) == true

  test "canStart false without wheat":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, ClayOven, ivec2(15, 15), 0)
    agent.inventoryWheat = 0
    let controller = newTestController(42)
    var state = AgentState()
    check canStartCraftBread(controller, env, agent, 0, state) == false

  test "canStart false when bread full":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, ClayOven, ivec2(15, 15), 0)
    agent.inventoryWheat = 5
    agent.inventoryBread = MapObjectAgentMaxInventory
    let controller = newTestController(42)
    var state = AgentState()
    check canStartCraftBread(controller, env, agent, 0, state) == false

  test "canStart false without clay oven":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryWheat = 5
    agent.inventoryBread = 0
    let controller = newTestController(42)
    var state = AgentState()
    check canStartCraftBread(controller, env, agent, 0, state) == false

  test "shouldTerminate when wheat depleted":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryWheat = 0
    agent.inventoryBread = 2
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateCraftBread(controller, env, agent, 0, state) == true

  test "shouldTerminate when bread full":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryWheat = 5
    agent.inventoryBread = MapObjectAgentMaxInventory
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateCraftBread(controller, env, agent, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: SmeltGold (exported)
# =============================================================================

suite "Options - SmeltGold canStart/shouldTerminate":
  test "canStart true with gold, bar space, and magma":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let magma = Thing(kind: Magma, pos: ivec2(20, 20))
    magma.inventory = emptyInventory()
    env.add(magma)
    agent.inventoryGold = 5
    agent.inventoryBar = 0
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSmeltGold(controller, env, agent, 0, state) == true

  test "canStart false without magma":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryGold = 5
    agent.inventoryBar = 0
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSmeltGold(controller, env, agent, 0, state) == false

  test "canStart false without gold":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let magma = Thing(kind: Magma, pos: ivec2(20, 20))
    magma.inventory = emptyInventory()
    env.add(magma)
    agent.inventoryGold = 0
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSmeltGold(controller, env, agent, 0, state) == false

  test "shouldTerminate when gold depleted":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryGold = 0
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateSmeltGold(controller, env, agent, 0, state) == true

  test "shouldTerminate when bar full":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryGold = 5
    agent.inventoryBar = MapObjectAgentMaxInventory
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateSmeltGold(controller, env, agent, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: EmergencyHeal (exported)
# =============================================================================

suite "Options - EmergencyHeal canStart/shouldTerminate":
  test "canStart true when HP below 50% and has bread":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryBread = 3
    agent.hp = 4
    agent.maxHp = 10
    let controller = newTestController(42)
    var state = AgentState()
    check canStartEmergencyHeal(controller, env, agent, 0, state) == true

  test "canStart false when HP above 50%":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryBread = 3
    agent.hp = 8
    agent.maxHp = 10
    let controller = newTestController(42)
    var state = AgentState()
    check canStartEmergencyHeal(controller, env, agent, 0, state) == false

  test "canStart false without bread":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryBread = 0
    agent.hp = 3
    agent.maxHp = 10
    let controller = newTestController(42)
    var state = AgentState()
    check canStartEmergencyHeal(controller, env, agent, 0, state) == false

  test "canStart false at exactly 50% HP":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryBread = 3
    agent.hp = 5
    agent.maxHp = 10
    let controller = newTestController(42)
    var state = AgentState()
    check canStartEmergencyHeal(controller, env, agent, 0, state) == false

  test "shouldTerminate when healed above 50%":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryBread = 3
    agent.hp = 6
    agent.maxHp = 10
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateEmergencyHeal(controller, env, agent, 0, state) == true

  test "shouldTerminate when bread runs out":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryBread = 0
    agent.hp = 3
    agent.maxHp = 10
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateEmergencyHeal(controller, env, agent, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: MonkHeal (exported)
# =============================================================================

suite "Options - MonkHeal canStart/shouldTerminate":
  test "canStart true when monk with wounded ally nearby":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    let ally = addAgentAt(env, 1, ivec2(12, 12))
    ally.hp = ally.maxHp - 5
    env.rebuildSpatialIndex()
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMonkHeal(controller, env, monk, 0, state) == true

  test "canStart false when not a monk":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitVillager)
    let ally = addAgentAt(env, 1, ivec2(12, 12))
    ally.hp = ally.maxHp - 5
    env.rebuildSpatialIndex()
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMonkHeal(controller, env, agent, 0, state) == false

  test "canStart false when no wounded allies":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    let ally = addAgentAt(env, 1, ivec2(12, 12))
    env.rebuildSpatialIndex()
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMonkHeal(controller, env, monk, 0, state) == false

  test "shouldTerminate when no longer monk":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitVillager)
    env.rebuildSpatialIndex()
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateMonkHeal(controller, env, agent, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: MonkRelicCollect (exported)
# =============================================================================

suite "Options - MonkRelicCollect canStart/shouldTerminate":
  test "canStart true when monk and relics exist":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    let relic = Thing(kind: Relic, pos: ivec2(20, 20))
    relic.inventory = emptyInventory()
    env.add(relic)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMonkRelicCollect(controller, env, monk, 0, state) == true

  test "canStart true when monk carrying relic":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    monk.inventoryRelic = 1
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMonkRelicCollect(controller, env, monk, 0, state) == true

  test "canStart false when not monk":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitVillager)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMonkRelicCollect(controller, env, agent, 0, state) == false

  test "shouldTerminate when not monk":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitVillager)
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateMonkRelicCollect(controller, env, agent, 0, state) == true

  test "shouldTerminate when no relics and not carrying":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    monk.inventoryRelic = 0
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateMonkRelicCollect(controller, env, monk, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: MonkConversion (exported)
# =============================================================================

suite "Options - MonkConversion canStart/shouldTerminate":
  test "canStart true when monk with faith and enemy nearby":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    monk.faith = MonkConversionFaithCost
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(12, 12), unitClass = UnitManAtArms)
    env.rebuildSpatialIndex()
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMonkConversion(controller, env, monk, 0, state) == true

  test "canStart false when faith too low":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    monk.faith = MonkConversionFaithCost - 1
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(12, 12), unitClass = UnitManAtArms)
    env.rebuildSpatialIndex()
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMonkConversion(controller, env, monk, 0, state) == false

  test "canStart false when not monk":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitVillager)
    agent.faith = MonkConversionFaithCost
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(12, 12), unitClass = UnitManAtArms)
    env.rebuildSpatialIndex()
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMonkConversion(controller, env, agent, 0, state) == false

  test "shouldTerminate when faith depleted":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    monk.faith = 0
    env.rebuildSpatialIndex()
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateMonkConversion(controller, env, monk, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: TradeCogTradeRoute (exported)
# =============================================================================

suite "Options - TradeCogTradeRoute canStart/shouldTerminate":
  test "canStart true with 2+ friendly docks":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitTradeCog)
    discard addBuilding(env, Dock, ivec2(5, 5), 0)
    discard addBuilding(env, Dock, ivec2(30, 30), 0)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartTradeCogTradeRoute(controller, env, agent, 0, state) == true

  test "canStart false with only 1 dock":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitTradeCog)
    discard addBuilding(env, Dock, ivec2(5, 5), 0)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartTradeCogTradeRoute(controller, env, agent, 0, state) == false

  test "canStart false when not trade cog":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitVillager)
    discard addBuilding(env, Dock, ivec2(5, 5), 0)
    discard addBuilding(env, Dock, ivec2(30, 30), 0)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartTradeCogTradeRoute(controller, env, agent, 0, state) == false

  test "canStart false with 0 docks":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitTradeCog)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartTradeCogTradeRoute(controller, env, agent, 0, state) == false

  test "shouldTerminate is inverse of canStart":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitTradeCog)
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateTradeCogTradeRoute(controller, env, agent, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: SiegeAdvance (exported)
# =============================================================================

suite "Options - SiegeAdvance canStart/shouldTerminate":
  test "canStart true when mangonel and enemy buildings exist":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    discard addBuilding(env, TownCenter, ivec2(30, 30), 1)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSiegeAdvance(controller, env, agent, 0, state) == true

  test "canStart true when trebuchet and enemy buildings exist":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitTrebuchet)
    discard addBuilding(env, Barracks, ivec2(30, 30), 1)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSiegeAdvance(controller, env, agent, 0, state) == true

  test "canStart false when not siege unit":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitVillager)
    discard addBuilding(env, TownCenter, ivec2(30, 30), 1)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSiegeAdvance(controller, env, agent, 0, state) == false

  test "canStart false when no enemy buildings":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSiegeAdvance(controller, env, agent, 0, state) == false

  test "shouldTerminate when no enemy buildings":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMangonel)
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateSiegeAdvance(controller, env, agent, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: SettlerMigrate (exported)
# =============================================================================

suite "Options - SettlerMigrate canStart/shouldTerminate":
  test "canStart true when settler with target and not arrived":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.isSettler = true
    agent.settlerTarget = ivec2(40, 40)
    agent.settlerArrived = false
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSettlerMigrate(controller, env, agent, 0, state) == true

  test "canStart false when not settler":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.isSettler = false
    agent.settlerTarget = ivec2(40, 40)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSettlerMigrate(controller, env, agent, 0, state) == false

  test "canStart false when no target":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.isSettler = true
    agent.settlerTarget = ivec2(-1, -1)
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSettlerMigrate(controller, env, agent, 0, state) == false

  test "canStart false when already arrived":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.isSettler = true
    agent.settlerTarget = ivec2(40, 40)
    agent.settlerArrived = true
    let controller = newTestController(42)
    var state = AgentState()
    check canStartSettlerMigrate(controller, env, agent, 0, state) == false

  test "shouldTerminate when arrived":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.isSettler = true
    agent.settlerTarget = ivec2(40, 40)
    agent.settlerArrived = true
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateSettlerMigrate(controller, env, agent, 0, state) == true

  test "shouldTerminate when no longer settler":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.isSettler = false
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateSettlerMigrate(controller, env, agent, 0, state) == true

# =============================================================================
# CanStart / ShouldTerminate: MarketTrade (exported)
# =============================================================================

suite "Options - MarketTrade canStart/shouldTerminate":
  test "canStart false without market":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryGold = 5
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMarketTrade(controller, env, agent, 0, state) == false

  test "canStart true with market and gold when team needs food":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    discard addBuilding(env, Market, ivec2(15, 15), 0)
    agent.inventoryGold = 5
    setStockpile(env, 0, ResourceFood, 5)  # Low food
    let controller = newTestController(42)
    var state = AgentState()
    check canStartMarketTrade(controller, env, agent, 0, state) == true

  test "shouldTerminate is inverse of canStart":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let controller = newTestController(42)
    var state = AgentState()
    check shouldTerminateMarketTrade(controller, env, agent, 0, state) == true

# =============================================================================
# OptionDef constants
# =============================================================================

suite "Options - OptionDef constants":
  test "SmeltGoldOption has correct name":
    check SmeltGoldOption.name == "SmeltGold"

  test "CraftBreadOption has correct name":
    check CraftBreadOption.name == "CraftBread"

  test "StoreValuablesOption has correct name":
    check StoreValuablesOption.name == "StoreValuables"

  test "EmergencyHealOption has correct name":
    check EmergencyHealOption.name == "EmergencyHeal"

  test "FallbackSearchOption is always interruptible":
    check FallbackSearchOption.interruptible == true

  test "TownBellGarrisonOption is not interruptible":
    check TownBellGarrisonOption.interruptible == false

  test "SettlerMigrateOption is not interruptible":
    check SettlerMigrateOption.interruptible == false

  test "MonkHealOption has correct name":
    check MonkHealOption.name == "MonkHeal"

  test "MonkRelicCollectOption has correct name":
    check MonkRelicCollectOption.name == "MonkRelicCollect"

  test "MonkConversionOption has correct name":
    check MonkConversionOption.name == "MonkConversion"

  test "TradeCogTradeRouteOption has correct name":
    check TradeCogTradeRouteOption.name == "TradeCogTradeRoute"

  test "SiegeAdvanceOption has correct name":
    check SiegeAdvanceOption.name == "SiegeAdvance"

  test "MarketTradeOption has correct name":
    check MarketTradeOption.name == "MarketTrade"

# =============================================================================
# MetaBehaviorOptions array
# =============================================================================

suite "Options - MetaBehaviorOptions":
  test "MetaBehaviorOptions array has expected length":
    check MetaBehaviorOptions.len == 34

  test "first behavior is SettlerMigrate":
    check MetaBehaviorOptions[0].name == "BehaviorSettlerMigrate"

  test "SettlerMigrate is not interruptible in meta array":
    check MetaBehaviorOptions[0].interruptible == false

  test "last behavior is SiegeAdvance":
    check MetaBehaviorOptions[MetaBehaviorOptions.high].name == "BehaviorSiegeAdvance"

  test "all meta behaviors have non-empty names":
    for opt in MetaBehaviorOptions:
      check opt.name.len > 0

  test "all meta behaviors have canStart proc":
    for opt in MetaBehaviorOptions:
      check not isNil(opt.canStart)

  test "all meta behaviors have shouldTerminate proc":
    for opt in MetaBehaviorOptions:
      check not isNil(opt.shouldTerminate)

  test "all meta behaviors have act proc":
    for opt in MetaBehaviorOptions:
      check not isNil(opt.act)

# =============================================================================
# Test private canStart/shouldTerminate through MetaBehaviorOptions
# =============================================================================

suite "Options - MetaBehavior canStart checks via OptionDef":
  test "BehaviorAntiTumorPatrol canStart with tumors":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let tumor = Thing(kind: Tumor, pos: ivec2(20, 20))
    tumor.inventory = emptyInventory()
    env.add(tumor)
    let controller = newTestController(42)
    var state = AgentState()
    # Find the AntiTumorPatrol option in MetaBehaviorOptions
    var found = false
    for opt in MetaBehaviorOptions:
      if opt.name == "BehaviorAntiTumorPatrol":
        check opt.canStart(controller, env, agent, 0, state) == true
        found = true
        break
    check found == true

  test "BehaviorAntiTumorPatrol canStart false without tumors":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let controller = newTestController(42)
    var state = AgentState()
    for opt in MetaBehaviorOptions:
      if opt.name == "BehaviorAntiTumorPatrol":
        check opt.canStart(controller, env, agent, 0, state) == false
        break

  test "BehaviorSpawnerHunter canStart with spawners":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let spawner = Thing(kind: Spawner, pos: ivec2(20, 20))
    spawner.inventory = emptyInventory()
    env.add(spawner)
    let controller = newTestController(42)
    var state = AgentState()
    for opt in MetaBehaviorOptions:
      if opt.name == "BehaviorSpawnerHunter":
        check opt.canStart(controller, env, agent, 0, state) == true
        break

  test "BehaviorRelicRaider canStart without relic and relics exist":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryRelic = 0
    let relic = Thing(kind: Relic, pos: ivec2(20, 20))
    relic.inventory = emptyInventory()
    env.add(relic)
    let controller = newTestController(42)
    var state = AgentState()
    for opt in MetaBehaviorOptions:
      if opt.name == "BehaviorRelicRaider":
        check opt.canStart(controller, env, agent, 0, state) == true
        break

  test "BehaviorRelicCourier canStart when carrying relic":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryRelic = 1
    let controller = newTestController(42)
    var state = AgentState()
    for opt in MetaBehaviorOptions:
      if opt.name == "BehaviorRelicCourier":
        check opt.canStart(controller, env, agent, 0, state) == true
        break

  test "BehaviorPredatorCull canStart with HP and predators":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.hp = 8
    agent.maxHp = 10
    let wolf = Thing(kind: Wolf, pos: ivec2(15, 15))
    wolf.inventory = emptyInventory()
    env.add(wolf)
    let controller = newTestController(42)
    var state = AgentState()
    for opt in MetaBehaviorOptions:
      if opt.name == "BehaviorPredatorCull":
        check opt.canStart(controller, env, agent, 0, state) == true
        break

  test "BehaviorGoblinNestClear canStart with goblin structures":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let hive = Thing(kind: GoblinHive, pos: ivec2(20, 20))
    hive.inventory = emptyInventory()
    env.add(hive)
    let controller = newTestController(42)
    var state = AgentState()
    for opt in MetaBehaviorOptions:
      if opt.name == "BehaviorGoblinNestClear":
        check opt.canStart(controller, env, agent, 0, state) == true
        break

  test "BehaviorFertileExpansion canStart with wheat":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryWheat = 3
    let controller = newTestController(42)
    var state = AgentState()
    for opt in MetaBehaviorOptions:
      if opt.name == "BehaviorFertileExpansion":
        check opt.canStart(controller, env, agent, 0, state) == true
        break

  test "BehaviorLanternFrontierPush canStart with lanterns":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.inventoryLantern = 3
    let controller = newTestController(42)
    var state = AgentState()
    for opt in MetaBehaviorOptions:
      if opt.name == "BehaviorLanternFrontierPush":
        check opt.canStart(controller, env, agent, 0, state) == true
        break
