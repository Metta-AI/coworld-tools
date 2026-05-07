# Meeting Mode — Design Document

> **Canonical reference** for the `meeting` mode handler. All meeting-
> mode design details live here; `DESIGN.md` contains only a brief
> overview and cross-reference.
>
> **Implementation:** `modes/meeting.nim` (232 LOC)
>
> Last updated: 2026-05-05

---

## 1. Purpose and role

The `meeting` mode handles all bot behavior during the voting phase
(emergency meetings and body reports). It is:

- **The target of the `voting_screen_appeared` reflex**
  (`reflex.nim:65-86`). When the game phase transitions to
  `PhaseVoting`, this reflex fires unconditionally (highest priority)
  and switches to `meeting` regardless of the current mode.
- **The voting-phase default directive** (`mode_registry.nim:103`).
  If the bot is already in voting phase when a default is evaluated,
  `meeting` is chosen.
- **LLM-driven via an action queue.** Unlike other modes which
  produce behavior from parameters alone, the meeting mode consumes
  a queue of `MeetingAction` values pushed by the guidance worker.
  The LLM controls what to say and who to vote for; the mode handles
  cursor navigation mechanics.

The mode is **only legal** during `PhaseVoting` (`isLegalFor` in
`modes/meeting.nim:20-21` checks `belief.self.phase == PhaseVoting`).
Any role (crewmate, imposter, ghost) can be in meeting mode during
voting.

---

## 2. Mode parameters

```text
meeting {
  meetWantToSpeakFirst: bool   # Hint to the LLM: generate chat before voting.
                               # Not read by decide() — purely informational for
                               # the guidance worker's prompt construction.
}
```

Implementation in `types.nim:269-270`:
```nim
of ModeMeeting:
  meetWantToSpeakFirst*: bool
```

**Default params** (from `modes/meeting.nim:23-25`):
- `meetWantToSpeakFirst: false`

The parameter is a soft hint — the mode's `decide()` ignores it.
The guidance worker reads it when constructing the LLM prompt.

---

## 3. Decision logic overview

`decide()` evaluates each tick with a priority cascade:

1. **Vote confirmed** — if `meetVoteConfirmed`, emit `noOpIntent()`
   (soft-lock: the bot is done for this meeting).
2. **Safety-net fallback** — if estimated time remaining ≤
   `MeetingFallbackTicksLeft` (100), navigate to SKIP and confirm.
3. **Auto-vote delay** — if no LLM action has ever arrived and
   `MeetingAutoVoteDelayTicks` (360) have elapsed, vote SKIP.
4. **Process LLM action** — pop one action per tick from
   `meetPendingActions` and execute it.
5. **Continue cursor navigation** — if a vote target is pending and
   not yet reached, keep moving the cursor.
6. **Idle** — no actions pending, no fallbacks triggered.

---

## 4. LLM action queue

The meeting mode receives instructions from the LLM via a queue of
`MeetingAction` values. These are pushed by `bot.nim:431-435` each
tick (pumped from the guidance channel into
`scratch.meetPendingActions`).

### 4.1 Action types

```nim
MeetingActionKind = enum
  MeetingActNone         # No-op (ignored).
  MeetingActSpeak        # Emit chat text.
  MeetingActVote         # Navigate cursor to a target slot.
  MeetingActUnvote       # Press B to deselect current vote.
  MeetingActConfirmVote  # Press A to confirm the current selection.
  MeetingActWait         # Explicit idle (one tick).

MeetingAction = object
  kind: MeetingActionKind
  text: string           # MeetingActSpeak: chat message.
  target: int            # MeetingActVote: color index, or -1 for SKIP.
```

Implementation in `types.nim:97-107, 193-196`.

### 4.2 Action processing

One action is popped per tick (FIFO). On pop:
- `meetLastLlmActionTick` is updated (disables auto-vote delay).
- The action is dispatched by kind.

The one-per-tick rate means a `vote → confirm_vote` sequence takes at
least 2 ticks plus cursor navigation time. The LLM should emit both
together; the queue handles sequencing.

### 4.3 Action behaviors

| Kind | Effect |
|---|---|
| `MeetingActSpeak` | Sets `intent.chat = text`. Currently a stub — FFI for chat emission is not wired. The text is placed on the intent for future use. |
| `MeetingActVote` | Sets `meetVoteTarget` and begins cursor navigation toward the target slot. |
| `MeetingActConfirmVote` | Sets `meetVoteConfirmed = true` and emits A press. Locks the mode. |
| `MeetingActUnvote` | Emits B press (deselects). Clears `meetVoteTarget`. |
| `MeetingActWait` | No-op for one tick. |
| `MeetingActNone` | No-op (defensive — shouldn't appear in practice). |

---

## 5. Cursor navigation

The voting screen has a cursor that the player moves to select a vote
target. The bot navigates this cursor using the voting parse's
real-time cursor position.

### 5.1 Voting ring

The cursor moves through a wrapped ring of positions:
- Slots 0..`playerCount-1`: player slots (color index == slot index).
- Slot `playerCount`: SKIP.
- Ring size: `playerCount + 1`.

Wrapping: right from SKIP → slot 0. Left from slot 0 → SKIP.

### 5.2 Shortest-path computation

`shortestCursorDir` (`modes/meeting.nim:50-65`) computes the optimal
direction:
- Compute right-distance: `(target - current + ring) mod ring`.
- Compute left-distance: `(current - target + ring) mod ring`.
- Pick the shorter direction.

For 8 players (ring size 9), worst case is 4 cursor moves.

### 5.3 Target mapping

`targetSlotForAction` (`modes/meeting.nim:67-75`):
- `target == -1` → SKIP (slot `playerCount`).
- `target >= 0` → color index (== slot index, per the Among Them
  voting grid where slot `i` has color index `i`).

### 5.4 Multi-tick cursor holds

The cursor needs to be held for multiple ticks per step for reliable
movement (`MeetingCursorHoldTicks = 3`). The state machine:

1. If `meetCursorMoveTicks > 0`: continue emitting the same cursor
   direction, decrement counter.
2. If `meetCursorMoveTicks == 0` and cursor != target: compute new
   direction, set `meetCursorMoveTicks = MeetingCursorHoldTicks - 1`
   (current tick counts as one), emit.
3. If cursor == target: stop. Return `noOpIntent()` and wait for
   the confirm action.

### 5.5 Unknown cursor fallback

If `belief.percep.votingCursor < 0` (parse failed, cursor unknown):
fall back to `CursorRight` (the old blind-navigation behavior).
This is a safety net — the voting parser should succeed on most frames.

---

## 6. Safety-net fallback

The structural backstop that ensures the bot always votes, even if
the LLM is slow or fails.

**Trigger:** `estimatedTicksLeft <= MeetingFallbackTicksLeft` (100
ticks, ~4s before meeting ends).

**Behavior:** navigate to SKIP using cursor tracking, then confirm.
If the cursor is already on SKIP, immediately confirm. If cursor
position is unknown, `navigateToSlot` falls back to CursorRight.

**Timer:** uses `MeetingDurationEstimateTicks` (600 ticks, ~25s) as
the meeting length estimate. The fallback fires at tick 500 into the
meeting.

**Non-overridable:** the LLM cannot prevent the fallback. Once
triggered, it navigates and confirms regardless of pending actions.

---

## 7. Auto-vote delay

For the no-LLM path (defaults-only, or LLM too slow).

**Trigger:** `meetLastLlmActionTick < 0` (no LLM action has ever
arrived this meeting) AND `ticksInMeeting >= MeetingAutoVoteDelayTicks`
(360, ~15s).

**Behavior:** same as fallback — navigate to SKIP and confirm.

**Purpose:** ensures the bot votes within 15s even without an LLM,
rather than waiting the full meeting timer. More aggressive than the
safety net but only activates in the absence of any LLM activity.

---

## 8. Vote soft-lock

Once `meetVoteConfirmed` is set true, the mode returns `noOpIntent()`
on every subsequent tick. The meeting is "done" from the bot's
perspective — it just waits for the voting phase to end.

This prevents:
- Re-voting after confirmation.
- The fallback from triggering after a successful LLM-directed vote.
- Any further cursor movement or button presses.

---

## 9. Chat emission (stub)

`MeetingActSpeak` places the chat text on `intent.chat`, but the
action layer's `emitChat` is currently a stub. Full chat requires:

- A Nim-side buffer for outgoing chat strings.
- A C FFI export (`guidedbot_take_chat`) for the Python bridge.
- Python-side `bitworld_chat_messages()` method integration.

Deferred to a separate implementation phase. The mode is structurally
ready — once FFI is wired, chat works without mode-side changes.

---

## 10. Scratch state

All fields are reset on mode entry (`onEnter`). Preserved across
directive changes within the same mode (per `DESIGN.md` §5.6).

```nim
of ModeMeeting:
  meetEnterTick*: int                    # Tick when meeting mode began.
  meetVoteConfirmed*: bool               # Soft-lock: vote is done.
  meetPendingActions*: seq[MeetingAction] # LLM action queue (FIFO).
  meetVoteTarget*: int                   # Target slot for cursor nav (-1 = none).
  meetCursorMoveTicks*: int              # Ticks remaining on current cursor hold.
  meetCursorDir*: CursorDir              # Direction being held.
  meetLastLlmActionTick*: int            # Tick of last LLM action (-1 = never).
```

Initial values on `onEnter`:
- `meetEnterTick = belief.tick`
- `meetVoteConfirmed = false`
- `meetPendingActions = @[]` (empty queue)
- `meetVoteTarget = -1` (no target)
- `meetCursorMoveTicks = 0`
- `meetCursorDir = CursorNone`
- `meetLastLlmActionTick = -1` (no LLM action yet)

---

## 11. Tuning constants

All live in `tuning.nim:22-27`:

| Constant | Value | Meaning |
|---|---|---|
| `MeetingFallbackTicksLeft` | 100 | Safety-net fires with ~4s remaining. |
| `MeetingDurationEstimateTicks` | 600 | Conservative meeting length estimate (~25s). |
| `MeetingAutoVoteDelayTicks` | 360 | Auto-vote SKIP after 15s with no LLM action. |
| `MeetingCursorHoldTicks` | 3 | Ticks to hold a cursor direction per step. |
| `MeetingChatLineGapTicks` | 12 | Min ticks between chat packets (rate-limit, future use). |

---

## 12. Reflex interactions

### 12.1 Incoming reflexes (other modes → meeting)

| Source mode | Condition | Params issued | Reflex name |
|---|---|---|---|
| Any mode | `PhaseVoting` entered (edge-triggered: `prevPhase != PhaseVoting`) | `meetWantToSpeakFirst: false`, TTL 0 | `voting_screen_appeared` |

This is the **highest-priority reflex** — it's evaluated first in
`evaluateReflexes` (`reflex.nim:65-86`) and fires regardless of
current mode. It has no TTL (meetings last until the phase ends
naturally).

### 12.2 Outgoing reflexes (meeting → other modes)

None. The meeting mode is only exited by:
- Phase change: when `PhaseVoting` ends, `isLegalFor` returns false,
  and `reconcileDirective`'s illegality check (`bot.nim:263-264`)
  switches to the default directive.
- This is the only mode that exits via illegality rather than TTL or
  reflex.

### 12.3 Cooldown

The `voting_screen_appeared` reflex is subject to
`ReflexCooldownTicks` (96 ticks, ~4s). In practice this never
matters — voting phases don't end and restart within 4 seconds.

---

## 13. Trace events

No mode-specific trace events are emitted. The standard trace captures:

- `meeting_started` event in `bot.nim:461-463` (on PhaseVoting entry).
- `chat_observed` events for incoming chat lines.
- Mode entry/exit via `modes.jsonl`.
- `decisions.jsonl` records cursor direction and button presses each
  tick, showing the full cursor navigation sequence.

A future enhancement could add `vote_cast` (when `meetVoteConfirmed`
is set) with the target color — deferred.

---

## 14. Action layer contract

The meeting mode does not use steering-based disciplines. All intents
use `DisciplineNoOp` with button/cursor fields set directly:

- **Cursor movement:** `cursor: CursorLeft | CursorRight` with no A/B.
- **Vote confirm:** `pressA: true` with no cursor or steering.
- **Unvote:** `pressB: true` with no cursor or steering.
- **Chat:** `chat: <text>` with no buttons (stub path).
- **Idle:** `noOpIntent()` — no buttons, no cursor, no steering.

`steerValid` is always `false` during meetings (no world-space
navigation occurs during voting).

---

## 15. Pipeline integration

The meeting mode has special pipeline support in `bot.nim`:

### 15.1 Action queue pumping (bot.nim:431-435)

Each tick during `PhaseVoting`, the bot pipeline reads meeting actions
from the guidance channel and appends them to
`scratch.meetPendingActions`:

```nim
while tryReceiveMeetingAction(bot.guidance, meetAction):
  bot.modeScratch.meetPendingActions.add meetAction
```

This bridges the async LLM worker → synchronous per-tick mode.

### 15.2 Meeting conversation flush (bot.nim:418-421)

When leaving voting phase, the guidance state's meeting conversation
buffer is flushed (`flushMeetingConversation`), resetting chat context
for the next meeting.

---

## 16. LLM snapshot context

During meetings, the snapshot (`snapshot.nim:82-218`) includes:

- `phase: "voting"` — signals the LLM that meeting mode is active.
- `current_mode: { "name": "meeting", ... }` with `ticks_active`.
- `recent_chat` — all chat lines from this meeting with speaker
  colors and text.
- Standard fields: visible players, memory, self state.

The LLM uses this to decide what to say (chat) and who to vote for.
The mode's scratch state (cursor position, pending actions, vote
status) is not exposed — the LLM generates actions based on game
state, not cursor mechanics.

---

## 17. Voting parse dependency

The meeting mode depends on `perception/voting.nim`'s per-frame parse
results, merged into belief by `mergeVotingPercept`
(`belief.nim:188-216`):

- `votingCursor: int` — current cursor slot index. `playerCount` for
  SKIP, `-1` if unknown.
- `votingSelfSlot: int` — our slot index (for future self-awareness).
- `votingPlayerCount: int` — total players in the grid.
- `votingValid: bool` — whether the current frame parsed successfully.

These are updated every interstitial frame. If the parse fails
(`votingValid = false`), cursor-based navigation degrades to the
CursorRight fallback.

---

## 18. Open questions

1. **Chat emission FFI.** The biggest missing feature. Requires
   Nim buffer + C export + Python bridge. The mode is ready; the
   infrastructure is not.

2. **Vote target persistence across actions.** If the LLM sends
   `MeetingActVote(target: 3)` and then later `MeetingActVote(target: 5)`
   before the first navigation completes, the second action overwrites
   `meetVoteTarget`. This is correct (latest instruction wins) but
   could cause visible cursor thrashing if the LLM changes its mind
   rapidly.

3. **Self-vote prevention.** Nothing prevents the LLM from voting for
   the bot itself. The server may reject self-votes, but the mode will
   navigate to the self-slot and confirm regardless. A guard using
   `votingSelfSlot` could prevent this. Low priority — the LLM should
   be smart enough.

4. **Vote tracking for snapshot.** The mode knows who it voted for
   (`meetVoteTarget` at confirmation time), but this isn't exposed to
   the snapshot or memory. A future version could record the vote in
   `belief.social.votesCast` for cross-meeting memory.

5. **Meeting duration calibration.** `MeetingDurationEstimateTicks = 600`
   matches the local server. Tournament servers may use different
   values. If the fallback fires too early or too late, this constant
   needs adjustment. Ideally the bot would detect meeting duration
   empirically from past meetings.
