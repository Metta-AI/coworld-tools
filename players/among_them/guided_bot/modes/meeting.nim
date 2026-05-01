## Mode: `meeting`. LLM in direct control via a queue of
## `MeetingAction` values (see DESIGN.md §7).
##
## Phase 0: no-op. Phase 2 will wire in the meeting-action queue, the
## cursor navigation, chat emission (via `action.emitChat`), and the
## `MeetingFallbackTicksLeft` safety-net (see tuning.nim).

import ../types
import ../action

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
  discard belief
  discard params
  discard scratch
  noOpIntent()
