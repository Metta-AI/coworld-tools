## Pixel-font OCR kernels.
##
## Phase 4 target: replace the Python vectorised ``best_glyph`` that
## dominates voting-chat frames (~25 ms p50 on chat-heavy frames). A
## scalar Nim scan over 95 glyphs × 7×7 pixels is ~5 µs per position,
## so a full 32-glyph chat-line read drops from ~800 µs per line to
## ~150 µs.
##
## Exported symbols:
##
## - ``mb_best_glyph`` — pick the best-matching glyph at ``(x, y)``.
##   Mirrors :func:`modulabot.ascii.best_glyph`.
## - ``mb_text_matches`` — exact-phrase check at a fixed position.
##   Mirrors :func:`modulabot.ascii.text_matches`. Useful for
##   interstitial-banner detection.
##
## Font packing format (caller-owned): one flat ``uint8`` pixel array
## of shape ``(num_glyphs, height, max_width)``, row-major, 1 = on
## and 0 = off. Trailing columns beyond the glyph's actual width are
## padded with zeros. Widths, opaque counts, and preferences are
## separate int32 arrays, one entry per glyph.
##
## ``find_text`` (full-frame sweep for interstitial banners) is kept
## in Python for now — the existing ``sliding_window_view`` numpy
## path is already <2 ms, and we only invoke it a handful of times
## per game.

import sprite_match  # ScreenWidth, ScreenHeight

# ---------------------------------------------------------------------------
# Frame-on mask helper
# ---------------------------------------------------------------------------

proc framePixelOn(
    frame: ptr UncheckedArray[uint8],
    x, y: int,
    background: uint8,
): int {.inline.} =
  ## 1 if the frame pixel at ``(x, y)`` is not the background
  ## (i.e. text-on). Off-screen reads return 0 — matches the Python
  ## ``_frame_pixel_on`` + padding behaviour.
  if x < 0 or y < 0 or
     x >= int(sprite_match.ScreenWidth) or
     y >= int(sprite_match.ScreenHeight):
    return 0
  if frame[y * int(sprite_match.ScreenWidth) + x] != background:
    return 1
  return 0

# ---------------------------------------------------------------------------
# mb_best_glyph
# ---------------------------------------------------------------------------

proc scoreGlyph(
    frame: ptr UncheckedArray[uint8],
    font_pixels: ptr UncheckedArray[uint8],
    glyph_idx: int,
    glyph_width: int,
    font_height: int,
    font_max_width: int,
    spacing: int,
    x, y: int,
    background: uint8,
    early_exit: int,
): int {.inline.} =
  ## Count mismatches between glyph ``glyph_idx`` and the frame at
  ## ``(x, y)``. Scan width is ``glyph_width + spacing`` (the
  ## trailing inter-glyph column is checked for bleed-over, matching
  ## :func:`modulabot.ascii.glyph_score`).
  ##
  ## ``early_exit`` is a strict upper bound — we stop counting once
  ## ``misses >= early_exit`` and return ``early_exit`` as the
  ## sentinel. Callers pass ``best_errors + 1`` so ties are fully
  ## counted for tie-breaking but strictly-worse glyphs reject
  ## cheaply. Using ``best_errors`` directly would make the sentinel
  ## indistinguishable from a real zero-miss glyph when
  ## ``best_errors == 0``.
  let scanW = glyph_width + spacing
  let glyphStride = font_max_width * font_height
  let glyphBase = glyph_idx * glyphStride
  var misses = 0
  for row in 0 ..< font_height:
    let glyphRow = glyphBase + row * font_max_width
    for col in 0 ..< scanW:
      let expected =
        if col < glyph_width: int(font_pixels[glyphRow + col])
        else: 0
      let actual = framePixelOn(frame, x + col, y + row, background)
      if expected != actual:
        inc misses
        if misses >= early_exit:
          return early_exit
  return misses

proc mb_best_glyph*(
    frame: ptr UncheckedArray[uint8],
    font_pixels: ptr UncheckedArray[uint8],
    font_widths: ptr UncheckedArray[int32],
    font_opaque: ptr UncheckedArray[int32],
    font_preferences: ptr UncheckedArray[int32],
    num_glyphs: cint,
    font_height: cint,
    font_max_width: cint,
    font_spacing: cint,
    x: cint,
    y: cint,
    max_errors: cint,
    background: cint,
    out_glyph_idx: ptr cint,     # -1 if nothing cleared max_errors
    out_errors: ptr cint,
    out_advance: ptr cint,       # width + spacing of the winner
) {.exportc, dynlib.} =
  ## Pick the best-matching glyph at ``(x, y)``.
  ##
  ## Tie-break order matches :func:`modulabot.ascii.best_glyph`:
  ##
  ## 1. Fewer mismatches.
  ## 2. More opaque pixels (the glyph with richer structure wins,
  ##    so a nearly-blank cell doesn't beat a real letter).
  ## 3. Higher preference (lowercase > digits > uppercase > space).
  ##
  ## When no glyph clears ``max_errors`` ``out_glyph_idx`` is set
  ## to ``-1`` and the Python wrapper returns ``'?'``.
  ##
  ## Early-exit: bad glyphs stop counting once they exceed the
  ## current best — the scalar inner loop spends most of its time
  ## rejecting the long tail of wrong answers.
  var
    bestIdx: int32 = -1
    bestErrors: int32 = int32(max_errors) + 1
    bestOpaque: int32 = -1
    bestPref: int32 = -1

  let ng = int(num_glyphs)
  let fh = int(font_height)
  let fw = int(font_max_width)
  let spacing = int(font_spacing)
  let bg = uint8(background)

  for g in 0 ..< ng:
    let width = int(font_widths[g])
    if width <= 0:
      continue
    # Early-exit budget: strictly worse than current best rejects
    # cheaply, but ties are fully counted for the tie-break ladder.
    # Using ``bestErrors`` directly would make the sentinel
    # indistinguishable from a zero-miss glyph when bestErrors == 0.
    let budget = int(bestErrors) + 1
    let errors = int32(scoreGlyph(
      frame, font_pixels,
      g, width, fh, fw, spacing,
      int(x), int(y), bg,
      budget,
    ))
    if errors > bestErrors:
      continue
    if errors == bestErrors:
      # Tie-break: higher opaque first, then higher preference.
      let op = font_opaque[g]
      if op < bestOpaque: continue
      if op == bestOpaque:
        let pr = font_preferences[g]
        if pr <= bestPref: continue
        bestIdx = int32(g)
        bestPref = pr
        continue
      # op > bestOpaque.
      bestIdx = int32(g)
      bestOpaque = op
      bestPref = font_preferences[g]
      continue
    # errors < bestErrors → new winner.
    bestIdx = int32(g)
    bestErrors = errors
    bestOpaque = font_opaque[g]
    bestPref = font_preferences[g]

  if bestIdx < 0 or bestErrors > int32(max_errors):
    out_glyph_idx[] = -1
    out_errors[] = bestErrors
    out_advance[] = 0
    return
  out_glyph_idx[] = cint(bestIdx)
  out_errors[] = cint(bestErrors)
  out_advance[] = cint(int(font_widths[bestIdx]) + spacing)

# ---------------------------------------------------------------------------
# mb_text_matches
# ---------------------------------------------------------------------------

proc mb_text_matches*(
    frame: ptr UncheckedArray[uint8],
    font_pixels: ptr UncheckedArray[uint8],
    font_widths: ptr UncheckedArray[int32],
    font_height: cint,
    font_max_width: cint,
    font_spacing: cint,
    # Packed text as glyph indices (int32, -1 for newline).
    text_indices: ptr UncheckedArray[int32],
    text_len: cint,
    x: cint,
    y: cint,
    max_errors: cint,
    background: cint,
    out_matched: ptr cint,    # 1 if passes, 0 otherwise
    out_errors: ptr cint,
    out_opaque: ptr cint,     # total expected-on pixels in all glyphs
) {.exportc, dynlib.} =
  ## Score a whole phrase at ``(x, y)`` and report
  ## ``(errors, opaque, matched)``.
  ##
  ## Text is passed as an array of glyph indices (-1 encodes newline,
  ## matching the Python caller's pre-conversion). The pen walks
  ## across glyphs advancing by ``widths[i] + spacing``; a newline
  ## resets pen-X to ``x`` and advances pen-Y by
  ## ``font_height + spacing`` — identical to
  ## :func:`modulabot.ascii.text_score`.
  ##
  ## Used by :func:`modulabot.ascii.text_matches`; callers check
  ## ``matched == 1`` (equivalent to ``opaque > 0 and errors <=
  ## max_errors``).
  let fh = int(font_height)
  let fw = int(font_max_width)
  let spacing = int(font_spacing)
  let bg = uint8(background)
  var penX = int(x)
  var penY = int(y)
  var totalErrors = 0
  var totalOpaque = 0

  # No per-glyph early-exit here; the caller wants the full totals
  # for reporting. ``max_errors`` is only consulted when we set the
  # matched flag at the end.
  for i in 0 ..< int(text_len):
    let idx = int(text_indices[i])
    if idx == -1:
      penX = int(x)
      penY += fh + spacing
      continue
    if idx < 0:
      continue
    let width = int(font_widths[idx])
    if width <= 0:
      continue
    let glyphStride = fw * fh
    let glyphBase = idx * glyphStride
    let scanW = width + spacing
    # Accumulate errors + opaque directly.
    for row in 0 ..< fh:
      let glyphRow = glyphBase + row * fw
      for col in 0 ..< scanW:
        let expected =
          if col < width: int(font_pixels[glyphRow + col])
          else: 0
        totalOpaque += expected
        let actual = framePixelOn(frame, penX + col, penY + row, bg)
        if expected != actual:
          inc totalErrors
    penX += width + spacing

  out_errors[] = cint(totalErrors)
  out_opaque[] = cint(totalOpaque)
  if totalOpaque > 0 and totalErrors <= int(max_errors):
    out_matched[] = 1
  else:
    out_matched[] = 0
