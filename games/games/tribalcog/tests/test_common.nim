## Shared behavior-test helpers.
## This module re-exports the common test environment setup.

import
  std/[strformat],
  agent_control,
  environment,
  items,
  terrain,
  test_utils,
  types

export test_utils, environment, agent_control, types, items, terrain

const
  BuildingKinds* = {
    Altar,
    TownCenter,
    House,
    Barracks,
    ArcheryRange,
    Stable,
    Blacksmith,
    Market,
    Monastery,
    University,
    Castle,
    Wonder,
    SiegeWorkshop,
    MangonelWorkshop,
    TrebuchetWorkshop,
    Dock,
    Outpost,
    GuardTower,
    Wall,
    Door,
    Mill,
    Granary,
    LumberCamp,
    Quarry,
    MiningCamp,
    WeavingLoom,
    ClayOven,
    Lantern,
    Temple,
  }
  DefaultTestSeed* = 42
  ShortSimSteps* = 100
  MediumSimSteps* = 200
  LongSimSteps* = 300
  VeryLongSimSteps* = 500

proc runGameSteps*(env: Environment, steps: int) =
  ## Runs the game for the requested number of AI-driven steps.
  for _ in 0 ..< steps:
    let actions = getActions(env)
    env.step(addr actions)

proc initBrutalAI*(seed: int = DefaultTestSeed) =
  ## Initializes the global AI controller in deterministic Brutal mode.
  initGlobalController(BuiltinAI, seed = seed)
  for teamId in 0 ..< MapRoomObjectsTeams:
    globalController.aiController.setDifficulty(teamId, DiffBrutal)

proc setupGameWithAI*(seed: int = DefaultTestSeed): Environment =
  ## Creates a new environment and initializes the global AI controller.
  result = newEnvironment()
  initBrutalAI(seed)

proc setupGameWithAI*(
  config: EnvironmentConfig,
  seed: int = DefaultTestSeed
): Environment =
  ## Creates a configured environment and initializes the global AI controller.
  result = newEnvironment(config, seed)
  # Mix the controller seed so it does not mirror environment randomness.
  initBrutalAI(seed xor 0x12345678)

proc printStockpileSummary*(env: Environment, teamId: int, label: string) =
  ## Prints a formatted snapshot of one team's stockpile.
  let
    food = env.stockpileCount(teamId, ResourceFood)
    wood = env.stockpileCount(teamId, ResourceWood)
    gold = env.stockpileCount(teamId, ResourceGold)
    stone = env.stockpileCount(teamId, ResourceStone)
  echo fmt"  [{label}] Team {teamId}: food={food} wood={wood} gold={gold} stone={stone}"

proc getTotalStockpile*(env: Environment, teamId: int): int =
  ## Returns the total stockpiled resources for one team.
  env.stockpileCount(teamId, ResourceFood) +
    env.stockpileCount(teamId, ResourceWood) +
    env.stockpileCount(teamId, ResourceGold) +
    env.stockpileCount(teamId, ResourceStone)

proc getTotalStockpileAllTeams*(env: Environment): int =
  ## Returns the total stockpiled resources across all teams.
  for teamId in 0 ..< MapRoomObjectsTeams:
    result += getTotalStockpile(env, teamId)

proc setTeamResources*(
  env: Environment,
  teamId: int,
  food: int = 0,
  wood: int = 0,
  gold: int = 0,
  stone: int = 0
) =
  ## Sets all stockpile resources for one team.
  setStockpile(env, teamId, ResourceFood, food)
  setStockpile(env, teamId, ResourceWood, wood)
  setStockpile(env, teamId, ResourceGold, gold)
  setStockpile(env, teamId, ResourceStone, stone)

proc setAllTeamsResources*(
  env: Environment,
  food: int = 0,
  wood: int = 0,
  gold: int = 0,
  stone: int = 0
) =
  ## Sets the same stockpile resources for every team.
  for teamId in 0 ..< MapRoomObjectsTeams:
    setTeamResources(env, teamId, food, wood, gold, stone)

proc giveTeamPlentyOfResources*(
  env: Environment,
  teamId: int,
  amount: int = 500
) =
  ## Gives one team a generous amount of each resource.
  setTeamResources(env, teamId, amount, amount, amount, amount)

proc giveAllTeamsPlentyOfResources*(env: Environment, amount: int = 500) =
  ## Gives every team a generous amount of each resource.
  setAllTeamsResources(env, amount, amount, amount, amount)

proc countRolesByTeam*(teamId: int): tuple[gatherers, builders, fighters: int] =
  ## Counts initialized agents by role for one team.
  let
    controller = globalController.aiController
    startIdx = teamId * MapAgentsPerTeam
    endIdx = min(startIdx + MapAgentsPerTeam, MapAgents)
  for agentId in startIdx ..< endIdx:
    if controller.isAgentInitialized(agentId):
      let role = controller.getAgentRole(agentId)
      case role
      of Gatherer:
        inc result.gatherers
      of Builder:
        inc result.builders
      of Fighter:
        inc result.fighters
      of Scripted:
        discard

proc countAliveUnits*(env: Environment, teamId: int): int =
  ## Counts currently alive units for one team.
  for agent in env.agents:
    if getTeamId(agent) == teamId and isAgentAlive(env, agent):
      inc result

proc countDeadUnits*(env: Environment, teamId: int): int =
  ## Counts units that have died for one team.
  let
    startIdx = teamId * MapAgentsPerTeam
    endIdx = min(startIdx + MapAgentsPerTeam, env.agents.len)
  for i in startIdx ..< endIdx:
    let agent = env.agents[i]
    if not agent.isNil and env.terminated[i] != 0.0 and agent.hp <= 0:
      inc result

proc countBuildings*(env: Environment, teamId: int): int =
  ## Counts standing buildings owned by one team.
  for kind in BuildingKinds:
    for thing in env.thingsByKind[kind]:
      if not thing.isNil and thing.teamId == teamId and thing.hp > 0:
        inc result

proc countAllBuildings*(env: Environment): int =
  ## Counts all standing buildings across teams.
  for kind in BuildingKinds:
    for thing in env.thingsByKind[kind]:
      if not thing.isNil and thing.hp > 0:
        inc result

proc damageBuilding*(thing: Thing, damageAmount: int) =
  ## Applies nonlethal damage to a building.
  if thing.maxHp > 0:
    thing.hp = max(1, thing.hp - damageAmount)
