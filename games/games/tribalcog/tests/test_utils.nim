## Shared test utility procedures.
## These helpers build minimal environments and scripted test fixtures.

import
  std/[tables],
  agent_control,
  common,
  environment,
  items,
  terrain,
  types

proc decodeAction*(action: uint16): tuple[verb: int, arg: int] =
  ## Decodes an action into its verb and argument.
  (
    action.int div ActionArgumentCount,
    action.int mod ActionArgumentCount,
  )

proc dirIndex*(fromPos, toPos: IVec2): int =
  ## Returns the direction index from one position to another.
  let
    dx = toPos.x - fromPos.x
    dy = toPos.y - fromPos.y
    sx =
      if dx > 0:
        1'i32
      elif dx < 0:
        -1'i32
      else:
        0'i32
    sy =
      if dy > 0:
        1'i32
      elif dy < 0:
        -1'i32
      else:
        0'i32
  if sx == 0'i32 and sy == -1'i32:
    return 0
  if sx == 0'i32 and sy == 1'i32:
    return 1
  if sx == -1'i32 and sy == 0'i32:
    return 2
  if sx == 1'i32 and sy == 0'i32:
    return 3
  if sx == -1'i32 and sy == -1'i32:
    return 4
  if sx == 1'i32 and sy == -1'i32:
    return 5
  if sx == -1'i32 and sy == 1'i32:
    return 6
  if sx == 1'i32 and sy == 1'i32:
    return 7
  0

proc placeholderAgent(agentId: int): Thing =
  ## Returns an inactive agent placeholder for unused slots.
  Thing(
    kind: Agent,
    pos: ivec2(-1, -1),
    agentId: agentId,
    orientation: N,
    inventory: emptyInventory(),
    hp: 0,
    maxHp: AgentMaxHp,
    attackDamage: 1,
    unitClass: UnitVillager,
    stance: StanceNoAttack,
    homeAltar: ivec2(-1, -1),
    rallyTarget: ivec2(-1, -1),
  )

proc ensureAgentSlots(env: Environment) =
  ## Fills the environment with inactive placeholders up to MapAgents.
  while env.agents.len < MapAgents:
    let
      nextId = env.agents.len
      agent = placeholderAgent(nextId)
    env.add(agent)
    env.terminated[nextId] = 1.0

proc initActions(): array[MapAgents, uint16] =
  ## Returns a zeroed action array for one environment step.
  default(array[MapAgents, uint16])

proc makeEmptyEnv*(): Environment =
  ## Creates an empty environment with test-friendly defaults.
  result = Environment(config: defaultEnvironmentConfig())
  result.currentStep = 0
  result.shouldReset = false
  result.observationsInitialized = false
  result.things.setLen(0)
  result.agents.setLen(0)
  result.stats.setLen(0)
  result.thingsByKind = default(array[ThingKind, seq[Thing]])
  result.tankUnits.setLen(0)
  result.monkUnits.setLen(0)

  for i in 0 ..< MapAgents:
    result.agentOrder[i] = i

  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      result.grid[x][y] = nil
      result.backgroundGrid[x][y] = nil
      result.terrain[x][y] = TerrainEmpty
      result.biomes[x][y] = BiomeBaseType
      result.elevation[x][y] = 0
      result.baseTintColors[x][y] = BaseTileColorDefault
      result.computedTintColors[x][y] =
        TileColor(r: 0, g: 0, b: 0, intensity: 0)
      result.tintMods[x][y] = TintModification(r: 0, g: 0, b: 0)
      result.tintStrength[x][y] = 0
      result.tumorTintMods[x][y] = TintModification(r: 0, g: 0, b: 0)
      result.tumorStrength[x][y] = 0

  result.teamStockpiles =
    default(array[MapRoomObjectsTeams, TeamStockpile])

  for teamId in 0 ..< MapRoomObjectsTeams:
    result.teamCivBonuses[teamId] = defaultCivBonus()

  # Use live market defaults in tests unless a case overrides them.
  result.initMarketPrices()
  result.victoryWinner = -1
  result.victoryWinners = NoTeamMask

  for teamId in 0 ..< MapRoomObjectsTeams:
    result.victoryStates[teamId].wonderBuiltStep = -1
    result.victoryStates[teamId].relicHoldStartStep = -1
    result.victoryStates[teamId].kingAgentId = -1

  for teamId in 0 ..< MapRoomObjectsTeams:
    result.teamAlliances[teamId] = TeamMasks[teamId]

  result.actionTintPositions.setLen(0)
  result.activeTiles.positions.setLen(0)
  result.activeTiles.flags =
    default(array[MapWidth, array[MapHeight, bool]])
  result.tumorActiveTiles.positions.setLen(0)
  result.tumorActiveTiles.flags =
    default(array[MapWidth, array[MapHeight, bool]])
  result.altarColors = initTable[IVec2, Color]()
  result.teamColors = newSeq[Color](MapRoomObjectsTeams)
  result.agentColors = newSeq[Color](MapAgents)

proc addAgentAt*(
  env: Environment,
  agentId: int,
  pos: IVec2,
  homeAltar: IVec2 = ivec2(-1, -1),
  unitClass: AgentUnitClass = UnitVillager,
  orientation: Orientation = N,
  stance: AgentStance = StanceNoAttack
): Thing =
  ## Adds an agent at the requested slot and position.
  while env.agents.len <= agentId:
    let
      nextId = env.agents.len
      isTarget = nextId == agentId
      agent = Thing(
        kind: Agent,
        pos: (if isTarget: pos else: ivec2(-1, -1)),
        agentId: nextId,
        orientation: (if isTarget: orientation else: N),
        inventory: emptyInventory(),
        hp: (if isTarget: AgentMaxHp else: 0),
        maxHp: AgentMaxHp,
        attackDamage: 1,
        unitClass: (if isTarget: unitClass else: UnitVillager),
        stance: (if isTarget: stance else: StanceNoAttack),
        homeAltar: (if isTarget: homeAltar else: ivec2(-1, -1)),
        faith: (if isTarget and unitClass == UnitMonk: MonkMaxFaith else: 0),
        rallyTarget: ivec2(-1, -1),
      )
    env.add(agent)
    env.terminated[nextId] = (if isTarget: 0.0 else: 1.0)
    if isTarget:
      result = agent

proc addBuilding*(
  env: Environment,
  kind: ThingKind,
  pos: IVec2,
  teamId: int
): Thing =
  ## Adds a completed building for a team.
  let thing = Thing(kind: kind, pos: pos, teamId: teamId)
  thing.inventory = emptyInventory()
  thing.rallyPoint = ivec2(-1, -1)
  thing.constructed = true
  let capacity = buildingBarrelCapacity(kind)
  if capacity > 0:
    thing.barrelCapacity = capacity
  env.add(thing)
  thing

proc addBuildings*(
  env: Environment,
  teamId: int,
  start: IVec2,
  kinds: openArray[ThingKind]
) =
  ## Adds a line of buildings starting at the requested position.
  var dx = 0
  for kind in kinds:
    discard addBuilding(env, kind, start + ivec2(dx.int32, 0), teamId)
    inc dx

proc addAltar*(env: Environment, pos: IVec2, teamId: int, hearts: int): Thing =
  ## Adds an altar with the requested heart count.
  let altar = Thing(kind: Altar, pos: pos, teamId: teamId)
  altar.inventory = emptyInventory()
  altar.hearts = hearts
  env.add(altar)
  altar

proc addResource*(
  env: Environment,
  kind: ThingKind,
  pos: IVec2,
  key: ItemKey,
  amount: int = ResourceNodeInitial
): Thing =
  ## Adds a resource node and optionally seeds its inventory.
  let node = Thing(kind: kind, pos: pos)
  node.inventory = emptyInventory()
  if key != ItemNone and amount > 0:
    setInv(node, key, amount)
  env.add(node)
  node

proc setStockpile*(
  env: Environment,
  teamId: int,
  res: StockpileResource,
  count: int
) =
  ## Sets one team stockpile bucket to the requested count.
  env.teamStockpiles[teamId].counts[res] = count

proc stepNoop*(env: Environment) =
  ## Steps the environment with all agents taking the noop action.
  ensureAgentSlots(env)
  var actions = initActions()
  env.step(addr actions)
  env.ensureObservations()

proc stepAction*(env: Environment, agentId: int, verb: uint16, argument: int) =
  ## Steps the environment with one explicit agent action.
  ensureAgentSlots(env)
  var actions = initActions()
  actions[agentId] = encodeAction(verb, argument.uint16)
  env.step(addr actions)
  env.ensureObservations()

proc newTestController*(seed: int): Controller =
  ## Creates a controller with Brutal difficulty for deterministic tests.
  result = newController(seed)
  for teamId in 0 ..< MapRoomObjectsTeams:
    result.setDifficulty(teamId, DiffBrutal)
