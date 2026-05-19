## Parse a ThingKind from an item key name.
proc parseThingKey(key: ItemKey, kind: var ThingKind): bool =
  if not isThingKey(key):
    return false
  for candidate in ThingKind:
    if $candidate == key.name:
      kind = candidate
      return true
  false

## Reset pooled thing state before reuse.
proc resetThing(thing: Thing, kind: ThingKind) =
  thing.kind = kind
  thing.pos = ivec2(0, 0)
  thing.id = 0
  thing.layer = 0
  thing.cooldown = 0
  thing.frozen = 0
  thing.thingsIndex = 0
  thing.kindListIndex = 0
  thing.agentId = 0
  thing.orientation = Orientation(0)
  thing.inventory = emptyInventory()
  thing.barrelCapacity = 0
  thing.reward = 0.0'f32
  thing.hp = 0
  thing.maxHp = 0
  thing.attackDamage = 0
  thing.unitClass = UnitVillager
  thing.stance = StanceNoAttack
  thing.isIdle = false
  thing.embarkedUnitClass = UnitVillager
  thing.teamIdOverride = 0
  thing.homeAltar = ivec2(0, 0)
  thing.movementDebt = 0.0'f32
  thing.herdId = 0
  thing.packId = 0
  thing.isPackLeader = false
  thing.scatteredSteps = 0
  thing.packed = false
  thing.tradeHomeDock = ivec2(0, 0)
  thing.faith = 0
  thing.homeSpawner = ivec2(0, 0)
  thing.hasClaimedTerritory = false
  thing.turnsAlive = 0
  thing.teamId = 0
  thing.teamMask = NoTeamMask
  thing.lanternHealthy = false
  thing.garrisonedUnits = @[]
  thing.townBellActive = false
  thing.garrisonedRelics = 0
  thing.productionQueue = ProductionQueue()
  thing.rallyPoint = ivec2(0, 0)
  thing.rallyTarget = ivec2(0, 0)
  thing.wonderVictoryCountdown = 0
  thing.lastTintPos = ivec2(0, 0)

## Acquire a Thing from the pool or allocate a fresh one.
proc acquireThing*(env: Environment, kind: ThingKind): Thing =
  if kind in PoolableKinds and env.thingPool.free[kind].len > 0:
    result = env.thingPool.free[kind].pop()
    env.thingPool.stats.poolSize -= 1
    resetThing(result, kind)
  else:
    result = Thing(kind: kind)
  env.thingPool.stats.acquired += 1

## Return a Thing to the reuse pool.
proc releaseThing(env: Environment, thing: Thing) =
  env.thingPool.free[thing.kind].add(thing)
  env.thingPool.stats.released += 1
  env.thingPool.stats.poolSize += 1

## Remove a Thing from all environment indices and caches.
proc removeThing(env: Environment, thing: Thing) =
  # Remove the thing from the spatial index before clearing its tile.
  removeFromSpatialIndex(env, thing)
  if isValidPos(thing.pos):
    if thingBlocksMovement(thing.kind):
      env.grid[thing.pos.x][thing.pos.y] = nil
    else:
      env.backgroundGrid[thing.pos.x][thing.pos.y] = nil
    env.updateObservations(ThingAgentLayer, thing.pos, 0)
  let thingIdx = thing.thingsIndex
  if thingIdx >= 0 and
    thingIdx < env.things.len and
    env.things[thingIdx] == thing:
    let lastIdx = env.things.len - 1
    if thingIdx != lastIdx:
      let last = env.things[lastIdx]
      env.things[thingIdx] = last
      last.thingsIndex = thingIdx
    env.things.setLen(lastIdx)
  let kindIdx = thing.kindListIndex
  let hasKindEntry =
    kindIdx >= 0 and
    kindIdx < env.thingsByKind[thing.kind].len and
    env.thingsByKind[thing.kind][kindIdx] == thing
  if hasKindEntry:
    let lastKindIdx = env.thingsByKind[thing.kind].len - 1
    if kindIdx != lastKindIdx:
      let lastKindThing = env.thingsByKind[thing.kind][lastKindIdx]
      env.thingsByKind[thing.kind][kindIdx] = lastKindThing
      lastKindThing.kindListIndex = kindIdx
    env.thingsByKind[thing.kind].setLen(lastKindIdx)
  if thing.kind == Altar and env.altarColors.hasKey(thing.pos):
    env.altarColors.del(thing.pos)
  # Return poolable things to the reuse pool.
  if thing.kind in PoolableKinds:
    releaseThing(env, thing)

## Add a Thing to the environment and initialize its derived state.
proc add*(env: Environment, thing: Thing) =
  let isBlocking = thingBlocksMovement(thing.kind)
  if isValidPos(thing.pos) and not isBlocking:
    let existing = env.backgroundGrid[thing.pos.x][thing.pos.y]
    if not isNil(existing):
      if existing.kind in CliffKinds:
        # Cliffs always own their tile.
        return
      if thing.kind in CliffKinds:
        # Cliffs take precedence over other background overlays.
        removeThing(env, existing)
  let defaultMaxHp =
    case thing.kind
    of Wall: WallMaxHp
    of Door: DoorMaxHearts
    of Outpost: OutpostMaxHp
    of GuardTower: GuardTowerMaxHp
    of TownCenter: TownCenterMaxHp
    of Castle: CastleMaxHp
    of Monastery: MonasteryMaxHp
    of Wonder: WonderMaxHp
    else: 0
  if defaultMaxHp > 0:
    if thing.maxHp <= 0:
      thing.maxHp = defaultMaxHp
    if thing.hp <= 0:
      thing.hp = thing.maxHp
  # Treat completed and instant-placement buildings as constructed.
  if thing.maxHp <= 0 or thing.hp >= thing.maxHp:
    thing.constructed = true

  if thing.attackDamage <= 0:
    case thing.kind
    of GuardTower: thing.attackDamage = GuardTowerAttackDamage
    of Castle: thing.attackDamage = CastleAttackDamage
    of TownCenter: thing.attackDamage = TownCenterAttackDamage
    else: discard

  # Initialize the rally point sentinel for buildings.
  if isBuildingKind(thing.kind):
    thing.rallyPoint = ivec2(-1, -1)

  case thing.kind
  of Wonder:
    thing.wonderVictoryCountdown = WonderVictoryCountdown
  of Stone:
    if getInv(thing, ItemStone) <= 0:
      setInv(thing, ItemStone, MineDepositAmount)
  of Gold:
    if getInv(thing, ItemGold) <= 0:
      setInv(thing, ItemGold, MineDepositAmount)
  else:
    discard
  env.things.add(thing)
  thing.thingsIndex = env.things.len - 1
  env.thingsByKind[thing.kind].add(thing)
  thing.kindListIndex = env.thingsByKind[thing.kind].len - 1
  if thing.kind == Agent:
    thing.rallyTarget = ivec2(-1, -1)
    if thing.teamIdOverride == 0:
      thing.teamIdOverride = -1
    # Initialize the cached team mask from the agent identity.
    updateTeamMask(thing)
    if thing.embarkedUnitClass == UnitVillager and
      thing.unitClass != UnitVillager:
        thing.embarkedUnitClass = thing.unitClass
    env.agents.add(thing)
    env.stats.add(Stats())
    # Track special aura units in dedicated lists.
    if thing.unitClass in TankAuraUnits:
      env.tankUnits.add(thing)
    elif thing.unitClass == UnitMonk:
      env.monkUnits.add(thing)
    # Cache villagers per team for town bell garrisoning.
    if thing.unitClass == UnitVillager:
      let teamId = getTeamId(thing)
      if teamId >= 0 and teamId < MapRoomObjectsTeams:
        env.teamVillagers[teamId].add(thing)
  # Update the cached team mask for non-agent things.
  if thing.kind != Agent:
    updateTeamMask(thing)
  if isValidPos(thing.pos):
    if isBlocking:
      env.grid[thing.pos.x][thing.pos.y] = thing
    else:
      env.backgroundGrid[thing.pos.x][thing.pos.y] = thing
    env.updateObservations(ThingAgentLayer, thing.pos, 0)
    # Add the thing to the spatial index.
    addToSpatialIndex(env, thing)
