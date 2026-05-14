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

import std/json
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

proc taskInRoom(idx, roomId: int): bool =
  let map = referenceData.map
  if idx < 0 or idx >= map.tasks.len or roomId < 0 or roomId >= map.rooms.len:
    return false
  let ts = map.tasks[idx]
  roomNameAt(map, ts.passableCX, ts.passableCY) == map.rooms[roomId].name

proc nearestTask(selfX, selfY: int, roomId: int = -1,
                 excludeClose = true): int =
  let tasks = referenceData.map.tasks
  var bestDist = high(int)
  result = -1
  for i, ts in tasks:
    if roomId >= 0 and not taskInRoom(i, roomId):
      continue
    let d = heuristic(selfX, selfY, ts.passableCX, ts.passableCY)
    if excludeClose and d <= 30:
      continue
    if d < bestDist:
      bestDist = d
      result = i

proc targetFromParams(belief: Belief, params: ModeParams): int =
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let tasks = referenceData.map.tasks
  case params.preTarget.kind
  of TgtIndex:
    if params.preTarget.taskIndex >= 0 and
       params.preTarget.taskIndex < tasks.len:
      params.preTarget.taskIndex
    else:
      -1
  of TgtSpecificRoom:
    nearestTask(selfX, selfY, params.preTarget.roomId, excludeClose = false)
  of TgtNearestMandatory, TgtNearestAny:
    let far = nearestTask(selfX, selfY)
    if far >= 0: far else: nearestTask(selfX, selfY, excludeClose = false)

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let localized = belief.percep.localized
  let tasks = referenceData.map.tasks

  if not localized or tasks.len == 0:
    return noOpIntent()

  let forcedTarget =
    params.preTarget.kind == TgtIndex or params.preTarget.kind == TgtSpecificRoom
  if forcedTarget:
    let target = targetFromParams(belief, params)
    if target >= 0 and scratch.preFakeTargetIndex != target:
      scratch.preFakeTargetIndex = target
      scratch.preLoiterUntilTick = 0
      scratch.preFakeHoldUntilTick = 0
      scratch.preWitnessSwapped = false

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
    scratch.preFakeTargetIndex = targetFromParams(belief, params)

  if scratch.preFakeTargetIndex < 0:
    return noOpIntent()

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

proc taskTargetKindStr(kind: TaskTargetKind): string =
  case kind
  of TgtIndex: "index"
  of TgtNearestMandatory: "nearest_mandatory"
  of TgtNearestAny: "nearest_any"
  of TgtSpecificRoom: "specific_room"

proc summarizeForLlm*(belief: Belief, params: ModeParams,
                      scratch: ModeScratch): JsonNode =
  result = newJObject()
  result["status"] = newJString("faking_tasks_for_cover")
  result["directive_target_kind"] =
    newJString(taskTargetKindStr(params.preTarget.kind))
  if params.preTarget.kind == TgtIndex:
    result["directive_task_index"] = newJInt(params.preTarget.taskIndex)
  elif params.preTarget.kind == TgtSpecificRoom:
    result["directive_room_id"] = newJInt(params.preTarget.roomId)
  result["loiter_ticks_requested"] = newJInt(params.preLoiterTicks)
  result["may_swap_on_witness"] = newJBool(params.preMaySwapOnWitness)
  result["fake_target_index"] = newJInt(scratch.preFakeTargetIndex)
  if scratch.preFakeTargetIndex >= 0 and
     scratch.preFakeTargetIndex < referenceData.map.tasks.len:
    let ts = referenceData.map.tasks[scratch.preFakeTargetIndex]
    result["fake_target_name"] = newJString(ts.name)
    result["fake_target_room"] =
      newJString(roomNameAt(referenceData.map, ts.passableCX, ts.passableCY))
  result["ticks_in_mode"] = newJInt(max(0, belief.tick - scratch.preEnterTick))
  result["loiter_ticks_remaining"] =
    newJInt(max(0, scratch.preLoiterUntilTick - belief.tick))
  result["fake_hold_ticks_remaining"] =
    newJInt(max(0, scratch.preFakeHoldUntilTick - belief.tick))
  result["witness_swap_used"] = newJBool(scratch.preWitnessSwapped)
