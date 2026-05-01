## Bot envelope + per-frame pipeline.
##
## Phase 0: `initBot` returns a fully-constructed `Bot`; `decideNextMask`
## wires perception -> belief-update -> decide -> act and returns whatever
## mask the action layer produces. Phase 1 filled in the perception
## pipeline. Phase 2 adds the action layer (A* + button masks), real
## mode handlers, and reflex evaluation. Phase 3 wires the LLM guidance
## loop: snapshot submission, directive channel reads, and meeting action
## channel reads.
##
## See DESIGN.md §4 (inner loop), §2 (persistent state ownership),
## §8 (guidance loop), §10 (concurrency model).

import std/[os, json, strutils]
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
import snapshot
import llm
import tuning
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
    ## Phase 3 — LLM guidance tracking.
    guidanceStarted*: bool     ## Whether the worker thread is running.
    prevPhaseForGuidance*: GamePhase ## For detecting meeting end transitions.
    ## Phase 4 — trace edge-detection state.
    prevBodyCount*: int        ## For detecting new bodies (body_seen event).
    prevRole*: BotRole         ## For detecting role_revealed event.
    prevPhaseForTrace*: GamePhase ## For detecting meeting_started / game_over.
    prevChatLen*: int          ## For detecting new chat lines.

proc initBot*(): Bot =
  result.frameTick = 0
  result.belief = initBelief()
  result.modeScratch = ModeScratch(mode: ModeIdle, idleEnterTick: 0)
  result.actionState = initActionState()
  result.reflexState = initReflexState()
  result.guidance = initGuidanceState()
  result.localizer = initLocalizer()
  result.actorScanner = initActorScanner()
  result.lastMask = 0'u8
  result.unpacked = newSeq[uint8](FrameLen)
  result.guidanceStarted = false
  result.prevPhaseForGuidance = PhaseUnknown
  result.prevBodyCount = 0
  result.prevRole = RoleUnknown
  result.prevPhaseForTrace = PhaseUnknown
  result.prevChatLen = 0

  # Phase 4: open trace writer if env vars are set.
  let traceDir = getEnv("GUIDED_BOT_TRACE_DIR", "")
  let traceLevelStr = getEnv("GUIDED_BOT_TRACE_LEVEL", "").toLowerAscii()
  let traceLevel = case traceLevelStr
    of "events":    TraceEvents
    of "decisions": TraceDecisions
    of "full":      TraceFull
    else:           TraceOff
  result.trace = openTrace(traceDir, traceLevel)

proc switchMode(bot: var Bot, newDirective: Directive) =
  ## Honor `on_exit` / `on_enter` lifecycle hooks and reset scratch per
  ## DESIGN.md §5.6. Called whenever the active mode name changes (LLM
  ## directive, default fallback, or reflex switch).
  let oldMode = bot.belief.directive.mode
  let tick = bot.belief.tick

  # Trace: log mode exit before onExit runs (captures duration).
  if bot.trace != nil:
    let duration = tick - bot.trace.modeEntryTick
    logModeExited(bot.trace, tick, oldMode, duration)

  onExit(oldMode, bot.belief, bot.modeScratch)
  bot.belief.directive = newDirective
  onEnter(newDirective.mode, bot.belief, newDirective.params, bot.modeScratch)

  # Trace: log mode entry after onEnter completes.
  if bot.trace != nil:
    let reason = case newDirective.source
      of SourceLlm:     "llm_directive"
      of SourceDefault:  "default"
      of SourceReflex:
        if newDirective.reflexName.len > 0:
          "reflex:" & newDirective.reflexName
        else:
          "reflex"
    logModeEntered(bot.trace, tick, oldMode, newDirective.mode,
                   newDirective.params, reason)

proc ensureGuidanceStarted(bot: var Bot) =
  ## Start the guidance worker thread on the first frame, if an API
  ## key is available. No-op if already started or no key.
  if bot.guidanceStarted:
    return
  if haveApiKey():
    startGuidance(bot.guidance)
    bot.guidanceStarted = true

proc shouldSubmitSnapshot(bot: Bot): bool =
  ## Decide whether to submit a belief snapshot to the guidance worker
  ## on this tick. Hybrid periodic + event-driven (DESIGN.md §8.2).
  if not bot.guidanceStarted:
    return false

  let tick = bot.belief.tick

  # Always submit if wake-up reasons are pending.
  if bot.belief.flags.wakeReasons.len > 0:
    return true

  # Periodic submission every GuidancePeriodTicks.
  if tick - bot.guidance.lastCallTick >= GuidancePeriodTicks or
     bot.guidance.lastCallTick < 0:
    return true

  # Directive expiring soon.
  if bot.belief.directive.ttlTicks > 0:
    let remaining = bot.belief.directive.ttlTicks -
                    (tick - bot.belief.directive.issuedAtTick)
    if remaining > 0 and remaining <= DirectiveExpiringSoonTicks:
      return true

  false

proc submitGuidanceSnapshot(bot: var Bot) =
  ## Render and submit a belief snapshot to the guidance worker.
  let payloadJson = renderSnapshot(bot.belief)
  let isMeeting = bot.belief.self.phase == PhaseVoting
  let snap = Snapshot(
    tick: bot.belief.tick,
    payloadJson: payloadJson,
    isMeeting: isMeeting
  )
  submitSnapshot(bot.guidance, snap)

proc readGuidanceDirective(bot: var Bot) =
  ## Non-blocking read of the directive channel. If a fresh LLM
  ## directive arrived, install it (with mode switch if needed).
  ## Per PHASE3_HANDOFF.md §5: this happens in updateBelief, before
  ## reconcileDirective, so the new directive gets the same validation
  ## pass (ghost override, illegality, reflexes).
  var newDirective: Directive
  if tryReceiveDirective(bot.guidance, newDirective):
    # Fill in the issued-at tick if the worker didn't.
    if newDirective.issuedAtTick <= 0:
      newDirective.issuedAtTick = bot.belief.tick

    # Mode changed? Perform a full mode switch with lifecycle hooks.
    if newDirective.mode != bot.belief.directive.mode:
      switchMode(bot, newDirective)
    else:
      # Same mode, different params — update directive in place.
      # Scratch is preserved per DESIGN.md §5.6.
      bot.belief.directive = newDirective
    bot.belief.flags.newDirectiveAvailable = true

proc checkDirectiveTtl(bot: var Bot) =
  ## Expire the current directive if its TTL has elapsed, falling back
  ## to the per-role default (DESIGN.md §4.2).
  let d = bot.belief.directive
  if d.ttlTicks > 0 and d.issuedAtTick > 0:
    let elapsed = bot.belief.tick - d.issuedAtTick
    if elapsed >= d.ttlTicks:
      switchMode(bot, defaultDirectiveFor(bot.belief))

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
    # Trace: log reflex firing before the mode switch.
    if bot.trace != nil:
      logReflexFired(bot.trace, bot.belief.tick, rx.reflexName,
                     cur, rx.newDirective.mode, rx.newDirective.params)
    switchMode(bot, rx.newDirective)
    bot.belief.flags.wakeReasons.incl WakeReflexFired
    return

  # Illegality fallback.
  if not isLegalFor(cur, bot.belief):
    switchMode(bot, defaultDirectiveFor(bot.belief))
    return

proc decideNextMask*(bot: var Bot): uint8 =
  ## One full inner-loop step. Perception → belief update → LLM
  ## directive read → reflex evaluation → mode decide → action layer
  ## → button mask.
  inc bot.frameTick

  # Phase 3: ensure guidance worker is running.
  ensureGuidanceStarted(bot)

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

  # Phase 3: flush meeting conversation when leaving voting phase.
  if bot.prevPhaseForGuidance == PhaseVoting and
     bot.belief.self.phase != PhaseVoting:
    flushMeetingConversation(bot.guidance)
  bot.prevPhaseForGuidance = bot.belief.self.phase

  # Phase 3: read LLM directives from the guidance channel. This
  # happens before reconcileDirective so fresh directives get the
  # same validation pass (PHASE3_HANDOFF.md §5).
  readGuidanceDirective(bot)

  # Phase 3: pump meeting actions from the guidance channel into the
  # mode scratch's pending actions queue. The meeting mode's decide()
  # pops one per tick.
  if bot.belief.self.phase == PhaseVoting and
     bot.modeScratch.mode == ModeMeeting:
    var meetAction: MeetingAction
    while tryReceiveMeetingAction(bot.guidance, meetAction):
      bot.modeScratch.meetPendingActions.add meetAction

  # Phase 3: check directive TTL expiry.
  checkDirectiveTtl(bot)

  # Phase 3: submit a snapshot to the guidance worker if conditions
  # are met (periodic or triggered by wake flags).
  if shouldSubmitSnapshot(bot):
    submitGuidanceSnapshot(bot)

  # Phase 4: detect and log game events (before wake flags are cleared).
  # Events are edge-triggered: we compare current state to previous frame.
  if bot.trace != nil:
    let tick = bot.belief.tick

    # body_seen: new bodies appeared this frame.
    if bot.belief.percep.visibleBodies.len > bot.prevBodyCount:
      for i in bot.prevBodyCount ..< bot.belief.percep.visibleBodies.len:
        let body = bot.belief.percep.visibleBodies[i]
        var payload = newJObject()
        payload["body_id"] = newJInt(i)
        if bot.belief.percep.localized:
          payload["position"] = %*[body.x, body.y]
        logGameEvent(bot.trace, "body_seen", tick, $payload)

    # meeting_started: transition into voting phase.
    if bot.belief.self.phase == PhaseVoting and
       bot.prevPhaseForTrace != PhaseVoting:
      logGameEvent(bot.trace, "meeting_started", tick, "")

    # role_revealed: role changed from unknown to a known role.
    if bot.belief.self.role != RoleUnknown and
       bot.prevRole == RoleUnknown:
      var payload = newJObject()
      case bot.belief.self.role
      of RoleCrewmate: payload["role"] = newJString("crewmate")
      of RoleImposter: payload["role"] = newJString("imposter")
      of RoleUnknown:  discard
      logGameEvent(bot.trace, "role_revealed", tick, $payload)
      # Update manifest role.
      case bot.belief.self.role
      of RoleCrewmate: setRole(bot.trace, "crewmate")
      of RoleImposter: setRole(bot.trace, "imposter")
      of RoleUnknown:  discard

    # chat_observed: new chat lines appeared during voting.
    if bot.belief.social.currentMeetingChat.len > bot.prevChatLen and
       bot.belief.self.phase == PhaseVoting:
      for i in bot.prevChatLen ..< bot.belief.social.currentMeetingChat.len:
        let cl = bot.belief.social.currentMeetingChat[i]
        var payload = newJObject()
        if cl.speakerColor >= 0:
          payload["speaker"] = newJInt(cl.speakerColor)
        payload["text"] = newJString(cl.text)
        logGameEvent(bot.trace, "chat_observed", tick, $payload)

    # game_over: transition to game-over phase.
    if bot.belief.self.phase == PhaseGameOver and
       bot.prevPhaseForTrace != PhaseGameOver:
      logGameEvent(bot.trace, "game_over", tick, "")

    # self_became_ghost: transition to ghost state.
    if bot.belief.self.isGhost and not bot.belief.self.alive:
      discard  # Detected via role/alive change — ghost event tracked
               # through the existing belief merge. Would need an
               # additional prev-ghost flag for edge detection; deferred.

    # Drain guidance trace events from the channel (worker → main).
    drainGuidanceTraceEvents(bot.guidance, bot.trace)

    # Update edge-detection state for next frame.
    bot.prevBodyCount = bot.belief.percep.visibleBodies.len
    bot.prevRole = bot.belief.self.role
    bot.prevPhaseForTrace = bot.belief.self.phase
    bot.prevChatLen = bot.belief.social.currentMeetingChat.len

    # Log raw frame if TraceFull.
    logFrame(bot.trace, bot.unpacked)

  # Clear wake reasons after snapshot submission decision so they
  # don't accumulate across frames.
  bot.belief.flags.wakeReasons = {}

  # 3. Reconcile directive (ghost override, reflexes, legality).
  reconcileDirective(bot)

  # 4. Decide.
  let intent = decide(bot.belief.directive.mode,
                      bot.belief,
                      bot.belief.directive.params,
                      bot.modeScratch)

  # Phase 4: log the decision and periodic snapshots.
  if bot.trace != nil:
    logDecision(bot.trace, bot.belief, intent, "")
    logSnapshot(bot.trace, bot.belief.tick, bot.belief)

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

proc destroyBot*(bot: var Bot) =
  ## Clean up the guidance worker thread, channels, and trace writer.
  ## Call this when the match ends or the bot is being deallocated.
  if bot.guidanceStarted:
    stopGuidance(bot.guidance)
    bot.guidanceStarted = false
  # Phase 4: flush and close the trace writer.
  if bot.trace != nil:
    closeTrace(bot.trace)
    bot.trace = nil
