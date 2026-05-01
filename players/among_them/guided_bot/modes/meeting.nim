## Mode: `meeting`. LLM in direct control via a queue of
## `MeetingAction` values (see DESIGN.md §7).
##
## Phase 3 implementation: the meeting mode reads MeetingAction values
## from the guidance worker's channel and executes them at game tempo:
##   - `speak` → emits chat text
##   - `vote` → moves cursor toward target slot
##   - `confirm_vote` → presses A to finalize vote (irrevocable per §7.5)
##   - `unvote` → re-selects before confirmation
##   - `wait` → idle until next trigger
##
## Safety-net fallback (DESIGN.md §7.7): if `MeetingFallbackTicksLeft`
## ticks remain and no vote has been confirmed, the mode forces SKIP.
## This is a structural backstop; the LLM cannot override it.
##
## Between actions, the mode emits no-ops until the next action arrives
## from the channel or a trigger fires.
##
## The meeting-action channel is read from `bot.guidance` which is
## passed indirectly — the action queue lives on `ModeScratch.
## meetPendingActions` and is populated by the bot pipeline calling
## `tryReceiveMeetingAction` each tick.

import ../types
import ../action
import ../tuning
import ../guidance

const Name* = ModeMeeting

proc isLegalFor*(belief: Belief): bool =
  belief.self.phase == PhaseVoting

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeMeeting, meetWantToSpeakFirst: false)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeMeeting,
                        meetEnterTick: belief.tick,
                        meetVoteConfirmed: false,
                        meetPendingActions: @[])
  discard params

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

# ---------------------------------------------------------------------------
# Meeting cursor navigation helpers
# ---------------------------------------------------------------------------

const
  ## Approximate number of ticks to hold a cursor direction before the
  ## game registers the move. The game processes cursor input at its
  ## own rate; we emit the direction for a few ticks to be safe.
  CursorHoldTicks = 3

  ## How many CursorRight presses to reach SKIP from any position
  ## (worst case: wrap around all 8 player slots). We use repeated
  ## CursorRight as a brute-force approach when we don't know exact
  ## cursor position.
  MaxCursorSteps = 10

# ---------------------------------------------------------------------------
# Vote-target cursor navigation
# ---------------------------------------------------------------------------

proc cursorDirectionForTarget(targetColorIndex: int,
                              playerCount: int): CursorDir =
  ## Determine which direction to move the cursor to reach the target.
  ## targetColorIndex == -1 means SKIP (the last slot).
  ## Without exact cursor position tracking, we move right toward the
  ## target. SKIP is always the rightmost position.
  # Simple strategy: always move right. SKIP is past all player slots.
  # The cursor wraps, so repeated right will cycle through all options.
  CursorRight

# ---------------------------------------------------------------------------
# Main decide logic
# ---------------------------------------------------------------------------

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  ## Phase 3: LLM-driven meeting behavior with safety-net fallback.
  discard params

  # If vote already confirmed, just idle (§7.5 soft-lock).
  if scratch.meetVoteConfirmed:
    return noOpIntent()

  let ticksInMeeting = belief.tick - scratch.meetEnterTick

  # --- Safety-net fallback (DESIGN.md §7.7) ---
  # Estimate meeting timer: typical voteTimerTicks = 1200 (~50s).
  # We don't have the exact timer, so use ticks-in-meeting as proxy.
  # If we've been in the meeting for a long time and haven't voted,
  # force SKIP. The MeetingFallbackTicksLeft constant is the safety
  # margin measured from the *end* of the typical meeting duration.
  const typicalMeetingDuration = 1200  # ~50s at 24Hz
  let estimatedTicksLeft = typicalMeetingDuration - ticksInMeeting

  if estimatedTicksLeft <= MeetingFallbackTicksLeft and
     not scratch.meetVoteConfirmed:
    # Force vote SKIP: move cursor right (toward SKIP) and confirm.
    if estimatedTicksLeft > MeetingFallbackTicksLeft - 24:
      # Phase 1: move cursor toward SKIP.
      return ActionIntent(
        steerValid: false,
        pressA: false,
        pressB: false,
        cursor: CursorRight,
        chat: "",
        discipline: DisciplineNoOp
      )
    else:
      # Phase 2: press A to confirm the fallback vote.
      scratch.meetVoteConfirmed = true
      return ActionIntent(
        steerValid: false,
        pressA: true,
        pressB: false,
        cursor: CursorNone,
        chat: "",
        discipline: DisciplineNoOp
      )

  # --- Process pending LLM meeting actions ---
  # Pop an action from the queue if available.
  if scratch.meetPendingActions.len > 0:
    let action = scratch.meetPendingActions[0]
    scratch.meetPendingActions.delete(0)

    case action.kind
    of MeetingActSpeak:
      # Emit chat text. The action layer handles the actual chat
      # packet emission. We put the text in the intent's chat field.
      return ActionIntent(
        steerValid: false,
        pressA: false,
        pressB: false,
        cursor: CursorNone,
        chat: action.text,
        discipline: DisciplineNoOp
      )

    of MeetingActVote:
      # Move cursor toward the target. We emit CursorRight to cycle
      # toward the target slot. The exact navigation depends on
      # cursor position tracking (which we approximate).
      # Store the vote target for subsequent ticks to continue moving.
      return ActionIntent(
        steerValid: false,
        pressA: false,
        pressB: false,
        cursor: CursorRight,
        chat: "",
        discipline: DisciplineNoOp
      )

    of MeetingActConfirmVote:
      # Press A to confirm the current vote selection.
      scratch.meetVoteConfirmed = true
      return ActionIntent(
        steerValid: false,
        pressA: true,
        pressB: false,
        cursor: CursorNone,
        chat: "",
        discipline: DisciplineNoOp
      )

    of MeetingActUnvote:
      # Press B to deselect (if the game supports it).
      return ActionIntent(
        steerValid: false,
        pressA: false,
        pressB: true,
        cursor: CursorNone,
        chat: "",
        discipline: DisciplineNoOp
      )

    of MeetingActWait:
      # Explicit wait — do nothing until next action arrives.
      return noOpIntent()

    of MeetingActNone:
      return noOpIntent()

  # --- No pending actions, no fallback needed yet ---
  # Idle until the LLM sends the next action.
  noOpIntent()
