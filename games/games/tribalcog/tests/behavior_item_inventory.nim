import std/[unittest, strformat]
import test_common

## Behavioral tests for item pickup, drop (dropoff), and inventory slot management.

suite "Behavior: Resource Pickup from Nodes":
  test "villager picks up wood from tree":
    let env = makeEmptyEnv()
    let treePos = ivec2(10, 9)
    let tree = addResource(env, Tree, treePos, ItemWood)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    check agent.inventoryWood == 0
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, treePos))

    echo &"  Wood after harvest: {agent.inventoryWood}"
    check agent.inventoryWood > 0

  test "villager picks up gold from gold node":
    let env = makeEmptyEnv()
    let goldPos = ivec2(10, 9)
    let goldNode = addResource(env, Gold, goldPos, ItemGold)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    check agent.inventoryGold == 0
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, goldPos))

    echo &"  Gold after mining: {agent.inventoryGold}"
    check agent.inventoryGold > 0

  test "villager picks up stone from stone node":
    let env = makeEmptyEnv()
    let stonePos = ivec2(10, 9)
    let stoneNode = addResource(env, Stone, stonePos, ItemStone)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    check agent.inventoryStone == 0
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, stonePos))

    echo &"  Stone after mining: {agent.inventoryStone}"
    check agent.inventoryStone > 0

  test "villager picks up wheat from wheat field":
    let env = makeEmptyEnv()
    let wheatPos = ivec2(10, 9)
    let wheatNode = addResource(env, Wheat, wheatPos, ItemWheat)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    check agent.inventoryWheat == 0
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, wheatPos))

    echo &"  Wheat after harvest: {agent.inventoryWheat}"
    check agent.inventoryWheat > 0

suite "Behavior: Inventory Capacity Limits":
  test "agent cannot pick up more resources when at carry capacity":
    let env = makeEmptyEnv()
    let treePos = ivec2(10, 9)
    discard addResource(env, Tree, treePos, ItemWood)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Fill wood to carry capacity
    setInv(agent, ItemWood, ResourceCarryCapacity)
    let woodBefore = agent.inventoryWood

    # Try to harvest - should not increase
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, treePos))

    echo &"  Wood before={woodBefore} after={agent.inventoryWood} (cap={ResourceCarryCapacity})"
    check agent.inventoryWood == ResourceCarryCapacity

  test "agent cannot pick up lantern when at max inventory":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Fill lanterns to max
    setInv(agent, ItemLantern, MapObjectAgentMaxInventory)

    let lanternPos = ivec2(10, 9)
    let lantern = Thing(kind: Lantern, pos: lanternPos)
    lantern.inventory = emptyInventory()
    env.add(lantern)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lanternPos))

    echo &"  Lanterns: {agent.inventoryLantern} (max={MapObjectAgentMaxInventory})"
    check agent.inventoryLantern == MapObjectAgentMaxInventory

  test "non-stockpile items have independent capacity from stockpile resources":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Fill stockpile resources to cap
    setInv(agent, ItemWood, ResourceCarryCapacity)

    # Lantern pickup should still work (non-stockpile item)
    let lanternPos = ivec2(10, 9)
    let lantern = Thing(kind: Lantern, pos: lanternPos)
    lantern.inventory = emptyInventory()
    env.add(lantern)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lanternPos))

    echo &"  Wood={agent.inventoryWood} (full), lantern={agent.inventoryLantern} (independent)"
    check agent.inventoryWood == ResourceCarryCapacity
    check agent.inventoryLantern == 1

suite "Behavior: Resource Dropoff at Buildings":
  test "villager drops wood at lumber camp":
    let env = makeEmptyEnv()
    let lcPos = ivec2(10, 9)
    discard addBuilding(env, LumberCamp, lcPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    setInv(agent, ItemWood, 3)
    setStockpile(env, 0, ResourceWood, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lcPos))

    echo &"  After dropoff: wood_inv={agent.inventoryWood} wood_stockpile={env.stockpileCount(0, ResourceWood)}"
    check agent.inventoryWood == 0
    check env.stockpileCount(0, ResourceWood) > 0

  test "villager drops gold at mining camp":
    let env = makeEmptyEnv()
    let mcPos = ivec2(10, 9)
    discard addBuilding(env, MiningCamp, mcPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    setInv(agent, ItemGold, 3)
    setStockpile(env, 0, ResourceGold, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, mcPos))

    echo &"  After dropoff: gold_inv={agent.inventoryGold} gold_stockpile={env.stockpileCount(0, ResourceGold)}"
    check agent.inventoryGold == 0
    check env.stockpileCount(0, ResourceGold) > 0

  test "villager drops food at granary":
    let env = makeEmptyEnv()
    let granaryPos = ivec2(10, 9)
    discard addBuilding(env, Granary, granaryPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    setInv(agent, ItemWheat, 3)
    setStockpile(env, 0, ResourceFood, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, granaryPos))

    echo &"  After dropoff: wheat_inv={agent.inventoryWheat} food_stockpile={env.stockpileCount(0, ResourceFood)}"
    check agent.inventoryWheat == 0
    check env.stockpileCount(0, ResourceFood) > 0

  test "villager drops all resource types at town center":
    let env = makeEmptyEnv()
    let tcPos = ivec2(10, 9)
    discard addBuilding(env, TownCenter, tcPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    setInv(agent, ItemWood, 2)
    setInv(agent, ItemGold, 1)
    setStockpile(env, 0, ResourceWood, 0)
    setStockpile(env, 0, ResourceGold, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, tcPos))

    echo &"  After TC dropoff: wood_inv={agent.inventoryWood} gold_inv={agent.inventoryGold}"
    echo &"  Stockpile: wood={env.stockpileCount(0, ResourceWood)} gold={env.stockpileCount(0, ResourceGold)}"
    check agent.inventoryWood == 0
    check agent.inventoryGold == 0
    check env.stockpileCount(0, ResourceWood) > 0
    check env.stockpileCount(0, ResourceGold) > 0

  test "villager cannot drop wrong resource type at specialized building":
    let env = makeEmptyEnv()
    let lcPos = ivec2(10, 9)
    discard addBuilding(env, LumberCamp, lcPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Lumber camp only accepts wood, not gold
    setInv(agent, ItemGold, 3)
    setStockpile(env, 0, ResourceGold, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lcPos))

    echo &"  After invalid dropoff: gold_inv={agent.inventoryGold} gold_stockpile={env.stockpileCount(0, ResourceGold)}"
    check agent.inventoryGold == 3
    check env.stockpileCount(0, ResourceGold) == 0

  test "enemy cannot drop off at opponent's building":
    let env = makeEmptyEnv()
    let lcPos = ivec2(10, 9)
    discard addBuilding(env, LumberCamp, lcPos, 0)  # Team 0's building
    let agent = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 10))  # Team 1 agent

    setInv(agent, ItemWood, 3)
    setStockpile(env, 1, ResourceWood, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lcPos))

    echo &"  Enemy dropoff attempt: wood_inv={agent.inventoryWood}"
    check agent.inventoryWood == 3
    check env.stockpileCount(1, ResourceWood) == 0

suite "Behavior: Special Item Pickup":
  test "monk picks up relic":
    let env = makeEmptyEnv()
    let relicPos = ivec2(10, 9)
    let relic = Thing(kind: Relic, pos: relicPos)
    relic.inventory = emptyInventory()
    env.add(relic)
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)

    check monk.inventoryRelic == 0
    env.stepAction(monk.agentId, 3'u8, dirIndex(monk.pos, relicPos))

    echo &"  Monk relic count: {monk.inventoryRelic}"
    check monk.inventoryRelic == 1

  test "relic pickup respects inventory cap":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    setInv(monk, ItemRelic, MapObjectAgentMaxInventory)

    let relicPos = ivec2(10, 9)
    let relic = Thing(kind: Relic, pos: relicPos)
    relic.inventory = emptyInventory()
    env.add(relic)

    let relicBefore = monk.inventoryRelic
    env.stepAction(monk.agentId, 3'u8, dirIndex(monk.pos, relicPos))

    echo &"  Relics before={relicBefore} after={monk.inventoryRelic} (max={MapObjectAgentMaxInventory})"
    check monk.inventoryRelic == MapObjectAgentMaxInventory

  test "villager picks up lantern":
    let env = makeEmptyEnv()
    let lanternPos = ivec2(10, 9)
    let lantern = Thing(kind: Lantern, pos: lanternPos)
    lantern.inventory = emptyInventory()
    env.add(lantern)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    check agent.inventoryLantern == 0
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, lanternPos))

    echo &"  Lantern count: {agent.inventoryLantern}"
    check agent.inventoryLantern == 1

suite "Behavior: Inventory Slot Management":
  test "empty inventory has zero length":
    let inv = emptyInventory()
    check inv.len == 0

  test "setting item increases inventory length":
    var inv = emptyInventory()
    inv[ItemWood] = 5
    check inv.len == 1
    check inv[ItemWood] == 5

  test "setting item to zero removes it from length count":
    var inv = emptyInventory()
    inv[ItemWood] = 5
    check inv.len == 1
    inv[ItemWood] = 0
    check inv.len == 0

  test "del removes item from inventory":
    var inv = emptyInventory()
    inv[ItemSpear] = 3
    check inv.hasKey(ItemSpear)
    inv.del(ItemSpear)
    check not inv.hasKey(ItemSpear)
    check inv[ItemSpear] == 0

  test "multiple item types coexist independently":
    var inv = emptyInventory()
    inv[ItemWood] = 3
    inv[ItemGold] = 2
    inv[ItemSpear] = 1
    check inv.len == 3
    check inv[ItemWood] == 3
    check inv[ItemGold] == 2
    check inv[ItemSpear] == 1

  test "negative values clamp to zero":
    var inv = emptyInventory()
    inv[ItemWood] = -5
    check inv[ItemWood] == 0
    check inv.len == 0

  test "canSpendInventory checks sufficient quantities":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 3)
    setInv(agent, ItemStone, 2)

    check canSpendInventory(agent, @[(ItemWood, 2), (ItemStone, 1)])
    check not canSpendInventory(agent, @[(ItemWood, 4)])
    check not canSpendInventory(agent, @[(ItemWood, 2), (ItemStone, 3)])
    echo "  canSpendInventory correctly validates costs"

suite "Behavior: Corpse Looting":
  test "agent loots items from corpse":
    let env = makeEmptyEnv()
    let corpsePos = ivec2(10, 9)
    let corpse = Thing(kind: Corpse, pos: corpsePos)
    corpse.inventory = emptyInventory()
    setInv(corpse, ItemMeat, 3)
    env.add(corpse)

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check getInv(agent, ItemMeat) == 0

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, corpsePos))

    echo &"  Meat after looting corpse: {getInv(agent, ItemMeat)}"
    check getInv(agent, ItemMeat) > 0

suite "Behavior: Crafting Produces Items":
  test "baking bread at oven converts wheat to bread":
    let env = makeEmptyEnv()
    let ovenPos = ivec2(10, 9)
    discard addBuilding(env, ClayOven, ovenPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    setInv(agent, ItemWheat, 3)
    let breadBefore = agent.inventoryBread

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, ovenPos))

    echo &"  Wheat: 3->{agent.inventoryWheat}, Bread: {breadBefore}->{agent.inventoryBread}"
    check agent.inventoryWheat < 3
    check agent.inventoryBread > breadBefore

  test "smelting gold at magma produces bar":
    let env = makeEmptyEnv()
    let magmaPos = ivec2(10, 9)
    let magma = Thing(kind: Magma, pos: magmaPos)
    magma.inventory = emptyInventory()
    magma.cooldown = 0
    env.add(magma)

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemGold, 3)
    let barBefore = agent.inventoryBar

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, magmaPos))

    echo &"  Gold: 3->{agent.inventoryGold}, Bar: {barBefore}->{agent.inventoryBar}"
    check agent.inventoryGold < 3
    check agent.inventoryBar > barBefore
