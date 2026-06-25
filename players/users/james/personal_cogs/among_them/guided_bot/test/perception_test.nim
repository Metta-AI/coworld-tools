## Phase-1.0 perception tests. Runs against the real fixture frames in
## `test/fixtures/*.bin` — 128×128 uint8 palette-index dumps captured
## from a real Among Them game.
##
## Exit 0 iff every check below passes. Failures print a concrete
## "expected / got" line so regressions are immediately diagnosable
## without a debugger.
##
## Coverage (by what's exercised):
##   - `unpack4bpp` round-trip correctness and bounds behaviour.
##   - `blackPixelCount` and `pixelAt` primitives.
##   - Interstitial detector classification of captured frames.
##   - Phase-1.0 ignore-mask component count and shape.
##   - Full `perceive` + `updateBelief` end-to-end against fixtures.
##   - `bot.stepUnpackedFrame` producing a consistent belief-phase
##     transition over the interstitial-to-gameplay crossover.
##
## Run:
##   nim c -r -d:release --threads:on --mm:orc \
##       among_them/guided_bot/test/perception_test.nim
##
## Phase 1.1+ will add tests for data loading, localization accuracy
## against the fixture camera ground-truth, etc. The harness style
## stays the same (binary fixtures; per-fixture expected values
## baked into the test file).

import std/[os, strformat]
import ../constants
import ../types
import ../belief
import ../bot
import ../perception
import ../perception/frame
import ../perception/interstitial
import ../perception/ignore

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

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
  ## Read one 16384-byte fixture into a `seq[uint8]`.
  let here = currentSourcePath().parentDir()
  let path = here / "fixtures" / name
  let data = readFile(path)
  doAssert data.len == FrameLen,
    "fixture " & name & " wrong length: " & $data.len
  result = newSeq[uint8](FrameLen)
  for i in 0 ..< FrameLen:
    result[i] = uint8(data[i])

# ---------------------------------------------------------------------------
# 1. unpack4bpp primitives
# ---------------------------------------------------------------------------

proc testUnpack4bpp() =
  # One byte unpacks to (low-nybble, high-nybble) — the order matters;
  # matches modulabot Python's `pixels[0::2] = packed & 0x0F;
  # pixels[1::2] = packed >> 4`.
  let packed = @[0x12'u8, 0xAB, 0xFF]
  var dst = newSeq[uint8](6)
  unpack4bpp(packed, dst)
  expectEq(dst[0], 0x02'u8, "unpack4bpp[0]: low nybble of 0x12")
  expectEq(dst[1], 0x01'u8, "unpack4bpp[1]: high nybble of 0x12")
  expectEq(dst[2], 0x0B'u8, "unpack4bpp[2]: low nybble of 0xAB")
  expectEq(dst[3], 0x0A'u8, "unpack4bpp[3]: high nybble of 0xAB")
  expectEq(dst[4], 0x0F'u8, "unpack4bpp[4]: low nybble of 0xFF")
  expectEq(dst[5], 0x0F'u8, "unpack4bpp[5]: high nybble of 0xFF")

  # Allocating form.
  let allocated = unpack4bpp(packed)
  expectEq(allocated.len, 6, "unpack4bpp alloc: output length")
  for i in 0 ..< 6:
    expectEq(allocated[i], dst[i], &"unpack4bpp alloc[{i}] matches in-place")

# ---------------------------------------------------------------------------
# 2. pixel helpers
# ---------------------------------------------------------------------------

proc testPixelHelpers() =
  let black = loadFixture("interstitial_0.bin")
  let gameplay = loadFixture("gameplay_200.bin")

  # `blackPixelCount` is a linear scan. Ground truth (computed by
  # counting zero bytes in the fixture file; see
  # historical fixture extraction):
  #   interstitial_0.bin -> 16067
  #   gameplay_200.bin   ->    60
  # We allow exact equality; the fixtures are fixed byte streams.
  expectEq(blackPixelCount(black),    16067, "blackPixelCount(interstitial_0)")
  expectEq(blackPixelCount(gameplay),    60, "blackPixelCount(gameplay_200)")

  # `pixelAt` bounds behaviour.
  expectEq(pixelAt(gameplay, -1, 0),      0'u8, "pixelAt OOB negative x")
  expectEq(pixelAt(gameplay, 0, -1),      0'u8, "pixelAt OOB negative y")
  expectEq(pixelAt(gameplay, ScreenWidth, 0),   0'u8, "pixelAt OOB x")
  expectEq(pixelAt(gameplay, 0, ScreenHeight),  0'u8, "pixelAt OOB y")
  # In-bounds indexed access matches direct seq read.
  expectEq(pixelAt(gameplay, 10, 20), gameplay[20 * ScreenWidth + 10],
           "pixelAt(10, 20) matches direct access")

# ---------------------------------------------------------------------------
# 3. interstitial detection
# ---------------------------------------------------------------------------

proc testInterstitialDetection() =
  type Case = tuple[name: string, expectInter: bool, expectKind: InterstitialKind]
  let cases: seq[Case] = @[
    ("interstitial_0.bin",   true,  InterstitialUnknown),
    ("interstitial_5.bin",   true,  InterstitialUnknown),
    ("interstitial_100.bin", true,  InterstitialUnknown),
    ("gameplay_131.bin",     false, NotInterstitial),
    ("gameplay_150.bin",     false, NotInterstitial),
    ("gameplay_200.bin",     false, NotInterstitial),
    ("gameplay_274.bin",     false, NotInterstitial),
  ]
  for c in cases:
    let frame = loadFixture(c.name)
    let obs = detectInterstitial(frame)
    expectEq(obs.isInterstitial, c.expectInter,
             &"{c.name}: isInterstitial")
    expectEq(obs.kind, c.expectKind, &"{c.name}: kind")
    expectEq(obs.blackPixelCount, blackPixelCount(frame),
             &"{c.name}: blackPixelCount cached correctly")

  # Threshold is 30 %: a frame that's exactly at threshold is
  # classified as interstitial, one pixel below is not.
  var synthetic = newSeq[uint8](FrameLen)
  # Zero frame: 100 % black -> clearly interstitial.
  expect(detectInterstitial(synthetic).isInterstitial,
         "all-zero frame is interstitial")

  # Set first 70 % to non-black; remaining 30 % is black, exactly at
  # threshold. Should still be classified as interstitial.
  let nonBlackN = (FrameLen * 70) div 100
  for i in 0 ..< nonBlackN:
    synthetic[i] = 12'u8
  expectEq(blackPixelCount(synthetic), FrameLen - nonBlackN,
           "30%-threshold fixture black count")
  expect(detectInterstitial(synthetic).isInterstitial,
         "30% black is still interstitial (>= threshold)")

  # Drop one more black pixel below threshold; now not interstitial.
  synthetic[nonBlackN] = 12'u8
  expect(not detectInterstitial(synthetic).isInterstitial,
         "below-threshold is not interstitial")

# ---------------------------------------------------------------------------
# 4. phase transition
# ---------------------------------------------------------------------------

proc testPhaseFromInterstitial() =
  let interObs = InterstitialObservation(
    isInterstitial: true, kind: InterstitialUnknown, blackPixelCount: 15000)
  let gameObs = InterstitialObservation(
    isInterstitial: false, kind: NotInterstitial, blackPixelCount: 50)

  # Interstitial observation flips Unknown / Gameplay to Interstitial,
  # but preserves Voting / GameOver (to avoid Phase 1.5's OCR-based
  # refinement being clobbered by the cheap black-% detector).
  expectEq(phaseFromInterstitial(PhaseUnknown, interObs),  PhaseInterstitial,
           "Unknown  + inter -> Interstitial")
  expectEq(phaseFromInterstitial(PhaseGameplay, interObs), PhaseInterstitial,
           "Gameplay + inter -> Interstitial")
  expectEq(phaseFromInterstitial(PhaseVoting, interObs),   PhaseVoting,
           "Voting   + inter -> Voting (persist)")
  expectEq(phaseFromInterstitial(PhaseGameOver, interObs), PhaseGameOver,
           "GameOver + inter -> GameOver (persist)")

  # Non-interstitial observation always transitions to Gameplay
  # (phase 1.0 doesn't distinguish Lobby — that arrives later).
  for prev in [PhaseUnknown, PhaseGameplay, PhaseInterstitial,
               PhaseVoting, PhaseGameOver]:
    expectEq(phaseFromInterstitial(prev, gameObs), PhaseGameplay,
             &"{prev} + gameplay obs -> Gameplay")

# ---------------------------------------------------------------------------
# 5. ignore-mask scaffolding
# ---------------------------------------------------------------------------

proc testIgnoreMask() =
  let frame = loadFixture("gameplay_200.bin")
  var mask = initIgnoreMask()
  expectEq(mask.data.len, FrameLen, "mask data length")
  expectEq(mask.countSet(), 0, "fresh mask has no bits set")

  buildPhase10IgnoreMask(mask, frame)

  # Player-centre zone: a (2*PlayerIgnoreRadius+1) square = 19x19 = 361.
  # `stampPlayerCentreZone` includes both endpoints, so the block is
  # 19 wide by 19 tall = 361 pixels — these are always set.
  const centreCells = (2 * PlayerIgnoreRadius + 1) * (2 * PlayerIgnoreRadius + 1)
  expect(mask.isSet(PlayerSpriteAnchorX, PlayerSpriteAnchorY),
         "player centre is in mask")
  expect(mask.isSet(PlayerSpriteAnchorX - PlayerIgnoreRadius,
                    PlayerSpriteAnchorY - PlayerIgnoreRadius),
         "player-centre upper-left corner in mask")
  expect(mask.isSet(PlayerSpriteAnchorX + PlayerIgnoreRadius,
                    PlayerSpriteAnchorY + PlayerIgnoreRadius),
         "player-centre lower-right corner in mask")
  expect(not mask.isSet(PlayerSpriteAnchorX + PlayerIgnoreRadius + 1, PlayerSpriteAnchorY),
         "one pixel past the centre zone is not in mask (unless radar)")

  # Count expectations. Minimum bits set = centreCells (if no radar
  # pixels in this frame). A real gameplay frame may have a few radar
  # dots, pushing the count up. Sanity-check: mask count >=
  # centreCells and < FrameLen.
  let count = mask.countSet()
  expect(count >= centreCells,
         &"mask count {count} >= player-centre {centreCells}")
  expect(count < FrameLen,
         &"mask count {count} < FrameLen {FrameLen}")

  # Radar pixels: any frame pixel with palette index 8 must be masked.
  var radarCount = 0
  for i in 0 ..< FrameLen:
    if frame[i] == RadarTaskColor:
      inc radarCount
      expectEq(mask.data[i], 1'u8,
               &"radar pixel at offset {i} must be in mask")

  # Idempotency: rebuilding on the same frame gives the same result.
  let before = mask.countSet()
  buildPhase10IgnoreMask(mask, frame)
  expectEq(mask.countSet(), before, "buildPhase10IgnoreMask is idempotent")

# ---------------------------------------------------------------------------
# 6. full perceive()
# ---------------------------------------------------------------------------

proc testPerceiveEndToEnd() =
  let inter = loadFixture("interstitial_0.bin")
  let game  = loadFixture("gameplay_150.bin")

  let pInter = perceive(inter, tick = 1)
  expectEq(pInter.tick, 1, "perceive: tick forwarded")
  expect(pInter.interstitial.isInterstitial,
         "perceive(interstitial frame): interstitial observed")
  expectEq(pInter.interstitial.kind, InterstitialUnknown,
           "perceive(interstitial frame): kind Unknown (phase 1.0)")
  expect(pInter.ignoreMask.countSet() > 0,
         "perceive: ignore mask has bits set even for interstitial")

  let pGame = perceive(game, tick = 42)
  expectEq(pGame.tick, 42, "perceive: tick forwarded for gameplay")
  expect(not pGame.interstitial.isInterstitial,
         "perceive(gameplay frame): no interstitial")
  expect(pGame.ignoreMask.countSet() > 0,
         "perceive: ignore mask populated for gameplay frame too")

# ---------------------------------------------------------------------------
# 7. end-to-end belief merge via stepUnpackedFrame
# ---------------------------------------------------------------------------

proc testStepUnpackedFrameBeliefMerge() =
  var bot = initBot()
  expectEq(bot.belief.self.phase, PhaseUnknown,
           "initBot phase is Unknown")
  expect(not bot.belief.percep.interstitial,
         "initBot: no interstitial")

  # Step through an interstitial frame.
  let inter = loadFixture("interstitial_5.bin")
  discard bot.stepUnpackedFrame(inter)
  expectEq(bot.frameTick, 1, "after one step, frameTick=1")
  expectEq(bot.belief.tick, 1, "after one step, belief.tick=1")
  expect(bot.belief.percep.interstitial,
         "interstitial frame: belief.percep.interstitial set")
  expectEq(bot.belief.self.phase, PhaseInterstitial,
           "interstitial frame: belief.self.phase = Interstitial")
  # Phase 3: wake flags are now consumed (submitted to guidance) and
  # cleared within decideNextMask. We can't check them after the call.
  # The WakeMeetingStarted flag was raised and consumed within the tick.

  # Step through a second interstitial: should NOT re-raise the flag
  # (phase was already Interstitial).
  # Phase 3: flags are cleared within the tick, so no manual clear needed.
  let inter2 = loadFixture("interstitial_100.bin")
  discard bot.stepUnpackedFrame(inter2)
  expectEq(bot.belief.self.phase, PhaseInterstitial,
           "still interstitial: phase remains Interstitial")
  expect(WakeMeetingStarted notin bot.belief.flags.wakeReasons,
         "second interstitial does not re-raise WakeMeetingStarted")

  # Transition to gameplay.
  let game = loadFixture("gameplay_131.bin")
  discard bot.stepUnpackedFrame(game)
  expectEq(bot.belief.self.phase, PhaseGameplay,
           "gameplay frame: phase -> Gameplay")
  expect(not bot.belief.percep.interstitial,
         "gameplay frame: interstitial cleared")

  # Interstitial again: WakeMeetingStarted fires (re-entering).
  # Phase 3: wake flags consumed within the tick; just verify the
  # phase transition works correctly.
  let inter3 = loadFixture("interstitial_0.bin")
  discard bot.stepUnpackedFrame(inter3)
  expectEq(bot.belief.self.phase, PhaseInterstitial,
           "re-entering interstitial: phase = Interstitial")

  # Tick count sanity.
  expectEq(bot.frameTick, 4, "four step calls -> frameTick=4")
  expectEq(bot.belief.tick, 4, "belief.tick in sync with frameTick")

  # Action layer returns no-op through phase 1.0.
  expectEq(bot.lastMask, 0'u8, "phase 1.0: mask still 0 (action layer stub)")

# ---------------------------------------------------------------------------
# 8. end-to-end fixture sweep — ensures every fixture frame runs
#    through the pipeline without assertions firing.
# ---------------------------------------------------------------------------

proc testFixtureSweep() =
  const fixtures = [
    "interstitial_0.bin", "interstitial_5.bin", "interstitial_100.bin",
    "gameplay_131.bin", "gameplay_150.bin", "gameplay_200.bin",
    "gameplay_274.bin",
  ]
  var bot = initBot()
  var lastMask: uint8 = 255
  for name in fixtures:
    let frame = loadFixture(name)
    lastMask = bot.stepUnpackedFrame(frame)
  # Phase 5: after gameplay_150 localizes and detects the crewmate role,
  # the stale-default re-evaluation (bot.nim:reconcileDirective) switches
  # from ModeIdle to ModeTaskCompleting, which emits directional movement.
  # The last frame (gameplay_274) runs in that mode and may produce a
  # non-zero mask. The important thing is no crash, not mask == 0.
  expect(lastMask != 255'u8, "fixture sweep: last mask updated from sentinel")
  expectEq(bot.frameTick, fixtures.len,
           "fixture sweep: frameTick == frame count")

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

proc main() =
  testUnpack4bpp()
  testPixelHelpers()
  testInterstitialDetection()
  testPhaseFromInterstitial()
  testIgnoreMask()
  testPerceiveEndToEnd()
  testStepUnpackedFrameBeliefMerge()
  testFixtureSweep()

  if failures == 0:
    echo "OK (all perception phase-1.0 checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
