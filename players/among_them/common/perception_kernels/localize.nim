## Camera-scoring and patch-hashing kernels for localization.
##
## Exported symbols (Phase 2):
##
## - ``mb_score_camera`` — count matches / errors for one camera
##   offset against the frame, with early-exit on miss budget.
##   Equivalent to :func:`modulabot.localize.score_camera` / the Nim
##   upstream ``scoreCamera``.
## - ``mb_hash_frame_patches`` — compute the 16×16 grid of frame
##   8×8-patch hashes, plus a validity mask (invalid iff any ignored
##   pixel falls in the patch). Equivalent to the Nim upstream
##   ``framePatchHash`` plus Python's ``_hash_frame_patches``.
##
## Constants and semantics must stay bit-identical to the Python
## implementations — any drift and the 275-frame fixture-parity test
## in ``tests/test_nim_perception.py`` catches it.

import sprite_match  # for ShadowMap, ScreenWidth/Height, PaletteMask
import std/algorithm

const
  MapVoidColor* = 12'u8
    ## Matches :data:`modulabot.data.MAP_VOID_COLOR`. Used to fill
    ## off-map pixels during ``score_camera``.

  PatchSize* = 8
    ## Width/height of one hash patch. Must match
    ## :data:`modulabot.localize.PATCH_SIZE` — do not change.
  PatchGridW* = sprite_match.ScreenWidth div PatchSize   # 16
  PatchGridH* = sprite_match.ScreenHeight div PatchSize  # 16

  PatchHashBase* = 16777619'u64
  PatchHashSeed* = 14695981039346656037'u64

# ---------------------------------------------------------------------------
# Camera scoring
# ---------------------------------------------------------------------------
#
# score = compared - errors * ScreenWidth  (matching Python and Nim
# upstream ordering). Early-exit once ``errors`` exceeds the budget —
# the scalar Nim version does this and it makes bad candidates almost
# free to reject (a few pixels instead of 16k).
#
# Output is returned via three int32 out-pointers because C doesn't
# have a sane tuple return and Python-side ctypes reads into a 3-slot
# int32 buffer. That keeps the caller cost to one allocation.

proc mb_score_camera*(
    frame: ptr UncheckedArray[uint8],     # (128*128,) uint8 row-major
    map_pixels: ptr UncheckedArray[uint8], # (map_h*map_w,) uint8 row-major
    map_w: cint,
    map_h: cint,
    ignore_mask: ptr UncheckedArray[uint8], # (128*128,) 0/1, may be nil
    cx: cint,
    cy: cint,
    max_errors: cint,
    out_score: cint,     # 1 if score should be computed, 0 to only
                         # populate errors/compared (used when caller
                         # wants a raw count without the Python-side
                         # ordering formula).
    out_errors: ptr cint,
    out_compared: ptr cint,
    out_score_val: ptr cint,
) {.exportc, dynlib.} =
  ## Score one camera offset. Writes ``errors``, ``compared``, and
  ## (if ``out_score != 0``) the Python-ordering score via the three
  ## out-pointers.
  ##
  ## Errors are incremented for every non-ignored frame pixel that
  ## matches neither the map's exact colour nor its shadow-map variant
  ## at camera offset ``(cx, cy)``. Off-map pixels use
  ## :data:`MapVoidColor`.
  ##
  ## **No early-exit.** We deliberately count every non-ignored pixel
  ## even when errors exceed ``max_errors``. That matches
  ## :func:`modulabot.localize._score_camera_numpy`'s behaviour —
  ## the Python ``_score_better`` helper needs the full error count to
  ## rank over-budget candidates deterministically. Early-exit would
  ## save ~10–20 µs in the worst case, but would diverge subtly from
  ## the numpy path and break the fixture-parity snapshot tests.
  ##
  ## Output score ordering mirrors Python:
  ## - ``errors > max_errors`` → ``score = -errors``
  ## - otherwise → ``score = compared - errors * ScreenWidth``
  var
    errors: int32 = 0
    compared: int32 = 0
  let sw = int(sprite_match.ScreenWidth)
  let sh = int(sprite_match.ScreenHeight)
  let mw = int(map_w)
  let mh = int(map_h)
  let useIgnore = not ignore_mask.isNil

  for sy in 0 ..< sh:
    let my = cy + cint(sy)
    let rowOff = sy * sw
    let mapRow = int(my) * mw
    let inRowY = my >= 0 and my < cint(mh)
    for sx in 0 ..< sw:
      let idx = rowOff + sx
      if useIgnore and ignore_mask[idx] != 0'u8:
        continue
      inc compared
      let mx = cx + cint(sx)
      var mapColor: uint8
      if inRowY and mx >= 0 and mx < cint(mw):
        mapColor = map_pixels[mapRow + int(mx)]
      else:
        mapColor = MapVoidColor
      let frameColor = frame[idx]
      if frameColor == mapColor:
        continue
      if sprite_match.ShadowMap[mapColor and sprite_match.PaletteMask] == frameColor:
        continue
      inc errors

  out_errors[] = errors
  out_compared[] = compared
  if out_score != 0:
    if errors > int32(max_errors):
      out_score_val[] = -errors
    else:
      out_score_val[] = compared - errors * int32(sw)

# ---------------------------------------------------------------------------
# Frame patch hashing
# ---------------------------------------------------------------------------

proc mb_hash_frame_patches*(
    frame: ptr UncheckedArray[uint8],      # (128*128,)
    ignore_mask: ptr UncheckedArray[uint8], # (128*128,) 0/1
    out_hashes: ptr UncheckedArray[uint64], # (16*16,)
    out_valid: ptr UncheckedArray[uint8],   # (16*16,) 0/1
) {.exportc, dynlib.} =
  ## Compute the 16×16 grid of per-patch hashes.
  ##
  ## Each patch is 8×8 frame pixels. A patch containing any ignored
  ## pixel is marked invalid (``out_valid[p] = 0``); its hash value is
  ## still written but callers skip it. Valid patches get
  ## ``out_valid[p] = 1`` and the same FNV-like hash the Nim upstream
  ## uses.
  ##
  ## Hash formula per patch pixel:
  ##   ``h = h * PatchHashBase + (colour and 0x0F) + 1``
  ## seeded with ``PatchHashSeed``. Integer overflow is defined for
  ## ``uint64`` in both Nim and Python (we cast to ``np.uint64``).
  let sw = int(sprite_match.ScreenWidth)

  for py in 0 ..< PatchGridH:
    for px in 0 ..< PatchGridW:
      var h: uint64 = PatchHashSeed
      var anyIgnored: uint8 = 0
      let ay = py * PatchSize
      let ax = px * PatchSize
      for oy in 0 ..< PatchSize:
        let rowOff = (ay + oy) * sw
        for ox in 0 ..< PatchSize:
          let idx = rowOff + ax + ox
          if ignore_mask[idx] != 0'u8:
            anyIgnored = 1
          let c = frame[idx] and sprite_match.PaletteMask
          h = h * PatchHashBase + uint64(c) + 1'u64
      let p = py * PatchGridW + px
      out_hashes[p] = h
      out_valid[p] = 1'u8 - anyIgnored

# ---------------------------------------------------------------------------
# mb_vote_camera_candidates
# ---------------------------------------------------------------------------
#
# Bulk Phase 2.5 kernel. Replaces the Python 256-patch loop in
# :func:`modulabot.localize.Localizer._locate_by_patches`, which was
# the actual cold-path bottleneck (FFI single-call overhead erased
# Phase 2's per-call score_camera speedup, but this loop dominates
# cold localize at ~2 ms and is pure interpreter work).
#
# API shape: takes the pre-built patch-index arrays + the frame's
# already-hashed patches, computes the vote accumulator, returns the
# top K ``(cx, cy, votes)`` candidates. Scoring + walk-mask
# predicate still happen in Python (at most K=16 score_camera calls).
#
# Deterministic tie-breaking matches Python's ``np.lexsort((cxs, cys,
# -votes))`` — higher votes first, then lower cy, then lower cx.

proc bsearchLeft(arr: ptr UncheckedArray[uint64], n: int, key: uint64): int =
  ## ``numpy.searchsorted(..., side='left')`` — returns the insertion
  ## point for ``key`` such that all elements before it are strictly
  ## less than ``key``.
  var lo = 0
  var hi = n
  while lo < hi:
    let mid = (lo + hi) shr 1
    if arr[mid] < key: lo = mid + 1
    else: hi = mid
  return lo

proc bsearchRight(arr: ptr UncheckedArray[uint64], n: int, key: uint64): int =
  ## ``numpy.searchsorted(..., side='right')``.
  var lo = 0
  var hi = n
  while lo < hi:
    let mid = (lo + hi) shr 1
    if arr[mid] <= key: lo = mid + 1
    else: hi = mid
  return lo

proc mb_vote_camera_candidates*(
    # Frame patches (pre-hashed; use ``mb_hash_frame_patches``).
    frame_hashes: ptr UncheckedArray[uint64],  # (PatchGridH*PatchGridW,)
    frame_valid: ptr UncheckedArray[uint8],    # (PatchGridH*PatchGridW,) 0/1
    # Pre-built patch index (sorted by hash).
    index_hashes: ptr UncheckedArray[uint64],  # (N,)
    index_cam_xs: ptr UncheckedArray[int32],   # (N,)
    index_cam_ys: ptr UncheckedArray[int32],   # (N,)
    index_len: cint,
    # Camera range (world coordinates).
    min_cx: cint,
    max_cx: cint,
    min_cy: cint,
    max_cy: cint,
    # Vote-accumulator scratch (size = cam_w*cam_h; caller-allocated
    # so we don't malloc per call).
    vote_buf: ptr UncheckedArray[uint16],
    vote_buf_len: cint,
    # Output: top K candidates. ``(cx, cy, votes)`` triples written
    # into ``out_cxs[i]`` / ``out_cys[i]`` / ``out_votes[i]``.
    top_k: cint,
    min_votes: cint,
    max_matches_per_patch: cint,
    out_cxs: ptr UncheckedArray[int32],
    out_cys: ptr UncheckedArray[int32],
    out_votes: ptr UncheckedArray[int32],
    out_count: ptr cint,
) {.exportc, dynlib.} =
  ## Bulk patch-vote kernel. One call replaces the Python
  ## ``_locate_by_patches`` inner loop (256 patches × per-patch
  ## searchsorted + vote + numpy ops).
  ##
  ## Semantics match the Python implementation byte-for-byte:
  ##
  ## - Each valid frame patch casts one vote per matching map
  ##   patch offset, clipped to the camera range.
  ## - Patches whose map-index match count exceeds
  ##   ``max_matches_per_patch`` are skipped (ambiguous patches
  ##   like pure-floor tiles).
  ## - Top-K candidates returned in descending vote order, ties
  ##   broken by ascending ``(cy, cx)`` to match numpy's
  ##   ``np.lexsort``.
  ## - ``vote_buf`` is zeroed on entry and re-zeroed on exit (the
  ##   caller passes a persistent buffer to avoid malloc
  ##   churn). Any indices outside the camera range are
  ##   implicitly skipped via the clip step.
  let camW = int(max_cx) - int(min_cx) + 1
  let camH = int(max_cy) - int(min_cy) + 1
  if camW <= 0 or camH <= 0 or vote_buf_len < int32(camW * camH):
    out_count[] = 0
    return

  # Zero touched entries tracker: record indices we touched so we can
  # reset cheaply at the end. Allocate on the stack as a dynamic seq;
  # size bounded by sum of match ranges.
  var touched: seq[int32] = @[]

  let totalPatches = PatchGridH * PatchGridW
  let indexN = int(index_len)

  for pIdx in 0 ..< totalPatches:
    if frame_valid[pIdx] == 0'u8:
      continue
    let h = frame_hashes[pIdx]
    let first = bsearchLeft(index_hashes, indexN, h)
    let last = bsearchRight(index_hashes, indexN, h)
    let count = last - first
    if count <= 0 or count > int(max_matches_per_patch):
      continue
    let py = pIdx div PatchGridW
    let px = pIdx mod PatchGridW
    let dx = int32(px * PatchSize)
    let dy = int32(py * PatchSize)
    for k in first ..< last:
      let cx = index_cam_xs[k] - dx
      let cy = index_cam_ys[k] - dy
      if cx < min_cx or cx > max_cx or cy < min_cy or cy > max_cy:
        continue
      let flatIdx = int32(int(cy - min_cy) * camW + int(cx - min_cx))
      if vote_buf[flatIdx] == 0'u16:
        touched.add(flatIdx)
      inc vote_buf[flatIdx]

  # Collect touched indices that clear the min-votes floor, then
  # select top K. Using an O(N log N) sort; touched.len is typically
  # small (hundreds to low thousands).
  type Candidate = object
    cx, cy: int32
    votes: int32

  var kept: seq[Candidate] = @[]
  for t in touched:
    let v = int32(vote_buf[t])
    if v >= int32(min_votes):
      let cx = int32(int(t) mod camW) + min_cx
      let cy = int32(int(t) div camW) + min_cy
      kept.add(Candidate(cx: cx, cy: cy, votes: v))

  # Reset the touched vote slots back to zero so the caller can reuse
  # the buffer on the next call without sweeping all of it.
  for t in touched:
    vote_buf[t] = 0'u16

  # Sort by (-votes, cy, cx) to match numpy lexsort((cxs, cys, -votes)).
  proc cmpCandidate(a, b: Candidate): int =
    if a.votes != b.votes: return int(b.votes) - int(a.votes)  # desc
    if a.cy != b.cy: return int(a.cy) - int(b.cy)              # asc
    return int(a.cx) - int(b.cx)                               # asc

  kept.sort(cmpCandidate)

  let k = min(int(top_k), kept.len)
  for i in 0 ..< k:
    out_cxs[i] = kept[i].cx
    out_cys[i] = kept[i].cy
    out_votes[i] = kept[i].votes
  out_count[] = cint(k)
