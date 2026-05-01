# Phase 4 Handoff Report

> Written 2026-05-01 after completing phase 3 (LLM guidance loop).
> Audience: the coding agent picking up phase 4 (structured trace
> writer) and phase 5 (fallback-only playability test + first
> submission). Everything in this file is context that isn't captured
> in the existing docs (DESIGN.md, README.md, MISSION.md) or is
> scattered across files and easy to miss.

---

## What exists now

The guided_bot has a complete perception pipeline (phases 0-1.6), a
complete action layer with six mode handlers (phase 2.0-2.7), and a
complete LLM guidance loop (phase 3.1-3.6). The bot receives
strategic directives from an Anthropic LLM during gameplay and takes
LLM-driven actions during meetings. It degrades gracefully without
an API key — scripted defaults keep it playing. All 7 test suites
pass; both CLI and library builds succeed.

### Files you'll touch most in phase 4

```
trace.nim              — stub you're filling in (7 JSONL streams + manifest)
bot.nim                — call sites for logDecision, logModeEntered, etc.
mode_registry.nim      — may need logModeEntered/Exited calls in dispatch
reflex.nim             — logReflexFired call sites
guidance.nim           — logGuidanceEvent call sites (snapshot_sent, llm_response, etc.)
snapshot.nim           — logSnapshots periodic dump source
types.nim              — if you need new types for trace payloads
```

### Files you'll read but probably not change

```
belief.nim             — belief state structure (what gets serialized)
perception.nim         — perceive() pipeline (timing events)
action.nim             — applyIntent (mask emission)
llm.nim                — LLM result types (latencyMs, promptTokens, etc.)
tuning.nim             — cadence knobs (trace might add its own)
modes/*.nim            — branch IDs will need to be emitted per decide()
```

---

## The trace schema (DESIGN.md §11)

### Files per round

| File | Content |
|---|---|
| `manifest.json` | Round metadata: seed, match id, role, tournament config, tuning snapshot, bot version, schema version, start/end ticks, outcome. |
| `events.jsonl` | Game events (body_seen, kill_witnessed, meeting_started, etc.). |
| `decisions.jsonl` | Per-frame mode / branch / intent log. |
| `modes.jsonl` | Mode transitions (entered, exited, reason). |
| `guidance.jsonl` | Outer-loop log: snapshots sent, LLM responses, directives. |
| `reflexes.jsonl` | Reflex firings and suppressions. |
| `snapshots.jsonl` | Periodic full-belief snapshots. |
| `frames.bin` (optional) | Raw unpacked frames for replay. |

See DESIGN.md §11.1-11.8 for the exact JSON shapes.

### Existing stub signatures (trace.nim)

```nim
type
  TraceLevel* = enum
    TraceOff
    TraceEvents
    TraceDecisions
    TraceFull

  TraceWriter* = ref object
    level*: TraceLevel
    rootDir*: string

proc openTrace*(rootDir: string, level: TraceLevel): TraceWriter
proc closeTrace*(trace: TraceWriter)
proc logDecision*(trace: TraceWriter, belief: Belief,
                  intent: ActionIntent, branchId: string)
proc logModeEntered*(trace: TraceWriter, tick: int, fromMode, toMode: ModeName,
                    params: ModeParams, reason: string)
proc logModeExited*(trace: TraceWriter, tick: int, mode: ModeName,
                   durationTicks: int)
proc logReflexFired*(trace: TraceWriter, tick: int, name: string,
                    fromMode, toMode: ModeName, toParams: ModeParams)
proc logGuidanceEvent*(trace: TraceWriter, payload: string)
proc logGameEvent*(trace: TraceWriter, kind: string, tick: int,
                  payload: string)
```

All procs are currently no-ops. Phase 4 replaces the bodies.

### Call-site inventory (where to wire trace calls)

| Trace proc | Where to call it |
|---|---|
| `logDecision` | `bot.nim:decideNextMask` after the `decide()` call returns an intent |
| `logModeEntered` | `bot.nim:switchMode` after `onEnter` completes |
| `logModeExited` | `bot.nim:switchMode` before `onExit` runs (capture duration) |
| `logReflexFired` | `bot.nim:reconcileDirective` when `rx.fired == true` |
| `logGuidanceEvent` | `guidance.nim:guidanceWorker` after each LLM call (snapshot_sent, llm_response, llm_call_failed) |
| `logGameEvent` | `belief.nim:mergeActorPercept` (body_seen), `mergeVotingPercept` (chat_observed, meeting_started), `mergePercept` (role_revealed, game_over) |

### Guidance trace challenge

`logGuidanceEvent` is called from the worker thread but the
`TraceWriter` lives on the `Bot` object (main thread). Options:

1. **Channel-based**: worker pushes trace events onto a channel;
   main thread drains them in `decideNextMask` alongside directives.
   Cleanest, follows the existing channel pattern.
2. **Direct file write with a lock**: worker writes to a separate
   `guidance.jsonl` file handle with a mutex. Simpler but introduces
   locking on the trace path.
3. **Thread-local buffer**: worker accumulates trace events in a
   thread-local seq; main thread swaps/drains it periodically. Low
   contention but more complex lifecycle.

Option 1 is recommended — it matches the snapshot/directive channel
pattern already in `guidance.nim`.

---

## Opt-in and non-perturbing

Per modulabot's tracing pattern:

- Tracing is opt-in via `MODULABOT_TRACE_DIR` (or an analogous
  `GUIDED_BOT_TRACE_DIR` env var) and `GUIDED_BOT_TRACE_LEVEL`.
- When off (`TraceOff` or no env var), every `log*` call should be a
  near-zero-cost no-op (check `trace == nil` early return).
- When on, trace I/O should not perturb the inner loop timing.
  JSONL writes are buffered; `frames.bin` (if enabled) is sequential
  append. No allocation-heavy serialization on the hot path.

---

## Phase 5: fallback-only playability test

After the trace writer works, the next deliverable is DESIGN.md §9.2:

> A dedicated test will run a full match with the LLM **forcibly
> disabled** (returns errors to every call). The bot must:
>
> - Play every phase without crashing.
> - Cast a vote in every meeting (even if always skip).
> - Have at least one non-no-op action per 10-tick window during
>   gameplay. (Passes the cogames validation gate.)
> - Complete at least one task as a crewmate in a representative
>   match.

This test requires a local Nim Among Them server
(`~/coding/bitworld/out/among_them`) and filler bots
(`~/coding/bitworld/out/nottoodumb`). The existing
`scripts/play_local.py` orchestrates this.

A simpler stepping-stone: add a deterministic smoke test that
replays the fixture frames with `ANTHROPIC_API_KEY` unset and
asserts the bot produces non-NOOP actions within 10 ticks (proving
the defaults-only path works through the validation gate).

---

## Build and test commands

```sh
# All tests (run from repo root):
for test in smoke perception_test data_test localize_test actors_test tasks_test ocr_voting_test; do
  nim c -r -d:release --threads:on --mm:orc \
    --path:among_them/guided_bot \
    "among_them/guided_bot/test/${test}.nim"
done

# Library build:
nim c -d:release --opt:speed --app:lib -d:guidedBotLibrary \
  --threads:on --mm:orc \
  -o:among_them/guided_bot/libguidedbot.dylib \
  among_them/guided_bot/guided_bot.nim

# CLI binary:
nim c -d:release --threads:on --mm:orc \
  -o:among_them/guided_bot/guided_bot \
  among_them/guided_bot/guided_bot.nim
```

---

## Gotchas from phase 3

1. **GC-safety with threads.** Nim 2.2.4 with `--mm:orc` enforces
   GC-safety at compile time. Global `seq`, `string`, or `ref`
   objects accessed from a `{.thread.}` proc cause a compile error.
   The guidance worker solved this by using thread-local variables
   (declared inside the proc body). The trace writer will face the
   same issue if it writes from the worker thread — use the channel
   approach (option 1 above) or thread-local buffers.

2. **`nim.cfg` for nimby packages.** Phase 3 added
   `among_them/guided_bot/nim.cfg` with `--path` entries for curly,
   jsony, libcurl, webby, zippy, crunchy. The trace writer shouldn't
   need new packages (std/json + std/streams + std/os suffice), but
   if you add one, update nim.cfg.

3. **Wake-flag lifecycle.** Phase 3 clears `belief.flags.wakeReasons`
   at the end of `decideNextMask`. The `perception_test.nim` had to
   be updated because external code can no longer observe wake flags
   after `stepUnpackedFrame`. If you add new trace events keyed on
   wake flags, read them before the clear.

4. **Meeting conversation flush.** `bot.nim` calls
   `flushMeetingConversation` when the phase transitions away from
   `PhaseVoting`. If the trace captures meeting conversation history,
   do it before the flush.

5. **`destroyBot` added in phase 3.** `bot.nim` now has a
   `destroyBot(bot)` proc that stops the guidance worker thread and
   joins it. The trace writer should flush and close files in
   `closeTrace` which should be called from `destroyBot` (or from
   the FFI teardown path).

---

## Recommended implementation order

1. **`TraceWriter` internal state.** Add file handles for each JSONL
   stream, a manifest record, and a trace-event channel (for worker
   thread events). Wire `openTrace` to create the directory structure
   and open files; `closeTrace` to flush and close.

2. **`logDecision` + `decisions.jsonl`.** Start with the simplest
   stream. Wire the call site in `bot.nim:decideNextMask` after the
   intent is produced. Emit one JSONL line per frame.

3. **`logModeEntered` / `logModeExited` + `modes.jsonl`.** Wire in
   `bot.nim:switchMode`. Track entry tick for duration calculation.

4. **`logReflexFired` + `reflexes.jsonl`.** Wire in
   `bot.nim:reconcileDirective`.

5. **`logGameEvent` + `events.jsonl`.** Wire in `belief.nim` merge
   procs. This is the trickiest because the belief module doesn't
   currently have access to the trace writer — you'll need to thread
   it through or use a different approach (return events from merge
   procs and have bot.nim log them).

6. **`logGuidanceEvent` + `guidance.jsonl`.** Add a trace-event
   channel to guidance.nim; worker pushes events; main thread drains
   in `decideNextMask`.

7. **`manifest.json`.** Write on `openTrace`; update on `closeTrace`
   with end-tick and outcome.

8. **`snapshots.jsonl`.** Periodic full-belief dumps. Reuse
   `snapshot.renderSnapshot` from phase 3.

9. **`frames.bin` (optional).** Raw frame append. Gated by trace
   level and an opt-in flag.

---

## Files to read first

In order:
1. This file
2. `DESIGN.md` §11 (trace schema — all subsections)
3. `trace.nim` — the stub you're filling in
4. `bot.nim` — where most call sites go
5. `guidance.nim` — where the worker-thread trace events originate
6. `belief.nim` — where game events are detected
7. `snapshot.nim` — reusable for snapshots.jsonl
