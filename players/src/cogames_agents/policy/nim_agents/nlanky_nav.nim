import std/[tables, sets, options, heapqueue, random, algorithm]

import common
import nlanky_entity_map

type
  NavAction* = enum
    naNoop,
    naMoveNorth,
    naMoveSouth,
    naMoveWest,
    naMoveEast

  Navigator* = ref object
    cachedPath: Option[seq[Location]]
    cachedTarget: Option[Location]
    cachedReachAdjacent: bool
    expectedPos: Option[Location]
    positionHistory: seq[Location]
    rng: Rand

proc newNavigator*(seed: int): Navigator =
  Navigator(
    cachedPath: none(seq[Location]),
    cachedTarget: none(Location),
    cachedReachAdjacent: false,
    expectedPos: none(Location),
    positionHistory: @[],
    rng: initRand(seed),
  )

proc clearCache*(nav: Navigator) =
  nav.cachedPath = none(seq[Location])
  nav.cachedTarget = none(Location)
  nav.cachedReachAdjacent = false
  nav.expectedPos = none(Location)

proc clearHistory*(nav: Navigator) =
  nav.positionHistory.setLen(0)

proc cachedTarget*(nav: Navigator): Option[Location] =
  nav.cachedTarget

proc manhattan2(a, b: Location): int =
  abs(a.x - b.x) + abs(a.y - b.y)

proc moveAction*(fromPos, toPos: Location): NavAction =
  if toPos.x == fromPos.x and toPos.y == fromPos.y:
    return naNoop
  if toPos.x == fromPos.x + 1 and toPos.y == fromPos.y:
    return naMoveEast
  if toPos.x == fromPos.x - 1 and toPos.y == fromPos.y:
    return naMoveWest
  if toPos.y == fromPos.y - 1 and toPos.x == fromPos.x:
    return naMoveNorth
  if toPos.y == fromPos.y + 1 and toPos.x == fromPos.x:
    return naMoveSouth
  naNoop

proc isStuck(nav: Navigator): bool =
  ## Mirrors Python Nlanky Navigator._is_stuck.
  let history = nav.positionHistory
  if history.len < 6:
    return false
  let recent = history[max(0, history.len - 6) ..< history.len]
  # Stuck in a small oscillation loop.
  if recent.toHashSet().len <= 2:
    return true
  if history.len >= 20:
    let current = history[^1]
    let earlier = history[0 ..< max(0, history.len - 10)]
    var count = 0
    for p in earlier:
      if p == current:
        count += 1
    if count >= 2:
      return true
  false

proc orderedDeltas(directionBias: string): seq[Location] =
  ## Mirrors Python Nlanky ordering:
  ## - north: N, W, E, S
  ## - south: S, W, E, N
  ## - east:  E, N, S, W
  ## - west:  W, N, S, E
  ## - default: N, S, W, E
  case directionBias
  of "north":
    @[Location(x: 0, y: -1), Location(x: -1, y: 0), Location(x: 1, y: 0), Location(x: 0, y: 1)]
  of "south":
    @[Location(x: 0, y: 1), Location(x: -1, y: 0), Location(x: 1, y: 0), Location(x: 0, y: -1)]
  of "east":
    @[Location(x: 1, y: 0), Location(x: 0, y: -1), Location(x: 0, y: 1), Location(x: -1, y: 0)]
  of "west":
    @[Location(x: -1, y: 0), Location(x: 0, y: -1), Location(x: 0, y: 1), Location(x: 1, y: 0)]
  else:
    @[Location(x: 0, y: -1), Location(x: 0, y: 1), Location(x: -1, y: 0), Location(x: 1, y: 0)]

proc randomMove(nav: Navigator, current: Location, m: EntityMap): NavAction =
  ## Mirrors Python Nlanky Navigator._random_move.
  let deltas = [Location(x: 0, y: -1), Location(x: 0, y: 1), Location(x: 1, y: 0), Location(x: -1, y: 0)]
  var order = @[0, 1, 2, 3]
  var r = nav.rng
  shuffle(r, order)
  nav.rng = r

  for idx in order:
    let d = deltas[idx]
    let pos = Location(x: current.x + d.x, y: current.y + d.y)
    if pos in m.explored and not m.isWall(pos) and not m.isStructure(pos):
      return moveAction(current, pos)
  for idx in order:
    let d = deltas[idx]
    let pos = Location(x: current.x + d.x, y: current.y + d.y)
    if not m.isWall(pos):
      return moveAction(current, pos)
  naNoop

proc breakStuck(nav: Navigator, current: Location, m: EntityMap): Option[NavAction] =
  ## Mirror Python behavior: clear cached path/target and reset history, then take a random step.
  nav.clearCache()
  nav.positionHistory.setLen(0)

  some(nav.randomMove(current, m))

proc isTraversable(pos: Location, m: EntityMap, allowUnknown: bool): bool =
  if m.isWall(pos) or m.isStructure(pos):
    return false
  if m.hasAgent(pos):
    return false
  if pos in m.explored:
    return pos notin m.entities or m.entities[pos].kind == "agent"
  allowUnknown

proc computeGoals(target: Location, m: EntityMap, reachAdjacent: bool): seq[Location] =
  if not reachAdjacent:
    return @[target]
  for d in [Location(x: 0, y: -1), Location(x: 0, y: 1), Location(x: 1, y: 0), Location(x: -1, y: 0)]:
    let p = Location(x: target.x + d.x, y: target.y + d.y)
    if isTraversable(p, m, allowUnknown=true):
      result.add(p)

proc reconstruct(cameFrom: Table[Location, Location], current: Location): seq[Location] =
  var cur = current
  var path: seq[Location] = @[]
  while cur in cameFrom:
    path.add(cur)
    cur = cameFrom[cur]
  path.reverse()
  path

proc astar(start: Location, goals: seq[Location], m: EntityMap, allowUnknown: bool): seq[Location] =
  if goals.len == 0:
    return @[]
  let goalSet = goals.toHashSet()
  proc h(pos: Location): int =
    var best = high(int)
    for g in goals:
      let d = manhattan2(pos, g)
      if d < best:
        best = d
    best

  type Node = tuple[f: int, tie: int, x: int, y: int]
  var open: HeapQueue[Node]
  var tie = 0
  push(open, (f: h(start), tie: tie, x: start.x, y: start.y))
  var cameFrom = initTable[Location, Location]()
  var gScore = initTable[Location, int]()
  gScore[start] = 0
  var visited = initHashSet[Location]()

  var iterations = 0
  let maxIterations = 5000
  while open.len > 0 and iterations < maxIterations:
    iterations += 1
    let (_, _, cx, cy) = pop(open)
    let current = Location(x: cx, y: cy)
    if current in visited:
      continue
    visited.incl(current)
    if current in goalSet:
      return reconstruct(cameFrom, current)

    let currentG = gScore.getOrDefault(current, high(int))
    for d in [Location(x: 0, y: -1), Location(x: 0, y: 1), Location(x: 1, y: 0), Location(x: -1, y: 0)]:
      let neighbor = Location(x: current.x + d.x, y: current.y + d.y)
      let isGoal = neighbor in goalSet
      if not isGoal and not isTraversable(neighbor, m, allowUnknown):
        continue
      let tentativeG = currentG + 1
      if tentativeG < gScore.getOrDefault(neighbor, high(int)):
        cameFrom[neighbor] = current
        gScore[neighbor] = tentativeG
        tie += 1
        push(open, (f: tentativeG + h(neighbor), tie: tie, x: neighbor.x, y: neighbor.y))
  @[]

proc getPath(nav: Navigator, start, target: Location, m: EntityMap, reachAdjacent: bool): seq[Location] =
  if nav.cachedPath.isSome and nav.cachedTarget.isSome and nav.cachedTarget.get() == target and nav.cachedReachAdjacent == reachAdjacent:
    # Verify agent is where we expected (it followed our last suggestion)
    if nav.expectedPos.isSome and start != nav.expectedPos.get():
      nav.cachedPath = none(seq[Location])
    else:
      # Validate cached path (agents can invalidate it).
      var ok = true
      for p in nav.cachedPath.get():
        if m.hasAgent(p):
          ok = false
          break
      if ok:
        return nav.cachedPath.get()

  let goals = computeGoals(target, m, reachAdjacent)
  if goals.len == 0:
    nav.cachedPath = none(seq[Location])
    nav.cachedTarget = some(target)
    nav.cachedReachAdjacent = reachAdjacent
    return @[]

  var path = astar(start, goals, m, allowUnknown=false)
  if path.len == 0:
    path = astar(start, goals, m, allowUnknown=true)

  nav.cachedPath = (if path.len > 0: some(path) else: none(seq[Location]))
  nav.cachedTarget = some(target)
  nav.cachedReachAdjacent = reachAdjacent
  path

proc moveTowardGreedy(nav: Navigator, current, target: Location, m: EntityMap): NavAction =
  ## Mirrors Python Nlanky Navigator._move_toward_greedy: prefer primary axis direction,
  ## then secondary axis, then random move.
  let dr = target.y - current.y
  let dc = target.x - current.x

  var primary: Location
  var secondary: Location
  if abs(dr) >= abs(dc):
    primary = (if dr > 0: Location(x: 0, y: 1) else: Location(x: 0, y: -1))
    secondary = (if dc > 0: Location(x: 1, y: 0) else: Location(x: -1, y: 0))
  else:
    primary = (if dc > 0: Location(x: 1, y: 0) else: Location(x: -1, y: 0))
    secondary = (if dr > 0: Location(x: 0, y: 1) else: Location(x: 0, y: -1))

  for d in [primary, secondary]:
    let pos = Location(x: current.x + d.x, y: current.y + d.y)
    if not m.isWall(pos) and not m.isStructure(pos) and not m.hasAgent(pos):
      return moveAction(current, pos)
  nav.randomMove(current, m)

proc getAction*(
  nav: Navigator,
  current: Location,
  target: Location,
  m: EntityMap,
  reachAdjacent: bool = false
): NavAction =
  nav.positionHistory.add(current)
  if nav.positionHistory.len > 30:
    nav.positionHistory.delete(0)

  if nav.isStuck():
    let a = nav.breakStuck(current, m)
    if a.isSome:
      return a.get()

  if current == target and not reachAdjacent:
    return naNoop
  if reachAdjacent and manhattan2(current, target) == 1:
    return naNoop

  let path = nav.getPath(current, target, m, reachAdjacent)
  if path.len == 0:
    return nav.moveTowardGreedy(current, target, m)

  let nextPos = path[0]
  if m.hasAgent(nextPos):
    # Attempt a small sidestep around the blocking agent (mirrors Python Nlanky).
    let currentDist = manhattan2(current, target)
    var best: Option[Location] = none(Location)
    var bestScore = high(int)
    for d in [Location(x: 0, y: -1), Location(x: 0, y: 1), Location(x: -1, y: 0), Location(x: 1, y: 0)]:
      let pos = Location(x: current.x + d.x, y: current.y + d.y)
      if pos == nextPos:
        continue
      if not isTraversable(pos, m, allowUnknown=true):
        continue
      let newDist = manhattan2(pos, target)
      let score = newDist - currentDist
      if score < bestScore:
        bestScore = score
        best = some(pos)
    if best.isSome and bestScore <= 2:
      nav.clearCache()
      return moveAction(current, best.get())
    return naNoop

  # Record where agent should be if it follows this suggestion
  nav.expectedPos = some(nextPos)
  # Advance cached path
  if path.len > 1:
    nav.cachedPath = some(path[1 .. ^1])
  else:
    nav.cachedPath = none(seq[Location])
  moveAction(current, nextPos)

proc findFrontier(nav: Navigator, fromPos: Location, m: EntityMap, directionBias: string): Option[Location] =
  # BFS for nearest unexplored cell adjacent to an explored free cell.
  type QItem = tuple[pos: Location, dist: int]
  var q: seq[QItem] = @[(pos: fromPos, dist: 0)]
  var seen = initHashSet[Location]()
  seen.incl(fromPos)

  let deltas = orderedDeltas(directionBias)
  var idx = 0
  while idx < q.len:
    let (pos, dist) = q[idx]
    idx += 1
    if dist > 50:
      continue

    for d in deltas:
      let nxt = Location(x: pos.x + d.x, y: pos.y + d.y)
      if nxt in seen:
        continue
      seen.incl(nxt)

      if nxt notin m.explored:
        # Check if any neighbor is explored and free.
        for d2 in deltas:
          let adj = Location(x: nxt.x + d2.x, y: nxt.y + d2.y)
          if adj in m.explored and m.isFree(adj):
            return some(nxt)
        continue

      if isTraversable(nxt, m, allowUnknown=false):
        q.add((pos: nxt, dist: dist + 1))

  none(Location)

proc explore*(nav: Navigator, current: Location, m: EntityMap, directionBias: string = ""): NavAction =
  nav.positionHistory.add(current)
  if nav.positionHistory.len > 30:
    nav.positionHistory.delete(0)

  if nav.isStuck():
    let a = nav.breakStuck(current, m)
    if a.isSome:
      return a.get()

  let frontier = nav.findFrontier(current, m, directionBias)
  if frontier.isSome:
    return nav.getAction(current, frontier.get(), m, reachAdjacent=false)
  nav.randomMove(current, m)
