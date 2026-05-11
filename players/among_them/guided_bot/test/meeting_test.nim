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
import ../action
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

proc testSpeakActionEmitsChatIntent() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  var scratch = makeScratch(belief)
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActSpeak,
    text: "red was near body",
    target: -1)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(intent.chat, "red was near body",
           "speak action exposes chat text on intent")

proc testEmitChatQueuesSanitizedText() =
  var state = initActionState()

  let queued = emitChat(state, 100, "  red was near body  ")
  expect(queued, "emitChat queues a clean chat line")
  expectEq(state.pendingChat, "red was near body",
           "emitChat trims outbound chat")

  let blocked = emitChat(state, 101, "second line")
  expect(not blocked, "emitChat does not overwrite pending chat")

proc testCrewAutoVoteSkipsWithoutEvidence() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.self.role = RoleCrewmate
  var scratch = makeScratch(belief)
  belief.tick = 100 + MeetingAutoVoteDelayTicks

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 4,
           "crew auto-vote targets SKIP without evidence")
  expect(not intent.pressA,
         "auto-vote navigates before confirming when cursor is not on target")

proc testCrewAutoVoteTargetsEvidence() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.self.role = RoleCrewmate
  belief.memory.perPlayer[2].timesNearBody = 1
  var scratch = makeScratch(belief)
  belief.tick = 100 + MeetingAutoVoteDelayTicks

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "crew auto-vote targets strongest memory evidence")
  expect(not intent.pressA,
         "auto-vote navigates before confirming the evidence target")

proc testImposterAutoVoteAvoidsKnownPartner() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.self.role = RoleImposter
  belief.self.knownImposterColors = @[2]
  var scratch = makeScratch(belief)
  belief.tick = 100 + MeetingAutoVoteDelayTicks

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 3,
           "imposter auto-vote skips known imposter partner")
  expect(not intent.pressA,
         "imposter auto-vote navigates before confirming")

proc testCrewAutoVoteConfirmsEvidenceTarget() =
  var belief = makeVotingBelief(cursor = 2, selfSlot = 1)
  belief.self.role = RoleCrewmate
  belief.memory.perPlayer[2].timesNearBody = 1
  var scratch = makeScratch(belief)
  belief.tick = 100 + MeetingAutoVoteDelayTicks

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "auto-vote records evidence target even when already on target")
  expect(intent.pressA, "auto-vote presses A on evidence target")
  expect(scratch.meetVoteConfirmed,
         "auto-vote marks evidence-target vote confirmed")

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
  belief.self.role = RoleCrewmate
  belief.memory.perPlayer[2].timesNearBody = 1
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
           "edge-triggered cursor simulation reaches the evidence target")
  expect(pressedAt >= 0,
         "auto-vote eventually confirms after multiple cursor pulses")

proc main() =
  testLlmSelfVoteRedirectsToSkip()
  testConfirmOnSelfRedirectsToSkip()
  testConfirmOnSkipStillVotes()
  testSpeakActionEmitsChatIntent()
  testEmitChatQueuesSanitizedText()
  testCrewAutoVoteSkipsWithoutEvidence()
  testCrewAutoVoteTargetsEvidence()
  testImposterAutoVoteAvoidsKnownPartner()
  testCrewAutoVoteConfirmsEvidenceTarget()
  testAutoVotePulsesThroughMultipleCursorSteps()

  if failures == 0:
    echo "OK (meeting vote safety checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
