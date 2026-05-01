## Static perception reference data — palette, player colours, sprite
## atlas, map raster, ASCII font, map metadata. Phase 1.1.
##
## DESIGN.md §15 picks between "pre-baked Nim binary blobs" and "PNG
## ``staticRead`` + a Nim PNG decoder". We took door #1: the Nim tool
## ``among_them/guided_bot/tools/bake_assets.nim`` reads the upstream
## ``~/coding/bitworld`` checkout directly (using the same
## ``bitworld/aseprite`` parser the live server uses) and writes raw
## binaries into ``perception/baked/``. This module pulls them in via
## ``staticRead`` so the runtime Nim build has no PNG decoder
## dependency, no nimby dependency, and no runtime file I/O. Re-bake
## when the upstream Among Them assets change — see the agent
## README's "Regenerating baked assets" section.
##
## Layout of each blob is documented in ``tools/bake_assets.nim``. The
## ``BakeSchemaVersion`` constant must match the one in the bake tool;
## a mismatch fires a compile-time assert and stops the build before
## any kernel reads garbage.
##
## All exported sub-records, constants, and the consolidated
## :class:`ReferenceData` value are designed to be the single source of
## truth for downstream perception modules (phase 1.2 localize, 1.3
## actor scan, 1.4 task icons, 1.5 OCR, 1.6 voting). Constants here
## must agree with both the upstream ``bitworld/common/protocol.nim``
## ``Palette`` and ``among_them/sim.nim`` ``PlayerColors`` /
## ``ShadowMap``, and with the matching declarations in
## ``among_them/common/perception_kernels/sprite_match.nim`` and
## ``localize.nim``. Drift is caught at bake time (the bake tool uses
## the upstream code) and at compile time (the static asserts at the
## bottom of this module).

import std/json

# Re-export the upstream constants so downstream modules can `import
# perception/data` and not also have to import `../constants`.
import ../constants
export constants

# ---------------------------------------------------------------------------
# Palette / colour constants (must match modulabot/data.py)
# ---------------------------------------------------------------------------

const
  ## Sprite-format sentinel for "transparent". The bitworld v2 sprite
  ## format paints transparency as ``255'u8`` so the per-pixel array
  ## stays uint8. Mirror of :data:`modulabot.data.TRANSPARENT_INDEX`.
  TransparentIndex* = 255'u8

  ## Sprite size: every reference sprite is 12×12.
  SpriteSize* = 12

  ## Sprite-draw offsets used by phase 1.3 actor scanning. Mirror of
  ## ``SPRITE_DRAW_OFF_X`` / ``SPRITE_DRAW_OFF_Y`` in modulabot/data.py.
  SpriteDrawOffX* = 2
  SpriteDrawOffY* = 8

  ## Skeld map dimensions. Match modulabot/data.py's ``MAP_WIDTH`` and
  ## ``MAP_HEIGHT`` exactly.
  MapWidth* = 952
  MapHeight* = 534

  ## Palette index for the "tint" placeholder in reference sprites
  ## (replaced by the player's lit tint at sprite-match time).
  ## ``sim.nim`` calls this ``TintColor``.
  TintColor* = 3'u8
  ## Shaded variant of :data:`TintColor` (palette dark-purple, index 9).
  ShadeTintColor* = 9'u8

  ## Off-map padding colour (PICO-8 dark navy, index 12). Painted by
  ## the BitWorld renderer outside the map rectangle.
  MapVoidColor* = 12'u8

  ## Pixel-font ASCII range — see modulabot/data.py.
  FirstPrintableAscii* = 32
  LastPrintableAscii*  = 126
  PrintableAsciiCount* = LastPrintableAscii - FirstPrintableAscii + 1
  DefaultGlyphSpacing* = 1

  ## Background palette index for OCR text rendering. BitWorld
  ## interstitial banners always paint on black (PICO-8 0).
  SpaceColor* = 0'u8

  ## Number of player colour slots — must match
  ## :data:`PlayerColorCount` in ``constants.nim`` (which already
  ## hardcodes 8 for live-game player count). The PALETTE-side player
  ## colour table below is **16** entries, matching ``sim.nim``'s
  ## ``PlayerColors`` and modulabot's ``PLAYER_COLOR_COUNT``. Phase 0
  ## set ``PlayerColorCount = 8`` because that's the in-game player
  ## limit; this constant is the *colour table* size, which is larger
  ## so post-hum-readable colour names cover dead-player fallbacks too.
  PaletteColorTableSize* = 16

  ## Bake schema version — must match
  ## ``BakeSchemaVersion`` in ``tools/bake_assets.nim``. Bumped on any
  ## blob layout change. A mismatch is a compile-time assertion (see
  ## bottom of this module).
  BakeSchemaVersion* = 1

# ---------------------------------------------------------------------------
# Static colour tables (palette index lookups)
# ---------------------------------------------------------------------------

type
  RGB* = object
    r*, g*, b*: uint8

const
  ## PICO-8 palette (RGB). Index n is exactly the colour the BitWorld
  ## renderer paints when the sprite/raster carries palette index n.
  ## Must match modulabot/data.py's ``PICO8_PALETTE`` row-for-row.
  Pico8Palette*: array[PaletteColorTableSize, RGB] = [
    RGB(r: 0x00'u8, g: 0x00'u8, b: 0x00'u8),  #  0 black
    RGB(r: 0xC2'u8, g: 0xC3'u8, b: 0xC7'u8),  #  1 light grey
    RGB(r: 0xFF'u8, g: 0xF1'u8, b: 0xE8'u8),  #  2 white
    RGB(r: 0xFF'u8, g: 0x00'u8, b: 0x4D'u8),  #  3 red (TintColor)
    RGB(r: 0xFF'u8, g: 0x77'u8, b: 0xA8'u8),  #  4 pink
    RGB(r: 0x5F'u8, g: 0x57'u8, b: 0x4F'u8),  #  5 dark grey
    RGB(r: 0xAB'u8, g: 0x52'u8, b: 0x36'u8),  #  6 brown
    RGB(r: 0xFF'u8, g: 0xA3'u8, b: 0x00'u8),  #  7 orange
    RGB(r: 0xFF'u8, g: 0xEC'u8, b: 0x27'u8),  #  8 yellow (radar)
    RGB(r: 0x7E'u8, g: 0x25'u8, b: 0x53'u8),  #  9 dark purple (ShadeTint)
    RGB(r: 0x00'u8, g: 0x87'u8, b: 0x51'u8),  # 10 dark green
    RGB(r: 0x00'u8, g: 0xE4'u8, b: 0x36'u8),  # 11 green
    RGB(r: 0x1D'u8, g: 0x2B'u8, b: 0x53'u8),  # 12 dark navy (MapVoid)
    RGB(r: 0x83'u8, g: 0x76'u8, b: 0x9C'u8),  # 13 indigo
    RGB(r: 0x29'u8, g: 0xAD'u8, b: 0xFF'u8),  # 14 blue
    RGB(r: 0xFF'u8, g: 0xCC'u8, b: 0xAA'u8),  # 15 peach
  ]

  ## Per-colour-slot lit-tint palette index. Player slot N's body is
  ## tinted with palette colour ``PlayerColors[N]``. Order must match
  ## ``sim.nim``'s ``PlayerColors`` and the table in
  ## ``common/perception_kernels/sprite_match.nim``.
  PlayerColors*: array[PaletteColorTableSize, uint8] = [
    3'u8, 7, 8, 14, 4, 11, 13, 15, 1, 2, 5, 6, 9, 10, 12, 0
  ]

  ## Human-readable colour names indexed identically to
  ## :data:`PlayerColors`. Sourced from
  ## ``among_them/players/modulabot/evidence.nim`` so chat OCR like
  ## "sus blue" maps back to the same slot the imposter logic uses.
  PlayerColorNames*: array[PaletteColorTableSize, string] = [
    "red", "orange", "yellow", "light blue",
    "pink", "lime", "blue", "pale blue",
    "gray", "white", "dark brown", "brown",
    "dark teal", "green", "dark navy", "black"
  ]

  ## Palette index → its shadowed variant. Mirrors ``ShadowMap`` in
  ## ``sim.nim``.
  ShadowMap*: array[PaletteColorTableSize, uint8] = [
    0'u8, 12, 9, 5, 5, 0, 5, 5, 5, 12, 9, 9, 0, 12, 12, 9
  ]

# ---------------------------------------------------------------------------
# Reference-data record types
# ---------------------------------------------------------------------------

type
  Sprite* = object
    ## Fixed-size 2D palette-indexed sprite. ``pixels`` is row-major,
    ## length ``height * width``; ``TransparentIndex`` (=255) marks
    ## transparent pixels.
    width*, height*: int
    pixels*: seq[uint8]

  Rect* = object
    x*, y*, w*, h*: int

  TaskStation* = object
    ## One task station from ``map.json``. ``index`` is the slot in
    ## the tasks array (used by perception's task-icon matcher to
    ## identify which station an on-screen icon belongs to).
    index*: int
    name*: string
    x*, y*, w*, h*: int

  Room* = object
    name*: string
    x*, y*, w*, h*: int

  GameMap* = object
    width*, height*: int
    button*: Rect            ## Meeting button location.
    homeX*, homeY*: int      ## Player spawn point (sim.nim ``home``).
    tasks*: seq[TaskStation]
    rooms*: seq[Room]
    ## Map raster layers. Each is row-major, length ``height * width``.
    mapPixels*: seq[uint8]   ## Palette indices.
    walkMask*: seq[uint8]    ## ``1`` walkable, ``0`` blocked.
    wallMask*: seq[uint8]    ## ``1`` wall, ``0`` not.

  Sprites* = object
    ## Six reference sprites sliced from spritesheet.png. Order matches
    ## :data:`SpriteColumns` in ``tools/bake_assets.nim``.
    player*: Sprite
    body*: Sprite
    ghost*: Sprite
    task*: Sprite
    killButton*: Sprite
    ghostIcon*: Sprite

  PixelGlyph* = object
    ## One variable-width glyph for the tiny5 pixel font. ``pixels``
    ## is row-major ``height * width`` bytes; ``1`` = foreground, ``0``
    ## = background.
    ch*: char
    width*, height*: int
    pixels*: seq[uint8]

  PixelFont* = object
    height*: int
    spacing*: int
    ## Indexed by ``ord(ch) - FirstPrintableAscii``. Always exactly
    ## :data:`PrintableAsciiCount` entries.
    glyphs*: array[PrintableAsciiCount, PixelGlyph]

  ReferenceData* = object
    map*: GameMap
    sprites*: Sprites
    font*: PixelFont

# ---------------------------------------------------------------------------
# Embedded blob bytes (compile-time staticRead)
# ---------------------------------------------------------------------------

const
  ## ``staticRead`` paths are relative to *this source file*, mirroring
  ## the layout under ``perception/baked/``. The compiler resolves them
  ## at compile time and embeds the bytes into the binary.
  PaletteBlob*  = staticRead("baked/palette.bin")
  SpritesBlob*  = staticRead("baked/sprites.bin")
  MapPixelsBlob* = staticRead("baked/map_pixels.bin")
  WalkMaskBlob*  = staticRead("baked/walk_mask.bin")
  WallMaskBlob*  = staticRead("baked/wall_mask.bin")
  FontBlob*      = staticRead("baked/font.bin")
  MapJsonBlob*   = staticRead("baked/map.json")

# Compile-time shape sanity. Any mismatch with the bake tool fires a
# `static:` assert and stops the build immediately, so a stale baked
# directory never silently mis-feeds the kernels.
static:
  doAssert PaletteBlob.len == PaletteColorTableSize * 3,
    "perception/data: palette.bin wrong size; re-run tools/bake_assets.nim"
  doAssert SpritesBlob.len == 6 * SpriteSize * SpriteSize,
    "perception/data: sprites.bin wrong size; re-run tools/bake_assets.nim"
  doAssert MapPixelsBlob.len == MapWidth * MapHeight,
    "perception/data: map_pixels.bin wrong size; re-run tools/bake_assets.nim"
  doAssert WalkMaskBlob.len == MapWidth * MapHeight,
    "perception/data: walk_mask.bin wrong size; re-run tools/bake_assets.nim"
  doAssert WallMaskBlob.len == MapWidth * MapHeight,
    "perception/data: wall_mask.bin wrong size; re-run tools/bake_assets.nim"

# ---------------------------------------------------------------------------
# Loaders (run once at module init)
# ---------------------------------------------------------------------------

proc blobToBytes(blob: string): seq[uint8] {.inline.} =
  ## Copy a compile-time string blob into a fresh ``seq[uint8]``. The
  ## copy is unavoidable because ``staticRead`` returns ``string`` and
  ## downstream perception code wants a mutable / indexable byte seq;
  ## the cost is paid once at module init (well below 10 ms total even
  ## for the 508 KB map raster).
  result = newSeq[uint8](blob.len)
  for i in 0 ..< blob.len:
    result[i] = uint8(blob[i])

proc loadSprites(): Sprites =
  ## Slice ``sprites.bin`` (864 bytes = 6 × 12 × 12) into the named
  ## :data:`SPRITE_ORDER` slots. Sprite order must match the bake tool.
  const stride = SpriteSize * SpriteSize
  proc slice(idx: int): Sprite =
    let base = idx * stride
    var px = newSeq[uint8](stride)
    for i in 0 ..< stride:
      px[i] = uint8(SpritesBlob[base + i])
    Sprite(width: SpriteSize, height: SpriteSize, pixels: px)

  Sprites(
    player:     slice(0),
    body:       slice(1),
    ghost:      slice(2),
    task:       slice(3),
    killButton: slice(4),
    ghostIcon:  slice(5)
  )

proc loadMap(): GameMap =
  ## Construct the :class:`GameMap` from the raster blobs and the
  ## map-metadata JSON. The metadata blob is parsed at module init
  ## (cheap; ~9 KB).
  let parsed = parseJson(MapJsonBlob)

  var tasks: seq[TaskStation] = @[]
  if parsed.hasKey("tasks"):
    var i = 0
    for t in parsed["tasks"].items:
      tasks.add TaskStation(
        index: i,
        name: t["name"].getStr,
        x: t["x"].getInt,
        y: t["y"].getInt,
        w: t["w"].getInt,
        h: t["h"].getInt
      )
      inc i

  var rooms: seq[Room] = @[]
  if parsed.hasKey("rooms"):
    for r in parsed["rooms"].items:
      rooms.add Room(
        name: r["name"].getStr,
        x: r["x"].getInt,
        y: r["y"].getInt,
        w: r["w"].getInt,
        h: r["h"].getInt
      )

  let bj = parsed["button"]
  let hj = parsed["home"]

  GameMap(
    width: MapWidth,
    height: MapHeight,
    button: Rect(
      x: bj["x"].getInt, y: bj["y"].getInt,
      w: bj["w"].getInt, h: bj["h"].getInt
    ),
    homeX: hj["x"].getInt,
    homeY: hj["y"].getInt,
    tasks: tasks,
    rooms: rooms,
    mapPixels: blobToBytes(MapPixelsBlob),
    walkMask:  blobToBytes(WalkMaskBlob),
    wallMask:  blobToBytes(WallMaskBlob)
  )

proc loadFont(): PixelFont =
  ## Decode ``font.bin``. Format (little-endian):
  ##   u8 height, u8 spacing, u16 glyph_count,
  ##   for each glyph: u8 width, height*width bytes (0/1 row-major).
  doAssert FontBlob.len >= 4, "font.bin truncated header"
  let height = int(uint8(FontBlob[0]))
  let spacing = int(uint8(FontBlob[1]))
  let count = int(uint8(FontBlob[2])) or (int(uint8(FontBlob[3])) shl 8)
  doAssert count == PrintableAsciiCount,
    "font.bin glyph count " & $count & " != " & $PrintableAsciiCount

  var pos = 4
  var glyphs: array[PrintableAsciiCount, PixelGlyph]
  for i in 0 ..< PrintableAsciiCount:
    doAssert pos < FontBlob.len, "font.bin truncated at glyph " & $i
    let width = int(uint8(FontBlob[pos]))
    inc pos
    let bytes = height * width
    doAssert pos + bytes <= FontBlob.len,
      "font.bin truncated in glyph " & $i & " body"
    var px = newSeq[uint8](bytes)
    for k in 0 ..< bytes:
      px[k] = uint8(FontBlob[pos + k])
    pos += bytes
    glyphs[i] = PixelGlyph(
      ch: chr(FirstPrintableAscii + i),
      width: width,
      height: height,
      pixels: px
    )
  doAssert pos == FontBlob.len,
    "font.bin trailing bytes; expected " & $FontBlob.len & " consumed " & $pos

  PixelFont(height: height, spacing: spacing, glyphs: glyphs)

proc buildReferenceData(): ReferenceData =
  ReferenceData(
    map: loadMap(),
    sprites: loadSprites(),
    font: loadFont()
  )

# ---------------------------------------------------------------------------
# Public reference-data value
# ---------------------------------------------------------------------------

## Initialised once at module load. All perception modules read from
## this single value.
let referenceData* = buildReferenceData()

# ---------------------------------------------------------------------------
# Convenience accessors (keep call sites concise)
# ---------------------------------------------------------------------------

proc gameMap*(): lent GameMap {.inline.} =
  referenceData.map

proc sprites*(): lent Sprites {.inline.} =
  referenceData.sprites

proc font*(): lent PixelFont {.inline.} =
  referenceData.font

proc glyphForChar*(ch: char): lent PixelGlyph {.inline.} =
  ## Look up a glyph by ASCII char. Out-of-range characters fall back
  ## to ``'?'`` so OCR matchers don't have to bounds-check.
  let c = ord(ch)
  if c < FirstPrintableAscii or c > LastPrintableAscii:
    return referenceData.font.glyphs[ord('?') - FirstPrintableAscii]
  referenceData.font.glyphs[c - FirstPrintableAscii]
