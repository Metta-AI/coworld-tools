## Action layer — phase 2.
##
## Translates `ActionIntent` values from modes into the game-protocol
## button mask. Owns the persistent tactical state (`ActionState`) that
## survives across ticks: current A* path, motion model, jiggle counters,
## last emitted mask, task-hold discipline. See DESIGN.md §4.4 and §6.
##
## Phase 2 implements:
##   - A* pathfinding on the 952×534 walk mask (4-connected, unit cost,
##     Manhattan heuristic). Path recomputed only when goal changes or
##     stuck detection triggers a re-plan.
##   - Discipline-aware button mask generation:
##     - `DisciplineNormal`    — A* path following + direction buttons
##     - `DisciplineTaskHold`  — hold ButtonA only, no movement
##     - `DisciplineKillStrike`— steer toward target + ButtonA on contact
##     - `DisciplineReport`    — steer toward target + ButtonA in range
##     - `DisciplineNoOp`      — mask 0
##   - Stuck detection and perpendicular jiggle.
##   - Ghost straight-line steering (no walk mask).
##   - Meeting cursor/button handling.

import types
import perception/data
import perception/geometry

# ---------------------------------------------------------------------------
# Tuning constants (action-layer specific)
# ---------------------------------------------------------------------------

const
  PathLookahead = 4      ## Steps ahead in the A* path to aim at. Kept small
                         ## so the waypoint stays tightly on the A* corridor
                         ## through turns. Larger values (18+) overshoot
                         ## corners and cause oscillation.
  StuckThreshold = 8     ## Frames of zero velocity before jiggle fires.
  JiggleDuration = 6     ## Ticks of perpendicular movement during jiggle.
  KillStrikeRange = 20   ## World-pixel distance for kill-strike ButtonA.
                         ## Matches the server's KillRange (sim.nim).
  ReportRange = 20       ## World-pixel distance for report ButtonA.
  MaxAstarNodes = 30_000 ## Upper bound on nodes expanded before A* gives
                         ## up. The 952x534 map has ~508K cells; capping at
                         ## 30K keeps worst-case latency <10 ms while still
                         ## finding any reasonable cross-map path.
  ReplanIntervalTicks = 24  ## Recompute A* path every N ticks to recover
                            ## from position-noise drift (~1s at 24Hz).
  StallProgressTicks = 48   ## If distance-to-goal hasn't decreased in N
                            ## ticks, force path recompute (~2s at 24Hz).

# ---------------------------------------------------------------------------
# A* pathfinding
# ---------------------------------------------------------------------------

proc passable(wm: openArray[uint8], x, y: int): bool {.inline.} =
  ## True when world pixel (x, y) is walkable and in bounds.
  ## Uses one-pixel margin on the far edges (matching modulabot).
  if x < 0 or y < 0: return false
  if x + 1 >= MapWidth or y + 1 >= MapHeight: return false
  wm[y * MapWidth + x] != 0

proc snapToPassable*(wm: openArray[uint8], x, y: int): (bool, int, int) =
  ## Find the nearest passable pixel to (x, y) via BFS in concentric
  ## Manhattan-distance shells. Returns (true, px, py) on success, or
  ## (false, x, y) if nothing passable exists within the search radius.
  ## Used at init time to precompute passable task-station centres, and
  ## as a defense-in-depth fallback for any steer target that lands on
  ## an impassable pixel.
  if passable(wm, x, y):
    return (true, x, y)
  const MaxRadius = 32  ## Task stations are 16x16; nearest walkable is
                        ## almost always within a few pixels.
  for r in 1 .. MaxRadius:
    for dx in -r .. r:
      let dy = r - abs(dx)
      # Check both +dy and -dy (the two points at this Manhattan distance
      # on the current ring).
      for sign in [-1, 1]:
        let ny = y + sign * dy
        let nx = x + dx
        if passable(wm, nx, ny):
          return (true, nx, ny)
        if dy == 0:
          break  # Only one point when dy == 0; avoid checking it twice.
  (false, x, y)

proc findPath*(wm: openArray[uint8],
               startX, startY, goalX, goalY: int): seq[Point] =
  ## Standard A* on the walk mask. Returns the path from the step
  ## *after* start through goal inclusive, one Point per pixel.
  ## Returns empty if no path exists or either endpoint is impassable.
  if not passable(wm, startX, startY): return @[]
  if not passable(wm, goalX, goalY): return @[]

  let area = MapWidth * MapHeight
  let startIdx = startY * MapWidth + startX
  let goalIdx = goalY * MapWidth + goalX
  if startIdx == goalIdx: return @[]

  # Flat arrays for parent tracking and cost.
  var parents = newSeq[int32](area)
  var costs = newSeq[int32](area)
  var closed = newSeq[bool](area)
  for i in 0 ..< area:
    parents[i] = -2'i32
    costs[i] = high(int32)

  parents[startIdx] = -1'i32
  costs[startIdx] = 0'i32

  # Binary heap entries: (priority, nodeIndex). Nim's built-in heapqueue
  # isn't available without import, so we use a simple seq-based min-heap.
  type HeapEntry = tuple[priority: int32, index: int32]

  var heap: seq[HeapEntry] = @[]

  # Inline heap operations for performance.
  proc heapPush(h: var seq[HeapEntry], e: HeapEntry) =
    h.add(e)
    var i = h.len - 1
    while i > 0:
      let parent = (i - 1) div 2
      if h[i].priority < h[parent].priority or
         (h[i].priority == h[parent].priority and h[i].index < h[parent].index):
        swap(h[i], h[parent])
        i = parent
      else:
        break

  proc heapPop(h: var seq[HeapEntry]): HeapEntry =
    result = h[0]
    h[0] = h[^1]
    h.setLen(h.len - 1)
    var i = 0
    while true:
      let left = 2 * i + 1
      let right = 2 * i + 2
      var smallest = i
      if left < h.len and
         (h[left].priority < h[smallest].priority or
          (h[left].priority == h[smallest].priority and h[left].index < h[smallest].index)):
        smallest = left
      if right < h.len and
         (h[right].priority < h[smallest].priority or
          (h[right].priority == h[smallest].priority and h[right].index < h[smallest].index)):
        smallest = right
      if smallest == i: break
      swap(h[i], h[smallest])
      i = smallest

  heapPush(heap, (int32(heuristic(startX, startY, goalX, goalY)), int32(startIdx)))

  var nodesExpanded = 0
  while heap.len > 0:
    let entry = heapPop(heap)
    let current = int(entry.index)
    if closed[current]: continue
    inc nodesExpanded
    if nodesExpanded > MaxAstarNodes:
      # Safety cap: prevent runaway expansion on unreachable or very
      # distant goals. The caller gets an empty path and falls back to
      # straight-line steering or idle.
      return @[]
    if current == goalIdx:
      # Reconstruct path from goal to start.
      var path: seq[Point] = @[]
      var step = goalIdx
      while step != startIdx and step >= 0:
        path.add Point(x: step mod MapWidth, y: step div MapWidth)
        step = int(parents[step])
      # Reverse to get start→goal order.
      var lo = 0
      var hi = path.len - 1
      while lo < hi:
        swap(path[lo], path[hi])
        inc lo
        dec hi
      return path

    closed[current] = true
    let cx = current mod MapWidth
    let cy = current div MapWidth
    let curCost = costs[current]

    # 4-connected neighbours.
    const dx = [-1'i32, 1, 0, 0]
    const dy = [0'i32, 0, -1, 1]
    for d in 0 ..< 4:
      let nx = cx + int(dx[d])
      let ny = cy + int(dy[d])
      if nx < 0 or ny < 0 or nx + 1 >= MapWidth or ny + 1 >= MapHeight:
        continue
      if wm[ny * MapWidth + nx] == 0: continue
      let ni = ny * MapWidth + nx
      if closed[ni]: continue
      let newCost = curCost + 1
      if newCost >= costs[ni]: continue
      costs[ni] = newCost
      parents[ni] = int32(current)
      heapPush(heap, (newCost + int32(heuristic(nx, ny, goalX, goalY)), int32(ni)))

  return @[]

# ---------------------------------------------------------------------------
# Path step selection
# ---------------------------------------------------------------------------

proc choosePathStep(path: seq[Point]): (bool, Point) =
  ## Return a short-lookahead waypoint. Returns (false, _) if path empty.
  if path.len == 0:
    return (false, Point(x: 0, y: 0))
  let idx = min(path.len - 1, PathLookahead)
  (true, path[idx])

# ---------------------------------------------------------------------------
# Direction buttons from current position to waypoint
# ---------------------------------------------------------------------------

proc steerButtons(selfX, selfY, targetX, targetY: int): uint8 {.inline.} =
  ## Produce direction-button bits to move from self toward target.
  var mask: uint8 = 0
  if targetX < selfX: mask = mask or ButtonLeft
  elif targetX > selfX: mask = mask or ButtonRight
  if targetY < selfY: mask = mask or ButtonUp
  elif targetY > selfY: mask = mask or ButtonDown
  mask

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

proc initActionState*(): ActionState =
  ActionState(
    currentPath: @[],
    currentGoalValid: false,
    lastEmittedMask: 0'u8,
    lastVelocityX: 0, lastVelocityY: 0,
    stuckFrames: 0,
    jiggleTicks: 0,
    taskHoldTicks: 0,
    lastReplanTick: 0,
    bestGoalDist: high(int),
    bestGoalDistTick: 0
  )

proc initActionIntent*(): ActionIntent =
  ActionIntent(
    steerValid: false,
    pressA: false,
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineNoOp
  )

proc noOpIntent*(): ActionIntent = initActionIntent()

# ---------------------------------------------------------------------------
# Core: applyIntent
# ---------------------------------------------------------------------------

proc applyIntent*(
    state: var ActionState,
    belief: Belief,
    intent: ActionIntent): uint8 =
  ## Translate an ActionIntent into a button mask. Handles all
  ## discipline types, A* path following, stuck detection, jiggle,
  ## ghost straight-line steering, and meeting cursor/button.

  # --- DisciplineNoOp ---
  if intent.discipline == DisciplineNoOp:
    # Meeting cursor movement still works under NoOp discipline
    # (cursor-only intents from meeting mode).
    var mask: uint8 = 0
    if intent.pressA: mask = mask or ButtonA
    if intent.pressB: mask = mask or ButtonB
    if intent.cursor == CursorLeft: mask = mask or ButtonLeft
    elif intent.cursor == CursorRight: mask = mask or ButtonRight
    state.lastEmittedMask = mask
    return mask

  # --- DisciplineWander ---
  # Raw directional movement without A*, localization, or stuck
  # detection. Used by idle mode to move before the localizer locks.
  # If steerValid, steer toward the target using the (possibly stale)
  # selfX/selfY. Otherwise cycle through cardinal directions based on
  # the tick counter embedded in steerTo.x (which idle mode sets to
  # the direction phase).
  if intent.discipline == DisciplineWander:
    var mask: uint8 = 0
    if intent.steerValid:
      # Steer toward steerTo using whatever position we have (may be
      # stale, but any movement helps the localizer).
      let sx = belief.percep.selfX
      let sy = belief.percep.selfY
      mask = steerButtons(sx, sy, intent.steerTo.x, intent.steerTo.y)
    else:
      # Tick-based cardinal cycling. steerTo.x carries the phase (0-3).
      case intent.steerTo.x
      of 0: mask = ButtonUp
      of 1: mask = ButtonRight
      of 2: mask = ButtonDown
      of 3: mask = ButtonLeft
      else: mask = ButtonUp
    if intent.pressA: mask = mask or ButtonA
    if intent.pressB: mask = mask or ButtonB
    state.lastEmittedMask = mask
    return mask

  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let localized = belief.percep.localized

  # --- DisciplineTaskHold ---
  if intent.discipline == DisciplineTaskHold:
    # Hold A, no movement.
    let mask = ButtonA
    inc state.taskHoldTicks
    state.lastEmittedMask = mask
    return mask

  # --- DisciplineKillStrike ---
  if intent.discipline == DisciplineKillStrike:
    var mask: uint8 = 0
    if intent.steerValid and localized:
      mask = steerButtons(selfX, selfY, intent.steerTo.x, intent.steerTo.y)
      let dist = heuristic(selfX, selfY, intent.steerTo.x, intent.steerTo.y)
      if dist <= KillStrikeRange:
        mask = mask or ButtonA
    state.lastEmittedMask = mask
    return mask

  # --- DisciplineReport ---
  if intent.discipline == DisciplineReport:
    var mask: uint8 = 0
    if intent.steerValid and localized:
      mask = steerButtons(selfX, selfY, intent.steerTo.x, intent.steerTo.y)
      let dist = heuristic(selfX, selfY, intent.steerTo.x, intent.steerTo.y)
      if dist <= ReportRange:
        mask = mask or ButtonA
    state.lastEmittedMask = mask
    return mask

  # --- DisciplineNormal ---
  # This is the main A*-backed steering path.
  var mask: uint8 = 0
  state.taskHoldTicks = 0

  if not intent.steerValid or not localized:
    # No destination or no camera lock — idle.
    if intent.pressA: mask = mask or ButtonA
    if intent.pressB: mask = mask or ButtonB
    state.lastEmittedMask = mask
    return mask

  let goalX = intent.steerTo.x
  let goalY = intent.steerTo.y
  let curGoalDist = heuristic(selfX, selfY, goalX, goalY)

  # Decide whether to (re)compute the A* path. Triggers:
  #   1. Goal changed (new task station, new target).
  #   2. Periodic replan every ReplanIntervalTicks to recover from
  #      position-noise drift that corrupts path trimming.
  #   3. Progress stall: distance hasn't decreased in StallProgressTicks.
  let goalChanged = not state.currentGoalValid or
                    state.currentGoal.x != goalX or
                    state.currentGoal.y != goalY
  let periodicReplan = belief.tick - state.lastReplanTick >= ReplanIntervalTicks
  let progressStall = belief.tick - state.bestGoalDistTick >= StallProgressTicks and
                      state.bestGoalDistTick > 0
  let needReplan = goalChanged or periodicReplan or progressStall or
                   state.currentPath.len == 0

  if needReplan:
    state.currentGoal = Point(x: goalX, y: goalY)
    state.currentGoalValid = true
    state.stuckFrames = 0
    state.jiggleTicks = 0
    state.lastReplanTick = belief.tick
    state.bestGoalDist = curGoalDist
    state.bestGoalDistTick = belief.tick
    # Ghost: straight-line (no walk mask needed).
    if belief.self.isGhost:
      state.currentPath = @[Point(x: goalX, y: goalY)]
    else:
      state.currentPath = findPath(
        referenceData.map.walkMask,
        selfX, selfY, goalX, goalY)
  else:
    # Track progress toward goal for stall detection.
    if curGoalDist < state.bestGoalDist:
      state.bestGoalDist = curGoalDist
      state.bestGoalDistTick = belief.tick

  # Velocity tracking for stuck detection. selfX = cameraX + PlayerWorldOff,
  # so velocity equals the camera delta between frames.
  let velX = belief.percep.cameraX - belief.percep.lastCameraX
  let velY = belief.percep.cameraY - belief.percep.lastCameraY
  state.lastVelocityX = velX
  state.lastVelocityY = velY

  # Stuck detection: if we intended to move but didn't. Two cases:
  #   1. Had a path + emitted direction buttons but velocity was zero
  #      (physically stuck against a wall).
  #   2. Had a valid steer target but A* returned an empty path AND
  #      the greedy fallback emitted direction buttons but velocity
  #      was still zero. The greedy fallback (below) ensures
  #      lastEmittedMask has direction bits even without a path, so
  #      case 1's condition now covers both scenarios.
  if velX == 0 and velY == 0 and
     state.lastEmittedMask != 0 and
     (state.lastEmittedMask and (ButtonUp or ButtonDown or ButtonLeft or ButtonRight)) != 0:
    inc state.stuckFrames
  else:
    state.stuckFrames = 0

  # Jiggle: if stuck for too long, move perpendicular for a few ticks.
  if state.jiggleTicks > 0:
    dec state.jiggleTicks
    # Emit perpendicular direction to the last attempted movement.
    let lastDir = state.lastEmittedMask and (ButtonUp or ButtonDown or ButtonLeft or ButtonRight)
    if (lastDir and (ButtonLeft or ButtonRight)) != 0:
      # Was moving horizontally — jiggle vertically.
      mask = ButtonDown  # Arbitrary; could alternate.
    else:
      # Was moving vertically — jiggle horizontally.
      mask = ButtonRight
    if intent.pressA: mask = mask or ButtonA
    state.lastEmittedMask = mask
    return mask

  if state.stuckFrames >= StuckThreshold:
    # Trigger jiggle and recompute path afterward.
    state.jiggleTicks = JiggleDuration
    state.stuckFrames = 0
    # Force path recompute next tick.
    state.lastReplanTick = 0

  # Follow path: pick a lookahead waypoint and steer toward it.
  if state.currentPath.len > 0:
    # Trim path: drop steps we've already passed.
    while state.currentPath.len > 1:
      let first = state.currentPath[0]
      let distToFirst = heuristic(selfX, selfY, first.x, first.y)
      if distToFirst <= 2:
        state.currentPath.delete(0)
      else:
        break

    let (found, waypoint) = choosePathStep(state.currentPath)
    if found:
      mask = steerButtons(selfX, selfY, waypoint.x, waypoint.y)

  # Greedy-steering fallback: if A* returned an empty path (goal
  # impassable, unreachable, or node cap exceeded), steer directly
  # toward the goal and let the anti-stuck jiggle handle walls.
  # Mirrors modulabot's ``policies/base.py`` fallback. Without this,
  # an empty path leaves mask at 0 and the bot freezes permanently.
  if mask == 0 and state.currentPath.len == 0:
    mask = steerButtons(selfX, selfY, goalX, goalY)

  # Apply button overrides from the intent.
  if intent.pressA: mask = mask or ButtonA
  if intent.pressB: mask = mask or ButtonB

  state.lastEmittedMask = mask
  mask

# ---------------------------------------------------------------------------
# Chat emission (meeting mode)
# ---------------------------------------------------------------------------

proc emitChat*(state: var ActionState, text: string): bool =
  ## Phase 2 stub: chat queuing for meeting mode. Returns true if
  ## accepted. Full implementation deferred to phase 3 (LLM integration).
  discard state
  discard text
  false
