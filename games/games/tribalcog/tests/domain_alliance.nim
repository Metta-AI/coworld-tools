import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import test_utils

suite "Alliance - Formation and Dissolution":
  test "each team is allied with itself by default":
    var env = makeEmptyEnv()
    for teamId in 0 ..< MapRoomObjectsTeams:
      check env.areAllied(teamId, teamId) == true
      check isTeamInMask(teamId, env.getAllies(teamId)) == true

  test "teams are not allied with others by default":
    var env = makeEmptyEnv()
    check env.areAllied(0, 1) == false
    check env.areAllied(1, 0) == false

  test "forming alliance is symmetric":
    var env = makeEmptyEnv()
    env.formAlliance(0, 1)
    check env.areAllied(0, 1) == true
    check env.areAllied(1, 0) == true
    # Both teams still allied with self
    check env.areAllied(0, 0) == true
    check env.areAllied(1, 1) == true

  test "breaking alliance is symmetric":
    var env = makeEmptyEnv()
    env.formAlliance(0, 1)
    check env.areAllied(0, 1) == true
    env.breakAlliance(0, 1)
    check env.areAllied(0, 1) == false
    check env.areAllied(1, 0) == false

  test "cannot break alliance with self":
    var env = makeEmptyEnv()
    env.breakAlliance(0, 0)
    check env.areAllied(0, 0) == true

  test "multi-team alliance":
    var env = makeEmptyEnv()
    env.formAlliance(0, 1)
    env.formAlliance(0, 2)
    check env.areAllied(0, 1) == true
    check env.areAllied(0, 2) == true
    # Team 1 and 2 are not directly allied unless explicitly formed
    check env.areAllied(1, 2) == false

  test "getAllies returns correct bitmask":
    var env = makeEmptyEnv()
    env.formAlliance(0, 1)
    env.formAlliance(0, 3)
    let allies = env.getAllies(0)
    check isTeamInMask(0, allies) == true
    check isTeamInMask(1, allies) == true
    check isTeamInMask(2, allies) == false
    check isTeamInMask(3, allies) == true

  test "invalid team IDs handled gracefully":
    var env = makeEmptyEnv()
    env.formAlliance(-1, 0)  # Should not crash
    env.formAlliance(0, MapRoomObjectsTeams)  # Should not crash
    check env.areAllied(-1, 0) == false
    check env.areAllied(0, MapRoomObjectsTeams) == false
    check env.getAllies(-1) == NoTeamMask

suite "Alliance - Conquest Victory":
  test "allied teams share conquest victory":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    # Team 0 and Team 1 are allied
    env.formAlliance(0, 1)
    # Both teams have agents alive
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20))
    discard env.addAltar(ivec2(12, 10), 0, 5)
    discard env.addAltar(ivec2(22, 20), 1, 5)
    env.stepNoop()
    # Both allied teams survive, no non-allied teams alive -> conquest victory
    check env.victoryWinner >= 0
    check isTeamInMask(0, env.victoryWinners) == true
    check isTeamInMask(1, env.victoryWinners) == true
    check env.shouldReset == true

  test "allied teams dont win if non-allied team survives":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    env.formAlliance(0, 1)
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20))
    # Team 2 also alive and NOT allied
    let agent2 = env.addAgentAt(MapAgentsPerTeam * 2, ivec2(30, 30))
    env.stepNoop()
    check env.victoryWinner == -1
    check env.shouldReset == false

  test "non-allied teams still compete normally":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    # No alliances - teams 0 and 1 compete
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20))
    env.stepNoop()
    # Both alive, no winner
    check env.victoryWinner == -1

  test "single team conquest victory still works without alliances":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    discard env.addAltar(ivec2(12, 10), 0, 5)
    # No other teams alive
    env.stepNoop()
    check env.victoryWinner == 0
    check isTeamInMask(0, env.victoryWinners) == true
    check env.shouldReset == true

  test "allied conquest winners get victory reward":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryConquest
    env.formAlliance(0, 1)
    let agent0 = env.addAgentAt(0, ivec2(10, 10))
    let agent1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20))
    discard env.addAltar(ivec2(12, 10), 0, 5)
    discard env.addAltar(ivec2(22, 20), 1, 5)
    env.stepNoop()
    check env.victoryWinner >= 0
    # Both allied team agents should be truncated (winners), not terminated
    check env.truncated[0] == 1.0
    check env.terminated[0] == 0.0
    check env.truncated[MapAgentsPerTeam] == 1.0
    check env.terminated[MapAgentsPerTeam] == 0.0

suite "Alliance - Wonder Victory":
  test "allied teams share wonder victory":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000
    env.formAlliance(0, 1)
    discard env.addAgentAt(0, ivec2(10, 10))
    discard env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    # Team 2 is a non-allied opponent (needed so conquest doesnt trigger)
    discard env.addAgentAt(MapAgentsPerTeam * 2, ivec2(80, 80))
    # Team 0 builds a Wonder
    let wonder = env.addBuilding(Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    check env.victoryStates[0].wonderBuiltStep >= 0
    # Advance past countdown
    let startStep = env.victoryStates[0].wonderBuiltStep
    env.currentStep = startStep + WonderVictoryCountdown
    env.stepNoop()
    check env.victoryWinner == 0
    # Both allied teams are in victoryWinners
    check isTeamInMask(0, env.victoryWinners) == true
    check isTeamInMask(1, env.victoryWinners) == true
    # Non-allied team 2 is not a winner
    check isTeamInMask(2, env.victoryWinners) == false
    check env.shouldReset == true

  test "ally agents are truncated not terminated on wonder win":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryWonder
    env.config.maxSteps = 5000
    env.formAlliance(0, 1)
    discard env.addAgentAt(0, ivec2(10, 10))
    discard env.addAgentAt(MapAgentsPerTeam, ivec2(50, 50))
    discard env.addAgentAt(MapAgentsPerTeam * 2, ivec2(80, 80))
    let wonder = env.addBuilding(Wonder, ivec2(15, 10), 0)
    env.stepNoop()
    let startStep = env.victoryStates[0].wonderBuiltStep
    env.currentStep = startStep + WonderVictoryCountdown
    env.stepNoop()
    # Ally team 1 agent should be truncated (winner), not terminated
    check env.truncated[MapAgentsPerTeam] == 1.0
    check env.terminated[MapAgentsPerTeam] == 0.0
    # Enemy team 2 should be terminated (loser)
    check env.terminated[MapAgentsPerTeam * 2] == 1.0

suite "Alliance - Edge Cases":
  test "alliance survives across multiple steps":
    var env = makeEmptyEnv()
    env.formAlliance(0, 1)
    discard env.addAgentAt(0, ivec2(10, 10))
    discard env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20))
    env.config.victoryCondition = VictoryNone
    env.stepNoop()
    env.stepNoop()
    env.stepNoop()
    # Alliance should still hold
    check env.areAllied(0, 1) == true

  test "forming already-existing alliance is idempotent":
    var env = makeEmptyEnv()
    env.formAlliance(0, 1)
    env.formAlliance(0, 1)
    env.formAlliance(0, 1)
    check env.areAllied(0, 1) == true
    env.breakAlliance(0, 1)
    check env.areAllied(0, 1) == false

  test "breaking non-existent alliance is safe":
    var env = makeEmptyEnv()
    env.breakAlliance(0, 1)  # Never formed, should be no-op
    check env.areAllied(0, 1) == false
    check env.areAllied(0, 0) == true
