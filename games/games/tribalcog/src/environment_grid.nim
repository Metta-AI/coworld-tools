import
  vmath,
  registry, terrain, types

export types

{.push inline.}

proc getThing*(env: Environment, pos: IVec2): Thing =
  ## Return the blocking thing at a position, or nil when it is invalid.
  if not isValidPos(pos):
    return nil
  env.grid[pos.x][pos.y]

proc getBackgroundThing*(env: Environment, pos: IVec2): Thing =
  ## Return the background thing at a position, or nil when it is invalid.
  if not isValidPos(pos):
    return nil
  env.backgroundGrid[pos.x][pos.y]

proc isEmpty*(env: Environment, pos: IVec2): bool =
  ## Return true when no blocking unit occupies the tile.
  isValidPos(pos) and isNil(env.grid[pos.x][pos.y])

proc hasDoor*(env: Environment, pos: IVec2): bool =
  ## Check whether a door occupies the position.
  let door = env.getBackgroundThing(pos)
  not isNil(door) and door.kind == Door

proc canAgentPassDoor*(env: Environment, agent: Thing, pos: IVec2): bool =
  ## Check whether an agent can pass through the door at the position.
  let door = env.getBackgroundThing(pos)
  isNil(door) or door.kind != Door or door.teamId == getTeamId(agent)

proc hasDockAt*(env: Environment, pos: IVec2): bool =
  ## Check whether a dock occupies the position.
  let background = env.getBackgroundThing(pos)
  not isNil(background) and background.kind == Dock

proc isWaterUnit*(agent: Thing): bool =
  ## Check whether an agent is a water-based unit.
  agent.unitClass in {
    UnitBoat,
    UnitTradeCog,
    UnitGalley,
    UnitFireShip,
    UnitFishingShip,
    UnitTransportShip,
    UnitDemoShip,
    UnitCannonGalleon
  }

proc isWaterBlockedForAgent*(env: Environment, agent: Thing, pos: IVec2): bool =
  ## Check whether a land unit cannot enter a water tile.
  env.terrain[pos.x][pos.y] == Water and
    not agent.isWaterUnit and
    not env.hasDockAt(pos)

{.pop.}

proc canTraverseElevation*(env: Environment, fromPos, toPos: IVec2): bool {.inline.} =
  ## Allow flat movement, ramp-assisted climbs, or cliff drops.
  if not isValidPos(fromPos) or not isValidPos(toPos):
    return false
  let dx = toPos.x - fromPos.x
  let dy = toPos.y - fromPos.y
  if abs(dx) + abs(dy) != 1:
    return false
  let elevFrom = env.elevation[fromPos.x][fromPos.y]
  let elevTo = env.elevation[toPos.x][toPos.y]
  if elevFrom == elevTo:
    return true
  if abs(elevFrom - elevTo) != 1:
    return false

  if elevFrom > elevTo:
    return true

  let terrainFrom = env.terrain[fromPos.x][fromPos.y]
  let terrainTo = env.terrain[toPos.x][toPos.y]
  terrainFrom == Road or terrainTo == Road or
    isRampTerrain(terrainFrom) or isRampTerrain(terrainTo)

proc willCauseCliffFallDamage*(
  env: Environment,
  fromPos,
  toPos: IVec2
): bool {.inline.} =
  ## Check whether moving between the positions would cause cliff fall damage.
  if not isValidPos(fromPos) or not isValidPos(toPos):
    return false
  let elevFrom = env.elevation[fromPos.x][fromPos.y]
  let elevTo = env.elevation[toPos.x][toPos.y]
  if elevFrom <= elevTo:
    return false

  let terrainFrom = env.terrain[fromPos.x][fromPos.y]
  let terrainTo = env.terrain[toPos.x][toPos.y]
  let hasRampOrRoad = terrainFrom == Road or terrainTo == Road or
    isRampTerrain(terrainFrom) or isRampTerrain(terrainTo)

  not hasRampOrRoad

proc isBuildableTerrain*(terrain: TerrainType): bool {.inline.} =
  ## Check whether the terrain allows building placement.
  terrain in BuildableTerrain

proc isSpawnable*(env: Environment, pos: IVec2): bool {.inline.} =
  ## Check whether a unit can spawn at the position.
  if not isValidPos(pos):
    return false
  if not env.isEmpty(pos):
    return false
  if not isNil(env.getBackgroundThing(pos)):
    return false
  not env.hasDoor(pos)

proc resetTileColor*(env: Environment, pos: IVec2) =
  ## Clear dynamic tint overlays for a tile.
  env.computedTintColors[pos.x][pos.y] = TileColor(
    r: 0,
    g: 0,
    b: 0,
    intensity: 0
  )
