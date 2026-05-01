## Sprite-matching kernels for the modulabot FFI.
##
## Exported symbols (Phase 1):
##
## - ``mb_match_actor_sprite_all`` — vectorised all-anchors match.
##   Semantics must be identical to
##   :func:`modulabot.sprite_match.matches_actor_sprite` run at every
##   valid anchor, under a caller-supplied miss / stable / tint budget.
## - ``mb_actor_color_index_all`` — per-anchor dominant-tint colour
##   index, matching :func:`modulabot.sprite_match.crewmate_color_index`.
##
## Palette constants are hardcoded here to match
## :mod:`modulabot.data` (``TintColor = 3``, ``ShadeTintColor = 9``,
## ``TransparentIndex = 255``, ``PLAYER_COLORS`` / ``SHADOW_MAP``
## identical to ``sim.nim``'s ``PlayerColors`` / ``ShadowMap``). If
## either side ever rewrites the palette, bump
## :data:`ModulabotPerceptionAbiVersion` in ``../lib.nim`` so the
## Python loader refuses the stale library.
##
## Data ownership: every buffer is caller-allocated. We read ``frame``
## and ``sprite`` as ``ptr UncheckedArray[uint8]`` and write through
## ``out_mask`` / ``out_indices`` in place. No allocation, no captured
## references — safe to call from any thread once the library is
## loaded (the Python GIL serialises the ctypes call anyway).

const
  ScreenWidth* = 128
  ScreenHeight* = 128
  TransparentIndex* = 255'u8
  TintColor* = 3'u8
  ShadeTintColor* = 9'u8
  PlayerColorCount* = 16
  PaletteMask* = 0x0F'u8

# Must match ``modulabot.data.PLAYER_COLORS`` (and ``sim.nim``'s
# ``PlayerColors``). Index into the array is the tracked player-colour
# slot; value is the palette index for that slot's lit tint.
const PlayerColors*: array[PlayerColorCount, uint8] = [
  3'u8, 7, 8, 14, 4, 11, 13, 15, 1, 2, 5, 6, 9, 10, 12, 0
]

# ``data.SHADOW_MAP``. Palette index → shadowed palette index. Exactly
# matches ``sim.nim``'s ``ShadowMap`` array.
const ShadowMap*: array[16, uint8] = [
  0'u8, 12, 9, 5, 5, 0, 5, 5, 5, 12, 9, 9, 0, 12, 12, 9
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

proc isPlayerBodyColor(c: uint8): bool {.inline.} =
  ## True iff ``c`` is a plausible player-body colour (lit tint *or*
  ## its shadowed variant). Mirrors
  ## :func:`modulabot.sprite_match.player_body_color`.
  ##
  ## Implemented as a linear scan rather than a 256-entry LUT because
  ## (a) the set is small (32 colours after dedup), (b) JIT-style
  ## branch prediction on the hot path is fine at this scale, and
  ## (c) a LUT would need to live in a ``let`` block with init, which
  ## is friction we don't need.
  for pc in PlayerColors:
    if c == pc:
      return true
    if c == ShadowMap[pc and PaletteMask]:
      return true
  return false

proc playerColorIndexOf(c: uint8): int {.inline.} =
  ## Return the tracked-player-colour slot for a *lit* (non-shadowed)
  ## palette index, or ``-1``. Matches
  ## :func:`modulabot.sprite_match.player_color_index`.
  for i, pc in PlayerColors:
    if c == pc:
      return i
  return -1

# ---------------------------------------------------------------------------
# mb_match_actor_sprite_all
# ---------------------------------------------------------------------------

proc mb_match_actor_sprite_all*(
    frame: ptr UncheckedArray[uint8],    # (SH*SW,) uint8 row-major
    sprite: ptr UncheckedArray[uint8],   # (sh*sw,) uint8 row-major
    sh: cint,
    sw: cint,
    flip_h: cint,
    max_misses: cint,
    min_stable: cint,
    min_tint: cint,
    out_mask: ptr UncheckedArray[uint8], # (max_y*max_x,) uint8 0/1
) {.exportc, dynlib.} =
  ## Vectorised all-anchors sprite match.
  ##
  ## Writes ``out_mask[ay * max_x + ax] = 1`` when the sprite is an
  ## acceptable match at anchor ``(ax, ay)`` under the budgets,
  ## otherwise ``0``.
  ##
  ## Semantics (per anchor):
  ##
  ## - **Stable** sprite pixels (neither ``TintColor`` nor
  ##   ``ShadeTintColor``, and not ``TransparentIndex``) must match
  ##   the frame colour exactly.
  ## - **Tint** sprite pixels (either ``TintColor`` or
  ##   ``ShadeTintColor``) match any plausible player body colour
  ##   (lit or shadowed).
  ## - Anchor is accepted iff cumulative misses ≤ ``max_misses`` AND
  ##   matched-stable ≥ ``min_stable`` AND matched-tint ≥ ``min_tint``.
  ##
  ## Performance: the outer loop is over anchors (cheap index math),
  ## the inner loop is over sprite pixels (bounded by sh*sw). With
  ## early-out on the miss budget the average anchor cost is far below
  ## the worst case because most anchors reject after a handful of
  ## miss hits.
  let
    maxY = int(ScreenHeight) - int(sh) + 1
    maxX = int(ScreenWidth) - int(sw) + 1
  if maxY <= 0 or maxX <= 0:
    return

  # Pre-count stable/tint *pixels* (not matches); bail early if the
  # sprite simply can't clear the floor because it doesn't have
  # enough of each. Mirrors the Python scalar path's final guard but
  # lets us skip the whole anchor sweep in the degenerate case.
  var totalStable = 0
  var totalTint = 0
  for sy in 0 ..< int(sh):
    for sx in 0 ..< int(sw):
      let c = sprite[sy * int(sw) + sx]
      if c == TransparentIndex: continue
      if c == TintColor or c == ShadeTintColor:
        inc totalTint
      else:
        inc totalStable
  if totalStable < int(min_stable) or totalTint < int(min_tint):
    # Zero the output buffer and return. Not strictly required — the
    # Python caller zeroes before calling — but belt-and-braces.
    for i in 0 ..< maxY * maxX:
      out_mask[i] = 0'u8
    return

  let flip = flip_h != 0

  for ay in 0 ..< maxY:
    for ax in 0 ..< maxX:
      var misses = 0
      var matchedStable = 0
      var matchedTint = 0
      var reject = false
      for sy in 0 ..< int(sh):
        if reject: break
        for sx in 0 ..< int(sw):
          let srcX = if flip: int(sw) - 1 - sx else: sx
          let c = sprite[sy * int(sw) + srcX]
          if c == TransparentIndex: continue
          let fy = ay + sy
          let fx = ax + sx
          # Anchor ranges above guarantee fy / fx in-bounds.
          let fc = frame[fy * int(ScreenWidth) + fx]
          if c == TintColor or c == ShadeTintColor:
            if isPlayerBodyColor(fc):
              inc matchedTint
            else:
              inc misses
          else:
            if fc == c:
              inc matchedStable
            else:
              inc misses
          if misses > int(max_misses):
            reject = true
            break
      if reject or matchedStable < int(min_stable) or matchedTint < int(min_tint):
        out_mask[ay * maxX + ax] = 0'u8
      else:
        out_mask[ay * maxX + ax] = 1'u8

# ---------------------------------------------------------------------------
# mb_actor_color_index_all
# ---------------------------------------------------------------------------

proc mb_actor_color_index_all*(
    frame: ptr UncheckedArray[uint8],
    sprite: ptr UncheckedArray[uint8],
    sh: cint,
    sw: cint,
    flip_h: cint,
    out_indices: ptr UncheckedArray[int8], # (max_y*max_x,) int8
) {.exportc, dynlib.} =
  ## Per-anchor dominant-tint colour index.
  ##
  ## For every anchor ``(ax, ay)``, count how many of the sprite's
  ## ``TintColor`` pixels match each tracked player colour in the
  ## frame (lit tint only — shadowed palette indices do not vote).
  ## Write the argmax index into ``out_indices`` or ``-1`` if no
  ## tint pixel voted.
  ##
  ## Ties are broken by lowest index, matching Python's
  ## ``np.argmax``.
  let
    maxY = int(ScreenHeight) - int(sh) + 1
    maxX = int(ScreenWidth) - int(sw) + 1
  if maxY <= 0 or maxX <= 0:
    return

  let flip = flip_h != 0
  var counts: array[PlayerColorCount, int32]

  for ay in 0 ..< maxY:
    for ax in 0 ..< maxX:
      for i in 0 ..< PlayerColorCount:
        counts[i] = 0
      for sy in 0 ..< int(sh):
        for sx in 0 ..< int(sw):
          let srcX = if flip: int(sw) - 1 - sx else: sx
          let c = sprite[sy * int(sw) + srcX]
          if c != TintColor: continue
          let fy = ay + sy
          let fx = ax + sx
          let fc = frame[fy * int(ScreenWidth) + fx]
          let idx = playerColorIndexOf(fc)
          if idx >= 0:
            inc counts[idx]
      var best = 0
      var bestVotes = counts[0]
      for i in 1 ..< PlayerColorCount:
        if counts[i] > bestVotes:
          bestVotes = counts[i]
          best = i
      if bestVotes > 0:
        out_indices[ay * maxX + ax] = int8(best)
      else:
        out_indices[ay * maxX + ax] = -1'i8
