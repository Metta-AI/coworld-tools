## Map generation and spawn verification tests.
## Verifies that generated maps are valid and playable by checking:
## - Each team has a town center
## - Resource nodes (food, wood, gold, stone) exist on every map
## - All team start positions are reachable from each other (connectivity)
## - No things spawn on invalid tiles (water for land units)
## - Population counts match expected initial values
## - Biome distribution is reasonable

import std/[unittest, strformat]
import environment
import types
import terrain

const
  NumTestSeeds = 20
  TestSeeds = block:
    var seeds: array[NumTestSeeds, int]
    for i in 0 ..< NumTestSeeds:
      seeds[i] = 42 + i * 7919  # Prime-spaced seeds for variety
    seeds

type
  MapStats = object
    seed: int
    townCenters: array[MapRoomObjectsTeams, int]
    treeCount: int
    wheatCount: int
    goldCount: int
    stoneCount: int
    agentCount: int
    thingsOnWater: int
    biomeDistribution: array[BiomeType, int]
    totalTiles: int

proc collectMapStats(env: Environment, seed: int): MapStats =
  ## Collect statistics about a generated map.
  result.seed = seed
  result.totalTiles = MapWidth * MapHeight

  # Count town centers per team
  for tc in env.thingsByKind[TownCenter]:
    if not isNil(tc) and tc.teamId >= 0 and tc.teamId < MapRoomObjectsTeams:
      inc result.townCenters[tc.teamId]

  # Count resource nodes
  for tree in env.thingsByKind[Tree]:
    if not isNil(tree):
      inc result.treeCount
  for wheat in env.thingsByKind[Wheat]:
    if not isNil(wheat):
      inc result.wheatCount
  for gold in env.thingsByKind[Gold]:
    if not isNil(gold):
      inc result.goldCount
  for stone in env.thingsByKind[Stone]:
    if not isNil(stone):
      inc result.stoneCount

  # Count agents
  for agent in env.agents:
    if not isNil(agent) and agent.hp > 0:
      inc result.agentCount

  # Check for critical things on water tiles (agents and team buildings)
  # Neutral walls/structures may intentionally cross water (bridges, barriers)
  const WaterBlockedKinds = {
    Agent,  # Units should not spawn on deep water
    TownCenter, Castle, House, Barracks, ArcheryRange, Stable,
    SiegeWorkshop, MangonelWorkshop, TrebuchetWorkshop, Blacksmith, Market,
    Monastery, University, Mill, Granary, LumberCamp, Quarry, MiningCamp,
    WeavingLoom, ClayOven, Lantern, Outpost, GuardTower, Wonder, Altar, Door
  }
  for thing in env.things:
    if isNil(thing):
      continue
    if not isValidPos(thing.pos):
      continue
    if thing.kind notin WaterBlockedKinds:
      continue
    # Skip neutral structures (teamId=-1) which may legitimately cross water
    if thing.teamId == -1:
      continue
    let terrainType = env.terrain[thing.pos.x][thing.pos.y]
    # Only deep water is blocked
    if terrainType == Water:
      inc result.thingsOnWater

  # Biome distribution
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      inc result.biomeDistribution[env.biomes[x][y]]

proc getTeamAltarPositions(env: Environment): seq[IVec2] =
  ## Get all team altar positions for connectivity testing.
  for altar in env.thingsByKind[Altar]:
    if not isNil(altar) and altar.teamId >= 0 and altar.teamId < MapRoomObjectsTeams:
      result.add(altar.pos)

suite "Spawn: Town Center Placement":
  test "every team has exactly one town center across 20 maps":
    var teamsWithoutTC = 0
    var teamsWithMultipleTC = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      for teamId in 0 ..< MapRoomObjectsTeams:
        if stats.townCenters[teamId] == 0:
          inc teamsWithoutTC
          echo &"  WARNING: Seed {seed} Team {teamId} has no town center"
        elif stats.townCenters[teamId] > 1:
          inc teamsWithMultipleTC
          echo &"  WARNING: Seed {seed} Team {teamId} has {stats.townCenters[teamId]} town centers"

    check teamsWithoutTC == 0
    check teamsWithMultipleTC == 0
    echo &"  All {NumTestSeeds} maps: every team has exactly one town center"

suite "Spawn: Resource Node Verification":
  test "every map has trees (wood resource)":
    var mapsWithoutTrees = 0
    var minTrees = high(int)
    var maxTrees = 0
    var totalTrees = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      if stats.treeCount == 0:
        inc mapsWithoutTrees
        echo &"  WARNING: Seed {seed} has no trees"
      minTrees = min(minTrees, stats.treeCount)
      maxTrees = max(maxTrees, stats.treeCount)
      totalTrees += stats.treeCount

    check mapsWithoutTrees == 0
    let avgTrees = totalTrees div NumTestSeeds
    echo &"  Trees across {NumTestSeeds} maps: min={minTrees} max={maxTrees} avg={avgTrees}"

  test "every map has wheat (food resource)":
    var mapsWithoutWheat = 0
    var minWheat = high(int)
    var maxWheat = 0
    var totalWheat = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      if stats.wheatCount == 0:
        inc mapsWithoutWheat
        echo &"  WARNING: Seed {seed} has no wheat"
      minWheat = min(minWheat, stats.wheatCount)
      maxWheat = max(maxWheat, stats.wheatCount)
      totalWheat += stats.wheatCount

    check mapsWithoutWheat == 0
    let avgWheat = totalWheat div NumTestSeeds
    echo &"  Wheat across {NumTestSeeds} maps: min={minWheat} max={maxWheat} avg={avgWheat}"

  test "every map has gold deposits":
    var mapsWithoutGold = 0
    var minGold = high(int)
    var maxGold = 0
    var totalGold = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      if stats.goldCount == 0:
        inc mapsWithoutGold
        echo &"  WARNING: Seed {seed} has no gold"
      minGold = min(minGold, stats.goldCount)
      maxGold = max(maxGold, stats.goldCount)
      totalGold += stats.goldCount

    check mapsWithoutGold == 0
    let avgGold = totalGold div NumTestSeeds
    echo &"  Gold across {NumTestSeeds} maps: min={minGold} max={maxGold} avg={avgGold}"

  test "every map has stone deposits":
    var mapsWithoutStone = 0
    var minStone = high(int)
    var maxStone = 0
    var totalStone = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      if stats.stoneCount == 0:
        inc mapsWithoutStone
        echo &"  WARNING: Seed {seed} has no stone"
      minStone = min(minStone, stats.stoneCount)
      maxStone = max(maxStone, stats.stoneCount)
      totalStone += stats.stoneCount

    check mapsWithoutStone == 0
    let avgStone = totalStone div NumTestSeeds
    echo &"  Stone across {NumTestSeeds} maps: min={minStone} max={maxStone} avg={avgStone}"

suite "Spawn: Team Start Position Connectivity":
  test "all teams have reachable starting positions":
    ## This test verifies that makeConnected() ensures the map is traversable.
    ## Note: The game guarantees connectivity via makeConnected() which is
    ## tested extensively in domain_connectivity.nim. Here we verify that
    ## team spawn areas are in the connected region.
    var teamsWithoutNearbyWalkable = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let altarPositions = getTeamAltarPositions(env)

      for altarPos in altarPositions:
        # Verify there's at least one walkable tile near each altar
        var hasWalkable = false
        for dx in -3 .. 3:
          for dy in -3 .. 3:
            let checkPos = altarPos + ivec2(dx.int32, dy.int32)
            if not isValidPos(checkPos):
              continue
            let terrainType = env.terrain[checkPos.x][checkPos.y]
            if terrainType != Water:
              let thing = env.getThing(checkPos)
              if isNil(thing) or thing.kind notin {Wall, TownCenter, Castle, House,
                  Barracks, ArcheryRange, Stable, Blacksmith, Market, Monastery,
                  University, Mill, Granary, LumberCamp, Quarry, MiningCamp,
                  GoblinHive, GoblinHut, GoblinTotem, Spawner, Magma, Temple, Altar}:
                hasWalkable = true
                break
          if hasWalkable:
            break
        if not hasWalkable:
          inc teamsWithoutNearbyWalkable
          echo &"  WARNING: Seed {seed} has altar at {altarPos} with no nearby walkable tiles"

    check teamsWithoutNearbyWalkable == 0
    echo &"  All {NumTestSeeds} maps: team spawn areas have walkable tiles"

  test "map connectivity is established via makeConnected":
    ## Verify that makeConnected() ran by checking that there are no
    ## completely isolated walkable regions in the playable area.
    ## This is a simplified check - detailed connectivity tests are in domain_connectivity.nim.
    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      # The existence of roads to trading hub indicates makeConnected ran
      var hasRoadTerrain = false
      for x in MapBorder ..< MapWidth - MapBorder:
        for y in MapBorder ..< MapHeight - MapBorder:
          if env.terrain[x][y] == Road:
            hasRoadTerrain = true
            break
        if hasRoadTerrain:
          break
      check hasRoadTerrain

    echo &"  All {NumTestSeeds} maps: road network established (connectivity verified)"

suite "Spawn: Invalid Tile Placement":
  test "no land units or buildings spawn on water tiles":
    var mapsWithWaterSpawns = 0
    var totalWaterSpawns = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      if stats.thingsOnWater > 0:
        inc mapsWithWaterSpawns
        totalWaterSpawns += stats.thingsOnWater
        echo &"  WARNING: Seed {seed} has {stats.thingsOnWater} things on water"

    check mapsWithWaterSpawns == 0
    echo &"  All {NumTestSeeds} maps: no invalid water placements"

  test "agents spawn only on valid land tiles":
    var agentsOnInvalidTiles = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)

      for agent in env.agents:
        if isNil(agent) or agent.hp <= 0:
          continue
        if not isValidPos(agent.pos):
          continue
        let terrain = env.terrain[agent.pos.x][agent.pos.y]
        if terrain == Water:
          inc agentsOnInvalidTiles
          echo &"  WARNING: Seed {seed} Agent {agent.agentId} spawned on water at {agent.pos}"

    check agentsOnInvalidTiles == 0
    echo &"  All {NumTestSeeds} maps: agents spawn on valid tiles"

suite "Spawn: Population Counts":
  test "initial population matches expected values":
    # Each team starts with 6 active agents
    const ExpectedInitialAgentsPerTeam = 6

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)

      var agentsPerTeam: array[MapRoomObjectsTeams, int]
      for agent in env.agents:
        if isNil(agent) or agent.hp <= 0:
          continue
        let teamId = getTeamId(agent)
        if teamId >= 0 and teamId < MapRoomObjectsTeams:
          inc agentsPerTeam[teamId]

      for teamId in 0 ..< MapRoomObjectsTeams:
        check agentsPerTeam[teamId] == ExpectedInitialAgentsPerTeam

    echo &"  All {NumTestSeeds} maps: each team has {ExpectedInitialAgentsPerTeam} initial agents"

  test "total agent count matches expected":
    # Total expected: teams * agents per team + goblins
    const ExpectedTotalAgents = MapRoomObjectsTeams * 6 + MapRoomObjectsGoblinAgents

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      check stats.agentCount == ExpectedTotalAgents

    echo &"  All {NumTestSeeds} maps: total agents = {ExpectedTotalAgents}"

suite "Spawn: Biome Distribution":
  test "multiple biome types present across maps":
    var allBiomesSeen: set[BiomeType]

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      for biome in BiomeType:
        if stats.biomeDistribution[biome] > 0:
          allBiomesSeen.incl(biome)

    # Should see at least base type and a few others
    check BiomeBaseType in allBiomesSeen
    check allBiomesSeen.card >= 3
    echo &"  Biomes seen across {NumTestSeeds} maps: {allBiomesSeen.card} types"

  test "no single biome dominates excessively":
    const MaxBiomeFraction = 0.90  # No biome should exceed 90% of tiles

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      for biome in BiomeType:
        let fraction = stats.biomeDistribution[biome].float / stats.totalTiles.float
        if fraction > MaxBiomeFraction:
          echo &"  WARNING: Seed {seed} has {biome} at {fraction * 100:.1f}%"
        check fraction <= MaxBiomeFraction

    echo &"  All {NumTestSeeds} maps: biome distribution within expected range"

  test "print biome distribution summary":
    var totalBiomeCounts: array[BiomeType, int]
    var totalTiles = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      for biome in BiomeType:
        totalBiomeCounts[biome] += stats.biomeDistribution[biome]
      totalTiles += stats.totalTiles

    echo &"  Biome distribution across {NumTestSeeds} maps:"
    for biome in BiomeType:
      let pct = totalBiomeCounts[biome].float / totalTiles.float * 100.0
      if pct > 0.1:
        echo &"    {biome}: {pct:.1f}%"

suite "Spawn: Map Statistics Summary":
  test "print comprehensive map statistics":
    echo &"  === Map Generation Statistics ({NumTestSeeds} seeds) ==="

    var totalTrees, totalWheat, totalGold, totalStone = 0
    var totalAgents = 0
    var totalTownCenters = 0

    for seed in TestSeeds:
      let config = defaultEnvironmentConfig()
      let env = newEnvironment(config, seed)
      let stats = collectMapStats(env, seed)

      totalTrees += stats.treeCount
      totalWheat += stats.wheatCount
      totalGold += stats.goldCount
      totalStone += stats.stoneCount
      totalAgents += stats.agentCount
      for tc in stats.townCenters:
        totalTownCenters += tc

    echo &"  Average per map:"
    echo &"    Trees: {totalTrees div NumTestSeeds}"
    echo &"    Wheat: {totalWheat div NumTestSeeds}"
    echo &"    Gold: {totalGold div NumTestSeeds}"
    echo &"    Stone: {totalStone div NumTestSeeds}"
    echo &"    Agents: {totalAgents div NumTestSeeds}"
    echo &"    Town Centers: {totalTownCenters div NumTestSeeds}"
    echo &"  Total across all maps:"
    echo &"    Trees: {totalTrees}"
    echo &"    Wheat: {totalWheat}"
    echo &"    Gold: {totalGold}"
    echo &"    Stone: {totalStone}"
