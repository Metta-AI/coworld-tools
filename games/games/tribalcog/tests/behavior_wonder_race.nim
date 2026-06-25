import std/[unittest, strformat]
import test_common

## Behavioral tests for the wonder race game mode: first team to build a wonder
## and survive the countdown wins, wonder destruction resets the countdown timer,
## and competing teams race to complete their wonder first. Uses 500-step sims.
    env.step(addr actions)

suite "Behavior: Wonder Race - First to Complete Wins":
  test "first team to build wonder starts countdown":
    ## Team 0 builds a wonder first; verify countdown begins for team 0
    ## and team 1 has no countdown active.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 500

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    # Team 0 builds a wonder
    discard addBuilding(env, Wonder, ivec2(15, 10), 0)

    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep >= 0
    check env.victoryStates[1].wonderBuiltStep == -1
    check env.victoryWinner == -1
    echo fmt"  Team 0 wonder registered at step {env.victoryStates[0].wonderBuiltStep}"
    echo fmt"  Team 1 has no wonder (wonderBuiltStep={env.victoryStates[1].wonderBuiltStep})"

  test "first team to survive wonder countdown wins the race":
    ## Team 0 builds a wonder and survives the full countdown.
    ## Verify team 0 wins and the game resets.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    discard addBuilding(env, Wonder, ivec2(15, 10), 0)

    env.stepNoop()
    let builtStep = env.victoryStates[0].wonderBuiltStep
    check builtStep >= 0

    # Advance to just before countdown expires - no winner yet
    env.currentStep = builtStep + WonderVictoryCountdown - 2
    env.stepNoop()
    check env.victoryWinner == -1
    echo fmt"  Step {env.currentStep}: countdown not expired, no winner"

    # Advance past countdown - team 0 wins
    env.currentStep = builtStep + WonderVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true
    echo fmt"  Step {env.currentStep}: Team 0 wins the wonder race!"

  test "team 1 can win wonder race if they build first":
    ## Team 1 builds a wonder (team 0 does not). Team 1 wins after countdown.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    # Only team 1 builds a wonder
    discard addBuilding(env, Wonder, ivec2(55, 50), 1)

    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep == -1
    check env.victoryStates[1].wonderBuiltStep >= 0
    echo fmt"  Team 1 wonder registered at step {env.victoryStates[1].wonderBuiltStep}"

    let builtStep = env.victoryStates[1].wonderBuiltStep
    env.currentStep = builtStep + WonderVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 1
    check env.shouldReset == true
    echo fmt"  Team 1 wins the wonder race!"

suite "Behavior: Wonder Race - Destruction Resets Timer":
  test "destroying wonder resets countdown for that team":
    ## Team 0 builds wonder, then it is destroyed. Verify countdown resets
    ## and no victory triggers even after enough time has passed.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 200

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    let wonder = addBuilding(env, Wonder, ivec2(15, 10), 0)

    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep >= 0
    echo fmt"  Wonder built, countdown started at step {env.victoryStates[0].wonderBuiltStep}"

    # Destroy the wonder by clearing it from the grid and thingsByKind
    env.grid[wonder.pos.x][wonder.pos.y] = nil
    env.thingsByKind[Wonder].setLen(0)
    env.stepNoop()

    check env.victoryStates[0].wonderBuiltStep == -1
    check env.victoryWinner == -1
    echo fmt"  Wonder destroyed - countdown reset (wonderBuiltStep={env.victoryStates[0].wonderBuiltStep})"

    # Advance well past where countdown would have expired
    env.currentStep = WonderVictoryCountdown + 100
    env.stepNoop()
    check env.victoryWinner == -1
    echo fmt"  Step {env.currentStep}: no winner (wonder was destroyed)"

  test "rebuilding wonder after destruction starts fresh countdown":
    ## Team 0 builds wonder, it gets destroyed, then team 0 rebuilds.
    ## Verify the new wonder starts a fresh countdown from the rebuild step.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown * 2 + 200

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    # Build first wonder
    let wonder1 = addBuilding(env, Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    let firstBuiltStep = env.victoryStates[0].wonderBuiltStep
    check firstBuiltStep >= 0
    echo fmt"  First wonder built at step {firstBuiltStep}"

    # Destroy it
    env.grid[wonder1.pos.x][wonder1.pos.y] = nil
    env.thingsByKind[Wonder].setLen(0)
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep == -1
    echo fmt"  First wonder destroyed"

    # Advance to a later step and rebuild
    env.currentStep = WonderVictoryCountdown + 50
    discard addBuilding(env, Wonder, ivec2(20, 10), 0)
    env.stepNoop()

    let secondBuiltStep = env.victoryStates[0].wonderBuiltStep
    check secondBuiltStep >= 0
    check secondBuiltStep > firstBuiltStep
    echo fmt"  Second wonder built at step {secondBuiltStep}"

    # Verify victory triggers from the NEW countdown, not the old one
    env.currentStep = secondBuiltStep + WonderVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true
    echo fmt"  Victory at step {env.currentStep} (from rebuild countdown)"

  test "destruction mid-countdown prevents imminent victory":
    ## Team 0 builds wonder and is close to winning. Destroy it just before
    ## countdown expires and verify no victory triggers.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 200

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    let wonder = addBuilding(env, Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    let builtStep = env.victoryStates[0].wonderBuiltStep

    # Advance to near the end of countdown
    env.currentStep = builtStep + WonderVictoryCountdown - 3
    env.stepNoop()
    check env.victoryWinner == -1
    echo fmt"  Step {env.currentStep}: 3 steps from victory..."

    # Destroy wonder just before countdown expires
    env.grid[wonder.pos.x][wonder.pos.y] = nil
    env.thingsByKind[Wonder].setLen(0)
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep == -1
    echo fmt"  Wonder destroyed at the last moment!"

    # Advance past where countdown would have expired
    env.currentStep = builtStep + WonderVictoryCountdown + 10
    env.stepNoop()
    check env.victoryWinner == -1
    echo fmt"  Step {env.currentStep}: no victory (wonder was destroyed in time)"

suite "Behavior: Wonder Race - Competing Teams":
  test "both teams build wonders, first to complete countdown wins":
    ## Both teams build wonders at different times. The team that built
    ## first (earlier wonderBuiltStep) should win first.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 200

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    # Team 0 builds wonder first
    discard addBuilding(env, Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    let team0BuiltStep = env.victoryStates[0].wonderBuiltStep
    check team0BuiltStep >= 0
    echo fmt"  Team 0 wonder built at step {team0BuiltStep}"

    # Team 1 builds wonder later (a few steps behind)
    env.currentStep = team0BuiltStep + 10
    discard addBuilding(env, Wonder, ivec2(55, 50), 1)
    env.stepNoop()
    let team1BuiltStep = env.victoryStates[1].wonderBuiltStep
    check team1BuiltStep >= 0
    check team1BuiltStep > team0BuiltStep
    echo fmt"  Team 1 wonder built at step {team1BuiltStep}"

    # Team 0's countdown expires first
    env.currentStep = team0BuiltStep + WonderVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true
    echo fmt"  Team 0 wins - their countdown expired first!"

  test "destroying leader's wonder lets trailing team win":
    ## Team 0 builds first, team 1 builds second. Team 0's wonder is destroyed.
    ## Team 1 then wins when their countdown completes.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown * 2 + 200

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    # Team 0 builds first
    let wonder0 = addBuilding(env, Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    let team0BuiltStep = env.victoryStates[0].wonderBuiltStep
    echo fmt"  Team 0 wonder built at step {team0BuiltStep}"

    # Team 1 builds 20 steps later
    env.currentStep = team0BuiltStep + 20
    discard addBuilding(env, Wonder, ivec2(55, 50), 1)
    env.stepNoop()
    let team1BuiltStep = env.victoryStates[1].wonderBuiltStep
    echo fmt"  Team 1 wonder built at step {team1BuiltStep}"

    # Destroy team 0's wonder mid-race
    env.currentStep = team0BuiltStep + 100
    env.grid[wonder0.pos.x][wonder0.pos.y] = nil
    # Remove only team 0's wonder from thingsByKind
    var newWonders: seq[Thing]
    for w in env.thingsByKind[Wonder]:
      if w.teamId != 0:
        newWonders.add(w)
    env.thingsByKind[Wonder] = newWonders
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep == -1
    echo fmt"  Team 0's wonder destroyed at step {env.currentStep}"

    # Team 1's countdown completes
    env.currentStep = team1BuiltStep + WonderVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 1
    check env.shouldReset == true
    echo fmt"  Team 1 wins at step {env.currentStep} after team 0's wonder fell!"

  test "no winner when neither team has a wonder":
    ## Neither team builds a wonder. Verify no victory triggers
    ## even after many steps.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 500

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    check env.victoryStates[0].wonderBuiltStep == -1
    check env.victoryStates[1].wonderBuiltStep == -1

    env.stepNoop()
    check env.victoryWinner == -1

    env.currentStep = 400
    env.stepNoop()
    check env.victoryWinner == -1
    check env.shouldReset == false
    echo fmt"  No wonders built after 400 steps - no winner (correct)"

suite "Behavior: Wonder Race - 500-Step Simulation":
  test "wonder race resolves within 500-step sim when countdown fits":
    ## Build a wonder early enough that the countdown can complete within
    ## 500 steps. Verify the game ends with a winner.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 500

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    # Build wonder at step 0 - if WonderVictoryCountdown <= 500, victory occurs
    discard addBuilding(env, Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    let builtStep = env.victoryStates[0].wonderBuiltStep
    echo fmt"  Wonder built at step {builtStep}, countdown={WonderVictoryCountdown}"

    if WonderVictoryCountdown <= 500:
      # Run the full 500-step sim
      for step in (env.currentStep + 1) ..< 500:
        env.currentStep = step
        env.stepNoop()
        if env.victoryWinner >= 0:
          break

      check env.victoryWinner == 0
      echo fmt"  Wonder race resolved: Team 0 wins within 500 steps"
    else:
      # Countdown exceeds 500 steps - game ends by maxSteps
      env.currentStep = 499
      env.stepNoop()
      echo fmt"  Countdown ({WonderVictoryCountdown}) exceeds 500 steps - no winner in sim window"

  test "500-step sim with wonder destruction and rebuild":
    ## Run a 500-step scenario: team 0 builds wonder, it's destroyed,
    ## then team 1 builds one. Check final state is consistent.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 500

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    # Phase 1: Team 0 builds wonder (step 0)
    let wonder0 = addBuilding(env, Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep >= 0
    echo fmt"  Phase 1: Team 0 wonder built at step {env.victoryStates[0].wonderBuiltStep}"

    # Phase 2: Destroy team 0's wonder at step 50
    env.currentStep = 50
    env.grid[wonder0.pos.x][wonder0.pos.y] = nil
    env.thingsByKind[Wonder].setLen(0)
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep == -1
    check env.victoryWinner == -1
    echo fmt"  Phase 2: Team 0's wonder destroyed at step 50"

    # Phase 3: Team 1 builds wonder at step 100
    env.currentStep = 100
    discard addBuilding(env, Wonder, ivec2(55, 50), 1)
    env.stepNoop()
    let team1BuiltStep = env.victoryStates[1].wonderBuiltStep
    check team1BuiltStep >= 0
    echo fmt"  Phase 3: Team 1 wonder built at step {team1BuiltStep}"

    # Phase 4: Advance through remaining steps until victory
    env.currentStep = team1BuiltStep + WonderVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 1
    check env.shouldReset == true
    echo fmt"  Phase 4: Team 1 wins at step {env.currentStep}!"

  test "wonder victory awards correct rewards in race scenario":
    ## Verify that the winning team receives VictoryReward and the episode
    ## ends with truncation (not termination) in a wonder race.
    let env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = WonderVictoryCountdown + 100

    let agent0 = addAgentAt(env, 0, ivec2(10, 10))
    let agent1 = addAgentAt(env, MapAgentsPerTeam, ivec2(50, 50))

    discard addBuilding(env, Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    let builtStep = env.victoryStates[0].wonderBuiltStep
    let rewardBefore0 = agent0.reward
    let rewardBefore1 = agent1.reward

    # Trigger victory
    env.currentStep = builtStep + WonderVictoryCountdown
    env.stepNoop()

    check env.victoryWinner == 0
    check agent0.reward > rewardBefore0
    echo fmt"  Winner (team 0) reward: {rewardBefore0} -> {agent0.reward}"

    # Winner is truncated (episode end) not terminated (killed)
    check env.truncated[0] == 1.0
    check env.terminated[0] == 0.0
    echo fmt"  Winner truncated={env.truncated[0]}, terminated={env.terminated[0]} (correct episode end)"
