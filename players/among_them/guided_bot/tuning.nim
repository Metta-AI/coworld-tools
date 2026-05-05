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
  MeetingFallbackTicksLeft*   = 100  ## If no vote confirmed with <N ticks left, force skip.
  MeetingChatLineGapTicks*    = 12   ## Min ticks between chat packets (rate-limit self).
  MeetingDurationEstimateTicks* = 600 ## Conservative estimate of meeting duration (~25s at 24Hz).
  MeetingAutoVoteDelayTicks*  = 360  ## Auto-vote SKIP after 15s with no LLM action.
  MeetingCursorHoldTicks*     = 3    ## Ticks to hold a cursor direction per step.

  # --- Call-rate caps (LLM) -------------------------------------------
  LlmMaxCallsPerMatch*        = 120  ## Hard cap across a full match.
  LlmMinIntervalTicks*        = 12   ## Floor on LLM call frequency (~0.5s).

  # --- Task-completing lifecycle (TASK_COMPLETING_DESIGN.md §8) ------
  TaskHoldTicks*              = 84   ## A-hold duration. Server accepts ~72; 84 pads 12 ticks.
  TaskConfirmWindowTicks*     = 48   ## Post-hold observation window before timeout (~2s).
  TaskIconMissCompleteTicks*  = 24   ## Consecutive icon-absent frames to confirm completion.
  TaskIconMissResolveFrames*  = 24   ## Consecutive icon-absent frames for "not mine" pruning.
  TaskClearScreenMargin*      = 8    ## Pixel margin for "icon area fully on-screen" check.
  RadarMatchTolerance*        = 2    ## Chebyshev distance for radar-dot → station matching.
  TaskCommitTicks*            = 48   ## Hysteresis: keep target for at least N ticks (~2s).

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
  HuntMemoryTicks*            = 48   ## Pursue last-known position for ~2s after losing visual.
  HuntKillConfirmTicks*       = 12   ## Check for kill success within ~0.5s of striking.
  HuntKillConfirmRadius*      = 30   ## World-px radius for matching body to strike target.
  HuntKillStrikeRange*        = 20   ## World-px distance for pressing A (matches server KillRange).
