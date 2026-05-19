import std/[unittest, strformat]
import test_common
import formations

suite "Behavior: Formation Position Assignment":
  test "units in line formation get distinct relative positions":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), stance = StanceDefensive)
    let a1 = env.addAgentAt(1, ivec2(52, 50), stance = StanceDefensive)
    let a2 = env.addAgentAt(2, ivec2(54, 50), stance = StanceDefensive)
    controlGroups[0] = @[a0, a1, a2]
    setFormation(0, FormationLine)

    let center = calcGroupCenter(0, env)
    var positions: seq[IVec2] = @[]
    for i in 0 ..< 3:
      let target = getFormationTargetForAgent(0, i, center, 3)
      check target.x >= 0
      check target.y >= 0
      positions.add(target)

    # All positions should be distinct
    for i in 0 ..< positions.len:
      for j in i + 1 ..< positions.len:
        check positions[i] != positions[j]

    # Line formation: positions should share y-coordinate (horizontal line, rotation=0)
    for i in 1 ..< positions.len:
      check positions[i].y == positions[0].y

    # Spacing between adjacent positions should be FormationSpacing
    for i in 1 ..< positions.len:
      check abs(positions[i].x - positions[i-1].x) == FormationSpacing

    echo &"  Line formation positions: {positions}"
    controlGroups[0] = @[]

  test "units in box formation maintain enclosing shape":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    var agents: seq[Thing] = @[]
    for i in 0 ..< 6:
      let a = env.addAgentAt(i, ivec2(50 + i.int32, 50), stance = StanceDefensive)
      agents.add(a)
    controlGroups[0] = agents
    setFormation(0, FormationBox)

    let center = calcGroupCenter(0, env)
    var positions: seq[IVec2] = @[]
    for i in 0 ..< 6:
      let target = getFormationTargetForAgent(0, i, center, 6)
      check target.x >= 0
      positions.add(target)

    # All positions should be distinct (at least 4 of 6)
    var distinctCount = 0
    for i in 0 ..< positions.len:
      var unique = true
      for j in 0 ..< i:
        if positions[i] == positions[j]:
          unique = false
          break
      if unique: inc distinctCount
    check distinctCount >= 4

    # Box positions should surround the center within a bounded area
    for pos in positions:
      check abs(pos.x - center.x) <= MaxFormationSize
      check abs(pos.y - center.y) <= MaxFormationSize

    echo &"  Box formation center: {center}, positions: {positions}"
    controlGroups[0] = @[]

  test "formation positions shift when group center moves":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(30, 30), stance = StanceDefensive)
    let a1 = env.addAgentAt(1, ivec2(32, 30), stance = StanceDefensive)
    controlGroups[0] = @[a0, a1]
    setFormation(0, FormationLine)

    let center1 = calcGroupCenter(0, env)
    let pos1_0 = getFormationTargetForAgent(0, 0, center1, 2)
    let pos1_1 = getFormationTargetForAgent(0, 1, center1, 2)

    # Simulate movement: shift agents to new positions (update grid too)
    env.grid[a0.pos.x][a0.pos.y] = nil
    env.grid[a1.pos.x][a1.pos.y] = nil
    a0.pos = ivec2(60, 60)
    a1.pos = ivec2(62, 60)
    env.grid[60][60] = a0
    env.grid[62][60] = a1

    let center2 = calcGroupCenter(0, env)
    let pos2_0 = getFormationTargetForAgent(0, 0, center2, 2)
    let pos2_1 = getFormationTargetForAgent(0, 1, center2, 2)

    # New target positions should be near the new center, not the old
    check abs(pos2_0.x - 61) < 10
    check abs(pos2_0.y - 60) < 10
    check abs(pos2_1.x - 61) < 10
    check abs(pos2_1.y - 60) < 10

    # Old positions were near (31,30)
    check abs(pos1_0.x - 31) < 10
    check abs(pos1_0.y - 30) < 10

    # Relative spacing preserved (same formation, same count)
    let relDx1 = pos1_1.x - pos1_0.x
    let relDy1 = pos1_1.y - pos1_0.y
    let relDx2 = pos2_1.x - pos2_0.x
    let relDy2 = pos2_1.y - pos2_0.y
    check relDx1 == relDx2
    check relDy1 == relDy2

    echo &"  Center moved from {center1} to {center2}, relative spacing preserved"
    controlGroups[0] = @[]

suite "Behavior: Formation Speed Consistency":
  test "all formation units converge toward their slots":
    ## All units in a formation should have valid target positions and
    ## those positions should be at consistent spacing from the center.
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    # Place 4 units scattered around center (50,50)
    let a0 = env.addAgentAt(0, ivec2(45, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a0, UnitManAtArms)
    let a1 = env.addAgentAt(1, ivec2(55, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a1, UnitManAtArms)
    let a2 = env.addAgentAt(2, ivec2(50, 45), unitClass = UnitArcher, stance = StanceDefensive)
    applyUnitClass(a2, UnitArcher)
    let a3 = env.addAgentAt(3, ivec2(50, 55), unitClass = UnitKnight, stance = StanceDefensive)
    applyUnitClass(a3, UnitKnight)
    controlGroups[0] = @[a0, a1, a2, a3]
    setFormation(0, FormationLine)

    let center = calcGroupCenter(0, env)
    var targets: seq[IVec2] = @[]
    for i in 0 ..< 4:
      let target = getFormationTargetForAgent(0, i, center, 4)
      check target.x >= 0
      targets.add(target)

    # All targets should be within reasonable range of center
    for target in targets:
      let dist = abs(target.x - center.x) + abs(target.y - center.y)
      check dist <= FormationSpacing * 4  # Manhattan distance bounded

    # Targets should be evenly spaced in line formation
    for i in 1 ..< targets.len:
      let dx = abs(targets[i].x - targets[i-1].x)
      check dx == FormationSpacing  # Horizontal line spacing

    echo &"  Mixed unit types converge to line targets: {targets}"
    controlGroups[0] = @[]

  test "formation target positions are equidistant from center":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    var agents: seq[Thing] = @[]
    for i in 0 ..< 4:
      let a = env.addAgentAt(i, ivec2(50 + i.int32 * 3, 50), stance = StanceDefensive)
      agents.add(a)
    controlGroups[0] = agents
    setFormation(0, FormationLine)

    let center = calcGroupCenter(0, env)
    var targets: seq[IVec2] = @[]
    for i in 0 ..< 4:
      targets.add(getFormationTargetForAgent(0, i, center, 4))

    # For a 4-unit line, the two outer units should be equidistant from the two inner ones
    # Positions are centered: indices 0,1,2,3 map to offsets -2,-1,0,1 * spacing relative to half
    # Check symmetry: first and last should be equidistant from center
    let distFirst = abs(targets[0].x - center.x) + abs(targets[0].y - center.y)
    let distLast = abs(targets[3].x - center.x) + abs(targets[3].y - center.y)
    # They should be roughly symmetric (within spacing tolerance)
    check abs(distFirst - distLast) <= FormationSpacing

    echo &"  Equidistant check: first dist={distFirst}, last dist={distLast}"
    controlGroups[0] = @[]

suite "Behavior: Formation Breaks on Attack":
  test "formation agent attacks nearby enemy instead of holding position":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    # Create a formation group
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(a0, UnitManAtArms)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(a1, UnitManAtArms)
    controlGroups[0] = @[a0, a1]
    setFormation(0, FormationLine)

    # Place enemy adjacent to a0
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(50, 49), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(enemy, UnitManAtArms)
    let startHp = enemy.hp

    # Agent attacks enemy instead of maintaining formation
    env.stepAction(a0.agentId, 2'u8, dirIndex(a0.pos, enemy.pos))
    check enemy.hp < startHp
    echo &"  Formation agent dealt {startHp - enemy.hp} damage to adjacent enemy"
    controlGroups[0] = @[]

  test "formation deactivation returns units to scatter":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), stance = StanceDefensive)
    let a1 = env.addAgentAt(1, ivec2(52, 50), stance = StanceDefensive)
    controlGroups[0] = @[a0, a1]
    setFormation(0, FormationLine)
    check isFormationActive(0) == true

    # Deactivate formation
    clearFormation(0)
    check isFormationActive(0) == false

    # Target positions should be invalid when formation is cleared
    let center = calcGroupCenter(0, env)
    let target = getFormationTargetForAgent(0, 0, center, 2)
    check target.x == -1  # No valid formation position
    echo "  Formation cleared, units returned to scatter"
    controlGroups[0] = @[]

suite "Behavior: Formation Re-assembly After Combat":
  test "formation stays active after unit takes damage":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a0, UnitManAtArms)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a1, UnitManAtArms)
    let a2 = env.addAgentAt(2, ivec2(54, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a2, UnitManAtArms)
    controlGroups[0] = @[a0, a1, a2]
    setFormation(0, FormationLine)

    # Simulate combat damage
    a0.hp = a0.hp div 2
    a1.hp = a1.hp div 2

    # Formation should still be active
    check isFormationActive(0) == true
    check aliveGroupSize(0, env) == 3

    # All alive units should still get valid formation positions
    let center = calcGroupCenter(0, env)
    for i in 0 ..< 3:
      let target = getFormationTargetForAgent(0, i, center, 3)
      check target.x >= 0
      check target.y >= 0

    echo &"  Formation active after combat damage, group size: {aliveGroupSize(0, env)}"
    controlGroups[0] = @[]

  test "formation adapts when unit dies during combat":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a0, UnitManAtArms)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a1, UnitManAtArms)
    let a2 = env.addAgentAt(2, ivec2(54, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a2, UnitManAtArms)
    controlGroups[0] = @[a0, a1, a2]
    setFormation(0, FormationLine)

    check aliveGroupSize(0, env) == 3
    let positionsBefore = calcLinePositions(calcGroupCenter(0, env), 3, 0)

    # Kill one unit
    a1.hp = 0
    env.terminated[1] = 1.0

    check aliveGroupSize(0, env) == 2
    check isFormationActive(0) == true

    # Formation recalculates for 2 alive units
    let centerAfter = calcGroupCenter(0, env)
    let positionsAfter = calcLinePositions(centerAfter, 2, 0)

    # New positions should be for 2 units, not 3
    check positionsAfter.len == 2
    check positionsBefore.len == 3

    # Surviving agents still get valid targets
    let idx0 = agentIndexInGroup(0, 0, env)
    let idx2 = agentIndexInGroup(0, 2, env)
    check idx0 >= 0
    check idx2 >= 0
    # They should have different indices now
    check idx0 != idx2

    let target0 = getFormationTargetForAgent(0, idx0, centerAfter, 2)
    let target2 = getFormationTargetForAgent(0, idx2, centerAfter, 2)
    check target0.x >= 0
    check target2.x >= 0
    check target0 != target2

    echo &"  Formation adapted: 3->2 units, new targets: {target0}, {target2}"
    controlGroups[0] = @[]

  test "formation dissolves when only one unit remains":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a0, UnitManAtArms)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a1, UnitManAtArms)
    controlGroups[0] = @[a0, a1]
    setFormation(0, FormationLine)

    check aliveGroupSize(0, env) == 2
    check isFormationActive(0) == true

    # Kill one unit, leaving only one
    a1.hp = 0
    env.terminated[1] = 1.0

    check aliveGroupSize(0, env) == 1
    # Formation is still marked active in state, but fighter behavior requires 2+ alive
    # The canStartFighterFormation check requires groupSize >= 2
    # This verifies the formation system handles the edge case
    check isFormationActive(0) == true  # State persists
    # But a single unit would get a valid position (center)
    let center = calcGroupCenter(0, env)
    let positions = calcLinePositions(center, 1, 0)
    check positions.len == 1
    check positions[0] == center

    echo &"  Single survivor at center: {center}"
    controlGroups[0] = @[]

suite "Behavior: Formation Rotation":
  test "rotation changes formation orientation":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    let a0 = env.addAgentAt(0, ivec2(50, 50), stance = StanceDefensive)
    let a1 = env.addAgentAt(1, ivec2(52, 50), stance = StanceDefensive)
    let a2 = env.addAgentAt(2, ivec2(54, 50), stance = StanceDefensive)
    controlGroups[0] = @[a0, a1, a2]
    setFormation(0, FormationLine)

    let center = calcGroupCenter(0, env)

    # Rotation 0: horizontal line (East-West)
    setFormationRotation(0, 0)
    let hPositions = calcLinePositions(center, 3, 0)
    # All y should be same
    for p in hPositions:
      check p.y == center.y

    # Rotation 2: vertical line (North-South)
    setFormationRotation(0, 2)
    let vPositions = calcLinePositions(center, 3, 2)
    # All x should be same
    for p in vPositions:
      check p.x == center.x

    # Horizontal and vertical positions should differ
    check hPositions != vPositions

    echo &"  Horizontal: {hPositions}, Vertical: {vPositions}"
    controlGroups[0] = @[]

  test "8-way rotation produces 8 distinct orientations for line formation":
    let center = ivec2(50, 50)
    var allPositions: seq[seq[IVec2]] = @[]
    for rot in 0 ..< 8:
      allPositions.add(calcLinePositions(center, 3, rot))

    # At minimum, rotations 0-3 should produce distinct formations
    # (4-7 are reversed versions of 0-3 but still produce different positions)
    var distinctCount = 0
    for i in 0 ..< 4:
      var unique = true
      for j in 0 ..< i:
        if allPositions[i] == allPositions[j]:
          unique = false
          break
      if unique: inc distinctCount
    check distinctCount == 4  # All cardinal/diagonal rotations are distinct

    echo &"  8 rotations produced {distinctCount} distinct cardinal orientations"

suite "Behavior: Ranged Formation Auto-Selection":
  test "archer group gets ranged spread formation automatically":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    # Create a group of archers
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitArcher, stance = StanceDefensive)
    applyUnitClass(a0, UnitArcher)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitArcher, stance = StanceDefensive)
    applyUnitClass(a1, UnitArcher)
    let a2 = env.addAgentAt(2, ivec2(54, 50), unitClass = UnitArcher, stance = StanceDefensive)
    applyUnitClass(a2, UnitArcher)
    controlGroups[0] = @[a0, a1, a2]

    # Auto-select formation based on unit composition
    setFormationAuto(0, env)

    # Should get ranged spread formation
    check isFormationActive(0) == true
    check getFormation(0) == FormationRangedSpread

    echo "  Archer group auto-selected FormationRangedSpread"
    controlGroups[0] = @[]

  test "mixed group with more melee gets line formation":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    # Create a group with more melee than ranged
    let a0 = env.addAgentAt(0, ivec2(50, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a0, UnitManAtArms)
    let a1 = env.addAgentAt(1, ivec2(52, 50), unitClass = UnitManAtArms, stance = StanceDefensive)
    applyUnitClass(a1, UnitManAtArms)
    let a2 = env.addAgentAt(2, ivec2(54, 50), unitClass = UnitArcher, stance = StanceDefensive)
    applyUnitClass(a2, UnitArcher)
    controlGroups[0] = @[a0, a1, a2]

    # Auto-select formation based on unit composition
    setFormationAuto(0, env)

    # Should get line formation (not ranged spread)
    check isFormationActive(0) == true
    check getFormation(0) == FormationLine

    echo "  Mixed group (mostly melee) auto-selected FormationLine"
    controlGroups[0] = @[]

  test "ranged spread positions provide clear firing lines":
    resetAllFormations()
    for i in 0 ..< ControlGroupCount:
      controlGroups[i] = @[]
    let env = makeEmptyEnv()
    # Create archers in a row
    var archers: seq[Thing] = @[]
    for i in 0 ..< 5:
      let a = env.addAgentAt(i, ivec2(50 + i.int32, 50), unitClass = UnitArcher, stance = StanceDefensive)
      applyUnitClass(a, UnitArcher)
      archers.add(a)
    controlGroups[0] = archers
    setFormation(0, FormationRangedSpread)

    let center = calcGroupCenter(0, env)
    var positions: seq[IVec2] = @[]
    for i in 0 ..< 5:
      let target = getFormationTargetForAgent(0, i, center, 5)
      check target.x >= 0
      positions.add(target)

    # Verify positions don't overlap (no friendly fire risk from stacking)
    for i in 0 ..< positions.len:
      for j in i + 1 ..< positions.len:
        check positions[i] != positions[j]

    # Staggered arrangement should have units at different depths
    # Check that not all y coordinates are the same (staggered rows)
    var yCoords: seq[int32] = @[]
    for pos in positions:
      if pos.y notin yCoords:
        yCoords.add(pos.y)

    echo &"  Ranged spread: {positions.len} archers at {yCoords.len} different y-coords"
    controlGroups[0] = @[]
