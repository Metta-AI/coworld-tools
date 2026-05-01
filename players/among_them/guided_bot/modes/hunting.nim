## Mode: `hunting`. Imposter closing on a kill. Also the imposter
## default directive (DESIGN.md §9.1) with `opportunistic: true` and no
## specific target. Phase 0: no-op. See §5.3, §5.4, §5.8.

import ../types
import ../action

const Name* = ModeHunting

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleImposter and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeHunting,
             hunPreferredTarget: -1,
             hunMaxWitnesses: 0,
             hunOpportunistic: true,
             hunCoverMode: ModePretending)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeHunting,
                        hunTargetColor: params.hunPreferredTarget,
                        hunLastSightingTick: 0,
                        hunEnterTick: belief.tick)

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  discard belief
  discard params
  discard scratch
  noOpIntent()
