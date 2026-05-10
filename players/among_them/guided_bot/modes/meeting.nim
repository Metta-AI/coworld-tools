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
## the temporary no-LLM target and confirms. This is a structural
## backstop; the LLM cannot override it.

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

proc skipSlotFor(playerCount: int): int {.inline.} =
  ## Slot index used by the server for SKIP. If the grid has not parsed yet,
  ## keep the old fallback target so navigation still moves rather than idles.
  if playerCount > 0: playerCount else: 8

proc selfVoteSlot(belief: Belief): int =
  ## Best known voting slot for this bot. The voting parser's explicit marker
  ## wins; color index is only a fallback because the vote grid is color-ordered.
  if belief.percep.votingSelfSlot >= 0:
    return belief.percep.votingSelfSlot
  if belief.self.colorIndex >= 0 and
     (belief.percep.votingPlayerCount <= 0 or
      belief.self.colorIndex < belief.percep.votingPlayerCount):
    return belief.self.colorIndex
  -1

proc isSelfVoteSlot(belief: Belief, slot: int): bool =
  let selfSlot = selfVoteSlot(belief)
  selfSlot >= 0 and slot == selfSlot

proc isSelectableVoteSlot(belief: Belief, slot, playerCount: int): bool =
  slot >= 0 and slot < playerCount and
    not isSelfVoteSlot(belief, slot) and
    belief.memory.perPlayer[slot].alive

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

proc targetSlotForAction(belief: Belief, action: MeetingAction,
                         playerCount: int): int =
  ## Map a MeetingActVote target to a slot index.
  ## target == -1 → SKIP (slot playerCount).
  ## target >= 0 → color index (== slot index in Among Them).
  let skipSlot = skipSlotFor(playerCount)
  result =
    if action.target < 0 or action.target >= playerCount:
      skipSlot
    else:
      action.target
  if isSelfVoteSlot(belief, result):
    result = skipSlot

proc deterministicTestVoteSlot(belief: Belief, playerCount: int): int =
  ## Temporary no-LLM vote target for mechanical validation: vote for the
  ## next selectable live player slot to the right. Strategy can replace this
  ## later, but the mechanical target must be reachable by the voting UI.
  if playerCount <= 1:
    return skipSlotFor(playerCount)
  let selfSlot = selfVoteSlot(belief)
  if selfSlot < 0 or selfSlot >= playerCount:
    return skipSlotFor(playerCount)
  for offset in 1 ..< playerCount:
    let slot = (selfSlot + offset) mod playerCount
    if isSelectableVoteSlot(belief, slot, playerCount):
      return slot
  skipSlotFor(playerCount)

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
  ## tick. Cursor movement is edge-triggered by the UI, so each directional
  ## pulse must be followed by a release tick before another pulse.
  let cursor = belief.percep.votingCursor
  let pc = belief.percep.votingPlayerCount
  let ring = ringSize(pc)

  scratch.meetVoteTarget = targetSlot

  # If cursor position is unknown, fall back to CursorRight.
  if cursor < 0 or pc <= 0:
    return cursorMoveIntent(CursorRight)

  # Already on target?
  if cursor == targetSlot:
    scratch.meetCursorMoveTicks = 0
    scratch.meetCursorDir = CursorNone
    return noOpIntent()  # Caller will handle confirm.

  # If we're in the middle of a multi-tick cursor hold, continue.
  if scratch.meetCursorMoveTicks > 0:
    scratch.meetCursorMoveTicks -= 1
    return cursorMoveIntent(scratch.meetCursorDir)

  # Release once after each pulse so the voting UI observes a fresh keydown
  # for the next cursor step. Holding Right/Left only advances one slot.
  if scratch.meetCursorDir != CursorNone:
    scratch.meetCursorDir = CursorNone
    return noOpIntent()

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
    let targetSlot = deterministicTestVoteSlot(belief, pc)
    scratch.meetVoteTarget = targetSlot

    if cursor >= 0 and cursor == targetSlot:
      scratch.meetVoteConfirmed = true
      return confirmVoteIntent()

    return navigateToSlot(belief, scratch, targetSlot)

  # --- Auto-vote delay (no-LLM path) ---
  # If no LLM action has arrived and enough time has passed, cast a
  # deterministic test vote so cursor navigation/confirmation is live-tested.
  if scratch.meetLastLlmActionTick < 0 and
     ticksInMeeting >= MeetingAutoVoteDelayTicks and
     not scratch.meetVoteConfirmed:
    let targetSlot = deterministicTestVoteSlot(belief, pc)
    scratch.meetVoteTarget = targetSlot

    if cursor >= 0 and cursor == targetSlot:
      scratch.meetVoteConfirmed = true
      return confirmVoteIntent()

    return navigateToSlot(belief, scratch, targetSlot)

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
      let targetSlot = targetSlotForAction(belief, action, pc)
      scratch.meetVoteTarget = targetSlot
      # If already on target, just wait for confirm.
      if cursor >= 0 and cursor == targetSlot:
        return noOpIntent()
      return navigateToSlot(belief, scratch, targetSlot)

    of MeetingActConfirmVote:
      let skipSlot = skipSlotFor(pc)
      if isSelfVoteSlot(belief, cursor) or
         isSelfVoteSlot(belief, scratch.meetVoteTarget):
        scratch.meetVoteTarget = skipSlot
        if cursor >= 0 and cursor == skipSlot:
          scratch.meetVoteConfirmed = true
          return confirmVoteIntent()
        return navigateToSlot(belief, scratch, skipSlot)
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
    if isSelfVoteSlot(belief, scratch.meetVoteTarget):
      scratch.meetVoteTarget = skipSlotFor(pc)
    if cursor >= 0 and cursor == scratch.meetVoteTarget:
      # Arrived at target. Wait for confirm action from LLM.
      return noOpIntent()
    return navigateToSlot(belief, scratch, scratch.meetVoteTarget)

  # --- No pending actions, no fallback needed yet ---
  noOpIntent()
