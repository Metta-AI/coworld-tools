## Mode: `task_completing`. Crewmate default and ghost default.
##
## Crewmate version: the first real strategy to implement post-phase-0.
## Per DESIGN.md §12.2, we inherit modulabot's task-state model (icon-area
## clearing, radar-vs-mandatory separation, hold-A discipline) but do not
## copy its code verbatim.
##
## Ghost version: `belief.self.isGhost` is true. Same decide logic but
## ghost-aware A* in the action layer (different passability mask; see
## `action.applyIntent`). Ghosts ignore bodies / imposters / reflexes.
##
## Phase 0: no-op.

import ../types
import ../action

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

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  discard belief
  discard params
  discard scratch
  noOpIntent()
