## Dynamic-pixel ignore mask. Phase 1.0 scaffolding + phase 1.3
## actor-exclusion extensions.
##
## Camera localization scores the frame against the static map pixel-
## for-pixel; anything on screen that isn't map (player sprite, other
## crewmates, bodies, ghosts, task icons, radar dots, HUD icons) must
## be masked out or it inflates the error count and sends the
## localizer off-target. See `how_to_make_a_bot.md` § "What To Ignore
## During Map Matching".
##
## This module builds that mask. Phase 1.0 populates the always-
## present components (the centred-player zone + the radar palette
## colour). Phase 1.3 stamps per-sprite exclusions for every
## crewmate / body / ghost the actor scanners found. Phase 1.4
## adds HUD icons (kill button / ghost icon) and task icons.
##
## The mask's representation (`IgnoreMask` in `perception/frame.nim`)
## is a flat `seq[uint8]` so the phase-1.2 localizer can hand it to
## the `nim_perception` kernels directly (`ptr UncheckedArray[uint8]`)
## with no conversion.

import ../constants
import ../types
import frame

const
  ## Half-extent (in screen pixels) of the centred player-sprite
  ## exclusion zone. Matches modulabot's `PLAYER_IGNORE_RADIUS = 9`
  ## in both the Python port and the original Nim upstream.
  PlayerIgnoreRadius* = 9

  ## Screen coordinates where the player's sprite is **rendered**
  ## (used to anchor the ignore-mask exclusion zone). Distinct from
  ## the geometry module's :data:`PlayerScreenX` /
  ## :data:`PlayerScreenY`, which name the player's *collision-box
  ## centre* — the two are off by one in X and four in Y because the
  ## player sprite's drawn anchor is offset from its hit-box centre.
  ## Matches modulabot's ``PLAYER_SCREEN_X`` / ``PLAYER_SCREEN_Y`` in
  ## ``modulabot/frame.py`` (renamed here only to avoid the symbol
  ## clash with ``perception/geometry.nim``; values are unchanged).
  PlayerSpriteAnchorX* = (ScreenWidth div 2) - 1
  PlayerSpriteAnchorY* = (ScreenHeight div 2) - 4

  ## Palette index of radar dots (offscreen-task pointers drawn at
  ## the screen edge). The bitworld palette assigns yellow here.
  ## Matches `RADAR_TASK_COLOR = 8` in the Python port.
  RadarTaskColor* = 8'u8

proc stampPlayerCentreZone*(mask: var IgnoreMask) =
  ## Stamp the always-on player-sprite exclusion zone: a
  ## `(2*PlayerIgnoreRadius+1)`-square block centred on the player's
  ## rendered position.
  let yLo = max(0, PlayerSpriteAnchorY - PlayerIgnoreRadius)
  let yHi = min(ScreenHeight - 1, PlayerSpriteAnchorY + PlayerIgnoreRadius)
  let xLo = max(0, PlayerSpriteAnchorX - PlayerIgnoreRadius)
  let xHi = min(ScreenWidth - 1, PlayerSpriteAnchorX + PlayerIgnoreRadius)
  for y in yLo .. yHi:
    let row = y * ScreenWidth
    for x in xLo .. xHi:
      mask.data[row + x] = 1'u8

proc stampRadarPixels*(mask: var IgnoreMask, frame: openArray[uint8]) =
  ## Stamp every pixel whose colour is `RadarTaskColor`. This is a
  ## whole-frame scan but in the phase-1 pipeline it's cheap — 16 384
  ## byte comparisons with no memory indirection.
  doAssert frame.len == FrameLen,
    "stampRadarPixels: frame.len (" & $frame.len & ") != FrameLen"
  for i in 0 ..< FrameLen:
    if frame[i] == RadarTaskColor:
      mask.data[i] = 1'u8

proc stampSpriteRect*(mask: var IgnoreMask, x, y, w, h: int) =
  ## Stamp a rectangular sprite bounding box into the ignore mask.
  ## Used by phase 1.3 actor exclusions to mask out detected
  ## crewmate / body / ghost sprites so a subsequent localize pass
  ## (or phase 1.4 refinements) isn't confused by their pixels.
  let yLo = max(0, y)
  let yHi = min(ScreenHeight - 1, y + h - 1)
  let xLo = max(0, x)
  let xHi = min(ScreenWidth - 1, x + w - 1)
  for py in yLo .. yHi:
    let row = py * ScreenWidth
    for px in xLo .. xHi:
      mask.data[row + px] = 1'u8

const
  ## Nameplate geometry. The Among Them server renders each player's
  ## name above its sprite using the PICO-8 font (~5px tall, ~4px
  ## per glyph + 1px spacing). Nameplates are centred horizontally
  ## on the sprite and drawn a few pixels above the sprite's top
  ## edge. We use generous margins so variable-length names and
  ## slight vertical jitter are covered.
  NameplateHeight* = 7     ## px above sprite top to cover text + gap.
  NameplateHalfWidth* = 40 ## px to each side of sprite centre.
                            ## Covers names up to ~20 chars.

proc stampNameplateRect*(mask: var IgnoreMask, spriteX, spriteY, spriteW: int) =
  ## Stamp a rectangular nameplate exclusion zone above a detected
  ## actor sprite. The zone is centred on the sprite and extends
  ## upward to cover the player-name text the server renders.
  let cx = spriteX + spriteW div 2
  let xLo = max(0, cx - NameplateHalfWidth)
  let xHi = min(ScreenWidth - 1, cx + NameplateHalfWidth)
  let yHi = max(0, spriteY - 1)
  let yLo = max(0, spriteY - NameplateHeight)
  for py in yLo .. yHi:
    let row = py * ScreenWidth
    for px in xLo .. xHi:
      mask.data[row + px] = 1'u8

proc buildPhase10IgnoreMask*(
    maskOut: var IgnoreMask,
    frame: openArray[uint8]) =
  ## Compose the phase-1.0 ignore mask for one frame.
  ##
  ## Components included:
  ##   - Always-on player-centre zone.
  ##   - Radar-colour pixels.
  ##
  ## Components deliberately missing until later sub-phases:
  ##   - Other crewmates / bodies / ghosts  (phase 1.3)
  ##   - Task-icon rectangles               (phase 1.4)
  ##   - Kill-button / ghost HUD icons      (phase 1.4)
  ##
  ## Callers that need the full mask should not use this helper;
  ## they should call the phase-1.4 `buildIgnoreMask` (not yet
  ## implemented) that consumes the scan results.
  maskOut.clear()
  stampPlayerCentreZone(maskOut)
  stampRadarPixels(maskOut, frame)
