## Diagnostic test: pin real voting-screen detection.
##
## The captured voting frames use the live game's 7px SKIP font. This test
## asserts that the voting parser accepts those frames and still rejects
## representative non-voting fixtures.

import std/[os, strformat]
import ../constants
import ../perception/data
import ../perception/voting
import ../perception/frame

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

proc loadFrame(path: string): seq[uint8] =
  let raw = readFile(path)
  assert raw.len == FrameLen, &"fixture size mismatch: {raw.len} != {FrameLen}"
  result = newSeq[uint8](FrameLen)
  copyMem(addr result[0], unsafeAddr raw[0], FrameLen)

proc diagnoseVotingParse(frame: openArray[uint8], label: string) =
  echo &"\n=== Diagnosing: {label} ==="

  # 1. Check black pixel count
  let blackCount = blackPixelCount(frame)
  let blackPct = blackCount * 100 div FrameLen
  echo &"  Black pixels: {blackCount}/{FrameLen} = {blackPct}%"
  let gateResult = if blackPct >= 30: "PASS" else: "FAIL"
  echo &"  Interstitial gate (>=30%): {gateResult}"

  # 2. Try each player count
  for count in countdown(16, 1):
    let layout = voteGridLayout(count)

    # Check SKIP text
    let skipOk = voteSkipTextMatches(frame, layout.skipX, layout.skipY)
    if not skipOk:
      if count <= 10:  # Only print for plausible counts
        echo &"  count={count}: SKIP text NOT found at ({layout.skipX},{layout.skipY})"
      continue
    
    echo &"  count={count}: SKIP text FOUND at ({layout.skipX},{layout.skipY})"
    
    # Check each slot
    var allMatch = true
    for i in 0 ..< count:
      let slot = parseVoteSlot(frame, referenceData.sprites, count, i)
      let (cx, cy) = voteCellOrigin(layout, count, i)
      if slot.colorIndex != i:
        echo &"    slot[{i}] at ({cx},{cy}): colorIndex={slot.colorIndex} alive={slot.alive} MISMATCH (expected {i})"
        allMatch = false
      else:
        echo &"    slot[{i}] at ({cx},{cy}): colorIndex={slot.colorIndex} alive={slot.alive} OK"

    if allMatch:
      echo &"  => ALL SLOTS MATCHED for count={count}! Parse should succeed."
    else:
      echo &"  => SLOT MISMATCH — parse would fail for count={count}"

  # 3. Run the actual parse
  let result = parseVotingScreen(frame, referenceData.sprites, -1)
  echo &"\n  parseVotingScreen result: valid={result.valid} playerCount={result.playerCount} cursor={result.cursor} selfSlot={result.selfSlot}"

proc checkVotingFixture(name, label: string) =
  let frame = loadFrame(FixtureDir / name)
  diagnoseVotingParse(frame, label)
  let result = parseVotingScreen(frame, referenceData.sprites, -1)
  expect(result.valid, &"{name}: parseVotingScreen valid")
  expectEq(result.playerCount, 8, &"{name}: playerCount")
  expect(result.selfSlot >= 0, &"{name}: selfSlot detected without prior self color")
  let layout = voteGridLayout(8)
  expect(voteSkipTextMatches(frame, layout.skipX, layout.skipY),
         &"{name}: SKIP pixel signature found")

proc checkNonVotingFixture(name: string) =
  let frame = loadFrame(FixtureDir / name)
  let result = parseVotingScreen(frame, referenceData.sprites, -1)
  echo &"  non-voting {name}: valid={result.valid} playerCount={result.playerCount}"
  expect(not result.valid, &"{name}: parseVotingScreen rejects non-voting frame")

checkVotingFixture("voting_real_1432.bin", "voting_real_1432 (early meeting)")
checkVotingFixture("voting_real_1500.bin", "voting_real_1500 (mid meeting)")

echo "\n=== Non-voting rejection ==="
for name in [
    "gameplay_150.bin",
    "interstitial_0.bin",
    "interstitial_100.bin",
  ]:
  checkNonVotingFixture(name)

if failures == 0:
  echo "\nOK (real voting frames accepted; non-voting fixtures rejected)"
else:
  stderr.writeLine &"\nFAILED: {failures} check(s)"
  quit(1)
