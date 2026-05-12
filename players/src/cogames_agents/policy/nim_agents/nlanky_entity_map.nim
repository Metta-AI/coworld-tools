import std/[tables, sets, options, strutils]

import common

type
  Alignment* = enum
    alNone,
    alCogs,
    alClips

  Entity* = object
    kind*: string
    alignment*: Alignment
    inventoryAmount*: int # -1 when unknown/not applicable
    lastSeen*: int
    vibe*: string

  EntityMap* = ref object
    entities*: Table[Location, Entity]
    explored*: HashSet[Location]

proc newEntityMap*(): EntityMap =
  EntityMap(entities: initTable[Location, Entity](), explored: initHashSet[Location]())

proc isWall*(m: EntityMap, pos: Location): bool =
  m.entities.getOrDefault(pos, Entity()).kind == "wall"

proc hasAgent*(m: EntityMap, pos: Location): bool =
  m.entities.getOrDefault(pos, Entity()).kind == "agent"

proc isStructure*(m: EntityMap, pos: Location): bool =
  ## Any non-wall, non-agent entity.
  let k = m.entities.getOrDefault(pos, Entity()).kind
  if k.len == 0:
    return false
  k != "wall" and k != "agent"

proc isFree*(m: EntityMap, pos: Location): bool =
  pos in m.explored and pos notin m.entities

proc updateFromObservation*(
  m: EntityMap,
  agentPos: Location,
  obsHalfHeight: int,
  obsHalfWidth: int,
  visibleEntities: Table[Location, Entity],
  step: int
) =
  ## Mirror Python Nlanky behavior:
  ## - mark currently observable cells explored
  ## - remove stale entities in currently observable cells
  ## - upsert currently visible entities
  var observed = initHashSet[Location]()
  for dr in -obsHalfHeight .. obsHalfHeight:
    for dc in -obsHalfWidth .. obsHalfWidth:
      if not withinObservationShape(dr, dc, obsHalfHeight, obsHalfWidth):
        continue
      let pos = Location(x: agentPos.x + dc, y: agentPos.y + dr)
      m.explored.incl(pos)
      observed.incl(pos)

  var toRemove: seq[Location] = @[]
  for pos in m.entities.keys:
    if pos in observed and pos notin visibleEntities:
      toRemove.add(pos)
  for pos in toRemove:
    m.entities.del(pos)

  for pos, ent0 in visibleEntities:
    var ent = ent0
    ent.lastSeen = step
    m.entities[pos] = ent

proc clearFarEntities*(m: EntityMap, center: Location, radius: int) =
  var toRemove: seq[Location] = @[]
  for pos in m.entities.keys:
    if manhattan(pos, center) > radius:
      toRemove.add(pos)
  for pos in toRemove:
    m.entities.del(pos)
  var exploredToRemove: seq[Location] = @[]
  for pos in m.explored:
    if manhattan(pos, center) > radius:
      exploredToRemove.add(pos)
  for pos in exploredToRemove:
    m.explored.excl(pos)

proc find*(
  m: EntityMap,
  kind: string = "",
  kindContains: string = "",
  alignment: Alignment = alNone
): seq[(Location, Entity)] =
  for pos, ent in m.entities:
    if kind.len > 0 and ent.kind != kind:
      continue
    if kindContains.len > 0 and kindContains notin ent.kind:
      continue
    if alignment != alNone and ent.alignment != alignment:
      continue
    result.add((pos, ent))

proc findNearest*(
  m: EntityMap,
  fromPos: Location,
  kind: string = "",
  kindContains: string = "",
  alignment: Alignment = alNone,
  maxDist: Option[int] = none(int)
): Option[(Location, Entity)] =
  let matches = m.find(kind=kind, kindContains=kindContains, alignment=alignment)
  if matches.len == 0:
    return none((Location, Entity))

  var bestDist = high(int)
  var best: Option[(Location, Entity)] = none((Location, Entity))
  for (pos, ent) in matches:
    let dist = manhattan(pos, fromPos)
    if maxDist.isSome and dist > maxDist.get():
      continue
    if dist < bestDist:
      bestDist = dist
      best = some((pos, ent))
  best
