## End-to-end voting pipeline checks against real voting-screen frames.
##
## This test exercises the bot pipeline rather than only the pure parser:
## once PhaseVoting is active, subsequent voting frames must still refresh
## votingCursor so meeting-mode cursor navigation can make progress.

import std/[os, strformat]
import ../constants
import ../types
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

proc main() =
  testVotingCursorRefreshesAfterPhaseVoting()
  testRightNeighborAutoVoteConfirms()

  if failures == 0:
    echo "OK (voting pipeline checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
