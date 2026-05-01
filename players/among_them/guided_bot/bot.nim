## Bot envelope + per-frame pipeline.
##
## Phase 0: `initBot` returns a fully-constructed `Bot`; `decideNextMask`
## wires perception -> belief-update -> decide -> act and returns whatever
## mask the action layer produces (which is currently always 0). Phase 1+
## replaces the perception stub and fleshes out each stage.
##
## See DESIGN.md §4 (inner loop) and §2 (persistent state ownership).

import constants
import types
import belief
import perception
import perception/localize
import action
import mode_registry
import guidance
import trace

type
  Bot* = object
    ## Thin envelope of persistent per-bot state. All sub-records are
    ## owned here; modules mutate them via `var Bot` or `var <sub>`
    ## arguments depending on their leaf/orchestrator status (DESIGN.md
    ## §3 conventions, lifted from modulabot).
    frameTick*: int
    belief*: Belief
    modeScratch*: ModeScratch
    actionState*: ActionState
    guidance*: GuidanceState
    trace*: TraceWriter
    localizer*: Localizer  ## Phase 1.2 — camera localization scratch
                            ## (vote buffer). Patch index is module-
                            ## level, shared across bots.
    lastMask*: uint8
    unpacked*: seq[uint8]

proc initBot*(): Bot =
  result.frameTick = 0
  result.belief = initBelief()
  result.modeScratch = ModeScratch(mode: ModeIdle, idleEnterTick: 0)
  result.actionState = initActionState()
  result.guidance = initGuidanceState()
  result.trace = nil
  result.localizer = initLocalizer()
  result.lastMask = 0'u8
  result.unpacked = newSeq[uint8](FrameLen)

proc switchMode(bot: var Bot, newDirective: Directive) =
  ## Honor `on_exit` / `on_enter` lifecycle hooks and reset scratch per
  ## DESIGN.md §5.6. Called whenever the active mode name changes (LLM
  ## directive, default fallback, or reflex switch).
  let oldMode = bot.belief.directive.mode
  onExit(oldMode, bot.belief, bot.modeScratch)
  bot.belief.directive = newDirective
  onEnter(newDirective.mode, bot.belief, newDirective.params, bot.modeScratch)

proc reconcileDirective(bot: var Bot) =
  ## Per-tick check. Honors the ghost override (§5.7), illegality
  ## fallback (§4.3), and (phase 2+) reflex evaluation (§5.8). Phase 0
  ## enforces ghost and legality only.
  let cur = bot.belief.directive.mode

  # Ghost override. Always forces task_completing regardless of LLM.
  if bot.belief.self.isGhost and cur != ModeTaskCompleting:
    switchMode(bot, defaultDirectiveFor(bot.belief))
    return

  # Illegality fallback.
  if not isLegalFor(cur, bot.belief):
    switchMode(bot, defaultDirectiveFor(bot.belief))
    return

proc decideNextMask*(bot: var Bot): uint8 =
  ## One full inner-loop step. Phase 1.2: perception returns a real
  ## `Percept` (interstitial observation + ignore mask); belief update
  ## merges it; localize updates camera state on non-interstitial
  ## frames; decide routes to the current mode; action layer returns
  ## 0. See DESIGN.md §4.
  inc bot.frameTick

  # 1. Perceive — returns a structured observation of this frame.
  let percept = perceive(bot.unpacked, bot.frameTick)

  # 2. Update belief with the percept (and, phase 2, read directive
  #    channel + evaluate reflexes).
  updateBelief(bot.belief, percept)

  # 2a. Camera localization (phase 1.2). Skip on interstitials —
  #     localize can't produce a sensible answer when the framebuffer
  #     is mostly black, and running it wastes ~5 ms. On the *first*
  #     gameplay frame after an interstitial, reseed the camera so
  #     local refit starts from the right place.
  if percept.interstitial.isInterstitial:
    bot.localizer.reseedCameraAtHome(bot.belief.percep)
  else:
    bot.localizer.updateLocation(
      bot.belief.percep,
      bot.unpacked,
      percept.ignoreMask.data,
      bot.frameTick)

  # 3. Reconcile directive against current state (ghost / legality).
  reconcileDirective(bot)

  # 4. Decide.
  let intent = decide(bot.belief.directive.mode,
                      bot.belief,
                      bot.belief.directive.params,
                      bot.modeScratch)

  # 5. Act.
  let mask = applyIntent(bot.actionState, bot.belief, intent)
  bot.lastMask = mask
  mask

proc stepUnpackedFrame*(bot: var Bot,
                       frame: openArray[uint8]): uint8 =
  ## Convenience entry point: copy an unpacked frame into the bot's
  ## internal buffer then run one decision. Used by FFI and CLI paths.
  if frame.len != FrameLen:
    return bot.lastMask
  if bot.unpacked.len != FrameLen:
    bot.unpacked.setLen(FrameLen)
  for i in 0 ..< FrameLen:
    bot.unpacked[i] = frame[i] and 0x0f'u8
  decideNextMask(bot)
