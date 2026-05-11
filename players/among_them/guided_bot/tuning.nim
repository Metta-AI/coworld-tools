## Cross-cutting tuning knobs for guided_bot.
##
## Per DESIGN.md §13 "Items explicitly deferred": exact TTLs and cadences
## are empirical. These values are rough starting points to make phase-0
## scaffolding compile and the bot's first games playable; expect them to
## change.
##
## Rule for what belongs here (borrowed from `modulabot/tuning.nim`):
##   - Numbers you'd actually A/B-test.
##   - Numbers referenced by more than one module.
## Magic numbers confined to a single module stay there.

const
  # --- Inner/outer loop cadence ---------------------------------------
  GuidancePeriodTicks*        = 120  ## Unconditional LLM call every N ticks (~5s at 24Hz).
  DirectiveDefaultTtlTicks*   = 360  ## LLM directive expires after N ticks (~15s).
  DirectiveExpiringSoonTicks* = 60   ## Wake the guidance loop this many ticks before TTL.

  # --- Reflex anti-thrash ---------------------------------------------
  ReflexCooldownTicks*        = 96   ## Per-reflex minimum gap between firings (~4s).

  # --- Meeting mode ----------------------------------------------------
  MeetingFallbackTicksLeft*   = 100  ## If no vote confirmed with <N ticks left, force no-LLM target.
  MeetingChatLineGapTicks*    = 12   ## Min ticks between chat packets (rate-limit self).
  MeetingDurationEstimateTicks* = 600 ## Conservative estimate of meeting duration (~25s at 24Hz).
  MeetingAutoVoteDelayTicks*  = 360  ## Auto-vote no-LLM target after 15s with no LLM action.
  MeetingCursorHoldTicks*     = 3    ## Ticks to hold a cursor pulse before releasing.
  MeetingLlmActionPeriodTicks* = 48   ## During meetings, ask for the next LLM action more often than gameplay.
  MeetingCrewEvidenceThreshold* = 5   ## Minimum fallback suspicion score before crew votes a player.
  MeetingBodyEvidenceRadius*  = 48   ## World-px radius for "seen near a body" memory evidence.
  MeetingBodyEvidenceCooldownTicks* = 72 ## Cooldown before counting the same near-body evidence again.
  MeetingChatMaxLen*          = 80   ## Hard cap for outbound chat text passed to the server.

  # --- Voting-screen detection fallback --------------------------------
  VotingProbeIntervalTicks*   = 12   ## Min ticks between voting-parse attempts on non-
                                     ## interstitial frames when localization is lost (~0.5s).
                                     ## Prevents expensive parse from running every tick during
                                     ## non-voting localization failures (kill animations, etc.).

  # --- Role / teammate detection ---------------------------------------
  KillIconRoleFrames*         = 3    ## Consecutive kill-HUD matches before Unknown→Imposter.
  KillIconCrewOverrideFrames* = 12   ## Stronger evidence needed to override OCR CREWMATE.
  RoleRevealMaxDetectedColors* = 3   ## Reject noisy IMPS scans that look like too many players.
  FailedKillImposterConfirmStrikes* = 2 ## Failed strikes needed before teammate inference.

  # --- Call-rate caps (LLM) -------------------------------------------
  LlmMaxCallsPerMatch*        = 120  ## Hard cap across a full match.
  LlmMinIntervalTicks*        = 12   ## Floor on LLM call frequency (~0.5s).

  # --- Task-completing lifecycle (TASK_COMPLETING_DESIGN.md §8) ------
  TaskHoldTicks*              = 74   ## A-hold duration. Server accepts ~72; pad only 2 ticks.
  TaskConfirmWindowTicks*     = 48   ## Post-hold observation window before timeout (~2s).
  TaskIconMissCompleteTicks*  = 4    ## Consecutive post-hold icon-absent frames to confirm completion.
  TaskIconMissResolveFrames*  = 6    ## Consecutive icon-absent frames for "not mine" pruning.
                                     ## Six frames (~0.25s) absorbs transient detection gaps from bob animation and
                                     ## edge clipping while still pruning genuinely absent icons quickly.
  TaskClearScreenMargin*      = 8    ## Pixel margin for "icon area fully on-screen" check.
  TaskConfirmMaxDistance*     = 80   ## Manhattan distance to abandon Confirm after relocation.
  RadarMatchTolerance*        = 2    ## Chebyshev distance for radar-dot → station matching.
  RadarRayIconPadding*        = 14   ## Half-extent of padded icon AABB for radar-ray tests.
  RadarRayMinPips*            = 1    ## Minimum detected pips required to run ray exclusion.
  PipDisappearGraceTicks*     = 5    ## Suppress icon-miss counting after radar pip count drops.
  TaskCommitTicks*            = 48   ## Hysteresis: keep target for at least N ticks (~2s).
  TaskReEvalPeriodTicks*      = 24   ## After hysteresis, reconsider locked Navigate targets at most this often (~1s).
  TaskSwitchDistanceRatio*    = 0.5  ## Same-tier switch only when candidate distance is below this fraction of current distance.

  # --- Idle-mode wander -----------------------------------------------
  IdleWanderPeriod*           = 36   ## Ticks per direction change in idle wander (~1.5s at 24Hz).

  # --- Reporting mode (REPORTING_DESIGN.md §4) -------------------------
  ReportBodyMatchRadius*      = 30   ## World-px radius for matching visible body to target.
  ReportBodyMissFrames*       = 36   ## Consecutive frames without body → give up (~1.5s).
  ReportApproachTimeoutTicks* = 240  ## Give up navigating after 10s without reaching range.
  ReportInRangeTimeoutTicks*  = 72   ## Give up pressing A after 3s in range without meeting.

  # --- Pretending mode (PRETENDING_DESIGN.md §4) -------------------------
  PreFakeHoldTicks*             = 60   ## Fake A-press duration during loiter (~2.5s at 24Hz).

  # --- Hunting mode (HUNTING_DESIGN.md §4) -----------------------------
  HuntCoverLoiterTicks*       = 72   ## Loiter at each cover station ~3s before moving.
  HuntAlibiFakeHoldTicks*     = 48   ## Fake A-hold while building cooldown alibi (~2s).
  HuntMemoryTicks*            = 72   ## Short visual pursuit memory after losing target (~3s).
  HuntSeekingMemoryTicks*     = 480  ## Long player-memory horizon for seeking likely rooms (~20s).
  HuntWitnessMemoryTicks*     = 180  ## Recent-memory horizon for predicted witnesses (~7.5s).
  HuntWitnessBaseRadius*      = 32   ## Base px radius for "could walk in soon" prediction.
  HuntWitnessPixelsPerTick*   = 1    ## Expansion rate for predicted witness reach.
  HuntIsolationRadius*        = 72   ## Other-player distance that breaks isolation.
  HuntKillConfirmTicks*       = 24   ## Check for cooldown/body confirmation after striking (~1s).
  HuntStrikeCommitTicks*      = 6    ## Keep kill-strike intent briefly, then disengage.
  HuntKillConfirmRadius*      = 30   ## World-px radius for matching body to strike target.
  HuntKillStrikeRange*        = 20   ## World-px distance for pressing A (matches server KillRange).
  HuntPostKillTicks*          = 192  ## Deliberate alibi phase after a strike (~8s).
  HuntPostKillFakeHoldTicks*  = 60   ## Fake task hold inside post-kill alibi (~2.5s).
  HuntPostKillAvoidRadius*    = 96   ## Prefer post-kill stations at least this far from strike.
  HuntPostKillVentRadius*     = 72   ## Vent entry must be this close to be a post-kill plan.
  HuntVentNearDistance*       = 64   ## Kill-site score bonus radius for nearby vents.
  HuntLateGameKnownCrewMax*   = 2    ## If only this many known crew remain, tolerate risk.
  HuntLateGameWitnessBonus*   = 1    ## Extra witness allowance in known late game.
