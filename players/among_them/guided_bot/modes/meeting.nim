## Mode: `meeting`. LLM in direct control via a queue of
## `MeetingAction` values (see DESIGN.md §7).
##
## Phase 6.3 rewrite: cursor-aware vote navigation using the voting
## parse's cursor position, timer fix (600 ticks default), and
## auto-vote delay for the no-LLM path. Chat emission remains a stub
## (deferred to FFI plumbing phase). See MEETING_DESIGN.md.
##
## Safety-net fallback (DESIGN.md §7.7): if `MeetingFallbackTicksLeft`
## ticks remain and no vote has been confirmed, the mode navigates to
## SKIP and confirms. This is a structural backstop; the LLM cannot
## override it.

import ../types
import ../action
import ../tuning

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
                        meetPendingActions: @[],
                        meetVoteTarget: -1,
                        meetCursorMoveTicks: 0,
                        meetCursorDir: CursorNone,
                        meetLastLlmActionTick: -1)
  discard params

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

# ---------------------------------------------------------------------------
# Cursor navigation helpers
# ---------------------------------------------------------------------------

proc ringSize(playerCount: int): int {.inline.} =
  ## Total positions in the voting ring: player slots + SKIP.
  playerCount + 1

proc shortestCursorDir(current, target, ring: int): CursorDir =
  ## Compute the shortest direction to move from `current` to `target`
  ## in a wrapped ring of `ring` positions. Returns CursorNone if
  ## already on target.
  if current == target:
    return CursorNone
  if ring <= 1:
    return CursorNone
  # Distance going right (positive direction).
  let rightDist = (target - current + ring) mod ring
  # Distance going left.
  let leftDist = (current - target + ring) mod ring
  if rightDist <= leftDist:
    CursorRight
  else:
    CursorLeft

proc targetSlotForAction(action: MeetingAction,
                         playerCount: int): int =
  ## Map a MeetingActVote target to a slot index.
  ## target == -1 → SKIP (slot playerCount).
  ## target >= 0 → color index (== slot index in Among Them).
  if action.target < 0:
    playerCount  # SKIP
  else:
    action.target

# ---------------------------------------------------------------------------
# Vote navigation intent
# ---------------------------------------------------------------------------

proc cursorMoveIntent(dir: CursorDir): ActionIntent =
  ActionIntent(
    steerValid: false,
    pressA: false, pressB: false,
    cursor: dir,
    chat: "",
    discipline: DisciplineNoOp)

proc confirmVoteIntent(): ActionIntent =
  ActionIntent(
    steerValid: false,
    pressA: true, pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineNoOp)

# ---------------------------------------------------------------------------
# Navigate-to-slot state machine
# ---------------------------------------------------------------------------

proc navigateToSlot(belief: Belief, scratch: var ModeScratch,
                    targetSlot: int): ActionIntent =
  ## Drive the cursor toward `targetSlot`. Returns the intent for this
  ## tick. Uses multi-tick holds for reliable cursor movement.
  let cursor = belief.percep.votingCursor
  let pc = belief.percep.votingPlayerCount
  let ring = ringSize(pc)

  scratch.meetVoteTarget = targetSlot

  # If cursor position is unknown, fall back to CursorRight.
  if cursor < 0 or pc <= 0:
    return cursorMoveIntent(CursorRight)

  # Already on target?
  if cursor == targetSlot:
    return noOpIntent()  # Caller will handle confirm.

  # If we're in the middle of a multi-tick cursor hold, continue.
  if scratch.meetCursorMoveTicks > 0:
    scratch.meetCursorMoveTicks -= 1
    return cursorMoveIntent(scratch.meetCursorDir)

  # Compute direction and start a new cursor hold.
  let dir = shortestCursorDir(cursor, targetSlot, ring)
  if dir == CursorNone:
    return noOpIntent()
  scratch.meetCursorDir = dir
  scratch.meetCursorMoveTicks = MeetingCursorHoldTicks - 1  # -1 because this tick counts.
  cursorMoveIntent(dir)

# ---------------------------------------------------------------------------
# Main decide logic
# ---------------------------------------------------------------------------

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  discard params

  # If vote already confirmed, just idle (§7.5 soft-lock).
  if scratch.meetVoteConfirmed:
    return noOpIntent()

  let ticksInMeeting = belief.tick - scratch.meetEnterTick
  let pc = belief.percep.votingPlayerCount
  let cursor = belief.percep.votingCursor

  # --- Safety-net fallback (DESIGN.md §7.7) ---
  # Use the configurable estimate instead of the old hardcoded 1200.
  let estimatedTicksLeft = MeetingDurationEstimateTicks - ticksInMeeting

  if estimatedTicksLeft <= MeetingFallbackTicksLeft and
     not scratch.meetVoteConfirmed:
    # Navigate to SKIP and confirm.
    let skipSlot = if pc > 0: pc else: 8  # Fallback if playerCount unknown.

    # If cursor is on SKIP, confirm.
    if cursor >= 0 and cursor == skipSlot:
      scratch.meetVoteConfirmed = true
      return confirmVoteIntent()

    # Navigate toward SKIP.
    return navigateToSlot(belief, scratch, skipSlot)

  # --- Auto-vote delay (no-LLM path) ---
  # If no LLM action has arrived and enough time has passed, vote SKIP.
  if scratch.meetLastLlmActionTick < 0 and
     ticksInMeeting >= MeetingAutoVoteDelayTicks and
     not scratch.meetVoteConfirmed:
    let skipSlot = if pc > 0: pc else: 8

    if cursor >= 0 and cursor == skipSlot:
      scratch.meetVoteConfirmed = true
      return confirmVoteIntent()

    return navigateToSlot(belief, scratch, skipSlot)

  # --- Process pending LLM meeting actions ---
  if scratch.meetPendingActions.len > 0:
    let action = scratch.meetPendingActions[0]
    scratch.meetPendingActions.delete(0)
    scratch.meetLastLlmActionTick = belief.tick

    case action.kind
    of MeetingActSpeak:
      # Chat emission is a stub (deferred). Put text on intent anyway
      # so it's ready when the FFI pipeline is wired.
      return ActionIntent(
        steerValid: false,
        pressA: false, pressB: false,
        cursor: CursorNone,
        chat: action.text,
        discipline: DisciplineNoOp)

    of MeetingActVote:
      # Start navigating toward the target slot.
      let targetSlot = targetSlotForAction(action, pc)
      scratch.meetVoteTarget = targetSlot
      # If already on target, just wait for confirm.
      if cursor >= 0 and cursor == targetSlot:
        return noOpIntent()
      return navigateToSlot(belief, scratch, targetSlot)

    of MeetingActConfirmVote:
      scratch.meetVoteConfirmed = true
      return confirmVoteIntent()

    of MeetingActUnvote:
      # Press B to deselect.
      scratch.meetVoteTarget = -1
      return ActionIntent(
        steerValid: false,
        pressA: false, pressB: true,
        cursor: CursorNone,
        chat: "",
        discipline: DisciplineNoOp)

    of MeetingActWait:
      return noOpIntent()

    of MeetingActNone:
      return noOpIntent()

  # --- Continue cursor navigation if a vote target is pending ---
  if scratch.meetVoteTarget >= 0:
    if cursor >= 0 and cursor == scratch.meetVoteTarget:
      # Arrived at target. Wait for confirm action from LLM.
      return noOpIntent()
    return navigateToSlot(belief, scratch, scratch.meetVoteTarget)

  # --- No pending actions, no fallback needed yet ---
  noOpIntent()
