## Mode: `fear`. Crewmate survival behavior: stay near groups, avoid
## empty rooms, don't get caught alone. Phase 0: no-op. See DESIGN.md
## §5.4.

import ../types
import ../action

const Name* = ModeFear

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleCrewmate and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeFear,
             fearMinVisibleOthers: 2,
             fearPreferRoomId: -1,
             fearMaxDistance: 32)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeFear, fearEnterTick: belief.tick)
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
