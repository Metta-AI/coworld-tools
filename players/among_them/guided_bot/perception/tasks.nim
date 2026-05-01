## Task-icon and radar-dot scanning. Phase 1.4.
##
## Two independent scans:
##
## 1. **Task-icon scan** — wraps ``mb_scan_task_icons`` from
##    ``among_them/common/perception_kernels/actors.nim``. For each task
##    station on the map, probes a neighbourhood around the expected icon
##    position (world→screen via camera offset) for the task-icon sprite.
##    Produces a list of ``IconMatch`` screen-anchor hits. Only runs when
##    ``localized`` is true (camera offset is known).
##
## 2. **Radar-dot scan** — pure Nim. Collects palette-index-8 (yellow)
##    pixels in the 2-pixel-wide border ring of the 128×128 frame, deduped
##    with Chebyshev-1 grouping. Produces a list of ``RadarDotMatch``
##    screen positions. Always runs (radar dots are HUD-layer, independent
##    of camera).
##
## Both scans produce raw perception output. The higher-level task-state
## machine (icon→task assignment, checkout latching, icon-miss pruning)
## is policy-layer logic deferred to phase 2.
##
## Kernel sharing: same pattern as phases 1.2 and 1.3 — ``from
## "../../common/perception_kernels/actors" as kActors import nil`` for
## qualified-only access to ``mb_scan_task_icons``.

import std/algorithm

import ../constants
import ../types
import data
import frame
import ignore  # For RadarTaskColor

# Import the shared task-icon kernel.
from "../../common/perception_kernels/actors" as kActors import nil

# ---------------------------------------------------------------------------
# Constants — pinned to modulabot/actors.py
# ---------------------------------------------------------------------------

const
  ## Search radius around the expected icon position. Matches
  ## ``modulabot.actors.TASK_ICON_EXPECTED_SEARCH_RADIUS``.
  TaskIconSearchRadius* = 3

  ## Maximum output matches from a single ``scanTaskIcons`` call.
  ## Generous cap; a typical frame has <5 visible task icons.
  TaskIconMaxMatches* = 64

  ## Pixel margin defining the screen-edge periphery ring where radar
  ## dots appear. Matches ``modulabot.actors.RADAR_PERIPHERY_MARGIN``.
  RadarPeripheryMargin* = 1

# ---------------------------------------------------------------------------
# Task-icon scan — wraps mb_scan_task_icons
# ---------------------------------------------------------------------------

type
  TaskCoordCache* = object
    ## Flat-packed ``(x, y, w, h)`` int32 quads for every task station
    ## on the map, built once and reused. Mirrors modulabot's
    ## ``_task_coords_for`` caching.
    coords*: seq[int32]
    numTasks*: int

proc buildTaskCoordCache*(map: GameMap): TaskCoordCache =
  ## Build the flat packed task-coord array from the map metadata.
  let n = map.tasks.len
  var coords = newSeq[int32](n * 4)
  for i in 0 ..< n:
    let t = map.tasks[i]
    coords[i * 4 + 0] = int32(t.x)
    coords[i * 4 + 1] = int32(t.y)
    coords[i * 4 + 2] = int32(t.w)
    coords[i * 4 + 3] = int32(t.h)
  TaskCoordCache(coords: coords, numTasks: n)

# Module-level cache: built lazily.
var taskCoordCacheBuilt: bool = false
var taskCoordCacheValue: TaskCoordCache

proc getTaskCoordCache*(): lent TaskCoordCache =
  if not taskCoordCacheBuilt:
    taskCoordCacheValue = buildTaskCoordCache(referenceData.map)
    taskCoordCacheBuilt = true
  taskCoordCacheValue

proc scanTaskIcons*(
    frame: openArray[uint8],
    sprite: Sprite,
    camX, camY: int): seq[IconMatch] =
  ## Scan for task-icon sprites at every task station's expected screen
  ## position. Returns a list of ``IconMatch`` screen-anchor hits.
  ##
  ## Delegates to ``mb_scan_task_icons`` which sweeps a
  ## ``3-bob x (2r+1)^2`` neighbourhood around each station's expected
  ## anchor and deduplicates within Chebyshev distance 1.
  ##
  ## Off-screen stations are rejected cheaply by the kernel (the strict
  ## sprite match early-exits on OOB pixels).
  let cache = getTaskCoordCache()
  if cache.numTasks == 0:
    return @[]

  var outXs: array[TaskIconMaxMatches, int32]
  var outYs: array[TaskIconMaxMatches, int32]
  var outCount: cint = 0

  kActors.mb_scan_task_icons(
    cast[ptr UncheckedArray[uint8]](unsafeAddr frame[0]),
    cast[ptr UncheckedArray[uint8]](unsafeAddr sprite.pixels[0]),
    cint(sprite.height),
    cint(sprite.width),
    cast[ptr UncheckedArray[int32]](unsafeAddr cache.coords[0]),
    cint(cache.numTasks),
    cint(camX),
    cint(camY),
    cint(TaskIconSearchRadius),
    cint(TaskIconMaxMatches),
    cast[ptr UncheckedArray[int32]](addr outXs[0]),
    cast[ptr UncheckedArray[int32]](addr outYs[0]),
    addr outCount)

  let n = int(outCount)
  result = newSeq[IconMatch](n)
  for i in 0 ..< n:
    result[i] = IconMatch(x: int(outXs[i]), y: int(outYs[i]))

# ---------------------------------------------------------------------------
# Radar-dot scan — pure Nim
# ---------------------------------------------------------------------------

proc isPeriphery(x, y: int): bool {.inline.} =
  ## True if ``(x, y)`` is in the screen-edge periphery ring where
  ## radar dots appear. The ring is ``RadarPeripheryMargin + 1`` pixels
  ## wide on each edge. Matches modulabot's mask construction.
  x <= RadarPeripheryMargin or
  y <= RadarPeripheryMargin or
  x >= ScreenWidth - 1 - RadarPeripheryMargin or
  y >= ScreenHeight - 1 - RadarPeripheryMargin

proc scanRadarDots*(frame: openArray[uint8]): seq[RadarDotMatch] =
  ## Collect deduped yellow pixels in the screen-edge periphery ring.
  ## Mirrors ``modulabot/actors.py::scan_radar_dots``.
  ##
  ## Algorithm:
  ## 1. Scan every pixel; keep those that are palette index 8 (yellow)
  ##    AND lie in the periphery ring.
  ## 2. Sort by raster order ``(y, x)``.
  ## 3. Greedy dedup: suppress any dot within Chebyshev distance 1 of
  ##    an already-kept dot.
  doAssert frame.len == FrameLen,
    "scanRadarDots: frame.len " & $frame.len & " != FrameLen"

  # Collect raw hits.
  type RawDot = tuple[y, x: int]
  var raw: seq[RawDot] = @[]
  for y in 0 ..< ScreenHeight:
    for x in 0 ..< ScreenWidth:
      if frame[y * ScreenWidth + x] == RadarTaskColor and isPeriphery(x, y):
        raw.add (y: y, x: x)

  # Already in raster order (row-major iteration), but sort to be safe.
  sort(raw, proc(a, b: RawDot): int =
    if a.y != b.y: a.y - b.y else: a.x - b.x)

  # Greedy dedup — same as actors.nim's dedup pattern.
  var kept: seq[RadarDotMatch] = @[]
  for d in raw:
    var dup = false
    for k in kept:
      if abs(d.y - k.y) <= 1 and abs(d.x - k.x) <= 1:
        dup = true
        break
    if not dup:
      kept.add RadarDotMatch(x: d.x, y: d.y)
  kept

# ---------------------------------------------------------------------------
# Output record (sub-percept for task/radar scans)
# ---------------------------------------------------------------------------

type
  TaskPercept* = object
    ## Structured output of one task/radar scan pass. Populated by
    ## ``scanTasksAndRadar`` and consumed by the belief-merge stage.
    taskIcons*: seq[IconMatch]
    radarDots*: seq[RadarDotMatch]

proc initTaskPercept*(): TaskPercept =
  TaskPercept(taskIcons: @[], radarDots: @[])

# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

proc scanTasksAndRadar*(
    frame: openArray[uint8],
    sprites: Sprites,
    camX, camY: int,
    localized: bool,
    isInterstitial: bool,
    isImposter: bool,
    isGhost: bool): TaskPercept =
  ## Run task-icon + radar-dot scans for one frame.
  ##
  ## - Short-circuits on interstitials.
  ## - Task-icon scan only runs when localized (needs camera offset).
  ## - Task-icon scan skips for alive imposters (they don't do real
  ##   tasks; matches modulabot's ``scan_all`` gating).
  ## - Radar-dot scan always runs on gameplay frames.
  result = initTaskPercept()

  if isInterstitial:
    return

  # Radar dots — always run (HUD layer, camera-independent).
  result.radarDots = scanRadarDots(frame)

  # Task icons — needs camera + skip for alive imposters.
  if localized and not (isImposter and not isGhost):
    result.taskIcons = scanTaskIcons(frame, sprites.task, camX, camY)
