import std/[unittest, strformat]
import test_common

suite "Behavior: Fog of War Visibility on Unit Movement":
  test "unit reveals tiles at new position after moving":
    let env = makeEmptyEnv()
    let teamId = 0
    let startPos = ivec2(50, 50)
    let scout = addAgentAt(env, teamId, startPos)
    applyUnitClass(scout, UnitScout)

    # Reveal at starting position
    env.updateRevealedMapFromVision(scout)
    check env.isRevealed(teamId, startPos)

    # Move scout far enough that new tiles are outside old vision
    let newPos = ivec2(50 + ScoutVisionRange * 2 + 5, 50)
    scout.pos = newPos
    env.updateRevealedMapFromVision(scout)

    # New position should be revealed
    check env.isRevealed(teamId, newPos)
    # Tiles near new position should be revealed
    check env.isRevealed(teamId, ivec2(newPos.x + ScoutVisionRange, newPos.y))
    echo &"  Scout moved from {startPos} to {newPos}, new area revealed"

  test "previously explored tiles stay revealed after unit moves away":
    let env = makeEmptyEnv()
    let teamId = 0
    let startPos = ivec2(30, 30)
    let scout = addAgentAt(env, teamId, startPos)
    applyUnitClass(scout, UnitScout)

    # Reveal at start
    env.updateRevealedMapFromVision(scout)
    check env.isRevealed(teamId, startPos)
    let countAfterFirst = env.getRevealedTileCount(teamId)

    # Move scout far away
    let newPos = ivec2(100, 100)
    scout.pos = newPos
    env.updateRevealedMapFromVision(scout)

    # Old position should still be revealed (fog of war reveals permanently)
    check env.isRevealed(teamId, startPos)
    check env.isRevealed(teamId, ivec2(30 + ScoutVisionRange, 30))

    # Total revealed tiles should have increased
    let countAfterSecond = env.getRevealedTileCount(teamId)
    check countAfterSecond > countAfterFirst
    echo &"  Revealed tiles: {countAfterFirst} -> {countAfterSecond} (old area retained)"

  test "unexplored tiles remain hidden":
    let env = makeEmptyEnv()
    let teamId = 0
    let scout = addAgentAt(env, teamId, ivec2(20, 20))
    applyUnitClass(scout, UnitScout)

    env.updateRevealedMapFromVision(scout)

    # Far away tiles should not be revealed
    check not env.isRevealed(teamId, ivec2(150, 150))
    check not env.isRevealed(teamId, ivec2(20 + ScoutVisionRange + 5, 20))
    echo "  Distant tiles correctly remain hidden"

suite "Behavior: Shared Vision Between Teammates":
  test "two units on same team contribute to shared revealed map":
    let env = makeEmptyEnv()
    let teamId = 0

    # Place two units on the same team far apart
    let unit1 = addAgentAt(env, 0, ivec2(20, 20))
    let unit2 = addAgentAt(env, 1, ivec2(80, 80))  # Same team (agentId 1 < 125)

    env.updateRevealedMapFromVision(unit1)
    env.updateRevealedMapFromVision(unit2)

    # Both areas should be revealed for the team
    check env.isRevealed(teamId, ivec2(20, 20))
    check env.isRevealed(teamId, ivec2(80, 80))
    check env.isRevealed(teamId, ivec2(20 + ThreatVisionRange, 20))
    check env.isRevealed(teamId, ivec2(80 + ThreatVisionRange, 80))
    echo "  Both teammates' vision merged into shared map"

  test "teammate vision does not reveal for opposing team":
    let env = makeEmptyEnv()
    let team0 = 0
    let team1 = 1

    # Team 0 unit
    let unit0 = addAgentAt(env, 0, ivec2(30, 30))
    env.updateRevealedMapFromVision(unit0)

    # Team 1 unit at different location
    let unit1 = addAgentAt(env, MapAgentsPerTeam, ivec2(80, 80))
    env.updateRevealedMapFromVision(unit1)

    # Team 0 should NOT see team 1's explored area
    check not env.isRevealed(team0, ivec2(80, 80))
    # Team 1 should NOT see team 0's explored area
    check not env.isRevealed(team1, ivec2(30, 30))
    echo "  Team vision correctly isolated"

  test "multiple teammates incrementally explore the map":
    let env = makeEmptyEnv()
    let teamId = 0

    # First scout explores
    let scout1 = addAgentAt(env, 0, ivec2(30, 30))
    applyUnitClass(scout1, UnitScout)
    env.updateRevealedMapFromVision(scout1)
    let countAfterFirst = env.getRevealedTileCount(teamId)

    # Second scout explores a different area
    let scout2 = addAgentAt(env, 1, ivec2(90, 90))
    applyUnitClass(scout2, UnitScout)
    env.updateRevealedMapFromVision(scout2)
    let countAfterSecond = env.getRevealedTileCount(teamId)

    # Third scout fills in between
    let scout3 = addAgentAt(env, 2, ivec2(60, 60))
    applyUnitClass(scout3, UnitScout)
    env.updateRevealedMapFromVision(scout3)
    let countAfterThird = env.getRevealedTileCount(teamId)

    check countAfterSecond > countAfterFirst
    check countAfterThird > countAfterSecond
    echo &"  Incremental exploration: {countAfterFirst} -> {countAfterSecond} -> {countAfterThird} tiles"

suite "Behavior: Buildings Remain Visible After Scouting":
  test "scouted building location stays revealed after scout leaves":
    let env = makeEmptyEnv()
    let team0 = 0
    let buildingPos = ivec2(60, 60)

    # Enemy team has a building
    discard addBuilding(env, Barracks, buildingPos, teamId = 1)

    # Team 0 scout explores near the building
    let scout = addAgentAt(env, 0, ivec2(60, 55))
    applyUnitClass(scout, UnitScout)
    env.updateRevealedMapFromVision(scout)

    # Building position should be revealed
    check env.isRevealed(team0, buildingPos)

    # Move scout far away
    scout.pos = ivec2(150, 150)
    env.updateRevealedMapFromVision(scout)

    # Building position should STILL be revealed (explored tiles persist)
    check env.isRevealed(team0, buildingPos)
    echo "  Building location remains revealed after scout departs"

  test "unscouted enemy building is not revealed":
    let env = makeEmptyEnv()
    let team0 = 0
    let buildingPos = ivec2(140, 140)

    # Enemy building far from any team 0 units
    discard addBuilding(env, Castle, buildingPos, teamId = 1)

    # Team 0 scout is nowhere near
    let scout = addAgentAt(env, 0, ivec2(20, 20))
    applyUnitClass(scout, UnitScout)
    env.updateRevealedMapFromVision(scout)

    # Building position should NOT be revealed
    check not env.isRevealed(team0, buildingPos)
    echo "  Unscouted enemy building correctly hidden"

  test "multiple buildings scouted in sequence all stay revealed":
    let env = makeEmptyEnv()
    let team0 = 0

    # Enemy buildings at various positions
    let bldg1Pos = ivec2(40, 40)
    let bldg2Pos = ivec2(80, 40)
    let bldg3Pos = ivec2(120, 40)
    discard addBuilding(env, Barracks, bldg1Pos, teamId = 1)
    discard addBuilding(env, ArcheryRange, bldg2Pos, teamId = 1)
    discard addBuilding(env, Stable, bldg3Pos, teamId = 1)

    let scout = addAgentAt(env, 0, bldg1Pos)
    applyUnitClass(scout, UnitScout)

    # Scout each building position in sequence
    env.updateRevealedMapFromVision(scout)
    check env.isRevealed(team0, bldg1Pos)

    scout.pos = bldg2Pos
    env.updateRevealedMapFromVision(scout)
    check env.isRevealed(team0, bldg2Pos)

    scout.pos = bldg3Pos
    env.updateRevealedMapFromVision(scout)
    check env.isRevealed(team0, bldg3Pos)

    # All previously scouted buildings should still be revealed
    check env.isRevealed(team0, bldg1Pos)
    check env.isRevealed(team0, bldg2Pos)
    check env.isRevealed(team0, bldg3Pos)
    echo "  All 3 building locations remain revealed after sequential scouting"

suite "Behavior: Enemy Units and Threat Map Decay":
  test "enemy unit detected within vision range is reported as threat":
    let env = makeEmptyEnv()
    let controller = newTestController(42)
    let team0 = 0

    # Team 0 scout
    let scout = addAgentAt(env, 0, ivec2(50, 50))
    applyUnitClass(scout, UnitScout)

    # Enemy unit within vision range
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(50 + ThreatVisionRange - 1, 50))
    applyUnitClass(enemy, UnitKnight)

    # Build spatial index so threat detection works
    env.rebuildSpatialIndex()
    controller.updateThreatMapFromVision(env, scout, currentStep = 0)

    # Should detect the enemy
    check controller.hasKnownThreats(team0, currentStep = 0)
    let nearest = controller.getNearestThreat(team0, scout.pos, currentStep = 0)
    check nearest.found
    check nearest.pos == enemy.pos
    echo &"  Enemy detected at {enemy.pos}, threat reported"

  test "enemy threat decays after leaving vision and time passes":
    let env = makeEmptyEnv()
    let controller = newTestController(42)
    let team0 = 0

    # Team 0 scout spots enemy
    let scout = addAgentAt(env, 0, ivec2(50, 50))
    applyUnitClass(scout, UnitScout)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))

    env.rebuildSpatialIndex()
    controller.updateThreatMapFromVision(env, scout, currentStep = 0)
    check controller.hasKnownThreats(team0, currentStep = 0)

    # Move enemy far away (out of vision)
    enemy.pos = ivec2(150, 150)
    env.rebuildSpatialIndex()

    # Scout scans again but doesn't see enemy anymore
    controller.updateThreatMapFromVision(env, scout, currentStep = 10)

    # Threat still exists (hasn't decayed yet, ThreatDecaySteps = 50)
    check controller.hasKnownThreats(team0, currentStep = 10)

    # After enough steps without re-sighting, threat decays
    controller.decayThreats(team0, currentStep = ThreatDecaySteps + 1)
    check not controller.hasKnownThreats(team0, currentStep = ThreatDecaySteps + 1)
    echo &"  Enemy threat decayed after {ThreatDecaySteps} steps without sighting"

  test "enemy unit beyond vision range is not detected":
    let env = makeEmptyEnv()
    let controller = newTestController(42)
    let team0 = 0

    let scout = addAgentAt(env, 0, ivec2(50, 50))
    applyUnitClass(scout, UnitScout)

    # Enemy beyond scout vision range
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(50 + ScoutVisionRange + 5, 50))

    env.rebuildSpatialIndex()
    controller.updateThreatMapFromVision(env, scout, currentStep = 0)

    # Should NOT detect the enemy
    check not controller.hasKnownThreats(team0, currentStep = 0)
    echo "  Enemy beyond vision range correctly undetected"

  test "re-sighting enemy refreshes threat and prevents decay":
    let env = makeEmptyEnv()
    let controller = newTestController(42)
    let team0 = 0

    let scout = addAgentAt(env, 0, ivec2(50, 50))
    applyUnitClass(scout, UnitScout)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(55, 50))

    env.rebuildSpatialIndex()

    # Spot enemy at step 0
    controller.updateThreatMapFromVision(env, scout, currentStep = 0)
    check controller.hasKnownThreats(team0, currentStep = 0)

    # Re-sight at step 40 (before decay at 50)
    controller.updateThreatMapFromVision(env, scout, currentStep = 40)

    # Decay at step 51 - threat should still exist because last seen at step 40
    controller.decayThreats(team0, currentStep = 51)
    check controller.hasKnownThreats(team0, currentStep = 51)

    # But should decay by step 91 (40 + 50 + 1)
    controller.decayThreats(team0, currentStep = 91)
    check not controller.hasKnownThreats(team0, currentStep = 91)
    echo "  Re-sighting refreshes threat timer correctly"
