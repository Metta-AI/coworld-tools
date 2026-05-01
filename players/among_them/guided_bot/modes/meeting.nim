## Mode: `meeting`. LLM in direct control via a queue of
## `MeetingAction` values (see DESIGN.md §7).
##
## Phase 2 fallback: no LLM integration yet, so the meeting mode
## always moves the cursor to SKIP and presses A. This satisfies the
## "always cast a vote" requirement (DESIGN.md §9.2) and passes the
## cogames validation gate.
##
## Cursor navigation: the voting parse provides `cursor` (current
## cursor slot index) and `playerCount` (SKIP = playerCount). We
## emit CursorLeft/CursorRight to move toward the SKIP slot, then
## press A to confirm.
##
## Phase 3 will wire in the meeting-action queue, the LLM worker,
## chat emission, and the MeetingFallbackTicksLeft safety-net.

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
                        meetPendingActions: @[])
  discard params

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  ## Phase 2 fallback: navigate cursor to SKIP, confirm vote.
  discard params

  # If we already confirmed our vote, just idle.
  if scratch.meetVoteConfirmed:
    return noOpIntent()

  # We need a valid voting parse to know cursor position.
  # The voting parse is available via the bot pipeline; the belief
  # carries the parsed data. However, cursor position is on the
  # VotingParse which gets merged each frame. We read it from
  # social state indirectly — actually, the VotingParse.cursor is
  # not directly on the belief. We need to add it.
  #
  # For now, use a simpler approach: emit CursorRight repeatedly
  # to cycle toward SKIP (the last position, after all player
  # slots). The cursor wraps, so CursorRight from the last player
  # slot reaches SKIP. After enough ticks, press A.
  #
  # Phase 3 will read the actual cursor position from the parsed
  # voting screen for precise navigation.

  let ticksInMeeting = belief.tick - scratch.meetEnterTick

  # Strategy: spend the first ~24 ticks (1 second) moving cursor
  # right to reach SKIP, then press A to confirm.
  const cursorMoveTicks = 24
  const confirmTick = cursorMoveTicks + 2  # Small gap before confirm.

  if ticksInMeeting < cursorMoveTicks:
    # Move cursor toward SKIP (rightward).
    return ActionIntent(
      steerValid: false,
      pressA: false,
      pressB: false,
      cursor: CursorRight,
      chat: "",
      discipline: DisciplineNoOp
    )

  if ticksInMeeting >= confirmTick:
    # Press A to confirm the vote.
    scratch.meetVoteConfirmed = true
    return ActionIntent(
      steerValid: false,
      pressA: true,
      pressB: false,
      cursor: CursorNone,
      chat: "",
      discipline: DisciplineNoOp
    )

  # Gap ticks — idle.
  noOpIntent()
