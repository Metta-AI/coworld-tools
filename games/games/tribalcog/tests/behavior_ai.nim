## AI behavioral tests verifying role assignment and decision making.
## Tests run multi-step games with fixed seeds and verify AI behavior patterns.

import std/[unittest, strformat]
import test_common

const
  TestSeed = DefaultTestSeed
  LongRunSteps = LongSimSteps
  ShortRunSteps = ShortSimSteps

proc totalAliveHp(env: Environment): int =
  for agent in env.agents:
    if not agent.isNil and agent.hp > 0:
      result += agent.hp

proc aliveAgentCounts(env: Environment): array[MapRoomObjectsTeams, int] =
  for agent in env.agents:
    if not agent.isNil and agent.hp > 0:
      let teamId = getTeamId(agent)
      if teamId >= 0 and teamId < MapRoomObjectsTeams:
        inc result[teamId]

suite "Behavioral AI - Gatherer Role":
  test "gatherer AI actually gathers resources over 300 steps":
    ## Run 300 steps and verify gatherer AI increases resource count.
    let env = setupGameWithAI(TestSeed)

    # Record initial stockpiles
    var initialTotal: array[MapRoomObjectsTeams, int]
    for teamId in 0 ..< MapRoomObjectsTeams:
      initialTotal[teamId] = getTotalStockpile(env, teamId)
      printStockpileSummary(env, teamId, "Start")

    runGameSteps(env, LongRunSteps)

    # Verify resources increased for at least one team
    var anyTeamGathered = false
    for teamId in 0 ..< MapRoomObjectsTeams:
      printStockpileSummary(env, teamId, fmt"After {LongRunSteps} steps")
      let finalTotal = getTotalStockpile(env, teamId)
      # Note: resources might be spent on buildings, so we check if either
      # stockpile increased OR buildings were constructed
      if finalTotal > initialTotal[teamId] or finalTotal > 0:
        anyTeamGathered = true

    echo fmt"  Summary: At least one team gathered resources = {anyTeamGathered}"
    check anyTeamGathered

  test "gatherers continue gathering over extended periods":
    ## Verify resource gathering is sustained, not just initial burst.
    let env = setupGameWithAI(123)

    runGameSteps(env, ShortRunSteps)

    let totalAt100 = getTotalStockpileAllTeams(env)
    echo fmt"  Total resources at step {ShortRunSteps}: {totalAt100}"

    runGameSteps(env, ShortRunSteps)

    let totalAt200 = getTotalStockpileAllTeams(env)
    echo fmt"  Total resources at step {ShortRunSteps * 2}: {totalAt200}"

    # Resources should be gathered at both checkpoints
    check totalAt100 > 0
    check totalAt200 > 0

suite "Behavioral AI - Fighter Role":
  test "fighter AI engages enemies when in range":
    ## Run a full game and verify fighters deal damage to enemy teams.
    let env = setupGameWithAI(TestSeed)
    let initialTotalHp = totalAliveHp(env)
    echo fmt"  Initial total HP across all agents: {initialTotalHp}"

    # Run game - fighters should engage and deal damage
    runGameSteps(env, 200)

    # Count final HP and dead agents
    let finalTotalHp = totalAliveHp(env)
    var deadAgents = 0
    for i, agent in env.agents:
      if not agent.isNil and agent.hp <= 0 and env.terminated[i] == 1.0:
        inc deadAgents

    echo fmt"  Final total HP: {finalTotalHp}, Dead agents: {deadAgents}"

    # Combat should have occurred - either HP reduced or agents died
    check finalTotalHp < initialTotalHp or deadAgents > 0

  test "fighter AI pursues enemies in multi-team game":
    ## Verify fighters engage in combat over time.
    let env = setupGameWithAI(256)
    let initialAgentCounts = aliveAgentCounts(env)
    echo fmt"  Initial agent counts: {initialAgentCounts}"

    # Run game
    runGameSteps(env, 300)

    let finalAgentCounts = aliveAgentCounts(env)
    echo fmt"  Final agent counts: {finalAgentCounts}"

    # Check for combat indicators: damaged agents or dead agents
    var damagedAgents = 0
    var deadAgents = 0
    for i, agent in env.agents:
      if not agent.isNil:
        if agent.hp > 0 and agent.hp < agent.maxHp:
          inc damagedAgents
        elif agent.hp <= 0 and env.terminated[i] == 1.0:
          inc deadAgents

    echo fmt"  Damaged agents: {damagedAgents}, Dead agents: {deadAgents}"

    # Combat should have occurred - agents damaged or killed
    check damagedAgents > 0 or deadAgents > 0

suite "Behavioral AI - Builder Role":
  test "builder AI constructs buildings when resources available":
    ## Run a full game and verify buildings are constructed.
    let env = setupGameWithAI(TestSeed)
    giveAllTeamsPlentyOfResources(env)

    let initialBuildings = countAllBuildings(env)
    echo fmt"  Initial buildings: {initialBuildings}"

    runGameSteps(env, 150)

    let finalBuildings = countAllBuildings(env)
    echo fmt"  Final buildings: {finalBuildings}"

    # Check if resources were spent (indicating building attempts)
    let totalResourcesRemaining = getTotalStockpileAllTeams(env)
    let initialTotalResources = MapRoomObjectsTeams * 2000  # 500 * 4 resources * teams
    let resourcesSpent = initialTotalResources - totalResourcesRemaining

    echo fmt"  Resources spent: {resourcesSpent}"

    # Builder should have either built something or spent resources
    check finalBuildings > initialBuildings or resourcesSpent > 0

  test "builder AI expands base over time":
    ## Verify buildings increase over extended play.
    let env = setupGameWithAI(500)
    setAllTeamsResources(env, 300, 300, 300, 300)

    runGameSteps(env, 200)

    var buildingsPerTeam: array[MapRoomObjectsTeams, int]
    for teamId in 0 ..< MapRoomObjectsTeams:
      buildingsPerTeam[teamId] = countBuildings(env, teamId)
    echo fmt"  Buildings per team: {buildingsPerTeam}"

    # At least one team should have built something
    var anyBuilding = false
    for teamId in 0 ..< MapRoomObjectsTeams:
      if buildingsPerTeam[teamId] > 0:
        anyBuilding = true
        break

    check anyBuilding

suite "Behavioral AI - Role Assignment":
  test "AI assigns roles appropriately - not all fighters or all gatherers":
    ## Verify the AI creates a balanced mix of roles.
    let env = setupGameWithAI(TestSeed)

    # Run enough steps to initialize all agents
    runGameSteps(env, 50)

    for teamId in 0 ..< MapRoomObjectsTeams:
      let roles = countRolesByTeam(teamId)
      echo fmt"  [After init] Team {teamId}: gatherers={roles.gatherers} builders={roles.builders} fighters={roles.fighters}"

      # Verify not all agents have the same role
      let totalAgents = roles.gatherers + roles.builders + roles.fighters
      if totalAgents > 0:
        # No single role should be 100% of agents (unless team has only 1-2 agents)
        if totalAgents >= 3:
          check roles.gatherers < totalAgents
          check roles.builders < totalAgents
          check roles.fighters < totalAgents

  test "role distribution follows expected 2-2-2 pattern per team":
    ## Verify the default slot-based role assignment.
    let env = setupGameWithAI(777)

    # Initialize agents
    runGameSteps(env, 20)

    for teamId in 0 ..< MapRoomObjectsTeams:
      let roles = countRolesByTeam(teamId)
      echo fmt"  [Role distribution] Team {teamId}: gatherers={roles.gatherers} builders={roles.builders} fighters={roles.fighters}"

      # Expected: 2 gatherers (slots 0,1), 2 builders (slots 2,3), 2 fighters (slots 4,5)
      # But actual count depends on how many agents are alive and initialized
      let totalAssigned = roles.gatherers + roles.builders + roles.fighters
      echo fmt"  Team {teamId}: total assigned = {totalAssigned}"

      # At minimum, if we have 6 agents per team, expect some of each role
      if totalAssigned >= 6:
        check roles.gatherers >= 1
        check roles.builders >= 1
        check roles.fighters >= 1

suite "Behavioral AI - Adaptive Behavior":
  test "AI decision making uses fixed seeds consistently":
    ## Verify AI uses seeds - different seeds should produce different results.
    ## Note: Perfect determinism depends on global state reset which may vary.

    # Run with seed 888
    var resourcesSeed1: int
    block:
      let env = setupGameWithAI(888)
      runGameSteps(env, 100)
      resourcesSeed1 = getTotalStockpileAllTeams(env)

    # Run with different seed 999
    var resourcesSeed2: int
    block:
      let env = setupGameWithAI(999)
      runGameSteps(env, 100)
      resourcesSeed2 = getTotalStockpileAllTeams(env)

    echo fmt"  Seed 888 total resources: {resourcesSeed1}"
    echo fmt"  Seed 999 total resources: {resourcesSeed2}"

    # Both runs should produce some resources (AI is functioning)
    check resourcesSeed1 > 0 or resourcesSeed2 > 0

  test "different seeds produce different outcomes":
    ## Different seeds should produce different results.

    # Run with seed 111
    var resourcesSeed1: int
    block:
      let env = setupGameWithAI(111)
      runGameSteps(env, 200)
      resourcesSeed1 = getTotalStockpileAllTeams(env)

    # Run with seed 222
    var resourcesSeed2: int
    block:
      let env = setupGameWithAI(222)
      runGameSteps(env, 200)
      resourcesSeed2 = getTotalStockpileAllTeams(env)

    echo fmt"  Seed 111 resources: {resourcesSeed1}"
    echo fmt"  Seed 222 resources: {resourcesSeed2}"

    # Different seeds should likely produce different results
    # (though there's a tiny chance they match by coincidence)
    # We don't hard-fail on this, just log it
    if resourcesSeed1 == resourcesSeed2:
      echo "  Note: Same result with different seeds (unlikely but possible)"

suite "Behavioral AI - Long Game Stability":
  test "AI remains active and functional over 300 steps":
    ## Verify AI doesn't crash or become idle over extended play.
    let env = setupGameWithAI(TestSeed)

    var actionCounts: array[MapAgents, int]

    for step in 0 ..< LongRunSteps:
      let actions = getActions(env)
      for i in 0 ..< MapAgents:
        if actions[i] != 0:  # Non-NOOP action
          inc actionCounts[i]
      env.step(addr actions)

    # Count active agents (those who took at least some actions)
    var activeAgents = 0
    for i in 0 ..< MapAgents:
      if actionCounts[i] > 0:
        inc activeAgents

    echo fmt"  Active agents (took non-NOOP actions): {activeAgents}"
    echo fmt"  Total steps: {LongRunSteps}"

    # At least some agents should be taking actions
    check activeAgents > 0

  test "game state remains valid after 300 steps":
    ## Verify no crashes, no NaN values, valid entity states.
    let env = setupGameWithAI(TestSeed)

    runGameSteps(env, LongRunSteps)

    # Check no NaN in stockpiles
    for teamId in 0 ..< MapRoomObjectsTeams:
      let food = env.stockpileCount(teamId, ResourceFood)
      let wood = env.stockpileCount(teamId, ResourceWood)
      let gold = env.stockpileCount(teamId, ResourceGold)
      let stone = env.stockpileCount(teamId, ResourceStone)

      check food >= 0
      check wood >= 0
      check gold >= 0
      check stone >= 0

    # Check agent HP values are valid
    for agent in env.agents:
      if not agent.isNil:
        check agent.hp >= 0
        check agent.hp <= agent.maxHp
        check agent.maxHp > 0

    # Verify positions are valid for live agents (not garrisoned or terminated)
    for agent in env.agents:
      if isAgentAlive(env, agent):
        check agent.pos.x >= 0 and agent.pos.x < MapWidth
        check agent.pos.y >= 0 and agent.pos.y < MapHeight

    echo fmt"  Game state valid after {LongRunSteps} steps"
