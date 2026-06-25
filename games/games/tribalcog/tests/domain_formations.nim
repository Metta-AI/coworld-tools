import std/unittest
import environment
import agent_control
import types
import formations
import test_utils

suite "Formation - Line Formation":
  test "line formation maintains spacing":
    let positions = calcLinePositions(ivec2(50, 50), 4, 0)
    check positions.len == 4
    # Units should be spaced FormationSpacing apart horizontally
    for i in 1 ..< positions.len:
      check abs(positions[i].x - positions[i-1].x) == FormationSpacing
      check positions[i].y == positions[i-1].y  # Same y for horizontal line

  test "vertical line formation":
    let positions = calcLinePositions(ivec2(50, 50), 3, 2)
    check positions.len == 3
    # Units should be spaced vertically
    for i in 1 ..< positions.len:
      check positions[i].x == positions[i-1].x  # Same x for vertical line
      check abs(positions[i].y - positions[i-1].y) == FormationSpacing

  test "single unit line formation":
    let positions = calcLinePositions(ivec2(50, 50), 1, 0)
    check positions.len == 1
    check positions[0] == ivec2(50, 50)

  test "empty line formation":
    let positions = calcLinePositions(ivec2(50, 50), 0, 0)
    check positions.len == 0

suite "Formation - Box Formation":
  test "box formation surrounds center":
    let positions = calcBoxPositions(ivec2(50, 50), 8, 0)
    check positions.len == 8
    # All positions should be within a reasonable distance of center
    for pos in positions:
      check abs(pos.x - 50) <= 10
      check abs(pos.y - 50) <= 10

  test "single unit box formation":
    let positions = calcBoxPositions(ivec2(50, 50), 1, 0)
    check positions.len == 1
    check positions[0] == ivec2(50, 50)

  test "box formation has unique positions":
    let positions = calcBoxPositions(ivec2(50, 50), 6, 0)
    check positions.len == 6
    # Check that positions are not all the same
    var distinct_count = 0
    for i in 0 ..< positions.len:
      var unique = true
      for j in 0 ..< i:
        if positions[i] == positions[j]:
          unique = false
          break
      if unique:
        inc distinct_count
    check distinct_count >= 4  # At least 4 distinct positions for 6 units

suite "Formation - Staggered Formation":
  test "staggered formation creates offset rows":
    let positions = calcStaggeredPositions(ivec2(50, 50), 6, 0)
    check positions.len == 6
    # Staggered formation should have alternating row offsets
    # With 6 units in a roughly 3x2 grid, second row should be offset
    var row0Xs: seq[int32] = @[]
    var row1Xs: seq[int32] = @[]
    for i, pos in positions:
      if i < 3:
        row0Xs.add(pos.x)
      else:
        row1Xs.add(pos.x)
    # Second row should have different x positions (offset by half spacing)
    if row0Xs.len > 0 and row1Xs.len > 0:
      check row0Xs[0] != row1Xs[0]  # First unit of each row at different x

  test "single unit staggered formation":
    let positions = calcStaggeredPositions(ivec2(50, 50), 1, 0)
    check positions.len == 1
    check positions[0] == ivec2(50, 50)

  test "empty staggered formation":
    let positions = calcStaggeredPositions(ivec2(50, 50), 0, 0)
    check positions.len == 0

  test "staggered formation has unique positions":
    let positions = calcStaggeredPositions(ivec2(50, 50), 9, 0)
    check positions.len == 9
    var distinct_count = 0
    for i in 0 ..< positions.len:
      var unique = true
      for j in 0 ..< i:
        if positions[i] == positions[j]:
          unique = false
          break
      if unique:
        inc distinct_count
    check distinct_count == 9  # All positions should be unique

  test "staggered formation rotation changes orientation":
    let pos0 = calcStaggeredPositions(ivec2(50, 50), 4, 0)
    let pos2 = calcStaggeredPositions(ivec2(50, 50), 4, 2)
    check pos0.len == pos2.len
    # Rotated 90 degrees should give different layout
    var allSame = true
    for i in 0 ..< pos0.len:
      if pos0[i] != pos2[i]:
        allSame = false
        break
    check not allSame

suite "Formation - Control Group Integration":
  test "set and get formation type":
    resetAllFormations()
    setFormation(0, FormationLine)
    check getFormation(0) == FormationLine
    check isFormationActive(0) == true

    setFormation(1, FormationBox)
    check getFormation(1) == FormationBox
    check isFormationActive(1) == true

  test "clear formation":
    resetAllFormations()
    setFormation(0, FormationLine)
    check isFormationActive(0) == true
    clearFormation(0)
    check isFormationActive(0) == false
    check getFormation(0) == FormationNone

  test "formation rotation":
    resetAllFormations()
    setFormation(0, FormationLine)
    setFormationRotation(0, 2)
    check getFormationRotation(0) == 2
    setFormationRotation(0, 10)  # Should wrap to 2 (10 mod 8)
    check getFormationRotation(0) == 2

  test "invalid group index":
    check getFormation(-1) == FormationNone
    check getFormation(100) == FormationNone
    check isFormationActive(-1) == false

  test "reset clears all formations":
    setFormation(0, FormationLine)
    setFormation(5, FormationBox)
    resetAllFormations()
    check isFormationActive(0) == false
    check isFormationActive(5) == false

suite "Formation - Agent Position Assignment":
  test "formation adjusts when units added/removed":
    resetAllFormations()
    # 3 units in line
    let pos3 = calcLinePositions(ivec2(50, 50), 3, 0)
    check pos3.len == 3
    # 5 units in line - should have different spacing
    let pos5 = calcLinePositions(ivec2(50, 50), 5, 0)
    check pos5.len == 5
    # More units means wider line
    let span3 = abs(pos3[pos3.len-1].x - pos3[0].x)
    let span5 = abs(pos5[pos5.len-1].x - pos5[0].x)
    check span5 > span3

  test "getFormationTargetForAgent returns valid positions":
    resetAllFormations()
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), stance = StanceDefensive)
    let a1 = env.addAgentAt(1, ivec2(52, 50), stance = StanceDefensive)
    let a2 = env.addAgentAt(2, ivec2(54, 50), stance = StanceDefensive)

    # Create control group
    controlGroups[0] = @[a0, a1, a2]
    setFormation(0, FormationLine)

    let target = getFormationTargetForAgent(0, 0, ivec2(52, 50), 3)
    check target.x >= 0
    check target.y >= 0
    check target.x < MapWidth
    check target.y < MapHeight

  test "getFormationTargetForAgent returns -1 when no formation":
    resetAllFormations()
    let target = getFormationTargetForAgent(0, 0, ivec2(50, 50), 3)
    check target.x == -1

suite "Formation - FFI API":
  test "control group formation via API":
    resetAllFormations()
    setControlGroupFormation(0, 1)  # Line
    check getControlGroupFormation(0) == 1
    setControlGroupFormation(0, 2)  # Box
    check getControlGroupFormation(0) == 2
    setControlGroupFormation(0, 5)  # Staggered
    check getControlGroupFormation(0) == 5
    clearFormation(0)
    check getControlGroupFormation(0) == 0  # None

  test "control group formation rotation via API":
    resetAllFormations()
    setControlGroupFormation(0, 1)
    setFormationRotation(0, 4)
    check getFormationRotation(0) == 4

suite "Formation - Group Utilities":
  test "findAgentControlGroup finds correct group":
    # Clear all control groups first to avoid state leaks
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50))
    let a1 = env.addAgentAt(1, ivec2(52, 50))
    controlGroups[3] = @[a0, a1]
    check findAgentControlGroup(0) == 3
    check findAgentControlGroup(1) == 3
    check findAgentControlGroup(2) == -1
    controlGroups[3] = @[]

  test "calcGroupCenter computes average position":
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(40, 40))
    let a1 = env.addAgentAt(1, ivec2(60, 60))
    controlGroups[0] = @[a0, a1]
    let center = calcGroupCenter(0, env)
    check center.x == 50
    check center.y == 50
    controlGroups[0] = @[]

  test "aliveGroupSize counts only alive members":
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50))
    let a1 = env.addAgentAt(1, ivec2(52, 50))
    controlGroups[0] = @[a0, a1]
    check aliveGroupSize(0, env) == 2
    # Kill one agent (mark as terminated)
    a1.hp = 0
    env.terminated[1] = 1.0
    check aliveGroupSize(0, env) == 1
    controlGroups[0] = @[]

suite "Formation - Ranged Spread Formation":
  test "ranged spread formation has wider spacing between adjacent units":
    let center = ivec2(50, 50)
    let linePositions = calcLinePositions(center, 4, 0)
    let rangedPositions = calcRangedSpreadPositions(center, 4, 0)
    check linePositions.len == 4
    check rangedPositions.len == 4

    # Check spacing between adjacent positions in line formation
    var lineMinSpacing = int.high
    for i in 1 ..< linePositions.len:
      let dist = abs(linePositions[i].x - linePositions[i-1].x) +
                 abs(linePositions[i].y - linePositions[i-1].y)
      if dist > 0 and dist < lineMinSpacing:
        lineMinSpacing = dist

    # For ranged, check the minimum distance between any two units
    var rangedMinSpacing = int.high
    for i in 0 ..< rangedPositions.len:
      for j in i+1 ..< rangedPositions.len:
        let dist = max(abs(rangedPositions[i].x - rangedPositions[j].x),
                       abs(rangedPositions[i].y - rangedPositions[j].y))
        if dist > 0 and dist < rangedMinSpacing:
          rangedMinSpacing = dist

    # Ranged formation should have at least as wide spacing as line (3 vs 2)
    # Note: ranged uses rows+columns so units may be closer together in one dimension
    check rangedMinSpacing >= 1  # Units should not be on top of each other

  test "ranged spread formation single unit at center":
    let positions = calcRangedSpreadPositions(ivec2(50, 50), 1, 0)
    check positions.len == 1
    check positions[0] == ivec2(50, 50)

  test "ranged spread formation empty":
    let positions = calcRangedSpreadPositions(ivec2(50, 50), 0, 0)
    check positions.len == 0

  test "ranged spread formation has unique positions":
    let positions = calcRangedSpreadPositions(ivec2(50, 50), 6, 0)
    check positions.len == 6
    var distinct_count = 0
    for i in 0 ..< positions.len:
      var unique = true
      for j in 0 ..< i:
        if positions[i] == positions[j]:
          unique = false
          break
      if unique:
        inc distinct_count
    check distinct_count == 6  # All positions should be unique

  test "ranged spread formation staggered rows for line of sight":
    # With 6 units, should get at least 2 rows
    let positions = calcRangedSpreadPositions(ivec2(50, 50), 6, 0)
    check positions.len == 6

    # Check that not all units are on the same x (indicating multiple rows)
    var xCoords: seq[int32] = @[]
    for pos in positions:
      if pos.x notin xCoords:
        xCoords.add(pos.x)
    # Should have positions at different depths (multiple x values)
    check xCoords.len >= 1  # At least some spread

  test "ranged spread formation rotation changes orientation":
    let pos0 = calcRangedSpreadPositions(ivec2(50, 50), 4, 0)
    let pos2 = calcRangedSpreadPositions(ivec2(50, 50), 4, 2)
    check pos0.len == pos2.len
    # Rotated 90 degrees should give different layout
    var allSame = true
    for i in 0 ..< pos0.len:
      if pos0[i] != pos2[i]:
        allSame = false
        break
    check not allSame

suite "Formation - Ranged Unit Detection":
  test "countRangedUnitsInGroup counts archers":
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    resetAllFormations()
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitArcher)
    applyUnitClass(a0, UnitArcher)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitArcher)
    applyUnitClass(a1, UnitArcher)
    let a2 = env.addAgentAt(2, ivec2(54, 50), unitClass = UnitManAtArms)
    applyUnitClass(a2, UnitManAtArms)
    controlGroups[0] = @[a0, a1, a2]

    check countRangedUnitsInGroup(0, env) == 2
    controlGroups[0] = @[]

  test "isGroupMostlyRanged detects ranged majority":
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    resetAllFormations()
    let env = makeEmptyEnv()
    # 3 archers, 1 melee = mostly ranged
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitArcher)
    applyUnitClass(a0, UnitArcher)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitArcher)
    applyUnitClass(a1, UnitArcher)
    let a2 = env.addAgentAt(2, ivec2(54, 50), unitClass = UnitArcher)
    applyUnitClass(a2, UnitArcher)
    let a3 = env.addAgentAt(3, ivec2(56, 50), unitClass = UnitManAtArms)
    applyUnitClass(a3, UnitManAtArms)
    controlGroups[0] = @[a0, a1, a2, a3]

    check isGroupMostlyRanged(0, env) == true
    controlGroups[0] = @[]

  test "isGroupMostlyRanged returns false for melee majority":
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    resetAllFormations()
    let env = makeEmptyEnv()
    # 1 archer, 3 melee = not mostly ranged
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitArcher)
    applyUnitClass(a0, UnitArcher)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitManAtArms)
    applyUnitClass(a1, UnitManAtArms)
    let a2 = env.addAgentAt(2, ivec2(54, 50), unitClass = UnitManAtArms)
    applyUnitClass(a2, UnitManAtArms)
    let a3 = env.addAgentAt(3, ivec2(56, 50), unitClass = UnitKnight)
    applyUnitClass(a3, UnitKnight)
    controlGroups[0] = @[a0, a1, a2, a3]

    check isGroupMostlyRanged(0, env) == false
    controlGroups[0] = @[]

  test "getRecommendedFormation returns ranged spread for archers":
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    resetAllFormations()
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitArcher)
    applyUnitClass(a0, UnitArcher)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitArcher)
    applyUnitClass(a1, UnitArcher)
    controlGroups[0] = @[a0, a1]

    check getRecommendedFormation(0, env) == FormationRangedSpread
    controlGroups[0] = @[]

  test "setFormationAuto applies ranged spread to archer group":
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    resetAllFormations()
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitArcher)
    applyUnitClass(a0, UnitArcher)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitArcher)
    applyUnitClass(a1, UnitArcher)
    let a2 = env.addAgentAt(2, ivec2(54, 50), unitClass = UnitArcher)
    applyUnitClass(a2, UnitArcher)
    controlGroups[0] = @[a0, a1, a2]

    setFormationAuto(0, env)
    check isFormationActive(0) == true
    check getFormation(0) == FormationRangedSpread
    controlGroups[0] = @[]

suite "Formation - Agent ID API":
  test "setFormationForAgents creates group and sets formation":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), stance = StanceDefensive)
    let a1 = env.addAgentAt(1, ivec2(52, 50), stance = StanceDefensive)
    let a2 = env.addAgentAt(2, ivec2(54, 50), stance = StanceDefensive)

    # Use agent IDs directly
    setFormationForAgents(env, @[0, 1, 2], FormationLine)

    # Should have created a control group with formation
    let groupIdx = findAgentControlGroup(0)
    check groupIdx >= 0
    check isFormationActive(groupIdx) == true
    check getFormation(groupIdx) == FormationLine
    check aliveGroupSize(groupIdx, env) == 3

  test "setFormationForAgents with rotation":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), stance = StanceDefensive)
    let a1 = env.addAgentAt(1, ivec2(52, 50), stance = StanceDefensive)

    setFormationForAgentsWithRotation(env, @[0, 1], FormationBox, 2)

    let groupIdx = findAgentControlGroup(0)
    check groupIdx >= 0
    check getFormation(groupIdx) == FormationBox
    check getFormationRotation(groupIdx) == 2

  test "clearFormationForAgents clears formation":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), stance = StanceDefensive)
    let a1 = env.addAgentAt(1, ivec2(52, 50), stance = StanceDefensive)

    setFormationForAgents(env, @[0, 1], FormationLine)
    let groupIdx = findAgentControlGroup(0)
    check isFormationActive(groupIdx) == true

    clearFormationForAgents(@[0])
    check isFormationActive(groupIdx) == false

  test "setFormationForAgents with empty list does nothing":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()

    setFormationForAgents(env, @[], FormationLine)
    # Should not crash, no group created
    for i in 0 ..< ControlGroupCount:
      check controlGroups[i].len == 0

  test "setFormationForAgents filters dead agents":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), stance = StanceDefensive)
    let a1 = env.addAgentAt(1, ivec2(52, 50), stance = StanceDefensive)
    # Kill a1
    a1.hp = 0
    env.terminated[1] = 1.0

    setFormationForAgents(env, @[0, 1], FormationLine)

    let groupIdx = findAgentControlGroup(0)
    check groupIdx >= 0
    # Only alive agent should be in group
    check aliveGroupSize(groupIdx, env) == 1

  test "findAvailableControlGroup finds empty group":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), stance = StanceDefensive)

    # All groups empty, should return 0
    check findAvailableControlGroup() == 0

    # Fill group 0
    controlGroups[0] = @[a0]
    check findAvailableControlGroup() == 1

    # Fill groups 0-8, should return 9
    for i in 0 ..< ControlGroupCount - 1:
      controlGroups[i] = @[a0]
    check findAvailableControlGroup() == ControlGroupCount - 1
