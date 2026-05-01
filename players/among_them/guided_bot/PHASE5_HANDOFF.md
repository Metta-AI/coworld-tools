# Phase 5 Handoff Report

> Written 2026-05-01 after completing phase 4 (structured trace writer).
> Audience: the coding agent picking up phase 5 (fallback-only
> playability test + first submission). Everything in this file is
> context that isn't captured in the existing docs (DESIGN.md, README.md,
> MISSION.md) or is scattered across files and easy to miss.

---

## What exists now

The guided_bot has:

- **Phase 1 (perception):** full pixel pipeline — frame unpacking,
  camera localization, actor/body/ghost scanning, task-icon + radar-dot
  scanning, ASCII OCR, voting-screen parse. All via shared kernels in
  `among_them/common/perception_kernels/`.
- **Phase 2 (action layer):** A\* pathfinding, button-mask generation,
  stuck detection, jiggle, ghost steering. Six mode handlers
  (`task_completing`, `meeting`, `hunting`, `pretending`, `reporting`,
  `fleeing`) plus 4 reflexes.
- **Phase 3 (LLM guidance):** async worker thread calling Anthropic
  Messages API. Gameplay directives + meeting actions. Degrades
  gracefully on no key / LLM failure.
- **Phase 4 (trace writer):** structured JSONL output per DESIGN.md
  section 11. Opt-in via `GUIDED_BOT_TRACE_DIR` / `GUIDED_BOT_TRACE_LEVEL`.
  7 streams + manifest + optional frames.bin. Worker-thread events
  use a `Channel[string]` for GC-safety.

All 7 test suites pass. Library + CLI builds green.

### Key files for phase 5

```
bot.nim                — initBot (reads trace env vars), decideNextMask, destroyBot
mode_registry.nim      — defaultDirectiveFor (per-role defaults)
modes/meeting.nim      — safety-net fallback (forces SKIP near timer expiry)
modes/task_completing.nim — crewmate task completion (nearest mandatory)
modes/hunting.nim      — imposter default (opportunistic kill)
cogames/
  amongthem_policy.py  — cogames MultiAgentPolicy wrapper (ctypes FFI)
  ship.sh              — dry-run / upload / ship convenience wrapper
ffi/lib.nim            — FFI exports (guidedbot_step_batch, ABI version)
trace.nim              — trace writer (can be used to verify behavior)
```

### Files you'll read but probably not change

```
belief.nim             — belief state (what the bot knows)
perception.nim         — perceive() pipeline
action.nim             — applyIntent (mask emission)
reflex.nim             — 4 starter reflexes
tuning.nim             — cadence knobs
guidance.nim           — worker thread + channels
llm.nim                — Anthropic API client
```

---

## Phase 5 goal: fallback-only playability + first submission

Two deliverables, in order:

### 5.1 Fallback-only playability test (DESIGN.md section 9.2)

A test that proves the bot plays a full match without the LLM.
The spec from DESIGN.md section 9.2:

> A dedicated test will run a full match with the LLM **forcibly
> disabled** (returns errors to every call). The bot must:
>
> - Play every phase without crashing.
> - Cast a vote in every meeting (even if always skip).
> - Have at least one non-no-op action per 10-tick window during
>   gameplay. (Passes the cogames validation gate.)
> - Complete at least one task as a crewmate in a representative
>   match.

**Two approaches, from simplest to most thorough:**

#### Approach A: Deterministic fixture replay (no server)

Add a test (e.g. `test/fallback_test.nim`) that:

1. Creates a bot with `ANTHROPIC_API_KEY` unset (or forcibly cleared).
2. Replays the existing fixture frames through `stepUnpackedFrame`.
3. Asserts non-NOOP masks within the first 10 frames (proves the
   default directive fires immediately — passes the cogames
   validation gate).
4. Asserts the bot switches mode when it encounters voting frames
   (proves the meeting reflex fires).

This is quick, deterministic, and doesn't need a running server.
It proves the defaults-only path works through the validation gate.
The fixture frames are at `test/fixtures/gameplay_frames.bin` (275
frames, 128x128 bytes each).

#### Approach B: Full local match (needs server)

Run a full episode with `scripts/play_local.py`:

```sh
PYTHONPATH=among_them \
ANTHROPIC_API_KEY= \
GUIDED_BOT_TRACE_DIR=/tmp/fallback_test_trace \
GUIDED_BOT_TRACE_LEVEL=decisions \
  python among_them/scripts/play_local.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --duration 60
```

Then inspect the trace output to verify:
- `events.jsonl` has `meeting_started` events.
- `decisions.jsonl` shows `directive_source: "default"` throughout
  (no LLM directives).
- `modes.jsonl` shows transitions (at minimum: idle -> task_completing
  and some_mode -> meeting on voting).
- No crash / traceback in stderr.

This requires the Nim server (`~/coding/bitworld/out/among_them`)
and filler bots (`~/coding/bitworld/out/nottoodumb`). The
`play_local.py` script handles spawning them.

**Recommendation:** Do Approach A first (fast, CI-friendly), then
Approach B as a manual smoke check.

### 5.2 First submission

Once fallback playability is confirmed:

1. **Check for a live Among Them season:**
   ```sh
   cogames season list
   ```
   If `among-them` is back, submit there. If not, check whether the
   bot can be adapted for `beta-cvc` or `beta-teams-tiny-fixed`
   (different games — probably not without new modes).

2. **Dry-run:**
   ```sh
   SEASON=among-them POLICY_NAME=$USER-guided-bot \
     among_them/guided_bot/cogames/ship.sh dry-run
   ```
   Expected outcome: "Policy took no actions (all no-ops)" failure
   **should not happen** — the defaults-only path emits real actions
   from tick 1. If it passes, proceed. If it fails with the no-op
   message, something is wrong with the FFI path or the Docker
   environment.

3. **Ship:**
   ```sh
   SEASON=among-them \
   POLICY_NAME=$USER-guided-bot \
   ANTHROPIC_API_KEY=sk-ant-... \
     among_them/guided_bot/cogames/ship.sh ship
   ```
   The API key is passed via `--secret-env` so the tournament runner
   can call the LLM.

4. **Record the submission** in `README.md` section "Submission log".

---

## Architecture notes for phase 5

### Default directive path

When no LLM directive is available (startup, TTL expiry, LLM failure),
`mode_registry.nim:defaultDirectiveFor` picks:

| Condition | Default mode |
|---|---|
| Ghost | `task_completing` (finish tasks as ghost) |
| Voting phase | `meeting` (safety-net fallback votes SKIP) |
| Dead, not ghost | `idle` |
| Imposter, alive | `hunting` (opportunistic, cover via pretending) |
| Crewmate, alive | `task_completing` (nearest mandatory) |
| Unknown role | `idle` |

This is the behavior the fallback test exercises.

### Meeting fallback

`modes/meeting.nim` has a safety-net: when the meeting timer nears
expiry (`MeetingFallbackTicksLeft` = 100 ticks remaining) and no
vote has been confirmed, it forces cursor-right-to-SKIP + press-A.
This ensures the bot always votes even without the LLM.

### Validation gate

The cogames 10-step dry-run requires `non_noop_actions > 0` within
10 frames. The bot's default directive is `task_completing` (crewmate)
or `hunting` (imposter), both of which emit directional movement on
the first frame after camera localization succeeds (~1-3 frames).
This should comfortably pass the gate without `--skip-validation`.

### Trace writer for debugging

Phase 4's trace writer is invaluable for debugging submission issues.
Enable it during local testing:

```sh
GUIDED_BOT_TRACE_DIR=/tmp/gb_trace GUIDED_BOT_TRACE_LEVEL=decisions
```

Check `decisions.jsonl` to see what modes are active and what
actions are being emitted. Check `events.jsonl` for game events.
Check `guidance.jsonl` to see if the LLM is being called and what
it returns.

---

## Gotchas from phase 4

1. **Trace env vars read in `initBot`.** The `GUIDED_BOT_TRACE_DIR`
   and `GUIDED_BOT_TRACE_LEVEL` env vars are read once at bot
   construction. In the FFI path, `guidedbot_new_policy` calls
   `initBot` for each agent, so env vars must be set before the
   Python wrapper loads the library.

2. **Game-event edge detection state lives on Bot.** Phase 4 added
   `prevBodyCount`, `prevRole`, `prevPhaseForTrace`, `prevChatLen`
   to the `Bot` object. These are reset on `initBot` but not on
   `destroyBot` — they're meaningless after destruction.

3. **`destroyBot` closes the trace.** If you add a test that creates
   and destroys bots, make sure the trace dir either doesn't exist
   or is cleaned up between runs.

4. **`traceEventChan` in guidance.nim.** Worker-thread trace events
   are pre-serialized JSON strings pushed onto a `Channel[string]`.
   The main thread drains them in `decideNextMask` via
   `drainGuidanceTraceEvents`. If the guidance worker isn't started
   (no API key), the channel is never opened and drain is a no-op.

5. **`logSnapshot` cadence.** Snapshots are logged every 240 ticks
   at `TraceFull` level only. The constant is in `trace.nim`, not
   `tuning.nim` (it's trace-internal, not a gameplay knob).

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

# Local match (needs server binaries):
PYTHONPATH=among_them python among_them/scripts/play_local.py \
  -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
  --duration 30

# Dry-run submission:
SEASON=among-them POLICY_NAME=test-guided-bot \
  among_them/guided_bot/cogames/ship.sh dry-run
```

---

## Recommended implementation order

1. **Fixture-replay fallback test** (Approach A). Add
   `test/fallback_test.nim`. Replay fixture frames with no API key.
   Assert non-NOOP within 10 ticks and mode transitions on voting
   frames. This is the minimum viable deliverable.

2. **Manual local-match smoke check** (Approach B). Run
   `play_local.py` with the guided_bot policy and no API key for
   60 seconds. Inspect trace output. Confirm no crashes, meetings
   voted, tasks attempted.

3. **Dry-run submission.** Run `ship.sh dry-run`. If the Among Them
   season isn't live, document the result and the blocker.

4. **Ship with API key.** Run `ship.sh ship` with
   `ANTHROPIC_API_KEY` set. Record the submission in README.md.

5. **Post-submission.** Check leaderboard. Compare LLM-enabled vs.
   defaults-only scores. Update README.md with results.

---

## Files to read first

In order:
1. This file
2. `DESIGN.md` section 9 (failure modes & fallback)
3. `mode_registry.nim` — `defaultDirectiveFor` (the code that runs
   when there's no LLM)
4. `modes/meeting.nim` — safety-net fallback behavior
5. `modes/task_completing.nim` — crewmate default behavior
6. `cogames/ship.sh` — submission wrapper
7. `cogames/amongthem_policy.py` — Python policy class
8. `ffi/lib.nim` — FFI exports and action table
