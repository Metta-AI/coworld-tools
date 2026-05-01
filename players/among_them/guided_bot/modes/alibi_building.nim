## Mode: `alibi_building`. Imposter loitering visibly near a specific
## crewmate in a public room to build an alibi. Phase 0: no-op. See
## DESIGN.md §5.4.

import ../types
import ../action

const Name* = ModeAlibiBuilding

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleImposter and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeAlibiBuilding,
             aliCompanionColor: -1,
             aliRoomId: -1,
             aliMinDurationTicks: 240)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeAlibiBuilding, aliEnterTick: belief.tick)
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
