## Mode: `fleeing`. Imposter just saw a body they didn't make and needs
## to put distance between them and it. Target of the
## `hunting -> fleeing` reflex. See DESIGN.md §5.4, §5.8.
##
## Strategy:
##   - Steer away from `fleeAwayFrom` until `fleeUntilTick` or until
##     the minimum distance is reached.
##   - Uses DisciplineNormal for movement (A* finds a path away).
##   - Once the duration expires or distance is sufficient, the mode
##     becomes idle and the default directive kicks in.

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
                        fleeUntilTick: belief.tick + params.fleeDurationTicks)

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

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
    # Done fleeing — idle until directive reconciliation picks up the
    # default. Return no-op; on the next tick reconcileDirective will
    # check legality (fleeing mode stays legal but the directive TTL
    # will expire, reverting to the default hunting directive).
    return noOpIntent()

  # Compute a flee target: move away from the body. Pick a point on
  # the opposite side of us from the body, clamped to the map.
  let dx = selfX - params.fleeAwayFrom.x
  let dy = selfY - params.fleeAwayFrom.y
  # If we're on top of the body, pick an arbitrary direction.
  var fleeX, fleeY: int
  if dx == 0 and dy == 0:
    fleeX = selfX + 60
    fleeY = selfY
  else:
    # Project further in the flee direction.
    fleeX = selfX + dx * 2
    fleeY = selfY + dy * 2

  # Clamp to map bounds.
  if fleeX < 0: fleeX = 0
  if fleeX >= MapWidth: fleeX = MapWidth - 2
  if fleeY < 0: fleeY = 0
  if fleeY >= MapHeight: fleeY = MapHeight - 2

  ActionIntent(
    steerTo: Point(x: fleeX, y: fleeY),
    steerValid: true,
    pressA: false,
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineNormal
  )
