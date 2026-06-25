import std/[unittest, strformat]
import test_common

## Behavioral trade tests verifying market buy/sell, dynamic pricing,
## price decay, cooldowns, and independent team prices.

suite "Behavioral Trade - Market Buy/Sell Resource Totals":
  test "selling wood at market converts inventory to stockpile gold":
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    let market = addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    setInv(agent, ItemWood, 100)
    setStockpile(env, 0, ResourceGold, 0)
    setStockpile(env, 0, ResourceWood, 0)

    echo fmt"  Before sell: wood_inv={agent.inventoryWood} gold_stockpile={env.stockpileCount(0, ResourceGold)}"

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let goldAfter = env.stockpileCount(0, ResourceGold)
    echo fmt"  After sell: wood_inv={agent.inventoryWood} gold_stockpile={goldAfter}"

    # Inventory wood should be cleared, gold should appear in stockpile
    check agent.inventoryWood == 0
    check goldAfter > 0

  test "buying food with gold converts gold inventory to food stockpile":
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    let market = addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    setInv(agent, ItemGold, 200)
    setStockpile(env, 0, ResourceFood, 0)

    echo fmt"  Before buy: gold_inv={agent.inventoryGold} food_stockpile={env.stockpileCount(0, ResourceFood)}"

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let foodAfter = env.stockpileCount(0, ResourceFood)
    echo fmt"  After buy: gold_inv={agent.inventoryGold} food_stockpile={foodAfter}"

    check agent.inventoryGold == 0
    check foodAfter > 0

  test "sell then buy round-trip preserves approximate resource value":
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    let market = addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Sell wood for gold
    setInv(agent, ItemWood, 100)
    setStockpile(env, 0, ResourceGold, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let goldGained = env.stockpileCount(0, ResourceGold)
    echo fmt"  Sold 100 wood -> {goldGained} gold"
    check goldGained > 0

    # Wait for cooldown
    for i in 0 ..< DefaultMarketCooldown:
      env.stepNoop()

    # Buy food with the gold
    setInv(agent, ItemGold, goldGained)
    setStockpile(env, 0, ResourceGold, 0)
    setStockpile(env, 0, ResourceFood, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let foodGained = env.stockpileCount(0, ResourceFood)
    echo fmt"  Bought food with {goldGained} gold -> {foodGained} food"

    # Should get some food, but not necessarily 100 due to pricing spreads
    check foodGained > 0

suite "Behavioral Trade - Dynamic Pricing Changes with Volume":
  test "selling wood repeatedly decreases wood price":
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    discard addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    let initialPrice = env.getMarketPrice(0, ResourceWood)
    echo fmt"  Initial wood price: {initialPrice}"

    # Sell wood multiple times, resetting cooldown each time
    for trade in 0 ..< 5:
      setInv(agent, ItemWood, 100)
      let market = env.getThing(marketPos)
      if not isNil(market):
        market.cooldown = 0
      env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let finalPrice = env.getMarketPrice(0, ResourceWood)
    echo fmt"  Wood price after 5 sells: {finalPrice}"

    # Selling increases supply -> price should decrease
    check finalPrice < initialPrice

  test "buying food repeatedly increases food price":
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    discard addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    let initialFoodPrice = env.getMarketPrice(0, ResourceFood)
    echo fmt"  Initial food price: {initialFoodPrice}"

    # Buy food multiple times with gold
    for trade in 0 ..< 5:
      setInv(agent, ItemGold, 200)
      let market = env.getThing(marketPos)
      if not isNil(market):
        market.cooldown = 0
      env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let finalFoodPrice = env.getMarketPrice(0, ResourceFood)
    echo fmt"  Food price after 5 buys: {finalFoodPrice}"

    # Buying increases demand -> food price should increase
    check finalFoodPrice > initialFoodPrice

  test "price changes are proportional to MarketSellPriceDecrease":
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    discard addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    let priceBefore = env.getMarketPrice(0, ResourceWood)

    # Single sell trade
    setInv(agent, ItemWood, 100)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let priceAfter = env.getMarketPrice(0, ResourceWood)
    echo fmt"  Wood price: {priceBefore} -> {priceAfter} (delta={priceBefore - priceAfter})"

    # Price should decrease by exactly MarketSellPriceDecrease (3)
    check priceAfter == priceBefore - MarketSellPriceDecrease

suite "Behavioral Trade - Price Decay Toward Base Rate":
  test "inflated prices decay toward base rate over time":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))

    # Manually set inflated price
    env.setMarketPrice(0, ResourceWood, MarketBasePrice + 30)
    let inflatedPrice = env.getMarketPrice(0, ResourceWood)
    echo fmt"  Inflated wood price: {inflatedPrice}"

    # Run enough steps for several decay ticks
    let decaySteps = MarketPriceDecayInterval * 10
    for i in 0 ..< decaySteps:
      env.stepNoop()

    let decayedPrice = env.getMarketPrice(0, ResourceWood)
    echo fmt"  After {decaySteps} steps: {decayedPrice}"

    # Price should have moved closer to base
    check decayedPrice < inflatedPrice
    check decayedPrice >= MarketBasePrice

  test "deflated prices decay toward base rate over time":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))

    # Manually set deflated price
    env.setMarketPrice(0, ResourceWood, MarketBasePrice - 30)
    let deflatedPrice = env.getMarketPrice(0, ResourceWood)
    echo fmt"  Deflated wood price: {deflatedPrice}"

    let decaySteps = MarketPriceDecayInterval * 10
    for i in 0 ..< decaySteps:
      env.stepNoop()

    let decayedPrice = env.getMarketPrice(0, ResourceWood)
    echo fmt"  After {decaySteps} steps: {decayedPrice}"

    # Price should have moved closer to base
    check decayedPrice > deflatedPrice
    check decayedPrice <= MarketBasePrice

  test "price at base rate stays at base rate after decay":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))

    # Ensure price is at base
    let basePriceBefore = env.getMarketPrice(0, ResourceWood)
    check basePriceBefore == MarketBasePrice

    let decaySteps = MarketPriceDecayInterval * 5
    for i in 0 ..< decaySteps:
      env.stepNoop()

    let basePriceAfter = env.getMarketPrice(0, ResourceWood)
    echo fmt"  Base price before: {basePriceBefore}, after {decaySteps} steps: {basePriceAfter}"

    check basePriceAfter == MarketBasePrice

suite "Behavioral Trade - Cooldowns Prevent Spam Trading":
  test "market rejects trades while on cooldown":
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    let market = addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # First trade: should succeed
    setInv(agent, ItemWood, 100)
    setStockpile(env, 0, ResourceGold, 0)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let goldAfterFirst = env.stockpileCount(0, ResourceGold)
    echo fmt"  First trade gold: {goldAfterFirst}, market cooldown: {market.cooldown}"
    check goldAfterFirst > 0
    check market.cooldown > 0

    # Second trade immediately: should fail (market on cooldown)
    let goldBefore = env.stockpileCount(0, ResourceGold)
    setInv(agent, ItemWood, 100)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let goldAfterSecond = env.stockpileCount(0, ResourceGold)
    echo fmt"  Second trade gold: {goldAfterSecond} (should equal {goldBefore} if blocked)"

    # Agent should still have wood (trade blocked)
    check agent.inventoryWood == 100
    check goldAfterSecond == goldBefore

  test "market accepts trades after cooldown expires":
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    let market = addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # First trade
    setInv(agent, ItemWood, 100)
    setStockpile(env, 0, ResourceGold, 0)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let goldAfterFirst = env.stockpileCount(0, ResourceGold)
    echo fmt"  First trade gold: {goldAfterFirst}"
    check goldAfterFirst > 0

    # Wait for cooldown to expire
    for i in 0 ..< DefaultMarketCooldown:
      env.stepNoop()

    echo fmt"  Cooldown after waiting: {market.cooldown}"

    # Second trade after cooldown: should succeed
    setInv(agent, ItemWood, 100)
    let goldBeforeSecond = env.stockpileCount(0, ResourceGold)
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let goldAfterSecond = env.stockpileCount(0, ResourceGold)
    echo fmt"  Second trade gold: {goldAfterSecond}"

    check agent.inventoryWood == 0
    check goldAfterSecond > goldBeforeSecond

suite "Behavioral Trade - Independent Team Prices":
  test "team 0 trades do not affect team 1 prices":
    let env = makeEmptyEnv()
    # Team 0: agentId 0 -> team 0
    let marketPos0 = ivec2(10, 9)
    discard addBuilding(env, Market, marketPos0, 0)
    let agent0 = addAgentAt(env, 0, ivec2(10, 10))

    # Team 1: agentId MapAgentsPerTeam -> team 1
    let marketPos1 = ivec2(20, 9)
    discard addBuilding(env, Market, marketPos1, 1)
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 10))

    let initialPriceTeam0 = env.getMarketPrice(0, ResourceWood)
    let initialPriceTeam1 = env.getMarketPrice(1, ResourceWood)
    echo fmt"  Initial prices: team0={initialPriceTeam0} team1={initialPriceTeam1}"

    # Team 0 sells wood 5 times
    for trade in 0 ..< 5:
      setInv(agent0, ItemWood, 100)
      let market = env.getThing(marketPos0)
      if not isNil(market):
        market.cooldown = 0
      env.stepAction(agent0.agentId, 3'u8, dirIndex(agent0.pos, marketPos0))

    let finalPriceTeam0 = env.getMarketPrice(0, ResourceWood)
    let finalPriceTeam1 = env.getMarketPrice(1, ResourceWood)
    echo fmt"  Final prices: team0={finalPriceTeam0} team1={finalPriceTeam1}"

    # Team 0 price should have changed
    check finalPriceTeam0 < initialPriceTeam0

    # Team 1 price should be unchanged
    check finalPriceTeam1 == initialPriceTeam1

  test "teams can have different prices from independent trading":
    let env = makeEmptyEnv()
    # Team 0: agentId 0 -> team 0
    let marketPos0 = ivec2(10, 9)
    discard addBuilding(env, Market, marketPos0, 0)
    let agent0 = addAgentAt(env, 0, ivec2(10, 10))

    # Team 1: agentId MapAgentsPerTeam -> team 1
    let marketPos1 = ivec2(20, 9)
    discard addBuilding(env, Market, marketPos1, 1)
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 10))

    # Team 0 sells wood (price goes down)
    for trade in 0 ..< 5:
      setInv(agent0, ItemWood, 100)
      let market0 = env.getThing(marketPos0)
      if not isNil(market0):
        market0.cooldown = 0
      env.stepAction(agent0.agentId, 3'u8, dirIndex(agent0.pos, marketPos0))

    # Team 1 buys food (food price goes up, but wood stays at base)
    for trade in 0 ..< 5:
      setInv(agent1, ItemGold, 200)
      let market1 = env.getThing(marketPos1)
      if not isNil(market1):
        market1.cooldown = 0
      env.stepAction(agent1.agentId, 3'u8, dirIndex(agent1.pos, marketPos1))

    let woodPrice0 = env.getMarketPrice(0, ResourceWood)
    let woodPrice1 = env.getMarketPrice(1, ResourceWood)
    let foodPrice0 = env.getMarketPrice(0, ResourceFood)
    let foodPrice1 = env.getMarketPrice(1, ResourceFood)

    echo fmt"  Team 0: wood={woodPrice0} food={foodPrice0}"
    echo fmt"  Team 1: wood={woodPrice1} food={foodPrice1}"

    # Team 0 sold wood -> lower wood price
    check woodPrice0 < MarketBasePrice
    # Team 1 didn't sell wood -> wood price unchanged
    check woodPrice1 == MarketBasePrice
    # Team 1 bought food -> higher food price
    check foodPrice1 > MarketBasePrice
    # Team 0 didn't buy food -> food price unchanged
    check foodPrice0 == MarketBasePrice
