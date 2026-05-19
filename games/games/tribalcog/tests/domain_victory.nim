import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import spatial_index
import test_utils

suite "Victory - Conquest":
  test "conquest victory when only one team remains":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    # Team 0 has an agent alive
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    # Team 1 agent is dead (terminated)
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20))
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil
    # Add an altar for team 0 so it counts as having units/buildings
    discard env.addAltar(ivec2(12, 10), 0, 5)
    env.stepNoop()
    # Only team 0 remains; all other teams have no units or buildings
    check env.victoryWinner == 0
    check env.shouldReset == true

  test "no conquest victory with multiple teams alive":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20))
    env.stepNoop()
    check env.victoryWinner == -1
    check env.shouldReset == false

  test "conquest victory not checked when VictoryNone":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    # Only one team has agents, but VictoryNone means no check
    env.stepNoop()
    check env.victoryWinner == -1

suite "Victory - Wonder":
  test "wonder victory after countdown expires":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000  # Ensure time limit doesn't interfere
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    # Build a Wonder for team 0
    let wonder = env.addBuilding(Wonder, ivec2(15, 10), 0)
    # Step once to register the wonder
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep >= 0
    check env.victoryWinner == -1  # Not enough time passed
    # Advance past countdown
    let startStep = env.victoryStates[0].wonderBuiltStep
    env.currentStep = startStep + WonderVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true

  test "wonder victory resets when wonder destroyed":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000
    discard env.addAgentAt(0, ivec2(10, 10))
    discard env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    let wonder = env.addBuilding(Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep >= 0
    # Destroy the wonder by removing from grid and kind list
    env.grid[wonder.pos.x][wonder.pos.y] = nil
    env.thingsByKind[Wonder].setLen(0)
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep == -1
    check env.victoryWinner == -1

  test "wonder under construction does not start countdown":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000
    discard env.addAgentAt(0, ivec2(10, 10))
    discard env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    # Place a wonder that is still under construction (hp=1, maxHp=80)
    let wonder = env.addBuilding(Wonder, ivec2(15, 10), 0)
    wonder.hp = 1  # Under construction
    env.stepNoop()
    # Countdown should NOT start for an incomplete wonder
    check env.victoryStates[0].wonderBuiltStep == -1
    check env.victoryWinner == -1

  test "wonder countdown starts only when fully built":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000
    discard env.addAgentAt(0, ivec2(10, 10))
    discard env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    let wonder = env.addBuilding(Wonder, ivec2(15, 10), 0)
    wonder.hp = 1  # Under construction
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep == -1  # Not tracked yet
    # Complete construction
    wonder.hp = wonder.maxHp
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep >= 0  # Now tracked

suite "Victory - Relic":
  test "relic victory after holding all relics":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRelic
    env.config.maxSteps = 5000
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    # Create a monastery with all relics garrisoned
    let monastery = env.addBuilding(Monastery, ivec2(15, 10), 0)
    monastery.garrisonedRelics = TotalRelicsOnMap
    env.stepNoop()
    check env.victoryStates[0].relicHoldStartStep >= 0
    check env.victoryWinner == -1  # Not enough time
    # Advance past countdown
    let startStep = env.victoryStates[0].relicHoldStartStep
    env.currentStep = startStep + RelicVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true

  test "relic hold resets when relics lost":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRelic
    env.config.maxSteps = 5000
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    let monastery = env.addBuilding(Monastery, ivec2(15, 10), 0)
    monastery.garrisonedRelics = TotalRelicsOnMap
    env.stepNoop()
    check env.victoryStates[0].relicHoldStartStep >= 0
    # Lose relics
    monastery.garrisonedRelics = 0
    env.stepNoop()
    check env.victoryStates[0].relicHoldStartStep == -1
    check env.victoryWinner == -1

  test "relic hold resets when monastery destroyed":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRelic
    env.config.maxSteps = 5000
    discard env.addAgentAt(0, ivec2(10, 10))
    discard env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    let monastery = env.addBuilding(Monastery, ivec2(15, 10), 0)
    monastery.garrisonedRelics = TotalRelicsOnMap
    env.stepNoop()
    check env.victoryStates[0].relicHoldStartStep >= 0
    # Destroy the monastery - relics drop onto map
    discard env.applyStructureDamage(monastery, monastery.hp + 1)
    env.stepNoop()
    # No team holds all relics anymore (they're on the ground)
    check env.victoryStates[0].relicHoldStartStep == -1
    check env.victoryWinner == -1
    # Relics were dropped
    check env.thingsByKind[Relic].len == TotalRelicsOnMap

  test "relic victory with relics spread across multiple monasteries":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRelic
    env.config.maxSteps = 5000
    discard env.addAgentAt(0, ivec2(10, 10))
    discard env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    # Spread relics across two monasteries
    let m1 = env.addBuilding(Monastery, ivec2(15, 10), 0)
    let m2 = env.addBuilding(Monastery, ivec2(20, 10), 0)
    m1.garrisonedRelics = TotalRelicsOnMap div 2
    m2.garrisonedRelics = TotalRelicsOnMap - (TotalRelicsOnMap div 2)
    env.stepNoop()
    check env.victoryStates[0].relicHoldStartStep >= 0
    # Advance past countdown
    let startStep = env.victoryStates[0].relicHoldStartStep
    env.currentStep = startStep + RelicVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0

suite "Victory - VictoryAll mode":
  test "VictoryAll triggers on conquest":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryAll
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    discard env.addAltar(ivec2(12, 10), 0, 5)
    # No other teams alive
    env.stepNoop()
    check env.victoryWinner == 0

  test "conquest victory with building-only team (no mobile units)":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    # Team 0 has only buildings, no living agents
    discard env.addAltar(ivec2(12, 10), 0, 5)
    discard env.addBuilding(TownCenter, ivec2(15, 10), 0)
    # Team 0's agent slot exists but is terminated (no mobile units)
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    env.terminated[0] = 1.0
    env.grid[10][10] = nil
    env.stepNoop()
    # Team 0 still has buildings, so it survives and wins by default
    check env.victoryWinner == 0
    check env.shouldReset == true

  test "no conquest victory when all teams eliminated (draw)":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    # No teams have any units or buildings - simultaneous elimination
    env.stepNoop()
    # No surviving team means no winner (draw)
    check env.victoryWinner == -1

suite "Victory - Winner termination":
  test "winning team agents are truncated not terminated":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    discard env.addAltar(ivec2(12, 10), 0, 5)
    env.stepNoop()
    check env.victoryWinner == 0
    # Winner agent should be truncated (episode ended), not terminated (dead)
    check env.truncated[0] == 1.0
    check env.terminated[0] == 0.0

  test "winning team agents receive conquest victory reward":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    discard env.addAltar(ivec2(12, 10), 0, 5)
    let rewardBefore = agent0.reward
    env.stepNoop()
    check env.victoryWinner == 0
    # Winner should receive VictoryReward
    check agent0.reward > rewardBefore
    check agent0.reward >= rewardBefore + VictoryReward - 1.0  # Allow for survival penalty

suite "Victory - King of the Hill":
  proc addControlPoint(env: Environment, pos: IVec2): Thing =
    let cp = Thing(kind: ControlPoint, pos: pos, teamId: -1)
    cp.inventory = emptyInventory()
    env.add(cp)
    cp

  test "hill victory after controlling for countdown duration":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryKingOfTheHill
    env.config.maxSteps = 5000
    let cp = env.addControlPoint(ivec2(50, 50))
    let agent0 = env.addAgentAt(0, ivec2(50, 51))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(100, 100))
    env.stepNoop()
    check env.victoryStates[0].hillControlStartStep >= 0
    check env.victoryWinner == -1
    let startStep = env.victoryStates[0].hillControlStartStep
    env.currentStep = startStep + HillVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true

  test "hill control resets when contested (tied units)":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryKingOfTheHill
    env.config.maxSteps = 5000
    let cp = env.addControlPoint(ivec2(50, 50))
    let agent0 = env.addAgentAt(0, ivec2(50, 51))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(50, 49))
    env.stepNoop()
    check env.victoryStates[0].hillControlStartStep == -1
    check env.victoryStates[1].hillControlStartStep == -1
    check env.victoryWinner == -1

  test "hill control resets when other team takes over":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryKingOfTheHill
    env.config.maxSteps = 5000
    let cp = env.addControlPoint(ivec2(50, 50))
    let agent0 = env.addAgentAt(0, ivec2(50, 51))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(100, 100))
    env.stepNoop()
    check env.victoryStates[0].hillControlStartStep >= 0
    env.grid[50][51] = nil
    env.terminated[0] = 1.0
    let oldPos = agent1.pos
    env.grid[100][100] = nil
    agent1.pos = ivec2(50, 52)
    env.grid[50][52] = agent1
    env.updateSpatialIndex(agent1, oldPos)
    env.stepNoop()
    check env.victoryStates[0].hillControlStartStep == -1
    check env.victoryStates[1].hillControlStartStep >= 0
    check env.victoryWinner == -1

  test "no hill victory when no units near control point":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryKingOfTheHill
    env.config.maxSteps = 5000
    let cp = env.addControlPoint(ivec2(50, 50))
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(100, 100))
    env.stepNoop()
    check env.victoryStates[0].hillControlStartStep == -1
    check env.victoryStates[1].hillControlStartStep == -1
    check env.victoryWinner == -1

  test "hill victory not checked when VictoryNone":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let cp = env.addControlPoint(ivec2(50, 50))
    let agent0 = env.addAgentAt(0, ivec2(50, 51))
    env.stepNoop()
    check env.victoryWinner == -1

  test "hill control determined by majority (2 vs 1)":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryKingOfTheHill
    env.config.maxSteps = 5000
    let cp = env.addControlPoint(ivec2(50, 50))
    let agent0a = env.addAgentAt(0, ivec2(50, 51))
    let agent0b = env.addAgentAt(1, ivec2(50, 52))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(50, 49))
    env.stepNoop()
    check env.victoryStates[0].hillControlStartStep >= 0
    check env.victoryStates[1].hillControlStartStep == -1
    check env.victoryWinner == -1

  test "VictoryAll includes king of the hill check":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryAll
    env.config.maxSteps = 5000
    let cp = env.addControlPoint(ivec2(50, 50))
    let agent0 = env.addAgentAt(0, ivec2(50, 51))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(100, 100))
    env.stepNoop()
    check env.victoryStates[0].hillControlStartStep >= 0

# Note: Regicide tests are in domain_regicide.nim (9 comprehensive tests)
