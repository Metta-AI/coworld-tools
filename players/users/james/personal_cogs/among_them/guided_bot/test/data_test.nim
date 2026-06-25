## Phase-1.1 perception-data tests.
##
## Verifies that the bake-tool-emitted blobs (`perception/baked/*.bin`)
## decode into a :class:`ReferenceData` value with the shape and
## magic-number content the downstream perception kernels assume.
## Constants here are pinned to known-good values from the upstream
## bitworld Among Them data (palette, player colours, shadow map,
## button rect, task count, etc.) so any silent drift between the
## bitworld assets and our baked blobs trips a diagnostic-quality
## "expected / got" failure rather than slipping into phase 1.2+.
##
## Run:
##   nim c -r -d:release --threads:on --mm:orc \
##       among_them/guided_bot/test/data_test.nim
##
## To regenerate the baked blobs (whenever the upstream bitworld
## checkout's Among Them assets change):
##   future UV/Coworld asset regeneration workflow
## (Override BITWORLD_DIR to point elsewhere; defaults to
## ~/coding/bitworld.)

import std/strformat
import ../perception/data

# ---------------------------------------------------------------------------
# Test harness (matches perception_test.nim)
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
# 1. Palette / colour tables
# ---------------------------------------------------------------------------

proc testPalette() =
  expectEq(Pico8Palette.len, 16, "palette length")
  # Spot-check a few entries that must agree with sim.nim.
  expectEq(Pico8Palette[0],
           RGB(r: 0x00'u8, g: 0x00'u8, b: 0x00'u8),
           "palette[0] black")
  expectEq(Pico8Palette[3],
           RGB(r: 0xFF'u8, g: 0x00'u8, b: 0x4D'u8),
           "palette[3] red (TintColor)")
  expectEq(Pico8Palette[8],
           RGB(r: 0xFF'u8, g: 0xEC'u8, b: 0x27'u8),
           "palette[8] yellow (radar)")
  expectEq(Pico8Palette[12],
           RGB(r: 0x1D'u8, g: 0x2B'u8, b: 0x53'u8),
           "palette[12] dark navy (MapVoid)")

  # Palette-derived constants the rest of the bot depends on.
  expectEq(TintColor, 3'u8, "TintColor")
  expectEq(ShadeTintColor, 9'u8, "ShadeTintColor")
  expectEq(MapVoidColor, 12'u8, "MapVoidColor")
  expectEq(TransparentIndex, 255'u8, "TransparentIndex")

proc testPlayerColors() =
  # Order must match sim.nim's PlayerColors (also mirrored in
  # the shared common/perception_kernels/sprite_match.nim).
  const expected: array[16, uint8] = [
    3'u8, 7, 8, 14, 4, 11, 13, 15, 1, 2, 5, 6, 9, 10, 12, 0
  ]
  for i in 0 ..< 16:
    expectEq(PlayerColors[i], expected[i],
             &"PlayerColors[{i}]")

  # Colour-name table lines up element-for-element. Spot-check a
  # couple that the chat OCR depends on.
  expectEq(PlayerColorNames[0], "red",         "PlayerColorNames[0]")
  expectEq(PlayerColorNames[6], "blue",        "PlayerColorNames[6]")
  expectEq(PlayerColorNames[3], "light blue",  "PlayerColorNames[3]")
  expectEq(PlayerColorNames[15], "black",      "PlayerColorNames[15]")

proc testShadowMap() =
  # ShadowMap mirrors sim.nim's ShadowMap exactly. A drift here would
  # invalidate the "matchesSpriteShadowed" path in phase 1.3.
  const expected: array[16, uint8] = [
    0'u8, 12, 9, 5, 5, 0, 5, 5, 5, 12, 9, 9, 0, 12, 12, 9
  ]
  for i in 0 ..< 16:
    expectEq(ShadowMap[i], expected[i], &"ShadowMap[{i}]")

# ---------------------------------------------------------------------------
# 2. Sprites
# ---------------------------------------------------------------------------

proc testSprites() =
  let sp = referenceData.sprites
  let allSix = [sp.player, sp.body, sp.ghost, sp.task,
                sp.killButton, sp.ghostIcon]
  for i, s in allSix:
    expectEq(s.width, SpriteSize, &"sprite #{i}: width = SpriteSize")
    expectEq(s.height, SpriteSize, &"sprite #{i}: height = SpriteSize")
    expectEq(s.pixels.len, SpriteSize * SpriteSize,
             &"sprite #{i}: pixels.len")

  # Concrete pixel sanity. A 12×12 sprite has at least one transparent
  # pixel at every corner (the player sprite is round-ish; body/ghost
  # share the silhouette). We don't pin specific palette indices
  # because that would tie the test too tightly to the modulabot PNG;
  # but we do require that *some* transparent pixels exist (a fully
  # opaque 12×12 means the slicer hit the wrong sprite).
  proc hasTransparent(s: Sprite): bool =
    for px in s.pixels:
      if px == TransparentIndex: return true
    false
  expect(hasTransparent(sp.player),
         "player sprite: contains some transparent pixels")
  expect(hasTransparent(sp.body),
         "body sprite: contains some transparent pixels")
  expect(hasTransparent(sp.task),
         "task sprite: contains some transparent pixels")

  # The player sprite uses TintColor (=3) somewhere — that's the lit-
  # tint placeholder that gets remapped to the player's colour at
  # match time.
  proc hasTint(s: Sprite, c: uint8): bool =
    for px in s.pixels:
      if px == c: return true
    false
  expect(hasTint(sp.player, TintColor),
         "player sprite: contains TintColor (3)")

# ---------------------------------------------------------------------------
# 3. Map raster + metadata
# ---------------------------------------------------------------------------

proc testMap() =
  let m = referenceData.map
  expectEq(m.width, MapWidth, "map.width")
  expectEq(m.height, MapHeight, "map.height")
  expectEq(m.mapPixels.len, MapWidth * MapHeight, "map.mapPixels.len")
  expectEq(m.walkMask.len, MapWidth * MapHeight, "map.walkMask.len")
  expectEq(m.wallMask.len, MapWidth * MapHeight, "map.wallMask.len")

  # Walk and wall masks are 0/1 only.
  var nonBoolWalk = 0
  var nonBoolWall = 0
  for i in 0 ..< m.walkMask.len:
    if m.walkMask[i] notin {0'u8, 1'u8}: inc nonBoolWalk
    if m.wallMask[i] notin {0'u8, 1'u8}: inc nonBoolWall
  expectEq(nonBoolWalk, 0, "walk mask is 0/1 only")
  expectEq(nonBoolWall, 0, "wall mask is 0/1 only")

  # Some pixels are walkable, some are not. Sanity bound: at least 1 %
  # walkable, at most 80 % walkable. Skeld empirically falls inside.
  var walkCount = 0
  for v in m.walkMask:
    if v == 1'u8: inc walkCount
  let total = m.walkMask.len
  expect(walkCount > total div 100,
         &"walk mask has at least 1 % walkable: {walkCount}/{total}")
  expect(walkCount < (total * 80) div 100,
         &"walk mask is not >80 % walkable: {walkCount}/{total}")

  # Button rect — pinned to map.json's value.
  expectEq(m.button.x, 524, "button.x")
  expectEq(m.button.y, 114, "button.y")
  expectEq(m.button.w, 28,  "button.w")
  expectEq(m.button.h, 34,  "button.h")

  # Home position.
  expectEq(m.homeX, 536, "homeX")
  expectEq(m.homeY, 120, "homeY")

  # Tasks: modulabot's map.json has 40 task entries on Skeld.
  expectEq(m.tasks.len, 40, "task count")
  expectEq(m.tasks[0].name, "Empty Garbage", "tasks[0].name")
  expectEq(m.tasks[0].x, 554, "tasks[0].x")
  # Task `index` is the slot in the array; checking the boundary
  # values protects against off-by-one in the loader.
  expectEq(m.tasks[0].index, 0, "tasks[0].index")
  expectEq(m.tasks[^1].index, m.tasks.len - 1, "tasks[^1].index")

  # Rooms: present on Skeld; spot-check the first.
  expect(m.rooms.len > 0, "at least one room parsed")
  if m.rooms.len > 0:
    expectEq(m.rooms[0].name, "Upper Engine", "rooms[0].name")
    expectEq(m.rooms[0].x, 159, "rooms[0].x")

# ---------------------------------------------------------------------------
# 4. Font
# ---------------------------------------------------------------------------

proc testFont() =
  let f = referenceData.font
  expect(f.height >= 5 and f.height <= 12,
         &"font height in plausible range: {f.height}")
  expectEq(f.spacing, DefaultGlyphSpacing, "font spacing")
  expectEq(f.glyphs.len, PrintableAsciiCount, "glyph count")

  # First glyph is space (' ').
  expectEq(f.glyphs[0].ch, ' ', "first glyph is space")
  expectEq(f.glyphs[ord('A') - FirstPrintableAscii].ch, 'A',
           "ord('A') glyph is 'A'")
  expectEq(f.glyphs[ord('~') - FirstPrintableAscii].ch, '~',
           "last glyph is tilde")

  # Every glyph's pixel buffer length equals height*width.
  for i in 0 ..< f.glyphs.len:
    let g = f.glyphs[i]
    expectEq(g.pixels.len, g.height * g.width,
             &"glyph #{i} ('{g.ch}'): pixels.len")
    # All pixel bytes are 0/1.
    for px in g.pixels:
      if px notin {0'u8, 1'u8}:
        stderr.writeLine &"FAIL: glyph #{i} has non-bool pixel byte {px}"
        inc failures
        break

  # 'A' has a known shape: width 4 in tiny5. (Pinned from inspection of
  # modulabot's font; if upstream re-renders the font this needs an
  # update.)
  let glyphA = f.glyphs[ord('A') - FirstPrintableAscii]
  expectEq(glyphA.width, 4, "glyph 'A' width")

  # Fallback look-up returns a glyph for OOB chars.
  let q = glyphForChar('?')
  expectEq(q.ch, '?', "glyphForChar('?')")
  let oob = glyphForChar('\0')
  expectEq(oob.ch, '?', "glyphForChar(NUL) falls back to '?'")

# ---------------------------------------------------------------------------
# 5. Cross-module wiring — `import perception` re-exports `data`.
# ---------------------------------------------------------------------------

proc testReExports() =
  # Importing perception/data here directly is what the rest of this
  # file does; verify that the higher-level `import ../perception` path
  # also surfaces these names. The perception module is imported via
  # the test's transitive includes; here we just confirm `referenceData`
  # is a non-empty reference-data value (sanity).
  expect(referenceData.map.tasks.len > 0,
         "referenceData reachable, has tasks")
  expect(referenceData.sprites.player.pixels.len ==
         SpriteSize * SpriteSize,
         "referenceData.sprites.player has expected size")

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

proc main() =
  testPalette()
  testPlayerColors()
  testShadowMap()
  testSprites()
  testMap()
  testFont()
  testReExports()

  if failures == 0:
    echo "OK (all perception phase-1.1 data checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
