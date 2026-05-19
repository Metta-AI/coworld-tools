import std/unittest
import environment
import items
import test_utils

suite "Market - Dynamic Pricing":
  test "market initializes with base prices":
    let env = makeEmptyEnv()
    check env.getMarketPrice(0, ResourceFood) == MarketBasePrice
    check env.getMarketPrice(0, ResourceWood) == MarketBasePrice
    check env.getMarketPrice(0, ResourceStone) == MarketBasePrice

  test "market sells resources for gold with dynamic pricing":
    let env = makeEmptyEnv()
    let market = addBuilding(env, Market, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 100)  # Sell 100 wood
    setStockpile(env, 0, ResourceGold, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, market.pos))

    # At base price (100 gold per 100 units), selling 100 wood = 100 gold
    check env.stockpileCount(0, ResourceGold) == 100
    check agent.inventoryWood == 0
    # Price should have decreased after selling
    check env.getMarketPrice(0, ResourceWood) == MarketBasePrice - MarketSellPriceDecrease

  test "market buys food with gold using dynamic pricing":
    let env = makeEmptyEnv()
    let market = addBuilding(env, Market, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemGold, 100)  # Spend 100 gold
    setStockpile(env, 0, ResourceFood, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, market.pos))

    # At base price (100 gold per 100 units), spending 100 gold = 100 food
    check env.stockpileCount(0, ResourceFood) == 100
    check agent.inventoryGold == 0
    # Price should have increased after buying
    check env.getMarketPrice(0, ResourceFood) == MarketBasePrice + MarketBuyPriceIncrease

  test "market price increases affect trade rates":
    let env = makeEmptyEnv()
    # Set wood price to 200 (double)
    env.setMarketPrice(0, ResourceWood, 200)
    let market = addBuilding(env, Market, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 100)
    setStockpile(env, 0, ResourceGold, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, market.pos))

    # At price 200, selling 100 wood = (100 * 200) / 100 = 200 gold
    check env.stockpileCount(0, ResourceGold) == 200
    check agent.inventoryWood == 0

  test "market price decreases affect trade rates":
    let env = makeEmptyEnv()
    # Set food price to 50 (half)
    env.setMarketPrice(0, ResourceFood, 50)
    let market = addBuilding(env, Market, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemGold, 100)
    setStockpile(env, 0, ResourceFood, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, market.pos))

    # At price 50, spending 100 gold = (100 * 100) / 50 = 200 food
    check env.stockpileCount(0, ResourceFood) == 200
    check agent.inventoryGold == 0

  test "market prices respect min/max bounds":
    let env = makeEmptyEnv()
    # Test max bound
    env.setMarketPrice(0, ResourceWood, 1000)  # Way above max
    check env.getMarketPrice(0, ResourceWood) == MarketMaxPrice

    # Test min bound
    env.setMarketPrice(0, ResourceWood, 1)  # Way below min
    check env.getMarketPrice(0, ResourceWood) == MarketMinPrice

  test "market prices decay toward base rate":
    let env = makeEmptyEnv()
    env.setMarketPrice(0, ResourceWood, MarketBasePrice + 10)
    env.setMarketPrice(0, ResourceFood, MarketBasePrice - 10)

    env.decayMarketPrices()

    # Prices should drift toward base
    check env.getMarketPrice(0, ResourceWood) == MarketBasePrice + 10 - MarketPriceDecayRate
    check env.getMarketPrice(0, ResourceFood) == MarketBasePrice - 10 + MarketPriceDecayRate

  test "market cooldown blocks trading":
    let env = makeEmptyEnv()
    let market = addBuilding(env, Market, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 100)
    setStockpile(env, 0, ResourceGold, 0)
    market.cooldown = 1

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, market.pos))

    check agent.inventoryWood == 100
    check env.stockpileCount(0, ResourceGold) == 0
    check market.cooldown == 0

  test "teams have independent market prices":
    let env = makeEmptyEnv()
    env.setMarketPrice(0, ResourceWood, 150)
    env.setMarketPrice(1, ResourceWood, 80)

    check env.getMarketPrice(0, ResourceWood) == 150
    check env.getMarketPrice(1, ResourceWood) == 80

suite "Crafting":
  test "university crafts table items":
    let env = makeEmptyEnv()
    let uni = addBuilding(env, University, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemWood, 1)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, uni.pos))

    check agent.inventoryWood == 0
    check getInv(agent, otherItem("bucket")) == 1

suite "Storage":
  test "barrel stores and returns items":
    let env = makeEmptyEnv()
    let barrel = addBuilding(env, Barrel, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setInv(agent, ItemBread, 2)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barrel.pos))
    check getInv(barrel, ItemBread) == 2
    check agent.inventoryBread == 0

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, barrel.pos))
    check getInv(barrel, ItemBread) == 0
    check agent.inventoryBread == 2

suite "Training":
  test "monastery trains monk and spends gold":
    let env = makeEmptyEnv()
    let monastery = addBuilding(env, Monastery, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceGold, 2)

    # First USE action queues the training (resources spent immediately)
    # The step also ticks the queue once, so remaining = duration - 1
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, monastery.pos))
    check agent.unitClass == UnitVillager  # Still villager (queued, not converted yet)
    check env.stockpileCount(0, ResourceGold) == 0
    check monastery.productionQueue.entries.len == 1
    check monastery.productionQueue.entries[0].remainingSteps == unitTrainTime(UnitMonk) - 1

    # Wait for remaining steps to complete
    for i in 0 ..< unitTrainTime(UnitMonk) - 1:
      env.stepNoop()

    # Queue entry should now be ready (remainingSteps == 0)
    check monastery.productionQueue.entries.len == 1
    check monastery.productionQueue.entries[0].remainingSteps == 0

    # Now USE again to consume the ready entry and convert
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, monastery.pos))
    check agent.unitClass == UnitMonk
