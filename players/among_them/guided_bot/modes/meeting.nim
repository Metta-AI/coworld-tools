## Mode: `meeting`. LLM in direct control via a queue of
## `MeetingAction` values (see DESIGN.md §7).
##
## Phase 6.3 rewrite: cursor-aware vote navigation using the voting
## parse's cursor position, timer fix (600 ticks default), auto-vote
## delay for the no-LLM path, chat emission, legality guards for
## LLM-directed votes, and structured evidence in the LLM snapshot.
## See MEETING_DESIGN.md.
##
## Safety-net fallback (DESIGN.md §7.7): if `MeetingFallbackTicksLeft`
## ticks remain and no vote has been confirmed, the mode navigates to
## a role-aware evidence target and confirms. This is a structural
## backstop; the LLM cannot override it.

import std/strutils
import ../types
import ../action
import ../tuning
import ../perception/data

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

proc isKnownImposterTeammate(belief: Belief, slot: int): bool =
  belief.self.role == RoleImposter and slot in belief.self.knownImposterColors

proc isSafeVoteSlot(belief: Belief, slot, playerCount: int): bool =
  isSelectableVoteSlot(belief, slot, playerCount) and
    not isKnownImposterTeammate(belief, slot)

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
  if result >= 0 and result < playerCount and
     (not belief.memory.perPlayer[result].alive or
      isSelfVoteSlot(belief, result) or
      isKnownImposterTeammate(belief, result)):
    result = skipSlot

proc legalVoteSlotOrSkip(belief: Belief, slot, playerCount: int): int =
  ## Hard legality guard. It does not judge evidence quality; it only
  ## prevents mechanically invalid or strategically catastrophic targets.
  let skipSlot = skipSlotFor(playerCount)
  if slot < 0 or slot >= playerCount:
    return skipSlot
  if isSafeVoteSlot(belief, slot, playerCount):
    slot
  else:
    skipSlot

proc textNamesColor(text: string, color: int): bool =
  if color < 0 or color >= PlayerColorCount:
    return false
  let lower = text.toLowerAscii()
  let name = PlayerColorNames[color].toLowerAscii()
  if name.len == 0:
    return false
  lower.contains(name)

proc chatSuspicionScore(belief: Belief, color: int): int =
  ## Lightweight parser for OCR'd meeting chat. The LLM gets the raw text;
  ## fallback strategy only needs a conservative "someone named this color".
  for line in belief.social.recentChat:
    if line.speakerColor == belief.self.colorIndex:
      continue
    if line.text.textNamesColor(color):
      let lower = line.text.toLowerAscii()
      if lower.contains("sus") or lower.contains("kill") or
         lower.contains("body") or lower.contains("vote"):
        result += 6
      else:
        result += 2

proc votesReceivedScore(belief: Belief, color: int): int =
  for voter in 0 ..< PlayerColorCount:
    if belief.social.votesCast[voter] == color:
      result += 3

proc bodyEvidenceScore(ps: PlayerSummary): int =
  if ps.nearBodyEvidenceScore > 0:
    ps.nearBodyEvidenceScore
  else:
    ps.timesNearBody * MeetingBodyEvidenceMaxStrength

proc soloTrustScore(ps: PlayerSummary): int =
  min(MeetingSoloTrustMaxScore,
      ps.soloWithSelfTicks div MeetingSoloTrustTicksPerPoint)

proc crewSuspicionScore(belief: Belief, slot: int): int =
  let ps = belief.memory.perPlayer[slot]
  if ps.role == RoleImposter:
    result += 100
  result += ps.timesWitnessedKill * 20
  result += ps.bodyEvidenceScore
  result += belief.chatSuspicionScore(slot)
  result += belief.votesReceivedScore(slot)
  result -= ps.soloTrustScore

proc imposterPlausibleVoteScore(belief: Belief, slot: int): int =
  let ps = belief.memory.perPlayer[slot]
  belief.chatSuspicionScore(slot) * 2 +
    belief.votesReceivedScore(slot) +
    ps.bodyEvidenceScore div 2 +
    ps.timesWitnessedKill * 6 -
    ps.soloTrustScore

proc guardedTargetSlotForAction(belief: Belief, action: MeetingAction,
                                playerCount: int): int =
  ## Safety guard for LLM-directed votes. SKIP remains always legal; live
  ## player targets are allowed even when the symbolic evidence score is
  ## low, because the LLM can reason over structured evidence and alibis.
  targetSlotForAction(belief, action, playerCount)

proc pickCrewVoteSlot(belief: Belief, playerCount: int): int =
  var bestSlot = -1
  var bestScore = 0
  for slot in 0 ..< playerCount:
    if not isSelectableVoteSlot(belief, slot, playerCount):
      continue
    let score = crewSuspicionScore(belief, slot)
    if score > bestScore:
      bestScore = score
      bestSlot = slot
  if bestSlot >= 0 and bestScore >= MeetingCrewEvidenceThreshold:
    bestSlot
  else:
    skipSlotFor(playerCount)

proc pickImposterVoteSlot(belief: Belief, playerCount: int): int =
  ## Blend with plausible accusations. If the table has no evidence,
  ## skip rather than starting a baseless pile-on.
  if playerCount <= 1:
    return skipSlotFor(playerCount)
  var bestSlot = -1
  var bestScore = low(int)
  for slot in 0 ..< playerCount:
    if not isSafeVoteSlot(belief, slot, playerCount):
      continue
    let score = imposterPlausibleVoteScore(belief, slot)
    if score > bestScore:
      bestScore = score
      bestSlot = slot
  if bestSlot >= 0 and bestScore > 0:
    return bestSlot
  skipSlotFor(playerCount)

proc strategicFallbackVoteSlot(belief: Belief, playerCount: int): int =
  ## Role-aware no-LLM vote target. Crew require evidence; imposters use
  ## evidence/alibis opportunistically but never vote self or known partners.
  case belief.self.role
  of RoleCrewmate:
    pickCrewVoteSlot(belief, playerCount)
  of RoleImposter:
    pickImposterVoteSlot(belief, playerCount)
  of RoleUnknown:
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
    let targetSlot = strategicFallbackVoteSlot(belief, pc)
    scratch.meetVoteTarget = targetSlot

    if cursor >= 0 and cursor == targetSlot:
      scratch.meetVoteConfirmed = true
      return confirmVoteIntent()

    return navigateToSlot(belief, scratch, targetSlot)

  # --- Auto-vote delay (no-LLM path) ---
  # If no LLM action has arrived and enough time has passed, cast a
  # role-aware fallback vote so the bot does not idle through meetings.
  if scratch.meetLastLlmActionTick < 0 and
     ticksInMeeting >= MeetingAutoVoteDelayTicks and
     not scratch.meetVoteConfirmed:
    let targetSlot = strategicFallbackVoteSlot(belief, pc)
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
      # Bot/action/FFI layers queue this text for the WebSocket bridge.
      return ActionIntent(
        steerValid: false,
        pressA: false, pressB: false,
        cursor: CursorNone,
        chat: action.text,
        discipline: DisciplineNoOp)

    of MeetingActVote:
      # Start navigating toward the target slot.
      let targetSlot = guardedTargetSlotForAction(belief, action, pc)
      scratch.meetVoteTarget = targetSlot
      # If already on target, just wait for confirm.
      if cursor >= 0 and cursor == targetSlot:
        return noOpIntent()
      return navigateToSlot(belief, scratch, targetSlot)

    of MeetingActConfirmVote:
      let selected =
        if scratch.meetVoteTarget >= 0:
          scratch.meetVoteTarget
        else:
          cursor
      let targetSlot = legalVoteSlotOrSkip(belief, selected, pc)
      scratch.meetVoteTarget = targetSlot
      if cursor < 0 or cursor != targetSlot:
        return navigateToSlot(belief, scratch, targetSlot)
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
    scratch.meetVoteTarget = legalVoteSlotOrSkip(
      belief, scratch.meetVoteTarget, pc)
    if cursor >= 0 and cursor == scratch.meetVoteTarget:
      # Arrived at target. Wait for confirm action from LLM.
      return noOpIntent()
    return navigateToSlot(belief, scratch, scratch.meetVoteTarget)

  # --- No pending actions, no fallback needed yet ---
  noOpIntent()
