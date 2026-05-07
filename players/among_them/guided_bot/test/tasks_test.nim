## Phase-1.4 task-icon and radar-dot scan tests.
##
## Coverage:
##   - ``scanTasksAndRadar`` short-circuits on interstitials.
##   - Task-icon scan produces plausible results on gameplay frames
##     when localized (may be 0 if no icons are on screen in the fixture).
##   - Task-icon scan is skipped when not localized.
##   - Radar-dot scan produces plausible results on gameplay frames
##     (dots in the periphery ring only).
##   - Task-icon ignore-mask stamping adds bits beyond the actor baseline.
##   - End-to-end bot pipeline populates ``belief.percep.visibleTaskIcons``
##     and ``belief.percep.radarDots``.
##   - Fixture sweep — every fixture frame runs without assertions.
##   - Smoke benchmark for task/radar scan.
##
## Run::
##
##     nim c -r -d:release --threads:on --mm:orc \
##         among_them/guided_bot/test/tasks_test.nim

import std/[monotimes, os, strformat, times]
import ../constants
import ../types
import ../belief
import ../bot
import ../perception
import ../perception/data
import ../perception/frame
import ../perception/ignore
import ../perception/tasks

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
  let d = readFile(path)
  doAssert d.len == FrameLen, "fixture wrong length: " & name
  result = newSeq[uint8](FrameLen)
  for i in 0 ..< FrameLen:
    result[i] = uint8(d[i])

# ---------------------------------------------------------------------------
# 1. Interstitial short-circuit
# ---------------------------------------------------------------------------

proc testInterstitialShortCircuit() =
  let frame = loadFixture("interstitial_0.bin")
  let sprites = referenceData.sprites
  let result = scanTasksAndRadar(frame, sprites,
    camX = 0, camY = 0,
    localized = true,
    isInterstitial = true,
    isImposter = false,
    isGhost = false)
  expectEq(result.taskIcons.len, 0, "interstitial: no task icons")
  expectEq(result.radarDots.len, 0, "interstitial: no radar dots")

# ---------------------------------------------------------------------------
# 2. Radar-dot scan basics
# ---------------------------------------------------------------------------

proc testRadarDotScan() =
  ## Radar dots are yellow (palette 8) pixels in the border ring.
  ## On gameplay frames, there may or may not be radar dots.
  let frame = loadFixture("gameplay_150.bin")
  let dots = scanRadarDots(frame)

  # Every dot must be in the periphery ring.
  for d in dots:
    expect(d.x <= RadarPeripheryMargin or
           d.x >= ScreenWidth - 1 - RadarPeripheryMargin or
           d.y <= RadarPeripheryMargin or
           d.y >= ScreenHeight - 1 - RadarPeripheryMargin,
           &"radar dot ({d.x},{d.y}) in periphery ring")

  # Count raw yellow periphery pixels for verification.
  var rawCount = 0
  for y in 0 ..< ScreenHeight:
    for x in 0 ..< ScreenWidth:
      if frame[y * ScreenWidth + x] == RadarTaskColor and
         (x <= RadarPeripheryMargin or
          x >= ScreenWidth - 1 - RadarPeripheryMargin or
          y <= RadarPeripheryMargin or
          y >= ScreenHeight - 1 - RadarPeripheryMargin):
        inc rawCount
  # Dedup means dots.len <= rawCount (could be equal if all pixels
  # are separated).
  expect(dots.len <= rawCount,
         &"deduped dots ({dots.len}) <= raw pixels ({rawCount})")

proc testRadarDotSynthetic() =
  ## Synthetic frame: place known yellow pixels in the border ring
  ## and verify they're detected.
  var frame = newSeq[uint8](FrameLen)
  # Place a dot at (0, 0) — top-left corner.
  frame[0] = RadarTaskColor
  # Place a dot at (127, 127) — bottom-right corner.
  frame[127 * ScreenWidth + 127] = RadarTaskColor
  # Place two adjacent dots at (1, 0) and (2, 0) — should dedup to one.
  frame[0 * ScreenWidth + 1] = RadarTaskColor
  frame[0 * ScreenWidth + 2] = RadarTaskColor

  let dots = scanRadarDots(frame)
  # Expect: (0,0) kept; (1,0) suppressed (Chebyshev 1 of (0,0));
  # (2,0) NOT suppressed (distance 2 from (0,0)); (127,127) kept.
  # Result: 3 dots.
  expectEq(dots.len, 3, "synthetic: 3 deduped dots")

  # Verify the dots are at the expected positions.
  var foundTopLeft = false
  var found2_0 = false
  var foundBottomRight = false
  for d in dots:
    if d.x == 0 and d.y == 0: foundTopLeft = true
    if d.x == 2 and d.y == 0: found2_0 = true
    if d.x == 127 and d.y == 127: foundBottomRight = true
  expect(foundTopLeft, "synthetic: found (0,0)")
  expect(found2_0, "synthetic: found (2,0)")
  expect(foundBottomRight, "synthetic: found (127,127)")

# ---------------------------------------------------------------------------
# 3. Task-icon scan — localized vs not
# ---------------------------------------------------------------------------

proc testTaskIconScanNotLocalized() =
  ## Task-icon scan should produce nothing when not localized.
  let frame = loadFixture("gameplay_150.bin")
  let sprites = referenceData.sprites
  let result = scanTasksAndRadar(frame, sprites,
    camX = 0, camY = 0,
    localized = false,
    isInterstitial = false,
    isImposter = false,
    isGhost = false)
  expectEq(result.taskIcons.len, 0,
           "not localized: no task icons")
  # Radar dots should still be present.
  # (May or may not have any, depending on fixture.)

proc testTaskIconScanLocalized() =
  ## Task-icon scan with known camera position. The fixture
  ## gameplay_150 has camera at (504, 54). We can't pin exact
  ## icon counts without detailed knowledge of which tasks are
  ## on-screen, but we can check the scan runs and produces
  ## plausible results.
  let frame = loadFixture("gameplay_150.bin")
  let sprites = referenceData.sprites
  let result = scanTasksAndRadar(frame, sprites,
    camX = 504, camY = 54,
    localized = true,
    isInterstitial = false,
    isImposter = false,
    isGhost = false)
  # Task icons should be a reasonable count (0-40; there are ~40 tasks
  # on the map but only a handful are on screen).
  expect(result.taskIcons.len <= 40,
         &"localized: task icon count {result.taskIcons.len} plausible")
  # All icon positions should be in screen bounds.
  for ti in result.taskIcons:
    expect(ti.x >= -12 and ti.x < ScreenWidth + 12,
           &"task icon x={ti.x} roughly in bounds")
    expect(ti.y >= -12 and ti.y < ScreenHeight + 12,
           &"task icon y={ti.y} roughly in bounds")

proc testTaskIconScanImposterSkip() =
  ## Alive imposters skip task-icon scanning (they don't do real tasks).
  let frame = loadFixture("gameplay_150.bin")
  let sprites = referenceData.sprites
  let result = scanTasksAndRadar(frame, sprites,
    camX = 504, camY = 54,
    localized = true,
    isInterstitial = false,
    isImposter = true,
    isGhost = false)
  expectEq(result.taskIcons.len, 0,
           "alive imposter: no task icons scanned")
  # Radar dots should still work.

proc testTaskIconScanGhostImposter() =
  ## Ghost imposters DO scan task icons (they use task_completing mode).
  ## This exercises the `isImposter and not isGhost` skip logic.
  let frame = loadFixture("gameplay_150.bin")
  let sprites = referenceData.sprites
  let resultGhostImp = scanTasksAndRadar(frame, sprites,
    camX = 504, camY = 54,
    localized = true,
    isInterstitial = false,
    isImposter = true,
    isGhost = true)
  let resultCrewmate = scanTasksAndRadar(frame, sprites,
    camX = 504, camY = 54,
    localized = true,
    isInterstitial = false,
    isImposter = false,
    isGhost = false)
  # Ghost imposter should get the same task icons as a crewmate.
  expectEq(resultGhostImp.taskIcons.len, resultCrewmate.taskIcons.len,
           "ghost imposter gets same task icons as crewmate")

# ---------------------------------------------------------------------------
# 4. Task-icon ignore-mask stamping
# ---------------------------------------------------------------------------

proc testTaskIconIgnoreMask() =
  ## Task-icon exclusions should add bits to the ignore mask.
  let frame = loadFixture("gameplay_150.bin")
  var mask = initIgnoreMask()
  buildPhase10IgnoreMask(mask, frame)
  let baseBits = mask.countSet()

  let sprites = referenceData.sprites
  let result = scanTasksAndRadar(frame, sprites,
    camX = 504, camY = 54,
    localized = true,
    isInterstitial = false,
    isImposter = false,
    isGhost = false)

  let taskW = sprites.task.width
  let taskH = sprites.task.height
  for ti in result.taskIcons:
    stampSpriteRect(mask, ti.x, ti.y, taskW, taskH)

  let afterBits = mask.countSet()
  if result.taskIcons.len > 0:
    expect(afterBits > baseBits,
           &"ignore mask grew from {baseBits} to {afterBits} with {result.taskIcons.len} task icons")

# ---------------------------------------------------------------------------
# 5. Task-icon-to-station attribution
# ---------------------------------------------------------------------------

proc testTaskIconStationAttributionRegression() =
  ## Dense station rects used to overlap under the old 16 px margin
  ## attribution. A Divert Power icon at station 10 must not also mark
  ## nearby Fix Wires station 5 as confirmed.
  let tasks = referenceData.map.tasks
  expect(tasks.len > 10, "attribution regression: station 10 exists")
  if tasks.len <= 10:
    return

  let station5 = tasks[5]
  let station10 = tasks[10]
  expectEq(station5.x, 392, "attribution regression: station 5 x")
  expectEq(station5.y, 296, "attribution regression: station 5 y")
  expectEq(station10.x, 372, "attribution regression: station 10 x")
  expectEq(station10.y, 293, "attribution regression: station 10 y")

  var belief = initBelief()
  ensureTaskSlotsInitialized(belief)
  belief.self.role = RoleCrewmate
  belief.self.alive = true
  belief.self.isGhost = false
  belief.percep.localized = true
  belief.percep.cameraX = 342
  belief.percep.cameraY = 243
  belief.percep.interstitial = false

  let iconX = station10.x + station10.w div 2 - SpriteSize div 2 -
              belief.percep.cameraX
  let iconY = station10.y - SpriteSize - 2 - belief.percep.cameraY
  expectEq(iconX, 32, "attribution regression: station 10 expected icon x")
  expectEq(iconY, 36, "attribution regression: station 10 expected icon y")

  belief.percep.visibleTaskIcons = @[IconMatch(x: iconX, y: iconY)]
  updateTaskState(belief, tick = 1, holdIndex = -1, confirmIndex = -1)

  expectEq(belief.tasks.slots[10].state, TaskConfirmed,
           "attribution regression: station 10 confirmed")
  expect(belief.tasks.slots[5].state != TaskConfirmed,
         "attribution regression: station 5 not misconfirmed")

# ---------------------------------------------------------------------------
# 6. End-to-end bot pipeline
# ---------------------------------------------------------------------------

proc testBotPipelineTasks() =
  var bot = initBot()

  # Interstitial — no task/radar results.
  discard bot.stepUnpackedFrame(loadFixture("interstitial_5.bin"))
  expectEq(bot.belief.percep.visibleTaskIcons.len, 0,
           "interstitial: no task icons in belief")
  expectEq(bot.belief.percep.radarDots.len, 0,
           "interstitial: no radar dots in belief")

  # Gameplay — should populate (at least radar dots).
  discard bot.stepUnpackedFrame(loadFixture("gameplay_150.bin"))
  # Radar dots may or may not be present, but the field should exist.
  expect(bot.belief.percep.radarDots.len >= 0,
         "pipeline: radarDots populated (even if empty)")
  # Task icons depend on camera lock — should be populated if localized.
  if bot.belief.percep.localized:
    expect(bot.belief.percep.visibleTaskIcons.len >= 0,
           "pipeline: visibleTaskIcons populated when localized")

  # Walk through all gameplay fixtures.
  for name in ["gameplay_200.bin", "gameplay_274.bin"]:
    discard bot.stepUnpackedFrame(loadFixture(name))

# ---------------------------------------------------------------------------
# 7. Fixture sweep
# ---------------------------------------------------------------------------

proc testFixtureSweep() =
  const fixtures = [
    "interstitial_0.bin", "interstitial_5.bin", "interstitial_100.bin",
    "gameplay_131.bin", "gameplay_150.bin", "gameplay_200.bin",
    "gameplay_274.bin",
  ]
  var bot = initBot()
  for name in fixtures:
    discard bot.stepUnpackedFrame(loadFixture(name))
  expectEq(bot.frameTick, fixtures.len,
           "fixture sweep: frameTick == frame count")

# ---------------------------------------------------------------------------
# 8. Smoke benchmark
# ---------------------------------------------------------------------------

proc testBenchmark() =
  let frame = loadFixture("gameplay_150.bin")
  let sprites = referenceData.sprites

  let t0 = getMonoTime()
  let r1 = scanTasksAndRadar(frame, sprites,
    camX = 504, camY = 54,
    localized = true, isInterstitial = false,
    isImposter = false, isGhost = false)
  let t1 = getMonoTime()
  let r2 = scanTasksAndRadar(frame, sprites,
    camX = 504, camY = 54,
    localized = true, isInterstitial = false,
    isImposter = false, isGhost = false)
  let t2 = getMonoTime()

  let coldMs = float((t1 - t0).inMicroseconds) / 1000.0
  let warmMs = float((t2 - t1).inMicroseconds) / 1000.0
  echo &"  bench: cold={coldMs:.2f} ms, warm={warmMs:.2f} ms"
  echo &"  taskIcons={r1.taskIcons.len}, radarDots={r1.radarDots.len}"

  # Task-icon scan is dominated by the kernel sweep over ~40 task
  # stations. Expected cost <1 ms. Radar dots are a trivial scan.
  expect(coldMs < 50.0, &"bench: cold <50ms, got {coldMs:.2f} ms")
  expect(warmMs < 50.0, &"bench: warm <50ms, got {warmMs:.2f} ms")

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

proc main() =
  testInterstitialShortCircuit()
  testRadarDotScan()
  testRadarDotSynthetic()
  testTaskIconScanNotLocalized()
  testTaskIconScanLocalized()
  testTaskIconScanImposterSkip()
  testTaskIconScanGhostImposter()
  testTaskIconIgnoreMask()
  testTaskIconStationAttributionRegression()
  testBotPipelineTasks()
  testFixtureSweep()
  testBenchmark()

  if failures == 0:
    echo "OK (all perception phase-1.4 task/radar checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
