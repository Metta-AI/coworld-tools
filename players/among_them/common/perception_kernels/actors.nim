## Actor scanners that don't fit in sprite_match.nim.
##
## Currently: the task-icon scan (Phase 3). Radar dots and the
## ignore-mask computation are left in Python because their numpy
## paths are already <1 ms; FFI overhead would erase the gain.
##
## Task-icon scan cost in Python was ~200–400 µs on a typical
## gameplay frame and up to a millisecond when many tasks are on
## screen. Pure Nim scalar loops bring that under 50 µs.

import sprite_match  # ScreenWidth, ScreenHeight, TransparentIndex, PaletteMask, ShadowMap

const
  TaskIconMaxMisses* = 4
    ## Strict match budget. Matches
    ## :data:`modulabot.sprite_match.TASK_ICON_MAX_MISSES`.
  SpriteSize* = 12
    ## Every reference sprite is 12×12. Matches
    ## :data:`modulabot.data.SPRITE_SIZE`.

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

proc spriteMatchStrict(
    frame: ptr UncheckedArray[uint8],
    sprite: ptr UncheckedArray[uint8],
    sh, sw: int,
    x, y: int,
): bool {.inline.} =
  ## Scalar strict match used for task icons (no tint, no flip).
  ## Matches :func:`modulabot.sprite_match.matches_sprite`.
  ##
  ## Early-exits once misses exceed :data:`TaskIconMaxMisses` so
  ## off-position candidates reject in <10 pixels instead of scanning
  ## the whole 144-pixel sprite.
  var
    misses = 0
    opaque = 0
  for sy in 0 ..< sh:
    for sx in 0 ..< sw:
      let c = sprite[sy * sw + sx]
      if c == sprite_match.TransparentIndex: continue
      inc opaque
      let fx = x + sx
      let fy = y + sy
      if fx < 0 or fy < 0 or
         fx >= int(sprite_match.ScreenWidth) or
         fy >= int(sprite_match.ScreenHeight):
        inc misses
      elif frame[fy * int(sprite_match.ScreenWidth) + fx] != c:
        inc misses
      if misses > TaskIconMaxMisses:
        return false
  return opaque > 0 and misses <= TaskIconMaxMisses

proc addMatchDedup(
    out_xs: ptr UncheckedArray[int32],
    out_ys: ptr UncheckedArray[int32],
    count: var int32,
    max_count: int32,
    x, y: int32,
): bool {.inline.} =
  ## Matches :func:`modulabot.actors._add_icon_match` — skips
  ## matches within Chebyshev distance 1 of an existing one. Returns
  ## ``true`` when the match was added.
  for i in 0 ..< int(count):
    if abs(int(out_xs[i] - x)) <= 1 and abs(int(out_ys[i] - y)) <= 1:
      return false
  if count >= max_count:
    return false
  out_xs[count] = x
  out_ys[count] = y
  inc count
  return true

# ---------------------------------------------------------------------------
# mb_scan_task_icons
# ---------------------------------------------------------------------------

proc mb_scan_task_icons*(
    frame: ptr UncheckedArray[uint8],
    sprite: ptr UncheckedArray[uint8],
    sh: cint,
    sw: cint,
    # Task rects. ``task_coords`` is a flat packed array of
    # ``(x, y, w, h)`` int32 quads, one per task. ``num_tasks`` is
    # the count.
    task_coords: ptr UncheckedArray[int32],
    num_tasks: cint,
    cam_x: cint,
    cam_y: cint,
    search_radius: cint,
    # Output: at most ``max_matches`` ``(x, y)`` pairs.
    max_matches: cint,
    out_xs: ptr UncheckedArray[int32],
    out_ys: ptr UncheckedArray[int32],
    out_count: ptr cint,
) {.exportc, dynlib.} =
  ## Scan every task-station rect for the task icon sprite.
  ##
  ## For each task, the expected icon anchor in screen space is
  ## ``(task.x + task.w/2 - SpriteSize/2 - cam_x,
  ##   task.y - SpriteSize - 2 - cam_y)``. We search a 3-bob × ``(2r+1)²``
  ## neighbourhood around that anchor (matching
  ## :func:`modulabot.actors.scan_task_icons`). Dedup uses Chebyshev-1
  ## so icons at overlapping bob positions don't double-count.
  ##
  ## Off-screen anchors reject cheaply inside :func:`spriteMatchStrict`
  ## — the scan is dominated by the <5 tasks actually on screen.
  var count: int32 = 0
  let radius = int(search_radius)
  let shi = int(sh)
  let swi = int(sw)

  for ti in 0 ..< int(num_tasks):
    let baseCoord = ti * 4
    let tx = task_coords[baseCoord]
    let ty = task_coords[baseCoord + 1]
    let tw = task_coords[baseCoord + 2]
    # th not used — the icon is anchored to ty, not centred vertically.
    let baseX = int(tx) + int(tw) div 2 - SpriteSize div 2 - int(cam_x)
    let baseY = int(ty) - SpriteSize - 2 - int(cam_y)
    for bobY in [-1, 0, 1]:
      let expectedY = baseY + bobY
      for dy in -radius .. radius:
        for dx in -radius .. radius:
          let x = baseX + dx
          let y = expectedY + dy
          if spriteMatchStrict(frame, sprite, shi, swi, x, y):
            discard addMatchDedup(
              out_xs, out_ys, count,
              int32(max_matches), int32(x), int32(y),
            )
            if count >= int32(max_matches):
              out_count[] = count
              return

  out_count[] = count
