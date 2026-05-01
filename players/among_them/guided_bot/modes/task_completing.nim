## Mode: `task_completing`. Crewmate default and ghost default.
##
## Picks a target task from visible task icons / radar dots, navigates to
## its world-space station rect, then holds A to complete it. Ghost variant
## skips body reactions and uses straight-line steering (handled by the
## action layer's ghost-aware A*). See DESIGN.md §5.7, §9.1, §12.2.
##
## Task selection strategy (phase 2, no full task-state machine yet):
##   - If a task icon is visible on screen, target the nearest task station
##     whose world rect contains the icon's world position.
##   - If radar dots are visible but no task icons, pick the nearest task
##     station in the direction of a radar dot.
##   - If nothing is visible, hold last known target or wander toward
##     the map centre.
##   - Once at the station rect, switch to DisciplineTaskHold (hold A).
##
## The mode respects `tcAbandonOnNearbyBody` — if true and a body is
## visible, the reflex system (wired in bot.nim) handles switching to
## `reporting` mode. This mode doesn't check bodies itself; it relies on
## the reflex.

import ../types
import ../action
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
                        tcEnterTick: belief.tick)
  discard params

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

# ---------------------------------------------------------------------------
# Task-station helpers
# ---------------------------------------------------------------------------

proc taskStationWorldCenter(ts: TaskStation): (int, int) =
  ## World-space centre of a task station rect.
  (ts.x + ts.w div 2, ts.y + ts.h div 2)

proc isInsideTaskRect(selfX, selfY: int, ts: TaskStation): bool =
  ## True when the player's world position is inside the station rect
  ## (with a small margin for pixel-level imprecision).
  const margin = 4
  selfX >= ts.x - margin and selfX < ts.x + ts.w + margin and
  selfY >= ts.y - margin and selfY < ts.y + ts.h + margin

proc nearestTaskStation(selfX, selfY: int,
                        tasks: openArray[TaskStation]): int =
  ## Index of the nearest task station by Manhattan distance. Returns
  ## -1 if the task list is empty.
  var bestDist = high(int)
  result = -1
  for i, ts in tasks:
    let (cx, cy) = taskStationWorldCenter(ts)
    let d = heuristic(selfX, selfY, cx, cy)
    if d < bestDist:
      bestDist = d
      result = i

proc taskIconWorldX(iconScreenX, cameraX: int): int {.inline.} =
  ## Convert a task-icon screen X to world X.
  cameraX + iconScreenX + SpriteDrawOffX

proc taskIconWorldY(iconScreenY, cameraY: int): int {.inline.} =
  cameraY + iconScreenY + SpriteDrawOffY

proc findTaskForIcon(iconWX, iconWY: int,
                     tasks: openArray[TaskStation]): int =
  ## Find the task station whose rect contains (or is nearest to) the
  ## icon's world position. Returns -1 if none found.
  var bestDist = high(int)
  result = -1
  for i, ts in tasks:
    # Check if icon is inside the task rect (with generous margin —
    # task icons float slightly above the station).
    const margin = 16
    if iconWX >= ts.x - margin and iconWX < ts.x + ts.w + margin and
       iconWY >= ts.y - margin and iconWY < ts.y + ts.h + margin:
      let d = heuristic(iconWX, iconWY, ts.x + ts.w div 2, ts.y + ts.h div 2)
      if d < bestDist:
        bestDist = d
        result = i

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

  # --- Task selection ---
  var targetIdx = scratch.tcLockedTaskIndex

  # Try to pick a target from visible task icons.
  if targetIdx < 0 and belief.percep.visibleTaskIcons.len > 0:
    var bestDist = high(int)
    for icon in belief.percep.visibleTaskIcons:
      let wx = taskIconWorldX(icon.x, belief.percep.cameraX)
      let wy = taskIconWorldY(icon.y, belief.percep.cameraY)
      let ti = findTaskForIcon(wx, wy, tasks)
      if ti >= 0:
        let (cx, cy) = taskStationWorldCenter(tasks[ti])
        let d = heuristic(selfX, selfY, cx, cy)
        if d < bestDist:
          bestDist = d
          targetIdx = ti

  # Fallback: if still no target, pick the nearest station.
  if targetIdx < 0:
    targetIdx = nearestTaskStation(selfX, selfY, tasks)

  # Lock the target so we don't thrash between stations.
  if targetIdx >= 0:
    scratch.tcLockedTaskIndex = targetIdx

  # No task stations at all — idle.
  if targetIdx < 0:
    return noOpIntent()

  let ts = tasks[targetIdx]
  let (goalX, goalY) = taskStationWorldCenter(ts)

  # --- Am I at the task? ---
  if isInsideTaskRect(selfX, selfY, ts):
    # At the station — check if a task icon is visible (confirms we
    # have an active task here). If so, hold A.
    # Even without a visible icon, hold A briefly to try to interact.
    return ActionIntent(
      steerTo: Point(x: goalX, y: goalY),
      steerValid: true,
      pressA: true,
      pressB: false,
      cursor: CursorNone,
      chat: "",
      discipline: DisciplineTaskHold
    )

  # --- Navigate to the task ---
  ActionIntent(
    steerTo: Point(x: goalX, y: goalY),
    steerValid: true,
    pressA: false,
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineNormal
  )
