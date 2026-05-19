import std/[unittest, strformat]
import test_common

## Behavioral victory tests that verify victory conditions work in multi-step games.
## These use controlled setups with fixed seeds to simulate realistic victory scenarios
## and check that victories trigger correctly with proper rewards and state changes.

suite "Behavioral Victory - Wonder Victory":
  test "wonder victory triggers after countdown in multi-step game":
    ## Build a wonder for team 0, advance game steps past the countdown,
    ## and verify the wonder victory triggers with correct winner.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 100

    # Team 0 with an agent
    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    # Team 1 with an agent (opponent must exist)
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    # Build a completed wonder for team 0
    let wonder = addBuilding(env, Wonder, ivec2(15, 10), 0)

    echo fmt"  Wonder HP: {wonder.hp}/{wonder.maxHp}"
    echo fmt"  Victory condition: VictoryWonder"

    # Step once to register the wonder
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep >= 0
    check env.victoryWinner == -1

    let builtStep = env.victoryStates[0].wonderBuiltStep
    echo fmt"  Wonder registered at step: {builtStep}"

    # Advance to just before countdown expires
    env.currentStep = builtStep + WonderVictoryCountdown - 2
    env.stepNoop()
    check env.victoryWinner == -1  # Not yet
    echo fmt"  Step {env.currentStep}: No winner yet (countdown not expired)"

    # Advance past countdown
    env.currentStep = builtStep + WonderVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true
    echo fmt"  Step {env.currentStep}: Team 0 wins by Wonder victory!"

  test "wonder victory does not trigger if wonder destroyed before countdown":
    ## Build a wonder, then destroy it before the countdown expires.
    ## Verify that no victory is awarded.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    let wonder = addBuilding(env, Wonder, ivec2(15, 10), 0)

    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep >= 0

    echo fmt"  Wonder built, countdown started"

    # Destroy the wonder mid-countdown
    env.grid[wonder.pos.x][wonder.pos.y] = nil
    env.thingsByKind[Wonder].setLen(0)
    env.stepNoop()

    check env.victoryStates[0].wonderBuiltStep == -1
    check env.victoryWinner == -1
    echo fmt"  Wonder destroyed - countdown reset, no winner"

    # Advance past where countdown would have expired
    env.currentStep = WonderVictoryCountdown + 50
    env.stepNoop()
    check env.victoryWinner == -1
    echo fmt"  Past countdown window: still no winner (wonder was destroyed)"

  test "wonder victory awards reward to winning team":
    ## Verify that agents on the winning team receive VictoryReward.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))
    discard addBuilding(env, Wonder, ivec2(15, 10), 0)

    env.stepNoop()
    let builtStep = env.victoryStates[0].wonderBuiltStep
    let rewardBefore = agent0.reward

    # Trigger victory
    env.currentStep = builtStep + WonderVictoryCountdown
    env.stepNoop()

    check env.victoryWinner == 0
    check agent0.reward > rewardBefore
    echo fmt"  Winner reward: {rewardBefore} -> {agent0.reward} (gained {agent0.reward - rewardBefore})"

    # Winner should be truncated (episode ended), not terminated (killed)
    check env.truncated[0] == 1.0
    check env.terminated[0] == 0.0
    echo fmt"  Winner agent truncated (not terminated) - correct episode end"

suite "Behavioral Victory - Relic Victory":
  test "relic victory triggers after holding all relics for countdown":
    ## Garrison all relics in a monastery, advance past countdown,
    ## and verify relic victory triggers.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRelic
    env.config.maxSteps = RelicVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    # Build a monastery and garrison all relics
    let monastery = addBuilding(env, Monastery, ivec2(15, 10), 0)
    monastery.garrisonedRelics = TotalRelicsOnMap

    echo fmt"  Relics garrisoned: {monastery.garrisonedRelics}/{TotalRelicsOnMap}"

    env.stepNoop()
    check env.victoryStates[0].relicHoldStartStep >= 0
    check env.victoryWinner == -1

    let holdStart = env.victoryStates[0].relicHoldStartStep
    echo fmt"  Relic hold started at step: {holdStart}"

    # Advance to just before countdown expires
    env.currentStep = holdStart + RelicVictoryCountdown - 2
    env.stepNoop()
    check env.victoryWinner == -1
    echo fmt"  Step {env.currentStep}: No winner yet (countdown not expired)"

    # Advance past countdown
    env.currentStep = holdStart + RelicVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true
    echo fmt"  Step {env.currentStep}: Team 0 wins by Relic victory!"

  test "relic victory with relics spread across multiple monasteries":
    ## Distribute relics across two monasteries and verify victory still triggers.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRelic
    env.config.maxSteps = RelicVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    let m1 = addBuilding(env, Monastery, ivec2(15, 10), 0)
    let m2 = addBuilding(env, Monastery, ivec2(20, 10), 0)

    # Split relics between monasteries
    let half = TotalRelicsOnMap div 2
    let remainder = TotalRelicsOnMap - half
    m1.garrisonedRelics = half
    m2.garrisonedRelics = remainder

    echo fmt"  Monastery 1 relics: {m1.garrisonedRelics}, Monastery 2 relics: {m2.garrisonedRelics}"
    echo fmt"  Total: {m1.garrisonedRelics + m2.garrisonedRelics}/{TotalRelicsOnMap}"

    env.stepNoop()
    check env.victoryStates[0].relicHoldStartStep >= 0

    let holdStart = env.victoryStates[0].relicHoldStartStep
    env.currentStep = holdStart + RelicVictoryCountdown
    env.stepNoop()

    check env.victoryWinner == 0
    check env.shouldReset == true
    echo fmt"  Relic victory with split monasteries!"

  test "relic victory resets when monastery destroyed mid-countdown":
    ## Start a relic hold, destroy the monastery, and verify hold resets.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRelic
    env.config.maxSteps = RelicVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    let monastery = addBuilding(env, Monastery, ivec2(15, 10), 0)
    monastery.garrisonedRelics = TotalRelicsOnMap

    env.stepNoop()
    check env.victoryStates[0].relicHoldStartStep >= 0
    echo fmt"  Relic hold started"

    # Destroy monastery - relics drop
    discard env.applyStructureDamage(monastery, monastery.hp + 1)
    env.stepNoop()

    check env.victoryStates[0].relicHoldStartStep == -1
    check env.victoryWinner == -1
    echo fmt"  Monastery destroyed - relics dropped, hold reset"

    # Advance past original countdown - should not trigger victory
    env.currentStep = RelicVictoryCountdown + 50
    env.stepNoop()
    check env.victoryWinner == -1
    echo fmt"  Past countdown: no winner (monastery was destroyed)"

  test "relic victory awards reward to winning team":
    ## Verify relic victory properly rewards the winning team's agents.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRelic
    env.config.maxSteps = RelicVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    let monastery = addBuilding(env, Monastery, ivec2(15, 10), 0)
    monastery.garrisonedRelics = TotalRelicsOnMap

    env.stepNoop()
    let holdStart = env.victoryStates[0].relicHoldStartStep
    let rewardBefore = agent0.reward

    env.currentStep = holdStart + RelicVictoryCountdown
    env.stepNoop()

    check env.victoryWinner == 0
    check agent0.reward > rewardBefore
    check env.truncated[0] == 1.0
    check env.terminated[0] == 0.0
    echo fmt"  Relic victory reward: {rewardBefore} -> {agent0.reward}"

suite "Behavioral Victory - Conquest Victory":
  test "conquest victory when all enemy units eliminated":
    ## Team 0 has a living agent, team 1 has all agents terminated.
    ## Verify conquest victory triggers for team 0.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    discard addAltar(env, ivec2(12, 10), 0, 5)

    # Team 1 agent exists but is terminated
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil

    echo fmt"  Team 0 alive: agent at (10,10)"
    echo fmt"  Team 1: all agents terminated"

    env.stepNoop()

    check env.victoryWinner == 0
    check env.shouldReset == true
    echo fmt"  Conquest victory: Team 0 wins!"

  test "conquest victory through combat - attacker kills defender":
    ## Set up a 1v1 combat scenario where attacker kills defender,
    ## then verify conquest victory triggers.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest

    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight, stance = StanceAggressive)
    applyUnitClass(attacker, UnitKnight)
    discard addAltar(env, ivec2(12, 10), 0, 5)

    let defender = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11), unitClass = UnitVillager)
    defender.hp = 3  # Low HP so combat resolves quickly

    echo fmt"  Attacker (Knight) HP: {attacker.hp}, Defender (Villager) HP: {defender.hp}"

    # Attack until defender dies
    var rounds = 0
    while defender.hp > 0 and rounds < 50:
      env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, defender.pos))
      inc rounds

    echo fmt"  Combat resolved in {rounds} rounds"
    check defender.hp <= 0
    check env.terminated[MapAgentsPerTeam] == 1.0

    # Step to trigger victory check
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true
    echo fmt"  Conquest victory after eliminating all enemies!"

  test "no conquest victory while both teams have units":
    ## Verify conquest does not trigger while both teams still have units.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    env.stepNoop()

    check env.victoryWinner == -1
    check env.shouldReset == false
    echo fmt"  Both teams alive: no conquest victory (correct)"

  test "conquest victory awards reward to winner":
    ## Verify conquest victory properly rewards the winning team.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    discard addAltar(env, ivec2(12, 10), 0, 5)

    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil

    let rewardBefore = agent0.reward
    env.stepNoop()

    check env.victoryWinner == 0
    check agent0.reward > rewardBefore
    check env.truncated[0] == 1.0
    check env.terminated[0] == 0.0
    echo fmt"  Conquest reward: {rewardBefore} -> {agent0.reward}"

suite "Behavioral Victory - Victory Events and State":
  test "victory sets shouldReset flag":
    ## Verify that any victory condition sets shouldReset to true.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    discard addAltar(env, ivec2(12, 10), 0, 5)
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil

    check env.shouldReset == false
    env.stepNoop()
    check env.shouldReset == true
    echo fmt"  shouldReset correctly set to true on victory"

  test "victoryWinner correctly identifies winning team":
    ## Verify victoryWinner is set to the correct team index.
    # Team 0 wins conquest
    let env0 = makeEmptyEnv()
    env0.config.victoryCondition = VictoryConquest
    discard addAgentAt(env0, 0, ivec2(10, 10))
    discard addAltar(env0, ivec2(12, 10), 0, 5)
    let e0 = addAgentAt(env0, MapAgentsPerTeam, ivec2(20, 20))
    env0.terminated[MapAgentsPerTeam] = 1.0
    env0.grid[20][20] = nil
    env0.stepNoop()
    check env0.victoryWinner == 0
    echo fmt"  Team 0 conquest: victoryWinner = {env0.victoryWinner}"

  test "winning team agents are truncated, not terminated":
    ## Victory ends the episode (truncation) but doesn't kill agents (termination).
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))
    discard addBuilding(env, Wonder, ivec2(15, 10), 0)

    env.stepNoop()
    let builtStep = env.victoryStates[0].wonderBuiltStep
    env.currentStep = builtStep + WonderVictoryCountdown
    env.stepNoop()

    check env.victoryWinner == 0
    # Winner is truncated (episode over) but not terminated (not dead)
    check env.truncated[0] == 1.0
    check env.terminated[0] == 0.0
    echo fmt"  Winner: truncated={env.truncated[0]} terminated={env.terminated[0]}"

  test "VictoryAll mode accepts any victory condition":
    ## Verify VictoryAll triggers on wonder, relic, or conquest.
    # Test wonder path
    let envW = makeEmptyEnv()
    envW.config.victoryCondition = VictoryAll
    envW.config.maxSteps = WonderVictoryCountdown + 100
    discard addAgentAt(envW, 0, ivec2(10, 10))
    discard addAgentAt(envW, MapAgentsPerTeam, ivec2(50, 50))
    discard addBuilding(envW, Wonder, ivec2(15, 10), 0)
    envW.stepNoop()
    let wStep = envW.victoryStates[0].wonderBuiltStep
    envW.currentStep = wStep + WonderVictoryCountdown
    envW.stepNoop()
    check envW.victoryWinner == 0
    echo fmt"  VictoryAll - Wonder path: winner = {envW.victoryWinner}"

    # Test relic path
    let envR = makeEmptyEnv()
    envR.config.victoryCondition = VictoryAll
    envR.config.maxSteps = RelicVictoryCountdown + 100
    discard addAgentAt(envR, 0, ivec2(10, 10))
    discard addAgentAt(envR, MapAgentsPerTeam, ivec2(50, 50))
    let mon = addBuilding(envR, Monastery, ivec2(15, 10), 0)
    mon.garrisonedRelics = TotalRelicsOnMap
    envR.stepNoop()
    let rStep = envR.victoryStates[0].relicHoldStartStep
    envR.currentStep = rStep + RelicVictoryCountdown
    envR.stepNoop()
    check envR.victoryWinner == 0
    echo fmt"  VictoryAll - Relic path: winner = {envR.victoryWinner}"

    # Test conquest path
    let envC = makeEmptyEnv()
    envC.config.victoryCondition = VictoryAll
    discard addAgentAt(envC, 0, ivec2(10, 10))
    discard addAltar(envC, ivec2(12, 10), 0, 5)
    let e1 = addAgentAt(envC, MapAgentsPerTeam, ivec2(20, 20))
    envC.terminated[MapAgentsPerTeam] = 1.0
    envC.grid[20][20] = nil
    envC.stepNoop()
    check envC.victoryWinner == 0
    echo fmt"  VictoryAll - Conquest path: winner = {envC.victoryWinner}"

  test "no victory triggers with VictoryNone":
    ## Verify VictoryNone disables all victory conditions.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    env.config.maxSteps = 5000

    # Set up a scenario that would normally trigger conquest
    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil

    env.stepNoop()
    check env.victoryWinner == -1
    echo fmt"  VictoryNone: no winner despite only one team remaining"
