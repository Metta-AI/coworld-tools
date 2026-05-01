## Mode: `pretending`. Imposter walking task-to-task without actually
## doing them. Target of the `pretending -> hunting` reflex when a lone
## kill opportunity appears. Phase 0: no-op. See DESIGN.md §5.4, §5.8.

import ../types
import ../action

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
  scratch = ModeScratch(mode: ModePretending,
                        preFakeTargetIndex: -1,
                        preLoiterUntilTick: 0,
                        preEnterTick: belief.tick)
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
