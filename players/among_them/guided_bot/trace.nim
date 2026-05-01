## Structured trace writer (phase 0 stub).
##
## Phase 0: every proc is a no-op. Phase 2 fills in the manifest +
## JSONL streams defined in DESIGN.md §11:
##
##   - manifest.json (round metadata, tuning snapshot)
##   - events.jsonl  (body_seen, kill_witnessed, meeting_started, ...)
##   - decisions.jsonl (per-frame mode / branch / intent)
##   - modes.jsonl   (mode_entered / mode_exited)
##   - guidance.jsonl (snapshot_sent / llm_response / directive_published)
##   - reflexes.jsonl (reflex_fired / reflex_suppressed)
##   - snapshots.jsonl (periodic full-belief snapshots)
##   - frames.bin    (optional)
##
## Keep the proc signatures here stable: call sites in `bot.nim`,
## `mode_registry.nim`, and `ffi/lib.nim` will reference them before
## phase 2 turns them on.

import types

type
  TraceLevel* = enum
    TraceOff
    TraceEvents
    TraceDecisions
    TraceFull

  TraceWriter* = ref object
    ## Phase 0: opaque placeholder. Fields added in phase 2.
    level*: TraceLevel
    rootDir*: string

proc openTrace*(rootDir: string, level: TraceLevel): TraceWriter =
  ## Phase 0: returns nil if tracing is off, otherwise a placeholder.
  if level == TraceOff or rootDir.len == 0: return nil
  TraceWriter(level: level, rootDir: rootDir)

proc closeTrace*(trace: TraceWriter) =
  discard trace

# The per-event writers are named now so call sites can reference them;
# they are intentional no-ops in phase 0.
proc logDecision*(trace: TraceWriter, belief: Belief,
                  intent: ActionIntent, branchId: string) =
  discard trace; discard belief; discard intent; discard branchId

proc logModeEntered*(trace: TraceWriter, tick: int, fromMode, toMode: ModeName,
                    params: ModeParams, reason: string) =
  discard trace; discard tick; discard fromMode; discard toMode
  discard params; discard reason

proc logModeExited*(trace: TraceWriter, tick: int, mode: ModeName,
                   durationTicks: int) =
  discard trace; discard tick; discard mode; discard durationTicks

proc logReflexFired*(trace: TraceWriter, tick: int, name: string,
                    fromMode, toMode: ModeName, toParams: ModeParams) =
  discard trace; discard tick; discard name; discard fromMode
  discard toMode; discard toParams

proc logGuidanceEvent*(trace: TraceWriter, payload: string) =
  discard trace; discard payload

proc logGameEvent*(trace: TraceWriter, kind: string, tick: int,
                  payload: string) =
  discard trace; discard kind; discard tick; discard payload
