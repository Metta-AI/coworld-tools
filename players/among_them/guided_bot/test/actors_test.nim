## Phase-1.3 actor-scan tests. Runs against the real fixture frames in
## `test/fixtures/*.bin` — 128x128 uint8 palette-index dumps captured
## from a real Among Them game.
##
## Coverage:
##   - ``scanAll`` short-circuits on interstitials (empty lists).
##   - ``scanAll`` on gameplay frames produces non-crashing results
##     with plausible actor counts.
##   - ``updateRole`` detects the correct role on gameplay frames (kill
##     button present → imposter in these fixtures).
##   - ``updateSelfColor`` extracts a valid colour index on gameplay
##     frames where the player sprite is visible.
##   - Actor-exclusion ignore-mask stamping adds bits beyond the
##     phase-1.0 baseline.
##   - End-to-end bot pipeline populates ``belief.percep.visible*``
##     and ``belief.self.colorIndex`` / ``role`` after gameplay frames.
##   - Fixture sweep — every fixture frame runs through the full
##     pipeline (including actor scan) without assertions firing.
##   - Smoke benchmark — cold + warm actor scan timing.
##
## Run::
##
##     nim c -r -d:release --threads:on --mm:orc \
##         among_them/guided_bot/test/actors_test.nim

import std/[monotimes, os, strformat, times]
import ../constants
import ../types
import ../belief
import ../bot
import ../perception
import ../perception/data
import ../perception/frame
import ../perception/ignore
import ../perception/actors

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
  let data = readFile(path)
  doAssert data.len == FrameLen, "fixture wrong length: " & name
  result = newSeq[uint8](FrameLen)
  for i in 0 ..< FrameLen:
    result[i] = uint8(data[i])

# ---------------------------------------------------------------------------
# 1. Interstitial short-circuit
# ---------------------------------------------------------------------------

proc testInterstitialShortCircuit() =
  ## Actor scan on an interstitial frame must return empty lists and
  ## preserve the ghost-icon frame counter.
  var scanner = initActorScanner()
  let prevPercep = initPerceptionState()
  let prevSelf = initSelfState()
  let sprites = referenceData.sprites
  let frame = loadFixture("interstitial_0.bin")

  let result = scanAll(scanner, prevPercep, prevSelf, sprites, frame,
                       isInterstitial = true)
  expectEq(result.crewmates.len, 0, "interstitial: no crewmates")
  expectEq(result.bodies.len, 0, "interstitial: no bodies")
  expectEq(result.ghosts.len, 0, "interstitial: no ghosts")
  expect(not result.roleUpdated, "interstitial: no role update")
  expect(not result.selfColorUpdated, "interstitial: no self-color update")

proc testInterstitialPreservesGhostIconFrames() =
  ## Ghost-icon frame counter should persist through interstitials
  ## (debounce isn't reset by a black gap).
  var scanner = initActorScanner()
  var prevPercep = initPerceptionState()
  prevPercep.ghostIconFrames = 1
  let prevSelf = initSelfState()
  let sprites = referenceData.sprites
  let frame = loadFixture("interstitial_0.bin")

  let result = scanAll(scanner, prevPercep, prevSelf, sprites, frame,
                       isInterstitial = true)
  expectEq(result.ghostIconFrames, 1,
           "interstitial preserves ghostIconFrames")

# ---------------------------------------------------------------------------
# 2. Gameplay scan — crewmate / body / ghost counts plausibility
# ---------------------------------------------------------------------------

proc testGameplayScanPlausibility() =
  ## On a real gameplay frame, the scan should run without crashing.
  ## We can't pin exact counts without knowing the fixture content
  ## in detail, but we can check that no list has an absurd count
  ## (e.g. > 20 crewmates on a 128x128 frame).
  var scanner = initActorScanner()
  let prevPercep = initPerceptionState()
  let prevSelf = initSelfState()
  let sprites = referenceData.sprites
  let frame = loadFixture("gameplay_150.bin")

  let result = scanAll(scanner, prevPercep, prevSelf, sprites, frame,
                       isInterstitial = false)
  expect(result.crewmates.len <= 20,
         &"gameplay_150: crewmate count {result.crewmates.len} plausible")
  expect(result.bodies.len <= 10,
         &"gameplay_150: body count {result.bodies.len} plausible")
  expect(result.ghosts.len <= 10,
         &"gameplay_150: ghost count {result.ghosts.len} plausible")

  # All anchor coordinates must be non-negative and within screen bounds.
  for cm in result.crewmates:
    expect(cm.x >= 0 and cm.x < ScreenWidth,
           &"crewmate x={cm.x} in bounds")
    expect(cm.y >= 0 and cm.y < ScreenHeight,
           &"crewmate y={cm.y} in bounds")
  for bm in result.bodies:
    expect(bm.x >= 0 and bm.x < ScreenWidth,
           &"body x={bm.x} in bounds")
    expect(bm.y >= 0 and bm.y < ScreenHeight,
           &"body y={bm.y} in bounds")

# ---------------------------------------------------------------------------
# 3. Role detection — imposter (kill button present in fixtures)
# ---------------------------------------------------------------------------

proc testRoleDetection() =
  ## The gameplay fixtures are from an imposter's POV (kill button
  ## visible at the HUD slot). updateRole should set role to Imposter.
  var scanner = initActorScanner()
  let prevPercep = initPerceptionState()
  let prevSelf = initSelfState()
  let sprites = referenceData.sprites

  for name in ["gameplay_131.bin", "gameplay_150.bin",
               "gameplay_200.bin", "gameplay_274.bin"]:
    let frame = loadFixture(name)
    let result = scanAll(scanner, prevPercep, prevSelf, sprites, frame,
                         isInterstitial = false)
    if result.roleUpdated:
      expectEq(result.newRole, RoleImposter,
               &"{name}: role is imposter (kill button present)")
    expect(not result.isGhost, &"{name}: not a ghost")

# ---------------------------------------------------------------------------
# 4. Self-colour detection
# ---------------------------------------------------------------------------

proc testSelfColorDetection() =
  ## On gameplay frames where the player sprite is visible (all
  ## non-interstitial fixtures), self-colour should be extracted as
  ## a valid index.
  var scanner = initActorScanner()
  let prevPercep = initPerceptionState()
  let prevSelf = initSelfState()
  let sprites = referenceData.sprites

  for name in ["gameplay_150.bin", "gameplay_200.bin", "gameplay_274.bin"]:
    let frame = loadFixture(name)
    let result = scanAll(scanner, prevPercep, prevSelf, sprites, frame,
                         isInterstitial = false)
    # Self-colour should be detected on most gameplay frames.
    # gameplay_131 is very early and may not have a clean sprite match.
    if result.selfColorUpdated:
      expect(result.newSelfColor >= 0 and
             result.newSelfColor < data.PaletteColorTableSize,
             &"{name}: self-color {result.newSelfColor} is valid index")

  # Additionally test that all gameplay frames agree on the same colour
  # (same player in all fixtures).
  var colors: seq[int] = @[]
  for name in ["gameplay_150.bin", "gameplay_200.bin", "gameplay_274.bin"]:
    let frame = loadFixture(name)
    let result = scanAll(scanner, prevPercep, prevSelf, sprites, frame,
                         isInterstitial = false)
    if result.selfColorUpdated:
      colors.add result.newSelfColor
  if colors.len >= 2:
    for i in 1 ..< colors.len:
      expectEq(colors[i], colors[0],
               "self-color consistent across gameplay fixtures")

# ---------------------------------------------------------------------------
# 5. Ignore-mask actor exclusions
# ---------------------------------------------------------------------------

proc testActorIgnoreMaskExclusions() =
  ## After actor scanning, stamping exclusions should add bits
  ## beyond the phase-1.0 baseline (player-centre + radar).
  let frame = loadFixture("gameplay_150.bin")
  var mask = initIgnoreMask()
  buildPhase10IgnoreMask(mask, frame)
  let baseBits = mask.countSet()

  # Run actor scan to get results.
  var scanner = initActorScanner()
  let prevPercep = initPerceptionState()
  let prevSelf = initSelfState()
  let sprites = referenceData.sprites
  let result = scanAll(scanner, prevPercep, prevSelf, sprites, frame,
                       isInterstitial = false)

  # Stamp actor exclusions.
  let spriteW = sprites.player.width
  let spriteH = sprites.player.height
  for cm in result.crewmates:
    stampSpriteRect(mask, cm.x, cm.y, spriteW, spriteH)
  let bodyW = sprites.body.width
  let bodyH = sprites.body.height
  for bm in result.bodies:
    stampSpriteRect(mask, bm.x, bm.y, bodyW, bodyH)
  let ghostW = sprites.ghost.width
  let ghostH = sprites.ghost.height
  for gm in result.ghosts:
    stampSpriteRect(mask, gm.x, gm.y, ghostW, ghostH)

  let afterBits = mask.countSet()
  # If any actors were detected, the mask should have grown.
  let totalActors = result.crewmates.len + result.bodies.len + result.ghosts.len
  if totalActors > 0:
    expect(afterBits > baseBits,
           &"ignore mask grew from {baseBits} to {afterBits} with {totalActors} actors")
  # Even with no actors, the mask must be at least as large.
  expect(afterBits >= baseBits,
         &"ignore mask never shrinks: {afterBits} >= {baseBits}")

# ---------------------------------------------------------------------------
# 6. End-to-end bot pipeline
# ---------------------------------------------------------------------------

proc testBotPipelineActors() =
  ## Verify the bot pipeline calls actor scan on gameplay frames and
  ## populates the belief's perception and self fields.
  var bot = initBot()

  # Start with an interstitial — no actors.
  discard bot.stepUnpackedFrame(loadFixture("interstitial_5.bin"))
  expectEq(bot.belief.percep.visibleCrewmates.len, 0,
           "interstitial: no crewmates in belief")
  expectEq(bot.belief.percep.visibleBodies.len, 0,
           "interstitial: no bodies in belief")

  # Gameplay frame — actors should be populated.
  discard bot.stepUnpackedFrame(loadFixture("gameplay_150.bin"))
  # Role should be set (imposter — kill button visible in these fixtures).
  expectEq(bot.belief.self.role, RoleImposter,
           "pipeline: role is imposter after gameplay")
  expect(not bot.belief.self.isGhost,
         "pipeline: not a ghost after gameplay")

  # Self-colour should be set on a gameplay frame.
  discard bot.stepUnpackedFrame(loadFixture("gameplay_200.bin"))
  if bot.belief.self.colorIndex >= 0:
    expect(bot.belief.self.colorIndex < data.PaletteColorTableSize,
           &"pipeline: colorIndex {bot.belief.self.colorIndex} valid")

  # WakeBodySeen should be set if bodies were found (may or may not be).
  # Just verify the flag doesn't crash.
  discard bot.stepUnpackedFrame(loadFixture("gameplay_274.bin"))
  # No assertion on WakeBodySeen presence — depends on fixture content.

# ---------------------------------------------------------------------------
# 7. Fixture sweep — all fixtures through the pipeline
# ---------------------------------------------------------------------------

proc testFixtureSweepWithActors() =
  ## Every fixture frame runs through the full pipeline (including
  ## actor scan) without assertions firing.
  const fixtures = [
    "interstitial_0.bin", "interstitial_5.bin", "interstitial_100.bin",
    "gameplay_131.bin", "gameplay_150.bin", "gameplay_200.bin",
    "gameplay_274.bin",
  ]
  var bot = initBot()
  for name in fixtures:
    let frame = loadFixture(name)
    discard bot.stepUnpackedFrame(frame)
  expectEq(bot.frameTick, fixtures.len,
           "fixture sweep: frameTick == frame count")

# ---------------------------------------------------------------------------
# 8. Smoke benchmark
# ---------------------------------------------------------------------------

proc testBenchmark() =
  ## Plausibility-only timing for the actor scan pass. Guards against
  ## catastrophic regressions, not precise perf measurement.
  var scanner = initActorScanner()
  let prevPercep = initPerceptionState()
  let prevSelf = initSelfState()
  let sprites = referenceData.sprites
  let frame = loadFixture("gameplay_150.bin")

  let t0 = getMonoTime()
  let r1 = scanAll(scanner, prevPercep, prevSelf, sprites, frame,
                   isInterstitial = false)
  let t1 = getMonoTime()
  let r2 = scanAll(scanner, prevPercep, prevSelf, sprites, frame,
                   isInterstitial = false)
  let t2 = getMonoTime()

  let coldMs = float((t1 - t0).inMilliseconds)
  let warmMs = float((t2 - t1).inMilliseconds)
  echo &"  bench: cold={coldMs:.1f} ms, warm={warmMs:.1f} ms"
  echo &"  crewmates={r1.crewmates.len}, bodies={r1.bodies.len}, ghosts={r1.ghosts.len}"
  if r1.selfColorUpdated:
    echo &"  selfColor={r1.newSelfColor} ({data.PlayerColorNames[r1.newSelfColor]})"
  else:
    echo "  selfColor=not detected"

  # Actor scan is dominated by three vectorised passes (crewmate ×2
  # flips, body ×1, ghost ×2) plus per-anchor colour votes. On a
  # 128×128 frame with 12×12 sprites, the per-flip kernel touches
  # ~117×117 = 13689 anchors. With early-out, typical cost is 5-50 ms
  # depending on frame content. Allow generous bounds.
  expect(coldMs < 500.0, &"bench: cold <500ms, got {coldMs} ms")
  expect(warmMs < 500.0, &"bench: warm <500ms, got {warmMs} ms")

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

proc main() =
  testInterstitialShortCircuit()
  testInterstitialPreservesGhostIconFrames()
  testGameplayScanPlausibility()
  testRoleDetection()
  testSelfColorDetection()
  testActorIgnoreMaskExclusions()
  testBotPipelineActors()
  testFixtureSweepWithActors()
  testBenchmark()

  if failures == 0:
    echo "OK (all perception phase-1.3 actor checks passed)"
  else:
    stderr.writeLine &"FAILED: {failures} check(s)"
    quit(1)

when isMainModule:
  main()
