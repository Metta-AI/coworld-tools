## Per-frame radar-ray exclusion tests.
##
## Coverage:
##   - ``rayIntersectsIconAABB`` slab geometry for hits, misses, edges,
##     vertical rays, behind-origin rays, and degenerate rays.
##   - Missing pip rays mark off-screen tasks excluded for this frame.
##   - A later hitting pip clears exclusion immediately on the next frame.
##   - On-screen tasks and zero-pip frames are never ray-excluded.
##   - Checkout latching is gated by the per-frame ray test off-screen.
##   - On-screen checkout still latches when a matching dot is present.
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
  ## Build a task station whose icon centre is at ``(iconX, iconY)``.
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

proc iconTopLeft(station: TaskStation, camX, camY: int): IconMatch =
  IconMatch(
    x: station.x + station.w div 2 - SpriteSize div 2 - camX,
    y: station.y - SpriteSize - 2 - camY)

proc projectedDot(station: TaskStation, belief: Belief): RadarDotMatch =
  let (projX, projY) = projectedRadarDot(station,
                                         belief.percep.cameraX,
                                         belief.percep.cameraY,
                                         belief.percep.selfX,
                                         belief.percep.selfY)
  RadarDotMatch(x: projX, y: projY)

proc rayHits(station: TaskStation, belief: Belief,
             dot: RadarDotMatch): bool =
  let playerSx = belief.percep.selfX - belief.percep.cameraX
  let playerSy = belief.percep.selfY - belief.percep.cameraY
  rayIntersectsIconAABB(belief.percep.selfX,
                        belief.percep.selfY,
                        dot.x - playerSx,
                        dot.y - playerSy,
                        station,
                        RadarRayIconPadding)

proc missDotForRay(station: TaskStation,
                   belief: Belief): RadarDotMatch =
  const candidates = [
    (0, 0), (ScreenWidth - 1, ScreenHeight - 1),
    (0, ScreenHeight - 1), (ScreenWidth - 1, 0),
    (ScreenWidth div 2, 0), (ScreenWidth div 2, ScreenHeight - 1),
    (0, ScreenHeight div 2), (ScreenWidth - 1, ScreenHeight div 2)
  ]
  for candidate in candidates:
    let dot = RadarDotMatch(x: candidate[0], y: candidate[1])
    if not rayHits(station, belief, dot):
      return dot
  RadarDotMatch(x: 0, y: 0)

proc matchedButMissingRayCase(): (int, RadarDotMatch) =
  ## Find a real off-screen station where a dot within checkout
  ## tolerance still misses the padded icon AABB. This captures the
  ## false-latch case the ray gate is meant to prevent.
  let camX = 0
  let camY = 0
  var belief = setupBelief(camX, camY)
  for i, station in referenceData.map.tasks:
    if taskIconOnScreen(station, camX, camY, 0):
      continue
    let base = projectedDot(station, belief)
    for dx in -RadarMatchTolerance .. RadarMatchTolerance:
      for dy in -RadarMatchTolerance .. RadarMatchTolerance:
        let dot = RadarDotMatch(x: base.x + dx, y: base.y + dy)
        if dot.x < 0 or dot.x >= ScreenWidth or
           dot.y < 0 or dot.y >= ScreenHeight:
          continue
        if abs(dot.x - base.x) <= RadarMatchTolerance and
           abs(dot.y - base.y) <= RadarMatchTolerance and
           not rayHits(station, belief, dot):
          return (i, dot)
  (-1, RadarDotMatch(x: 0, y: 0))

proc onScreenCameraFor(station: TaskStation): (int, int) =
  (station.x + station.w div 2 - SpriteSize div 2 - 50,
   station.y - SpriteSize - 2 - 50)

# ---------------------------------------------------------------------------
# 1. Ray-AABB intersection
# ---------------------------------------------------------------------------

proc testRayIntersectsIconAABB() =
  let east = syntheticStationForIcon(100, 0)
  expect(rayIntersectsIconAABB(0, 0, 1, 0, east, RadarRayIconPadding),
         "ray AABB: horizontal hit")
  expect(not rayIntersectsIconAABB(0, 0, 100, 20, east, RadarRayIconPadding),
         "ray AABB: horizontal miss")
  expect(not rayIntersectsIconAABB(120, 0, 1, 0, east, RadarRayIconPadding),
         "ray AABB: box behind origin")
  expect(not rayIntersectsIconAABB(0, 0, 0, 0, east, RadarRayIconPadding),
         "ray AABB: degenerate ray")

  let north = syntheticStationForIcon(50, 20)
  expect(rayIntersectsIconAABB(50, 100, 0, -1, north, RadarRayIconPadding),
         "ray AABB: vertical hit")
  expect(not rayIntersectsIconAABB(0, 100, 0, -1, north, RadarRayIconPadding),
         "ray AABB: vertical ray outside x slab")

  let edge = syntheticStationForIcon(100, RadarRayIconPadding)
  expect(rayIntersectsIconAABB(0, 0, 1, 0, edge, RadarRayIconPadding),
         "ray AABB: tangent edge hit")

# ---------------------------------------------------------------------------
# 2. Per-frame exclusion
# ---------------------------------------------------------------------------

proc testPerFrameExclusionClearsImmediately() =
  let camX = 0
  let camY = 0
  let taskIdx = findOffScreenTask(camX, camY)
  expect(taskIdx >= 0, "per-frame: found off-screen task")
  if taskIdx < 0:
    return

  var belief = setupBelief(camX, camY)
  let station = referenceData.map.tasks[taskIdx]
  belief.percep.radarDots = @[missDotForRay(station, belief)]
  updateTaskState(belief, 1, holdIndex = -1, confirmIndex = -1)
  expect(belief.tasks.slots[taskIdx].radarRayExcluded,
         "per-frame: miss ray excludes this frame")

  belief.percep.radarDots = @[projectedDot(station, belief)]
  updateTaskState(belief, 2, holdIndex = -1, confirmIndex = -1)
  expect(not belief.tasks.slots[taskIdx].radarRayExcluded,
         "per-frame: hitting ray clears next frame")

proc testOnScreenTaskNotExcluded() =
  let taskIdx = 0
  let station = referenceData.map.tasks[taskIdx]
  let (camX, camY) = onScreenCameraFor(station)
  var belief = setupBelief(camX, camY)
  belief.percep.visibleTaskIcons = @[iconTopLeft(station, camX, camY)]
  belief.percep.radarDots = @[missDotForRay(station, belief)]

  updateTaskState(belief, 1, holdIndex = -1, confirmIndex = -1)
  expect(not belief.tasks.slots[taskIdx].radarRayExcluded,
         "on-screen: task not ray-excluded")

proc testZeroPipsSkipExclusion() =
  var belief = setupBelief(camX = 0, camY = 0)
  belief.percep.radarDots = @[]

  updateTaskState(belief, 1, holdIndex = -1, confirmIndex = -1)
  for i, slot in belief.tasks.slots:
    expect(not slot.radarRayExcluded,
           &"zero pips: task {i} not ray-excluded")

# ---------------------------------------------------------------------------
# 3. Checkout gating
# ---------------------------------------------------------------------------

proc testCheckoutGatedByRayExclusion() =
  let (taskIdx, dot) = matchedButMissingRayCase()
  expect(taskIdx >= 0, "checkout gate: found matched miss-ray case")
  if taskIdx < 0:
    return

  var belief = setupBelief(camX = 0, camY = 0)
  belief.percep.radarDots = @[dot]
  updateTaskState(belief, 1, holdIndex = -1, confirmIndex = -1)

  expect(belief.tasks.slots[taskIdx].radarRayExcluded,
         "checkout gate: off-screen task ray-excluded")
  expect(not belief.tasks.slots[taskIdx].checkout,
         "checkout gate: checkout did not latch")
  expectEq(belief.tasks.slots[taskIdx].state, TaskNotDoing,
           "checkout gate: state remains not-doing")

proc testOnScreenCheckoutStillLatches() =
  let taskIdx = 0
  let station = referenceData.map.tasks[taskIdx]
  let (camX, camY) = onScreenCameraFor(station)
  var belief = setupBelief(camX, camY)
  belief.percep.visibleTaskIcons = @[iconTopLeft(station, camX, camY)]
  belief.percep.radarDots = @[projectedDot(station, belief)]

  updateTaskState(belief, 1, holdIndex = -1, confirmIndex = -1)

  expect(not belief.tasks.slots[taskIdx].radarRayExcluded,
         "on-screen checkout: not ray-excluded")
  expect(belief.tasks.slots[taskIdx].checkout,
         "on-screen checkout: checkout latched")
  expectEq(belief.tasks.slots[taskIdx].state, TaskConfirmed,
           "on-screen checkout: icon remains hard signal")

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

proc main() =
  testRayIntersectsIconAABB()
  testPerFrameExclusionClearsImmediately()
  testOnScreenTaskNotExcluded()
  testZeroPipsSkipExclusion()
  testCheckoutGatedByRayExclusion()
  testOnScreenCheckoutStillLatches()

  if failures == 0:
    echo "OK (all per-frame radar-ray exclusion checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
