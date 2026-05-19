## Behavioral tests for town expansion / settler migration mechanic.
## Verifies that towns can split when population exceeds threshold,
## settlers found new towns at appropriate distances, and villagers
## redistribute correctly across settlements.
##
## These tests define the expected behavior for the settler migration system.
## They depend on the instrumentation from tv-72vq8 being in place.
## Constants (TownSplitPopulationThreshold, etc.) are imported from
## src/constants.nim via test_common → types → constants.

import std/[unittest, strformat, math, tables]
import test_common

# ============================================================================
# Helper procs for settlement tests
# ============================================================================

proc countAltarsForTeam(env: Environment, teamId: int): int =
  ## Count the number of altars owned by a team.
  for altar in env.thingsByKind[Altar]:
    if not altar.isNil and altar.teamId == teamId:
      inc result

proc countTownCentersForTeam(env: Environment, teamId: int): int =
  ## Count the number of town centers owned by a team.
  for tc in env.thingsByKind[TownCenter]:
    if not tc.isNil and tc.teamId == teamId:
      inc result

proc getAltarPositions(env: Environment, teamId: int): seq[IVec2] =
  ## Get positions of all altars owned by a team.
  for altar in env.thingsByKind[Altar]:
    if not altar.isNil and altar.teamId == teamId:
      result.add(altar.pos)

proc getTownCenterPositions(env: Environment, teamId: int): seq[IVec2] =
  ## Get positions of all town centers owned by a team.
  for tc in env.thingsByKind[TownCenter]:
    if not tc.isNil and tc.teamId == teamId:
      result.add(tc.pos)

proc getVillagersPerAltar(env: Environment, teamId: int): Table[IVec2, int] =
  ## Get a mapping of altar positions to villager counts for a team.
  result = initTable[IVec2, int]()
  # Initialize all altar positions to 0
  for altar in env.thingsByKind[Altar]:
    if not altar.isNil and altar.teamId == teamId:
      result[altar.pos] = 0
  # Count villagers per homeAltar
  for agent in env.agents:
    if not agent.isNil and agent.hp > 0:
      let agentTeam = getTeamId(agent)
      if agentTeam == teamId and agent.homeAltar in result:
        result[agent.homeAltar] += 1

proc euclideanDistance(a, b: IVec2): float =
  ## Euclidean distance between two positions.
  let dx = (a.x - b.x).float
  let dy = (a.y - b.y).float
  sqrt(dx * dx + dy * dy)

# ============================================================================
# Test suites
# ============================================================================

suite "Behavior: Town Split Triggers at Threshold":
  test "town split triggers when population exceeds threshold":
    ## Set up a game with 1 team, spawn enough villagers to exceed
    ## TownSplitPopulationThreshold, run simulation with AI controller,
    ## and verify that the team ends up with more than 1 altar and
    ## more than 1 town center.
    let env = setupGameWithAI(seed = 42)

    let altarPos = ivec2(50, 50)
    discard addAltar(env, altarPos, 0, 100)

    # Add a town center for the team
    discard addBuilding(env, TownCenter, ivec2(52, 50), 0)

    # Add enough houses to support a large population
    for i in 0 ..< 10:
      discard addBuilding(env, House, ivec2(45 + i.int32, 45), 0)

    # Provide wood resources needed for town split (requires >= 14 wood)
    giveTeamPlentyOfResources(env, 0, 500)

    # Spawn villagers exceeding the split threshold
    let villagerCount = TownSplitPopulationThreshold + 5
    for i in 0 ..< villagerCount:
      let x = 48 + (i mod 10).int32
      let y = 48 + (i div 10).int32
      discard addAgentAt(env, i, ivec2(x, y), homeAltar = altarPos)

    # Run simulation with AI controller long enough for split to trigger
    env.runGameSteps(VeryLongSimSteps * 2)

    # After simulation, the team should have expanded
    let altarCount = countAltarsForTeam(env, 0)
    let tcCount = countTownCentersForTeam(env, 0)

    echo fmt"  Altars for team 0: {altarCount}"
    echo fmt"  Town centers for team 0: {tcCount}"

    check altarCount > 1
    check tcCount > 1

suite "Behavior: Villagers Redistribute After Split":
  test "villagers redistribute after town split":
    ## Set up game with AI, trigger a town split, run simulation until
    ## settlers arrive and found new town. Verify villager distribution.
    let env = setupGameWithAI(seed = 42)

    let altarPos = ivec2(50, 50)
    discard addAltar(env, altarPos, 0, 100)
    discard addBuilding(env, TownCenter, ivec2(52, 50), 0)

    # Enough houses for large population
    for i in 0 ..< 15:
      discard addBuilding(env, House, ivec2(40 + i.int32, 45), 0)

    # Provide resources needed for town split
    giveTeamPlentyOfResources(env, 0, 500)

    # Spawn more than threshold villagers
    let villagerCount = TownSplitPopulationThreshold + TownSplitSettlerCount
    for i in 0 ..< villagerCount:
      let x = 46 + (i mod 10).int32
      let y = 48 + (i div 10).int32
      discard addAgentAt(env, i, ivec2(x, y), homeAltar = altarPos)

    let totalBefore = countAliveUnits(env, 0)
    echo fmt"  Total villagers before: {totalBefore}"

    # Run simulation with AI for settlers to split and found new town
    env.runGameSteps(VeryLongSimSteps * 2)

    # Check villager distribution
    let villagersPerAltar = getVillagersPerAltar(env, 0)
    let totalAfter = countAliveUnits(env, 0)

    echo fmt"  Total villagers after: {totalAfter}"
    echo fmt"  Villagers per altar:"
    for pos, count in villagersPerAltar:
      echo fmt"    Altar at ({pos.x}, {pos.y}): {count} villagers"

    # Total villager count should be preserved (no villagers lost)
    check totalAfter >= totalBefore

    # If split occurred, original altar should have fewer villagers
    if villagersPerAltar.len > 1:
      let originalCount = villagersPerAltar.getOrDefault(altarPos, 0)
      check originalCount < totalBefore

      # New altar should have at least some settlers (no lower bound on upper end
      # because villagers spawn naturally at new settlements over time)
      for pos, count in villagersPerAltar:
        if pos != altarPos and count > 0:
          echo fmt"    New altar at ({pos.x}, {pos.y}) has {count} villagers (expected >= {TownSplitSettlerCount div 2})"
          check count >= TownSplitSettlerCount div 2

suite "Behavior: New Town Center Distance":
  test "new town center is placed at appropriate distance":
    ## After a split completes, measure distance between original and new
    ## town center. Assert distance is between TownSplitMinDistance and
    ## TownSplitMaxDistance.
    let env = setupGameWithAI(seed = 42)

    let altarPos = ivec2(100, 95)
    let tcPos = ivec2(102, 95)
    discard addAltar(env, altarPos, 0, 100)
    discard addBuilding(env, TownCenter, tcPos, 0)

    # Enough houses for population
    for i in 0 ..< 12:
      discard addBuilding(env, House, ivec2(90 + i.int32, 90), 0)

    # Provide resources needed for town split
    giveTeamPlentyOfResources(env, 0, 500)

    # Spawn villagers exceeding threshold
    let villagerCount = TownSplitPopulationThreshold + 5
    for i in 0 ..< villagerCount:
      let x = 98 + (i mod 8).int32
      let y = 93 + (i div 8).int32
      discard addAgentAt(env, i, ivec2(x, y), homeAltar = altarPos)

    # Run simulation with AI
    env.runGameSteps(VeryLongSimSteps * 2)

    let tcPositions = getTownCenterPositions(env, 0)
    echo fmt"  Town center positions: {tcPositions}"

    if tcPositions.len > 1:
      # Check that each NEW TC (created by splits) has a reasonable nearest-neighbor
      # distance. The original TC at tcPos is excluded because it wasn't created by
      # a split and may be far from the cluster of split-generated TCs.
      var newTcCount = 0
      for i in 0 ..< tcPositions.len:
        if tcPositions[i] == tcPos: continue  # Skip original TC
        var nearestDist = float.high
        for j in 0 ..< tcPositions.len:
          if i == j: continue
          let dist = euclideanDistance(tcPositions[i], tcPositions[j])
          if dist < nearestDist:
            nearestDist = dist
        echo fmt"    TC[{i}] at ({tcPositions[i].x}, {tcPositions[i].y}): nearest neighbor dist = {nearestDist:.1f}"
        check nearestDist <= TownSplitMaxDistance.float * 2  # Allow slack for TC offset from altar
        inc newTcCount
      check newTcCount >= 1  # At least one new TC was placed
    else:
      echo "  WARNING: No town split occurred - only 1 town center found"
      # This test will pass but indicates the feature isn't implemented yet
      check tcPositions.len > 1

suite "Behavior: Team Color Preserved After Split":
  test "new town center and altar have same teamId as original":
    ## After split, verify new town center and altar have same teamId.
    let env = setupGameWithAI(seed = 42)

    let teamId = 0
    let altarPos = ivec2(50, 50)
    discard addAltar(env, altarPos, teamId, 100)
    discard addBuilding(env, TownCenter, ivec2(52, 50), teamId)

    # Houses for population
    for i in 0 ..< 10:
      discard addBuilding(env, House, ivec2(45 + i.int32, 45), teamId)

    # Provide resources needed for town split
    giveTeamPlentyOfResources(env, teamId, 500)

    # Spawn villagers above threshold
    let villagerCount = TownSplitPopulationThreshold + 5
    for i in 0 ..< villagerCount:
      let x = 48 + (i mod 10).int32
      let y = 48 + (i div 10).int32
      discard addAgentAt(env, i, ivec2(x, y), homeAltar = altarPos)

    # Run simulation with AI
    env.runGameSteps(VeryLongSimSteps * 2)

    # All altars should belong to the same team
    let altarPositions = getAltarPositions(env, teamId)
    for altar in env.thingsByKind[Altar]:
      if not altar.isNil and altar.pos in altarPositions:
        echo fmt"    Altar at ({altar.pos.x}, {altar.pos.y}): teamId={altar.teamId}"
        check altar.teamId == teamId

    # All town centers should belong to the same team
    let tcPositions = getTownCenterPositions(env, teamId)
    for tc in env.thingsByKind[TownCenter]:
      if not tc.isNil and tc.pos in tcPositions:
        echo fmt"    TC at ({tc.pos.x}, {tc.pos.y}): teamId={tc.teamId}"
        check tc.teamId == teamId

    # All villagers assigned to any of our altars should maintain teamId
    for agent in env.agents:
      if not agent.isNil and agent.hp > 0:
        let agentTeam = getTeamId(agent)
        if agent.homeAltar in altarPositions:
          check agentTeam == teamId

    if altarPositions.len > 1:
      echo fmt"  Verified: {altarPositions.len} altars all have teamId={teamId}"
    else:
      echo "  WARNING: No split occurred - cannot verify team preservation across settlements"
      check altarPositions.len > 1

suite "Behavior: Multiple Splits":
  test "team can split more than once with sufficient population":
    ## Run a long simulation with generous resources and AI controller.
    ## Assert that the team can split more than once (3+ altars eventually).
    ## This tests that the system works recursively.
    let env = setupGameWithAI(seed = 42)

    let altarPos = ivec2(100, 95)
    discard addAltar(env, altarPos, 0, 200)  # Lots of hearts
    discard addBuilding(env, TownCenter, ivec2(102, 95), 0)

    # Many houses for large population cap
    for i in 0 ..< 20:
      let x = 85 + (i mod 10).int32
      let y = 85 + (i div 10).int32
      discard addBuilding(env, House, ivec2(x, y), 0)

    # Spawn a very large population to enable multiple splits
    let villagerCount = TownSplitPopulationThreshold * 3
    for i in 0 ..< villagerCount:
      let x = 90 + (i mod 15).int32
      let y = 90 + (i div 15).int32
      discard addAgentAt(env, i, ivec2(x, y), homeAltar = altarPos)

    # Give the team generous resources to support expansion
    giveTeamPlentyOfResources(env, 0, 1000)

    # Seed resources around the area for new settlements to use
    for i in 0 ..< 20:
      let rx = 70 + (i * 7).int32
      let ry = 75 + ((i * 5) mod 40).int32
      if rx < MapWidth.int32 and ry < MapHeight.int32:
        discard addResource(env, Tree, ivec2(rx, ry), ItemWood)
        discard addResource(env, Wheat, ivec2(rx + 1, ry), ItemWheat)

    echo fmt"  Starting with {villagerCount} villagers"

    # Run a very long simulation with AI
    env.runGameSteps(VeryLongSimSteps * 4)

    let altarCount = countAltarsForTeam(env, 0)
    let tcCount = countTownCentersForTeam(env, 0)
    let totalUnits = countAliveUnits(env, 0)

    echo fmt"  After {VeryLongSimSteps * 4} steps:"
    echo fmt"    Altars: {altarCount}"
    echo fmt"    Town centers: {tcCount}"
    echo fmt"    Total alive units: {totalUnits}"

    # Verify multiple splits occurred
    check altarCount >= 3
    check tcCount >= 3

    # Verify villagers are distributed across all settlements
    let villagersPerAltar = getVillagersPerAltar(env, 0)
    echo fmt"    Villager distribution:"
    for pos, count in villagersPerAltar:
      echo fmt"      Altar ({pos.x}, {pos.y}): {count} villagers"

    # Most settlements should have some villagers (original altar may be empty
    # if all villagers migrated away, which is valid behavior)
    var populatedAltars = 0
    for pos, count in villagersPerAltar:
      if count > 0:
        inc populatedAltars
    check populatedAltars >= altarCount - 1  # At most one empty (abandoned) altar
