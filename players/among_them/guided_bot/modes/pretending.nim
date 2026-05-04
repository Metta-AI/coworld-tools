## Mode: `pretending`. Imposter walking task-to-task without actually
## doing them. Loiters at each station for a configurable duration to
## look like a crewmate working.
##
## Target of the `pretending -> hunting` reflex when a lone kill
## opportunity appears (DESIGN.md §5.8).
##
## Strategy:
##   - Pick a task station to walk to (nearest, or random-ish rotation).
##   - Navigate there using DisciplineNormal.
##   - On arrival, loiter (emit no-op or idle steer) for `preLoiterTicks`.
##   - After loiter, pick a new station and repeat.

import ../types
import ../action
import ../perception/data
import ../perception/geometry

const Name* = ModePretending

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleImposter and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  var tgt = TaskTarget(kind: TgtNearestAny, taskIndex: -1, roomId: -1)
  ModeParams(mode: ModePretending,
             preTarget: tgt,
             preLoiterTicks: 96,
             preMaySwapOnWitness: true)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModePretending,
                        preFakeTargetIndex: -1,
                        preLoiterUntilTick: 0,
                        preEnterTick: belief.tick)
  discard params

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let localized = belief.percep.localized
  let tasks = referenceData.map.tasks

  if not localized or tasks.len == 0:
    return noOpIntent()

  # --- Loitering at a station ---
  if scratch.preLoiterUntilTick > 0 and belief.tick < scratch.preLoiterUntilTick:
    # Still loitering — idle in place.
    return noOpIntent()

  # Done loitering (or never started). Pick a new target.
  if scratch.preLoiterUntilTick > 0 and belief.tick >= scratch.preLoiterUntilTick:
    # Loiter finished — invalidate target to pick a new one.
    scratch.preFakeTargetIndex = -1
    scratch.preLoiterUntilTick = 0

  # --- Pick a target ---
  if scratch.preFakeTargetIndex < 0:
    # Simple rotation: pick a station based on tick to get variety.
    # Avoid picking the same one we just left by offsetting from the
    # last target.
    let offset = (belief.tick div 100) mod tasks.len
    var bestDist = high(int)
    var bestIdx = offset
    for i in 0 ..< tasks.len:
      let idx = (offset + i) mod tasks.len
      let ts = tasks[idx]
      let cx = ts.passableCX
      let cy = ts.passableCY
      let d = heuristic(selfX, selfY, cx, cy)
      # Pick a station that's not too close (we just left one) and
      # not too far (stay efficient).
      if d > 30 and d < bestDist:
        bestDist = d
        bestIdx = idx
    scratch.preFakeTargetIndex = bestIdx

  let ti = scratch.preFakeTargetIndex
  let ts = tasks[ti]
  let goalX = ts.passableCX
  let goalY = ts.passableCY

  # --- Am I at the station? ---
  const margin = 8
  if selfX >= ts.x - margin and selfX < ts.x + ts.w + margin and
     selfY >= ts.y - margin and selfY < ts.y + ts.h + margin:
    # Arrived — start loitering.
    scratch.preLoiterUntilTick = belief.tick + params.preLoiterTicks
    return noOpIntent()

  # --- Navigate to station ---
  ActionIntent(
    steerTo: Point(x: goalX, y: goalY),
    steerValid: true,
    pressA: false,
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineNormal
  )
