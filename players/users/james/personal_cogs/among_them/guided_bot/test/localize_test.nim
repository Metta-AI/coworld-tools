## Phase-1.2 camera-localization tests.
##
## Pins guided_bot's localizer behavior against the ground truth from
## modulabot's own ``Localizer`` (run on the same fixture frames; see
## the comment block before each ``expectEq`` for the exact values).
## Because both implementations route the heavy work through the same
## ``mb_score_camera`` / ``mb_hash_frame_patches`` /
## ``mb_vote_camera_candidates`` kernels under
## ``among_them/common/perception_kernels/``, drift between Python
## and Nim orchestration shows up as a camera-position mismatch on
## these frames.
##
## Coverage:
##   - Camera math primitives (``minCameraX/Y`` etc.) match modulabot
##     and ``among_them/players/modulabot/geometry.nim``.
##   - Patch-index lazy build runs once and produces a non-empty,
##     hash-sorted index covering the camera grid.
##   - ``updateLocation`` against an interstitial-free fixture frame
##     produces the expected camera offset and lock kind.
##   - ``reseedCameraAtHome`` resets the camera to button (no home
##     set) or to the homeed world position.
##   - End-to-end pipeline via ``bot.stepUnpackedFrame`` populates
##     ``belief.percep.cameraX/Y/selfX/Y`` after a gameplay frame and
##     leaves them stale (last-good camera) on an interstitial.
##   - Smoke benchmark — cold + warm ``updateLocation`` complete in a
##     plausible time bound. We don't pin a wall-clock number, just
##     check that we're not catastrophically slow.
##
## Run::
##
##     nim c -r -d:release --threads:on --mm:orc \
##         among_them/guided_bot/test/localize_test.nim

import std/[monotimes, os, strformat, times]
import ../constants
import ../types
import ../belief
import ../bot
import ../perception
import ../perception/data
import ../perception/geometry
import ../perception/localize

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
  let here = currentSourcePath().parentDir()
  let path = here / "fixtures" / name
  let data = readFile(path)
  doAssert data.len == FrameLen, "fixture wrong length: " & name
  result = newSeq[uint8](FrameLen)
  for i in 0 ..< FrameLen:
    result[i] = uint8(data[i])

# ---------------------------------------------------------------------------
# 1. Camera math
# ---------------------------------------------------------------------------

proc testGeometry() =
  # Fixed values pinned to modulabot/geometry.py for Skeld:
  #   ScreenWidth = 128, ScreenHeight = 128, SpriteSize = 12,
  #   MapWidth = 952, MapHeight = 534.
  expectEq(minCameraX(), -76,  "minCameraX")        # -64 - 12
  expectEq(maxCameraX(), 900,  "maxCameraX")        # 952 - 64 + 12
  expectEq(minCameraY(), -76,  "minCameraY")        # -64 - 12
  expectEq(maxCameraY(), 482,  "maxCameraY")        # 534 - 64 + 12

  # Player-screen anchor: centre of 128×128 minus the sprite-half.
  # PlayerScreenX = 64, PlayerScreenY = 64 here (matching modulabot's
  # convention; see modulabot/geometry.py PLAYER_SCREEN_X).
  expectEq(PlayerScreenX, 64, "PlayerScreenX")
  expectEq(PlayerScreenY, 64, "PlayerScreenY")
  # PlayerWorldOffX = SpriteDrawOffX + 64 - 6 = 2 + 58 = 60
  expectEq(PlayerWorldOffX, 60, "PlayerWorldOffX")
  # PlayerWorldOffY = SpriteDrawOffY + 64 - 6 = 8 + 58 = 66
  expectEq(PlayerWorldOffY, 66, "PlayerWorldOffY")

  # Button camera: button rect is (524, 114, 28, 34) per Skeld
  # map.json. Centre is (538, 131). camera = centre - PlayerWorldOff
  # = (478, 65), inside bounds.
  let bx = buttonCameraX(referenceData.map)
  let by = buttonCameraY(referenceData.map)
  expectEq(bx, 478, "buttonCameraX(skeld)")
  expectEq(by, 65,  "buttonCameraY(skeld)")

  # cameraCanHoldPlayer: button camera puts player at (538, 131),
  # well inside the map.
  expect(cameraCanHoldPlayer(bx, by),
         "button camera holds player on map")
  # Way past the right edge: not on map.
  expect(not cameraCanHoldPlayer(maxCameraX(), maxCameraY()),
         "extreme camera does not hold player")

# ---------------------------------------------------------------------------
# 2. Patch index
# ---------------------------------------------------------------------------

proc testPatchIndex() =
  let idx = getPatchIndex()
  # Camera-anchor grid spans the camera rectangle plus
  # ScreenWidth - PatchSize = 120 in each direction.
  let expectedW = (maxCameraX() - minCameraX() + 1) +
    (ScreenWidth - PatchSize)
  let expectedH = (maxCameraY() - minCameraY() + 1) +
    (ScreenHeight - PatchSize)
  expectEq(idx.width,  expectedW, "patch index width")
  expectEq(idx.height, expectedH, "patch index height")
  expectEq(idx.hashes.len, expectedW * expectedH, "patch index entry count")
  expectEq(idx.camXs.len, idx.hashes.len, "co-sized cam_xs")
  expectEq(idx.camYs.len, idx.hashes.len, "co-sized cam_ys")

  # Hashes are sorted ascending — ``mb_vote_camera_candidates``
  # binary-searches them.
  var sorted = true
  for i in 1 ..< idx.hashes.len:
    if idx.hashes[i] < idx.hashes[i - 1]:
      sorted = false
      break
  expect(sorted, "patch index hashes are sorted ascending")

  # Cached: a second call returns the same value without rebuilding.
  let idx2 = getPatchIndex()
  expectEq(idx2.hashes.len, idx.hashes.len, "patch index cached")

# ---------------------------------------------------------------------------
# 3. updateLocation against a fixture
# ---------------------------------------------------------------------------

proc testUpdateLocationGameplay150() =
  ## Ground truth from modulabot.localize.Localizer on a fresh bot:
  ##   gameplay_150.bin → camera=(504, 54), FrameMapLock,
  ##   localized=True. Score within a hundred or so of -25489.
  var loc = initLocalizer()
  var p = initPerceptionState()
  let frame = loadFixture("gameplay_150.bin")
  let pcpt = perceive(frame, tick = 1)
  loc.updateLocation(p, frame, pcpt.ignoreMask.data, tick = 1)

  expect(p.localized, "gameplay_150: localized")
  expectEq(p.cameraX, 504, "gameplay_150: cameraX")
  expectEq(p.cameraY, 54,  "gameplay_150: cameraY")
  expectEq(p.cameraLock, FrameMapLock, "gameplay_150: lock")
  expect(p.gameStarted, "gameplay_150: gameStarted set")
  expect(p.homeSet,     "gameplay_150: homeSet")
  expectEq(p.selfX, p.cameraX + PlayerWorldOffX, "gameplay_150: selfX")
  expectEq(p.selfY, p.cameraY + PlayerWorldOffY, "gameplay_150: selfY")
  expectEq(p.lastLocalizedTick, 1, "gameplay_150: lastLocalizedTick")

proc testUpdateLocationSequence() =
  ## Walk the gameplay sequence the runtime would produce on a single
  ## Bot. Modulabot ground truth (sequential, with the kernel-shared
  ## scoring path):
  ##   131 → not localized (cold, ignore-mask covers too much)
  ##   150 → (504, 54) FrameMapLock
  ##   200 → (504, 54) LocalFrameMapLock  (local refit from previous)
  ##   274 → (504, 54) LocalFrameMapLock
  var loc = initLocalizer()
  var p = initPerceptionState()

  type Step = tuple[
    name: string,
    expectLoc: bool,
    expectX, expectY: int,
    expectLock: CameraLock]

  let steps: array[4, Step] = [
    ("gameplay_131.bin", false, 0,   0,  NoLock),
    ("gameplay_150.bin", true,  504, 54, FrameMapLock),
    ("gameplay_200.bin", true,  504, 54, LocalFrameMapLock),
    ("gameplay_274.bin", true,  504, 54, LocalFrameMapLock),
  ]

  var tick = 0
  for s in steps:
    inc tick
    let frame = loadFixture(s.name)
    let pcpt = perceive(frame, tick = tick)
    loc.updateLocation(p, frame, pcpt.ignoreMask.data, tick = tick)
    expectEq(p.localized, s.expectLoc, &"seq[{s.name}]: localized")
    if s.expectLoc:
      expectEq(p.cameraX, s.expectX, &"seq[{s.name}]: cameraX")
      expectEq(p.cameraY, s.expectY, &"seq[{s.name}]: cameraY")
      expectEq(p.cameraLock, s.expectLock, &"seq[{s.name}]: lock")
      # Self-position is recomputed every accepted lock.
      expectEq(p.selfX, p.cameraX + PlayerWorldOffX,
               &"seq[{s.name}]: selfX")

# ---------------------------------------------------------------------------
# 4. reseedCameraAtHome
# ---------------------------------------------------------------------------

proc testReseedAtHome() =
  var loc = initLocalizer()
  var p = initPerceptionState()

  # Fresh perception: home not set → reseed sends camera to button.
  loc.reseedCameraAtHome(p)
  expect(not p.localized, "reseed (no home): localized=false")
  expectEq(p.cameraX, buttonCameraX(referenceData.map),
           "reseed (no home): camera at button X")
  expectEq(p.cameraY, buttonCameraY(referenceData.map),
           "reseed (no home): camera at button Y")
  expectEq(p.cameraLock, NoLock, "reseed (no home): lock=NoLock")

  # After a gameplay lock, home is set and reseed centres on it.
  let frame = loadFixture("gameplay_150.bin")
  let pcpt = perceive(frame, tick = 1)
  loc.updateLocation(p, frame, pcpt.ignoreMask.data, tick = 1)
  expect(p.homeSet, "after lock: homeSet")
  let homeX = p.homeX
  let homeY = p.homeY

  # Now move the camera away (simulating drift), then reseed.
  p.cameraX = 0
  p.cameraY = 0
  p.localized = true
  loc.reseedCameraAtHome(p)
  expect(not p.localized, "reseed (home set): localized=false")
  expectEq(p.cameraX, cameraXForWorld(homeX),
           "reseed (home set): cameraX = cameraXForWorld(homeX)")
  expectEq(p.cameraY, cameraYForWorld(homeY),
           "reseed (home set): cameraY = cameraYForWorld(homeY)")

# ---------------------------------------------------------------------------
# 5. End-to-end via bot.stepUnpackedFrame
# ---------------------------------------------------------------------------

proc testBotPipeline() =
  ## Verify the bot pipeline calls localize on gameplay frames and
  ## skips it on interstitials, populating the belief's perception
  ## fields appropriately. This is the same path the FFI / cogames
  ## entry exercises.
  var bot = initBot()

  # Sequential walk: interstitial → gameplay_150 → interstitial → gameplay_200.
  discard bot.stepUnpackedFrame(loadFixture("interstitial_5.bin"))
  expect(not bot.belief.percep.localized,
         "after interstitial: not localized")

  discard bot.stepUnpackedFrame(loadFixture("gameplay_150.bin"))
  expect(bot.belief.percep.localized,
         "after gameplay_150: localized")
  expectEq(bot.belief.percep.cameraX, 504, "pipeline: cameraX")
  expectEq(bot.belief.percep.cameraY, 54,  "pipeline: cameraY")
  expectEq(bot.belief.percep.selfX, 504 + PlayerWorldOffX, "pipeline: selfX")
  expectEq(bot.belief.percep.selfY, 54 + PlayerWorldOffY,  "pipeline: selfY")
  expect(bot.belief.percep.homeSet, "pipeline: homeSet after first lock")

  # Interstitial should clear localized and reseed at home.
  discard bot.stepUnpackedFrame(loadFixture("interstitial_0.bin"))
  expect(not bot.belief.percep.localized,
         "interstitial after lock: localized cleared")
  expect(bot.belief.percep.homeSet,
         "interstitial after lock: homeSet preserved")

  # Next gameplay frame should localize again.
  discard bot.stepUnpackedFrame(loadFixture("gameplay_200.bin"))
  expect(bot.belief.percep.localized,
         "after second gameplay: localized")
  expectEq(bot.belief.percep.cameraX, 504, "pipeline (2): cameraX")
  expectEq(bot.belief.percep.cameraY, 54,  "pipeline (2): cameraY")

# ---------------------------------------------------------------------------
# 6. Smoke benchmark
# ---------------------------------------------------------------------------

proc testBenchmark() =
  ## Plausibility-only timing: cold + warm localize on the same frame.
  ## Pins are deliberately loose; we're guarding against catastrophic
  ## regressions (e.g. someone disabling the kernels and falling back
  ## to a quadratic Nim path), not measuring perf.
  var loc = initLocalizer()
  var p = initPerceptionState()
  let frame = loadFixture("gameplay_150.bin")
  let pcpt = perceive(frame, tick = 1)

  let t0 = getMonoTime()
  loc.updateLocation(p, frame, pcpt.ignoreMask.data, tick = 1)
  let t1 = getMonoTime()
  loc.updateLocation(p, frame, pcpt.ignoreMask.data, tick = 2)
  let t2 = getMonoTime()

  let coldMs = float((t1 - t0).inMilliseconds)
  let warmMs = float((t2 - t1).inMilliseconds)
  echo &"  bench: cold={coldMs:.1f} ms, warm={warmMs:.1f} ms"

  # Cold path includes patch-index build (~100-500 ms scalar) on
  # first call, so be lenient. Warm path is local refit only —
  # MISSION.md targets ~1 ms with the kernels; allow 50 ms here.
  expect(coldMs < 5000.0, &"bench: cold <5s, got {coldMs} ms")
  expect(warmMs < 50.0,   &"bench: warm <50ms, got {warmMs} ms")

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

proc main() =
  testGeometry()
  testPatchIndex()
  testUpdateLocationGameplay150()
  testUpdateLocationSequence()
  testReseedAtHome()
  testBotPipeline()
  testBenchmark()

  if failures == 0:
    echo "OK (all perception phase-1.2 localize checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
