import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import test_utils

suite "Market - Initialization":
  test "market prices start at base rate":
    var env = makeEmptyEnv()
    for teamId in 0 ..< MapRoomObjectsTeams:
      for res in StockpileResource:
        if res != ResourceNone and res != ResourceGold:
          check env.getMarketPrice(teamId, res) == MarketBasePrice

  test "gold has no market price":
    var env = makeEmptyEnv()
    check env.getMarketPrice(0, ResourceGold) == 0

  test "ResourceNone has no market price":
    var env = makeEmptyEnv()
    check env.getMarketPrice(0, ResourceNone) == 0

suite "Market - Buying Resources":
  test "buying deducts gold and adds resource":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceGold, 500)
    let (goldCost, gained) = env.marketBuyResource(0, ResourceWood, 100)
    check gained == 100
    check goldCost > 0
    check env.stockpileCount(0, ResourceWood) == 100
    check env.stockpileCount(0, ResourceGold) == 500 - goldCost

  test "buying increases price":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceGold, 1000)
    let priceBefore = env.getMarketPrice(0, ResourceWood)
    discard env.marketBuyResource(0, ResourceWood, 100)
    check env.getMarketPrice(0, ResourceWood) == priceBefore + MarketBuyPriceIncrease

  test "cannot buy without enough gold":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceGold, 0)
    let (goldCost, gained) = env.marketBuyResource(0, ResourceWood, 100)
    check goldCost == 0
    check gained == 0
    check env.stockpileCount(0, ResourceWood) == 0

  test "cannot buy gold with gold":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceGold, 500)
    let (goldCost, gained) = env.marketBuyResource(0, ResourceGold, 100)
    check goldCost == 0
    check gained == 0

  test "cannot buy zero or negative amount":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceGold, 500)
    let (goldCost, gained) = env.marketBuyResource(0, ResourceWood, 0)
    check goldCost == 0
    check gained == 0

suite "Market - Selling Resources":
  test "selling deducts resource and adds gold":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceWood, 200)
    let (sold, goldGained) = env.marketSellResource(0, ResourceWood, 100)
    check sold == 100
    check goldGained > 0
    check env.stockpileCount(0, ResourceWood) == 100
    check env.stockpileCount(0, ResourceGold) == goldGained

  test "selling decreases price":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceWood, 500)
    let priceBefore = env.getMarketPrice(0, ResourceWood)
    discard env.marketSellResource(0, ResourceWood, 100)
    check env.getMarketPrice(0, ResourceWood) == priceBefore - MarketSellPriceDecrease

  test "cannot sell without enough resources":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceWood, 50)
    let (sold, goldGained) = env.marketSellResource(0, ResourceWood, 100)
    check sold == 0
    check goldGained == 0
    check env.stockpileCount(0, ResourceWood) == 50

  test "cannot sell gold":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceGold, 500)
    let (sold, goldGained) = env.marketSellResource(0, ResourceGold, 100)
    check sold == 0
    check goldGained == 0

suite "Market - Price Bounds":
  test "price cannot exceed max":
    var env = makeEmptyEnv()
    env.setMarketPrice(0, ResourceWood, MarketMaxPrice + 100)
    check env.getMarketPrice(0, ResourceWood) == MarketMaxPrice

  test "price cannot go below min":
    var env = makeEmptyEnv()
    env.setMarketPrice(0, ResourceWood, MarketMinPrice - 100)
    check env.getMarketPrice(0, ResourceWood) == MarketMinPrice

  test "repeated buying pushes price up toward max":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceGold, 100000)
    let initialPrice = env.getMarketPrice(0, ResourceWood)
    for i in 0 ..< 100:
      discard env.marketBuyResource(0, ResourceWood, 10)
    let finalPrice = env.getMarketPrice(0, ResourceWood)
    check finalPrice > initialPrice
    check finalPrice <= MarketMaxPrice

  test "repeated selling pushes price down toward min":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceWood, 100000)
    let initialPrice = env.getMarketPrice(0, ResourceWood)
    for i in 0 ..< 100:
      discard env.marketSellResource(0, ResourceWood, 10)
    let finalPrice = env.getMarketPrice(0, ResourceWood)
    check finalPrice < initialPrice
    check finalPrice >= MarketMinPrice

suite "Market - Team Independence":
  test "team 0 buying does not affect team 1 prices":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceGold, 500)
    let team1PriceBefore = env.getMarketPrice(1, ResourceWood)
    discard env.marketBuyResource(0, ResourceWood, 100)
    check env.getMarketPrice(1, ResourceWood) == team1PriceBefore

  test "teams have independent stockpiles for market":
    var env = makeEmptyEnv()
    env.setStockpile(0, ResourceGold, 500)
    env.setStockpile(1, ResourceGold, 500)
    discard env.marketBuyResource(0, ResourceFood, 100)
    check env.stockpileCount(0, ResourceFood) == 100
    check env.stockpileCount(1, ResourceFood) == 0
