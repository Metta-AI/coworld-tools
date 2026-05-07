## Voting-screen parse. Phase 1.6.
##
## Ports the core of ``modulabot/voting.py``: grid layout, slot parsing
## (sprite match for alive/dead + colour), cursor detection, self-marker,
## vote-dot parsing, SKIP text check, chat OCR with speaker attribution.
##
## The parse is invoked on interstitial frames to detect whether the
## frame is a voting screen. If it parses successfully, the
## ``InterstitialKind`` is refined to ``InterstitialVoting`` and the
## ``VotingParse`` result is merged into the belief.
##
## Sprite matching for slot parsing reuses the same kernels as
## ``perception/actors.nim`` (scalar ``matchesCrewmate`` / colour
## detection). Chat OCR reuses ``perception/ocr.nim``.

import ../constants
import ../types
import data
import frame
import ocr

# ---------------------------------------------------------------------------
# Constants — pinned to modulabot/voting.py
# ---------------------------------------------------------------------------

const
  VoteCellW* = 16
  VoteCellH* = 17
  VoteStartY* = 2
  VoteSkipW* = 28
  VoteSkipTextH = 8
  VoteSkipMinTextPixels = 35
  MaxPlayers* = 16

  VoteUnknown* = -1
  VoteSkip* = -2

  CursorColor* = 2'u8      ## PICO-8 white — cursor outline.
  TextBackground* = 0'u8   ## Black background for OCR.
  VoteBlackMarker* = 12'u8 ## Dark navy for black-player marker shadow.

  VoteChatIconX* = 1
  VoteChatTextX* = 14       ## 1 + SpriteSize + 1
  VoteCharsPerLine* = 32
  VoteChatSpeakerSearch* = 24

  ## Sprite-match budgets for body detection in vote slots.
  BodyMaxMisses = 9
  BodyMinStable = 6
  BodyMinTint = 6

  ## Crewmate match budgets (reused from actors).
  CrewmateMaxMisses = 8
  CrewmateMinStable = 8
  CrewmateMinBody = 8

# ---------------------------------------------------------------------------
# Grid layout
# ---------------------------------------------------------------------------

type
  VoteGridLayout* = object
    cols*, rows*: int
    startX*: int
    skipX*, skipY*: int

proc voteGridLayout*(count: int): VoteGridLayout =
  let cols = min(count, 8)
  let rows = if cols == 0: 0 else: (count + cols - 1) div cols
  let startX = (ScreenWidth - cols * VoteCellW) div 2
  let skipX = (ScreenWidth - VoteSkipW) div 2
  let skipY = VoteStartY + rows * VoteCellH + 1
  VoteGridLayout(cols: cols, rows: rows, startX: startX,
                 skipX: skipX, skipY: skipY)

proc voteCellOrigin*(layout: VoteGridLayout, count, index: int): tuple[x, y: int] =
  let cols = layout.cols
  if cols == 0: return (0, 0)
  let cx = layout.startX + (index mod cols) * VoteCellW
  let cy = VoteStartY + (index div cols) * VoteCellH
  (cx, cy)

# ---------------------------------------------------------------------------
# Scalar sprite-match helpers (reused from actors, but local here
# to avoid circular imports — these are tiny)
# ---------------------------------------------------------------------------

proc isPlayerBodyColor(c: uint8): bool {.inline.} =
  for pc in data.PlayerColors:
    if c == pc: return true
    if c == ShadowMap[pc and 0x0F'u8]: return true
  false

proc matchesCrewmateAt(
    frame: openArray[uint8], sprite: Sprite,
    x, y: int, flipH: bool): bool =
  ## Scalar crewmate match at a single anchor.
  var misses, matchedStable, bodyMatched, stablePixels, bodyPixels = 0
  let sw = sprite.width
  let sh = sprite.height
  for sy in 0 ..< sh:
    for sx in 0 ..< sw:
      let srcX = if flipH: sw - 1 - sx else: sx
      let c = sprite.pixels[sy * sw + srcX]
      if c == TransparentIndex: continue
      let fx = x + sx
      let fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        inc misses
        if c == TintColor or c == ShadeTintColor: inc bodyPixels
        else: inc stablePixels
      else:
        let fc = frame[fy * ScreenWidth + fx]
        if c == TintColor or c == ShadeTintColor:
          inc bodyPixels
          if isPlayerBodyColor(fc): inc bodyMatched
          else: inc misses
        else:
          inc stablePixels
          if fc == c: inc matchedStable
          else: inc misses
      if misses > CrewmateMaxMisses: return false
  stablePixels >= CrewmateMinStable and matchedStable >= CrewmateMinStable and
    bodyPixels >= CrewmateMinBody and bodyMatched >= CrewmateMinBody

proc matchesActorSpriteAt(
    frame: openArray[uint8], sprite: Sprite,
    x, y: int, flipH: bool,
    maxMisses, minStable, minTint: int): bool =
  ## Generalised sprite match (for body detection in vote slots).
  var misses, matchedStable, matchedTint, stablePixels, tintPixels = 0
  let sw = sprite.width
  let sh = sprite.height
  for sy in 0 ..< sh:
    for sx in 0 ..< sw:
      let srcX = if flipH: sw - 1 - sx else: sx
      let c = sprite.pixels[sy * sw + srcX]
      if c == TransparentIndex: continue
      let fx = x + sx
      let fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        inc misses
        if c == TintColor or c == ShadeTintColor: inc tintPixels
        else: inc stablePixels
      else:
        let fc = frame[fy * ScreenWidth + fx]
        if c == TintColor or c == ShadeTintColor:
          inc tintPixels
          if isPlayerBodyColor(fc): inc matchedTint
          else: inc misses
        else:
          inc stablePixels
          if fc == c: inc matchedStable
          else: inc misses
      if misses > maxMisses: return false
  matchedStable >= minStable and matchedTint >= minTint

proc crewmateColorAt(
    frame: openArray[uint8], sprite: Sprite,
    x, y: int, flipH: bool): int =
  ## Scalar colour vote at one anchor. Returns player-colour index or -1.
  var counts: array[data.PaletteColorTableSize, int]
  let sw = sprite.width
  let sh = sprite.height
  for sy in 0 ..< sh:
    for sx in 0 ..< sw:
      let srcX = if flipH: sw - 1 - sx else: sx
      let c = sprite.pixels[sy * sw + srcX]
      if c != TintColor: continue
      let fx = x + sx
      let fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight: continue
      let fc = frame[fy * ScreenWidth + fx]
      for i, pc in data.PlayerColors:
        if fc == pc:
          inc counts[i]
          break
  var best = -1
  var bestV = 0
  for i in 0 ..< data.PaletteColorTableSize:
    if counts[i] > bestV: bestV = counts[i]; best = i
  best

proc playerColorIndexOf(c: uint8): int {.inline.} =
  for i, pc in data.PlayerColors:
    if c == pc: return i
  -1

# ---------------------------------------------------------------------------
# Slot parsing
# ---------------------------------------------------------------------------

type
  VoteSlot* = object
    colorIndex*: int   ## PlayerColors index or VoteUnknown
    alive*: bool

proc parseVoteSlot*(
    frame: openArray[uint8], sprites: Sprites,
    count, index: int): VoteSlot =
  let layout = voteGridLayout(count)
  let (cx, cy) = voteCellOrigin(layout, count, index)
  let spriteX = cx + (VoteCellW - sprites.player.width) div 2
  let spriteY = cy + 1

  # Try alive crewmate first.
  for flip in [false, true]:
    if matchesCrewmateAt(frame, sprites.player, spriteX, spriteY, flip):
      let ci = crewmateColorAt(frame, sprites.player, spriteX, spriteY, flip)
      return VoteSlot(colorIndex: ci, alive: true)

  # Try body (dead).
  if matchesActorSpriteAt(frame, sprites.body, spriteX, spriteY, false,
                          BodyMaxMisses, BodyMinStable, BodyMinTint):
    let ci = crewmateColorAt(frame, sprites.body, spriteX, spriteY, false)
    return VoteSlot(colorIndex: ci, alive: false)

  VoteSlot(colorIndex: VoteUnknown, alive: false)

# ---------------------------------------------------------------------------
# Cursor / self-marker / vote-dot detection (pure pixel math)
# ---------------------------------------------------------------------------

proc voteCellSelected(frame: openArray[uint8], count, index: int): bool =
  let layout = voteGridLayout(count)
  let (cx, cy) = voteCellOrigin(layout, count, index)
  var hits = 0
  let topY = cy - 1
  let botY = cy + VoteCellH - 2
  for x in cx ..< cx + VoteCellW:
    if topY >= 0 and topY < ScreenHeight and x >= 0 and x < ScreenWidth:
      if frame[topY * ScreenWidth + x] == CursorColor: inc hits
    if botY >= 0 and botY < ScreenHeight and x >= 0 and x < ScreenWidth:
      if frame[botY * ScreenWidth + x] == CursorColor: inc hits
  hits >= VoteCellW

proc voteSkipSelected(frame: openArray[uint8], skipX, skipY: int): bool =
  var hits = 0
  let topY = skipY - 1
  let botY = skipY + 6
  for x in skipX ..< skipX + VoteSkipW:
    if topY >= 0 and topY < ScreenHeight and x >= 0 and x < ScreenWidth:
      if frame[topY * ScreenWidth + x] == CursorColor: inc hits
    if botY >= 0 and botY < ScreenHeight and x >= 0 and x < ScreenWidth:
      if frame[botY * ScreenWidth + x] == CursorColor: inc hits
  hits >= VoteSkipW

proc voteSelfMarkerPresent(
    frame: openArray[uint8], count, index, colorIndex: int): bool =
  let layout = voteGridLayout(count)
  let (cx, cy) = voteCellOrigin(layout, count, index)
  let mx = cx + 8 - 1
  let my = cy - 2
  if mx < 0 or mx >= ScreenWidth or my < 0 or my >= ScreenHeight: return false
  let px0 = frame[my * ScreenWidth + mx]
  let px1 = if mx + 1 < ScreenWidth: frame[my * ScreenWidth + mx + 1] else: 0'u8
  if colorIndex >= 0 and colorIndex < data.PaletteColorTableSize:
    let expected = data.PlayerColors[colorIndex]
    if expected == 0'u8:
      # Black player: cursor-colour + black-marker pair.
      return (px0 == CursorColor and px1 == VoteBlackMarker) or
             (px0 == VoteBlackMarker and px1 == CursorColor)
    return px0 == expected or px1 == expected
  false

proc voteDotColorIndex(frame: openArray[uint8], x, y: int): int =
  if x < 0 or x >= ScreenWidth or y < 0 or y >= ScreenHeight: return VoteUnknown
  let c = frame[y * ScreenWidth + x]
  if c == 0'u8: return VoteUnknown  # Background
  # Black-player dots: cursor-colour next to black-marker.
  if c == CursorColor:
    if x + 1 < ScreenWidth and frame[y * ScreenWidth + x + 1] == VoteBlackMarker:
      return playerColorIndexOf(0'u8)  # Black is PlayerColors[15]=0
  if c == VoteBlackMarker:
    if x > 0 and frame[y * ScreenWidth + x - 1] == CursorColor:
      return playerColorIndexOf(0'u8)
  playerColorIndexOf(c)

# ---------------------------------------------------------------------------
# SKIP text check
# ---------------------------------------------------------------------------

proc voteSkipTextPixelCount(
    frame: openArray[uint8], skipX, skipY: int): int =
  ## Count cursor-colour pixels in the expected 7px-tall SKIP text box.
  for y in skipY ..< skipY + VoteSkipTextH:
    if y < 0 or y >= ScreenHeight: continue
    for x in skipX ..< skipX + VoteSkipW:
      if x < 0 or x >= ScreenWidth: continue
      if frame[y * ScreenWidth + x] == CursorColor:
        inc result

proc voteSkipTextMatches*(
    frame: openArray[uint8], skipX, skipY: int): bool =
  ## Search a small window around the expected SKIP position.
  ##
  ## The live voting screen renders SKIP with a 7px-tall font, while the
  ## baked OCR font is 6px tall. Validate the button by its actual pixel
  ## signature instead of trying to OCR-match the text.
  for dy in -1 .. 1:
    for dx in -2 .. 2:
      if voteSkipTextPixelCount(frame, skipX + dx, skipY + dy) >=
          VoteSkipMinTextPixels:
        return true
  false

# ---------------------------------------------------------------------------
# Chat OCR + speaker attribution
# ---------------------------------------------------------------------------

proc voteChatSpeakerAt(
    frame: openArray[uint8], sprites: Sprites, y: int): int =
  ## Check for a player sprite pip at the chat-icon column.
  let sprite = sprites.player
  for flip in [false, true]:
    if matchesCrewmateAt(frame, sprite, VoteChatIconX, y, flip):
      return crewmateColorAt(frame, sprite, VoteChatIconX, y, flip)
  VoteUnknown

type
  VoteChatLine* = object
    speakerColor*: int
    y*: int
    text*: string

proc usefulChatLine(line: string): bool =
  var letters = 0
  var questions = 0
  for ch in line:
    if (ch >= 'a' and ch <= 'z') or (ch >= 'A' and ch <= 'Z'): inc letters
    if ch == '?': inc questions
  letters >= 2 and questions * 2 <= max(1, line.len)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

type
  VotingParse* = object
    ## Result of a successful voting-screen parse. Merged into belief
    ## by the pipeline.
    valid*: bool
    playerCount*: int
    cursor*: int            ## Slot index, or playerCount = SKIP, or -1
    selfSlot*: int          ## Our slot index, or -1
    slots*: array[MaxPlayers, VoteSlot]
    choices*: array[MaxPlayers, int]  ## Per-voter → target slot
    chatLines*: seq[VoteChatLine]

proc initVotingParse*(): VotingParse =
  result.valid = false
  result.playerCount = 0
  result.cursor = -1
  result.selfSlot = -1
  for i in 0 ..< MaxPlayers:
    result.slots[i] = VoteSlot(colorIndex: VoteUnknown, alive: false)
    result.choices[i] = VoteUnknown

# ---------------------------------------------------------------------------
# Main parse
# ---------------------------------------------------------------------------

proc parseVotingCandidate(
    frame: openArray[uint8],
    sprites: Sprites,
    count: int,
    selfColorIndex: int): VotingParse =
  ## Try to parse the frame as a voting screen with ``count`` players.
  ## Returns a valid result on success, invalid on failure.
  result = initVotingParse()
  let layout = voteGridLayout(count)

  # 1. SKIP text must be present.
  if not voteSkipTextMatches(frame, layout.skipX, layout.skipY):
    return

  # 2. Strict slot check — each slot's colour must match its index.
  for i in 0 ..< count:
    let slot = parseVoteSlot(frame, sprites, count, i)
    if slot.colorIndex != i:
      return  # Colour mismatch → reject this player count.
    result.slots[i] = slot

  # All slots validated → parse succeeds.
  result.valid = true
  result.playerCount = count

  # 3. Cursor detection.
  for i in 0 ..< count:
    if voteCellSelected(frame, count, i):
      result.cursor = i
      break
  if result.cursor < 0 and voteSkipSelected(frame, layout.skipX, layout.skipY):
    result.cursor = count  # SKIP

  # 4. Self-marker detection.
  for i in 0 ..< count:
    if selfColorIndex >= 0 and voteSelfMarkerPresent(frame, count, i, selfColorIndex):
      result.selfSlot = i
      break

  # 5. Vote-dot parsing for each target slot + SKIP.
  let spriteH = sprites.player.height
  for target in 0 ..< count:
    let (cx, cy) = voteCellOrigin(layout, count, target)
    let dotX = cx + 1
    let dotY = cy + spriteH + 2
    for row in 0 ..< MaxPlayers:
      let dx = dotX + (row mod 8) * 2
      let dy = dotY + (row div 8)
      let ci = voteDotColorIndex(frame, dx, dy)
      if ci >= 0 and ci < MaxPlayers:
        result.choices[ci] = target

  # SKIP vote dots.
  let skipDotX = layout.skipX + VoteSkipW + 2
  let skipDotY = layout.skipY
  for row in 0 ..< MaxPlayers:
    let dx = skipDotX + (row mod 8) * 2
    let dy = skipDotY + (row div 8)
    let ci = voteDotColorIndex(frame, dx, dy)
    if ci >= 0 and ci < MaxPlayers:
      result.choices[ci] = count  # SKIP target = playerCount

  # 6. Chat OCR with speaker attribution.
  let chatY = layout.skipY + 10
  let chatStartY = chatY + 1
  let chatEndY = ScreenHeight - 6

  # Collect speaker pips.
  type SpeakerPip = tuple[y, color: int]
  var speakers: seq[SpeakerPip] = @[]
  var lastPipY = -100
  let pipEndY = ScreenHeight - spriteH
  var y = chatStartY
  while y < pipEndY:
    let ci = voteChatSpeakerAt(frame, sprites, y)
    if ci >= 0:
      if y - lastPipY > spriteH div 2:
        speakers.add (y: y, color: ci)
        lastPipY = y
      y += spriteH div 2  # skip past this pip
    else:
      inc y

  # Read chat lines.
  var lastText = ""
  y = chatStartY
  while y < chatEndY:
    # Fast check: any non-background pixel on this row in the text region?
    var hasText = false
    for x in VoteChatTextX ..< ScreenWidth:
      if frame[y * ScreenWidth + x] != TextBackground:
        hasText = true
        break
    if not hasText:
      inc y
      continue

    let text = readRun(frame, VoteChatTextX, y, VoteCharsPerLine,
                       maxErrors = 0, background = TextBackground)
    if text.len > 0 and usefulChatLine(text) and text != lastText:
      # Find speaker for this line.
      var speaker = VoteUnknown
      # Prefer pip at or above the text line.
      for s in countdown(speakers.len - 1, 0):
        if speakers[s].y <= y:
          speaker = speakers[s].color
          break
      # Fallback: nearest pip below within search distance.
      if speaker == VoteUnknown:
        for s in speakers:
          if s.y > y and s.y - y <= VoteChatSpeakerSearch:
            speaker = s.color
            break
      result.chatLines.add VoteChatLine(
        speakerColor: speaker, y: y, text: text)
      lastText = text
    # Advance past the font height to avoid re-reading the same line.
    y += referenceData.font.height + 1
    continue

proc parseVotingScreen*(
    frame: openArray[uint8],
    sprites: Sprites,
    selfColorIndex: int): VotingParse =
  ## Try to parse the frame as a voting screen by iterating candidate
  ## player counts from 16 down to 1. Returns the first valid parse.
  ## Mirrors ``modulabot/voting.py::parse_voting_screen``.
  for count in countdown(MaxPlayers, 1):
    let parse = parseVotingCandidate(frame, sprites, count, selfColorIndex)
    if parse.valid:
      return parse
  initVotingParse()  # No valid parse found.
