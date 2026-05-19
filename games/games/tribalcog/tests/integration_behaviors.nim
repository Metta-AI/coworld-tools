## Integration behavioral tests: run 200-step games with fixed seeds
## and verify emergent outcomes (resource gathering, building, combat, population).
## Run with: nim r --path:src tests/integration_behaviors.nim

import std/strformat
import test_common
import items

const Steps = 200

type
  GameSummary = object
    seed: int
    stepsCompleted: int
    # Resources
    totalStartResources: int
    totalEndResources: int
    peakResources: int
    agentsCarryingResources: int
    # Buildings
    startBuildingCount: int
    endBuildingCount: int
    # Combat
    totalDeaths: int
    # Population
    startAlive: int
    endAlive: int

proc countAliveAgents(env: Environment): int =
  for i in 0 ..< env.agents.len:
    if env.terminated[i] == 0.0 and not env.agents[i].isNil and env.agents[i].hp > 0:
      inc result

proc countBuildings(env: Environment): int =
  ## Count player-placed buildings (not resources/terrain/agents)
  const buildingKinds = {Wall, Door, Outpost, GuardTower, Barrel, Altar, TownCenter,
    House, ClayOven, WeavingLoom, Mill, Granary, LumberCamp, Quarry, MiningCamp,
    Lantern, Barracks, ArcheryRange, Stable, SiegeWorkshop, MangonelWorkshop,
    TrebuchetWorkshop, Blacksmith, Market, Dock, Monastery, Temple, University,
    Castle, Wonder}
  for kind in buildingKinds:
    result += env.thingsByKind[kind].len

proc runGame(seed: int): GameSummary =
  initGlobalController(BuiltinAI, seed = seed)
  var env = newEnvironment()

  result.seed = seed
  result.startAlive = countAliveAgents(env)
  result.totalStartResources = getTotalStockpileAllTeams(env)
  result.peakResources = result.totalStartResources
  result.startBuildingCount = countBuildings(env)

  for step in 0 ..< Steps:
    var actions = getActions(env)
    env.step(addr actions)
    let cur = getTotalStockpileAllTeams(env)
    if cur > result.peakResources:
      result.peakResources = cur

  result.stepsCompleted = env.currentStep
  result.endAlive = countAliveAgents(env)
  result.totalEndResources = getTotalStockpileAllTeams(env)
  result.endBuildingCount = countBuildings(env)
  for i, agent in env.agents:
    if env.terminated[i] == 1.0:
      inc result.totalDeaths
    elif not agent.isNil and
        (agent.inventory.items[ikWood] > 0 or agent.inventory.items[ikStone] > 0 or
         agent.inventory.items[ikGold] > 0 or agent.inventory.items[ikWheat] > 0 or
         agent.inventory.items[ikFish] > 0 or agent.inventory.items[ikMeat] > 0):
      inc result.agentsCarryingResources

proc main() =
  const seeds = [42, 123, 777]
  var summaries: seq[GameSummary]

  echo "=== Integration Behavioral Tests: 200-step games ==="
  echo ""

  for seed in seeds:
    echo &"Running game with seed {seed}..."
    let s = runGame(seed)
    echo &"  Seed {s.seed}: {s.stepsCompleted} steps completed"
    echo &"    Resources: {s.totalStartResources} -> {s.totalEndResources} (peak: {s.peakResources}, agents carrying: {s.agentsCarryingResources})"
    echo &"    Buildings: {s.startBuildingCount} -> {s.endBuildingCount} (delta: {s.endBuildingCount - s.startBuildingCount})"
    echo &"    Population: {s.startAlive} alive -> {s.endAlive} alive, {s.totalDeaths} total deaths"
    summaries.add(s)
    echo ""

  # Aggregate checks
  echo "=== Verifying behavioral outcomes ==="

  # 1. All games completed 200 steps
  var allCompleted = true
  for s in summaries:
    if s.stepsCompleted < Steps:
      echo &"  FAIL: Seed {s.seed} only completed {s.stepsCompleted}/{Steps} steps"
      allCompleted = false
  if allCompleted:
    echo "  PASS: All games completed 200 steps"
  else:
    quit(1)

  # 2. Agents gather resources: peak stockpile exceeds start, or agents carry resources,
  #    or buildings were built (which requires gathered resources to afford)
  var anyGathered = false
  for s in summaries:
    if s.peakResources > s.totalStartResources or
       s.agentsCarryingResources > 0 or
       s.endBuildingCount > s.startBuildingCount:
      anyGathered = true
      break
  if anyGathered:
    echo "  PASS: Agents gather resources (peak stockpile, carrying, or buildings confirm gathering)"
  else:
    echo "  FAIL: No game showed resource gathering"
    quit(1)

  # 3. Agents build buildings (building count increases in at least one game)
  var anyBuilt = false
  for s in summaries:
    if s.endBuildingCount > s.startBuildingCount:
      anyBuilt = true
      break
  if anyBuilt:
    echo "  PASS: Agents build buildings (at least one game has more buildings)"
  else:
    echo "  FAIL: No game showed building construction"
    quit(1)

  # 4. Combat occurs (deaths happen in at least one game)
  var anyCombat = false
  for s in summaries:
    if s.totalDeaths > s.startAlive:  # More deaths than initial pop means some died
      anyCombat = true
      break
  # Fallback: even if deaths == startAlive (all initial could die from env),
  # check if population changed
  if not anyCombat:
    for s in summaries:
      if s.totalDeaths > 0:
        anyCombat = true
        break
  if anyCombat:
    echo "  PASS: Combat/damage events occur (deaths observed)"
  else:
    echo "  FAIL: No combat or deaths observed in any game"
    quit(1)

  # 5. Population changes over time
  var anyPopChange = false
  for s in summaries:
    if s.endAlive != s.startAlive:
      anyPopChange = true
      break
  if anyPopChange:
    echo "  PASS: Population changes over time"
  else:
    echo "  FAIL: Population unchanged in all games"
    quit(1)

  echo ""
  echo "=== All behavioral integration tests passed ==="

main()
