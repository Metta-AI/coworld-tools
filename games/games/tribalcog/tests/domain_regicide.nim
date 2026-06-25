import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import test_utils

suite "Victory - Regicide":
  test "regicide victory when only one king survives":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRegicide
    # Team 0: king alive
    let king0 = env.addAgentAt(0, ivec2(10, 10), unitClass = UnitKing)
    env.victoryStates[0].kingAgentId = 0
    # Team 1: king dead
    let king1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20), unitClass = UnitKing)
    env.victoryStates[1].kingAgentId = MapAgentsPerTeam
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil
    env.stepNoop()
    check env.victoryWinner == 0
    check env.shouldReset == true

  test "no regicide victory with multiple kings alive":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRegicide
    let king0 = env.addAgentAt(0, ivec2(10, 10), unitClass = UnitKing)
    env.victoryStates[0].kingAgentId = 0
    let king1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20), unitClass = UnitKing)
    env.victoryStates[1].kingAgentId = MapAgentsPerTeam
    env.stepNoop()
    check env.victoryWinner == -1
    check env.shouldReset == false

  test "regicide not checked when VictoryNone":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let king0 = env.addAgentAt(0, ivec2(10, 10), unitClass = UnitKing)
    env.victoryStates[0].kingAgentId = 0
    # Only one king, but VictoryNone means no check
    env.stepNoop()
    check env.victoryWinner == -1

  test "regicide requires at least two teams with kings":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRegicide
    # Only team 0 has a king - not enough teams
    let king0 = env.addAgentAt(0, ivec2(10, 10), unitClass = UnitKing)
    env.victoryStates[0].kingAgentId = 0
    env.stepNoop()
    check env.victoryWinner == -1

  test "regicide ignores teams without kings":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRegicide
    # Team 0: king alive
    let king0 = env.addAgentAt(0, ivec2(10, 10), unitClass = UnitKing)
    env.victoryStates[0].kingAgentId = 0
    # Team 1: king dead
    let king1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20), unitClass = UnitKing)
    env.victoryStates[1].kingAgentId = MapAgentsPerTeam
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil
    # Team 2: has agents but no king assigned (not participating in regicide)
    let agent2 = env.addAgentAt(2 * MapAgentsPerTeam, ivec2(30, 30))
    # No kingAgentId set for team 2
    env.stepNoop()
    check env.victoryWinner == 0

  test "king unit has correct high HP stats":
    var env = makeEmptyEnv()
    let king = env.addAgentAt(0, ivec2(10, 10), unitClass = UnitKing)
    applyUnitClass(env, king, UnitKing)
    check king.maxHp == KingMaxHp
    check king.attackDamage == KingAttackDamage

  test "regicide victory awards reward to winning team":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRegicide
    let king0 = env.addAgentAt(0, ivec2(10, 10), unitClass = UnitKing)
    env.victoryStates[0].kingAgentId = 0
    let king1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20), unitClass = UnitKing)
    env.victoryStates[1].kingAgentId = MapAgentsPerTeam
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil
    let rewardBefore = king0.reward
    env.stepNoop()
    check env.victoryWinner == 0
    check king0.reward > rewardBefore
    # Winner should be truncated not terminated
    check env.truncated[0] == 1.0
    check env.terminated[0] == 0.0

  test "regicide with three teams - last king standing wins":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRegicide
    # Team 0: king alive
    let king0 = env.addAgentAt(0, ivec2(10, 10), unitClass = UnitKing)
    env.victoryStates[0].kingAgentId = 0
    # Team 1: king dead
    let king1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20), unitClass = UnitKing)
    env.victoryStates[1].kingAgentId = MapAgentsPerTeam
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil
    # Team 2: king dead
    let king2 = env.addAgentAt(2 * MapAgentsPerTeam, ivec2(30, 30), unitClass = UnitKing)
    env.victoryStates[2].kingAgentId = 2 * MapAgentsPerTeam
    env.terminated[2 * MapAgentsPerTeam] = 1.0
    env.grid[30][30] = nil
    env.stepNoop()
    check env.victoryWinner == 0

  test "all kings dead means no winner (draw)":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryRegicide
    # Team 0: king dead
    let king0 = env.addAgentAt(0, ivec2(10, 10), unitClass = UnitKing)
    env.victoryStates[0].kingAgentId = 0
    env.terminated[0] = 1.0
    env.grid[10][10] = nil
    # Team 1: king dead
    let king1 = env.addAgentAt(MapAgentsPerTeam, ivec2(20, 20), unitClass = UnitKing)
    env.victoryStates[1].kingAgentId = MapAgentsPerTeam
    env.terminated[MapAgentsPerTeam] = 1.0
    env.grid[20][20] = nil
    env.stepNoop()
    # No surviving king = no winner
    check env.victoryWinner == -1
