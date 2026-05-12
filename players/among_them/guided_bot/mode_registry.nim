## Mode registry + dispatch.
##
## The single extension point for behavior. Adding a new mode is:
##   1. Add a variant to `ModeName` in `types.nim` (append; don't reorder).
##   2. Add a `modes/<name>.nim` file implementing the six-proc interface
##      (`isLegalFor`, `defaultParamsFor`, `onEnter`, `onExit`, `decide`,
##      `summarizeForLlm`).
##   3. Add one import + one `case` arm below.
##
## No other file needs to change. Per DESIGN.md §5.2.

import std/json
import types
import modes/idle
import modes/task_completing
import modes/reporting
import modes/pretending
import modes/hunting
import modes/fleeing
import modes/alibi_building
import modes/meeting

proc isLegalFor*(mode: ModeName, belief: Belief): bool =
  case mode
  of ModeIdle:             idle.isLegalFor(belief)
  of ModeTaskCompleting:   task_completing.isLegalFor(belief)
  of ModeReporting:        reporting.isLegalFor(belief)
  of ModePretending:       pretending.isLegalFor(belief)
  of ModeHunting:          hunting.isLegalFor(belief)
  of ModeFleeing:          fleeing.isLegalFor(belief)
  of ModeAlibiBuilding:    alibi_building.isLegalFor(belief)
  of ModeMeeting:          meeting.isLegalFor(belief)

proc defaultParamsFor*(mode: ModeName, belief: Belief): ModeParams =
  case mode
  of ModeIdle:             idle.defaultParamsFor(belief)
  of ModeTaskCompleting:   task_completing.defaultParamsFor(belief)
  of ModeReporting:        reporting.defaultParamsFor(belief)
  of ModePretending:       pretending.defaultParamsFor(belief)
  of ModeHunting:          hunting.defaultParamsFor(belief)
  of ModeFleeing:          fleeing.defaultParamsFor(belief)
  of ModeAlibiBuilding:    alibi_building.defaultParamsFor(belief)
  of ModeMeeting:          meeting.defaultParamsFor(belief)

proc onEnter*(mode: ModeName, belief: Belief, params: ModeParams,
              scratch: var ModeScratch) =
  case mode
  of ModeIdle:             idle.onEnter(belief, params, scratch)
  of ModeTaskCompleting:   task_completing.onEnter(belief, params, scratch)
  of ModeReporting:        reporting.onEnter(belief, params, scratch)
  of ModePretending:       pretending.onEnter(belief, params, scratch)
  of ModeHunting:          hunting.onEnter(belief, params, scratch)
  of ModeFleeing:          fleeing.onEnter(belief, params, scratch)
  of ModeAlibiBuilding:    alibi_building.onEnter(belief, params, scratch)
  of ModeMeeting:          meeting.onEnter(belief, params, scratch)

proc onExit*(mode: ModeName, belief: Belief, scratch: var ModeScratch) =
  case mode
  of ModeIdle:             idle.onExit(belief, scratch)
  of ModeTaskCompleting:   task_completing.onExit(belief, scratch)
  of ModeReporting:        reporting.onExit(belief, scratch)
  of ModePretending:       pretending.onExit(belief, scratch)
  of ModeHunting:          hunting.onExit(belief, scratch)
  of ModeFleeing:          fleeing.onExit(belief, scratch)
  of ModeAlibiBuilding:    alibi_building.onExit(belief, scratch)
  of ModeMeeting:          meeting.onExit(belief, scratch)

proc decide*(mode: ModeName, belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  case mode
  of ModeIdle:             idle.decide(belief, params, scratch)
  of ModeTaskCompleting:   task_completing.decide(belief, params, scratch)
  of ModeReporting:        reporting.decide(belief, params, scratch)
  of ModePretending:       pretending.decide(belief, params, scratch)
  of ModeHunting:          hunting.decide(belief, params, scratch)
  of ModeFleeing:          fleeing.decide(belief, params, scratch)
  of ModeAlibiBuilding:    alibi_building.decide(belief, params, scratch)
  of ModeMeeting:          meeting.decide(belief, params, scratch)

proc summarizeForLlm*(mode: ModeName, belief: Belief, params: ModeParams,
                      scratch: ModeScratch): JsonNode =
  case mode
  of ModeIdle:             idle.summarizeForLlm(belief, params, scratch)
  of ModeTaskCompleting:   task_completing.summarizeForLlm(belief, params, scratch)
  of ModeReporting:        reporting.summarizeForLlm(belief, params, scratch)
  of ModePretending:       pretending.summarizeForLlm(belief, params, scratch)
  of ModeHunting:          hunting.summarizeForLlm(belief, params, scratch)
  of ModeFleeing:          fleeing.summarizeForLlm(belief, params, scratch)
  of ModeAlibiBuilding:    alibi_building.summarizeForLlm(belief, params, scratch)
  of ModeMeeting:          meeting.summarizeForLlm(belief, params, scratch)

proc defaultDirectiveFor*(belief: Belief): Directive =
  ## Per-role default used when no LLM directive is available (see
  ## DESIGN.md §9.1). Phase 0: the action layer is no-op anyway, so the
  ## returned directive is purely structural. Phase 2 actually plays on
  ## these defaults when the LLM is unavailable.
  let mode =
    if belief.self.isGhost:                                ModeTaskCompleting
    elif belief.self.phase == PhaseVoting:                 ModeMeeting
    elif not belief.self.alive:                            ModeIdle
    elif belief.self.role == RoleImposter:                 ModeHunting
    elif belief.self.role == RoleCrewmate:                 ModeTaskCompleting
    else:                                                  ModeIdle
  Directive(
    mode: mode,
    params: defaultParamsFor(mode, belief),
    source: SourceDefault,
    issuedAtTick: belief.tick,
    ttlTicks: 0,
    reflexName: "",
    reasoning: ""
  )
