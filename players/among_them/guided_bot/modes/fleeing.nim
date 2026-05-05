## Mode: `fleeing`. Imposter just saw a body (that they didn't make)
## and needs to put distance between them and it. Target of the
## `hunting -> fleeing` reflex. See DESIGN.md §5.4, §5.8.
##
## Strategy:
##   - Steer away from `fleeAwayFrom` until `fleeUntilTick` or until
##     the minimum distance is reached.
##   - Flee target is snapped to passable terrain so A* gets a valid goal.
##   - Once the duration expires or distance is sufficient, transition to
##     cover behavior: navigate to a nearby task station (away from body)
##     to look like a crewmate working.

import ../types
import ../action
import ../perception/data
import ../perception/geometry

const Name* = ModeFleeing

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleImposter and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeFleeing,
             fleeAwayFrom: Point(x: 0, y: 0),
             fleeMinDistance: 48,
             fleeDurationTicks: 240)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeFleeing,
                        fleeUntilTick: belief.tick + params.fleeDurationTicks,
                        fleeCoverTargetX: 0,
                        fleeCoverTargetY: 0,
                        fleeCoverSet: false)

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

proc pickCoverStation(selfX, selfY: int, awayFrom: Point): (int, int) =
  ## Pick the nearest task station whose passable centre is at least
  ## 24 px from the body and in the "away" hemisphere.
  let tasks = referenceData.map.tasks
  let dx = selfX - awayFrom.x
  let dy = selfY - awayFrom.y
  var bestDist = high(int)
  var bestX = selfX + 60
  var bestY = selfY
  var fallbackDist = high(int)
  var fallbackX = selfX
  var fallbackY = selfY

  for ts in tasks:
    let cx = ts.passableCX
    let cy = ts.passableCY
    let distFromSelf = heuristic(selfX, selfY, cx, cy)
    let distFromBody = heuristic(awayFrom.x, awayFrom.y, cx, cy)

    # Track absolute nearest as fallback.
    if distFromSelf < fallbackDist:
      fallbackDist = distFromSelf
      fallbackX = cx
      fallbackY = cy

    # Prefer stations away from the body.
    if distFromBody < 24:
      continue
    # Dot product: station is in the "away" hemisphere from self.
    let sdx = cx - selfX
    let sdy = cy - selfY
    if dx * sdx + dy * sdy < 0:
      continue
    if distFromSelf < bestDist:
      bestDist = distFromSelf
      bestX = cx
      bestY = cy

  if bestDist < high(int):
    (bestX, bestY)
  else:
    (fallbackX, fallbackY)

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let localized = belief.percep.localized

  if not localized:
    return noOpIntent()

  # Check if we've fled long enough or far enough.
  let dist = heuristic(selfX, selfY,
                       params.fleeAwayFrom.x, params.fleeAwayFrom.y)
  if belief.tick >= scratch.fleeUntilTick or dist >= params.fleeMinDistance:
    # Post-flee cover: navigate to a station away from the body.
    if not scratch.fleeCoverSet:
      scratch.fleeCoverSet = true
      let (cx, cy) = pickCoverStation(selfX, selfY, params.fleeAwayFrom)
      scratch.fleeCoverTargetX = cx
      scratch.fleeCoverTargetY = cy
    return ActionIntent(
      steerTo: Point(x: scratch.fleeCoverTargetX, y: scratch.fleeCoverTargetY),
      steerValid: true,
      pressA: false,
      pressB: false,
      cursor: CursorNone,
      chat: "",
      discipline: DisciplineNormal
    )

  # Compute a flee target: move away from the body.
  let fdx = selfX - params.fleeAwayFrom.x
  let fdy = selfY - params.fleeAwayFrom.y
  var fleeX, fleeY: int
  if fdx == 0 and fdy == 0:
    fleeX = selfX + 60
    fleeY = selfY
  else:
    fleeX = selfX + fdx * 2
    fleeY = selfY + fdy * 2

  # Clamp to map bounds.
  if fleeX < 0: fleeX = 0
  if fleeX >= MapWidth: fleeX = MapWidth - 2
  if fleeY < 0: fleeY = 0
  if fleeY >= MapHeight: fleeY = MapHeight - 2

  # Snap to passable terrain.
  let (found, px, py) = snapToPassable(referenceData.map.walkMask, fleeX, fleeY)
  if found:
    fleeX = px
    fleeY = py

  ActionIntent(
    steerTo: Point(x: fleeX, y: fleeY),
    steerValid: true,
    pressA: false,
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineNormal
  )
