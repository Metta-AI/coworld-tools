## Action layer — hierarchical waypoint navigation.
##
## Translates `ActionIntent` values from modes into the game-protocol
## button mask. Uses the precomputed waypoint graph and pixel-paths
## for navigation (no runtime A*). See NAVIGATION_DESIGN.md.
##
## Disciplines:
##   - `DisciplineNormal`     — waypoint-based path following
##   - `DisciplineTaskHold`   — hold ButtonA, no movement
##   - `DisciplineKillStrike` — steer toward target + ButtonA on contact
##   - `DisciplineReport`     — steer toward target + ButtonA in range
##   - `DisciplineWander`     — raw directional movement (pre-localization)
##   - `DisciplineNoOp`       — mask 0 (plus cursor/button passthrough)

import std/strutils
import types
import navigation
import perception/data
import perception/geometry
import tuning

export navigation.initActionState

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

const
  KillStrikeRange = 20   ## World-pixel distance for kill-strike ButtonA.
  ReportRange = 20       ## World-pixel distance for report ButtonA.

# ---------------------------------------------------------------------------
# Momentum-aware steering controller
# ---------------------------------------------------------------------------

proc hasMovement(mask: uint8): bool {.inline.} =
  ## True if any direction button is set in the mask.
  (mask and (ButtonUp or ButtonDown or ButtonLeft or ButtonRight)) != 0

proc updateMotionState*(state: var ActionState, selfX, selfY: int,
                        localized: bool) =
  ## Track frame-to-frame velocity. Call once per tick before steering.
  if not localized:
    state.haveMotionSample = false
    state.velocityX = 0
    state.velocityY = 0
    state.stuckFrames = 0
    state.jiggleTicks = 0
    return

  if state.haveMotionSample and state.lastEmittedMask.hasMovement():
    state.velocityX = selfX - state.previousSelfX
    state.velocityY = selfY - state.previousSelfY
    let moved = abs(state.velocityX) + abs(state.velocityY)
    if moved == 0:
      inc state.stuckFrames
    else:
      state.stuckFrames = 0
    if state.stuckFrames >= StuckFrameThreshold:
      state.stuckFrames = 0
      state.jiggleTicks = JiggleDuration
      state.jiggleSide = 1 - state.jiggleSide
  else:
    state.velocityX = 0
    state.velocityY = 0
    state.stuckFrames = 0

  state.haveMotionSample = true
  state.previousSelfX = selfX
  state.previousSelfY = selfY

proc coastDistance(velocity: int): int =
  ## Simulate friction decay to predict how far current velocity carries.
  var speed = abs(velocity)
  for _ in 0 ..< CoastLookaheadTicks:
    if speed <= 0:
      break
    result += speed
    speed = (speed * FrictionNum) div FrictionDen

proc shouldCoast(delta, velocity: int): bool =
  ## True when existing velocity will carry us to the target.
  if delta > 0 and velocity > 0:
    return delta <= coastDistance(velocity) + CoastArrivalPadding
  if delta < 0 and velocity < 0:
    return -delta <= coastDistance(velocity) + CoastArrivalPadding
  false

proc axisMask(delta, velocity: int, negativeMask, positiveMask: uint8): uint8 =
  ## Momentum-aware single-axis steering with coasting and active braking.
  ## - Far from target: accelerate toward it (or coast/brake if appropriate)
  ## - Within deadband: only brake residual velocity
  if delta > SteerDeadband:
    if shouldCoast(delta, velocity):
      return 0
    if velocity > 1 and delta <= abs(velocity) + BrakeDeadband:
      return negativeMask
    return positiveMask
  if delta < -SteerDeadband:
    if shouldCoast(delta, velocity):
      return 0
    if velocity < -1 and -delta <= abs(velocity) + BrakeDeadband:
      return positiveMask
    return negativeMask
  if velocity > 0:
    return negativeMask
  if velocity < 0:
    return positiveMask
  0

proc preciseAxisMask(delta, velocity: int,
                     negativeMask, positiveMask: uint8): uint8 =
  ## Zero-deadband variant for final approach. Uses coast/brake but
  ## targets delta=0 exactly instead of accepting a 2px band.
  if delta > 0:
    if shouldCoast(delta, velocity):
      return 0
    if velocity > 1 and delta <= abs(velocity) + BrakeDeadband:
      return negativeMask
    return positiveMask
  if delta < 0:
    if shouldCoast(delta, velocity):
      return 0
    if velocity < -1 and -delta <= abs(velocity) + BrakeDeadband:
      return positiveMask
    return negativeMask
  if velocity > 0:
    return negativeMask
  if velocity < 0:
    return positiveMask
  0

proc steerButtons(selfX, selfY, targetX, targetY: int,
                  velX, velY: int): uint8 {.inline.} =
  ## Momentum-aware steering: coast/brake/accelerate per axis.
  let dx = targetX - selfX
  let dy = targetY - selfY
  result = axisMask(dx, velX, ButtonLeft, ButtonRight) or
           axisMask(dy, velY, ButtonUp, ButtonDown)

proc preciseSteerButtons(selfX, selfY, targetX, targetY: int,
                         velX, velY: int): uint8 {.inline.} =
  ## Zero-deadband final-approach steering with coast/brake.
  let dx = targetX - selfX
  let dy = targetY - selfY
  result = preciseAxisMask(dx, velX, ButtonLeft, ButtonRight) or
           preciseAxisMask(dy, velY, ButtonUp, ButtonDown)

proc applyJiggle(state: var ActionState, mask: uint8): uint8 =
  ## Add perpendicular correction while keeping intent direction held.
  ## Only applies when stuck detection has triggered a jiggle window.
  result = mask
  if state.jiggleTicks <= 0 or not mask.hasMovement():
    return
  dec state.jiggleTicks
  let
    vertical = (mask and (ButtonUp or ButtonDown)) != 0
    horizontal = (mask and (ButtonLeft or ButtonRight)) != 0
  if vertical and not horizontal:
    if state.jiggleSide == 0:
      result = result or ButtonLeft
    else:
      result = result or ButtonRight
  elif horizontal and not vertical:
    if state.jiggleSide == 0:
      result = result or ButtonUp
    else:
      result = result or ButtonDown
  elif state.jiggleSide == 0:
    result = result or ButtonLeft
  else:
    result = result or ButtonRight

proc addIntentButtons(mask: var uint8, intent: ActionIntent) {.inline.} =
  if intent.pressA: mask = mask or ButtonA
  if intent.pressB: mask = mask or ButtonB

proc canVentSafely(belief: Belief): bool =
  ## Conservative witness check for VentIfSafe. Actor scan usually includes
  ## our own sprite, so one visible crewmate is still safe.
  belief.percep.visibleCrewmates.len <= 1

proc desiredVentPolicy(belief: Belief): VentPolicy =
  ## Mode-level default. Crewmates never vent; impostors can use vents in
  ## pursuit/flee modes once the traversal code is ready.
  if belief.self.role != RoleImposter:
    return VentNever
  case belief.directive.mode
  of ModeFleeing:
    VentAlways
  of ModeHunting:
    VentIfSafe
  else:
    VentNever

proc pathForward(graph: NavGraph, edgeIdx, fromWp, toWp: int): bool =
  ## True when the current waypoint-index transition matches the baked
  ## edge's src->dst direction. Walking edges may be traversed either way.
  if edgeIdx < 0 or edgeIdx >= graph.edges.len:
    return true
  if fromWp < 0 or fromWp >= graph.waypointCount:
    return true
  if toWp < 0 or toWp >= graph.waypointCount:
    return true
  let edge = graph.edges[edgeIdx]
  let fromId = graph.waypoints[fromWp].id
  let toId = graph.waypoints[toWp].id
  edge.src == fromId and edge.dst == toId

proc replanStrategic(state: var ActionState, graph: NavGraph,
                     belief: Belief, selfX, selfY, goalX, goalY,
                     tick: int) =
  ## Recompute waypoint sequence and set up the first edge.
  state.currentGoal = Point(x: goalX, y: goalY)
  state.currentGoalValid = true
  state.strategicPath = planStrategicPath(
    graph, selfX, selfY, goalX, goalY, state.ventPolicy,
    canVentSafely(belief))
  state.pathProgress = 0
  state.currentEdgeIdx = -1
  state.currentEdgeFrom = -1
  state.currentEdgeTo = -1
  state.lastPlanTick = tick
  state.lastProgressTick = tick
  state.lastWaypointDistance = high(int)
  state.ventAttemptTicks = 0
  if state.strategicPath.len > 0:
    let startWp = nearestWaypoint(graph, selfX, selfY)
    let nextWp = state.strategicPath[0]
    setCurrentEdge(state, graph, startWp, nextWp)

# ---------------------------------------------------------------------------
# Snap to passable (retained as utility for fleeing.nim)
# ---------------------------------------------------------------------------

proc snapToPassable*(wm: openArray[uint8], x, y: int): (bool, int, int) =
  ## Find the nearest passable pixel to (x, y) via BFS in concentric
  ## Manhattan-distance shells. Retained for compatibility with
  ## fleeing.nim which calls this directly.
  proc passable(wm: openArray[uint8], x, y: int): bool {.inline.} =
    if x < 0 or y < 0: return false
    if x + 1 >= MapWidth or y + 1 >= MapHeight: return false
    wm[y * MapWidth + x] != 0

  if passable(wm, x, y):
    return (true, x, y)
  const MaxRadius = 32
  for r in 1 .. MaxRadius:
    for dx in -r .. r:
      let dy = r - abs(dx)
      for sign in [-1, 1]:
        let ny = y + sign * dy
        let nx = x + dx
        if passable(wm, nx, ny):
          return (true, nx, ny)
        if dy == 0:
          break
  (false, x, y)

# ---------------------------------------------------------------------------
# Intent constructors (retained interface)
# ---------------------------------------------------------------------------

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
  ## Translate an ActionIntent into a button mask using hierarchical
  ## waypoint navigation for DisciplineNormal. Other disciplines
  ## use simpler direct-steering logic.

  state.lastLookaheadValid = false

  let graph = navGraph()[]
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let localized = belief.percep.localized
  updateMotionState(state, selfX, selfY, localized)

  # --- DisciplineNoOp ---
  if intent.discipline == DisciplineNoOp:
    var mask: uint8 = 0
    if intent.pressA: mask = mask or ButtonA
    if intent.pressB: mask = mask or ButtonB
    if intent.cursor == CursorLeft: mask = mask or ButtonLeft
    elif intent.cursor == CursorRight: mask = mask or ButtonRight
    state.lastEmittedMask = mask
    return mask

  # --- DisciplineWander ---
  if intent.discipline == DisciplineWander:
    var mask: uint8 = 0
    if intent.steerValid:
      let sx = belief.percep.selfX
      let sy = belief.percep.selfY
      mask = steerButtons(sx, sy, intent.steerTo.x, intent.steerTo.y,
                          state.velocityX, state.velocityY)
    else:
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

  # --- DisciplineTaskHold ---
  if intent.discipline == DisciplineTaskHold:
    let mask = ButtonA
    inc state.taskHoldTicks
    state.lastSelfX = selfX
    state.lastSelfY = selfY
    state.lastEmittedMask = mask
    return mask

  # --- DisciplineKillStrike ---
  if intent.discipline == DisciplineKillStrike:
    var mask: uint8 = 0
    if intent.steerValid and localized:
      mask = steerButtons(selfX, selfY, intent.steerTo.x, intent.steerTo.y,
                          state.velocityX, state.velocityY)
      let dist = heuristic(selfX, selfY, intent.steerTo.x, intent.steerTo.y)
      if dist <= KillStrikeRange:
        mask = mask or ButtonA
    state.lastSelfX = selfX
    state.lastSelfY = selfY
    state.lastEmittedMask = mask
    return mask

  # --- DisciplineReport ---
  if intent.discipline == DisciplineReport:
    var mask: uint8 = 0
    if intent.steerValid and localized:
      mask = steerButtons(selfX, selfY, intent.steerTo.x, intent.steerTo.y,
                          state.velocityX, state.velocityY)
      let dist = heuristic(selfX, selfY, intent.steerTo.x, intent.steerTo.y)
      if dist <= ReportRange:
        mask = mask or ButtonA
    state.lastSelfX = selfX
    state.lastSelfY = selfY
    state.lastEmittedMask = mask
    return mask

  # --- DisciplineNormal: hierarchical waypoint navigation ---
  var mask: uint8 = 0
  state.taskHoldTicks = 0

  if not intent.steerValid or not localized:
    if intent.pressA: mask = mask or ButtonA
    if intent.pressB: mask = mask or ButtonB
    state.lastSelfX = selfX
    state.lastSelfY = selfY
    state.lastEmittedMask = mask
    return mask

  let goalX = intent.steerTo.x
  let goalY = intent.steerTo.y
  let tick = belief.tick
  state.arrivedAtWaypoint = false
  state.ventPolicy = desiredVentPolicy(belief)

  if state.navNoopUntilTick > tick:
    state.lastSelfX = selfX
    state.lastSelfY = selfY
    state.lastEmittedMask = 0'u8
    return 0'u8

  # Ghost: greedy straight-line (no obstacles)
  if belief.self.isGhost:
    mask = steerButtons(selfX, selfY, goalX, goalY,
                        state.velocityX, state.velocityY)
    mask = applyJiggle(state, mask)
    addIntentButtons(mask, intent)
    state.lastSelfX = selfX
    state.lastSelfY = selfY
    state.lastEmittedMask = mask
    return mask

  # Final approach: if very close to goal, steer directly (skip waypoints)
  if heuristic(selfX, selfY, goalX, goalY) <= FinalApproachRadius:
    mask = preciseSteerButtons(selfX, selfY, goalX, goalY,
                               state.velocityX, state.velocityY)
    mask = applyJiggle(state, mask)
    addIntentButtons(mask, intent)
    state.lastSelfX = selfX
    state.lastSelfY = selfY
    state.lastEmittedMask = mask
    return mask

  let nearestDist = nearestWaypointDistance(graph, selfX, selfY)
  if nearestDist > 100:
    setNavError(state, tick, "nearest_waypoint_far")
    state.lastSelfX = selfX
    state.lastSelfY = selfY
    state.lastEmittedMask = 0'u8
    return 0'u8

  # Replan strategic path if goal changed, periodically, or after a stall.
  let periodicReplan = state.currentGoalValid and
    tick - state.lastPlanTick >= ReplanIntervalTicks
  let stalled = state.currentGoalValid and
    state.strategicPath.len > 0 and
    tick - state.lastProgressTick >= StallProgressTicks
  if goalChanged(state, goalX, goalY) or periodicReplan or stalled:
    replanStrategic(state, graph, belief, selfX, selfY, goalX, goalY, tick)

  if state.strategicPath.len > 0 and state.currentEdgeIdx < 0:
    setNavError(state, tick, "strategic_edge_missing")
    state.lastSelfX = selfX
    state.lastSelfY = selfY
    state.lastEmittedMask = 0'u8
    return 0'u8

  # Check waypoint arrival — advance to next edge
  if state.strategicPath.len > 0:
    let targetWpIdx = state.strategicPath[0]
    if targetWpIdx < graph.waypointCount:
      let targetWp = graph.waypoints[targetWpIdx]
      let targetDist = heuristic(selfX, selfY, targetWp.x, targetWp.y)
      if targetDist < state.lastWaypointDistance:
        state.lastWaypointDistance = targetDist
        state.lastProgressTick = tick
      if heuristic(selfX, selfY, targetWp.x, targetWp.y) <= WaypointArrivalRadius:
        # Arrived at this waypoint — advance
        state.strategicPath.delete(0)
        state.arrivedAtWaypoint = true
        state.lastProgressTick = tick
        state.lastWaypointDistance = high(int)
        state.ventAttemptTicks = 0
        state.pathProgress = 0
        state.currentEdgeIdx = -1
        state.currentEdgeFrom = -1
        state.currentEdgeTo = -1
        if state.strategicPath.len > 0:
          let nextWp = state.strategicPath[0]
          setCurrentEdge(state, graph, targetWpIdx, nextWp)

  # Handle vent traversal edges. Walking to the vent entry happened on
  # the previous edge; the vent edge itself emits ButtonB until teleport.
  if state.currentEdgeIdx >= 0 and graph.edges[state.currentEdgeIdx].isVent:
    if state.currentEdgeFrom < 0 or state.currentEdgeTo < 0:
      setNavError(state, tick, "vent_edge_missing_waypoints")
      state.lastSelfX = selfX
      state.lastSelfY = selfY
      state.lastEmittedMask = 0'u8
      return 0'u8

    let entry = graph.waypoints[state.currentEdgeFrom]
    let exit = graph.waypoints[state.currentEdgeTo]
    let entryDist = heuristic(selfX, selfY, entry.x, entry.y)
    let exitDist = heuristic(selfX, selfY, exit.x, exit.y)
    let jumped = heuristic(selfX, selfY, state.lastSelfX, state.lastSelfY) >=
      VentTeleportDistance

    if exitDist <= WaypointArrivalRadius or (jumped and exitDist <= PathSnapRadius):
      if state.strategicPath.len > 0 and state.strategicPath[0] == state.currentEdgeTo:
        state.strategicPath.delete(0)
      state.arrivedAtWaypoint = true
      state.lastProgressTick = tick
      state.lastWaypointDistance = high(int)
      state.ventAttemptTicks = 0
      let exitedWp = state.currentEdgeTo
      state.currentEdgeIdx = -1
      state.currentEdgeFrom = -1
      state.currentEdgeTo = -1
      if state.strategicPath.len > 0:
        setCurrentEdge(state, graph, exitedWp, state.strategicPath[0])
    elif entryDist <= VentActivationRadius:
      inc state.ventAttemptTicks
      if state.ventAttemptTicks > VentActivationTimeout:
        state.ventPolicy = VentNever
        state.currentGoalValid = false
        replanStrategic(state, graph, belief, selfX, selfY, goalX, goalY, tick)
      else:
        mask = ButtonB
    else:
      setNavError(state, tick, "vent_entry_not_reached")
      state.lastSelfX = selfX
      state.lastSelfY = selfY
      state.lastEmittedMask = 0'u8
      return 0'u8

  # Follow the precomputed path for the current edge
  if state.currentEdgeIdx >= 0 and not graph.edges[state.currentEdgeIdx].isVent:
    let walkIdx = walkingEdgeIndex(graph, state.currentEdgeIdx)
    if walkIdx >= 0 and walkIdx < graph.paths.len:
      let edge = graph.edges[state.currentEdgeIdx]
      let path = graph.paths[walkIdx]
      if path.points.len > 0:
        discard edge
        let forward = pathForward(graph, state.currentEdgeIdx,
                                  state.currentEdgeFrom,
                                  state.currentEdgeTo)
        let look = selectLookahead(path, state.pathProgress,
                                   selfX, selfY, tick, forward)
        state.lastLookahead = look.target
        state.lastLookaheadValid = true
        if look.snapDist > PathSnapRadius:
          if state.currentEdgeFrom >= 0 and
             state.currentEdgeFrom < graph.waypointCount:
            let fromWp = graph.waypoints[state.currentEdgeFrom]
            let fromDist = heuristic(selfX, selfY, fromWp.x, fromWp.y)
            if fromDist <= 100:
              state.navErrorReason = "path_resync_to_edge_start"
              mask = steerButtons(selfX, selfY, fromWp.x, fromWp.y,
                                  state.velocityX, state.velocityY)
            else:
              setNavError(state, tick, "path_snap_too_far")
              state.lastSelfX = selfX
              state.lastSelfY = selfY
              state.lastEmittedMask = 0'u8
              return 0'u8
          else:
            setNavError(state, tick, "path_snap_too_far")
            state.lastSelfX = selfX
            state.lastSelfY = selfY
            state.lastEmittedMask = 0'u8
            return 0'u8
        else:
          if look.newProgress > state.pathProgress:
            state.lastProgressTick = tick
          state.pathProgress = look.newProgress
          state.navErrorReason = ""
          mask = steerButtons(selfX, selfY, look.target.x, look.target.y,
                              state.velocityX, state.velocityY)
    else:
      setNavError(state, tick, "missing_baked_path")
      state.lastSelfX = selfX
      state.lastSelfY = selfY
      state.lastEmittedMask = 0'u8
      return 0'u8

  # With no strategic path remaining, steer toward the exact goal pixel.
  if mask == 0 and state.strategicPath.len == 0:
    state.navErrorReason = ""
    mask = steerButtons(selfX, selfY, goalX, goalY,
                        state.velocityX, state.velocityY)

  # Apply button overrides
  mask = applyJiggle(state, mask)
  addIntentButtons(mask, intent)

  state.lastSelfX = selfX
  state.lastSelfY = selfY
  state.lastEmittedMask = mask
  mask

# ---------------------------------------------------------------------------
# Chat emission (meeting mode)
# ---------------------------------------------------------------------------

proc sanitizeChatText(text: string): string =
  ## Keep the protocol-facing chat packet short and printable ASCII.
  let stripped = text.strip()
  for ch in stripped:
    let o = ord(ch)
    if o >= 32 and o <= 126:
      result.add ch
    if result.len >= MeetingChatMaxLen:
      break

proc emitChat*(state: var ActionState, tick: int, text: string): bool =
  ## Queue one outbound chat line for the Python/WebSocket bridge.
  ## The FFI drain consumes ``pendingChat`` exactly once after the next
  ## ``step_batch``.
  if text.len == 0:
    return false
  if state.pendingChat.len > 0:
    return false
  if tick - state.lastChatTick < MeetingChatLineGapTicks:
    return false
  let clean = sanitizeChatText(text)
  if clean.len == 0:
    return false
  state.pendingChat = clean
  state.lastChatTick = tick
  true
