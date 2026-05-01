## Frame-level primitives: bit-unpacking and palette-indexed frame
## helpers. Phase 1.0.
##
## Split out of `perception.nim` so per-concern perception modules
## (frame / interstitial / ignore / localize / actors / tasks / voting)
## live side-by-side under `perception/`, mirroring the bitworld
## modulabot layout. This keeps the top-level agent dir tidy and makes
## it obvious where a new perception helper belongs.
##
## None of the procs here depend on map or sprite data. Everything
## needing baked assets lives in `perception/data.nim` (phase 1.1).

import ../constants

# ---------------------------------------------------------------------------
# 4-bpp unpacking
# ---------------------------------------------------------------------------

proc unpack4bpp*(packed: openArray[uint8], dst: var openArray[uint8]) =
  ## Expand the 4-bit packed wire-format frame the BitWorld server
  ## sends into one palette-index byte per pixel. Two pixels per
  ## source byte: low nybble then high nybble, row-major.
  ##
  ## Preconditions:
  ##   - `packed.len == FrameLen div 2`  (`8192` for a 128×128 frame).
  ##   - `dst.len   == FrameLen`         (`16384`).
  ##
  ## A mismatched length is a caller bug; we check and fail loudly
  ## rather than silently truncating.
  doAssert packed.len * 2 == dst.len,
    "unpack4bpp: packed.len*2 (" & $(packed.len * 2) &
      ") != dst.len (" & $dst.len & ")"
  for i in 0 ..< packed.len:
    let b = packed[i]
    dst[i * 2]     = b and 0x0f'u8
    dst[i * 2 + 1] = (b shr 4) and 0x0f'u8

proc unpack4bpp*(packed: openArray[uint8]): seq[uint8] =
  ## Allocating convenience wrapper. Prefer the in-place form on hot
  ## paths; this one allocates a fresh buffer each call.
  result = newSeq[uint8](packed.len * 2)
  unpack4bpp(packed, result)

# ---------------------------------------------------------------------------
# Cheap whole-frame statistics
# ---------------------------------------------------------------------------

proc blackPixelCount*(frame: openArray[uint8]): int =
  ## Count pixels with palette index 0 (black in the PICO-8 palette
  ## bitworld uses). Foundational input to the interstitial detector
  ## in `perception/interstitial.nim`.
  ##
  ## Kept in this module because it's a per-pixel primitive; it has
  ## no notion of what "interstitial" means — that classification is
  ## one level up.
  result = 0
  for c in frame:
    if c == 0'u8: inc result

proc pixelAt*(frame: openArray[uint8], x, y: int): uint8 {.inline.} =
  ## Safe indexed access with bounds check; returns 0 (the
  ## `MapVoidColor` sentinel, conveniently) for any OOB access. Used
  ## by ignore-mask builders and future sprite matchers so they don't
  ## have to re-derive the ScreenWidth offset math.
  if x < 0 or x >= ScreenWidth or y < 0 or y >= ScreenHeight:
    return 0'u8
  frame[y * ScreenWidth + x]

# ---------------------------------------------------------------------------
# Ignore-mask support
# ---------------------------------------------------------------------------

type
  IgnoreMask* = object
    ## A 128×128 0/1 mask of "skip-this-pixel" flags, matching the
    ## Python implementation's :class:`numpy.ndarray` of shape
    ## `(128, 128)` bool and the Nim kernel's
    ## `ptr UncheckedArray[uint8]` form. Phase 1.0 uses only the
    ## always-on components (player-centre zone + radar colour);
    ## phases 1.3 / 1.4 stamp per-sprite exclusions on top.
    ##
    ## Stored as a flat seq so it can be handed to the nim_perception
    ## kernels in phase 1.2 without a conversion step.
    data*: seq[uint8]

proc initIgnoreMask*(): IgnoreMask =
  IgnoreMask(data: newSeq[uint8](FrameLen))

proc clear*(mask: var IgnoreMask) =
  for i in 0 ..< mask.data.len:
    mask.data[i] = 0'u8

proc setBit*(mask: var IgnoreMask, x, y: int) {.inline.} =
  if x < 0 or x >= ScreenWidth or y < 0 or y >= ScreenHeight: return
  mask.data[y * ScreenWidth + x] = 1'u8

proc isSet*(mask: IgnoreMask, x, y: int): bool {.inline.} =
  if x < 0 or x >= ScreenWidth or y < 0 or y >= ScreenHeight: return false
  mask.data[y * ScreenWidth + x] != 0'u8

proc countSet*(mask: IgnoreMask): int =
  ## Diagnostic helper used by tests.
  for b in mask.data:
    if b != 0'u8: inc result
