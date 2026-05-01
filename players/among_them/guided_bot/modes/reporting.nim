## Mode: `reporting`. A body is known; navigate to report range and
## press A. Crewmate only (imposters don't self-report in the default
## fallback — the LLM could issue this in phase 3).
##
## Target of the `task_completing -> reporting` reflex (DESIGN.md §5.8).
## The reflex provides the body's world position in `repBodyLocation`.
##
## Strategy:
##   - Navigate toward the body location using DisciplineReport.
##   - The action layer steers toward the target and presses A when in
##     report range (within ReportRange pixels).

import ../types
import ../action
import ../perception/geometry

const Name* = ModeReporting

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleCrewmate and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeReporting,
             repBodyLocation: Point(x: 0, y: 0))

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeReporting, repEnterTick: belief.tick)
  discard params

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  discard scratch
  let localized = belief.percep.localized

  if not localized:
    return noOpIntent()

  # Navigate toward the body and press A when in range.
  ActionIntent(
    steerTo: params.repBodyLocation,
    steerValid: true,
    pressA: false,  # Action layer handles ButtonA via DisciplineReport.
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineReport
  )
