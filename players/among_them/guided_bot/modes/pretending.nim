## Mode: `pretending`. Imposter walking task-to-task without actually
## doing them. Loiters at each station with a fake A-press to look
## like a crewmate working.
##
## Target of the `pretending -> hunting` reflex when a lone kill
## opportunity appears (DESIGN.md §5.8).
##
## Strategy:
##   - Pick a task station to walk to (nearest, or random-ish rotation).
##   - Navigate there using DisciplineNormal.
##   - On arrival, fake-hold A for PreFakeHoldTicks (mimics task work).
##   - Then linger briefly (no-op) before picking a new station.
##   - If a crewmate appears during loiter and preMaySwapOnWitness is
##     true, end loiter early and re-select a new station.

import ../types
import ../tuning
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
  discard params
  scratch = ModeScratch(mode: ModePretending,
                        preFakeTargetIndex: -1,
                        preLoiterUntilTick: 0,
                        preFakeHoldUntilTick: 0,
                        preWitnessSwapped: false,
                        preEnterTick: belief.tick)

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

  # --- Loitering (fake-hold + linger) ---
  if scratch.preLoiterUntilTick > 0 and belief.tick < scratch.preLoiterUntilTick:
    # Witness swap: if a crewmate appears, leave early.
    if params.preMaySwapOnWitness and
       not scratch.preWitnessSwapped and
       belief.percep.visibleCrewmates.len > 0:
      scratch.preWitnessSwapped = true
      scratch.preFakeTargetIndex = -1
      scratch.preLoiterUntilTick = 0
      scratch.preFakeHoldUntilTick = 0
      # Fall through to target selection below.
    else:
      # Sub-phase: fake-hold or linger?
      if belief.tick < scratch.preFakeHoldUntilTick:
        return ActionIntent(
          steerTo: Point(x: 0, y: 0),
          steerValid: false,
          pressA: true,
          pressB: false,
          cursor: CursorNone,
          chat: "",
          discipline: DisciplineTaskHold
        )
      else:
        return noOpIntent()

  # Done loitering (or never started). Pick a new target.
  if scratch.preLoiterUntilTick > 0 and belief.tick >= scratch.preLoiterUntilTick:
    scratch.preFakeTargetIndex = -1
    scratch.preLoiterUntilTick = 0
    scratch.preFakeHoldUntilTick = 0
    scratch.preWitnessSwapped = false

  # --- Pick a target ---
  if scratch.preFakeTargetIndex < 0:
    let offset = (belief.tick div 100) mod tasks.len
    var bestDist = high(int)
    var bestIdx = offset
    for i in 0 ..< tasks.len:
      let idx = (offset + i) mod tasks.len
      let ts = tasks[idx]
      let cx = ts.passableCX
      let cy = ts.passableCY
      let d = heuristic(selfX, selfY, cx, cy)
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
    # Arrived — start loitering with fake-hold.
    scratch.preLoiterUntilTick = belief.tick + params.preLoiterTicks
    let holdDuration = min(PreFakeHoldTicks, params.preLoiterTicks)
    scratch.preFakeHoldUntilTick = belief.tick + holdDuration
    scratch.preWitnessSwapped = false
    return ActionIntent(
      steerTo: Point(x: 0, y: 0),
      steerValid: false,
      pressA: true,
      pressB: false,
      cursor: CursorNone,
      chat: "",
      discipline: DisciplineTaskHold
    )

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
