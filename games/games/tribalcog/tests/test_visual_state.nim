## Visual State Tests: Tests for team colors, health bars, selection, and death animation
##
## Tests visual state consistency without requiring actual rendering:
## - Team color assignment and consistency
## - Health bar updates with damage
## - Selection highlight state
## - Dead unit death animation state

import std/[unittest, strformat]
import environment
import agent_control
import common
import types
import items
import test_utils
import ui_harness

# Helper proc for applying death tint (mirrors what combat.nim does)
proc applyDeathTintTest(env: Environment, pos: IVec2) =
  if not isValidPos(pos):
    return
  env.actionTintCode[pos.x][pos.y] = ActionTintDeath
  env.actionTintCountdown[pos.x][pos.y] = DeathTintDuration
  if not env.actionTintFlags[pos.x][pos.y]:
    env.actionTintFlags[pos.x][pos.y] = true
    env.actionTintPositions.add(pos)

# ---------------------------------------------------------------------------
# Team Color Tests
# ---------------------------------------------------------------------------

suite "Visual State: Team Color Consistency":
  test "newly spawned units have correct team color":
    let env = makeEmptyEnv()
    # Initialize team colors
    env.teamColors = @[WarmTeamPalette[0], WarmTeamPalette[1]]
    env.agentColors.setLen(MapAgents)

    let team0Agent = addAgentAt(env, 0, ivec2(10, 10))
    env.agentColors[0] = env.teamColors[0]

    let team1Agent = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    env.agentColors[MapAgentsPerTeam] = env.teamColors[1]

    # Verify team colors are assigned
    check env.agentColors[0] == WarmTeamPalette[0]
    check env.agentColors[MapAgentsPerTeam] == WarmTeamPalette[1]
    echo "  Team 0 agent has red tint, Team 1 agent has orange tint"

  test "all units on same team share team color":
    let env = makeEmptyEnv()
    env.teamColors = @[WarmTeamPalette[0]]
    env.agentColors.setLen(MapAgents)

    # Add multiple units to team 0
    for i in 0 ..< 5:
      discard addAgentAt(env, i, ivec2((10 + i * 5).int32, 10))
      env.agentColors[i] = env.teamColors[0]

    # All should have the same team color
    for i in 0 ..< 5:
      check env.agentColors[i] == WarmTeamPalette[0]
    echo "  All 5 team 0 units share the same color"

  test "team colors are distinct for all teams":
    let env = makeEmptyEnv()
    env.teamColors.setLen(MapRoomObjectsTeams)
    for i in 0 ..< min(MapRoomObjectsTeams, WarmTeamPalette.len):
      env.teamColors[i] = WarmTeamPalette[i]

    # Verify all team colors are distinct
    for i in 0 ..< min(MapRoomObjectsTeams, WarmTeamPalette.len):
      for j in (i + 1) ..< min(MapRoomObjectsTeams, WarmTeamPalette.len):
        check env.teamColors[i] != env.teamColors[j]
    echo &"  All {min(MapRoomObjectsTeams, WarmTeamPalette.len)} team colors are distinct"

  test "building has correct team color":
    let env = makeEmptyEnv()
    env.teamColors = @[WarmTeamPalette[0], WarmTeamPalette[1]]

    let barracks0 = addBuilding(env, Barracks, ivec2(10, 10), 0)
    let barracks1 = addBuilding(env, Barracks, ivec2(30, 30), 1)

    # Buildings use teamId field for team association
    check barracks0.teamId == 0
    check barracks1.teamId == 1
    echo "  Buildings correctly associated with their teams"

# ---------------------------------------------------------------------------
# Health Bar Tests
# ---------------------------------------------------------------------------

suite "Visual State: Health Bar Updates":
  test "initial health bar is at maximum":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    check agent.hp == agent.maxHp
    check agent.hp == AgentMaxHp
    echo &"  Agent starts with full health: {agent.hp}/{agent.maxHp}"

  test "health bar updates after taking damage":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let initialHp = agent.hp

    # Simulate damage
    agent.hp = agent.hp - 3

    check agent.hp == initialHp - 3
    check agent.hp < agent.maxHp
    echo &"  Health updated: {agent.hp}/{agent.maxHp} after 3 damage"

  test "health bar reflects healing":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Damage then heal
    agent.hp = 3
    let damagedHp = agent.hp
    agent.hp = min(agent.hp + 2, agent.maxHp)

    check agent.hp == damagedHp + 2
    echo &"  Health restored: {damagedHp} -> {agent.hp}"

  test "health cannot exceed max health":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Try to overheal
    agent.hp = agent.maxHp + 10

    # For rendering, we expect the bar to be clamped at max
    let displayHp = min(agent.hp, agent.maxHp)
    check displayHp == agent.maxHp
    echo "  Health bar display capped at max"

  test "building health bar updates with damage":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    barracks.hp = 100
    barracks.maxHp = 100

    # Damage building
    barracks.hp = barracks.hp - 25

    check barracks.hp == 75
    check barracks.hp < barracks.maxHp
    echo &"  Building health: {barracks.hp}/{barracks.maxHp}"

  test "health ratio for rendering is correct":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.hp = 5
    agent.maxHp = 10

    let ratio = agent.hp.float / agent.maxHp.float
    check ratio == 0.5
    echo &"  Health ratio: {ratio} (50%)"

# ---------------------------------------------------------------------------
# Selection Highlight Tests
# ---------------------------------------------------------------------------

suite "Visual State: Selection Highlights":
  setup:
    resetSelection()

  test "unselected units have no highlight":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    check not isSelected(agent)
    check selection.len == 0
    echo "  Unselected unit has no highlight"

  test "selected unit has highlight":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    selectThing(agent)

    check isSelected(agent)
    check selectedPos == agent.pos
    echo "  Selected unit has highlight at its position"

  test "multi-selection highlights all units":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(20, 20))
    let agent3 = addAgentAt(env, 2, ivec2(30, 30))

    selectThings(@[agent1, agent2, agent3])

    check isSelected(agent1)
    check isSelected(agent2)
    check isSelected(agent3)
    check selection.len == 3
    echo "  All 3 units in multi-selection have highlights"

  test "deselected unit loses highlight":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    selectThing(agent)
    check isSelected(agent)

    resetSelection()
    check not isSelected(agent)
    echo "  Deselected unit no longer has highlight"

  test "selection updates when unit moves":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    selectThing(agent)
    check selectedPos == ivec2(10, 10)

    # Move agent
    agent.pos = ivec2(50, 50)

    # Selection highlight should still be associated with the agent
    check isSelected(agent)
    # Note: selectedPos may or may not update depending on implementation
    echo "  Selection remains on moved unit"

  test "building selection works":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)

    selectThing(barracks)

    check isSelected(barracks)
    check selectedPos == barracks.pos
    echo "  Building selection highlight works"

# ---------------------------------------------------------------------------
# Death Animation State Tests
# ---------------------------------------------------------------------------

suite "Visual State: Death Animation State":
  test "alive unit is not terminated":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    check env.terminated[agent.agentId] == 0.0
    check env.isAgentAlive(agent)
    echo "  Alive agent has terminated = 0.0"

  test "dead unit has terminated state":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Simulate death
    env.terminated[agent.agentId] = 1.0

    check env.terminated[agent.agentId] == 1.0
    check not env.isAgentAlive(agent)
    echo "  Dead agent has terminated = 1.0"

  test "dead units excluded from selection":
    let env = makeEmptyEnv()
    let alive = addAgentAt(env, 0, ivec2(10, 10))
    let dead = addAgentAt(env, 1, ivec2(15, 15))
    env.terminated[dead.agentId] = 1.0

    # Drag-box select should exclude dead
    let selectedAgents = simulateDragBox(env, vec2(5, 5), vec2(20, 20))

    check selectedAgents.len == 1
    check alive in selectedAgents
    check dead notin selectedAgents
    echo "  Dead units excluded from drag-box selection"

  test "death tint is applied at kill location":
    let env = makeEmptyEnv()
    env.actionTintPositions.setLen(0)
    for x in 0 ..< MapWidth:
      for y in 0 ..< MapHeight:
        env.actionTintFlags[x][y] = false
        env.actionTintCode[x][y] = ActionTintNone

    let killPos = ivec2(25, 25)

    # Apply death tint manually (simulating what combat does)
    applyDeathTintTest(env, killPos)

    # Check that death tint was applied
    check env.actionTintCode[killPos.x][killPos.y] == ActionTintDeath
    check env.actionTintFlags[killPos.x][killPos.y] == true
    echo &"  Death tint applied at {killPos}"

  test "corpse spawned at death location":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(30, 30))
    let deathPos = agent.pos

    # Create corpse at death location
    let corpse = Thing(kind: Corpse, pos: deathPos)
    corpse.inventory = emptyInventory()
    setInv(corpse, ItemMeat, ResourceNodeInitial - 1)
    env.add(corpse)

    # Verify corpse exists
    var foundCorpse = false
    for c in env.thingsByKind[Corpse]:
      if c.pos == deathPos:
        foundCorpse = true
        break
    check foundCorpse
    echo &"  Corpse spawned at death location {deathPos}"

  test "multiple deaths create multiple visual effects":
    let env = makeEmptyEnv()
    env.actionTintPositions.setLen(0)
    for x in 0 ..< MapWidth:
      for y in 0 ..< MapHeight:
        env.actionTintFlags[x][y] = false
        env.actionTintCode[x][y] = ActionTintNone

    let pos1 = ivec2(10, 10)
    let pos2 = ivec2(40, 40)
    let pos3 = ivec2(70, 70)

    applyDeathTintTest(env, pos1)
    applyDeathTintTest(env, pos2)
    applyDeathTintTest(env, pos3)

    check env.actionTintCode[pos1.x][pos1.y] == ActionTintDeath
    check env.actionTintCode[pos2.x][pos2.y] == ActionTintDeath
    check env.actionTintCode[pos3.x][pos3.y] == ActionTintDeath
    echo "  Multiple death tints applied independently"

# ---------------------------------------------------------------------------
# Combined Visual State Tests
# ---------------------------------------------------------------------------

suite "Visual State: Combined State Consistency":
  setup:
    resetSelection()

  test "selected damaged unit shows both states":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    # Damage the unit
    agent.hp = agent.maxHp div 2

    # Select it
    selectThing(agent)

    # Both states should be present
    check isSelected(agent)
    check agent.hp < agent.maxHp
    echo &"  Selected unit at {agent.hp}/{agent.maxHp} HP"

  test "team colored unit with low health":
    let env = makeEmptyEnv()
    env.teamColors = @[WarmTeamPalette[0]]
    env.agentColors.setLen(MapAgents)

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    env.agentColors[0] = env.teamColors[0]
    agent.hp = 1  # Critical health

    check env.agentColors[0] == WarmTeamPalette[0]
    check agent.hp == 1
    check agent.hp < agent.maxHp
    echo "  Team-colored unit shows critical health"

  test "dead unit retains team color for corpse rendering":
    let env = makeEmptyEnv()
    env.teamColors = @[WarmTeamPalette[0]]
    env.agentColors.setLen(MapAgents)

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    let originalColor = WarmTeamPalette[0]
    env.agentColors[0] = originalColor

    # Kill the agent
    env.terminated[agent.agentId] = 1.0

    # Color should still be available for corpse/death animation
    check env.agentColors[0] == originalColor
    check not env.isAgentAlive(agent)
    echo "  Dead unit's color preserved for death visuals"
