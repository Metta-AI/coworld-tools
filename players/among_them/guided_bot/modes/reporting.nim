## Mode: `reporting`. A body is known; navigate to report range and
## press A. Crewmate only (imposters don't self-report).
##
## Phase 0: no-op. Target of the `task_completing -> reporting` reflex
## (DESIGN.md §5.8). See §5.3 for params.

import ../types
import ../action

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
  discard belief
  discard params
  discard scratch
  noOpIntent()
