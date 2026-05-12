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

import std/[os, json, strutils, strformat]
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
    ## Phase 5 — interstitial OCR cache. classifyInterstitial is a
    ## full-frame OCR sweep (~22 ms). We cache the result across
    ## consecutive interstitial frames so the sweep runs at most once
    ## per interstitial run.
    interstitialClassified*: bool  ## True once we've run OCR on this run.
    cachedInterstitialKind*: InterstitialKind  ## Cached classification.
    cachedImposterColors*: seq[int]  ## Colors detected during interstitial scan (applied on role confirm).
    ## Voting-screen detection fallback. The voting screen doesn't always
    ## pass the 30%-black interstitial gate, causing the localizer to fail
    ## without the voting parse ever running. This fallback probes
    ## parseVotingScreen on a cooldown when localization is lost on a
    ## non-interstitial frame.
    lastVotingProbeTick*: int      ## Last tick we tried parseVotingScreen as fallback.

proc initBot*(botIndex: int = -1): Bot =
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
  result.interstitialClassified = false
  result.cachedInterstitialKind = InterstitialUnknown

  # Phase 4: open trace writer if env vars are set.
  let traceDir = getEnv("GUIDED_BOT_TRACE_DIR", "")
  let traceLevelStr = getEnv("GUIDED_BOT_TRACE_LEVEL", "").toLowerAscii()
  let traceLevel = case traceLevelStr
    of "events":    TraceEvents
    of "decisions": TraceDecisions
    of "full":      TraceFull
    else:           TraceOff
  result.trace = openTrace(traceDir, traceLevel, botIndex)

  # Localization diagnostics: announce if debug logging is enabled.
  if localizeDebug:
    stderr.writeLine "[localize] diagnostics ENABLED (GUIDED_BOT_LOCALIZE_DEBUG)"

proc switchMode(bot: var Bot, newDirective: Directive) =
  ## Honor `on_exit` / `on_enter` lifecycle hooks and reset scratch per
  ## DESIGN.md §5.6. Called whenever the active mode name changes (LLM
  ## directive, default fallback, or reflex switch).
  let oldMode = bot.belief.directive.mode
  let tick = bot.belief.tick

  # Trace: task_abandoned if leaving task_completing during Hold/Confirm.
  if bot.trace != nil and oldMode == ModeTaskCompleting and
     bot.modeScratch.mode == ModeTaskCompleting and
     (bot.modeScratch.tcPhase == TpHold or bot.modeScratch.tcPhase == TpConfirm):
    let ti = bot.modeScratch.tcLockedTaskIndex
    let tasks = referenceData.map.tasks
    var payload = newJObject()
    payload["task_index"] = newJInt(ti)
    if ti >= 0 and ti < tasks.len:
      payload["station_name"] = newJString(tasks[ti].name)
    payload["reason"] = newJString("mode_switch")
    if bot.modeScratch.tcPhase == TpHold:
      payload["phase_at_abandon"] = newJString("hold")
    else:
      payload["phase_at_abandon"] = newJString("confirm")
    payload["hold_ticks_elapsed"] = newJInt(
      tick - bot.modeScratch.tcHoldStartTick)
    logGameEvent(bot.trace, "task_abandoned", tick, $payload)

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

proc huntingPhaseStr(phase: HuntingPhase): string =
  case phase
  of HpAlibi:    "alibi"
  of HpSeeking:  "seeking"
  of HpStalking: "stalking"
  of HpStrike:   "strike"
  of HpPostKill: "post_kill"

proc postKillPlanStr(plan: PostKillPlanKind): string =
  case plan
  of PkNone:    "none"
  of PkVent:    "vent"
  of PkStation: "station"
  of PkPlayer:  "player"

proc ensureGuidanceStarted(bot: var Bot) =
  ## Start the guidance worker thread on the first frame, if an LLM
  ## provider is available. No-op if already started or no provider.
  if bot.guidanceStarted:
    return
  if haveLlmProvider():
    startGuidance(bot.guidance)
    bot.guidanceStarted = true

proc snapshotTrigger(bot: Bot): string =
  ## Human-readable reason recorded with guidance snapshot traces.
  if not bot.guidanceStarted:
    return ""

  let tick = bot.belief.tick

  # Always submit if wake-up reasons are pending.
  if bot.belief.flags.wakeReasons.len > 0:
    var reasons: seq[string] = @[]
    for w in WakeReason:
      if w in bot.belief.flags.wakeReasons:
        reasons.add wakeReasonStr(w)
    return "wake_up:" & reasons.join("+")

  # Meetings need several single-action LLM calls (speak -> vote ->
  # confirm) inside a short voting timer, so use a faster cadence than
  # the gameplay strategy loop while the meeting is still undecided.
  if bot.belief.self.phase == PhaseVoting and
     bot.modeScratch.mode == ModeMeeting and
     not bot.modeScratch.meetVoteConfirmed and
     bot.modeScratch.meetPendingActions.len == 0 and
     (tick - bot.guidance.lastCallTick >= MeetingLlmActionPeriodTicks or
      bot.guidance.lastCallTick < 0):
    return "meeting_action"

  # Periodic submission every GuidancePeriodTicks.
  if tick - bot.guidance.lastCallTick >= GuidancePeriodTicks or
     bot.guidance.lastCallTick < 0:
    return "periodic"

  # Directive expiring soon.
  if bot.belief.directive.ttlTicks > 0:
    let remaining = bot.belief.directive.ttlTicks -
                    (tick - bot.belief.directive.issuedAtTick)
    if remaining > 0 and remaining <= DirectiveExpiringSoonTicks:
      return "directive_expiring_soon"

  ""

proc shouldSubmitSnapshot(bot: Bot): bool =
  ## Decide whether to submit a belief snapshot to the guidance worker
  ## on this tick. Hybrid periodic + event-driven (DESIGN.md §8.2).
  snapshotTrigger(bot).len > 0

proc submitGuidanceSnapshot(bot: var Bot) =
  ## Render and submit a belief snapshot to the guidance worker.
  let trigger = snapshotTrigger(bot)
  if trigger.len == 0:
    return
  let modeSummary = summarizeForLlm(bot.belief.directive.mode,
                                    bot.belief,
                                    bot.belief.directive.params,
                                    bot.modeScratch)
  let payloadJson = renderSnapshot(bot.belief, modeSummary)
  let isMeeting = bot.belief.self.phase == PhaseVoting
  let snap = Snapshot(
    id: &"t{bot.belief.tick}-c{bot.guidance.callsThisMatch + 1}",
    tick: bot.belief.tick,
    payloadJson: payloadJson,
    isMeeting: isMeeting,
    trigger: trigger
  )
  discard submitSnapshot(bot.guidance, snap)

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
  ## Per-tick check. Honors the ghost override (§5.7), stale-default
  ## re-evaluation, reflex evaluation (§5.8), and illegality fallback
  ## (§4.3).
  let cur = bot.belief.directive.mode

  # Ghost override. Always forces task_completing regardless of LLM.
  if bot.belief.self.isGhost and cur != ModeTaskCompleting:
    switchMode(bot, defaultDirectiveFor(bot.belief))
    return

  # Stale-default re-evaluation (§9.1 fallback path). When the bot is
  # running on a default directive in ModeIdle and the role is now known
  # (crewmate or imposter), the original "unknown role" default is stale.
  # Re-evaluate so the bot transitions to task_completing or hunting
  # immediately on role detection — without waiting for the LLM. This
  # is the mechanism that passes the cogames 10-step validation gate.
  if cur == ModeIdle and
     bot.belief.directive.source == SourceDefault and
     bot.belief.self.role != RoleUnknown:
    let better = defaultDirectiveFor(bot.belief)
    if better.mode != cur:
      switchMode(bot, better)
      return

  # Reflex evaluation (§5.8). Runs before illegality so reflexes
  # can install a legal directive that the illegality check would
  # otherwise override to the default.
  let rx = evaluateReflexes(bot.belief, bot.reflexState, bot.modeScratch)
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

proc decideNextMaskInner(bot: var Bot): uint8  # forward decl

proc decideNextMask*(bot: var Bot): uint8 =
  ## One full inner-loop step. Perception → belief update → LLM
  ## directive read → reflex evaluation → mode decide → action layer
  ## → button mask.
  inc bot.frameTick
  try:
    return decideNextMaskInner(bot)
  except Exception:
    # Pre-existing perception/OCR IndexDefects (actors.nim, ocr.nim)
    # crash on some frames. Fall back to last mask (same as the old
    # behavior where the FFI boundary silently swallowed the exception).
    return bot.lastMask

proc decideNextMaskInner(bot: var Bot): uint8 =

  # One-shot diagnostic on first frame: verify reference data integrity.
  if bot.frameTick == 1:
    stderr.writeLine "[diag] font.height=" & $referenceData.font.height &
      " font.spacing=" & $referenceData.font.spacing &
      " sprites.player.w=" & $referenceData.sprites.player.width &
      " sprites.player.pixels.len=" & $referenceData.sprites.player.pixels.len

  # Phase 3: ensure guidance worker is running.
  ensureGuidanceStarted(bot)

  # 1. Perceive — returns a structured observation of this frame
  #    (interstitial + ignore mask; actors + tasks added in steps 2b/2d).
  var percept = perceive(bot.unpacked, bot.frameTick)

  # 2. Update belief with the percept.
  updateBelief(bot.belief, percept)

  # 2a. Actor scan (phase 1.3) — runs BEFORE localization so that
  #     other-player sprite and nameplate exclusions are in the ignore
  #     mask when the localizer scores the frame. Without this,
  #     crowded spawn areas (many visible players) push the error
  #     count above the localizer's budget and prevent any lock.
  percept.actors = scanAll(
    bot.actorScanner,
    bot.belief.percep,
    bot.belief.self,
    referenceData.sprites,
    bot.unpacked,
    percept.interstitial.isInterstitial)
  # Stamp actor sprite + nameplate exclusions into the ignore mask.
  # Sprite rects cover the detected sprite bounding box. Nameplate
  # rects cover the player-name text rendered by the server above
  # each sprite (PICO-8 font ~5px tall, centered horizontally;
  # names up to ~15 chars ≈ 60px wide). We use a generous margin
  # so variable-length names and slight position jitter are covered.
  let spriteW = referenceData.sprites.player.width
  let spriteH = referenceData.sprites.player.height
  for cm in percept.actors.crewmates:
    stampSpriteRect(percept.ignoreMask, cm.x, cm.y, spriteW, spriteH)
    stampNameplateRect(percept.ignoreMask, cm.x, cm.y, spriteW)
  let bodyW = referenceData.sprites.body.width
  let bodyH = referenceData.sprites.body.height
  for bm in percept.actors.bodies:
    stampSpriteRect(percept.ignoreMask, bm.x, bm.y, bodyW, bodyH)
    # Bodies don't have nameplates.
  let ghostW = referenceData.sprites.ghost.width
  let ghostH = referenceData.sprites.ghost.height
  for gm in percept.actors.ghosts:
    stampSpriteRect(percept.ignoreMask, gm.x, gm.y, ghostW, ghostH)
    # Ghosts don't have nameplates.

  # 2b. Camera localization (phase 1.2). Skip on interstitials.
  #     Runs after actor exclusions so crowded frames don't break
  #     the error budget.
  if percept.interstitial.isInterstitial:
    bot.localizer.reseedCameraAtHome(bot.belief.percep)
  else:
    let wasLocalized = bot.belief.percep.localized
    bot.localizer.updateLocation(
      bot.belief.percep,
      bot.unpacked,
      percept.ignoreMask.data,
      bot.frameTick)
    # One-shot diagnostic: log the very first successful localization.
    if localizeDebug and bot.belief.percep.localized and not wasLocalized and
       bot.localizer.diag.successes == 1:
      stderr.writeLine &"[localize t={bot.frameTick}] FIRST LOCK  cam=({bot.belief.percep.cameraX},{bot.belief.percep.cameraY}) self=({bot.belief.percep.selfX},{bot.belief.percep.selfY})"

    # 2b'. Voting-screen fallback probe. The voting screen often doesn't
    #      pass the 30%-black interstitial gate, so parseVotingScreen
    #      never runs and the bot idles through the entire meeting.
    #      When the localizer fails on a "gameplay" frame, periodically
    #      try the voting parse to catch this case.
    if not bot.belief.percep.localized and
       bot.belief.self.phase != PhaseVoting and
       (bot.frameTick - bot.lastVotingProbeTick) >= VotingProbeIntervalTicks:
      bot.lastVotingProbeTick = bot.frameTick
      let probe = parseVotingScreen(
        bot.unpacked,
        referenceData.sprites,
        bot.belief.self.colorIndex)
      if probe.valid:
        # The voting screen is up but the interstitial detector missed it.
        # Override phase and interstitial state so the rest of the pipeline
        # (reflex evaluation, mode switching) sees PhaseVoting correctly.
        bot.belief.self.phase = PhaseVoting
        bot.belief.percep.interstitialKind = InterstitialVoting
        percept.interstitial.isInterstitial = true
        percept.interstitial.kind = InterstitialVoting
        percept.votingParse = probe
        mergeVotingPercept(bot.belief, probe)
        # Reseed localizer so it doesn't keep trying to match map pixels
        # against the voting screen.
        bot.localizer.reseedCameraAtHome(bot.belief.percep)

  # 2c. Merge actor scan results into belief (needs camera for world
  #     coords, so stays after localization).
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

  # 2e'. Task-state machine update (phase 6.1). Runs after
  #      mergeTaskPercept so visibleTaskIcons and radarDots are current.
  ensureTaskSlotsInitialized(bot.belief)
  # Shield the hold target from icon-miss only when the task was previously
  # icon-confirmed. Checkout-only holds (no icon ever seen) remain unshielded
  # so wrong-task detection still works quickly.
  let holdIdx = block:
    if bot.modeScratch.mode == ModeTaskCompleting and
       bot.modeScratch.tcPhase == TpHold:
      let idx = bot.modeScratch.tcLockedTaskIndex
      if idx >= 0 and idx < bot.belief.tasks.slots.len and
         bot.belief.tasks.slots[idx].state == TaskConfirmed:
        idx
      else:
        -1
    else:
      -1
  # Confirm remains shielded because icon absence is the success signal
  # after a completed hold, not evidence that the station is unassigned.
  let confirmIdx = if bot.modeScratch.mode == ModeTaskCompleting and
                      bot.modeScratch.tcPhase == TpConfirm:
                     bot.modeScratch.tcLockedTaskIndex
                   else: -1
  updateTaskState(bot.belief, bot.frameTick, holdIdx, confirmIdx)

  # 2f. Interstitial classification (phase 1.5) + voting-screen parse
  #     (phase 1.6). Voting parse must keep running while PhaseVoting is
  #     active; otherwise cursor navigation acts on a stale first-frame
  #     cursor and never reaches its target.
  if percept.interstitial.isInterstitial:
    percept.votingParse = parseVotingScreen(
      bot.unpacked,
      referenceData.sprites,
      bot.belief.self.colorIndex)
    if percept.votingParse.valid:
      bot.belief.self.phase = PhaseVoting
      bot.belief.percep.interstitialKind = InterstitialVoting
      percept.interstitial.kind = InterstitialVoting
      # Voting is a new sub-phase — reset the OCR cache so a
      # subsequent non-voting interstitial gets re-classified.
      bot.interstitialClassified = false
    else:
      # classifyInterstitial is a full-frame OCR sweep (~22 ms).
      if not bot.interstitialClassified:
        let kind = classifyInterstitial(bot.unpacked)
        bot.cachedInterstitialKind = kind
        if kind != InterstitialUnknown:
          bot.interstitialClassified = true
      if bot.cachedInterstitialKind != InterstitialUnknown:
        bot.belief.percep.interstitialKind = bot.cachedInterstitialKind
        percept.interstitial.kind = bot.cachedInterstitialKind
        case bot.cachedInterstitialKind
        of InterstitialGameOver:
          bot.belief.self.phase = PhaseGameOver
        of InterstitialRoleReveal, InterstitialRoleRevealCrewmate,
           InterstitialRoleRevealImposter, InterstitialVoteResult:
          bot.belief.self.phase = PhaseInterstitial
        else:
          discard
      if bot.belief.self.role == RoleUnknown:
        case bot.cachedInterstitialKind
        of InterstitialRoleRevealImposter:
          bot.belief.self.role = RoleImposter
        of InterstitialRoleRevealCrewmate:
          bot.belief.self.role = RoleCrewmate
        else: discard
      # Scan for imposter teammate colors on any interstitial frame.
      # The histogram is self-validating: returns empty if no imposter
      # sprites are present (e.g. CREWMATE screen, lobby). We cache the
      # result and apply it once role is confirmed as imposter, since
      # role detection via HUD only fires AFTER the interstitial ends.
      if bot.belief.self.knownImposterColors.len == 0:
        let colors = scanRoleRevealImposters(
          bot.actorScanner, referenceData.sprites, bot.unpacked)
        if colors.len >= 1 and colors.len <= RoleRevealMaxDetectedColors:
          bot.cachedImposterColors = colors
    mergeVotingPercept(bot.belief, percept.votingParse)
  else:
    # Leaving interstitial phase — reset the cache for the next run.
    bot.interstitialClassified = false
    mergeVotingPercept(bot.belief, initVotingParse())

  # Log full per-frame perception output for offline visualization.
  logPerception(bot.trace, bot.frameTick, percept, bot.belief)

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

    # vent_witnessed: a player newly appeared on a previously-visible vent.
    for ci in 0 ..< PlayerColorCount:
      let ps = bot.belief.memory.perPlayer[ci]
      if ps.lastVentTick == tick:
        var payload = newJObject()
        payload["color"] = newJInt(ci)
        payload["position"] = %*[ps.lastVentX, ps.lastVentY]
        if ps.lastVentLabel.len > 0:
          payload["vent_label"] = newJString(ps.lastVentLabel)
        logGameEvent(bot.trace, "vent_witnessed", tick, $payload)
      if ps.lastNearVentTick == tick:
        var payload = newJObject()
        payload["color"] = newJInt(ci)
        payload["position"] = %*[ps.lastNearVentX, ps.lastNearVentY]
        payload["distance"] = newJInt(ps.lastNearVentDistance)
        payload["probability_pct"] = newJInt(ps.lastNearVentProbabilityPct)
        payload["score"] = newJInt(ps.nearVentEvidenceScore)
        if ps.lastNearVentLabel.len > 0:
          payload["vent_label"] = newJString(ps.lastNearVentLabel)
        logGameEvent(bot.trace, "vent_suspected", tick, $payload)

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
      # Apply cached interstitial imposter colors retroactively.
      # The scan ran during the interstitial (role still Unknown), but
      # now role is confirmed as imposter so we can commit the colors.
      if bot.belief.self.role == RoleImposter and
         bot.cachedImposterColors.len > 0:
        var added: seq[int] = @[]
        for ci in bot.cachedImposterColors:
          if rememberKnownImposterColor(bot.belief, ci):
            added.add ci
        if added.len > 0 and bot.trace != nil:
          var payload = newJObject()
          payload["source"] = newJString("role_reveal_cached")
          payload["partner_colors"] = %bot.belief.self.knownImposterColors
          payload["added_colors"] = %added
          payload["self_color"] = newJInt(bot.belief.self.colorIndex)
          payload["all_detected"] = %bot.cachedImposterColors
          logGameEvent(bot.trace, "imposters_detected",
                       bot.frameTick, $payload)
        bot.cachedImposterColors = @[]

    # chat_observed: OCR found durable new chat lines during voting.
    if bot.belief.social.pendingChatObserved.len > 0 and
       bot.belief.self.phase == PhaseVoting:
      for cl in bot.belief.social.pendingChatObserved:
        var payload = newJObject()
        if cl.speakerColor >= 0:
          payload["speaker"] = newJInt(cl.speakerColor)
        payload["text"] = newJString(cl.text)
        logGameEvent(bot.trace, "chat_observed", tick, $payload)
      bot.belief.social.pendingChatObserved.setLen(0)

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

  # 4a. Apply task completion from task_completing mode.
  # The mode signals completion via scratch; we apply it to belief
  # here to preserve the DESIGN.md §3 invariant.
  if bot.modeScratch.mode == ModeTaskCompleting and
     bot.modeScratch.tcCompletedTaskIndex >= 0:
    let ci = bot.modeScratch.tcCompletedTaskIndex
    if ci < bot.belief.tasks.slots.len:
      bot.belief.tasks.slots[ci].state = TaskCompleted
    # Trace: task_completed event.
    if bot.trace != nil:
      let tasks = referenceData.map.tasks
      var payload = newJObject()
      payload["task_index"] = newJInt(ci)
      if ci < tasks.len:
        payload["station_name"] = newJString(tasks[ci].name)
      payload["hold_duration_ticks"] = newJInt(
        bot.belief.tick - bot.modeScratch.tcHoldStartTick)
      logGameEvent(bot.trace, "task_completed", bot.belief.tick, $payload)
    bot.modeScratch.tcCompletedTaskIndex = -1

  # 4a'. Trace meeting vote attempts. The meeting mode sets
  # meetVoteConfirmed on the same tick it emits A, so this is one-shot.
  if bot.trace != nil and
     bot.modeScratch.mode == ModeMeeting and
     intent.pressA:
    var payload = newJObject()
    payload["cursor"] = newJInt(bot.belief.percep.votingCursor)
    payload["target"] = newJInt(bot.modeScratch.meetVoteTarget)
    payload["self_slot"] = newJInt(bot.belief.percep.votingSelfSlot)
    logGameEvent(bot.trace, "vote_attempted", bot.belief.tick, $payload)

  # 4a''. Meeting chat: the action layer owns the one-line outbound
  # buffer that the FFI/Python bridge drains after step_batch.
  if intent.chat.len > 0:
    let queued = emitChat(bot.actionState, bot.belief.tick, intent.chat)
    if queued and bot.trace != nil:
      var payload = newJObject()
      payload["text"] = newJString(bot.actionState.pendingChat)
      logGameEvent(bot.trace, "chat_sent", bot.belief.tick, $payload)

  # 4b. Trace: task_started event (Navigate→Hold transition detected
  #     by checking if we just entered Hold this tick).
  if bot.trace != nil and
     bot.modeScratch.mode == ModeTaskCompleting and
     bot.modeScratch.tcPhase == TpHold and
     bot.modeScratch.tcHoldStartTick == bot.belief.tick:
    let ti = bot.modeScratch.tcLockedTaskIndex
    let tasks = referenceData.map.tasks
    var payload = newJObject()
    payload["task_index"] = newJInt(ti)
    if ti >= 0 and ti < tasks.len:
      payload["station_name"] = newJString(tasks[ti].name)
    case bot.modeScratch.tcSelectionTier
    of TierIcon:     payload["selection_tier"] = newJString("icon")
    of TierCheckout: payload["selection_tier"] = newJString("checkout")
    of TierGeometry: payload["selection_tier"] = newJString("geometry")
    logGameEvent(bot.trace, "task_started", bot.belief.tick, $payload)

  # 4c. Reporting mode: give-up detection + trace events.
  if bot.modeScratch.mode == ModeReporting:
    # Trace: report_attempted when bot first reaches range.
    if bot.trace != nil and bot.modeScratch.repReachedRange and
       bot.modeScratch.repInRangeTicks <= 1:
      var payload = newJObject()
      payload["body_x"] = newJInt(bot.belief.directive.params.repBodyLocation.x)
      payload["body_y"] = newJInt(bot.belief.directive.params.repBodyLocation.y)
      payload["self_x"] = newJInt(bot.belief.percep.selfX)
      payload["self_y"] = newJInt(bot.belief.percep.selfY)
      logGameEvent(bot.trace, "report_attempted", bot.belief.tick, $payload)

    # Give-up: switch to default directive immediately.
    if bot.modeScratch.repGaveUp:
      if bot.trace != nil:
        var payload = newJObject()
        payload["reason"] = newJString(bot.modeScratch.repGaveUpReason)
        payload["ticks_in_mode"] = newJInt(
          bot.belief.tick - bot.modeScratch.repEnterTick)
        payload["reached_range"] = newJBool(bot.modeScratch.repReachedRange)
        logGameEvent(bot.trace, "report_gave_up", bot.belief.tick, $payload)
      switchMode(bot, defaultDirectiveFor(bot.belief))

  # 4d. Hunting mode: failed kill inference. The mode can only signal
  # suspected teammate evidence through scratch; the bot envelope owns
  # belief mutation and trace output.
  if bot.modeScratch.mode == ModeHunting and
     bot.modeScratch.huntFailedKillColor >= 0:
    let ci = bot.modeScratch.huntFailedKillColor
    let outcome = recordFailedKillSuspect(bot.belief, ci)
    if bot.trace != nil and outcome.count > 0:
      var payload = newJObject()
      payload["source"] = newJString("failed_kill")
      payload["target_color"] = newJInt(ci)
      payload["failed_count"] = newJInt(outcome.count)
      payload["threshold"] = newJInt(FailedKillImposterConfirmStrikes)
      payload["kill_ready_after"] = newJBool(bot.belief.percep.killReady)
      payload["known_imposters"] = %bot.belief.self.knownImposterColors
      logGameEvent(bot.trace, "imposter_teammate_suspected",
                   bot.belief.tick, $payload)
      if outcome.promoted:
        payload["known_imposters"] = %bot.belief.self.knownImposterColors
        logGameEvent(bot.trace, "imposter_teammate_inferred",
                     bot.belief.tick, $payload)
    bot.modeScratch.huntFailedKillColor = -1

  # 4e. Hunting mode: kill trace events.
  if bot.trace != nil and bot.modeScratch.mode == ModeHunting:
    # hunting_phase_changed: internal phase transition within ModeHunting.
    if bot.modeScratch.huntPhaseChanged:
      var payload = newJObject()
      payload["from_phase"] = newJString(
        huntingPhaseStr(bot.modeScratch.huntPrevPhase))
      payload["to_phase"] = newJString(
        huntingPhaseStr(bot.modeScratch.huntPhase))
      payload["reason"] = newJString(bot.modeScratch.huntPhaseReason)
      payload["target_color"] = newJInt(bot.modeScratch.huntTargetColor)
      payload["target_position"] = %*[bot.modeScratch.huntLastSeenX,
                                      bot.modeScratch.huntLastSeenY]
      payload["post_kill_plan"] = newJString(
        postKillPlanStr(bot.modeScratch.huntPostKillPlan))
      if bot.modeScratch.huntPostKillTargetValid:
        payload["post_kill_target"] = %*[bot.modeScratch.huntPostKillTargetX,
                                         bot.modeScratch.huntPostKillTargetY]
      logGameEvent(bot.trace, "hunting_phase_changed",
                   bot.belief.tick, $payload)
      bot.modeScratch.huntPhaseChanged = false

    # kill_attempted: huntStrikeTick was just set this tick.
    if bot.modeScratch.huntStrikeTick == bot.belief.tick:
      var payload = newJObject()
      payload["target_color"] = newJInt(bot.modeScratch.huntTargetColor)
      payload["distance"] = newJInt(
        abs(bot.belief.percep.selfX - bot.modeScratch.huntStrikeTargetX) +
        abs(bot.belief.percep.selfY - bot.modeScratch.huntStrikeTargetY))
      payload["witnesses"] = newJInt(bot.belief.percep.visibleCrewmates.len - 1)
      logGameEvent(bot.trace, "kill_attempted", bot.belief.tick, $payload)

    # kill_confirmed: flag set by the mode.
    if bot.modeScratch.huntKillConfirmed:
      var payload = newJObject()
      payload["target_color"] = newJInt(bot.modeScratch.huntLastKillTargetColor)
      payload["strike_position"] = %*[bot.modeScratch.huntStrikeTargetX,
                                      bot.modeScratch.huntStrikeTargetY]
      logGameEvent(bot.trace, "kill_confirmed", bot.belief.tick, $payload)
      bot.modeScratch.huntKillConfirmed = false

  # 5. Act.
  var mask = applyIntent(bot.actionState, bot.belief, intent)

  # Phase 4: log the decision and periodic snapshots. Runs after
  # applyIntent so the final button mask is included in the trace.
  if bot.trace != nil:
    logDecision(bot.trace, bot.belief, intent, "", bot.actionState, mask)
    let modeSummary = summarizeForLlm(bot.belief.directive.mode,
                                      bot.belief,
                                      bot.belief.directive.params,
                                      bot.modeScratch)
    logSnapshot(bot.trace, bot.belief.tick, bot.belief, modeSummary)

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
