# Phase 3 Handoff Report

> Written 2026-05-01 after completing phase 2 (action layer + mode
> strategies). Audience: the coding agent picking up phase 3 (LLM
> guidance loop + meeting LLM control). Everything in this file is
> context that isn't captured in the existing docs (DESIGN.md,
> README.md, MISSION.md) or is scattered across files and easy to miss.

---

## What exists now

The guided_bot has a complete perception pipeline (phases 0-1.6) and
a complete action layer with six mode handlers (phase 2.0-2.7). The
bot produces real button masks: crewmates navigate to tasks and hold
A to complete them, imposters hunt/pretend/flee, meetings vote SKIP,
and four reflexes fire on bodies and voting screens. The LLM is
**not wired** — every decision comes from scripted defaults.

### Files you'll touch most in phase 3

```
guidance.nim         — worker-thread shell (currently a stub)
llm.nim              — HTTP LLM client (currently a stub)
modes/meeting.nim    — needs to read the meeting-action queue
bot.nim              — needs to submit snapshots and read directives
belief.nim           — needs to read the directive channel
types.nim            — Snapshot, GuidanceState may need expansion
tuning.nim           — LLM cadence / cap knobs
```

### Files you'll read but probably not change

```
action.nim           — button mask generation (complete)
mode_registry.nim    — mode dispatch + default directives
reflex.nim           — reflex evaluation (complete)
perception/*         — perception pipeline (complete)
modes/idle.nim       — template for mode handlers
modes/task_completing.nim — crewmate default (complete)
modes/hunting.nim    — imposter default (complete)
modes/pretending.nim — imposter cover (complete)
modes/reporting.nim  — body report (complete)
modes/fleeing.nim    — imposter flee (complete)
```

---

## The pipeline ordering (bot.nim:decideNextMask)

```
1.  perceive(frame)           → interstitial + ignore mask
2.  updateBelief(percept)     → merge interstitial into belief, set phase
2a. localize                  → camera X/Y, selfX/selfY (gameplay only)
2b. actor scan                → crewmates/bodies/ghosts, role, self-colour
    stamp actor exclusions    → ignore mask refined
2c. merge actors into belief
2d. task/radar scan           → task icons, radar dots
    stamp task-icon exclusions
2e. merge tasks into belief
2f. interstitial classification (OCR) + voting parse (interstitial only)
    merge voting into belief
3.  reconcileDirective        → ghost override, reflex evaluation, legality
4.  decide                    → mode registry → ActionIntent
5.  applyIntent               → button mask
```

**Phase 3 work touches steps 2 and 3:**
- Step 2 (`updateBelief`) needs to read the directive channel from
  the guidance worker. If a fresh directive arrived, install it.
- Step 3 (`reconcileDirective`) already handles ghost override,
  reflexes, and illegality. The LLM directive feeds in via step 2.
- **New:** the main thread needs to submit belief snapshots to the
  guidance worker at step 2 (periodic or triggered by wake flags).
- **New:** meeting mode's `decide()` needs to read from the
  meeting-action channel instead of always voting SKIP.

---

## Current stub signatures (already compile)

### guidance.nim

```nim
type
  Snapshot = object
    tick: int
    payloadJson: string
    isMeeting: bool

  GuidanceState = object
    running: bool
    callsThisMatch: int
    lastCallTick: int
    meetingConversationJson: string

proc initGuidanceState(): GuidanceState
proc startGuidance(state: var GuidanceState)      # no-op
proc stopGuidance(state: var GuidanceState)       # no-op
proc submitSnapshot(state: var GuidanceState, snap: Snapshot)        # no-op
proc tryReceiveDirective(state: var GuidanceState, d: var Directive): bool  # false
proc tryReceiveMeetingAction(state: var GuidanceState, a: var MeetingAction): bool  # false
```

All procs are wired into `bot.nim` / `types.nim` but do nothing.
Phase 3 replaces the bodies.

### llm.nim

```nim
type
  LlmRequestKind = enum LlmReqGameplay, LlmReqMeeting
  LlmRequest = object
    kind: LlmRequestKind
    snapshotJson: string
    conversationJson: string

  LlmResultKind = enum LlmOk, LlmSchemaError, LlmHttpError, LlmTimeout, LlmRateLimit, LlmNoKey
  LlmResult = object
    kind: LlmResultKind
    directive: Directive           # valid iff kind == LlmOk and gameplay
    meetingAction: MeetingAction   # valid iff kind == LlmOk and meeting
    rawResponse, detail: string
    latencyMs, promptTokens, responseTokens: int

proc haveApiKey(): bool
proc callLlm(req: LlmRequest): LlmResult    # returns LlmNoKey or LlmSchemaError
```

Currently returns a stub result. Phase 3 wires in `curly` + `jsony`
HTTP calls to the Anthropic Messages API.

---

## What meeting mode does now (phase 2 fallback)

`modes/meeting.nim` is a time-based fallback:

1. For the first 24 ticks (~1 s), emit `CursorRight` every tick.
2. After a 2-tick gap, press A to confirm (votes SKIP).
3. Set `scratch.meetVoteConfirmed = true` and idle.

Phase 3 replaces this with:

1. On enter, fire an immediate LLM call with full meeting context.
2. Each LLM response produces a `MeetingAction` on the queue.
3. `decide()` pops one action per tick: `speak` emits chat,
   `vote` moves cursor to target, `confirm_vote` presses A.
4. Between actions, idle (no-op) until the next action or trigger.
5. Safety-net: if `MeetingFallbackTicksLeft` (100) ticks remain
   and no vote confirmed, force SKIP.

The `MeetingAction` type and `ModeScratch.meetPendingActions` seq
are already declared in `types.nim`.

---

## What the LLM needs to produce

### Gameplay response (stateless)

```json
{
  "mode": "task_completing",
  "params": { "target": { "kind": "nearest_mandatory" }, "abandon_on_nearby_body": true },
  "ttl_ticks": 240,
  "reasoning": "..."
}
```

The guidance loop validates mode name, `isLegalFor`, and params
schema before publishing. Invalid responses are dropped silently
(the inner loop keeps the previous directive or defaults).

### Meeting response (stateful, one action per call)

```json
{
  "action": "speak",
  "text": "I saw red near the body in electrical"
}
```

or

```json
{
  "action": "vote",
  "target": "red"
}
```

or `"confirm_vote"`, `"unvote"`, `"wait"`. See DESIGN.md §7.1.

---

## Prior art for the LLM client

```
~/coding/bitworld/src/bitworld/ais/claude.nim   — ~60 LOC Anthropic client
~/coding/bitworld/src/bitworld/ais/openai.nim   — ~60 LOC OpenAI client
~/coding/bitworld/among_them/players/italkalot.nim — Nim bot making live LLM calls
```

All use `curly` (Nim HTTP via libcurl) + `jsony` (fast JSON
serialization). The pattern is:
1. Build a JSON request body with `jsony.toJson`.
2. `curly.post(url, headers, body)` → response string.
3. `jsony.fromJson[T](response)` → typed result.

`curly` is already available in the nimby environment. `jsony` may
need `nimby install jsony` — check before coding.

---

## Concurrency: Nim threads + channels

DESIGN.md §10.2-10.3 specifies:

- **Main thread:** inner loop (perceive/update/decide/act). Owns
  belief, scratch, action state.
- **Worker thread:** blocks on snapshot channel, calls LLM, pushes
  directive (or meeting action) onto outgoing channel.

Nim `system.Channel[T]`:
- `snapshotChan`: main → worker. Bounded size 1 (newest wins).
- `directiveChan`: worker → main. Main reads non-blocking in
  `updateBelief`.
- `meetingActionChan`: worker → main. FIFO, one per tick during
  meetings.

The worker is never on the critical path. If the LLM is slow, the
inner loop continues on the current directive (or default).

**Threading gotcha:** Nim's `--threads:on --mm:orc` is already set
in the build commands. Channels require `import std/channels` (or
the older `system.Channel`). Thread creation is `createThread`.
Both are well-tested in the bitworld codebase.

---

## Snapshot rendering

The snapshot (DESIGN.md §8.3) is a JSON dump of curated belief
fields. Current belief state has all the data:

| Snapshot field | Belief source |
|---|---|
| `self.role` | `belief.self.role` |
| `self.color` | `PlayerColorNames[belief.self.colorIndex]` |
| `self.position` | `(belief.percep.selfX, belief.percep.selfY)` |
| `phase` | `belief.self.phase` |
| `visible_now.players` | `belief.percep.visibleCrewmates` (+ world-coord conversion) |
| `visible_now.bodies` | `belief.percep.visibleBodies` (+ world-coord conversion) |
| `task_state` | `belief.tasks` (partially populated; phase 2 uses raw icon matches) |
| `recent_chat` | `belief.social.currentMeetingChat` |
| `wake_up_reasons` | `belief.flags.wakeReasons` |
| `current_mode` | `belief.directive` |
| `memory.per_player` | `belief.memory.perPlayer` |

The `visible_now` fields need screen→world conversion using
`geometry.visibleCrewmateWorldX/Y` + `roomNameAt` for room names.

---

## Wake-up triggers

`belief.flags.wakeReasons` is a `set[WakeReason]`. Current triggers
that are already raised by the perception/belief pipeline:

| WakeReason | When raised |
|---|---|
| `WakeBodySeen` | `mergeActorPercept` detects bodies |
| `WakeChatObserved` | `mergeVotingPercept` finds chat lines |
| `WakeMeetingStarted` | `mergePercept` detects interstitial entry |
| `WakeReflexFired` | `reconcileDirective` after a reflex fires |

Not yet raised (phase 3 should wire):
| `WakeKillCooldownReady` | kill cooldown reaches 0 |
| `WakeRoleRevealed` | role detection fires in actor scan |
| `WakeDirectiveExpiringSoon` | directive TTL nearing expiry |

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

## Gotchas from phase 2

1. **Import paths differ between test and library builds.** Tests
   use `--path:among_them/guided_bot`, so mode files import
   `../perception/data`. The library build resolves from the
   `guided_bot.nim` entry point. Both work now, but if you add new
   imports in mode files, use `../` prefix relative to `modes/`.

2. **`GuidanceState` is on `Bot`, not threaded.** The stub currently
   lives on `Bot.guidance` as a plain object. Phase 3 needs to
   refactor this into a thread-safe structure with channels. The
   `Bot` object is owned by the main thread; the guidance state
   needs to be split into main-owned and worker-owned halves.

3. **`discard` warnings.** Several perception modules have unused
   import warnings (cosmetic). Don't chase them unless you're
   touching those files.

4. **Meeting mode's `tuning` import is unused.** The `import
   ../tuning` in `modes/meeting.nim` was added for
   `MeetingFallbackTicksLeft` but isn't used yet by the phase 2
   fallback. Phase 3 will use it.

5. **The directive channel read should happen in `updateBelief`,
   not in `reconcileDirective`.** Reconcile already handles ghost
   override, reflexes, and illegality. A fresh LLM directive should
   be installed before those checks run, so it gets the same
   validation pass. See DESIGN.md §4.2.

6. **`callLlm` is synchronous.** The stub blocks. In the real
   implementation this is fine because it runs on the worker thread,
   but if you prototype without threading first, it will block the
   inner loop. Use `--threads:off` + a timeout for initial testing,
   then add the thread.

7. **Meeting conversation history must be flushed on meeting end.**
   `GuidanceState.meetingConversationJson` persists for the current
   meeting. When the phase transitions away from `PhaseVoting`, the
   conversation must be cleared so the next meeting starts fresh
   (DESIGN.md §7.3).

---

## Recommended phase 3 implementation order

1. **Snapshot rendering.** Write a `renderSnapshot(belief): string`
   proc that produces the JSON from DESIGN.md §8.3. Test it
   against fixture frames to make sure it produces valid JSON with
   sensible field values.

2. **`llm.nim` — real HTTP client.** Adapt
   `bitworld/src/bitworld/ais/claude.nim`. Wire `curly.post` to the
   Anthropic Messages API. Parse the response JSON into a
   `Directive` (gameplay) or `MeetingAction` (meeting). Handle
   errors gracefully (timeout, rate limit, malformed JSON).

3. **`guidance.nim` — worker thread + channels.** Create
   `snapshotChan`, `directiveChan`, `meetingActionChan`. Spawn the
   worker in `startGuidance`. Worker loop: block on snapshot, call
   `callLlm`, push result. Main thread: non-blocking reads in
   `updateBelief` (directives) and `meeting.decide` (actions).

4. **Wire `bot.nim` — snapshot submission.** In `decideNextMask`,
   after `updateBelief`, check whether a snapshot should be sent
   (periodic every `GuidancePeriodTicks`, or triggered by wake
   flags). Call `submitSnapshot`. Read the directive channel and
   install fresh LLM directives.

5. **`modes/meeting.nim` — LLM-driven.** Replace the time-based
   SKIP fallback with queue-driven behavior: pop `MeetingAction`
   values, execute them (cursor navigation for votes, chat
   emission for speak). Keep the safety-net fallback for when the
   LLM is silent.

6. **Prompt design.** Write system prompts for gameplay (role
   briefing + directive format) and meeting (evidence summary +
   action format). This is iterative — start simple, measure,
   refine.

7. **Integration test.** Run a full local match with
   `scripts/play_local.py` and `ANTHROPIC_API_KEY` set. Verify:
   the LLM receives snapshots, returns directives, the bot changes
   behavior mid-match, meetings produce real votes/chat.

---

## Files to read first

In order:
1. This file
2. `DESIGN.md` §7 (meeting LLM control), §8 (guidance loop), §10 (concurrency)
3. `guidance.nim` — the stub you're filling in
4. `llm.nim` — the stub you're filling in
5. `modes/meeting.nim` — the mode you're upgrading
6. `bot.nim` — where snapshots are submitted and directives read
7. `~/coding/bitworld/src/bitworld/ais/claude.nim` — reference LLM client
8. `~/coding/bitworld/among_them/players/italkalot.nim` — existence proof
