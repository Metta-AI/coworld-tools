## Phase-5 fallback-only playability test. Proves the bot plays a
## full match sequence without the LLM (provider explicitly disabled).
##
## DESIGN.md §9.2 requirements:
##   - Play every phase without crashing.
##   - Have at least one non-no-op action within the first 10 frames.
##     (Keeps Coworld validation/gameplay active from the first frame.)
##   - Mode transitions happen (at minimum idle -> task_completing or
##     equivalent default when role is detected).
##
## Strategy: replay the real fixture frames (test/fixtures/) through
## `stepUnpackedFrame` in a deterministic sequence that exercises the
## gameplay→interstitial→gameplay transitions a real match produces.
## The bot runs on scripted defaults the entire time because the LLM
## provider is explicitly disabled.
##
## Run:
##   nim c -r -d:release --threads:on --mm:orc \
##       among_them/guided_bot/test/fallback_test.nim

import std/[os, strformat]
import ../constants
import ../types
import ../bot

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
  doAssert data.len == FrameLen,
    "fixture " & name & " wrong length: " & $data.len
  result = newSeq[uint8](FrameLen)
  for i in 0 ..< FrameLen:
    result[i] = uint8(data[i])

# ---------------------------------------------------------------------------
# 1. Ensure LLM provider is disabled
# ---------------------------------------------------------------------------

proc disableLlm() =
  ## Force the bot onto scripted defaults only. This matters on local
  ## machines where AWS Bedrock credentials may be present by default.
  putEnv("GUIDED_BOT_LLM_DISABLE", "1")
  delEnv("ANTHROPIC_API_KEY")
  delEnv("COGAMES_LLM_PROVIDER")
  delEnv("COGAMES_LLM_MODEL")
  delEnv("CLAUDE_CODE_USE_BEDROCK")
  delEnv("USE_BEDROCK")

# ---------------------------------------------------------------------------
# 2. Validation-gate test: non-NOOP within 10 frames
# ---------------------------------------------------------------------------

proc testValidationGate() =
  ## Replay gameplay fixtures as if they're consecutive frames. The bot
  ## must emit at least one non-NOOP mask within the first 10 frames.
  ## This mirrors the early-frame activity requirement.
  disableLlm()
  var b = initBot()
  defer: destroyBot(b)

  # Load gameplay fixtures to use as frame data. gameplay_131 is
  # excluded because it's a known non-localizable frame (too much
  # ignore-mask coverage; see localize_test.nim ground truth). In a
  # real match the bot sees continuous frames; here we use the
  # localizable fixtures which is enough for the localizer to lock
  # and task_completing to emit directional movement.
  let frame150 = loadFixture("gameplay_150.bin")
  let frame200 = loadFixture("gameplay_200.bin")
  let frame274 = loadFixture("gameplay_274.bin")
  let gameplayFrames = [frame150, frame200, frame274]

  var sawNonNoop = false
  var firstNonNoopTick = -1

  # Feed 10 frames to cover the early-frame validation window.
  for i in 0 ..< 10:
    # Cycle through the gameplay fixtures to give the bot diverse
    # visual input for localization and task detection.
    let mask = b.stepUnpackedFrame(gameplayFrames[i mod gameplayFrames.len])
    if mask != 0'u8 and not sawNonNoop:
      sawNonNoop = true
      firstNonNoopTick = i + 1  # 1-indexed to match frameTick

  expect(sawNonNoop,
    "validation gate: non-NOOP mask must appear within 10 frames " &
    "(early validation requires non_noop_actions > 0)")
  if firstNonNoopTick > 0:
    echo &"  validation gate: first non-NOOP at tick {firstNonNoopTick}"

# ---------------------------------------------------------------------------
# 3. Mode transition test: idle -> task_completing (crewmate default)
# ---------------------------------------------------------------------------

proc testModeTransitions() =
  ## Feed gameplay + interstitial fixtures and verify the bot
  ## transitions between modes. At minimum: the initial idle mode
  ## should transition to task_completing once the localizer locks
  ## and role detection kicks in.
  disableLlm()
  var b = initBot()
  defer: destroyBot(b)

  # gameplay_131 excluded: known non-localizable frame (see
  # localize_test.nim ground truth). Using it would cause ~11s
  # spiral-search timeouts on every occurrence.
  let frame150 = loadFixture("gameplay_150.bin")
  let frame200 = loadFixture("gameplay_200.bin")
  let frame274 = loadFixture("gameplay_274.bin")
  let inter0 = loadFixture("interstitial_0.bin")
  let inter5 = loadFixture("interstitial_5.bin")
  let inter100 = loadFixture("interstitial_100.bin")

  # Track all modes the bot enters.
  var modesSeen: set[ModeName]
  modesSeen.incl b.belief.directive.mode  # initial mode

  # Phase 1: gameplay sequence (should trigger task_completing or
  # hunting once role is detected and camera locks).
  let gameplayFrames = [frame150, frame200, frame274]
  for rep in 0 ..< 3:
    for fi, frame in gameplayFrames:
      discard b.stepUnpackedFrame(frame)
      modesSeen.incl b.belief.directive.mode

  # Phase 2: interstitial sequence (may trigger meeting mode if the
  # voting parse fires on interstitial frames).
  let interFrames = [inter0, inter5, inter100]
  for rep in 0 ..< 2:
    for frame in interFrames:
      discard b.stepUnpackedFrame(frame)
      modesSeen.incl b.belief.directive.mode

  # Phase 3: back to gameplay (mode should transition back from
  # meeting/interstitial to a gameplay mode).
  for rep in 0 ..< 3:
    for frame in gameplayFrames:
      discard b.stepUnpackedFrame(frame)
      modesSeen.incl b.belief.directive.mode

  echo &"  modes seen: {modesSeen}"

  # The bot must have left the initial idle mode at some point.
  # On gameplay frames with a crewmate role, it should enter
  # task_completing. On imposter frames, hunting. Either way, it
  # shouldn't stay in idle the entire sequence.
  expect(modesSeen.len > 1,
    "mode transitions: bot must transition out of initial mode " &
    "(expected at least 2 distinct modes, got " & $modesSeen.len & ")")

  # Crewmate or imposter gameplay mode should appear.
  let hasGameplayMode = ModeTaskCompleting in modesSeen or
                        ModeHunting in modesSeen
  expect(hasGameplayMode,
    "mode transitions: expected task_completing or hunting in modes seen")

# ---------------------------------------------------------------------------
# 4. No-crash full-sequence test
# ---------------------------------------------------------------------------

proc testNoCrashFullSequence() =
  ## Replay all fixtures in a long sequence to prove the bot doesn't
  ## crash, panic, or enter an unrecoverable state. Exercises the full
  ## gameplay→interstitial→gameplay→interstitial cycle.
  disableLlm()
  var b = initBot()
  defer: destroyBot(b)

  # gameplay_131 excluded: known non-localizable (see testValidationGate).
  let frame150 = loadFixture("gameplay_150.bin")
  let frame200 = loadFixture("gameplay_200.bin")
  let frame274 = loadFixture("gameplay_274.bin")
  let inter0 = loadFixture("interstitial_0.bin")
  let inter5 = loadFixture("interstitial_5.bin")
  let inter100 = loadFixture("interstitial_100.bin")

  # All frames in a mix that simulates a real match progression:
  # gameplay -> interstitial (voting/result) -> gameplay -> more
  # interstitials -> gameplay.
  let allFrames = @[
    frame150, frame200, frame274,            # gameplay
    inter0, inter5, inter100,                # interstitial
    frame150, frame200, frame274,            # gameplay
    inter0, inter5,                          # interstitial
    frame200, frame274, frame150,            # gameplay
  ]

  var totalTicks = 0
  var nonNoopCount = 0

  # Run a few repetitions to exercise transitions and check for
  # accumulating state bugs.
  for rep in 0 ..< 3:
    for fi, frame in allFrames:
      let mask = b.stepUnpackedFrame(frame)
      inc totalTicks
      if mask != 0'u8:
        inc nonNoopCount

  echo &"  full sequence: {totalTicks} ticks, {nonNoopCount} non-NOOP"
  expect(totalTicks == 3 * allFrames.len,
    &"full sequence: expected {3 * allFrames.len} ticks, got {totalTicks}")

  # The bot should have produced some non-NOOP actions during
  # gameplay phases. Zero across 170 ticks would mean the pipeline
  # is broken.
  expect(nonNoopCount > 0,
    "full sequence: expected at least 1 non-NOOP action across " &
    $totalTicks & " ticks")

# ---------------------------------------------------------------------------
# 5. Default directive source test
# ---------------------------------------------------------------------------

proc testDefaultDirectiveSource() =
  ## Verify that with no LLM provider, the directive source stays "default"
  ## or "reflex" throughout — never "llm".
  disableLlm()
  var b = initBot()
  defer: destroyBot(b)

  let frame150 = loadFixture("gameplay_150.bin")
  let frame274 = loadFixture("gameplay_274.bin")

  for i in 0 ..< 20:
    let frame = if i mod 2 == 0: frame150 else: frame274
    discard b.stepUnpackedFrame(frame)
    let src = b.belief.directive.source
    expect(src != SourceLlm,
      &"tick {i+1}: directive source must not be SourceLlm " &
      "when the LLM provider is disabled (got " & $src & ")")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

proc main() =
  echo "=== fallback_test ==="

  echo "1. Validation gate (non-NOOP within 10 frames):"
  testValidationGate()

  echo "2. Mode transitions:"
  testModeTransitions()

  echo "3. No-crash full sequence:"
  testNoCrashFullSequence()

  echo "4. Default directive source:"
  testDefaultDirectiveSource()

  if failures > 0:
    stderr.writeLine &"\n{failures} FAILURE(S)"
    quit(1)
  else:
    echo &"\nOK — all fallback tests passed"

when isMainModule:
  main()
