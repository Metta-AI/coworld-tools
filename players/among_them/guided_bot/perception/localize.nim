## Camera localization. Phase 1.2.
##
## Port of ``modulabot/localize.py``'s orchestration. Reuses the Nim
## perception kernels in ``among_them/common/perception_kernels/`` via
## direct relative imports — see DESIGN.md §15 "Sharing nim_perception"
## and ``among_them/common/README.md``. The kernels are pure Nim,
## stateless, and parity-pinned in modulabot's test suite; if a kernel
## signature drifts, our own tests fail at compile time or trip a
## parity check.
##
## Strategy mirrors the upstream ``updateLocation``:
##
## 1. **Local refit** — ``mb_score_camera`` over a small window around
##    the previous camera. Cheap; usually finds a zero-error fit in
##    one step on a stationary bot.
## 2. **Patch-hash global search** — hash 8×8 frame patches via
##    ``mb_hash_frame_patches``, look each up in a pre-built
##    map-patch index, vote for camera offsets via
##    ``mb_vote_camera_candidates``, score the top candidates with the
##    full 128×128 fit. Invoked when local refit fails.
## 3. **Spiral fallback** — last resort. Spirals outward from the best
##    seed (previous lock or the button if we've never locked).
##
## State model (PerceptionState fields owned by this module):
##
## - ``cameraX`` / ``cameraY`` / ``cameraScore`` / ``cameraLock``
##   /``localized`` / ``lastLocalizedTick`` — the current lock.
## - ``lastCameraX`` / ``lastCameraY`` — the previous frame's camera,
##   so the local refit starts from the right seed.
## - ``homeX`` / ``homeY`` / ``homeSet`` — remembered button-area
##   camera for post-interstitial reseeds.
## - ``gameStarted`` — false during the very first frames; forces the
##   global search to start from the button rather than trusting
##   stale state.
##
## ``selfX`` / ``selfY`` are the inferred player world position
## ``cameraX + PlayerWorldOffX`` etc., recomputed on every accepted
## lock.
##
## The patch index is built once (lazily, on the first non-interstitial
## frame) and cached at module level. Cost: ~0.5 s of scalar Nim work
## over the padded ~600×1100 map. Subsequent localize calls reuse the
## index.

import std/[algorithm]

import ../constants
import ../types
import data
import geometry

# ``mb_score_camera``, ``mb_hash_frame_patches``,
# ``mb_vote_camera_candidates`` live in the shared kernel directory
# ``among_them/common/perception_kernels/``. ``from path import nil``
# imports the module without leaking any identifiers into our
# namespace — the kernels define their own ``ScreenWidth`` /
# ``MapVoidColor`` constants that would collide with ours otherwise.
# We refer to kernel symbols only via the qualified names
# ``kSpriteMatch.X`` / ``kLocalize.X``.
from "../../common/perception_kernels/sprite_match" as kSpriteMatch import nil
from "../../common/perception_kernels/localize" as kLocalize import nil

# ---------------------------------------------------------------------------
# Constants — pinned to modulabot/localize.py
# ---------------------------------------------------------------------------

const
  ## Max per-frame mismatches the global search will accept on a lock.
  FullFrameFitMaxErrors* = 420
  ## Max per-frame mismatches the cheap local refit will accept.
  LocalFrameFitMaxErrors* = 320
  ## Minimum non-ignored opaque pixels for a score to be trusted.
  ## Guards against degenerate "everything is ignored" frames.
  FrameFitMinCompared* = 12000
  ## Local refit search half-extent (square window of 17×17).
  LocalFrameSearchRadius* = 8

  ## Patch-hash size. Must match ``kLocalize.PatchSize`` (=8) and the
  ## upstream Python constant. Hardcoded to 8 here as a sanity pin.
  PatchSize* = 8
  PatchGridW* = ScreenWidth div PatchSize    # 16
  PatchGridH* = ScreenHeight div PatchSize   # 16
  PatchTotalCount* = PatchGridW * PatchGridH # 256

  ## FNV-style hash constants. Mirror ``kLocalize.PatchHashBase`` and
  ## ``PatchHashSeed``; pinned again here so we can build the index
  ## without an extra import surface.
  PatchHashBase*: uint64 = 16777619'u64
  PatchHashSeed*: uint64 = 14695981039346656037'u64

  ## Skip frame patches whose hash matches more than this many map
  ## entries — too ambiguous (large featureless regions like floor
  ## tiles) to contribute useful votes.
  PatchMaxMatches* = 4096
  ## Keep this many top-voted candidates for full-frame scoring.
  PatchTopCandidates* = 16
  ## Minimum patch votes for a camera offset to be considered.
  PatchMinVotes* = 3

# Static asserts: kernel-side constants must agree with ours.
static:
  doAssert kLocalize.PatchSize == PatchSize,
    "localize: PatchSize differs between guided_bot and modulabot kernel"
  doAssert kLocalize.PatchGridW == PatchGridW
  doAssert kLocalize.PatchGridH == PatchGridH
  doAssert kLocalize.PatchHashBase == PatchHashBase
  doAssert kLocalize.PatchHashSeed == PatchHashSeed
  doAssert kSpriteMatch.ScreenWidth == ScreenWidth
  doAssert kSpriteMatch.ScreenHeight == ScreenHeight

# ---------------------------------------------------------------------------
# Camera score record — same shape as modulabot's ``CameraScore``
# ---------------------------------------------------------------------------

type
  CameraScore* = object
    score*: int     ## ``compared - errors * ScreenWidth`` (or ``-errors``
                    ## when over budget). Higher is better.
    errors*: int
    compared*: int

const
  NoScore* = CameraScore(
    score: -(1 shl 30),
    errors: (1 shl 30),
    compared: 0)

# ---------------------------------------------------------------------------
# Patch index — a sorted (hash → camera-offset) lookup over the map
# ---------------------------------------------------------------------------

type
  PatchIndex* = object
    ## Sorted-by-hash global index over every valid 8×8 anchor in the
    ## map. ``cam_xs`` and ``cam_ys`` are the upper-left of the 8×8
    ## window (anchor coords, **not** the player-centred camera the
    ## localizer ultimately reports). The lookup math in
    ## ``mb_vote_camera_candidates`` translates anchor → camera by
    ## subtracting the patch offset.
    hashes*: seq[uint64]   ## (N,), sorted ascending
    camXs*: seq[int32]     ## (N,), co-sorted
    camYs*: seq[int32]     ## (N,), co-sorted
    width*: int            ## anchor-grid width  (cameraWidth) - 1 + …
    height*: int

# Module-level cache: built lazily on first localize call. Cost is
# borne once per process. Module init does not allocate this — we
# don't want every smoke-test or no-op build to pay 0.5 s of patch
# hashing.
var patchIndexCache: PatchIndex
var patchIndexBuilt: bool = false

proc buildPatchIndex(map: GameMap): PatchIndex =
  ## Compute patch hashes for every valid camera-anchor offset on the
  ## map. Equivalent to ``modulabot/localize.py::_build_patch_index``,
  ## except scalar (the upstream Python is vectorised numpy over the
  ## padded map; here we iterate the 64 in-patch pixels and the full
  ## anchor grid in plain Nim — runs once at startup so no need to
  ## vectorise).
  ##
  ## The anchor grid covers
  ## ``[minCameraX, maxCameraX + ScreenWidth - PatchSize]`` in X (and
  ## Y), matching ``buildPatchEntries`` in modulabot's localize.nim.
  ## Anchors near the map edge fold in :data:`MapVoidColor` for the
  ## off-map pixels so frame patches near the screen edge can still
  ## match during global search.
  let minX = minCameraX()
  let maxX = maxCameraX() + ScreenWidth - PatchSize
  let minY = minCameraY()
  let maxY = maxCameraY() + ScreenHeight - PatchSize

  let width = maxX - minX + 1
  let height = maxY - minY + 1
  let count = width * height

  var hashes = newSeq[uint64](count)
  var camXs = newSeq[int32](count)
  var camYs = newSeq[int32](count)

  # Per-pixel reads with a void-fill fallback. Inlined in the inner
  # loop below; the explicit ``mapPixel`` proc here is the lookup we'd
  # use otherwise.
  let mapPx = map.mapPixels
  template mapPixel(x, y: int): uint8 =
    if x >= 0 and x < MapWidth and y >= 0 and y < MapHeight:
      mapPx[y * MapWidth + x]
    else:
      MapVoidColor

  var idx = 0
  for ay in minY .. maxY:
    for ax in minX .. maxX:
      var h: uint64 = PatchHashSeed
      for oy in 0 ..< PatchSize:
        let my = ay + oy
        for ox in 0 ..< PatchSize:
          let mx = ax + ox
          let c = mapPixel(mx, my) and 0x0F'u8
          h = h * PatchHashBase + uint64(c) + 1'u64
      hashes[idx] = h
      camXs[idx] = int32(ax)
      camYs[idx] = int32(ay)
      inc idx

  # Sort by hash ascending so ``mb_vote_camera_candidates`` can
  # binary-search. Co-sort camera coordinates with stable indirect
  # sort: build an index permutation, then materialise.
  var perm = newSeq[int32](count)
  for i in 0 ..< count:
    perm[i] = int32(i)
  sort(perm, proc(a, b: int32): int =
    let ha = hashes[a]
    let hb = hashes[b]
    if ha < hb: -1 elif ha > hb: 1 else: 0)
  var sortedHashes = newSeq[uint64](count)
  var sortedXs = newSeq[int32](count)
  var sortedYs = newSeq[int32](count)
  for i in 0 ..< count:
    let p = int(perm[i])
    sortedHashes[i] = hashes[p]
    sortedXs[i] = camXs[p]
    sortedYs[i] = camYs[p]

  PatchIndex(
    hashes: sortedHashes,
    camXs: sortedXs,
    camYs: sortedYs,
    width: width,
    height: height)

proc getPatchIndex*(): lent PatchIndex =
  ## Return the cached patch index, building it on first use against
  ## the static :data:`referenceData.map`. One map per process so the
  ## cache is effectively permanent.
  if not patchIndexBuilt:
    patchIndexCache = buildPatchIndex(referenceData.map)
    patchIndexBuilt = true
  patchIndexCache

# ---------------------------------------------------------------------------
# Kernel call wrappers
# ---------------------------------------------------------------------------

proc scoreCamera*(
    frame: openArray[uint8],
    mapPixels: openArray[uint8],
    ignoreMask: openArray[uint8],
    cx, cy: int,
    maxErrors: int = FullFrameFitMaxErrors): CameraScore =
  ## Score one camera offset. Thin wrapper over
  ## ``kLocalize.mb_score_camera``. Always computes the
  ## Python-ordering ``score`` (``out_score=1``) so the caller can
  ## rank candidates without re-deriving the formula.
  doAssert frame.len == FrameLen,
    "scoreCamera: frame.len " & $frame.len & " != FrameLen"
  doAssert mapPixels.len == MapWidth * MapHeight,
    "scoreCamera: mapPixels.len wrong"
  doAssert ignoreMask.len == FrameLen,
    "scoreCamera: ignoreMask.len " & $ignoreMask.len & " != FrameLen"

  var errs: int32 = 0
  var compared: int32 = 0
  var scoreVal: int32 = 0
  kLocalize.mb_score_camera(
    cast[ptr UncheckedArray[uint8]](unsafeAddr frame[0]),
    cast[ptr UncheckedArray[uint8]](unsafeAddr mapPixels[0]),
    cint(MapWidth), cint(MapHeight),
    cast[ptr UncheckedArray[uint8]](unsafeAddr ignoreMask[0]),
    cint(cx), cint(cy),
    cint(maxErrors),
    cint(1),
    addr errs, addr compared, addr scoreVal)
  CameraScore(
    score: int(scoreVal),
    errors: int(errs),
    compared: int(compared))

proc hashFramePatches*(
    frame: openArray[uint8],
    ignoreMask: openArray[uint8]): tuple[
      hashes: array[PatchTotalCount, uint64],
      valid: array[PatchTotalCount, uint8]] =
  ## Compute the 16×16 grid of frame patch hashes plus per-patch
  ## validity. Wrapper over ``kLocalize.mb_hash_frame_patches``.
  doAssert frame.len == FrameLen,
    "hashFramePatches: frame.len " & $frame.len & " != FrameLen"
  doAssert ignoreMask.len == FrameLen,
    "hashFramePatches: ignoreMask.len " & $ignoreMask.len & " != FrameLen"
  kLocalize.mb_hash_frame_patches(
    cast[ptr UncheckedArray[uint8]](unsafeAddr frame[0]),
    cast[ptr UncheckedArray[uint8]](unsafeAddr ignoreMask[0]),
    cast[ptr UncheckedArray[uint64]](addr result.hashes[0]),
    cast[ptr UncheckedArray[uint8]](addr result.valid[0]))

proc voteCameraCandidates*(
    frameHashes: array[PatchTotalCount, uint64],
    frameValid: array[PatchTotalCount, uint8],
    index: PatchIndex,
    voteBuf: var seq[uint16]): seq[tuple[cx, cy, votes: int]] =
  ## Bulk patch-vote kernel. Wrapper over
  ## ``kLocalize.mb_vote_camera_candidates``. Returns the top
  ## :data:`PatchTopCandidates` ``(cx, cy, votes)`` triples in
  ## descending vote order with ties broken by ascending ``(cy, cx)``.
  ##
  ## ``voteBuf`` is the persistent vote-accumulator scratch array;
  ## the kernel zeroes only the slots it touches, so a caller-owned
  ## buffer avoids per-call malloc churn. Resized to
  ## ``cameraWidth() * cameraHeight()`` if smaller.
  let camW = cameraWidth()
  let camH = cameraHeight()
  let needed = camW * camH
  if voteBuf.len < needed:
    voteBuf.setLen(needed)

  var outCxs: array[PatchTopCandidates, int32]
  var outCys: array[PatchTopCandidates, int32]
  var outVotes: array[PatchTopCandidates, int32]
  var outCount: cint = 0

  kLocalize.mb_vote_camera_candidates(
    cast[ptr UncheckedArray[uint64]](unsafeAddr frameHashes[0]),
    cast[ptr UncheckedArray[uint8]](unsafeAddr frameValid[0]),
    cast[ptr UncheckedArray[uint64]](unsafeAddr index.hashes[0]),
    cast[ptr UncheckedArray[int32]](unsafeAddr index.camXs[0]),
    cast[ptr UncheckedArray[int32]](unsafeAddr index.camYs[0]),
    cint(index.hashes.len),
    cint(minCameraX()), cint(maxCameraX()),
    cint(minCameraY()), cint(maxCameraY()),
    cast[ptr UncheckedArray[uint16]](addr voteBuf[0]),
    cint(needed),
    cint(PatchTopCandidates),
    cint(PatchMinVotes),
    cint(PatchMaxMatches),
    cast[ptr UncheckedArray[int32]](addr outCxs[0]),
    cast[ptr UncheckedArray[int32]](addr outCys[0]),
    cast[ptr UncheckedArray[int32]](addr outVotes[0]),
    addr outCount)

  let n = int(outCount)
  result = newSeq[tuple[cx, cy, votes: int]](n)
  for i in 0 ..< n:
    result[i] = (cx: int(outCxs[i]), cy: int(outCys[i]), votes: int(outVotes[i]))

# ---------------------------------------------------------------------------
# Score acceptance / comparison helpers
# ---------------------------------------------------------------------------

proc acceptCameraScore(score: CameraScore, maxErrors: int): bool {.inline.} =
  score.errors <= maxErrors and score.compared >= FrameFitMinCompared

proc scoreBetter(newSc, bestSc: CameraScore): bool {.inline.} =
  ## Nim-side ordering: fewer errors first, then more compared. Mirrors
  ## ``modulabot/localize.py::_score_better``.
  if newSc.errors != bestSc.errors:
    return newSc.errors < bestSc.errors
  newSc.compared > bestSc.compared

# ---------------------------------------------------------------------------
# Localizer — stateful front-end
# ---------------------------------------------------------------------------

type
  Localizer* = object
    ## One :class:`Localizer` per :class:`Bot`. Holds a reference to
    ## the shared module-level patch index plus per-bot scratch state
    ## (vote buffer, touched list — both consumed by the kernel and
    ## otherwise transparent to callers).
    votes*: seq[uint16]   ## Persistent vote-accumulator scratch.

proc initLocalizer*(): Localizer =
  ## Cheap. Lazy-allocates the patch index on first ``updateLocation``.
  Localizer(votes: @[])

# ---------------------------------------------------------------------------
# Locator strategies
# ---------------------------------------------------------------------------

proc acceptLock(
    perception: var PerceptionState,
    cx, cy: int,
    score: CameraScore,
    lock: CameraLock,
    tick: int) =
  perception.cameraX = cx
  perception.cameraY = cy
  perception.cameraScore = score.score
  perception.cameraLock = lock
  perception.localized = true
  perception.gameStarted = true
  perception.lastLocalizedTick = tick
  perception.selfX = playerWorldX(cx)
  perception.selfY = playerWorldY(cy)
  if not perception.homeSet:
    perception.homeX = perception.selfX
    perception.homeY = perception.selfY
    perception.homeSet = true

proc locateNearFrame(
    self: var Localizer,
    perception: var PerceptionState,
    frame, mapPixels, ignoreMask: openArray[uint8],
    tick: int): bool =
  ## Cheap local refit within :data:`LocalFrameSearchRadius` of the
  ## previous lock. Two-tier: try the seed first, sweep the
  ## neighbourhood only if the seed misses.
  let seedX = perception.cameraX
  let seedY = perception.cameraY
  let seedScore = scoreCamera(
    frame, mapPixels, ignoreMask, seedX, seedY, LocalFrameFitMaxErrors)
  if acceptCameraScore(seedScore, LocalFrameFitMaxErrors):
    acceptLock(perception, seedX, seedY, seedScore, LocalFrameMapLock, tick)
    return true

  var best = seedScore
  var bestX = seedX
  var bestY = seedY
  let loX = max(minCameraX(), seedX - LocalFrameSearchRadius)
  let hiX = min(maxCameraX(), seedX + LocalFrameSearchRadius)
  let loY = max(minCameraY(), seedY - LocalFrameSearchRadius)
  let hiY = min(maxCameraY(), seedY + LocalFrameSearchRadius)

  for y in loY .. hiY:
    for x in loX .. hiX:
      if x == seedX and y == seedY:
        continue
      let sc = scoreCamera(
        frame, mapPixels, ignoreMask, x, y, LocalFrameFitMaxErrors)
      if scoreBetter(sc, best):
        best = sc
        bestX = x
        bestY = y
        if sc.errors == 0 and sc.compared >= FrameFitMinCompared:
          acceptLock(perception, bestX, bestY, best, LocalFrameMapLock, tick)
          return true

  if not acceptCameraScore(best, LocalFrameFitMaxErrors):
    return false
  acceptLock(perception, bestX, bestY, best, LocalFrameMapLock, tick)
  true

proc locateByPatches(
    self: var Localizer,
    perception: var PerceptionState,
    frame, mapPixels, ignoreMask: openArray[uint8],
    tick: int): bool =
  ## Patch-hash vote + full-frame rescore of the top candidates.
  let (frameHashes, valid) = hashFramePatches(frame, ignoreMask)
  let candidates = voteCameraCandidates(
    frameHashes, valid, getPatchIndex(), self.votes)
  if candidates.len == 0:
    return false

  var best = NoScore
  var bestX = perception.cameraX
  var bestY = perception.cameraY
  for cand in candidates:
    if not cameraCanHoldPlayer(cand.cx, cand.cy):
      continue
    let sc = scoreCamera(
      frame, mapPixels, ignoreMask, cand.cx, cand.cy, FullFrameFitMaxErrors)
    if scoreBetter(sc, best):
      best = sc
      bestX = cand.cx
      bestY = cand.cy

  if not acceptCameraScore(best, FullFrameFitMaxErrors):
    return false
  acceptLock(perception, bestX, bestY, best, FrameMapLock, tick)
  true

proc locateBySpiral(
    self: var Localizer,
    perception: var PerceptionState,
    frame, mapPixels, ignoreMask: openArray[uint8],
    tick: int): bool =
  ## Last-resort spiral scan around the best available seed.
  ## Mirrors ``modulabot/localize.py::Localizer._locate_by_spiral``.
  ##
  ## Implementation note: we use a ``template`` for the per-cell
  ## "score and bookkeep" step instead of a nested closure because
  ## ``frame`` (and friends) are ``openArray[uint8]`` parameters,
  ## which Nim refuses to capture in a closure for memory-safety
  ## reasons. The template inlines the body at each call site so the
  ## openArrays stay on the spiral-iteration stack frame.
  var seedX =
    if perception.gameStarted: perception.cameraX
    else: buttonCameraX(referenceData.map)
  var seedY =
    if perception.gameStarted: perception.cameraY
    else: buttonCameraY(referenceData.map)
  let loX = minCameraX()
  let hiX = maxCameraX()
  let loY = minCameraY()
  let hiY = maxCameraY()
  seedX = max(loX, min(hiX, seedX))
  seedY = max(loY, min(hiY, seedY))
  let maxRadius = max(
    max(abs(seedX - loX), abs(seedX - hiX)),
    max(abs(seedY - loY), abs(seedY - hiY)))

  var best = NoScore
  var bestX = seedX
  var bestY = seedY
  var done = false

  template tryCamera(x, y: int): bool =
    block tryCameraBlock:
      var hit = false
      if x >= loX and x <= hiX and y >= loY and y <= hiY and
         cameraCanHoldPlayer(x, y):
        let sc = scoreCamera(
          frame, mapPixels, ignoreMask, x, y, FullFrameFitMaxErrors)
        if scoreBetter(sc, best):
          best = sc
          bestX = x
          bestY = y
          if sc.errors == 0 and sc.compared >= FrameFitMinCompared:
            hit = true
      hit

  if tryCamera(seedX, seedY):
    discard
  else:
    for radius in 1 .. maxRadius:
      if done: break
      # Top + bottom rows of the ring.
      for dx in -radius .. radius:
        if tryCamera(seedX + dx, seedY - radius): done = true; break
        if done: break
        if tryCamera(seedX + dx, seedY + radius): done = true; break
      if done: break
      # Left + right columns (excluding already-visited corners).
      for dy in -radius + 1 .. radius - 1:
        if tryCamera(seedX - radius, seedY + dy): done = true; break
        if done: break
        if tryCamera(seedX + radius, seedY + dy): done = true; break

  if not acceptCameraScore(best, FullFrameFitMaxErrors):
    perception.cameraLock = NoLock
    perception.cameraScore = best.score
    perception.localized = false
    return false
  acceptLock(perception, bestX, bestY, best, FrameMapLock, tick)
  true

proc locateByFrame(
    self: var Localizer,
    perception: var PerceptionState,
    frame, mapPixels, ignoreMask: openArray[uint8],
    tick: int): bool =
  ## Global search: patches first, spiral fallback.
  if locateByPatches(self, perception, frame, mapPixels, ignoreMask, tick):
    return true
  locateBySpiral(self, perception, frame, mapPixels, ignoreMask, tick)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

proc updateLocation*(
    self: var Localizer,
    perception: var PerceptionState,
    frame, ignoreMask: openArray[uint8],
    tick: int) =
  ## Localize the camera against ``frame`` and update ``perception``.
  ##
  ## Caller is responsible for having gated out interstitials before
  ## calling — running a localize pass on a black voting screen wastes
  ## ~5 ms and produces garbage. The pipeline in
  ## ``among_them/guided_bot/bot.nim`` enforces this by checking
  ## ``percept.interstitial.isInterstitial`` before invoking us.
  ##
  ## Caller is also responsible for having populated the ignore mask.
  ## Phase 1.0 supplies only the always-on player-centre + radar zone
  ## (see :mod:`perception/ignore`); phase 1.3+ stamps additional
  ## per-actor / per-task / HUD-icon exclusions.
  ##
  ## On success, sets ``localized=true`` and populates ``cameraX/Y``,
  ## ``cameraScore``, ``cameraLock``, ``selfX/Y``, ``lastLocalizedTick``.
  ## On failure, leaves the camera fields at their previous values
  ## with ``localized=false``; callers should treat them as stale.
  perception.lastCameraX = perception.cameraX
  perception.lastCameraY = perception.cameraY

  let mapPixels = referenceData.map.mapPixels

  if perception.localized:
    if locateNearFrame(self, perception, frame, mapPixels, ignoreMask, tick):
      return
  discard locateByFrame(
    self, perception, frame, mapPixels, ignoreMask, tick)

proc reseedCameraAtHome*(
    self: var Localizer,
    perception: var PerceptionState) =
  ## Reset the camera to home (or the button) with no active lock.
  ## Called after interstitials when we want the next localization
  ## pass to start from a known-good seed instead of stale state.
  ## Mirrors ``modulabot/localize.py::Localizer.reseed_camera_at_home``.
  if perception.homeSet:
    perception.cameraX = cameraXForWorld(perception.homeX)
    perception.cameraY = cameraYForWorld(perception.homeY)
  else:
    perception.cameraX = buttonCameraX(referenceData.map)
    perception.cameraY = buttonCameraY(referenceData.map)
  perception.lastCameraX = perception.cameraX
  perception.lastCameraY = perception.cameraY
  perception.cameraLock = NoLock
  perception.cameraScore = 0
  perception.localized = false
