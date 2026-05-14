## Bake guided_bot's perception assets directly from the upstream
## bitworld checkout — single source of truth, no modulabot middleman.
##
## Phase 1.1 of the perception port (DESIGN.md §15, decision D20).
## Reads:
##
##   - ``$BITWORLD_DIR/clients/data/pallete.png``  (16-entry palette)
##   - ``$BITWORLD_DIR/among_them/map.json``       (map metadata)
##   - ``$BITWORLD_DIR/among_them/skeld2.aseprite`` (3 layers: map/walk/walls)
##   - ``$BITWORLD_DIR/among_them/spritesheet.aseprite`` (the 12×12 sprite atlas;
##     preferred when present, with ``spritesheet.png`` as fallback)
##   - ``$BITWORLD_DIR/among_them/tiny5.aseprite``  (variable-width pixel font)
##
## Writes (under ``among_them/guided_bot/perception/baked/``):
##
##   - ``palette.bin``    16 × 3 bytes RGB
##   - ``sprites.bin``    6 × 12 × 12 bytes, palette-indexed,
##                        order: player, body, ghost, task, kill_button,
##                        ghost_icon. (Sprite-atlas columns 0, 1, 6, 4, 3, 7.)
##   - ``map_pixels.bin`` MapH × MapW palette-indexed bytes
##   - ``walk_mask.bin``  MapH × MapW 0/1 bytes (alpha > 0)
##   - ``wall_mask.bin``  MapH × MapW 0/1 bytes (alpha > 0)
##   - ``font.bin``       compact variable-width font; format documented in
##                        ``perception/data.nim`` ``loadFont``.
##   - ``map.json``       verbatim copy of the upstream JSON.
##   - ``manifest.json``  schema version + sizes + sha256 per file.
##
## Reproducibility: every output is a deterministic function of the
## upstream inputs. Re-running on unchanged inputs produces byte-
## identical outputs.
##
## Why Nim (not Python): the upstream uses the ``bitworld/aseprite``
## parser to render ``skeld2.aseprite`` and ``tiny5.aseprite``, so reading
## it the same way the live server does is the cheapest correctness
## guarantee. Python lacks a well-maintained aseprite parser; rather
## than write our own decoder for a binary format we already have a
## production-quality reader for, we just call the production reader.
##
## Usage::
##
##     among_them/guided_bot/tools/bake_assets.sh
##
## or, equivalently, from the repo root::
##
##     BITWORLD_DIR=${BITWORLD_DIR:-$HOME/coding/bitworld}
##     nim r --threads:on --mm:orc \
##         --path:"$BITWORLD_DIR/src" \
##         --path:"$BITWORLD_DIR" \
##         --path:"$BITWORLD_DIR/common" \
##         among_them/guided_bot/tools/bake_assets.nim
##
## The tool requires ``nimby`` (for ``pixie`` + ``zippy``) and the
## bitworld checkout. Both are already prerequisites for any Among
## Them work in this repo (per AGENTS.md). The ``guided_bot`` runtime
## binary remains nimby-free; only this bake step needs the upstream.

import std/[os, strformat, strutils, json, sha1]

import pixie
import bitworld/aseprite
# protocol.nim owns the global `Palette` array and `loadPalette`;
# server.nim provides `nearestPaletteIndex`. Both live under the
# upstream ``$BITWORLD_DIR/common/`` directory which our wrapper
# script adds to ``--path:``.
import protocol
import server
import pixelfonts

# ---------------------------------------------------------------------------
# Layout decisions (must match perception/data.nim)
# ---------------------------------------------------------------------------

const
  ## Bumped in lock-step with ``BakeSchemaVersion`` in
  ## ``perception/data.nim``. A drift here trips a compile-time assert
  ## in the data module so a stale baked dir never silently mis-feeds
  ## the kernels.
  BakeSchemaVersion = 1

  MapWidth = 952
  MapHeight = 534
  SpriteSize = 12

  ## Sprite-atlas columns to slice. Order matches the field order in
  ## ``perception/data.nim::Sprites`` and ``modulabot.data.Sprites``.
  ## Column 2 is "bone" (unused by guided_bot), column 5 is empty —
  ## both omitted.
  SpriteColumns: array[6, int] = [
    0,  # player
    1,  # body
    6,  # ghost
    4,  # task
    3,  # kill_button
    7,  # ghost_icon
  ]

  FirstPrintableAsciiBake = 32
  LastPrintableAsciiBake = 126
  PrintableAsciiCountBake =
    LastPrintableAsciiBake - FirstPrintableAsciiBake + 1

# Resolve where to read upstream from. Default points at the local
# clone documented in repo AGENTS.md; override with ``BITWORLD_DIR``
# if the user keeps it elsewhere.
let bitworldDir =
  if existsEnv("BITWORLD_DIR"):
    getEnv("BITWORLD_DIR")
  else:
    getHomeDir() / "coding" / "bitworld"

# Resolve where to write blobs. The script normally runs with cwd at
# repo root; computing the output dir from this source file's location
# makes the tool usable from any cwd.
let bakedDir =
  currentSourcePath().parentDir().parentDir() / "perception" / "baked"

# ---------------------------------------------------------------------------
# Layer rendering helpers (port of `asepriteLayerImage` from sim.nim)
# ---------------------------------------------------------------------------

proc asepritePixelAt(
    aseprite: AsepriteSprite,
    cel: AsepriteCel,
    i: int): ColorRGBA =
  ## Convert one cel pixel to straight RGBA. Mirrors the private
  ## ``asepritePixelAt`` in ``bitworld/among_them/sim.nim`` — kept in
  ## sync by reading the same code on each upstream refresh. Indexed
  ## cels resolve through the aseprite file's own palette (NOT the
  ## bitworld 16-colour PICO-8 palette, which is a separate concept
  ## populated by ``loadPalette``).
  case aseprite.header.colorDepth
  of DepthRgba:
    let base = i * 4
    rgba(
      cel.data[base],
      cel.data[base + 1],
      cel.data[base + 2],
      cel.data[base + 3])
  of DepthGrayscale:
    let base = i * 2
    rgba(cel.data[base], cel.data[base], cel.data[base], cel.data[base + 1])
  of DepthIndexed:
    let index = cel.data[i].int
    if index == aseprite.header.transparentIndex:
      rgba(0, 0, 0, 0)
    elif index < aseprite.palette.len:
      aseprite.palette[index]
    else:
      rgba(0, 0, 0, 0)

proc renderLayer(aseprite: AsepriteSprite, layerIndex: int): Image =
  ## Render one named layer of the first frame to a fresh RGBA image
  ## without alpha-blending against other layers. Mirrors the private
  ## ``asepriteLayerImage`` in sim.nim — same logic, same behavior.
  if aseprite.frames.len == 0:
    raise newException(ValueError, "aseprite has no frames")
  if layerIndex < 0 or layerIndex >= aseprite.layers.len:
    raise newException(
      ValueError,
      "aseprite is missing layer index " & $layerIndex)
  result = newImage(aseprite.header.width, aseprite.header.height)
  result.fill(rgba(0, 0, 0, 0))
  for cel in aseprite.frames[0].cels:
    if cel.layerIndex != layerIndex:
      continue
    if cel.kind notin {CelRaw, CelCompressed}:
      continue
    for y in 0 ..< cel.height:
      let dstY = cel.y + y
      if dstY < 0 or dstY >= result.height:
        continue
      for x in 0 ..< cel.width:
        let dstX = cel.x + x
        if dstX < 0 or dstX >= result.width:
          continue
        let pixel = aseprite.asepritePixelAt(cel, y * cel.width + x)
        if pixel.a > 0:
          result[dstX, dstY] = pixel

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

type
  BakedFile = object
    name: string
    size: int
    sha256: string

proc writeBlob(name: string, data: string): BakedFile =
  let path = bakedDir / name
  writeFile(path, data)
  BakedFile(
    name: name,
    size: data.len,
    sha256: $secureHash(data))

proc imageToPaletteBytes(image: Image): string =
  ## Convert a Pixie ``Image`` to a row-major sequence of palette
  ## indices using the upstream ``nearestPaletteIndex`` (from
  ## ``bitworld/common/server``). Off-palette / transparent pixels
  ## come back as :data:`TransparentColorIndex` (255).
  result = newString(image.width * image.height)
  for y in 0 ..< image.height:
    for x in 0 ..< image.width:
      result[y * image.width + x] = char(nearestPaletteIndex(image[x, y]))

proc imageToAlphaMask(image: Image, alphaMin: uint8 = 20): string =
  ## Reduce an RGBA image to a 0/1 byte mask: 1 iff alpha >= ``alphaMin``.
  ## Walk and wall layers in skeld2.aseprite use any opaque pixel as
  ## "this tile is walkable / wall"; alpha threshold matches the
  ## upstream check (``a > 20``).
  result = newString(image.width * image.height)
  for y in 0 ..< image.height:
    for x in 0 ..< image.width:
      result[y * image.width + x] =
        if image[x, y].a >= alphaMin: '\1' else: '\0'

# ---------------------------------------------------------------------------
# Bake passes
# ---------------------------------------------------------------------------

proc bakePalette(): BakedFile =
  ## Emit the 16-entry palette as 48 RGB bytes in row-major order.
  ## Reads upstream ``Palette`` after ``loadPalette`` populated it.
  var buf = newString(Palette.len * 3)
  for i in 0 ..< Palette.len:
    buf[i * 3]     = char(Palette[i].r)
    buf[i * 3 + 1] = char(Palette[i].g)
    buf[i * 3 + 2] = char(Palette[i].b)
  writeBlob("palette.bin", buf)

proc bakeSprites(spritesheetPath: string): BakedFile =
  ## Slice the sprite atlas into the six 12×12 sprites guided_bot
  ## consumes, in :data:`SpriteColumns` order. Each sprite is encoded
  ## as palette-indexed bytes with ``TransparentColorIndex`` (=255)
  ## for transparency.
  # Prefer Aseprite because the live server renders from it; PNG exports
  # can lag behind upstream sprite edits.
  let img =
    if spritesheetPath.endsWith(".aseprite"):
      readAsepriteImage(spritesheetPath)
    else:
      readImage(spritesheetPath)
  doAssert img.height >= SpriteSize,
    spritesheetPath & " height " & $img.height & " < " & $SpriteSize
  let stride = SpriteSize * SpriteSize
  var buf = newString(SpriteColumns.len * stride)
  for slot, col in SpriteColumns:
    let x0 = col * SpriteSize
    if x0 + SpriteSize > img.width:
      raise newException(
        ValueError,
        &"spritesheet column {col} out of range; width={img.width}")
    for y in 0 ..< SpriteSize:
      for x in 0 ..< SpriteSize:
        let dst = slot * stride + y * SpriteSize + x
        buf[dst] = char(nearestPaletteIndex(img[x0 + x, y]))
  writeBlob("sprites.bin", buf)

proc bakeMapLayers(mapAsepritePath: string): tuple[
    pixels, walk, wall: BakedFile] =
  ## Render the three named layers of skeld2.aseprite. Layer indices
  ## come from the upstream ``map.json`` ``layers`` block:
  ## ``{map: 0, walk: 1, walls: 2}``. We pin those values rather than
  ## re-parsing the JSON because they have not moved upstream and
  ## hard-coding them here keeps this bake tool small.
  let aseprite = readAseprite(mapAsepritePath)
  doAssert aseprite.header.width == MapWidth,
    &"{mapAsepritePath} width {aseprite.header.width} != {MapWidth}"
  doAssert aseprite.header.height == MapHeight,
    &"{mapAsepritePath} height {aseprite.header.height} != {MapHeight}"

  let mapImage  = renderLayer(aseprite, 0)
  let walkImage = renderLayer(aseprite, 1)
  let wallImage = renderLayer(aseprite, 2)

  result = (
    pixels: writeBlob("map_pixels.bin", imageToPaletteBytes(mapImage)),
    walk:   writeBlob("walk_mask.bin",  imageToAlphaMask(walkImage)),
    wall:   writeBlob("wall_mask.bin",  imageToAlphaMask(wallImage)))

proc bakeFont(fontAsepritePath: string): BakedFile =
  ## Decode the variable-width pixel font and emit a compact binary.
  ## Format mirrors the loader in ``perception/data.nim``::
  ##
  ##   u8  height
  ##   u8  spacing
  ##   u16 (LE) glyph_count        # always PrintableAsciiCount = 95
  ##   for each glyph (in ASCII order, starting at FirstPrintableAscii):
  ##     u8 width
  ##     height*width bytes (0/1, row-major)
  ##
  ## Width 0 is allowed (placeholder glyphs for any printable codes the
  ## upstream font hasn't filled in); their pixel block is zero bytes.
  let font = readPixelFont(fontAsepritePath)
  doAssert font.height >= 1 and font.height <= 255,
    &"font height {font.height} out of u8 range"
  doAssert font.spacing >= 0 and font.spacing <= 255,
    &"font spacing {font.spacing} out of u8 range"

  var buf = ""
  buf.add char(font.height)
  buf.add char(font.spacing)
  buf.add char(PrintableAsciiCountBake and 0xff)
  buf.add char((PrintableAsciiCountBake shr 8) and 0xff)

  for code in FirstPrintableAsciiBake .. LastPrintableAsciiBake:
    let idx = code - FirstPrintableAsciiBake
    let g =
      if idx < font.glyphs.len:
        font.glyphs[idx]
      else:
        # Pad missing trailing glyphs with width-0 placeholders so the
        # baked file always carries exactly PrintableAsciiCount entries.
        PixelGlyph(ch: char(code), width: 0, height: font.height)
    doAssert g.width >= 0 and g.width <= 255,
      &"glyph '{chr(code)}' width {g.width} out of u8 range"
    doAssert g.height == font.height,
      &"glyph '{chr(code)}' height {g.height} != font height {font.height}"
    buf.add char(g.width)
    if g.width > 0:
      doAssert g.pixels.len == font.height * g.width,
        &"glyph '{chr(code)}' pixel buffer size mismatch"
      for px in g.pixels:
        buf.add (if px: '\1' else: '\0')

  writeBlob("font.bin", buf)

proc copyMapJson(srcPath: string): BakedFile =
  ## Copy the upstream ``map.json`` verbatim. The Nim runtime parses
  ## it at module load, so we keep it human-readable and re-loadable.
  let body = readFile(srcPath)
  writeBlob("map.json", body)

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

proc main() =
  if not dirExists(bitworldDir):
    stderr.writeLine &"FATAL: BITWORLD_DIR={bitworldDir} does not exist."
    stderr.writeLine "Set BITWORLD_DIR to your bitworld checkout root."
    quit(2)

  let palettePath  = bitworldDir / "clients" / "data" / "pallete.png"
  let mapJsonPath  = bitworldDir / "among_them" / "map.json"
  let mapAseprite  = bitworldDir / "among_them" / "skeld2.aseprite"
  let spritesAsepritePath = bitworldDir / "among_them" / "spritesheet.aseprite"
  let spritesPngPath = bitworldDir / "among_them" / "spritesheet.png"
  let spritesPath =
    if fileExists(spritesAsepritePath):
      spritesAsepritePath
    else:
      spritesPngPath
  let fontPath     = bitworldDir / "among_them" / "tiny5.aseprite"

  for label, path in {
      "palette": palettePath,
      "map.json": mapJsonPath,
      "skeld2.aseprite": mapAseprite,
      "spritesheet": spritesPath,
      "tiny5.aseprite": fontPath}.items:
    if not fileExists(path):
      stderr.writeLine &"FATAL: missing upstream {label} at {path}"
      quit(2)

  createDir(bakedDir)

  # Populate Palette[] before any nearestPaletteIndex call.
  loadPalette(palettePath)

  var entries: seq[BakedFile]
  entries.add bakePalette()
  entries.add bakeSprites(spritesPath)
  let layers = bakeMapLayers(mapAseprite)
  entries.add layers.pixels
  entries.add layers.walk
  entries.add layers.wall
  entries.add bakeFont(fontPath)
  entries.add copyMapJson(mapJsonPath)

  var manifest = %*{
    "schema_version": BakeSchemaVersion,
    "source": {
      "bitworld_dir": bitworldDir,
      "files": {
        "palette":         palettePath,
        "map_json":        mapJsonPath,
        "map_aseprite":    mapAseprite,
        "spritesheet":     spritesPath,
        "font_aseprite":   fontPath
      }
    },
    "screen": {"width": 128, "height": 128},
    "map": {"width": MapWidth, "height": MapHeight},
    "sprite": {
      "size": SpriteSize,
      "atlas_columns": @SpriteColumns,
      "transparent_index": 255
    },
    "files": []
  }
  for entry in entries:
    manifest["files"].add %*{
      "name": entry.name, "size": entry.size, "sha256": entry.sha256}
  writeFile(bakedDir / "manifest.json", manifest.pretty() & "\n")

  var total = 0
  for entry in entries:
    total += entry.size
  echo &"baked {entries.len} blobs ({total} bytes) to {bakedDir}"
  for entry in entries:
    echo &"  {entry.name:<18} {entry.size:>10} bytes"

when isMainModule:
  main()
