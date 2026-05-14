## End-to-end voting pipeline checks against real voting-screen frames.
##
## This test exercises the bot pipeline rather than only the pure parser:
## once PhaseVoting is active, subsequent voting frames must still refresh
## votingCursor so meeting-mode cursor navigation can make progress.

import std/[os, strformat]
import ../constants
import ../types
import ../belief
import ../bot
import ../tuning
import ../perception/voting

const FixtureDir = currentSourcePath().parentDir / "fixtures"

var failures = 0

proc expect(cond: bool, label: string) =
  if not cond:
    stderr.writeLine "FAIL: ", label
    inc failures

proc expectEq[T](got, want: T, label: string) =
  if got != want:
    stderr.writeLine &"FAIL: {label}: got {got}, want {want}"
    inc failures

proc loadFixture(name: string): seq[uint8] =
  let path = FixtureDir / name
  let data = readFile(path)
  result = newSeq[uint8](data.len)
  for i, ch in data:
    result[i] = uint8(ord(ch)) and 0x0f'u8

proc clearCursor(frame: var seq[uint8], count: int) =
  let layout = voteGridLayout(count)
  for i in 0 ..< count:
    let (cx, cy) = voteCellOrigin(layout, count, i)
    for y in [cy - 1, cy + VoteCellH - 2]:
      if y < 0 or y >= ScreenHeight: continue
      for x in cx ..< cx + VoteCellW:
        if x >= 0 and x < ScreenWidth and
           frame[y * ScreenWidth + x] == CursorColor:
          frame[y * ScreenWidth + x] = 0'u8
  for y in [layout.skipY - 1, layout.skipY + 6]:
    if y < 0 or y >= ScreenHeight: continue
    for x in layout.skipX ..< layout.skipX + VoteSkipW:
      if x >= 0 and x < ScreenWidth and
         frame[y * ScreenWidth + x] == CursorColor:
        frame[y * ScreenWidth + x] = 0'u8

proc setCursor(frame: var seq[uint8], count, slot: int) =
  clearCursor(frame, count)
  let layout = voteGridLayout(count)
  if slot >= 0 and slot < count:
    let (cx, cy) = voteCellOrigin(layout, count, slot)
    for y in [cy - 1, cy + VoteCellH - 2]:
      if y < 0 or y >= ScreenHeight: continue
      for x in cx ..< cx + VoteCellW:
        if x >= 0 and x < ScreenWidth:
          frame[y * ScreenWidth + x] = CursorColor
  elif slot == count:
    for y in [layout.skipY - 1, layout.skipY + 6]:
      if y < 0 or y >= ScreenHeight: continue
      for x in layout.skipX ..< layout.skipX + VoteSkipW:
        if x >= 0 and x < ScreenWidth:
          frame[y * ScreenWidth + x] = CursorColor

proc testVotingCursorRefreshesAfterPhaseVoting() =
  var frame7 = loadFixture("voting_real_1432.bin")
  var frame0 = loadFixture("voting_real_1432.bin")
  setCursor(frame7, 8, 7)
  setCursor(frame0, 8, 0)

  var b = initBot()
  discard b.stepUnpackedFrame(frame7)
  expectEq(b.belief.self.phase, PhaseVoting,
           "first voting frame enters PhaseVoting")
  expectEq(b.belief.percep.votingCursor, 7,
           "first voting frame cursor parsed as slot 7")
  expectEq(b.belief.percep.votingSelfSlot, 7,
           "fixture self slot parsed as slot 7")

  discard b.stepUnpackedFrame(frame0)
  expectEq(b.belief.percep.votingCursor, 0,
           "subsequent voting frame refreshes cursor after PhaseVoting")

proc testRightNeighborAutoVoteConfirms() =
  var frame0 = loadFixture("voting_real_1432.bin")
  setCursor(frame0, 8, 0)

  var b = initBot()
  b.belief.self.role = RoleCrewmate
  b.belief.memory.perPlayer[0].timesNearBody = 1
  var sawA = false
  for _ in 0 .. MeetingAutoVoteDelayTicks + 8:
    let mask = b.stepUnpackedFrame(frame0)
    if (mask and ButtonA) != 0:
      sawA = true
      break

  expectEq(b.belief.self.phase, PhaseVoting,
           "auto-vote replay remains in PhaseVoting")
  expectEq(b.belief.percep.votingSelfSlot, 7,
           "auto-vote replay self slot parsed")
  expect(sawA, "evidence-target auto-vote eventually presses A")

proc syntheticVotingParse(chatText: string): VotingParse =
  result = initVotingParse()
  result.valid = true
  result.playerCount = 2
  result.cursor = 0
  result.selfSlot = 0
  result.slots[0] = VoteSlot(colorIndex: 0, alive: true)
  result.slots[1] = VoteSlot(colorIndex: 1, alive: true)
  result.chatLines = @[
    VoteChatLine(speakerColor: 1, y: 31, text: chatText)
  ]

proc testVotingChatMergeTracksNewContent() =
  var b = initBelief()
  b.tick = 100

  mergeVotingPercept(b, syntheticVotingParse("body nav"))
  expectEq(b.social.currentMeetingChat.len, 1,
           "chat merge: visible chat populated")
  expectEq(b.social.recentChat.len, 1,
           "chat merge: recent chat receives first line")
  expectEq(b.social.pendingChatObserved.len, 1,
           "chat merge: first line marked pending")
  expect(WakeChatObserved in b.flags.wakeReasons,
         "chat merge: first line raises wake reason")

  b.flags.wakeReasons = {}
  b.tick = 101
  mergeVotingPercept(b, syntheticVotingParse("body nav"))
  expectEq(b.social.currentMeetingChat.len, 1,
           "chat merge: repeated visible line remains visible")
  expectEq(b.social.recentChat.len, 1,
           "chat merge: repeated line is deduplicated")
  expectEq(b.social.pendingChatObserved.len, 0,
           "chat merge: repeated line is not pending")
  expect(not (WakeChatObserved in b.flags.wakeReasons),
         "chat merge: repeated line does not raise wake reason")

  b.tick = 102
  mergeVotingPercept(b, syntheticVotingParse("vote red"))
  expectEq(b.social.currentMeetingChat.len, 1,
           "chat merge: one visible row can change text")
  expectEq(b.social.recentChat.len, 2,
           "chat merge: changed text appends to recent chat")
  expectEq(b.social.pendingChatObserved.len, 1,
           "chat merge: changed text marked pending despite same row count")
  expectEq(b.social.pendingChatObserved[0].speakerColor, 1,
           "chat merge: pending line preserves speaker attribution")
  expectEq(b.social.pendingChatObserved[0].text, "vote red",
           "chat merge: pending line preserves text")

proc main() =
  testVotingCursorRefreshesAfterPhaseVoting()
  testRightNeighborAutoVoteConfirms()
  testVotingChatMergeTracksNewContent()

  if failures == 0:
    echo "OK (voting pipeline checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
