# Phase 6.3 — `meeting` Mode: Cursor Navigation + Timer Fix

> **Scope:** Fix two of three meeting mode problems: blind cursor
> navigation and hardcoded timer. Chat emission is deferred (requires
> FFI plumbing across Nim/C/Python).
>
> **Parent doc:** `DESIGN.md` §7 (meeting mode).
>
> Last updated: 2026-05-01

---

## 1. What exists today

### 1.1 Mode handler (`modes/meeting.nim`, 193 LOC)

- LLM-driven action queue: `speak`, `vote`, `confirm_vote`, `unvote`,
  `wait`. Actions popped one-per-tick from `scratch.meetPendingActions`.
- Safety-net fallback: forces cursor-right + A when
  `estimatedTicksLeft <= MeetingFallbackTicksLeft (100)`.
- Vote soft-lock: once `meetVoteConfirmed`, returns `noOpIntent()`.

### 1.2 Voting parse (`perception/voting.nim`)

The parser runs every interstitial frame and produces `VotingParse`
with:
- `valid: bool` — parse succeeded.
- `playerCount: int` — number of players in the vote grid.
- `cursor: int` — current cursor slot index, or `playerCount` for
  SKIP, or `-1` if unknown.
- `selfSlot: int` — our slot index, or `-1`.
- `slots[16]` — per-slot alive/dead + colour.
- `choices[16]` — per-voter vote target.
- `chatLines` — speaker-attributed chat.

Currently `mergeVotingPercept` only copies `chatLines` into belief.
The cursor position, playerCount, selfSlot, and slot data are
discarded.

### 1.3 Problems addressed in this phase

**Problem 1 — Blind cursor.** `cursorDirectionForTarget` always
returns `CursorRight` regardless of target. The LLM's `vote`
action specifying a target color is ignored. The cursor hammers
right until the fallback fires, which means the bot either votes
SKIP (if it wraps around) or votes for whoever the cursor lands on
(arbitrary).

**Problem 2 — Hardcoded timer.** `typicalMeetingDuration = 1200`
(~50s), but the local server uses `voteTimerTicks = 600` (~25s).
The fallback triggers at tick 1100 into the meeting — but the
meeting only lasts 600 ticks. **The safety-net never fires.** The
bot never votes unless the LLM explicitly issues `confirm_vote`.

### 1.4 Problem deferred

**Chat emission.** `MeetingActSpeak` sets `intent.chat` but
`action.nim:emitChat` is a stub. Chat requires a Nim buffer + C FFI
export (`guidedbot_take_chat`) + Python `bitworld_chat_messages()`
method, following mod_talks' pattern. Deferred to a separate phase.

---

## 2. Design

### 2.1 Merge voting parse into belief

Add fields to `PerceptionState` (or a new `VotingState` sub-record
on belief — but keeping it on `PerceptionState` is simpler and
consistent with how other perception data is stored):

```nim
# On PerceptionState:
votingCursor*: int          ## Current cursor slot, playerCount=SKIP, -1=unknown.
votingSelfSlot*: int        ## Our slot, -1=unknown.
votingPlayerCount*: int     ## Number of players in the grid.
votingValid*: bool          ## True when the current frame has a valid parse.
```

`mergeVotingPercept` is extended to copy these fields alongside
chatLines. They are cleared to defaults (`-1`, `0`, `false`) on
non-voting frames (when `mergePercept` detects a phase change away
from voting).

### 2.2 Cursor-aware navigation

Replace the blind `cursorDirectionForTarget` with position-aware
navigation using `belief.percep.votingCursor`.

**Slot layout:** The voting grid has `playerCount` player slots
(indices 0..playerCount-1) plus a SKIP slot (index playerCount).
The cursor wraps: right from SKIP goes back to slot 0, left from
slot 0 goes to SKIP.

**Navigation algorithm:**

Given `currentCursor` and `targetSlot`:
1. If `currentCursor == targetSlot`: cursor is already on target.
   Return `CursorNone`.
2. If `currentCursor < 0` (unknown): fall back to `CursorRight`
   (the old behavior, as a safety net).
3. Otherwise compute the shortest path in either direction around
   the wrapped ring of `playerCount + 1` positions (player slots +
   SKIP). Pick `CursorLeft` or `CursorRight` accordingly.

The total ring size is `playerCount + 1`. For 8 players, that's 9
positions — worst case 4 cursor moves in the optimal direction.

**Target mapping:** The LLM's `MeetingActVote` carries
`target: int` (color index or -1 for skip). To map this to a slot
index:
- If `target == -1`: target slot = `playerCount` (SKIP).
- Otherwise: target slot = `target` (color index == slot index in
  the Among Them grid, since slot `i` has `colorIndex == i` per the
  strict validator in `voting.nim:364`).

**Multi-tick navigation:** The cursor needs to be held for a few
ticks per step (`CursorHoldTicks = 3`). The mode needs scratch
state to track:
- `meetVoteTarget: int` — the slot we're navigating to (-1 = none).
- `meetCursorMoveTicks: int` — ticks remaining on the current
  cursor-direction hold.

Each tick during vote navigation:
1. If `meetCursorMoveTicks > 0`: continue emitting the same
   cursor direction. Decrement counter.
2. If `meetCursorMoveTicks == 0` and cursor != target: compute
   direction, set `meetCursorMoveTicks = CursorHoldTicks`, emit.
3. If cursor == target: stop moving. The next `MeetingActConfirmVote`
   from the LLM (or from the fallback) will press A.

### 2.3 Timer fix

Replace the hardcoded `typicalMeetingDuration = 1200` with a
tuning constant `MeetingDurationEstimateTicks = 600` in
`tuning.nim`. This matches the local server config. If the
tournament uses a different value, the LLM should vote before the
fallback fires anyway; the fallback is just the safety net.

With `MeetingDurationEstimateTicks = 600` and
`MeetingFallbackTicksLeft = 100`, the fallback fires at tick 500
into the meeting — 100 ticks (~4s) before the meeting ends. This
gives enough time for the cursor-right-to-SKIP + confirm-A
sequence.

### 2.4 Fallback improvement

The existing fallback hammers `CursorRight` for 24 ticks then
presses A. With cursor tracking, the fallback can navigate directly
to SKIP:

1. Read `belief.percep.votingCursor`.
2. Compute the shortest path to SKIP (slot `playerCount`).
3. Navigate there, then press A.

If cursor position is unknown (parse failed), fall back to the old
behavior (CursorRight spam).

### 2.5 Fallback-only vote behavior (no LLM)

When no LLM is available (defaults-only path), the meeting mode
receives no `MeetingActVote` actions. The only vote comes from the
safety-net fallback. With the timer fix, this now actually fires.

An improvement for the no-LLM path: if no LLM action arrives
within `MeetingAutoVoteDelayTicks = 360` (~15s), automatically
navigate to SKIP and confirm. This ensures the bot votes even if
the LLM is slow or disabled, without waiting for the full meeting
timer to expire. This is more aggressive than the safety-net
(which fires at 100 ticks remaining) but only activates in the
absence of any LLM activity.

---

## 3. Scratch state changes

```nim
of ModeMeeting:
  meetEnterTick: int                    ## (exists)
  meetVoteConfirmed: bool               ## (exists)
  meetPendingActions: seq[MeetingAction] ## (exists)
  meetVoteTarget: int                   ## (new) Target slot for cursor nav, -1 = none.
  meetCursorMoveTicks: int              ## (new) Ticks remaining on current cursor hold.
  meetCursorDir: CursorDir              ## (new) Direction being held.
  meetLastLlmActionTick: int            ## (new) Tick of last LLM action received.
```

---

## 4. Tuning constants

| Constant | Value | Rationale |
|---|---|---|
| `MeetingDurationEstimateTicks` | 600 | Local server config. Conservative default. |
| `MeetingAutoVoteDelayTicks` | 360 | Auto-vote SKIP after 15s with no LLM action. |
| `CursorHoldTicks` | 3 | Already exists in meeting.nim as a local const; promote to tuning. |

`MeetingFallbackTicksLeft` already exists (100).

---

## 5. Trace events

No new event kinds. The existing `decisions.jsonl` records will show
the cursor direction and meeting state. If we want richer meeting
tracing, that's a future phase.

---

## 6. Files changed

| File | Change |
|---|---|
| `types.nim` | Add `votingCursor`, `votingSelfSlot`, `votingPlayerCount`, `votingValid` to `PerceptionState`. Expand `ModeScratch.ModeMeeting` with 4 new fields. |
| `tuning.nim` | Add `MeetingDurationEstimateTicks`, `MeetingAutoVoteDelayTicks`. Promote `CursorHoldTicks`. |
| `belief.nim` | Extend `mergeVotingPercept` to copy cursor/selfSlot/playerCount. Clear on non-voting frames. |
| `modes/meeting.nim` | Rewrite cursor navigation with position-aware shortest-path. Fix timer. Add auto-vote delay. Update fallback to use cursor tracking. |
| `IMPL_PLAN.md` | Mark 6.3 done, note chat deferred to separate item. |
| `README.md` | Update phase table. |

---

## 7. Implementation plan

### Step 1 — Type + tuning foundations
- Add 4 perception fields to `types.nim`.
- Add 4 scratch fields to `ModeScratch.ModeMeeting`.
- Add tuning constants.
- Verify: compile, existing tests pass.

### Step 2 — Merge voting parse into belief
- Extend `mergeVotingPercept` to copy cursor, selfSlot, playerCount,
  valid.
- Clear voting fields on phase transition away from voting.
- Verify: compile, existing tests pass.

### Step 3 — Rewrite meeting.decide()
- Cursor-aware navigation with shortest-path ring computation.
- Timer fix (use `MeetingDurationEstimateTicks`).
- Auto-vote delay (SKIP after `MeetingAutoVoteDelayTicks` with no
  LLM action).
- Improved fallback (navigate to SKIP using cursor tracking).
- Multi-tick cursor holds via scratch state.
- Verify: compile, all tests pass.

### Step 4 — Doc updates + live game validation
- Update IMPL_PLAN.md, README.md.
- Run all 8 test suites + library build.
- 30s live match with tracing.
- Verify in traces: meeting mode enters, cursor moves, vote happens
  before meeting ends.
