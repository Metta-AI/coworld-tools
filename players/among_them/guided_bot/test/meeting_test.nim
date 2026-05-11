## Focused meeting-mode safety checks.
##
## Run::
##
##     nim c -r -d:release --threads:on --mm:orc \
##         among_them/guided_bot/test/meeting_test.nim

import std/[json, strformat]
import ../types
import ../belief
import ../tuning
import ../action
import ../snapshot
import ../perception/actors
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

proc testCrewLlmVoteAllowsLlmJudgmentWithoutSymbolicEvidence() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.self.role = RoleCrewmate
  var scratch = makeScratch(belief)
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActVote,
    text: "",
    target: 2)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "crew LLM vote without symbolic evidence keeps legal target")
  expect(not intent.pressA,
         "crew LLM vote navigates before confirming legal target")

proc testCrewLlmVoteTargetsEvidence() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.self.role = RoleCrewmate
  belief.memory.perPlayer[2].timesNearBody = 1
  var scratch = makeScratch(belief)
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActVote,
    text: "",
    target: 2)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "crew LLM vote with concrete evidence keeps the target")
  expect(not intent.pressA,
         "crew LLM vote navigates before confirming evidence target")

proc testImposterLlmVoteAllowsLlmJudgmentWithoutSymbolicSuspicion() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  var scratch = makeScratch(belief)
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActVote,
    text: "",
    target: 2)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "imposter LLM vote without symbolic suspicion keeps legal target")
  expect(not intent.pressA,
         "imposter LLM vote navigates before confirming legal target")

proc testImposterLlmVoteRedirectsKnownPartnerToSkip() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.self.role = RoleImposter
  belief.self.knownImposterColors = @[2]
  var scratch = makeScratch(belief)
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActVote,
    text: "",
    target: 2)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 4,
           "imposter LLM vote for known partner is rewritten to SKIP")
  expect(not intent.pressA,
         "known-partner vote navigates instead of confirming")

proc testImposterLlmVoteTargetsPlausibleSuspicion() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.memory.perPlayer[2].timesNearBody = 1
  var scratch = makeScratch(belief)
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActVote,
    text: "",
    target: 2)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "imposter LLM vote with plausible suspicion keeps the target")
  expect(not intent.pressA,
         "imposter LLM vote navigates before confirming plausible target")

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

proc testConfirmCurrentLegalTargetWithoutSymbolicEvidence() =
  var belief = makeVotingBelief(cursor = 2, selfSlot = 1)
  belief.self.role = RoleCrewmate
  var scratch = makeScratch(belief)
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActConfirmVote,
    text: "",
    target: -1)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "confirm_vote on legal player keeps current cursor target")
  expect(intent.pressA,
         "confirm_vote on legal player presses A without symbolic veto")
  expect(scratch.meetVoteConfirmed,
         "confirm_vote on legal player is marked confirmed")

proc testConfirmEvidenceTarget() =
  var belief = makeVotingBelief(cursor = 2, selfSlot = 1)
  belief.self.role = RoleCrewmate
  belief.memory.perPlayer[2].timesNearBody = 1
  var scratch = makeScratch(belief)
  scratch.meetPendingActions.add MeetingAction(
    kind: MeetingActConfirmVote,
    text: "",
    target: -1)

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 2,
           "confirm_vote on evidenced target preserves the target")
  expect(intent.pressA, "confirm_vote on evidenced target presses A")
  expect(scratch.meetVoteConfirmed,
         "confirm_vote on evidenced target is marked confirmed")

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

  var state2 = initActionState()
  let emDash = chr(226) & chr(128) & chr(148)
  let queued2 = emitChat(state2, 100, "yet" & emDash & "let's discuss")
  expect(queued2, "emitChat queues text with non-ASCII separator")
  expectEq(state2.pendingChat, "yet let's discuss",
           "emitChat replaces non-ASCII punctuation with a space")

proc testNearBodyEvidenceTracksDistanceStrength() =
  var belief = initBelief()
  belief.tick = 10
  belief.self.role = RoleCrewmate
  belief.self.phase = PhaseGameplay
  belief.self.colorIndex = 1
  belief.percep.localized = true
  var actors = initActorPercept()
  actors.crewmates = @[
    CrewmateMatch(x: 40, y: 40, colorIndex: 1, flipH: false),
    CrewmateMatch(x: 50, y: 40, colorIndex: 2, flipH: false)]
  actors.bodies = @[
    BodyMatch(x: 50, y: 42, colorIndex: 4)]

  mergeActorPercept(belief, actors)

  let ps = belief.memory.perPlayer[2]
  expectEq(ps.timesNearBody, 1,
           "near-body memory increments for player close to body")
  expectEq(ps.lastNearBodyDistance, 2,
           "near-body memory records body distance")
  expect(ps.nearBodyEvidenceScore > 1,
         "near-body evidence score grows when player is very close")

proc testSoloTrustAppearsInMeetingEvidenceLedger() =
  var belief = initBelief()
  belief.self.role = RoleCrewmate
  belief.self.phase = PhaseGameplay
  belief.self.colorIndex = 1
  belief.self.alive = true
  belief.percep.localized = true
  var actors = initActorPercept()
  actors.crewmates = @[
    CrewmateMatch(x: 40, y: 40, colorIndex: 1, flipH: false),
    CrewmateMatch(x: 58, y: 40, colorIndex: 2, flipH: false)]

  for tick in 1 .. 12:
    belief.tick = tick
    mergeActorPercept(belief, actors)

  expectEq(belief.memory.perPlayer[2].soloWithSelfTicks, 12,
           "solo survival trust accumulates while alone with one player")
  expectEq(belief.memory.perPlayer[2].currentSoloWithSelfTicks, 12,
           "solo survival trust records current streak")

  belief.self.phase = PhaseVoting
  belief.percep.votingPlayerCount = 4
  belief.percep.votingSelfSlot = 1
  belief.percep.votingCursor = 4
  let snap = parseJson(renderSnapshot(belief))
  let yellow = snap["meeting"]["evidence_ledger"]["yellow"]

  expect(yellow["vote_legal"].getBool(),
         "evidence ledger marks live non-self player as legal vote target")
  expectEq(yellow["exculpatory"][0]["kind"].getStr(),
           "solo_survival_trust",
           "evidence ledger exposes solo survival trust as exculpatory")

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

proc testImposterAutoVoteSkipsWithoutPlausibleSuspicion() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.self.role = RoleImposter
  belief.self.knownImposterColors = @[2]
  var scratch = makeScratch(belief)
  belief.tick = 100 + MeetingAutoVoteDelayTicks

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 4,
           "imposter auto-vote skips when there is no plausible suspicion")
  expect(not intent.pressA,
         "imposter auto-vote navigates before confirming")

proc testImposterAutoVoteTargetsPlausibleSuspicion() =
  var belief = makeVotingBelief(cursor = 1, selfSlot = 1)
  belief.self.role = RoleImposter
  belief.self.knownImposterColors = @[2]
  belief.memory.perPlayer[3].timesNearBody = 1
  var scratch = makeScratch(belief)
  belief.tick = 100 + MeetingAutoVoteDelayTicks

  let intent = meetingMode.decide(belief, meetingParams(), scratch)

  expectEq(scratch.meetVoteTarget, 3,
           "imposter auto-vote targets plausible non-partner suspicion")
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
  testCrewLlmVoteAllowsLlmJudgmentWithoutSymbolicEvidence()
  testCrewLlmVoteTargetsEvidence()
  testImposterLlmVoteAllowsLlmJudgmentWithoutSymbolicSuspicion()
  testImposterLlmVoteRedirectsKnownPartnerToSkip()
  testImposterLlmVoteTargetsPlausibleSuspicion()
  testConfirmOnSelfRedirectsToSkip()
  testConfirmCurrentLegalTargetWithoutSymbolicEvidence()
  testConfirmEvidenceTarget()
  testConfirmOnSkipStillVotes()
  testSpeakActionEmitsChatIntent()
  testEmitChatQueuesSanitizedText()
  testNearBodyEvidenceTracksDistanceStrength()
  testSoloTrustAppearsInMeetingEvidenceLedger()
  testCrewAutoVoteSkipsWithoutEvidence()
  testCrewAutoVoteTargetsEvidence()
  testImposterAutoVoteSkipsWithoutPlausibleSuspicion()
  testImposterAutoVoteTargetsPlausibleSuspicion()
  testCrewAutoVoteConfirmsEvidenceTarget()
  testAutoVotePulsesThroughMultipleCursorSteps()

  if failures == 0:
    echo "OK (meeting vote safety checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
