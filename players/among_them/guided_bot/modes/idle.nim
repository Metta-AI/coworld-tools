## Mode: `idle`. Safe default behavior: stand somewhere reasonable,
## observe, respond only to reflexes. Fallback when the bot has nothing
## better to do and the LLM hasn't issued anything.
##
## Phase 0: `decide` returns a no-op intent. See DESIGN.md §5.4.

import ../types
import ../action

const Name* = ModeIdle

proc isLegalFor*(belief: Belief): bool =
  ## Legal in any role, any phase except meeting/game over.
  discard belief
  true

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeIdle,
             idleLingerValid: false,
             idleNearGroup: true)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeIdle, idleEnterTick: belief.tick)
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
