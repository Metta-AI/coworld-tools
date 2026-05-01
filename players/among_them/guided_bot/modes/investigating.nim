## Mode: `investigating`. Go gather evidence on someone or somewhere.
## Phase 0: no-op. See DESIGN.md §5.3, §5.4.

import ../types
import ../action

const Name* = ModeInvestigating

proc isLegalFor*(belief: Belief): bool =
  belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  var tgt = InvestigateTarget(kind: InvestLocation,
                              colorIndex: -1,
                              location: Point(x: 0, y: 0),
                              roomId: -1)
  ModeParams(mode: ModeInvestigating,
             invTarget: tgt,
             invTimeoutTicks: 480)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeInvestigating,
                        invDeadlineTick: belief.tick + params.invTimeoutTicks)

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  discard belief
  discard params
  discard scratch
  noOpIntent()
