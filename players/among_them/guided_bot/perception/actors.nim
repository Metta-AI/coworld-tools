## Actor scanning. Phase 1.3.
##
## Port of ``modulabot/actors.py``'s orchestration. Reuses the Nim
## sprite-matching kernels in ``among_them/common/perception_kernels/``
## via direct relative imports — same sharing pattern as phase 1.2's
## ``localize.nim``. The kernels are pure Nim, stateless, and
## parity-pinned in modulabot's test suite.
##
## Scan pipeline (mirrors modulabot's ``scan_all`` ordering):
##
## 1. **Short-circuit** on interstitial frames — clear all lists, return.
## 2. ``updateRole`` — HUD ghost-icon / kill-button check.
## 3. ``updateSelfColor`` — single-anchor colour vote at player centre.
## 4. ``scanBodies`` — dead-crewmate sprites.
## 5. ``scanGhosts`` — ghost sprites.
## 6. ``scanCrewmates`` — living crewmates (excluding self).
##
## Task-icon and radar-dot scanning are deferred to phases 1.4.
##
## Results are written into ``ActorPercept`` (a sub-record of the
## ``Percept`` value), then merged into ``PerceptionState`` by
## ``belief.mergePercept``.
##
## The vectorised kernels ``mb_match_actor_sprite_all`` and
## ``mb_actor_color_index_all`` produce whole-frame boolean / index
## masks. The orchestration layer here extracts positive anchors,
## deduplicates them (greedy raster-order within a Chebyshev
## ``dedup_radius``), and runs per-anchor colour identification.

import std/algorithm

import ../constants
import ../types
import ../tuning
import data
import frame
import ignore

# Import shared kernels — qualified-only, same pattern as localize.nim.
from "../../common/perception_kernels/sprite_match" as kSpriteMatch import nil

# ---------------------------------------------------------------------------
# Constants — pinned to modulabot/actors.py
# ---------------------------------------------------------------------------

const
  ## Crewmate sprite-match budgets. Must match
  ## ``modulabot.sprite_match.CREWMATE_MAX_MISSES`` etc.
  CrewmateMaxMisses* = 8
  CrewmateMinStablePixels* = 8
  CrewmateMinBodyPixels* = 8

  ## Body (dead crewmate) sprite-match budgets.
  BodyMaxMisses* = 9
  BodyMinStablePixels* = 6
  BodyMinTintPixels* = 6

  ## Ghost sprite-match budgets.
  GhostMaxMisses* = 9
  GhostMinStablePixels* = 6
  GhostMinTintPixels* = 6

  ## HUD icon match budgets (scalar, not vectorised).
  GhostIconMaxMisses* = 3
  GhostIconFrameThreshold* = 2
  KillIconMaxMisses* = 5

  ## Dedup radius for anchor grouping. Same for all actor types.
  CrewmateSearchRadius* = 1
  BodySearchRadius* = 1
  GhostSearchRadius* = 1

  ## Screen-space kill-button / ghost-icon HUD anchor. Must match
  ## modulabot's ``KILL_ICON_X`` / ``KILL_ICON_Y`` and the server
  ## rendering at ``sim.nim:3490`` (``iconX = 1``,
  ## ``iconY = ScreenHeight - SpriteSize - 1``).
  KillIconX* = 1
  KillIconY* = ScreenHeight - SpriteSize - 1  ## = 115

  ## The server's playerView centers the camera on the drawn player sprite:
  ## sprite top-left is ``ScreenWidth/2 - SpriteSize/2`` and same for Y.
  ## Probe a tiny window around that anchor to tolerate odd dimensions or
  ## renderer drift without accidentally matching other actors.
  SelfColorSearchRadius* = 2

# Static asserts: kernel-side constants must agree with ours.
static:
  doAssert kSpriteMatch.ScreenWidth == ScreenWidth
  doAssert kSpriteMatch.ScreenHeight == ScreenHeight
  doAssert kSpriteMatch.PlayerColorCount == data.PaletteColorTableSize

# ---------------------------------------------------------------------------
# Output record (sub-percept for actors)
# ---------------------------------------------------------------------------

type
  ActorPercept* = object
    ## Structured output of one actor-scan pass. Populated by
    ## ``scanAll`` and consumed by the belief-merge stage.
    crewmates*: seq[CrewmateMatch]
    bodies*: seq[BodyMatch]
    ghosts*: seq[GhostMatch]
    ## Role / self-colour updates. ``roleUpdated`` is true when
    ## ``updateRole`` made a change this frame; the belief merge
    ## layer uses it to gate ``SelfState`` writes.
    roleUpdated*: bool
    newRole*: BotRole
    isGhost*: bool
    killReady*: bool
    ghostIconFrames*: int
    killIconFrames*: int
    selfColorUpdated*: bool
    newSelfColor*: int   ## Player-colour index or -1.

proc initActorPercept*(): ActorPercept =
  ActorPercept(
    crewmates: @[],
    bodies: @[],
    ghosts: @[],
    roleUpdated: false,
    newRole: RoleUnknown,
    isGhost: false,
    killReady: false,
    ghostIconFrames: 0,
    killIconFrames: 0,
    selfColorUpdated: false,
    newSelfColor: -1,
  )

# ---------------------------------------------------------------------------
# Vectorised scan backbone — wraps the shared kernels
# ---------------------------------------------------------------------------

proc matchMaskMaxDim(sprite: Sprite): tuple[maxY, maxX: int] {.inline.} =
  ## Match mask dimensions for a given sprite. The kernel writes a
  ## ``(maxY, maxX)`` 0/1 mask where maxY = 128 - sh + 1, maxX = 128 - sw + 1.
  (ScreenHeight - sprite.height + 1,
   ScreenWidth - sprite.width + 1)

proc runMatchKernel(
    frame: openArray[uint8],
    sprite: Sprite,
    flipH: bool,
    maxMisses, minStable, minTint: int,
    outMask: var seq[uint8]) =
  ## Call ``mb_match_actor_sprite_all`` for one sprite + flip combo.
  ## ``outMask`` is resized to ``maxY * maxX`` if needed.
  let (maxY, maxX) = matchMaskMaxDim(sprite)
  let needed = maxY * maxX
  if outMask.len < needed:
    outMask.setLen(needed)
  # Zero the mask — the kernel writes 1s at accepted anchors and 0s
  # elsewhere, but only if the sprite has enough stable/tint pixels;
  # the kernel may bail without touching the buffer.
  for i in 0 ..< needed:
    outMask[i] = 0'u8
  kSpriteMatch.mb_match_actor_sprite_all(
    cast[ptr UncheckedArray[uint8]](unsafeAddr frame[0]),
    cast[ptr UncheckedArray[uint8]](unsafeAddr sprite.pixels[0]),
    cint(sprite.height),
    cint(sprite.width),
    cint(if flipH: 1 else: 0),
    cint(maxMisses),
    cint(minStable),
    cint(minTint),
    cast[ptr UncheckedArray[uint8]](addr outMask[0]))

proc runColorKernel(
    frame: openArray[uint8],
    sprite: Sprite,
    flipH: bool,
    outIndices: var seq[int8]) =
  ## Call ``mb_actor_color_index_all`` for one sprite + flip combo.
  let (maxY, maxX) = matchMaskMaxDim(sprite)
  let needed = maxY * maxX
  if outIndices.len < needed:
    outIndices.setLen(needed)
  kSpriteMatch.mb_actor_color_index_all(
    cast[ptr UncheckedArray[uint8]](unsafeAddr frame[0]),
    cast[ptr UncheckedArray[uint8]](unsafeAddr sprite.pixels[0]),
    cint(sprite.height),
    cint(sprite.width),
    cint(if flipH: 1 else: 0),
    cast[ptr UncheckedArray[int8]](addr outIndices[0]))

# ---------------------------------------------------------------------------
# Deduplication — mirrors modulabot's ``_dedup_anchors``
# ---------------------------------------------------------------------------

type
  RawAnchor = tuple[y, x: int, flipH: bool]

proc dedupAnchors(anchors: var seq[RawAnchor], radius: int) =
  ## Greedy raster-order dedup. Keeps an anchor only if no
  ## already-kept anchor is within ``radius`` on both axes.
  ## Modifies ``anchors`` in-place, trimming duplicates.
  if anchors.len <= 1:
    return
  # Sort by (y, x) for raster-order priority.
  sort(anchors, proc(a, b: RawAnchor): int =
    if a.y != b.y: return a.y - b.y
    a.x - b.x)
  var kept: seq[RawAnchor] = @[]
  for a in anchors:
    var dup = false
    for k in kept:
      if abs(a.y - k.y) <= radius and abs(a.x - k.x) <= radius:
        dup = true
        break
    if not dup:
      kept.add a
  anchors = kept

# ---------------------------------------------------------------------------
# Generic actor scan — mirrors ``_scan_actor`` in modulabot/actors.py
# ---------------------------------------------------------------------------

proc scanActor(
    frame: openArray[uint8],
    sprite: Sprite,
    flips: openArray[bool],
    maxMisses, minStable, minTint, dedupRadius: int,
    ignoreCenter: bool,
    matchBuf: var seq[uint8]): seq[RawAnchor] =
  ## Core scan backbone. For each flip orientation, run the vectorised
  ## match kernel, extract positive anchors, apply self-centre
  ## exclusion if requested, then dedup.
  ##
  ## Flip priority: iterate flips in order; mark positions as claimed
  ## by the first flip that matches them. This mirrors modulabot's
  ## preference for unflipped first.
  let (maxY, maxX) = matchMaskMaxDim(sprite)
  var claimed = newSeq[bool](maxY * maxX)

  var anchors: seq[RawAnchor] = @[]

  for flip in flips:
    runMatchKernel(frame, sprite, flip,
                   maxMisses, minStable, minTint, matchBuf)

    # Optional self-centre exclusion (crewmates only). Zero out
    # anchors whose sprite centre falls within PlayerIgnoreRadius of
    # the player's rendered position.
    if ignoreCenter:
      let sprCentreOffX = sprite.width div 2
      let sprCentreOffY = sprite.height div 2
      for ay in 0 ..< maxY:
        for ax in 0 ..< maxX:
          if matchBuf[ay * maxX + ax] == 0'u8:
            continue
          let cx = ax + sprCentreOffX
          let cy = ay + sprCentreOffY
          if abs(cx - PlayerSpriteAnchorX) <= PlayerIgnoreRadius and
             abs(cy - PlayerSpriteAnchorY) <= PlayerIgnoreRadius:
            matchBuf[ay * maxX + ax] = 0'u8

    # Collect positive anchors not already claimed by a prior flip.
    for ay in 0 ..< maxY:
      for ax in 0 ..< maxX:
        let idx = ay * maxX + ax
        if matchBuf[idx] != 0'u8 and not claimed[idx]:
          claimed[idx] = true
          anchors.add (y: ay, x: ax, flipH: flip)

  dedupAnchors(anchors, dedupRadius)
  anchors

# ---------------------------------------------------------------------------
# Scalar sprite-match helpers (for HUD icons)
# ---------------------------------------------------------------------------

proc spriteMisses(
    frame: openArray[uint8],
    sprite: Sprite,
    x, y: int): tuple[misses, opaque: int] =
  ## Count misses and opaque pixels for one sprite at one anchor.
  ## Mirrors ``modulabot.sprite_match.sprite_misses``. Used for
  ## kill-button / ghost-icon HUD checks (single known position,
  ## not worth vectorising).
  var misses, opaque = 0
  for sy in 0 ..< sprite.height:
    for sx in 0 ..< sprite.width:
      let c = sprite.pixels[sy * sprite.width + sx]
      if c == TransparentIndex:
        continue
      inc opaque
      let fx = x + sx
      let fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        inc misses
      elif frame[fy * ScreenWidth + fx] != c:
        inc misses
  (misses, opaque)

proc matchesSprite(
    frame: openArray[uint8],
    sprite: Sprite,
    x, y: int): bool =
  ## Strict sprite match with max 4 misses (task-icon budget). Used
  ## for the lit kill-button check.
  let (m, o) = spriteMisses(frame, sprite, x, y)
  o > 0 and m <= 4

proc matchesSpriteShadowed(
    frame: openArray[uint8],
    sprite: Sprite,
    x, y: int): bool =
  ## Match the sprite's shadow-mapped variant. Used for the unlit
  ## (shadowed) kill-button check. Mirrors
  ## ``modulabot.sprite_match.matches_sprite_shadowed``.
  var misses = 0
  var opaque = 0
  for sy in 0 ..< sprite.height:
    for sx in 0 ..< sprite.width:
      let c = sprite.pixels[sy * sprite.width + sx]
      if c == TransparentIndex:
        continue
      inc opaque
      let sc = ShadowMap[c and 0x0F'u8]
      let fx = x + sx
      let fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        inc misses
      elif frame[fy * ScreenWidth + fx] != sc:
        inc misses
      if misses > KillIconMaxMisses:
        return false
  opaque > 0 and misses <= KillIconMaxMisses

proc isPlayerBodyColor(c: uint8): bool {.inline.} =
  ## True iff ``c`` is a plausible player-body colour (lit tint *or*
  ## its shadowed variant). Local copy of the kernel's helper.
  for pc in data.PlayerColors:
    if c == pc:
      return true
    if c == ShadowMap[pc and 0x0F'u8]:
      return true
  false

proc matchesCrewmate(
    frame: openArray[uint8],
    sprite: Sprite,
    x, y: int,
    flipH: bool): bool =
  ## Single-anchor crewmate match. Used only for ``updateSelfColor``
  ## (where we know the exact screen position). Mirrors
  ## ``modulabot.sprite_match.matches_crewmate``.
  var misses, matchedStable, bodyMatched = 0
  var stablePixels, bodyPixels = 0
  let sw = sprite.width
  let sh = sprite.height
  for sy in 0 ..< sh:
    for sx in 0 ..< sw:
      let srcX = if flipH: sw - 1 - sx else: sx
      let c = sprite.pixels[sy * sw + srcX]
      if c == TransparentIndex:
        continue
      let fx = x + sx
      let fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        inc misses
        if c == TintColor or c == ShadeTintColor:
          inc bodyPixels
        else:
          inc stablePixels
      else:
        let fc = frame[fy * ScreenWidth + fx]
        if c == TintColor or c == ShadeTintColor:
          inc bodyPixels
          if isPlayerBodyColor(fc):
            inc bodyMatched
          else:
            inc misses
        else:
          inc stablePixels
          if fc == c:
            inc matchedStable
          else:
            inc misses
      if misses > CrewmateMaxMisses:
        return false
  stablePixels >= CrewmateMinStablePixels and
    matchedStable >= CrewmateMinStablePixels and
    bodyPixels >= CrewmateMinBodyPixels and
    bodyMatched >= CrewmateMinBodyPixels

proc crewmateColorIndex(
    frame: openArray[uint8],
    sprite: Sprite,
    x, y: int,
    flipH: bool): int =
  ## Single-anchor colour vote. Only ``TintColor`` pixels vote (not
  ## ``ShadeTintColor``), matching the kernel's
  ## ``mb_actor_color_index_all``. Returns the argmax player-colour
  ## index or ``-1``.
  var counts: array[data.PaletteColorTableSize, int]
  let sw = sprite.width
  let sh = sprite.height
  for sy in 0 ..< sh:
    for sx in 0 ..< sw:
      let srcX = if flipH: sw - 1 - sx else: sx
      let c = sprite.pixels[sy * sw + srcX]
      if c != TintColor:
        continue
      let fx = x + sx
      let fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        continue
      let fc = frame[fy * ScreenWidth + fx]
      for i, pc in data.PlayerColors:
        if fc == pc:
          inc counts[i]
          break
  var best = -1
  var bestVotes = 0
  for i in 0 ..< data.PaletteColorTableSize:
    if counts[i] > bestVotes:
      bestVotes = counts[i]
      best = i
  best

# ---------------------------------------------------------------------------
# Public scan procs
# ---------------------------------------------------------------------------

proc updateRole*(
    percept: var ActorPercept,
    prevGhostIconFrames: int,
    prevKillIconFrames: int,
    prevRole: BotRole,
    sprites: Sprites,
    frame: openArray[uint8]) =
  ## Check the HUD icon slot for the ghost icon or kill button.
  ## Mirrors ``modulabot/actors.py::update_role``.
  ##
  ## Ghost detection requires ``GhostIconFrameThreshold`` consecutive
  ## frames with the icon present (debounce against transient
  ## occlusion). Kill-button role detection is also debounced:
  ## Unknown→Imposter needs a few consecutive HUD matches, and
  ## Crew→Imposter needs stronger evidence so one bad HUD match cannot
  ## override a CREWMATE role reveal.
  let ghostSprite = sprites.ghostIcon
  let (gMisses, gOpaque) = spriteMisses(frame, ghostSprite, KillIconX, KillIconY)

  if gOpaque > 0 and gMisses <= GhostIconMaxMisses:
    # Ghost icon present at the HUD slot.
    percept.ghostIconFrames = prevGhostIconFrames + 1
    percept.killIconFrames = 0
    percept.killReady = false
    if percept.ghostIconFrames >= GhostIconFrameThreshold:
      percept.isGhost = true
      percept.roleUpdated = true
      if prevRole == RoleUnknown:
        percept.newRole = RoleCrewmate
      else:
        percept.newRole = prevRole
    return

  percept.ghostIconFrames = 0

  # Check kill button (lit, then shadowed).
  let killSprite = sprites.killButton
  let litMatch = matchesSprite(frame, killSprite, KillIconX, KillIconY)
  let shadMatch = matchesSpriteShadowed(frame, killSprite, KillIconX, KillIconY)

  if litMatch or shadMatch:
    percept.killIconFrames = prevKillIconFrames + 1
    let requiredFrames = KillIconRoleFrames
    let stable = prevRole == RoleImposter or
                 percept.killIconFrames >= requiredFrames
    percept.killReady = litMatch and stable
    # Never override an OCR-confirmed crewmate role. The only path that
    # sets RoleCrewmate is OCR reading "CREWMATE" text — authoritative.
    # HUD sprite matching at (1,115) produces false positives when the
    # camera places map/task pixels at that position.
    if stable and prevRole == RoleUnknown:
      percept.roleUpdated = true
      percept.newRole = RoleImposter
  else:
    percept.killIconFrames = 0
    percept.killReady = false
    # Neither kill button nor ghost icon — crewmate by default.
    if prevRole == RoleUnknown:
      percept.roleUpdated = true
      percept.newRole = RoleCrewmate

proc updateSelfColor*(
    percept: var ActorPercept,
    sprites: Sprites,
    frame: openArray[uint8]) =
  ## Center-camera check at the known player screen position to determine
  ## our colour. Tries unflipped, then flipped, probing a tiny window around
  ## the canonical anchor. Mirrors the server's ``playerView`` camera math.
  let sprite = sprites.player
  let baseX = (ScreenWidth div 2) - (sprite.width div 2)
  let baseY = (ScreenHeight div 2) - (sprite.height div 2)
  for radius in 0 .. SelfColorSearchRadius:
    for dy in -radius .. radius:
      for dx in -radius .. radius:
        if abs(dx) != radius and abs(dy) != radius:
          continue
        let ax = baseX + dx
        let ay = baseY + dy
        for flip in [false, true]:
          if matchesCrewmate(frame, sprite, ax, ay, flip):
            let ci = crewmateColorIndex(frame, sprite, ax, ay, flip)
            if ci >= 0:
              percept.selfColorUpdated = true
              percept.newSelfColor = ci
              return

proc scanCrewmates*(
    percept: var ActorPercept,
    sprites: Sprites,
    frame: openArray[uint8],
    matchBuf: var seq[uint8],
    colorBuf: var seq[int8]) =
  ## Scan for living crewmates, excluding self. Mirrors
  ## ``modulabot/actors.py::scan_crewmates``.
  let sprite = sprites.player
  let anchors = scanActor(
    frame, sprite,
    flips = [false, true],
    maxMisses = CrewmateMaxMisses,
    minStable = CrewmateMinStablePixels,
    minTint = CrewmateMinBodyPixels,
    dedupRadius = CrewmateSearchRadius,
    ignoreCenter = true,
    matchBuf = matchBuf)

  for a in anchors:
    let ci = crewmateColorIndex(frame, sprite, a.x, a.y, a.flipH)
    percept.crewmates.add CrewmateMatch(
      x: a.x, y: a.y, colorIndex: ci, flipH: a.flipH)

proc scanBodies*(
    percept: var ActorPercept,
    sprites: Sprites,
    frame: openArray[uint8],
    matchBuf: var seq[uint8],
    colorBuf: var seq[int8]) =
  ## Scan for dead crewmate bodies. Mirrors
  ## ``modulabot/actors.py::scan_bodies``. Bodies don't flip.
  let sprite = sprites.body
  let anchors = scanActor(
    frame, sprite,
    flips = [false],
    maxMisses = BodyMaxMisses,
    minStable = BodyMinStablePixels,
    minTint = BodyMinTintPixels,
    dedupRadius = BodySearchRadius,
    ignoreCenter = false,
    matchBuf = matchBuf)

  for a in anchors:
    let ci = crewmateColorIndex(frame, sprite, a.x, a.y, false)
    percept.bodies.add BodyMatch(
      x: a.x, y: a.y, colorIndex: ci)

proc scanGhosts*(
    percept: var ActorPercept,
    sprites: Sprites,
    frame: openArray[uint8],
    matchBuf: var seq[uint8]) =
  ## Scan for ghost sprites. Mirrors
  ## ``modulabot/actors.py::scan_ghosts``. No colour index extracted
  ## (ghosts are translucent).
  let sprite = sprites.ghost
  let anchors = scanActor(
    frame, sprite,
    flips = [false, true],
    maxMisses = GhostMaxMisses,
    minStable = GhostMinStablePixels,
    minTint = GhostMinTintPixels,
    dedupRadius = GhostSearchRadius,
    ignoreCenter = false,
    matchBuf = matchBuf)

  for a in anchors:
    percept.ghosts.add GhostMatch(
      x: a.x, y: a.y, flipH: a.flipH)

# ---------------------------------------------------------------------------
# Scratch state — reusable buffers to avoid per-frame allocs
# ---------------------------------------------------------------------------

type
  ActorScanner* = object
    ## Per-bot scratch for the actor scan pass. Holds reusable
    ## buffers so ``scanAll`` doesn't allocate on every frame.
    matchBuf*: seq[uint8]
    colorBuf*: seq[int8]

proc initActorScanner*(): ActorScanner =
  ActorScanner(matchBuf: @[], colorBuf: @[])

# ---------------------------------------------------------------------------
# Role-reveal imposter detection
# ---------------------------------------------------------------------------

proc scanRoleRevealImposters*(
    scanner: var ActorScanner,
    sprites: Sprites,
    frame: openArray[uint8]): seq[int] =
  ## Detect imposter player colors from the role-reveal interstitial.
  ##
  ## Strategy: palette histogram. We know the IMPS screen is black
  ## background + "IMPS" text (palette 2) + N imposter sprites. Each
  ## sprite has exactly:
  ##   40 TintColor pixels → replaced by the player's palette color
  ##    5 ShadeTintColor pixels → replaced by ShadowMap[player_color]
  ##   60 outline pixels (palette 0, same as background)
  ##    8 eye/white pixels (palette 2)
  ##   10 visor pixels (palette 14)
  ##
  ## For each player color slot (0-7), check if its palette index has
  ## significantly more pixels than the stable contribution alone. The
  ## one collision is player slot 3 (palette 14 = visor color): we
  ## handle that by checking if palette-14 count exceeds the expected
  ## visor contribution (10 per sprite on screen).
  result = @[]
  let sprite = sprites.player

  # Count stable pixels per palette value in the sprite template.
  # This gives us the known fixed contribution per sprite.
  var stableCount: array[16, int]
  for i in 0 ..< sprite.width * sprite.height:
    let px = sprite.pixels[i]
    if px != TransparentIndex and px != TintColor and px != ShadeTintColor:
      if px <= 15:
        inc stableCount[px]

  # Count all palette index occurrences in the frame.
  var frameCount: array[16, int]
  for px in frame:
    inc frameCount[px and 0x0F]

  # Estimate how many sprites are on screen from non-black pixel total.
  # Each sprite contributes ~63 non-black opaque pixels (123 opaque - 60
  # black outline). Text adds ~50 pixels (white, palette 2).
  let nonBlack = FrameLen - frameCount[0]
  let estSprites = max(1, (nonBlack - 50) div 63)

  # Body tint is 40 pixels per sprite. Require at least half a body
  # (~20 pixels) above the stable contribution to count as present.
  const TintBodyPixels = 40
  const BodyThreshold = 20

  for i in 0 ..< PlayerColorCount:
    let pc = PlayerColors[i]
    let count = frameCount[pc]
    if count == 0:
      continue
    # Expected stable pixels of this palette index from all sprites.
    let stableContrib = stableCount[pc] * estSprites
    # For the visor collision (palette 14 = player slot 3 "light blue"):
    # stableCount[14] = 10, so stableContrib = 10 * estSprites.
    # A light-blue imposter adds 40 MORE pixels of palette 14.
    # Threshold of 20 catches this: 10*2 = 20 stable, actual = 60,
    # excess = 40 > 20. Works for any number of sprites.
    if count > stableContrib + BodyThreshold:
      result.add i

# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

proc scanAll*(
    scanner: var ActorScanner,
    prevPerception: PerceptionState,
    prevSelfState: SelfState,
    sprites: Sprites,
    frame: openArray[uint8],
    isInterstitial: bool): ActorPercept =
  ## Run the full actor scan pipeline for one frame. Mirrors
  ## ``modulabot/actors.py::scan_all`` ordering. Short-circuits on
  ## interstitials. Returns an ``ActorPercept`` for the belief merge
  ## to consume.
  ##
  ## Caller passes the *previous* frame's ``PerceptionState`` and
  ## ``SelfState`` so role detection can persist the ghost-icon
  ## frame counter and the known role across frames.
  result = initActorPercept()

  if isInterstitial:
    # Preserve ghost-icon frame counter through interstitials so
    # the debounce isn't reset by a brief black gap.
    result.ghostIconFrames = prevPerception.ghostIconFrames
    result.killIconFrames = 0
    return

  # 1. Role detection (HUD ghost icon / kill button).
  updateRole(
    result,
    prevPerception.ghostIconFrames,
    prevPerception.killIconFrames,
    prevSelfState.role,
    sprites,
    frame)

  # 2. Self-colour detection.
  updateSelfColor(result, sprites, frame)

  # 3. Bodies first (modulabot ordering).
  scanBodies(result, sprites, frame, scanner.matchBuf, scanner.colorBuf)

  # 4. Ghosts.
  scanGhosts(result, sprites, frame, scanner.matchBuf)

  # 5. Crewmates (excluding self via ignore_center).
  scanCrewmates(result, sprites, frame, scanner.matchBuf, scanner.colorBuf)
