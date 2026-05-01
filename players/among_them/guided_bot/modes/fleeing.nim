## Mode: `fleeing`. Imposter just saw a body they didn't make and needs
## to put distance between them and it. Target of the
## `hunting -> fleeing` reflex. Phase 0: no-op. See DESIGN.md §5.4, §5.8.

import ../types
import ../action

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
  discard belief
  discard params
  discard scratch
  noOpIntent()
