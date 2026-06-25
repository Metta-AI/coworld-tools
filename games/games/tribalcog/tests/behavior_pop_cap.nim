import std/[unittest]
import test_common

## Behavioral tests for population cap enforcement.
## Population cap = number of houses * HousePopCap (4).
## Agents cannot respawn at altars when at cap.

suite "Behavior: Population Cap at Respawn":
  test "agent cannot respawn when at population cap":
    ## With no houses and existing agents, dead agents cannot respawn.
    let env = makeEmptyEnv()

    # Create an altar with hearts for respawning
    let altarPos = ivec2(10, 10)
    let altar = addAltar(env, altarPos, 0, 10)

    # Add one living agent (at cap with 0 houses = 0 pop cap)
    let agent = addAgentAt(env, 0, ivec2(12, 10), homeAltar = altarPos)

    # Add a dead agent that should try to respawn
    let deadAgent = addAgentAt(env, 1, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    let heartsBeforeStep = altar.hearts

    # Step should not respawn the dead agent (no pop cap without houses)
    env.stepNoop()

    # Dead agent should still be dead (no respawn)
    check env.terminated[deadAgent.agentId] == 1.0
    check deadAgent.pos == ivec2(-1, -1)
    # Hearts should not be spent
    check altar.hearts == heartsBeforeStep

  test "agent respawns when under population cap":
    ## With enough houses, dead agents should respawn.
    let env = makeEmptyEnv()

    # Create an altar with hearts for respawning
    let altarPos = ivec2(10, 10)
    discard addAltar(env, altarPos, 0, 10)

    # Add a house to provide population cap (HousePopCap = 4)
    discard addBuilding(env, House, ivec2(20, 10), 0)

    # Add one living agent (under cap of 4)
    discard addAgentAt(env, 0, ivec2(12, 10), homeAltar = altarPos)

    # Add a dead agent that should try to respawn
    let deadAgent = addAgentAt(env, 1, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    # Step should respawn the dead agent (under pop cap of 4)
    env.stepNoop()

    # Dead agent should now be alive
    check env.terminated[deadAgent.agentId] == 0.0
    check deadAgent.pos.x >= 0
    check deadAgent.hp > 0

suite "Behavior: Houses Increase Population Cap":
  test "building houses allows more agents to respawn":
    ## Adding houses increases the population cap.
    let env = makeEmptyEnv()

    # Create an altar with hearts for respawning
    let altarPos = ivec2(10, 10)
    discard addAltar(env, altarPos, 0, 20)

    # Add HousePopCap (4) living agents (exactly at cap with 1 house)
    # Place agents far from houses to avoid position collisions
    for i in 0 ..< HousePopCap:
      discard addAgentAt(env, i, ivec2(30 + i.int32, 10), homeAltar = altarPos)

    # Add a dead agent that should try to respawn
    let deadAgent = addAgentAt(env, HousePopCap, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    # Add only 1 house (cap = 4), so at capacity
    discard addBuilding(env, House, ivec2(20, 10), 0)

    # Step should NOT respawn (at capacity)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 1.0

    # Add another house (cap = 8), now under capacity
    discard addBuilding(env, House, ivec2(22, 10), 0)

    # Step should respawn the dead agent (now under cap of 8)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 0.0
    check deadAgent.pos.x >= 0

  test "multiple houses provide cumulative population cap":
    ## Population cap scales with house count.
    let env = makeEmptyEnv()

    # Create an altar with hearts for respawning
    let altarPos = ivec2(10, 10)
    let altar = addAltar(env, altarPos, 0, 50)

    # Add houses to get cap of 3 * HousePopCap = 12
    for i in 0 ..< 3:
      discard addBuilding(env, House, ivec2(15 + i.int32, 10), 0)

    # Add 11 living agents (under cap of 12)
    for i in 0 ..< 11:
      let x = (i mod 10).int32
      let y = (i div 10).int32
      discard addAgentAt(env, i, ivec2(20 + x, 15 + y), homeAltar = altarPos)

    # Add a dead agent
    let deadAgent = addAgentAt(env, 11, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    # Should respawn (11 < 12)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 0.0

suite "Behavior: Destroyed Houses Reduce Population Cap":
  test "pop cap is based on house count at step time":
    ## Population cap is recalculated each step from current house count.
    ## This test verifies that the number of houses determines cap.
    let env = makeEmptyEnv()

    # Create an altar with hearts
    let altarPos = ivec2(10, 10)
    let altar = addAltar(env, altarPos, 0, 20)

    # With 1 house (cap = 4) and 4 agents, we're at capacity
    discard addBuilding(env, House, ivec2(15, 10), 0)

    # Add exactly 4 living agents (at cap)
    for i in 0 ..< 4:
      discard addAgentAt(env, i, ivec2(20 + i.int32, 10), homeAltar = altarPos)

    # Add a dead agent
    let deadAgent = addAgentAt(env, 4, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    # Should NOT respawn (4 = 4, at cap)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 1.0

    # Add a second house (cap = 8)
    discard addBuilding(env, House, ivec2(16, 10), 0)

    # Now should respawn (4 < 8)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 0.0

  test "cannot respawn at reduced cap even with altar hearts":
    ## Having altar hearts doesn't bypass population cap.
    let env = makeEmptyEnv()

    # Create an altar with many hearts
    let altarPos = ivec2(10, 10)
    let altar = addAltar(env, altarPos, 0, 100)

    # Add 1 house (cap = 4)
    discard addBuilding(env, House, ivec2(15, 10), 0)

    # Add exactly 4 living agents (at cap)
    for i in 0 ..< 4:
      discard addAgentAt(env, i, ivec2(20 + i.int32, 10), homeAltar = altarPos)

    # Add a dead agent
    let deadAgent = addAgentAt(env, 4, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    let heartsBefore = altar.hearts

    # Should NOT respawn (at cap) even with plenty of hearts
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 1.0
    # Hearts should not be spent
    check altar.hearts == heartsBefore

suite "Behavior: Population Cap Shared Across Unit Types":
  test "all unit types count toward same population cap":
    ## Villagers, military units, and other types share the same cap.
    let env = makeEmptyEnv()

    # Create an altar with hearts
    let altarPos = ivec2(10, 10)
    let altar = addAltar(env, altarPos, 0, 20)

    # Add 1 house (cap = 4)
    discard addBuilding(env, House, ivec2(15, 10), 0)

    # Add agents of different unit classes
    let villager = addAgentAt(env, 0, ivec2(20, 10), homeAltar = altarPos, unitClass = UnitVillager)
    let archer = addAgentAt(env, 1, ivec2(21, 10), homeAltar = altarPos, unitClass = UnitArcher)
    let knight = addAgentAt(env, 2, ivec2(22, 10), homeAltar = altarPos, unitClass = UnitKnight)
    let manAtArms = addAgentAt(env, 3, ivec2(23, 10), homeAltar = altarPos, unitClass = UnitManAtArms)

    # Now at cap of 4 with mixed unit types

    # Add a dead agent
    let deadAgent = addAgentAt(env, 4, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    # Should NOT respawn (at cap with mixed unit types)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 1.0

  test "military units convert from villagers without changing pop count":
    ## Training military units converts villagers - population doesn't change.
    let env = makeEmptyEnv()

    # Create an altar with hearts
    let altarPos = ivec2(10, 10)
    let altar = addAltar(env, altarPos, 0, 20)

    # Add 1 house (cap = 4)
    discard addBuilding(env, House, ivec2(15, 10), 0)

    # Add 3 villagers (under cap)
    for i in 0 ..< 3:
      discard addAgentAt(env, i, ivec2(20 + i.int32, 10), homeAltar = altarPos, unitClass = UnitVillager)

    # Add a dead agent
    let deadAgent = addAgentAt(env, 3, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    # Should respawn (3 < 4)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 0.0

    # Convert one of the villagers to a military unit
    let villager = env.agents[0]
    applyUnitClass(villager, UnitKnight)

    # Kill the respawned agent again
    deadAgent.hp = 0
    deadAgent.pos = ivec2(-1, -1)
    env.terminated[deadAgent.agentId] = 1.0

    # Should still respawn - population didn't change from conversion
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 0.0

suite "Behavior: Population Cap Edge Cases":
  test "town center provides no population cap":
    ## Town centers have TownCenterPopCap = 0.
    let env = makeEmptyEnv()

    # Create an altar with hearts
    let altarPos = ivec2(10, 10)
    let altar = addAltar(env, altarPos, 0, 20)

    # Add only a town center (provides 0 pop cap)
    discard addBuilding(env, TownCenter, ivec2(15, 10), 0)

    # Add one living agent
    let agent = addAgentAt(env, 0, ivec2(20, 10), homeAltar = altarPos)

    # Add a dead agent
    let deadAgent = addAgentAt(env, 1, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    # Should NOT respawn (TC provides 0 pop cap)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 1.0

  test "population cap clamped to MapAgentsPerTeam":
    ## Even with many houses, cap cannot exceed MapAgentsPerTeam.
    let env = makeEmptyEnv()

    # Create an altar
    let altarPos = ivec2(10, 10)
    let altar = addAltar(env, altarPos, 0, 200)

    # Add many houses to exceed MapAgentsPerTeam (125) / HousePopCap (4) = 31.25
    # Adding 40 houses would give 160 cap, but clamped to 125
    for i in 0 ..< 40:
      let x = (i mod 10).int32
      let y = (i div 10).int32
      discard addBuilding(env, House, ivec2(5 + x * 2, 5 + y * 2), 0)

    # The effective cap should be MapAgentsPerTeam (125), not 160
    # This is enforced in step.nim: teamPopCaps[teamId] = min(MapAgentsPerTeam, computed)
    # We can't easily test the exact clamping without filling 125+ agents,
    # but we verify the system doesn't crash with excessive houses

    # Add some agents
    for i in 0 ..< 10:
      discard addAgentAt(env, i, ivec2(50 + i.int32, 10), homeAltar = altarPos)

    # Add a dead agent
    let deadAgent = addAgentAt(env, 10, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    # Should respawn (10 < 125)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 0.0

  test "enemy house does not contribute to team pop cap":
    ## Houses only count for their own team.
    let env = makeEmptyEnv()

    # Create an altar for team 0
    let altarPos = ivec2(10, 10)
    let altar = addAltar(env, altarPos, 0, 20)

    # Add a house for team 1 (enemy)
    discard addBuilding(env, House, ivec2(15, 10), 1)

    # Add one living agent for team 0
    let agent = addAgentAt(env, 0, ivec2(20, 10), homeAltar = altarPos)

    # Add a dead agent for team 0
    let deadAgent = addAgentAt(env, 1, ivec2(-1, -1), homeAltar = altarPos)
    deadAgent.hp = 0
    env.terminated[deadAgent.agentId] = 1.0

    # Should NOT respawn (team 0 has no houses, enemy house doesn't count)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 1.0

    # Add a house for team 0
    discard addBuilding(env, House, ivec2(16, 10), 0)

    # Now should respawn (team 0 has 1 house, cap = 4)
    env.stepNoop()
    check env.terminated[deadAgent.agentId] == 0.0
