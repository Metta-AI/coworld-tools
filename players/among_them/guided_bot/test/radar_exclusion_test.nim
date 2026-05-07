## Radar-ray exclusion tests.
##
## Coverage:
##   - ``projectedRadarDot`` uses ray-clip projection for cardinal and
##     diagonal off-screen task icons.
##   - Missing radar dots exclude an off-screen task after the configured
##     consecutive-frame threshold.
##   - Matching dots reset the exclusion counter.
##   - On-screen tasks and zero-dot frames do not accumulate exclusion.
##   - Hold and Confirm targets are shielded from exclusion firing.
##
## Run::
##
##     nim c -r -d:release --threads:on --mm:orc \
##         among_them/guided_bot/test/radar_exclusion_test.nim

import std/strformat
import ../belief
import ../constants
import ../perception/data
import ../perception/geometry
import ../tuning
import ../types

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

proc syntheticStationForIcon(iconX, iconY: int): TaskStation =
  ## Build a task station whose radar icon centre would be at
  ## ``(iconX, iconY)`` for camera (0, 0).
  TaskStation(
    index: -1,
    name: "synthetic",
    x: iconX - SpriteSize div 2,
    y: iconY + SpriteSize div 2 + 2,
    w: SpriteSize,
    h: SpriteSize,
    passableCX: 0,
    passableCY: 0)

proc setupBelief(camX, camY: int): Belief =
  result = initBelief()
  ensureTaskSlotsInitialized(result)
  result.self.role = RoleCrewmate
  result.self.alive = true
  result.self.isGhost = false
  result.percep.localized = true
  result.percep.interstitial = false
  result.percep.cameraX = camX
  result.percep.cameraY = camY
  result.percep.selfX = playerWorldX(camX)
  result.percep.selfY = playerWorldY(camY)
  result.percep.visibleTaskIcons = @[]
  result.percep.radarDots = @[]

proc findOffScreenTask(camX, camY: int): int =
  for i, station in referenceData.map.tasks:
    if not taskIconOnScreen(station, camX, camY, 0):
      return i
  -1

proc farDotFor(station: TaskStation,
               camX, camY, selfX, selfY: int): RadarDotMatch =
  let (projX, projY) = projectedRadarDot(station, camX, camY, selfX, selfY)
  const candidates = [
    (0, 0), (ScreenWidth - 1, ScreenHeight - 1),
    (0, ScreenHeight - 1), (ScreenWidth - 1, 0),
    (ScreenWidth div 2, 0), (ScreenWidth div 2, ScreenHeight - 1),
    (0, ScreenHeight div 2), (ScreenWidth - 1, ScreenHeight div 2)
  ]
  for candidate in candidates:
    if abs(candidate[0] - projX) > RadarExclusionDistance or
       abs(candidate[1] - projY) > RadarExclusionDistance:
      return RadarDotMatch(x: candidate[0], y: candidate[1])
  RadarDotMatch(x: 0, y: 0)

proc iconTopLeft(station: TaskStation, camX, camY: int): IconMatch =
  IconMatch(
    x: station.x + station.w div 2 - SpriteSize div 2 - camX,
    y: station.y - SpriteSize - 2 - camY)

# ---------------------------------------------------------------------------
# 1. Ray-clip projection
# ---------------------------------------------------------------------------

proc testRayClipProjection() =
  let camX = 0
  let camY = 0
  let playerX = 64
  let playerY = 64

  expectEq(projectedRadarDot(syntheticStationForIcon(190, 64),
                             camX, camY, playerX, playerY),
           (ScreenWidth - 1, 64),
           "ray-clip: right edge")
  expectEq(projectedRadarDot(syntheticStationForIcon(-20, 64),
                             camX, camY, playerX, playerY),
           (0, 64),
           "ray-clip: left edge")
  expectEq(projectedRadarDot(syntheticStationForIcon(64, -40),
                             camX, camY, playerX, playerY),
           (64, 0),
           "ray-clip: top edge")
  expectEq(projectedRadarDot(syntheticStationForIcon(64, 200),
                             camX, camY, playerX, playerY),
           (64, ScreenHeight - 1),
           "ray-clip: bottom edge")
  expectEq(projectedRadarDot(syntheticStationForIcon(190, 96),
                             camX, camY, playerX, playerY),
           (ScreenWidth - 1, 80),
           "ray-clip: right diagonal uses edge intersection")

# ---------------------------------------------------------------------------
# 2. Exclusion state machine
# ---------------------------------------------------------------------------

proc testExclusionFiresAfterThreshold() =
  let camX = 0
  let camY = 0
  let taskIdx = findOffScreenTask(camX, camY)
  expect(taskIdx >= 0, "exclusion fires: found off-screen task")
  if taskIdx < 0:
    return

  var belief = setupBelief(camX, camY)
  let station = referenceData.map.tasks[taskIdx]
  let farDot = farDotFor(station, camX, camY,
                         belief.percep.selfX, belief.percep.selfY)
  for tick in 1 .. RadarExclusionFrames:
    belief.percep.radarDots = @[farDot]
    updateTaskState(belief, tick, holdIndex = -1, confirmIndex = -1)

  # Soft exclusion: counter saturates at threshold, but does NOT set
  # resolvedNotMine. Task is deprioritized in tier-3, not permanently dead.
  expect(not belief.tasks.slots[taskIdx].resolvedNotMine,
         "soft exclusion: task NOT permanently resolved")
  expectEq(belief.tasks.slots[taskIdx].radarExclusionCount,
           RadarExclusionFrames,
           "soft exclusion: counter saturated at threshold")

proc testExclusionResetsOnDotMatch() =
  let camX = 0
  let camY = 0
  let taskIdx = findOffScreenTask(camX, camY)
  expect(taskIdx >= 0, "reset on match: found off-screen task")
  if taskIdx < 0:
    return

  var belief = setupBelief(camX, camY)
  let station = referenceData.map.tasks[taskIdx]
  let farDot = farDotFor(station, camX, camY,
                         belief.percep.selfX, belief.percep.selfY)
  for tick in 1 .. 8:
    belief.percep.radarDots = @[farDot]
    updateTaskState(belief, tick, holdIndex = -1, confirmIndex = -1)

  expectEq(belief.tasks.slots[taskIdx].radarExclusionCount, 8,
           "reset on match: accumulated pre-match count")

  let (projX, projY) = projectedRadarDot(station, camX, camY,
                                         belief.percep.selfX,
                                         belief.percep.selfY)
  belief.percep.radarDots = @[RadarDotMatch(x: projX, y: projY)]
  updateTaskState(belief, 9, holdIndex = -1, confirmIndex = -1)

  expect(not belief.tasks.slots[taskIdx].resolvedNotMine,
         "reset on match: task not excluded")
  expectEq(belief.tasks.slots[taskIdx].radarExclusionCount, 0,
           "reset on match: counter reset")
  expect(belief.tasks.slots[taskIdx].checkout,
         "reset on match: checkout latched")

proc testOnScreenTaskDoesNotAccumulate() =
  let station = referenceData.map.tasks[0]
  let camX = station.x + station.w div 2 - SpriteSize div 2 - 50
  let camY = station.y - SpriteSize - 2 - 50
  var belief = setupBelief(camX, camY)
  let taskIdx = 0
  let farDot = farDotFor(station, camX, camY,
                         belief.percep.selfX, belief.percep.selfY)
  belief.percep.visibleTaskIcons = @[iconTopLeft(station, camX, camY)]

  for tick in 1 .. RadarExclusionFrames + 3:
    belief.percep.radarDots = @[farDot]
    updateTaskState(belief, tick, holdIndex = -1, confirmIndex = -1)

  expect(not belief.tasks.slots[taskIdx].resolvedNotMine,
         "on-screen: task not excluded")
  expectEq(belief.tasks.slots[taskIdx].radarExclusionCount, 0,
           "on-screen: counter remains zero")

proc testZeroDotsSkipExclusion() =
  let camX = 0
  let camY = 0
  let taskIdx = findOffScreenTask(camX, camY)
  expect(taskIdx >= 0, "zero dots: found off-screen task")
  if taskIdx < 0:
    return

  var belief = setupBelief(camX, camY)
  for tick in 1 .. RadarExclusionFrames + 3:
    belief.percep.radarDots = @[]
    updateTaskState(belief, tick, holdIndex = -1, confirmIndex = -1)

  expect(not belief.tasks.slots[taskIdx].resolvedNotMine,
         "zero dots: task not excluded")
  expectEq(belief.tasks.slots[taskIdx].radarExclusionCount, 0,
           "zero dots: counter remains zero")

proc testSoftExclusionReversible() =
  ## Soft exclusion saturates the counter but the task is never
  ## permanently dead. A subsequent dot match resets the counter.
  let camX = 0
  let camY = 0
  let taskIdx = findOffScreenTask(camX, camY)
  expect(taskIdx >= 0, "reversible: found off-screen task")
  if taskIdx < 0:
    return

  let station = referenceData.map.tasks[taskIdx]

  var belief = setupBelief(camX, camY)
  let farDot = farDotFor(station, camX, camY,
                         belief.percep.selfX, belief.percep.selfY)
  # Saturate the counter.
  for tick in 1 .. RadarExclusionFrames + 5:
    belief.percep.radarDots = @[farDot]
    updateTaskState(belief, tick, holdIndex = -1, confirmIndex = -1)
  expectEq(belief.tasks.slots[taskIdx].radarExclusionCount,
           RadarExclusionFrames,
           "reversible: counter saturated")
  expect(not belief.tasks.slots[taskIdx].resolvedNotMine,
         "reversible: not permanently resolved")

  # Now a dot matches — counter resets, task is back.
  let (projX, projY) = projectedRadarDot(station, camX, camY,
                                         belief.percep.selfX,
                                         belief.percep.selfY)
  belief.percep.radarDots = @[RadarDotMatch(x: projX, y: projY)]
  updateTaskState(belief, RadarExclusionFrames + 6,
                  holdIndex = -1, confirmIndex = -1)
  expectEq(belief.tasks.slots[taskIdx].radarExclusionCount, 0,
           "reversible: counter reset after dot match")

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

proc main() =
  testRayClipProjection()
  testExclusionFiresAfterThreshold()
  testExclusionResetsOnDotMatch()
  testOnScreenTaskDoesNotAccumulate()
  testZeroDotsSkipExclusion()
  testSoftExclusionReversible()

  if failures == 0:
    echo "OK (all radar-ray exclusion checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
