# Meeting Mode — Design Document

> **Canonical reference** for the `meeting` mode handler. All meeting-
> mode design details live here; `DESIGN.md` contains only a brief
> overview and cross-reference.
>
> **Implementation:** `modes/meeting.nim`
>
> Last updated: 2026-05-15

---

## 1. Purpose and role

The `meeting` mode handles all bot behavior during the voting phase
(emergency meetings and body reports). It is:

- **The target of the `voting_screen_appeared` reflex**
  (`reflex.nim`). When the game phase transitions to
  `PhaseVoting`, this reflex fires unconditionally (highest priority)
  and switches to `meeting` regardless of the current mode.
- **The voting-phase default directive** (`mode_registry.nim`).
  If the bot is already in voting phase when a default is evaluated,
  `meeting` is chosen.
- **LLM-driven via an action queue.** Unlike other modes which
  produce behavior from parameters alone, the meeting mode consumes
  a queue of `MeetingAction` values pushed by the guidance worker.
  The LLM controls what to say and who to vote for; the mode handles
  cursor navigation mechanics.

The mode is **only legal** during `PhaseVoting` (`isLegalFor` checks
`belief.self.phase == PhaseVoting`). Living crewmates and imposters use
it to vote. Ghosts may transiently record `meeting_started`, but the
core reconcile path redirects known ghosts to the ghost default
(`task_completing`), so ghosts do not attempt to vote.

---

## 2. Mode parameters

```text
meeting {
  meetWantToSpeakFirst: bool   # Hint to the LLM: generate chat before voting.
                               # Not read by decide() — purely informational for
                               # the guidance worker's prompt construction.
}
```

Implementation in `types.nim`:
```nim
of ModeMeeting:
  meetWantToSpeakFirst*: bool
```

**Default params** (from `modes/meeting.nim`):
- `meetWantToSpeakFirst: false`

The parameter is a soft hint — the mode's `decide()` ignores it.
The guidance worker reads it when constructing the LLM prompt.

---

## 3. Decision logic overview

`decide()` evaluates each tick with a priority cascade:

1. **Vote confirmed** — if `meetVoteConfirmed`, emit `noOpIntent()`
   (soft-lock: the bot is done for this meeting).
2. **Safety-net fallback** — if estimated time remaining ≤
   `MeetingFallbackTicksLeft` (100), navigate to the role-aware
   evidence/alibi fallback target and confirm.
3. **Auto-vote delay** — if no LLM action has ever arrived and
   `MeetingAutoVoteDelayTicks` (96) have elapsed, vote for the
   role-aware fallback target.
4. **Process LLM action** — pop one action per tick from
   `meetPendingActions` and execute it.
5. **Continue cursor navigation** — if a vote target is pending and
   not yet reached, keep moving the cursor.
6. **Idle** — no actions pending, no fallbacks triggered.

---

## 4. LLM action queue

The meeting mode receives instructions from the LLM via a queue of
`MeetingAction` values. These are pushed by `bot.nim` each
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

Implementation in `types.nim`.

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
| `MeetingActSpeak` | Sets `intent.chat = text`; `bot.nim` queues it through `action.emitChat`, `guidedbot_take_chat`, and the Python WebSocket chat hook. |
| `MeetingActVote` | Resolves the requested color target to the current voting slot, sets `meetVoteTarget`, and begins cursor navigation. Self-targets, dead targets, invalid targets, and known imposter teammates are rewritten to SKIP. Symbolic evidence score is not a hard veto for LLM votes. |
| `MeetingActConfirmVote` | Runs the pending target or current cursor through the same legality guard, sets `meetVoteConfirmed = true`, and emits A only after the cursor is on that legal target. Illegal targets are redirected to SKIP. |
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
- Slots 0..`playerCount-1`: player slots. The player color at each slot comes
  from `belief.percep.votingSlotColors[slot]`; Coworld may draw slots in live
  join order rather than color order.
- Slot `playerCount`: SKIP.
- Ring size: `playerCount + 1`.

Wrapping: right from SKIP → slot 0. Left from slot 0 → SKIP.

### 5.2 Shortest-path computation

`shortestCursorDir` computes the optimal direction:
- Compute right-distance: `(target - current + ring) mod ring`.
- Compute left-distance: `(current - target + ring) mod ring`.
- Pick the shorter direction.

For 8 players (ring size 9), worst case is 4 cursor moves.

### 5.3 Target mapping

`targetSlotForAction`:
- `target == -1` → SKIP (slot `playerCount`).
- `target >= 0` → player color index. The meeting mode resolves that color to
  a live voting slot through `votingSlotColors`; it only falls back to
  `slot == color` when no parser-owned slot map is available.

### 5.4 Edge-triggered cursor pulses

The voting UI advances one slot per fresh left/right keydown. Holding a
direction continuously only moves one step, so the bot uses a pulse plus
release state machine:

1. If `meetCursorMoveTicks > 0`: continue emitting the same cursor
   direction and decrement the counter.
2. If the hold finished and `meetCursorDir != CursorNone`: emit one
   no-op release tick and clear `meetCursorDir`.
3. If cursor != target: compute a fresh shortest direction, set
   `meetCursorMoveTicks = MeetingCursorHoldTicks - 1` (current tick
   counts as one), and emit the direction.
4. If cursor == target: stop. Return `noOpIntent()` and wait for the
   confirm action, or let the fallback/auto-vote branch confirm.

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

**Behavior:** navigate to `strategicFallbackVoteSlot` using cursor tracking,
then confirm. If the cursor is already on that target, immediately confirm.
If cursor position is unknown, `navigateToSlot` falls back to CursorRight.

Crewmate fallback requires evidence. It scores known-imposter role memory,
hard witnessed venting, probabilistic near-vent appearances,
distance-weighted near-body sightings, witnessed-kill counts, visible
vote dots, and chat mentions by resolved player color, then subtracts
solo-survival trust; if no score reaches `MeetingCrewEvidenceThreshold`, it
votes SKIP. The current threshold is intentionally low enough that one
visible vote dot counts as actionable fallback evidence when the LLM path
has not produced an action.

The LLM prompt uses the same weighting direction but keeps the uncertainty
visible in chat. A repeated `near_vent_appearance`,
`near_vent_evidence_score >= 8`, or `probability_pct >= 60` is actionable
voting evidence unless stronger counterevidence exists, but the bot must
describe it as "appeared near vent" rather than hard vent proof.

Imposter fallback avoids self and known imposter teammates. It prefers a
live crewmate who already has chat/vote/body evidence against them; if the
table has no usable accusation, it votes SKIP rather than starting a
baseless pile-on.

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
(96, ~4s).

**Behavior:** same as fallback — navigate to `strategicFallbackVoteSlot`
and confirm.

**Purpose:** ensures the bot votes within 4s even without an LLM,
rather than waiting until late in the meeting timer. More aggressive than
the safety net but only activates in the absence of any LLM activity.

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

## 9. Chat emission

`MeetingActSpeak` places the chat text on `intent.chat`. The bot pipeline
then calls `action.emitChat`, which sanitizes printable ASCII, caps length
at `MeetingChatMaxLen`, applies `MeetingChatLineGapTicks`, and stores one
pending line in `ActionState.pendingChat`.

The C FFI export `guidedbot_take_chat(handle, agentId, buffer, bufferLen)`
drains that pending line. The Python policy polls it after `step_batch`
and exposes both:

- `bitworld_chat_messages(agent_ids)` for the Coworld/BitWorld runner.

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

All live in `tuning.nim`:

| Constant | Value | Meaning |
|---|---|---|
| `MeetingFallbackTicksLeft` | 100 | Safety-net fires with ~4s remaining. |
| `MeetingDurationEstimateTicks` | 600 | Conservative meeting length estimate (~25s). |
| `MeetingAutoVoteDelayTicks` | 96 | No-LLM fallback: vote via evidence/alibi strategy after 4s. |
| `MeetingCursorHoldTicks` | 3 | Ticks to hold each cursor pulse before releasing for the next step. |
| `MeetingChatLineGapTicks` | 12 | Min ticks between chat packets. |
| `MeetingLlmActionPeriodTicks` | 48 | Faster meeting cadence for speak/vote/confirm LLM actions. |
| `MeetingCrewEvidenceThreshold` | 3 | Minimum fallback score before crew votes a player instead of SKIP. |
| `MeetingBodyEvidenceRadius` | 48 | World-pixel radius for counting a player near a body. |
| `MeetingBodyEvidenceMaxStrength` | 8 | Per-sighting near-body score at body-contact distance. |
| `MeetingBodyEvidenceCooldownTicks` | 72 | Cooldown before counting the same near-body evidence again. |
| `MeetingSoloTrustTicksPerPoint` | 120 | Alone-together survival ticks that become one fallback trust point. |
| `MeetingSoloTrustMaxScore` | 8 | Maximum fallback suspicion reduction from direct solo trust. |
| `MeetingChatMaxLen` | 60 | Hard cap for outbound chat text. |

---

## 12. Reflex interactions

### 12.1 Incoming reflexes (other modes → meeting)

| Source mode | Condition | Params issued | Reflex name |
|---|---|---|---|
| Any mode | `PhaseVoting` entered (edge-triggered: `prevPhase != PhaseVoting`) | `meetWantToSpeakFirst: false`, TTL 0 | `voting_screen_appeared` |

This is the **highest-priority reflex** — it's evaluated first in
`evaluateReflexes` and fires regardless of
current mode. It has no TTL (meetings last until the phase ends
naturally).

### 12.2 Outgoing reflexes (meeting → other modes)

None. The meeting mode is only exited by:
- Phase change: when `PhaseVoting` ends, `isLegalFor` returns false,
  and `reconcileDirective`'s illegality check
  switches to the default directive.
- This is the only mode that exits via illegality rather than TTL or
  reflex.

### 12.3 Cooldown

The `voting_screen_appeared` reflex is subject to
`ReflexCooldownTicks` (96 ticks, ~4s). In practice this never
matters — voting phases don't end and restart within 4 seconds.

---

## 13. Trace events

The standard trace captures:

- `meeting_started` event in `bot.nim` (on PhaseVoting entry).
- `chat_observed` events for newly observed, deduplicated incoming chat
  lines, including OCR speaker attribution.
- `chat_sent` events when outgoing chat enters the FFI buffer.
- `vote_attempted` event when meeting mode emits A to confirm a vote.
- Mode entry/exit via `modes.jsonl`.
- `decisions.jsonl` records cursor direction and button presses each
  tick, showing the full cursor navigation sequence.

---

## 14. Action layer contract

The meeting mode does not use steering-based disciplines. All intents
use `DisciplineNoOp` with button/cursor fields set directly:

- **Cursor movement:** `cursor: CursorLeft | CursorRight` with no A/B.
- **Vote confirm:** `pressA: true` with no cursor or steering.
- **Unvote:** `pressB: true` with no cursor or steering.
- **Chat:** `chat: <text>` with no buttons.
- **Idle:** `noOpIntent()` — no buttons, no cursor, no steering.

`steerValid` is always `false` during meetings (no world-space
navigation occurs during voting).

---

## 15. Pipeline integration

The meeting mode has special pipeline support in `bot.nim`:

### 15.1 Action queue pumping

Each tick during `PhaseVoting`, the bot pipeline reads meeting actions
from the guidance channel and appends them to
`scratch.meetPendingActions`:

```nim
while tryReceiveMeetingAction(bot.guidance, meetAction):
  bot.modeScratch.meetPendingActions.add meetAction
```

This bridges the async LLM worker → synchronous per-tick mode.

### 15.2 Meeting conversation flush

When leaving voting phase, the guidance state's meeting conversation
buffer is flushed (`flushMeetingConversation`), resetting chat context
for the next meeting.

---

## 16. LLM snapshot context

During meetings, the snapshot (`snapshot.nim`) includes:

- `phase: "voting"` — signals the LLM that meeting mode is active.
- `current_mode.name/source/ticks_active`.
- `current_mode.params`, including `want_to_speak_first`.
- `current_mode.summary`, including pending action count, vote target
  slot, cursor, player count, estimated ticks left, last LLM action age,
  and active cursor movement.
- `meeting` — player count, self slot, cursor, slot-to-color mapping,
  selectable players, observed votes, per-player `evidence_ledger`, and recent
  alibi witnesses.
- `memory.per_player` — alive/role status, last-seen room, near-body
  counts, distance-weighted near-body score, solo-survival trust,
  witnessed-kill counts, hard witnessed-vent counts, probabilistic
  near-vent appearance score/probability, and ejection state keyed by player
  color.
- `meeting.evidence_ledger` — for each player: current voting slot, legality,
  current vote, voters targeting them, incriminating evidence, exculpatory
  evidence, and chat mentions that the LLM must classify as accusation,
  defense, alibi, or noise.
- `new_chat` — newly observed transcript lines that triggered the current
  chat wake-up, with speaker colours and text.
- `visible_chat` and `recent_chat` — current OCR-visible chat plus the
  deduplicated recent transcript with speaker colours and text.
- Standard fields: visible players, task state, self state.

The LLM uses this to decide what to say (chat) and who to vote for.
The LLM still does not receive raw scratch state, but it does receive
the compact `current_mode.summary` so it can see whether a vote is
already pending or confirmed and whether cursor movement is underway.

---

## 17. Voting parse dependency

The meeting mode depends on `perception/voting.nim`'s per-frame parse
results, merged into belief by `mergeVotingPercept`:

- `votingCursor: int` — current cursor slot index. `playerCount` for
  SKIP, `-1` if unknown.
- `votingSelfSlot: int` — our slot index, used for self-vote guards.
- `votingPlayerCount: int` — total players in the grid.
- `votingSlotColors: array[PlayerColorCount, int]` — slot index to player
  color index. This is authoritative for Coworld meetings because slot order
  can differ from color order.
- `votingValid: bool` — whether the current frame parsed successfully.
- Voting slot alive/dead state — merged into `memory.perPlayer[ci].alive`,
  so fallback strategy and LLM guards can skip dead slots.
- Vote-dot choices — merged into `social.votesCast`, then exposed in
  the meeting snapshot as observed votes.

These are updated every interstitial frame. If the parse fails
(`votingValid = false`), cursor-based navigation degrades to the
CursorRight fallback.

The bot pipeline runs voting parse on every interstitial frame,
including after `PhaseVoting` has already been established. This keeps
cursor and alive-slot state fresh while the meeting mode is navigating.

---

## 18. Open questions

1. **Vote target persistence across actions.** If the LLM sends
   `MeetingActVote(target: 3)` and then later `MeetingActVote(target: 5)`
   before the first navigation completes, the second action overwrites
   `meetVoteTarget`. This is correct (latest instruction wins) but
   could cause visible cursor thrashing if the LLM changes its mind
   rapidly.

2. **Self vote tracking for snapshot.** The mode knows who it voted for
   (`meetVoteTarget` at confirmation time), but this isn't exposed to
   the snapshot or memory. A future version could record the vote in
   `belief.social.votesCast` for cross-meeting memory.

3. **Meeting duration calibration.** `MeetingDurationEstimateTicks = 600`
   matches the local server. Tournament servers may use different
   values. If the fallback fires too early or too late, this constant
   needs adjustment. Ideally the bot would detect meeting duration
   empirically from past meetings.
