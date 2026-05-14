## Pixel-font OCR. Phase 1.5.
##
## Wraps ``mb_best_glyph`` and ``mb_text_matches`` from
## ``among_them/common/perception_kernels/ocr.nim``. Adds a pure-Nim
## ``findText`` (full-frame sweep for interstitial banner detection)
## and ``classifyInterstitial`` for refining ``InterstitialKind``.
##
## The baked font data from ``data.nim`` is repacked into the flat
## arrays the kernels expect (one-time init at module load).
##
## Phase 1.6 (voting) consumes ``textMatches``, ``bestGlyph``, and
## ``readRun`` for SKIP-label detection and chat-line OCR.

import ../constants
import ../types
import data
import frame

# Import shared OCR kernel — qualified-only.
from "../../common/perception_kernels/ocr" as kOcr import nil

# ---------------------------------------------------------------------------
# Packed font — flat arrays the kernels expect
# ---------------------------------------------------------------------------

type
  PackedFont* = object
    ## Flat representation consumed by ``mb_best_glyph`` and
    ## ``mb_text_matches``. Built once from ``referenceData.font``.
    pixels*: seq[uint8]       ## (numGlyphs * height * maxWidth) 0/1
    widths*: seq[int32]       ## (numGlyphs,)
    opaque*: seq[int32]       ## (numGlyphs,) total foreground pixels
    preferences*: seq[int32]  ## (numGlyphs,) tie-break score
    numGlyphs*: int
    height*: int
    maxWidth*: int
    spacing*: int

proc glyphPreference(ch: char): int32 =
  ## Tie-break preference per glyph character. Matches
  ## modulabot's ``_glyph_preference``: lowercase > digits >
  ## uppercase > space > everything else.
  if ch >= 'a' and ch <= 'z': return 4
  if ch >= '0' and ch <= '9': return 3
  if ch >= 'A' and ch <= 'Z': return 2
  if ch == ' ': return 1
  return 0

proc packFont(font: PixelFont): PackedFont =
  ## Convert the structured ``PixelFont`` into the flat kernel format.
  let n = PrintableAsciiCount
  let h = font.height
  # Find max width across all glyphs.
  var mw = 0
  for i in 0 ..< n:
    if font.glyphs[i].width > mw:
      mw = font.glyphs[i].width
  let stride = h * mw
  var pixels = newSeq[uint8](n * stride)
  var widths = newSeq[int32](n)
  var opaq = newSeq[int32](n)
  var prefs = newSeq[int32](n)
  for i in 0 ..< n:
    let g = font.glyphs[i]
    widths[i] = int32(g.width)
    prefs[i] = glyphPreference(g.ch)
    var count: int32 = 0
    for row in 0 ..< h:
      for col in 0 ..< g.width:
        let v = g.pixels[row * g.width + col]
        pixels[i * stride + row * mw + col] = v
        if v != 0: inc count
    opaq[i] = count
  PackedFont(
    pixels: pixels, widths: widths, opaque: opaq,
    preferences: prefs, numGlyphs: n,
    height: h, maxWidth: mw, spacing: font.spacing)

# Module-level cache.
var packedFontCache: PackedFont
var packedFontBuilt: bool = false

proc getPackedFont*(): lent PackedFont =
  if not packedFontBuilt:
    packedFontCache = packFont(referenceData.font)
    packedFontBuilt = true
  packedFontCache

# ---------------------------------------------------------------------------
# Text → glyph-index conversion
# ---------------------------------------------------------------------------

proc textToIndices(text: string): seq[int32] =
  ## Convert a string to an array of glyph indices for the kernel.
  ## ``-1`` encodes newline.
  result = newSeq[int32](text.len)
  for i in 0 ..< text.len:
    let ch = text[i]
    if ch == '\n':
      result[i] = -1'i32
    else:
      let c = ord(ch)
      if c < FirstPrintableAscii or c > LastPrintableAscii:
        result[i] = int32(ord('?') - FirstPrintableAscii)
      else:
        result[i] = int32(c - FirstPrintableAscii)

# ---------------------------------------------------------------------------
# Kernel wrappers
# ---------------------------------------------------------------------------

proc textMatches*(
    frame: openArray[uint8],
    text: string,
    x, y: int,
    maxErrors: int = 0,
    background: uint8 = SpaceColor): bool =
  ## Check if ``text`` renders at ``(x, y)`` within error budget.
  ## Dispatches to ``mb_text_matches``.
  let pf = getPackedFont()
  let indices = textToIndices(text)
  if indices.len == 0: return false
  var matched: cint = 0
  var errors: cint = 0
  var opaque: cint = 0
  kOcr.mb_text_matches(
    cast[ptr UncheckedArray[uint8]](unsafeAddr frame[0]),
    cast[ptr UncheckedArray[uint8]](unsafeAddr pf.pixels[0]),
    cast[ptr UncheckedArray[int32]](unsafeAddr pf.widths[0]),
    cint(pf.height), cint(pf.maxWidth), cint(pf.spacing),
    cast[ptr UncheckedArray[int32]](unsafeAddr indices[0]),
    cint(indices.len),
    cint(x), cint(y), cint(maxErrors), cint(background),
    addr matched, addr errors, addr opaque)
  matched != 0

proc bestGlyph*(
    frame: openArray[uint8],
    x, y: int,
    maxErrors: int = 0,
    background: uint8 = SpaceColor): tuple[ch: char, errors: int, advance: int] =
  ## Pick the best-matching glyph at ``(x, y)``.
  ## Returns ``('?', high, 0)`` if nothing clears ``maxErrors``.
  let pf = getPackedFont()
  var glyphIdx: cint = -1
  var errors: cint = 0
  var advance: cint = 0
  kOcr.mb_best_glyph(
    cast[ptr UncheckedArray[uint8]](unsafeAddr frame[0]),
    cast[ptr UncheckedArray[uint8]](unsafeAddr pf.pixels[0]),
    cast[ptr UncheckedArray[int32]](unsafeAddr pf.widths[0]),
    cast[ptr UncheckedArray[int32]](unsafeAddr pf.opaque[0]),
    cast[ptr UncheckedArray[int32]](unsafeAddr pf.preferences[0]),
    cint(pf.numGlyphs), cint(pf.height), cint(pf.maxWidth),
    cint(pf.spacing),
    cint(x), cint(y), cint(maxErrors), cint(background),
    addr glyphIdx, addr errors, addr advance)
  if glyphIdx < 0:
    return ('?', int(errors), 0)
  let ch = chr(FirstPrintableAscii + int(glyphIdx))
  (ch, int(errors), int(advance))

# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

proc readRun*(
    frame: openArray[uint8],
    x, y: int,
    count: int,
    maxErrors: int = 0,
    background: uint8 = SpaceColor,
    strip: bool = true): string =
  ## Read ``count`` variable-width glyphs starting at ``(x, y)``.
  ## Mirrors ``modulabot.ascii.read_run``.
  var penX = x
  var buf = ""
  let pf = getPackedFont()
  for _ in 0 ..< count:
    let (ch, _, adv) = bestGlyph(frame, penX, y, maxErrors, background)
    buf.add ch
    if adv > 0:
      penX += adv
    else:
      # Unknown glyph — advance by the average width to avoid stuck loop.
      penX += pf.maxWidth + pf.spacing
  if strip:
    # Strip leading/trailing whitespace.
    var lo = 0
    while lo < buf.len and buf[lo] == ' ': inc lo
    var hi = buf.len - 1
    while hi >= lo and buf[hi] == ' ': dec hi
    if lo > hi: return ""
    return buf[lo .. hi]
  buf

proc readLineStrict*(
    frame: openArray[uint8],
    y: int,
    maxErrors: int = 0,
    background: uint8 = SpaceColor): string =
  ## Read a line of text starting from the first non-background pixel
  ## on row ``y``. Scans only row ``y`` (strict, matching Nim upstream).
  ## Returns empty string if no text found.
  var startX = -1
  for x in 0 ..< ScreenWidth:
    if frame[y * ScreenWidth + x] != background:
      startX = x
      break
  if startX < 0: return ""
  readRun(frame, startX, y, 32, maxErrors, background)

# ---------------------------------------------------------------------------
# findText — full-frame sweep for interstitial banners
# ---------------------------------------------------------------------------

proc findText*(
    frame: openArray[uint8],
    text: string,
    maxErrors: int = 0,
    background: uint8 = SpaceColor): tuple[found: bool, x, y: int] =
  ## Search the entire 128×128 frame for the first position where
  ## ``text`` matches. Pure Nim — no numpy sliding-window needed.
  ##
  ## Returns ``(found=false, 0, 0)`` on miss. Scans in raster order
  ## (y-major, x-minor) so the first match is the top-leftmost.
  ##
  ## Performance: each candidate runs ``mb_text_matches`` which
  ## early-exits on the first over-budget glyph. Typical interstitial
  ## banners (5-8 chars centred on the screen) have one correct
  ## anchor out of ~16K candidates; the vast majority reject in the
  ## first few pixels. Expected cost <2 ms.
  let pf = getPackedFont()
  let indices = textToIndices(text)
  if indices.len == 0: return (false, 0, 0)

  # Compute text render width to bound the X sweep.
  var textW = 0
  for i in 0 ..< indices.len:
    let idx = int(indices[i])
    if idx < 0: continue  # newline
    if idx < pf.numGlyphs:
      textW += int(pf.widths[idx]) + pf.spacing
  let maxX = ScreenWidth - textW + pf.spacing  # allow partial last glyph
  let maxY = ScreenHeight - pf.height

  for y in 0 .. maxY:
    for x in 0 .. max(0, maxX):
      if textMatches(frame, text, x, y, maxErrors, background):
        return (true, x, y)
  (false, 0, 0)

# ---------------------------------------------------------------------------
# Interstitial classification
# ---------------------------------------------------------------------------

const
  ## Known interstitial banner strings and their classification.
  ## Searched in this order; first match wins. Longer strings are
  ## checked first to avoid partial matches (e.g. "IMPS" inside
  ## "IMPS WIN").
  InterstitialBanners*: array[5, tuple[text: string, kind: InterstitialKind]] = [
    ("CREW WINS", InterstitialGameOver),
    ("CREW WIN", InterstitialGameOver),
    ("IMPS WIN", InterstitialGameOver),
    ("CREWMATE", InterstitialRoleRevealCrewmate),
    ("IMPS", InterstitialRoleRevealImposter),
  ]

proc countColorInRect(
    frame: openArray[uint8],
    x0, y0, w, h: int,
    color: uint8): int =
  for y in max(0, y0) ..< min(ScreenHeight, y0 + h):
    for x in max(0, x0) ..< min(ScreenWidth, x0 + w):
      if frame[y * ScreenWidth + x] == color:
        inc result

proc looksLikeGameOverSummary(frame: openArray[uint8]): bool =
  ## The live game-over screen uses the server's 7px ASCII font, while the
  ## current OCR font is 6px tall. Detect the stable summary layout directly:
  ## a top white title plus role labels in the vertical player list.
  let titleWhite = countColorInRect(frame, 20, 2, 89, 9, 2'u8)
  var roleWhite = 0
  for y in [20, 34, 48, 62, 76, 90, 104, 118]:
    roleWhite += countColorInRect(frame, 19, y, 36, 8, 2'u8)
  titleWhite >= 50 and roleWhite >= 80

proc classifyInterstitial*(
    frame: openArray[uint8],
    maxErrors: int = 2): InterstitialKind =
  ## Attempt to classify an interstitial frame by scanning for known
  ## banner text. Returns ``InterstitialUnknown`` if no banner matches.
  ##
  ## Called only on frames already classified as interstitial by the
  ## black-pixel detector (phase 1.0). The error budget is generous
  ## (2 mismatches per banner) to handle slight rendering variations.
  for banner in InterstitialBanners:
    let (found, _, _) = findText(frame, banner.text, maxErrors)
    if found:
      return banner.kind
  if looksLikeGameOverSummary(frame):
    return InterstitialGameOver
  InterstitialUnknown
