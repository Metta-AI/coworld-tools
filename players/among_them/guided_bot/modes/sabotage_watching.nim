## Mode: `sabotage_watching`. Placeholder — only activates if a season
## enables sabotage tasks. Phase 0: no-op. See DESIGN.md §5.4.

import ../types
import ../action

const Name* = ModeSabotageWatching

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleImposter and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeSabotageWatching, sabStationId: -1)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeSabotageWatching, sabEnterTick: belief.tick)
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
