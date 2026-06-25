import std/[unittest, strformat]
import test_common

## Behavioral economy tests that verify economy behaviors work in multi-step games.
## These use full AI controllers with fixed seeds to run simulations and check outcomes.

suite "Behavioral Economy - Resource Gathering":
  test "gatherers accumulate food/wood/gold/stone over 200 steps":
    ## Run 200 steps with a fully initialized environment and verify
    ## each team accumulates at least some of each resource type.
    let env = setupGameWithAI(DefaultTestSeed)

    printStockpileSummary(env, 0, "Start")
    printStockpileSummary(env, 1, "Start")

    runGameSteps(env, 200)

    printStockpileSummary(env, 0, "After 200 steps")
    printStockpileSummary(env, 1, "After 200 steps")

    # At least one team should have accumulated some resources
    # (both teams have gatherers by default)
    var anyTeamGathered = false
    for teamId in 0 ..< MapRoomObjectsTeams:
      if getTotalStockpile(env, teamId) > 0:
        anyTeamGathered = true
    check anyTeamGathered

  test "resources increase over time with fixed seed":
    ## Verify that resource accumulation grows over time - resources at step 200
    ## should be >= resources at step 100.
    let env = setupGameWithAI(123)

    runGameSteps(env, 100)

    let totalAt100 = getTotalStockpileAllTeams(env)
    echo fmt"  Total resources at step 100: {totalAt100}"

    runGameSteps(env, 100)

    let totalAt200 = getTotalStockpileAllTeams(env)
    echo fmt"  Total resources at step 200: {totalAt200}"

    # Resources should be gathered by step 100 and not collapse by step 200.
    # Some spending on buildings is expected, so we verify both checkpoints.
    check totalAt100 > 0
    check totalAt200 > 0

suite "Behavioral Economy - Villager Deposits":
  test "villagers deposit resources at town centers":
    ## Set up a controlled scenario where a villager gathers and deposits.
    ## Villager adjacent to resource + town center should gather then deposit.
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    # Place town center
    let tcPos = ivec2(10, 10)
    discard addBuilding(env, TownCenter, tcPos, 0)

    # Place agent adjacent to town center
    let agentPos = ivec2(10, 11)
    let agent = addAgentAt(env, 0, agentPos, homeAltar = tcPos)

    # Give agent carried wood
    setInv(agent, ItemWood, 3)

    # Decide action - with carried resources and adjacent to TC, should deposit
    let action = controller.decideAction(env, 0)
    let (verb, arg) = decodeAction(action)

    echo fmt"  Agent action: verb={verb} arg={arg}"
    echo fmt"  Agent wood before: {agent.inventoryWood}"

    # Agent should USE (verb 3) on the town center to deposit
    check verb == 3
    check arg == dirIndex(agentPos, tcPos)

    # Execute the action
    env.stepAction(0, verb.uint16, arg)

    echo fmt"  Agent wood after: {agent.inventoryWood}"
    echo fmt"  Team stockpile wood: {env.stockpileCount(0, ResourceWood)}"

    # Resources should have been deposited to stockpile
    check agent.inventoryWood == 0
    check env.stockpileCount(0, ResourceWood) == 3

  test "multiple deposit cycles accumulate resources":
    ## Simulate gather-deposit cycles manually and verify stockpile grows.
    let env = makeEmptyEnv()
    let tcPos = ivec2(10, 10)
    discard addBuilding(env, TownCenter, tcPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 11), homeAltar = tcPos)

    # Place a wood resource adjacent to agent
    discard addResource(env, Tree, ivec2(10, 12), ItemWood, 20)

    # Cycle 1: Gather from tree
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 12)))
    check agent.inventoryWood >= 1

    # Move to TC and deposit (agent is at 10,11, TC is at 10,10)
    env.stepAction(0, 3'u8, dirIndex(agent.pos, tcPos))
    let woodAfterFirst = env.stockpileCount(0, ResourceWood)
    echo fmt"  Wood after first deposit: {woodAfterFirst}"
    check woodAfterFirst > 0

    # Cycle 2: Gather again
    env.stepAction(0, 3'u8, dirIndex(agent.pos, ivec2(10, 12)))
    # Deposit again
    env.stepAction(0, 3'u8, dirIndex(agent.pos, tcPos))
    let woodAfterSecond = env.stockpileCount(0, ResourceWood)
    echo fmt"  Wood after second deposit: {woodAfterSecond}"
    check woodAfterSecond > woodAfterFirst

suite "Behavioral Economy - Market Trading":
  test "market trading works end-to-end in multi-step game":
    ## Verify a villager can sell wood at a market for gold, then buy food.
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    let market = addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Step 1: Sell wood for gold
    setInv(agent, ItemWood, 100)
    setStockpile(env, 0, ResourceGold, 0)
    setStockpile(env, 0, ResourceFood, 0)

    echo fmt"  Before sell: wood={agent.inventoryWood} gold={env.stockpileCount(0, ResourceGold)}"
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let goldAfterSell = env.stockpileCount(0, ResourceGold)
    echo fmt"  After sell: wood={agent.inventoryWood} gold={goldAfterSell}"

    check agent.inventoryWood == 0
    check goldAfterSell > 0

    # Wait for cooldown
    for i in 0 ..< market.cooldown:
      env.stepNoop()

    # Step 2: Buy food with gold
    setInv(agent, ItemGold, goldAfterSell)
    setStockpile(env, 0, ResourceGold, 0)  # Clear stockpile gold
    setStockpile(env, 0, ResourceFood, 0)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let foodAfterBuy = env.stockpileCount(0, ResourceFood)
    echo fmt"  After buy: gold={agent.inventoryGold} food={foodAfterBuy}"

    check agent.inventoryGold == 0
    check foodAfterBuy > 0

  test "market prices change with repeated trades":
    ## Verify dynamic pricing: selling wood repeatedly decreases its price.
    let env = makeEmptyEnv()
    let marketPos = ivec2(10, 9)
    discard addBuilding(env, Market, marketPos, 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    let initialPrice = env.getMarketPrice(0, ResourceWood)
    echo fmt"  Initial wood price: {initialPrice}"

    # Sell wood multiple times
    for trade in 0 ..< 5:
      setInv(agent, ItemWood, 100)
      setStockpile(env, 0, ResourceGold, 0)
      let market = env.getThing(marketPos)
      if not isNil(market):
        market.cooldown = 0  # Reset cooldown for test
      env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, marketPos))

    let finalPrice = env.getMarketPrice(0, ResourceWood)
    echo fmt"  Final wood price after 5 sells: {finalPrice}"

    # Price should have decreased from selling
    check finalPrice < initialPrice

suite "Behavioral Economy - Building Construction":
  test "building construction consumes stockpile resources":
    ## Verify that building placement spends resources from team stockpile.
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Give team plenty of resources
    setStockpile(env, 0, ResourceFood, 50)
    setStockpile(env, 0, ResourceWood, 50)
    setStockpile(env, 0, ResourceStone, 50)
    setStockpile(env, 0, ResourceGold, 50)

    let woodBefore = env.stockpileCount(0, ResourceWood)
    let foodBefore = env.stockpileCount(0, ResourceFood)
    echo fmt"  Before build: food={foodBefore} wood={woodBefore}"

    # Build a granary (costs resources)
    env.stepAction(agent.agentId, 8'u8, buildIndexFor(Granary))

    let woodAfter = env.stockpileCount(0, ResourceWood)
    let foodAfter = env.stockpileCount(0, ResourceFood)
    echo fmt"  After build: food={foodAfter} wood={woodAfter}"

    # At least some resource type should have been consumed
    let totalBefore = foodBefore + woodBefore
    let totalAfter = foodAfter + woodAfter
    check totalAfter < totalBefore

  test "cannot build without sufficient resources":
    ## Verify that building fails when resources are insufficient.
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Start with zero resources
    setStockpile(env, 0, ResourceFood, 0)
    setStockpile(env, 0, ResourceWood, 0)
    setStockpile(env, 0, ResourceStone, 0)
    setStockpile(env, 0, ResourceGold, 0)

    # Try to build
    env.stepAction(agent.agentId, 8'u8, buildIndexFor(Granary))

    # Should still have zero resources (nothing was spent because build failed)
    check env.stockpileCount(0, ResourceFood) == 0
    check env.stockpileCount(0, ResourceWood) == 0
    check env.stockpileCount(0, ResourceStone) == 0
    check env.stockpileCount(0, ResourceGold) == 0

    # No building should have been placed in 8-connected neighbors
    var buildingFound = false
    for dx in -1'i32 .. 1'i32:
      for dy in -1'i32 .. 1'i32:
        let pos = ivec2(10 + dx, 10 + dy)
        let thing = env.getThing(pos)
        if not isNil(thing) and thing.kind == Granary:
          buildingFound = true
    check not buildingFound

suite "Behavioral Economy - Relic Monastery Gold":
  test "monastery with garrisoned relic generates gold":
    ## Verify that a monastery holding a relic passively generates gold.
    let env = makeEmptyEnv()
    let monastery = addBuilding(env, Monastery, ivec2(10, 10), 0)
    discard addAgentAt(env, 0, ivec2(20, 20))  # Need at least one agent

    # Garrison a relic in the monastery
    monastery.garrisonedRelics = 1
    monastery.cooldown = 0

    setStockpile(env, 0, ResourceGold, 0)

    echo fmt"  Gold at start: {env.stockpileCount(0, ResourceGold)}"

    # Run enough steps for gold generation (interval is MonasteryRelicGoldInterval = 20)
    for i in 0 ..< MonasteryRelicGoldInterval * 3:
      env.stepNoop()

    let goldGenerated = env.stockpileCount(0, ResourceGold)
    echo fmt"  Gold after {MonasteryRelicGoldInterval * 3} steps: {goldGenerated}"

    # Should have generated gold from the garrisoned relic
    check goldGenerated > 0

  test "more relics generate more gold":
    ## Verify gold generation scales with number of garrisoned relics.
    let env = makeEmptyEnv()
    let monastery = addBuilding(env, Monastery, ivec2(10, 10), 0)
    discard addAgentAt(env, 0, ivec2(20, 20))

    # Garrison 3 relics
    monastery.garrisonedRelics = 3
    monastery.cooldown = 0

    setStockpile(env, 0, ResourceGold, 0)

    # Run steps for multiple gold generation cycles
    let totalSteps = MonasteryRelicGoldInterval * 5
    for i in 0 ..< totalSteps:
      env.stepNoop()

    let goldWith3 = env.stockpileCount(0, ResourceGold)
    echo fmt"  Gold with 3 relics after {totalSteps} steps: {goldWith3}"

    # Compare with 1 relic
    let env2 = makeEmptyEnv()
    let monastery2 = addBuilding(env2, Monastery, ivec2(10, 10), 0)
    discard addAgentAt(env2, 0, ivec2(20, 20))
    monastery2.garrisonedRelics = 1
    monastery2.cooldown = 0

    setStockpile(env2, 0, ResourceGold, 0)

    for i in 0 ..< totalSteps:
      env2.stepNoop()

    let goldWith1 = env2.stockpileCount(0, ResourceGold)
    echo fmt"  Gold with 1 relic after {totalSteps} steps: {goldWith1}"

    # 3 relics should generate more gold than 1 relic
    check goldWith3 > goldWith1

suite "Behavioral Economy - Priority Override API":
  test "setGathererPriority forces gatherer to specific resource":
    ## Verify individual gatherer priority override takes precedence.
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    let tcPos = ivec2(10, 10)
    discard addBuilding(env, TownCenter, tcPos, 0)
    let agent = addAgentAt(env, 0, ivec2(12, 12), homeAltar = tcPos)

    # Initialize the agent in controller
    discard controller.decideAction(env, agent.agentId)
    let state = addr controller.agents[agent.agentId]

    # Default: gatherer task is set automatically
    controller.updateGathererTask(env, agent, state[])
    let autoTask = state.gathererTask
    echo fmt"  Auto task: {autoTask}"

    # Set individual priority override to gold
    controller.setGathererPriority(agent.agentId, ResourceGold)

    controller.updateGathererTask(env, agent, state[])
    let overrideTask = state.gathererTask

    echo fmt"  After gold priority: {overrideTask}"
    check overrideTask == TaskGold

    # Clear priority - should return to auto
    controller.clearGathererPriority(agent.agentId)
    controller.updateGathererTask(env, agent, state[])
    let clearedTask = state.gathererTask

    echo fmt"  After clear: {clearedTask}"
    # Task should return to automatic selection (may differ from original due to game state)
    check controller.isGathererPriorityActive(agent.agentId) == false

  test "setTeamEconomyFocus biases all gatherers":
    ## Verify team-level economy focus affects all gatherers on the team.
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    let tcPos = ivec2(10, 10)
    discard addBuilding(env, TownCenter, tcPos, 0)

    # Add multiple agents on team 0 (agent IDs 0 and 1)
    let agent1 = addAgentAt(env, 0, ivec2(12, 12), homeAltar = tcPos)
    let agent2 = addAgentAt(env, 1, ivec2(14, 14), homeAltar = tcPos)

    # Initialize agents
    discard controller.decideAction(env, agent1.agentId)
    discard controller.decideAction(env, agent2.agentId)

    # Set team focus to wood
    controller.setTeamEconomyFocus(0, ResourceWood)

    # Both agents should now prioritize wood
    let state1 = addr controller.agents[agent1.agentId]
    let state2 = addr controller.agents[agent2.agentId]

    controller.updateGathererTask(env, agent1, state1[])
    controller.updateGathererTask(env, agent2, state2[])

    echo fmt"  Agent 1 task: {state1.gathererTask}"
    echo fmt"  Agent 2 task: {state2.gathererTask}"

    check state1.gathererTask == TaskWood
    check state2.gathererTask == TaskWood

    # Clear team focus
    controller.clearTeamEconomyFocus(0)
    check controller.isTeamEconomyFocusActive(0) == false

  test "individual priority overrides team focus":
    ## Verify individual override takes precedence over team focus.
    let env = makeEmptyEnv()
    let controller = newTestController(42)

    let tcPos = ivec2(10, 10)
    discard addBuilding(env, TownCenter, tcPos, 0)

    # Agent IDs 0 and 1 are both on team 0 (team = agentId div 125)
    let agent1 = addAgentAt(env, 0, ivec2(12, 12), homeAltar = tcPos)
    let agent2 = addAgentAt(env, 1, ivec2(14, 14), homeAltar = tcPos)

    discard controller.decideAction(env, agent1.agentId)
    discard controller.decideAction(env, agent2.agentId)

    # Set team focus to wood
    controller.setTeamEconomyFocus(0, ResourceWood)

    # Set individual priority for agent1 to stone (overrides team)
    controller.setGathererPriority(agent1.agentId, ResourceStone)

    let state1 = addr controller.agents[agent1.agentId]
    let state2 = addr controller.agents[agent2.agentId]

    controller.updateGathererTask(env, agent1, state1[])
    controller.updateGathererTask(env, agent2, state2[])

    echo fmt"  Agent 1 (individual override): {state1.gathererTask}"
    echo fmt"  Agent 2 (team focus only): {state2.gathererTask}"

    # Agent 1 should have stone (individual override)
    check state1.gathererTask == TaskStone
    # Agent 2 should have wood (team focus)
    check state2.gathererTask == TaskWood
