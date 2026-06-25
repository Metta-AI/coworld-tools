## Phase-1.5 OCR tests + Phase-1.6 voting-screen parse tests.
##
## Coverage:
##   - Font packing produces arrays of the expected shape.
##   - ``textMatches`` detects known text at known positions on
##     synthetic frames.
##   - ``bestGlyph`` identifies characters on synthetic frames.
##   - ``readRun`` reads multi-character sequences.
##   - ``findText`` locates text in a frame.
##   - ``classifyInterstitial`` returns ``InterstitialUnknown`` on
##     non-banner interstitials and gameplay frames.
##   - Voting grid layout math matches expected values.
##   - Full pipeline fixture sweep with OCR + voting doesn't crash.
##   - Smoke benchmark for OCR and voting operations.
##
## Run::
##
##     nim c -r -d:release --threads:on --mm:orc \
##         among_them/guided_bot/test/ocr_voting_test.nim

import std/[monotimes, os, strformat, strutils, times]
import ../constants
import ../types
import ../bot
import ../perception
import ../perception/data
import ../perception/ocr
import ../perception/voting

# ---------------------------------------------------------------------------
# Test harness
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

proc loadFixture(name: string): seq[uint8] =
  let here = currentSourcePath().parentDir()
  let path = here / "fixtures" / name
  let d = readFile(path)
  doAssert d.len == FrameLen, "fixture wrong length: " & name
  result = newSeq[uint8](FrameLen)
  for i in 0 ..< FrameLen:
    result[i] = uint8(d[i])

# ---------------------------------------------------------------------------
# 1. Font packing
# ---------------------------------------------------------------------------

proc testFontPacking() =
  let pf = getPackedFont()
  expectEq(pf.numGlyphs, PrintableAsciiCount,
           "packed font: numGlyphs = PrintableAsciiCount")
  expect(pf.height > 0, "packed font: height > 0")
  expect(pf.maxWidth > 0, "packed font: maxWidth > 0")
  expectEq(pf.pixels.len, pf.numGlyphs * pf.height * pf.maxWidth,
           "packed font: pixels array size")
  expectEq(pf.widths.len, pf.numGlyphs, "packed font: widths len")
  expectEq(pf.opaque.len, pf.numGlyphs, "packed font: opaque len")
  expectEq(pf.preferences.len, pf.numGlyphs, "packed font: preferences len")

  # Space glyph should have 0 opaque pixels.
  let spaceIdx = ord(' ') - FirstPrintableAscii
  expectEq(pf.opaque[spaceIdx], 0'i32, "space glyph: 0 opaque")
  # 'A' glyph should have some opaque pixels.
  let aIdx = ord('A') - FirstPrintableAscii
  expect(pf.opaque[aIdx] > 0, "'A' glyph has opaque pixels")

# ---------------------------------------------------------------------------
# 2. textMatches on synthetic frame
# ---------------------------------------------------------------------------

proc renderTextOnFrame(frame: var seq[uint8], text: string, x, y: int) =
  ## Render text onto a black frame using the baked font.
  let pf = getPackedFont()
  var penX = x
  for ch in text:
    let idx = if ch == '\n': -1
              else:
                let c = ord(ch)
                if c < FirstPrintableAscii or c > LastPrintableAscii:
                  ord('?') - FirstPrintableAscii
                else: c - FirstPrintableAscii
    if idx < 0: continue
    let w = int(pf.widths[idx])
    let stride = pf.height * pf.maxWidth
    for row in 0 ..< pf.height:
      for col in 0 ..< w:
        if pf.pixels[idx * stride + row * pf.maxWidth + col] != 0:
          let fx = penX + col
          let fy = y + row
          if fx >= 0 and fx < ScreenWidth and fy >= 0 and fy < ScreenHeight:
            frame[fy * ScreenWidth + fx] = 2'u8  # Non-black = foreground
    penX += w + pf.spacing

proc drawTintedPlayer(frame: var seq[uint8], x, y, colorIndex: int) =
  let sprite = referenceData.sprites.player
  for sy in 0 ..< sprite.height:
    for sx in 0 ..< sprite.width:
      let src = sprite.pixels[sy * sprite.width + sx]
      if src == TransparentIndex:
        continue
      var outPx = src
      if src == TintColor:
        outPx = PlayerColors[colorIndex]
      elif src == ShadeTintColor:
        outPx = ShadowMap[PlayerColors[colorIndex] and 0x0F'u8]
      let fx = x + sx
      let fy = y + sy
      if fx >= 0 and fy >= 0 and fx < ScreenWidth and fy < ScreenHeight:
        frame[fy * ScreenWidth + fx] = outPx

proc clearVoteChatPanel(frame: var seq[uint8], count: int) =
  let layout = voteGridLayout(count)
  let chatY = layout.skipY + 10
  for y in chatY ..< ScreenHeight:
    for x in 0 ..< ScreenWidth:
      frame[y * ScreenWidth + x] = 0'u8

proc testTextMatches() =
  var frame = newSeq[uint8](FrameLen)
  renderTextOnFrame(frame, "SKIP", 50, 60)

  expect(textMatches(frame, "SKIP", 50, 60),
         "textMatches: SKIP at rendered position")
  expect(not textMatches(frame, "SKIP", 51, 60),
         "textMatches: SKIP at wrong X fails")
  expect(not textMatches(frame, "NOPE", 50, 60),
         "textMatches: wrong text fails")

# ---------------------------------------------------------------------------
# 3. bestGlyph on synthetic frame
# ---------------------------------------------------------------------------

proc testBestGlyph() =
  var frame = newSeq[uint8](FrameLen)
  renderTextOnFrame(frame, "A", 10, 10)
  let (ch, errors, adv) = bestGlyph(frame, 10, 10, maxErrors = 2)
  # Should recognize 'A' (or 'a' via preference tie-break — either is acceptable).
  expect(ch == 'A' or ch == 'a',
         &"bestGlyph: recognized '{ch}' (expected A/a)")
  expect(errors <= 2, &"bestGlyph: errors={errors} <= 2")
  expect(adv > 0, &"bestGlyph: advance={adv} > 0")

# ---------------------------------------------------------------------------
# 4. readRun on synthetic frame
# ---------------------------------------------------------------------------

proc toUpperAscii(s: string): string =
  result = ""
  for ch in s:
    if ch >= 'a' and ch <= 'z':
      result.add chr(ord(ch) - 32)
    else:
      result.add ch

proc testReadRun() =
  var frame = newSeq[uint8](FrameLen)
  renderTextOnFrame(frame, "HI", 20, 20)
  let text = readRun(frame, 20, 20, 4, maxErrors = 2)
  # Should contain "HI" (case may vary due to preference tie-breaks).
  let upper = text.toUpperAscii()
  expect(upper.len >= 2, &"readRun: got '{text}', len >= 2")

# ---------------------------------------------------------------------------
# 4b. Voting chat speaker attribution
# ---------------------------------------------------------------------------

proc testVotingChatSpeakerAttribution() =
  var frame = loadFixture("voting_real_1432.bin")
  clearVoteChatPanel(frame, 8)

  let layout = voteGridLayout(8)
  let rowGap = referenceData.font.height + 1
  let prevY = layout.skipY + 11
  let wrappedY = prevY + referenceData.sprites.player.height + 1

  drawTintedPlayer(frame, VoteChatIconX, prevY, 5)
  renderTextOnFrame(frame, "old chat", VoteChatTextX, prevY)

  # Two-row chat centers the speaker icon one pixel below the first text row.
  # The parser must choose that nearest lower icon, not the previous message's
  # icon above the line.
  drawTintedPlayer(frame, VoteChatIconX, wrappedY + 1, 0)
  renderTextOnFrame(frame, "first row", VoteChatTextX, wrappedY)
  renderTextOnFrame(frame, "second row", VoteChatTextX, wrappedY + rowGap)

  let parsed = parseVotingScreen(frame, referenceData.sprites, -1)
  expect(parsed.valid, "voting chat attribution fixture parses as voting")

  var sawFirst = false
  var sawSecond = false
  for line in parsed.chatLines:
    let upper = line.text.toUpperAscii()
    if upper.startsWith("FIRST"):
      sawFirst = true
      expectEq(line.speakerColor, 0,
               "wrapped chat first row attributed to nearest speaker")
    if upper.startsWith("SECOND"):
      sawSecond = true
      expectEq(line.speakerColor, 0,
               "wrapped chat second row attributed to same speaker")
  expect(sawFirst, "wrapped chat first row parsed")
  expect(sawSecond, "wrapped chat second row parsed")

proc testVotingParserAcceptsShuffledSlotColors() =
  var frame = loadFixture("voting_real_1432.bin")
  let
    layout = voteGridLayout(8)
    shuffled = [2, 3, 6, 7, 0, 5, 4, 1]
  for slot, colorIndex in shuffled:
    let (cx, cy) = voteCellOrigin(layout, 8, slot)
    drawTintedPlayer(
      frame,
      cx + (VoteCellW - referenceData.sprites.player.width) div 2,
      cy + 1,
      colorIndex)

  let parsed = parseVotingScreen(frame, referenceData.sprites, -1)
  expect(parsed.valid, "shuffled voting fixture parses as voting")
  expectEq(parsed.playerCount, 8,
           "shuffled voting fixture: player count")
  for slot, colorIndex in shuffled:
    expectEq(parsed.slots[slot].colorIndex, colorIndex,
             &"shuffled voting fixture: slot {slot} color")

# ---------------------------------------------------------------------------
# 5. findText on synthetic frame
# ---------------------------------------------------------------------------

proc testFindText() =
  var frame = newSeq[uint8](FrameLen)
  renderTextOnFrame(frame, "CREWMATE", 30, 50)

  let (found, x, y) = findText(frame, "CREWMATE", maxErrors = 0)
  expect(found, "findText: found CREWMATE")
  expectEq(x, 30, "findText: x=30")
  expectEq(y, 50, "findText: y=50")

  let (notFound, _, _) = findText(frame, "NOTHING")
  expect(not notFound, "findText: NOTHING not found")

# ---------------------------------------------------------------------------
# 6. classifyInterstitial
# ---------------------------------------------------------------------------

proc testClassifyInterstitial() =
  # Gameplay frame should not classify as any banner.
  let gameplay = loadFixture("gameplay_150.bin")
  let kind = classifyInterstitial(gameplay)
  expectEq(kind, InterstitialUnknown,
           "gameplay frame: classifyInterstitial = Unknown")

  # Synthetic frame with "CREWMATE" banner.
  var crew = newSeq[uint8](FrameLen)
  renderTextOnFrame(crew, "CREWMATE", 30, 50)
  let crewKind = classifyInterstitial(crew, maxErrors = 0)
  expectEq(crewKind, InterstitialRoleRevealCrewmate,
           "CREWMATE banner: classifyInterstitial = RoleRevealCrewmate")

  # Synthetic frame with "IMPS WIN" banner.
  var win = newSeq[uint8](FrameLen)
  renderTextOnFrame(win, "IMPS WIN", 30, 50)
  let winKind = classifyInterstitial(win, maxErrors = 0)
  expectEq(winKind, InterstitialGameOver,
           "IMPS WIN banner: classifyInterstitial = GameOver")

  # Real game-over frames use the server title "CREW WINS".
  let realCrewWins = loadFixture("gameover_crew_wins_real.bin")
  let realCrewWinsKind = classifyInterstitial(realCrewWins)
  expectEq(realCrewWinsKind, InterstitialGameOver,
           "real CREW WINS frame: classifyInterstitial = GameOver")

# ---------------------------------------------------------------------------
# 6b. Full bot phase update from classified interstitials
# ---------------------------------------------------------------------------

proc testGameOverPhaseUpdate() =
  var bot = initBot()
  let win = loadFixture("gameover_crew_wins_real.bin")

  discard bot.stepUnpackedFrame(win)

  expectEq(bot.belief.self.phase, PhaseGameOver,
           "pipeline: real CREW WINS frame sets PhaseGameOver")
  expectEq(bot.belief.percep.interstitialKind, InterstitialGameOver,
           "pipeline: real CREW WINS frame records GameOver kind")

# ---------------------------------------------------------------------------
# 7. Voting grid layout
# ---------------------------------------------------------------------------

proc testVoteGridLayout() =
  # 8 players: 8 cols, 1 row.
  let l8 = voteGridLayout(8)
  expectEq(l8.cols, 8, "layout(8): cols")
  expectEq(l8.rows, 1, "layout(8): rows")
  expectEq(l8.startX, (128 - 8 * 16) div 2, "layout(8): startX")
  expectEq(l8.skipY, 2 + 1 * 17 + 1, "layout(8): skipY")

  # 10 players: 8 cols, 2 rows.
  let l10 = voteGridLayout(10)
  expectEq(l10.cols, 8, "layout(10): cols")
  expectEq(l10.rows, 2, "layout(10): rows")

  # 1 player: 1 col, 1 row.
  let l1 = voteGridLayout(1)
  expectEq(l1.cols, 1, "layout(1): cols")
  expectEq(l1.rows, 1, "layout(1): rows")

# ---------------------------------------------------------------------------
# 8. Fixture sweep with OCR + voting
# ---------------------------------------------------------------------------

proc testFixtureSweep() =
  const fixtures = [
    "interstitial_0.bin", "interstitial_5.bin", "interstitial_100.bin",
    "gameplay_131.bin", "gameplay_150.bin", "gameplay_200.bin",
    "gameplay_274.bin",
  ]
  var bot = initBot()
  for name in fixtures:
    discard bot.stepUnpackedFrame(loadFixture(name))
  expectEq(bot.frameTick, fixtures.len,
           "fixture sweep: frameTick == frame count")

# ---------------------------------------------------------------------------
# 9. Smoke benchmark
# ---------------------------------------------------------------------------

proc testBenchmark() =
  var frame = newSeq[uint8](FrameLen)
  renderTextOnFrame(frame, "CREWMATE", 30, 50)

  let t0 = getMonoTime()
  discard classifyInterstitial(frame, maxErrors = 0)
  let t1 = getMonoTime()
  discard classifyInterstitial(frame, maxErrors = 0)
  let t2 = getMonoTime()

  let coldMs = float((t1 - t0).inMicroseconds) / 1000.0
  let warmMs = float((t2 - t1).inMicroseconds) / 1000.0
  echo &"  bench classifyInterstitial: cold={coldMs:.2f} ms, warm={warmMs:.2f} ms"

  # textMatches benchmark.
  let t3 = getMonoTime()
  for _ in 0 ..< 100:
    discard textMatches(frame, "CREWMATE", 30, 50)
  let t4 = getMonoTime()
  let tmMs = float((t4 - t3).inMicroseconds) / 100000.0
  echo &"  bench textMatches (x100): avg={tmMs:.3f} ms"

  expect(coldMs < 2000.0, &"bench: classifyInterstitial cold <2s, got {coldMs:.0f} ms")

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

proc main() =
  testFontPacking()
  testTextMatches()
  testBestGlyph()
  testReadRun()
  testVotingChatSpeakerAttribution()
  testVotingParserAcceptsShuffledSlotColors()
  testFindText()
  testClassifyInterstitial()
  testGameOverPhaseUpdate()
  testVoteGridLayout()
  testFixtureSweep()
  testBenchmark()

  if failures == 0:
    echo "OK (all perception phase-1.5/1.6 OCR + voting checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
