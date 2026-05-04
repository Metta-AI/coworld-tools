## Mode: `task_completing`. Crewmate default and ghost default.
##
## Phase 6.1 rewrite: three-phase hold lifecycle (Navigate → Hold →
## Confirm) with belief-layer task state, tiered target selection,
## and icon-disappearance completion detection.
##
## See TASK_COMPLETING_DESIGN.md for the full design.
##
## Navigate: A* to the target station centre.
## Hold:     Press A for TaskHoldTicks (84) ticks.
## Confirm:  Watch for icon disappearance (24 consecutive miss frames)
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
  ## True when the player's world position is inside the station rect
  ## (with a small margin for pixel-level imprecision).
  const margin = 4
  selfX >= ts.x - margin and selfX < ts.x + ts.w + margin and
  selfY >= ts.y - margin and selfY < ts.y + ts.h + margin

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
  bestDist = high(int)
  bestIdx = -1
  for i in 0 ..< tasks.len:
    if i >= nSlots: break
    let slot = belief.tasks.slots[i]
    if slot.state != TaskCompleted and not slot.resolvedNotMine:
      let (cx, cy) = taskStationWorldCenter(tasks[i])
      let d = heuristic(selfX, selfY, cx, cy)
      if d < bestDist:
        bestDist = d
        bestIdx = i
  if bestIdx >= 0:
    scratch.tcSelectionTier = TierGeometry
    return bestIdx

  -1

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
  const margin = 16
  for icon in belief.percep.visibleTaskIcons:
    let wx = camX + icon.x + SpriteDrawOffX
    let wy = camY + icon.y + SpriteDrawOffY
    if wx >= station.x - margin and wx < station.x + station.w + margin and
       wy >= station.y - margin and wy < station.y + station.h + margin:
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

  # Check if locked target is still valid.
  if targetIdx >= 0 and targetIdx < belief.tasks.slots.len:
    let slot = belief.tasks.slots[targetIdx]
    if slot.state == TaskCompleted or slot.resolvedNotMine:
      # Target is done or pruned — unlock immediately.
      targetIdx = -1
      scratch.tcLockedTaskIndex = -1
      scratch.tcPhase = TpNavigate

  # If in Navigate with no target, run selection.
  if targetIdx < 0:
    scratch.tcPhase = TpNavigate
    targetIdx = selectTarget(belief, scratch)
    if targetIdx >= 0:
      scratch.tcLockedTaskIndex = targetIdx
      scratch.tcLockTick = belief.tick

  # Hysteresis: if we have a target and the commit window hasn't
  # expired, keep it even if a better one appeared. If committed
  # long enough, allow re-evaluation on next Navigate entry.

  # No target at all — idle.
  if targetIdx < 0:
    return noOpIntent()

  let ts = tasks[targetIdx]
  let (goalX, goalY) = taskStationWorldCenter(ts)

  # =======================================================================
  # Phase: CONFIRM
  # =======================================================================
  if scratch.tcPhase == TpConfirm:
    # Check icon visibility for miss counting.
    if iconVisibleAtStation(belief, targetIdx):
      scratch.tcConfirmMissCount = 0
    else:
      scratch.tcConfirmMissCount += 1

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
