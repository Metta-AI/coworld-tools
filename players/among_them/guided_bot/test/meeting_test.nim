## Focused meeting-mode safety checks.
##
## Run::
##
##     nim c -r -d:release --threads:on --mm:orc \
##         among_them/guided_bot/test/meeting_test.nim

import std/strformat
import ../types
import ../belief
import ../tuning
import ../modes/meeting as meetingMode

var failures = 0

proc expect(cond: bool, label: string) =
  if not cond:
    stderr.writeLine "FAIL: ", label
    inc failures

proc expectEq[T](got, want: T, label: string) =
  if got != want:
    stderr.writeLine &"FAIL: {label}: got {got}, want {want}"
    inc failures

proc meetingParams(): ModeParams =
  ModeParams(mode: ModeMeeting, meetWantToSpeakFirst: false)

proc makeVotingBelief(cursor, selfSlot: int): Belief =
  result = initBelief()
  result.tick = 100
  result.self.role = RoleImposter
  result.self.phase = PhaseVoting
  result.self.colorIndex = selfSlot
  result.percep.votingValid = true
  result.percep.votingCursor = cursor
  result.percep.votingSelfSlot = selfSlot
  result.percep.votingPlayerCount = 4

proc makeScratch(belief: Belief): ModeScratch =
  let params = meetingParams()
  meetingMode.onEnter(belief, params, result)

proc testLlmSelfVoteRedirectsToSkip() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  var scratch = makeScratch(belief)
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActVote,
    text: "",
    target: 1)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 4,
           "self-target vote is rewritten to SKIP slot")
  expect(not intent.pressA,
         "self-target vote does not confirm while cursor is on self")

proc testConfirmOnSelfRedirectsToSkip() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  var scratch = makeScratch(belief)
  scratch.meetVoteTarget = 1
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActConfirmVote,
    text: "",
    target: -1)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 4,
           "confirm-on-self redirects pending target to SKIP")
  expect(not intent.pressA,
         "confirm-on-self does not press A")
  expect(not scratch.meetVoteConfirmed,
         "confirm-on-self is not marked confirmed before reaching SKIP")

proc testConfirmOnSkipStillVotes() =
  var belief = makeVotingBelief(cursor = 4, selfSlot = 1)
  var scratch = makeScratch(belief)
  scratch.meetVoteTarget = 4
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActConfirmVote,
    text: "",
    target: -1)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expect(intent.pressA, "confirm on SKIP presses A")
  expect(scratch.meetVoteConfirmed, "confirm on SKIP marks vote confirmed")

proc testAutoVoteTargetsRightNeighbor() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  var scratch = makeScratch(belief)
  belief.tick = 100 + MeetingAutoVoteDelayTicks

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "auto-vote targets the next slot to the right")
  expect(not intent.pressA,
         "auto-vote navigates before confirming when cursor is not on target")

proc testAutoVoteSkipsDeadRightNeighbor() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.memory.perPlayer[2].alive = false
  var scratch = makeScratch(belief)
  belief.tick = 100 + MeetingAutoVoteDelayTicks

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 3,
           "auto-vote skips dead slots when choosing a right-neighbor target")
  expect(not intent.pressA,
         "auto-vote navigates before confirming the next live target")

proc testAutoVoteConfirmsRightNeighbor() =
  var belief = makeVotingBelief(cursor = 2, selfSlot = 1)
  var scratch = makeScratch(belief)
  belief.tick = 100 + MeetingAutoVoteDelayTicks

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "auto-vote records target even when already on target")
  expect(intent.pressA, "auto-vote presses A on right-neighbor target")
  expect(scratch.meetVoteConfirmed,
         "auto-vote marks right-neighbor vote confirmed")

proc advanceCursorOnFreshPress(cursor: var int, keyDown: var CursorDir,
                               intent: ActionIntent, ring: int) =
  if intent.cursor == CursorNone:
    keyDown = CursorNone
    return
  if keyDown == CursorNone:
    if intent.cursor == CursorRight:
      cursor = (cursor + 1) mod ring
    elif intent.cursor == CursorLeft:
      cursor = (cursor - 1 + ring) mod ring
  keyDown = intent.cursor

proc testAutoVotePulsesThroughMultipleCursorSteps() =
  var belief = makeVotingBelief(cursor = 0, selfSlot = 1)
  var scratch = makeScratch(belief)
  var cursor = 0
  var keyDown = CursorNone
  var pressedAt = -1

  for i in 0 .. 40:
    belief.tick = 100 + MeetingAutoVoteDelayTicks + i
    belief.percep.votingCursor = cursor
    let intent = meetingMode.decide(belief, meetingParams(), scratch)
    if intent.pressA:
      pressedAt = i
      break
    advanceCursorOnFreshPress(cursor, keyDown, intent, ring = 5)

  expectEq(cursor, 2,
           "edge-triggered cursor simulation reaches the right-neighbor target")
  expect(pressedAt >= 0,
         "auto-vote eventually confirms after multiple cursor pulses")

proc main() =
  testLlmSelfVoteRedirectsToSkip()
  testConfirmOnSelfRedirectsToSkip()
  testConfirmOnSkipStillVotes()
  testAutoVoteTargetsRightNeighbor()
  testAutoVoteSkipsDeadRightNeighbor()
  testAutoVoteConfirmsRightNeighbor()
  testAutoVotePulsesThroughMultipleCursorSteps()

  if failures == 0:
    echo "OK (meeting vote safety checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
