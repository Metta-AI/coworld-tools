import std/unittest
import environment
import types
import items
import test_utils

suite "Tribute - Basic Transfer":
  test "basic tribute transfers correct amount after tax":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 100)

    let received = env.tributeResources(0, 1, ResourceGold, 50)

    # Default tax rate is 20%, so receiver gets 80% of 50 = 40
    check received == 40
    check env.stockpileCount(0, ResourceGold) == 50  # 100 - 50 sent
    check env.stockpileCount(1, ResourceGold) == 40  # received after tax

  test "tribute works for all resource types":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceWood, 100)
    setStockpile(env, 0, ResourceGold, 100)
    setStockpile(env, 0, ResourceStone, 100)

    let receivedFood = env.tributeResources(0, 1, ResourceFood, 10)
    let receivedWood = env.tributeResources(0, 2, ResourceWood, 10)
    let receivedGold = env.tributeResources(0, 3, ResourceGold, 10)
    let receivedStone = env.tributeResources(0, 4, ResourceStone, 10)

    check receivedFood == 8  # 10 - 20% tax = 8
    check receivedWood == 8
    check receivedGold == 8
    check receivedStone == 8

suite "Tribute - Tax Rate":
  test "default tax rate applies 20% fee":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 100)

    let received = env.tributeResources(0, 1, ResourceGold, 100)

    # 20% tax on 100 = 20 lost, 80 received
    check received == 80
    check env.stockpileCount(0, ResourceGold) == 0    # Sent all 100
    check env.stockpileCount(1, ResourceGold) == 80   # Received after tax

  test "coinage tech reduces tax to 10%":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 100)
    # Research Coinage tech for sending team
    env.teamUniversityTechs[0].researched[TechCoinage] = true

    let received = env.tributeResources(0, 1, ResourceGold, 100)

    # Coinage reduces tax from 20% to 10%, so 90 received
    check received == 90
    check env.stockpileCount(0, ResourceGold) == 0    # Sent all 100
    check env.stockpileCount(1, ResourceGold) == 90   # Reduced tax

  test "coinage on receiver team does not affect tax":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 100)
    # Coinage on receiver, not sender
    env.teamUniversityTechs[1].researched[TechCoinage] = true

    let received = env.tributeResources(0, 1, ResourceGold, 100)

    # Tax should still be 20% because sender lacks Coinage
    check received == 80

suite "Tribute - Validation":
  test "cannot tribute negative amounts":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 100)

    let received = env.tributeResources(0, 1, ResourceGold, -5)

    check received == 0
    check env.stockpileCount(0, ResourceGold) == 100  # Unchanged
    check env.stockpileCount(1, ResourceGold) == 0    # Unchanged

  test "cannot tribute zero":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 100)

    let received = env.tributeResources(0, 1, ResourceGold, 0)

    check received == 0
    check env.stockpileCount(0, ResourceGold) == 100

  test "cannot tribute more than available":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 10)

    let received = env.tributeResources(0, 1, ResourceGold, 50)

    check received == 0
    check env.stockpileCount(0, ResourceGold) == 10  # Unchanged
    check env.stockpileCount(1, ResourceGold) == 0   # Unchanged

  test "cannot tribute to own team":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 100)

    let received = env.tributeResources(0, 0, ResourceGold, 50)

    check received == 0
    check env.stockpileCount(0, ResourceGold) == 100  # Unchanged

  test "cannot tribute ResourceNone":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 100)

    let received = env.tributeResources(0, 1, ResourceNone, 50)

    check received == 0

  test "invalid team IDs return zero":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 100)

    check env.tributeResources(-1, 1, ResourceGold, 50) == 0
    check env.tributeResources(0, -1, ResourceGold, 50) == 0
    check env.tributeResources(99, 1, ResourceGold, 50) == 0
    check env.tributeResources(0, 99, ResourceGold, 50) == 0

suite "Tribute - Cumulative Tracking":
  test "tribute sent and received counters accumulate":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 200)

    discard env.tributeResources(0, 1, ResourceGold, 50)
    discard env.tributeResources(0, 2, ResourceGold, 30)

    # Sent counter: 50 + 30 = 80
    check env.teamTributesSent[0] == 80
    # Received counters: 40 (50 - 20% tax), 24 (30 - 20% tax)
    check env.teamTributesReceived[1] == 40
    check env.teamTributesReceived[2] == 24
    # Team 0 received nothing
    check env.teamTributesReceived[0] == 0

  test "failed tributes do not affect counters":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceGold, 5)

    # This should fail (not enough resources)
    discard env.tributeResources(0, 1, ResourceGold, 50)

    check env.teamTributesSent[0] == 0
    check env.teamTributesReceived[1] == 0
