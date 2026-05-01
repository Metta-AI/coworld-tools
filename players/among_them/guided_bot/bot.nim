## Bot envelope + per-frame pipeline.
##
## Phase 0: `initBot` returns a fully-constructed `Bot`; `decideNextMask`
## wires perception -> belief-update -> decide -> act and returns whatever
## mask the action layer produces. Phase 1 filled in the perception
## pipeline. Phase 2 adds the action layer (A* + button masks), real
## mode handlers, and reflex evaluation.
##
## See DESIGN.md §4 (inner loop) and §2 (persistent state ownership).

import constants
import types
import belief
import perception
import perception/data
import perception/actors
import perception/ignore
import perception/localize
import perception/ocr
import perception/voting
import action
import mode_registry
import reflex
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
    reflexState*: ReflexState  ## Phase 2 — reflex edge-trigger memory.
    guidance*: GuidanceState
    trace*: TraceWriter
    localizer*: Localizer      ## Phase 1.2 — camera localization scratch.
    actorScanner*: ActorScanner ## Phase 1.3 — actor-scan reusable buffers.
    lastMask*: uint8
    unpacked*: seq[uint8]

proc initBot*(): Bot =
  result.frameTick = 0
  result.belief = initBelief()
  result.modeScratch = ModeScratch(mode: ModeIdle, idleEnterTick: 0)
  result.actionState = initActionState()
  result.reflexState = initReflexState()
  result.guidance = initGuidanceState()
  result.trace = nil
  result.localizer = initLocalizer()
  result.actorScanner = initActorScanner()
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
  ## fallback (§4.3), and reflex evaluation (§5.8).
  let cur = bot.belief.directive.mode

  # Ghost override. Always forces task_completing regardless of LLM.
  if bot.belief.self.isGhost and cur != ModeTaskCompleting:
    switchMode(bot, defaultDirectiveFor(bot.belief))
    return

  # Reflex evaluation (§5.8). Runs before illegality so reflexes
  # can install a legal directive that the illegality check would
  # otherwise override to the default.
  let rx = evaluateReflexes(bot.belief, bot.reflexState)
  if rx.fired:
    switchMode(bot, rx.newDirective)
    bot.belief.flags.wakeReasons.incl WakeReflexFired
    return

  # Illegality fallback.
  if not isLegalFor(cur, bot.belief):
    switchMode(bot, defaultDirectiveFor(bot.belief))
    return

proc decideNextMask*(bot: var Bot): uint8 =
  ## One full inner-loop step. Perception → belief update → reflex
  ## evaluation → mode decide → action layer → button mask.
  inc bot.frameTick

  # 1. Perceive — returns a structured observation of this frame
  #    (interstitial + ignore mask; actors + tasks added in steps 2b/2d).
  var percept = perceive(bot.unpacked, bot.frameTick)

  # 2. Update belief with the percept.
  updateBelief(bot.belief, percept)

  # 2a. Camera localization (phase 1.2). Skip on interstitials.
  if percept.interstitial.isInterstitial:
    bot.localizer.reseedCameraAtHome(bot.belief.percep)
  else:
    bot.localizer.updateLocation(
      bot.belief.percep,
      bot.unpacked,
      percept.ignoreMask.data,
      bot.frameTick)

  # 2b. Actor scan (phase 1.3).
  percept.actors = scanAll(
    bot.actorScanner,
    bot.belief.percep,
    bot.belief.self,
    referenceData.sprites,
    bot.unpacked,
    percept.interstitial.isInterstitial)

  # Stamp actor sprite exclusions into the ignore mask.
  let spriteW = referenceData.sprites.player.width
  let spriteH = referenceData.sprites.player.height
  for cm in percept.actors.crewmates:
    stampSpriteRect(percept.ignoreMask, cm.x, cm.y, spriteW, spriteH)
  let bodyW = referenceData.sprites.body.width
  let bodyH = referenceData.sprites.body.height
  for bm in percept.actors.bodies:
    stampSpriteRect(percept.ignoreMask, bm.x, bm.y, bodyW, bodyH)
  let ghostW = referenceData.sprites.ghost.width
  let ghostH = referenceData.sprites.ghost.height
  for gm in percept.actors.ghosts:
    stampSpriteRect(percept.ignoreMask, gm.x, gm.y, ghostW, ghostH)

  # 2c. Merge actor scan results into belief.
  mergeActorPercept(bot.belief, percept.actors)

  # 2d. Task-icon + radar-dot scan (phase 1.4).
  percept.taskPercept = scanTasksAndRadar(
    bot.unpacked,
    referenceData.sprites,
    bot.belief.percep.cameraX,
    bot.belief.percep.cameraY,
    bot.belief.percep.localized,
    percept.interstitial.isInterstitial,
    bot.belief.self.role == RoleImposter,
    bot.belief.self.isGhost)

  # Stamp task-icon exclusions into the ignore mask.
  let taskW = referenceData.sprites.task.width
  let taskH = referenceData.sprites.task.height
  for ti in percept.taskPercept.taskIcons:
    stampSpriteRect(percept.ignoreMask, ti.x, ti.y, taskW, taskH)

  # 2e. Merge task/radar scan results into belief.
  mergeTaskPercept(bot.belief, percept.taskPercept)

  # 2f. Interstitial classification (phase 1.5) + voting-screen parse
  #     (phase 1.6).
  if percept.interstitial.isInterstitial:
    percept.votingParse = parseVotingScreen(
      bot.unpacked,
      referenceData.sprites,
      bot.belief.self.colorIndex)
    if percept.votingParse.valid:
      bot.belief.self.phase = PhaseVoting
      bot.belief.percep.interstitialKind = InterstitialVoting
    else:
      let kind = classifyInterstitial(bot.unpacked)
      if kind != InterstitialUnknown:
        bot.belief.percep.interstitialKind = kind
    mergeVotingPercept(bot.belief, percept.votingParse)

  # 3. Reconcile directive (ghost override, reflexes, legality).
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
