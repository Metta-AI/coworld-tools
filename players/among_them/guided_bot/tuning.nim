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
  ReflexCooldownTicks*        = 48   ## Per-reflex minimum gap between firings (~2s).

  # --- Meeting mode ----------------------------------------------------
  MeetingFallbackTicksLeft*   = 100  ## If no vote confirmed with <N ticks left, force skip.
  MeetingChatLineGapTicks*    = 12   ## Min ticks between chat packets (rate-limit self).

  # --- Call-rate caps (LLM) -------------------------------------------
  LlmMaxCallsPerMatch*        = 120  ## Hard cap across a full match.
  LlmMinIntervalTicks*        = 12   ## Floor on LLM call frequency (~0.5s).

  # --- Task-completing defaults ---------------------------------------
  TaskHoldTicksDefault*       = 48   ## Baseline hold-A duration for completing a task.
