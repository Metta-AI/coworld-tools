## Mode: `task_completing`. Crewmate default and ghost default.
##
## Phase 6.1 rewrite: three-phase hold lifecycle (Navigate → Hold →
## Confirm) with belief-layer task state, tiered target selection,
## and icon-disappearance completion detection.
##
## See TASK_COMPLETING_DESIGN.md for the full design.
##
## Navigate: A* to the target station centre.
## Hold:     Press A for TaskHoldTicks (74) ticks.
## Confirm:  Watch for icon disappearance (4 consecutive miss frames)
##           or timeout (TaskConfirmWindowTicks = 48).
##
## Target selection uses a three-tier priority system:
##   1. Icon-visible stations (TaskConfirmed in belief.tasks).
##   2. Checkout-latched stations (radar-dot evidence).
##   3. Unresolved stations (nearest by geometry).
##
## The mode respects `tcAbandonOnNearbyBody` — if true and a body is
## visible, the reflex system (wired in bot.nim) handles switching to
## `reporting` mode. This mode doesn't check bodies itself; it relies
## on the reflex.

import std/json
import ../types
import ../action
import ../tuning
import ../perception/data
import ../perception/geometry

const Name* = ModeTaskCompleting

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleCrewmate or belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  var tgt = TaskTarget(kind: TgtNearestMandatory, taskIndex: -1, roomId: -1)
  ModeParams(mode: ModeTaskCompleting,
             tcTarget: tgt,
             tcAbandonOnNearbyBody: not belief.self.isGhost)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeTaskCompleting,
                        tcLockedTaskIndex: -1,
                        tcEnterTick: belief.tick,
                        tcPhase: TpNavigate,
                        tcHoldRemaining: 0,
                        tcHoldStartTick: 0,
                        tcConfirmDeadlineTick: 0,
                        tcConfirmMissCount: 0,
                        tcCompletedTaskIndex: -1,
                        tcLockTick: 0,
                        tcLastReEvalTick: 0,
                        tcLockedTier: TierGeometry,
                        tcSelectionTier: TierGeometry)
  discard params

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

# ---------------------------------------------------------------------------
# Task-station helpers
# ---------------------------------------------------------------------------

proc taskStationWorldCenter(ts: TaskStation): (int, int) =
  ## Passable world-space centre of a task station. Uses the
  ## precomputed walk-mask-snapped coordinates so A* never receives
  ## an impassable goal.
  (ts.passableCX, ts.passableCY)

proc isInsideTaskRect(selfX, selfY: int, ts: TaskStation): bool =
  ## True when the player's world position is inside the station rect.
  ## Must match the server's exact check (sim.nim:2184-2185): no margin.
  selfX >= ts.x and selfX < ts.x + ts.w and
  selfY >= ts.y and selfY < ts.y + ts.h

proc completedTaskCount(belief: Belief): int =
  for slot in belief.tasks.slots:
    if slot.state == TaskCompleted:
      inc result

proc hasLiveTaskEvidence(belief: Belief): bool =
  if belief.percep.visibleTaskIcons.len > 0 or belief.percep.radarDots.len > 0:
    return true
  for slot in belief.tasks.slots:
    if slot.state == TaskConfirmed or slot.state == TaskCheckout:
      return true
  false

proc bodyEvidenceScore(ps: PlayerSummary): int =
  if ps.nearBodyEvidenceScore > 0:
    ps.nearBodyEvidenceScore
  else:
    ps.timesNearBody * MeetingBodyEvidenceMaxStrength

proc crewButtonEvidenceScore(ps: PlayerSummary): int =
  if not ps.alive:
    return 0
  if ps.role == RoleImposter:
    result += 100
  result += ps.timesWitnessedKill * 20
  result += ps.timesWitnessedVent * 50
  result += ps.nearVentEvidenceScore
  result += ps.bodyEvidenceScore

proc bestCrewButtonEvidence(belief: Belief): int =
  for color in 0 ..< PlayerColorCount:
    if color == belief.self.colorIndex:
      continue
    result = max(result, belief.memory.perPlayer[color].crewButtonEvidenceScore)

proc buttonPoint(): Point =
  let button = referenceData.map.button
  Point(x: button.x + button.w div 2, y: button.y + button.h div 2)

proc closestVisibleCrewmate(belief: Belief): tuple[found: bool, point: Point] =
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  var bestDist = high(int)
  result = (false, Point(x: 0, y: 0))
  for cm in belief.percep.visibleCrewmates:
    if cm.colorIndex >= 0 and cm.colorIndex == belief.self.colorIndex:
      continue
    let wx = visibleCrewmateWorldX(belief.percep.cameraX, cm.x)
    let wy = visibleCrewmateWorldY(belief.percep.cameraY, cm.y)
    let d = heuristic(selfX, selfY, wx, wy)
    if d < bestDist:
      bestDist = d
      result = (true, Point(x: wx, y: wy))

proc shouldUsePostTaskCrewBehavior(belief: Belief): bool =
  belief.self.role == RoleCrewmate and
    belief.self.alive and
    not belief.self.isGhost and
    belief.completedTaskCount >= CrewPostTaskCompleteCount and
    not belief.hasLiveTaskEvidence

proc postTaskCrewIntent(belief: Belief): ActionIntent =
  let evidence = belief.bestCrewButtonEvidence
  var target = buttonPoint()
  var pressA = false

  if evidence >= CrewButtonEvidenceThreshold:
    let dist = heuristic(belief.percep.selfX, belief.percep.selfY,
                         target.x, target.y)
    pressA = dist <= CrewButtonRange
  else:
    let shadow = closestVisibleCrewmate(belief)
    if shadow.found:
      target = shadow.point

  ActionIntent(
    steerTo: target,
    steerValid: true,
    pressA: pressA,
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineNormal)

# ---------------------------------------------------------------------------
# Target selection (3-tier, per TASK_COMPLETING_DESIGN.md §6)
# ---------------------------------------------------------------------------

proc selectTarget(belief: Belief,
                  scratch: var ModeScratch): int =
  ## Pick a target task station using tiered priority. Returns the
  ## station index, or -1 if no candidates. Sets scratch.tcSelectionTier.
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let tasks = referenceData.map.tasks
  let nSlots = belief.tasks.slots.len

  # Tier 1: icon-visible (TaskConfirmed).
  var bestDist = high(int)
  var bestIdx = -1
  for i in 0 ..< tasks.len:
    if i >= nSlots: break
    let slot = belief.tasks.slots[i]
    if slot.state == TaskConfirmed and not slot.resolvedNotMine:
      let (cx, cy) = taskStationWorldCenter(tasks[i])
      let d = heuristic(selfX, selfY, cx, cy)
      if d < bestDist:
        bestDist = d
        bestIdx = i
  if bestIdx >= 0:
    scratch.tcSelectionTier = TierIcon
    return bestIdx

  # Tier 2: checkout-latched (radar evidence).
  bestDist = high(int)
  bestIdx = -1
  for i in 0 ..< tasks.len:
    if i >= nSlots: break
    let slot = belief.tasks.slots[i]
    if slot.checkout and slot.state != TaskCompleted and not slot.resolvedNotMine:
      let (cx, cy) = taskStationWorldCenter(tasks[i])
      let d = heuristic(selfX, selfY, cx, cy)
      if d < bestDist:
        bestDist = d
        bestIdx = i
  if bestIdx >= 0:
    scratch.tcSelectionTier = TierCheckout
    return bestIdx

  # Tier 3: unresolved stations (geometry fallback).
  # Skip tasks soft-excluded by this frame's radar-ray evidence.
  bestDist = high(int)
  bestIdx = -1
  for i in 0 ..< tasks.len:
    if i >= nSlots: break
    let slot = belief.tasks.slots[i]
    if slot.state != TaskCompleted and not slot.resolvedNotMine and
       not slot.radarRayExcluded:
      let (cx, cy) = taskStationWorldCenter(tasks[i])
      let d = heuristic(selfX, selfY, cx, cy)
      if d < bestDist:
        bestDist = d
        bestIdx = i
  if bestIdx >= 0:
    scratch.tcSelectionTier = TierGeometry
    return bestIdx

  -1

proc stationAvailable(belief: Belief, idx: int): bool =
  let tasks = referenceData.map.tasks
  if idx < 0 or idx >= tasks.len or idx >= belief.tasks.slots.len:
    return false
  let slot = belief.tasks.slots[idx]
  slot.state != TaskCompleted and not slot.resolvedNotMine

proc taskInRoom(idx, roomId: int): bool =
  let map = referenceData.map
  if idx < 0 or idx >= map.tasks.len or roomId < 0 or roomId >= map.rooms.len:
    return false
  let ts = map.tasks[idx]
  roomNameAt(map, ts.passableCX, ts.passableCY) == map.rooms[roomId].name

proc nearestAvailableTask(belief: Belief, roomId: int = -1): int =
  let tasks = referenceData.map.tasks
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  var bestDist = high(int)
  result = -1
  for i, ts in tasks:
    if not belief.stationAvailable(i):
      continue
    if roomId >= 0 and not taskInRoom(i, roomId):
      continue
    let d = heuristic(selfX, selfY, ts.passableCX, ts.passableCY)
    if d < bestDist:
      bestDist = d
      result = i

proc directiveTargetIndex(belief: Belief, params: ModeParams): int =
  ## Return an LLM-directed target station, or -1 to use the local tiered
  ## selector. `nearest_mandatory` deliberately keeps the existing task
  ## evidence tiers as the mandatory-task policy.
  case params.tcTarget.kind
  of TgtIndex:
    if belief.stationAvailable(params.tcTarget.taskIndex):
      params.tcTarget.taskIndex
    else:
      -1
  of TgtSpecificRoom:
    belief.nearestAvailableTask(params.tcTarget.roomId)
  of TgtNearestAny:
    belief.nearestAvailableTask()
  of TgtNearestMandatory:
    -1

proc shouldSwitch(belief: Belief,
                  currentIdx: int,
                  currentTier: TaskSelectionTier,
                  candidateIdx: int,
                  candidateTier: TaskSelectionTier): bool =
  ## True when a post-hysteresis candidate is strong enough to replace
  ## the locked target without causing oscillation.
  if candidateIdx < 0 or candidateIdx == currentIdx:
    return false
  if ord(candidateTier) < ord(currentTier):
    return true
  if candidateTier != currentTier:
    return false

  let tasks = referenceData.map.tasks
  if currentIdx < 0 or currentIdx >= tasks.len or
     candidateIdx < 0 or candidateIdx >= tasks.len:
    return false

  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let (currentX, currentY) = taskStationWorldCenter(tasks[currentIdx])
  let (candidateX, candidateY) = taskStationWorldCenter(tasks[candidateIdx])
  let currentDist = heuristic(selfX, selfY, currentX, currentY)
  let candidateDist = heuristic(selfX, selfY, candidateX, candidateY)
  float(candidateDist) < float(currentDist) * TaskSwitchDistanceRatio

# ---------------------------------------------------------------------------
# Icon-match check for Confirm phase
# ---------------------------------------------------------------------------

proc iconVisibleAtStation(belief: Belief, stationIdx: int): bool =
  ## True if any visible task icon matches the locked station.
  let tasks = referenceData.map.tasks
  if stationIdx < 0 or stationIdx >= tasks.len:
    return false
  let station = tasks[stationIdx]
  let camX = belief.percep.cameraX
  let camY = belief.percep.cameraY
  const tolerance = 2
  let expectedX = station.x + station.w div 2 - SpriteSize div 2 - camX
  let expectedY = station.y - SpriteSize - 2 - camY
  for icon in belief.percep.visibleTaskIcons:
    if abs(icon.x - expectedX) <= tolerance and
       abs(icon.y - expectedY) <= tolerance:
      return true
  false

# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let localized = belief.percep.localized
  let tasks = referenceData.map.tasks

  # If not localized yet, emit no-op and wait for the localizer.
  if not localized or tasks.len == 0:
    return noOpIntent()

  # Clear the completion signal (bot.nim reads and applies this).
  scratch.tcCompletedTaskIndex = -1

  # --- Target selection / hysteresis ---
  var targetIdx = scratch.tcLockedTaskIndex
  let directiveTarget = directiveTargetIndex(belief, params)
  let hasDirectiveTarget = directiveTarget >= 0

  # Check if locked target is still valid.
  if targetIdx >= 0 and targetIdx < belief.tasks.slots.len:
    let slot = belief.tasks.slots[targetIdx]
    if slot.state == TaskCompleted or slot.resolvedNotMine:
      # Target is done or pruned — unlock immediately.
      targetIdx = -1
      scratch.tcLockedTaskIndex = -1
      scratch.tcPhase = TpNavigate

  if belief.shouldUsePostTaskCrewBehavior:
    scratch.tcLockedTaskIndex = -1
    scratch.tcPhase = TpNavigate
    return postTaskCrewIntent(belief)

  # Commit hysteresis: keep current target for at least TaskCommitTicks
  # after locking. Prevents target oscillation from small position changes.
  if hasDirectiveTarget and targetIdx != directiveTarget:
    targetIdx = directiveTarget
    scratch.tcLockedTaskIndex = targetIdx
    scratch.tcLockTick = belief.tick
    scratch.tcLockedTier = TierGeometry
    scratch.tcSelectionTier = TierGeometry
    scratch.tcPhase = TpNavigate
  elif targetIdx >= 0 and
       belief.tick - scratch.tcLockTick < TaskCommitTicks:
    discard  # Hold current target; skip re-selection.
  elif targetIdx < 0:
    scratch.tcPhase = TpNavigate
    if hasDirectiveTarget:
      targetIdx = directiveTarget
      scratch.tcSelectionTier = TierGeometry
    else:
      targetIdx = selectTarget(belief, scratch)
    if targetIdx >= 0:
      scratch.tcLockedTaskIndex = targetIdx
      scratch.tcLockTick = belief.tick
      scratch.tcLockedTier = scratch.tcSelectionTier
  elif not hasDirectiveTarget:
    if scratch.tcPhase == TpNavigate and
       belief.tick - scratch.tcLastReEvalTick >= TaskReEvalPeriodTicks:
      scratch.tcLastReEvalTick = belief.tick
      let currentTier = scratch.tcLockedTier
      let candidateIdx = selectTarget(belief, scratch)
      let candidateTier = scratch.tcSelectionTier
      if shouldSwitch(belief, targetIdx, currentTier, candidateIdx, candidateTier):
        targetIdx = candidateIdx
        scratch.tcLockedTaskIndex = targetIdx
        scratch.tcLockTick = belief.tick
        scratch.tcPhase = TpNavigate
        scratch.tcLockedTier = candidateTier
        scratch.tcSelectionTier = candidateTier
      else:
        scratch.tcSelectionTier = scratch.tcLockedTier

  # No target at all — idle.
  if targetIdx < 0:
    return noOpIntent()

  let ts = tasks[targetIdx]
  let (goalX, goalY) = taskStationWorldCenter(ts)

  # --- Hold/Confirm displacement guard ---
  # If we're in Hold but no longer inside the task rect (meeting relocated us),
  # abandon the hold and return to Navigate.
  if scratch.tcPhase == TpHold and not isInsideTaskRect(selfX, selfY, ts):
    scratch.tcPhase = TpNavigate
    scratch.tcLockedTaskIndex = -1
    let newTarget = selectTarget(belief, scratch)
    if newTarget >= 0:
      scratch.tcLockedTaskIndex = newTarget
      scratch.tcLockTick = belief.tick
      scratch.tcLockedTier = scratch.tcSelectionTier
      let newTs = tasks[newTarget]
      let (nx, ny) = taskStationWorldCenter(newTs)
      return ActionIntent(
        steerTo: Point(x: nx, y: ny),
        steerValid: true,
        pressA: false, pressB: false,
        cursor: CursorNone, chat: "",
        discipline: DisciplineNormal)
    return noOpIntent()

  # =======================================================================
  # Phase: CONFIRM
  # =======================================================================
  if scratch.tcPhase == TpConfirm:
    let (cx, cy) = taskStationWorldCenter(ts)
    let confirmDist = heuristic(selfX, selfY, cx, cy)

    # If relocated far from station (e.g. meeting), abandon confirm.
    if confirmDist > TaskConfirmMaxDistance:
      scratch.tcLockedTaskIndex = -1
      scratch.tcPhase = TpNavigate
      let newTarget = selectTarget(belief, scratch)
      if newTarget >= 0:
        scratch.tcLockedTaskIndex = newTarget
        scratch.tcLockTick = belief.tick
        scratch.tcLockedTier = scratch.tcSelectionTier
        let newTs = tasks[newTarget]
        let (nx, ny) = taskStationWorldCenter(newTs)
        return ActionIntent(
          steerTo: Point(x: nx, y: ny),
          steerValid: true,
          pressA: false, pressB: false,
          cursor: CursorNone, chat: "",
          discipline: DisciplineNormal)
      return noOpIntent()

    # Only count icon misses when the station is actually on-screen.
    let camX = belief.percep.cameraX
    let camY = belief.percep.cameraY
    if taskIconOnScreen(ts, camX, camY, TaskClearScreenMargin):
      if iconVisibleAtStation(belief, targetIdx):
        scratch.tcConfirmMissCount = 0
      else:
        scratch.tcConfirmMissCount += 1
    # Else: station off-screen, don't count misses (absence is uninformative).

    # Completion: icon absent for enough consecutive frames.
    if scratch.tcConfirmMissCount >= TaskIconMissCompleteTicks:
      scratch.tcCompletedTaskIndex = targetIdx
      scratch.tcLockedTaskIndex = -1
      scratch.tcPhase = TpNavigate
      # Re-select on same tick (Navigate will pick a new target).
      let newTarget = selectTarget(belief, scratch)
      if newTarget >= 0:
        scratch.tcLockedTaskIndex = newTarget
        scratch.tcLockTick = belief.tick
        scratch.tcLockedTier = scratch.tcSelectionTier
        let newTs = tasks[newTarget]
        let (nx, ny) = taskStationWorldCenter(newTs)
        return ActionIntent(
          steerTo: Point(x: nx, y: ny),
          steerValid: true,
          pressA: false, pressB: false,
          cursor: CursorNone, chat: "",
          discipline: DisciplineNormal)
      return noOpIntent()

    # Timeout: confirm window expired without enough misses.
    if belief.tick >= scratch.tcConfirmDeadlineTick:
      # Clear checkout latch — the task may not be ours.
      if targetIdx < belief.tasks.slots.len:
        # Note: we can't write belief directly (invariant). The bot
        # pipeline will handle this via tcCompletedTaskIndex = -1
        # (no completion). But we DO need to clear checkout — use
        # a sentinel to signal the bot pipeline. For now, we clear
        # the lock and re-select. The belief-layer's iconMissCount
        # will naturally accumulate if we revisit this station.
        discard
      scratch.tcLockedTaskIndex = -1
      scratch.tcPhase = TpNavigate
      let newTarget = selectTarget(belief, scratch)
      if newTarget >= 0:
        scratch.tcLockedTaskIndex = newTarget
        scratch.tcLockTick = belief.tick
        scratch.tcLockedTier = scratch.tcSelectionTier
        let newTs = tasks[newTarget]
        let (nx, ny) = taskStationWorldCenter(newTs)
        return ActionIntent(
          steerTo: Point(x: nx, y: ny),
          steerValid: true,
          pressA: false, pressB: false,
          cursor: CursorNone, chat: "",
          discipline: DisciplineNormal)
      return noOpIntent()

    # Still confirming — stay still, no buttons.
    return ActionIntent(
      steerTo: Point(x: goalX, y: goalY),
      steerValid: true,
      pressA: false, pressB: false,
      cursor: CursorNone, chat: "",
      discipline: DisciplineNoOp)

  # =======================================================================
  # Phase: HOLD
  # =======================================================================
  if scratch.tcPhase == TpHold:
    scratch.tcHoldRemaining -= 1
    if scratch.tcHoldRemaining <= 0:
      # Transition to Confirm.
      scratch.tcPhase = TpConfirm
      scratch.tcConfirmDeadlineTick = belief.tick + TaskConfirmWindowTicks
      scratch.tcConfirmMissCount = 0
      # First Confirm tick: stay still, watch.
      return ActionIntent(
        steerTo: Point(x: goalX, y: goalY),
        steerValid: true,
        pressA: false, pressB: false,
        cursor: CursorNone, chat: "",
        discipline: DisciplineNoOp)

    # Still holding — press A.
    return ActionIntent(
      steerTo: Point(x: goalX, y: goalY),
      steerValid: true,
      pressA: true, pressB: false,
      cursor: CursorNone, chat: "",
      discipline: DisciplineTaskHold)

  # =======================================================================
  # Phase: NAVIGATE (default)
  # =======================================================================

  # Am I at the task station?
  if isInsideTaskRect(selfX, selfY, ts):
    # Transition to Hold.
    scratch.tcPhase = TpHold
    scratch.tcHoldRemaining = TaskHoldTicks
    scratch.tcHoldStartTick = belief.tick
    # First Hold tick: press A.
    return ActionIntent(
      steerTo: Point(x: goalX, y: goalY),
      steerValid: true,
      pressA: true, pressB: false,
      cursor: CursorNone, chat: "",
      discipline: DisciplineTaskHold)

  # Navigate to the task.
  ActionIntent(
    steerTo: Point(x: goalX, y: goalY),
    steerValid: true,
    pressA: false, pressB: false,
    cursor: CursorNone, chat: "",
    discipline: DisciplineNormal)

proc taskPhaseStr(phase: TaskPhase): string =
  case phase
  of TpNavigate: "navigate"
  of TpHold: "hold"
  of TpConfirm: "confirm"

proc taskTierStr(tier: TaskSelectionTier): string =
  case tier
  of TierIcon: "icon"
  of TierCheckout: "checkout"
  of TierGeometry: "geometry"

proc taskTargetKindStr(kind: TaskTargetKind): string =
  case kind
  of TgtIndex: "index"
  of TgtNearestMandatory: "nearest_mandatory"
  of TgtNearestAny: "nearest_any"
  of TgtSpecificRoom: "specific_room"

proc summarizeForLlm*(belief: Belief, params: ModeParams,
                      scratch: ModeScratch): JsonNode =
  result = newJObject()
  result["status"] = newJString("navigating_or_completing_tasks")
  result["phase"] = newJString(taskPhaseStr(scratch.tcPhase))
  result["directive_target_kind"] =
    newJString(taskTargetKindStr(params.tcTarget.kind))
  if params.tcTarget.kind == TgtIndex:
    result["directive_task_index"] = newJInt(params.tcTarget.taskIndex)
  elif params.tcTarget.kind == TgtSpecificRoom:
    result["directive_room_id"] = newJInt(params.tcTarget.roomId)
  result["abandon_on_nearby_body"] =
    newJBool(params.tcAbandonOnNearbyBody)
  result["locked_task_index"] = newJInt(scratch.tcLockedTaskIndex)
  result["locked_tier"] = newJString(taskTierStr(scratch.tcLockedTier))
  result["selection_tier"] = newJString(taskTierStr(scratch.tcSelectionTier))
  result["completed_task_count"] = newJInt(belief.completedTaskCount)
  result["live_task_evidence"] = newJBool(belief.hasLiveTaskEvidence)
  result["post_task_crew_behavior"] =
    newJBool(belief.shouldUsePostTaskCrewBehavior)
  result["best_button_evidence"] = newJInt(belief.bestCrewButtonEvidence)
  if scratch.tcLockedTaskIndex >= 0 and
     scratch.tcLockedTaskIndex < referenceData.map.tasks.len:
    let ts = referenceData.map.tasks[scratch.tcLockedTaskIndex]
    result["locked_task_name"] = newJString(ts.name)
    result["locked_task_room"] =
      newJString(roomNameAt(referenceData.map, ts.passableCX, ts.passableCY))
  result["ticks_in_mode"] = newJInt(max(0, belief.tick - scratch.tcEnterTick))
  if scratch.tcPhase == TpHold:
    result["hold_ticks_remaining"] = newJInt(scratch.tcHoldRemaining)
    result["hold_ticks_elapsed"] =
      newJInt(max(0, belief.tick - scratch.tcHoldStartTick))
  if scratch.tcPhase == TpConfirm:
    result["confirm_ticks_remaining"] =
      newJInt(max(0, scratch.tcConfirmDeadlineTick - belief.tick))
    result["confirm_icon_miss_count"] = newJInt(scratch.tcConfirmMissCount)
