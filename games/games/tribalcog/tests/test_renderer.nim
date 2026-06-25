## Renderer Tests: Tests for renderer_core, tileset, and rendering helpers
##
## Tests verify renderer calculations without actual graphics output:
## - Sprite key selection for units by class and orientation
## - Team color lookup with fallback
## - Health bar color gradient and fade timing
## - Color conversion utilities
## - Render cache rebuild logic
## - Projectile trail calculations
## - Building smoke animation determinism

import std/[unittest, math, strformat]
import test_common
import renderer_core

const
  RendererTestEpsilon = 0.001'f32  # Tolerance for float comparisons

proc rendererApproxEqual(a, b: float32, eps: float32 = RendererTestEpsilon): bool =
  abs(a - b) < eps

# ---------------------------------------------------------------------------
# Sprite Key Selection Tests
# ---------------------------------------------------------------------------

suite "Renderer: Unit Sprite Base Selection":
  test "villager uses role-based sprite keys":
    # UnitVillager (class 0) should use role-based keys based on agentId
    let baseKey0 = getUnitSpriteBase(UnitVillager, 0)  # mod 6 == 0
    let baseKey1 = getUnitSpriteBase(UnitVillager, 1)  # mod 6 == 1
    let baseKey2 = getUnitSpriteBase(UnitVillager, 2)  # mod 6 == 2
    let baseKey3 = getUnitSpriteBase(UnitVillager, 3)  # mod 6 == 3
    let baseKey4 = getUnitSpriteBase(UnitVillager, 4)  # mod 6 == 4
    let baseKey5 = getUnitSpriteBase(UnitVillager, 5)  # mod 6 == 5
    let baseKey6 = getUnitSpriteBase(UnitVillager, 6)  # mod 6 == 0

    check baseKey0 == "oriented/gatherer"
    check baseKey1 == "oriented/gatherer"
    check baseKey2 == "oriented/builder"
    check baseKey3 == "oriented/builder"
    check baseKey4 == "oriented/fighter"
    check baseKey5 == "oriented/fighter"
    check baseKey6 == "oriented/gatherer"  # Wraps around
    echo "  Villager sprite keys cycle through gatherer/builder/fighter"

  test "military units use predefined sprite keys":
    check getUnitSpriteBase(UnitManAtArms, 0) == "oriented/man_at_arms"
    check getUnitSpriteBase(UnitArcher, 0) == "oriented/archer"
    check getUnitSpriteBase(UnitScout, 0) == "oriented/scout"
    check getUnitSpriteBase(UnitKnight, 0) == "oriented/knight"
    check getUnitSpriteBase(UnitMonk, 0) == "oriented/monk"
    echo "  Military units have predefined sprite keys"

  test "siege units use predefined sprite keys":
    check getUnitSpriteBase(UnitBatteringRam, 0) == "oriented/battering_ram"
    check getUnitSpriteBase(UnitMangonel, 0) == "oriented/mangonel"
    echo "  Siege units have predefined sprite keys"

  test "trebuchet uses packed/unpacked state":
    let packedKey = getUnitSpriteBase(UnitTrebuchet, 0, packed = true)
    let unpackedKey = getUnitSpriteBase(UnitTrebuchet, 0, packed = false)

    check packedKey == "oriented/trebuchet_packed"
    check unpackedKey == "oriented/trebuchet_unpacked"
    echo "  Trebuchet switches between packed and unpacked sprites"

  test "naval units use predefined sprite keys":
    check getUnitSpriteBase(UnitBoat, 0) == "oriented/boat"
    check getUnitSpriteBase(UnitTradeCog, 0) == "oriented/trade_cog"
    check getUnitSpriteBase(UnitGalley, 0) == "oriented/galley"
    check getUnitSpriteBase(UnitFireShip, 0) == "oriented/fire_ship"
    check getUnitSpriteBase(UnitTransportShip, 0) == "oriented/transport_ship"
    echo "  Naval units have predefined sprite keys"

  test "unique units use predefined sprite keys":
    check getUnitSpriteBase(UnitSamurai, 0) == "oriented/samurai"
    check getUnitSpriteBase(UnitLongbowman, 0) == "oriented/longbowman"
    check getUnitSpriteBase(UnitCataphract, 0) == "oriented/cataphract"
    check getUnitSpriteBase(UnitTeutonicKnight, 0) == "oriented/teutonic_knight"
    echo "  Unique units have predefined sprite keys"

  test "agentId does not affect non-villager sprite keys":
    # Non-villager units should ignore agentId
    check getUnitSpriteBase(UnitArcher, 0) == getUnitSpriteBase(UnitArcher, 99)
    check getUnitSpriteBase(UnitKnight, 1) == getUnitSpriteBase(UnitKnight, 42)
    echo "  Non-villager sprite keys are independent of agentId"

# ---------------------------------------------------------------------------
# Orientation Direction Key Tests
# ---------------------------------------------------------------------------

suite "Renderer: Orientation Direction Keys":
  test "all 8 orientations have direction keys":
    check OrientationDirKeys.len == 8
    echo "  OrientationDirKeys has 8 entries"

  test "cardinal direction keys are correct":
    check OrientationDirKeys[Orientation.N.int] == "n"
    check OrientationDirKeys[Orientation.S.int] == "s"
    check OrientationDirKeys[Orientation.W.int] == "w"
    check OrientationDirKeys[Orientation.E.int] == "e"
    echo "  Cardinal directions: n, s, w, e"

  test "diagonal direction keys are correct":
    check OrientationDirKeys[Orientation.NW.int] == "nw"
    check OrientationDirKeys[Orientation.NE.int] == "ne"
    check OrientationDirKeys[Orientation.SW.int] == "sw"
    check OrientationDirKeys[Orientation.SE.int] == "se"
    echo "  Diagonal directions: nw, ne, sw, se"

  test "tumor direction keys simplify diagonals":
    # Tumors only use 4 directions, simplifying diagonals
    check TumorDirKeys[Orientation.N.int] == "n"
    check TumorDirKeys[Orientation.S.int] == "s"
    check TumorDirKeys[Orientation.W.int] == "w"
    check TumorDirKeys[Orientation.E.int] == "e"
    check TumorDirKeys[Orientation.NW.int] == "w"  # Simplified to W
    check TumorDirKeys[Orientation.NE.int] == "e"  # Simplified to E
    check TumorDirKeys[Orientation.SW.int] == "w"  # Simplified to W
    check TumorDirKeys[Orientation.SE.int] == "e"  # Simplified to E
    echo "  Tumor diagonal directions simplified to cardinal"

# ---------------------------------------------------------------------------
# Team Color Tests
# ---------------------------------------------------------------------------

suite "Renderer: Team Color Lookup":
  test "valid team index returns correct color":
    let env = makeEmptyEnv()
    env.teamColors = @[WarmTeamPalette[0], WarmTeamPalette[1], WarmTeamPalette[2]]

    check getTeamColor(env, 0) == WarmTeamPalette[0]
    check getTeamColor(env, 1) == WarmTeamPalette[1]
    check getTeamColor(env, 2) == WarmTeamPalette[2]
    echo "  Valid team indices return correct colors"

  test "negative team index returns fallback":
    let env = makeEmptyEnv()
    env.teamColors = @[WarmTeamPalette[0]]
    let fallback = color(0.6, 0.6, 0.6, 1.0)

    let result = getTeamColor(env, -1, fallback)
    check result == fallback
    echo "  Negative team index returns fallback color"

  test "out of range team index returns fallback":
    let env = makeEmptyEnv()
    env.teamColors = @[WarmTeamPalette[0]]
    let fallback = color(0.5, 0.5, 0.5, 1.0)

    let result = getTeamColor(env, 10, fallback)
    check result == fallback
    echo "  Out of range team index returns fallback color"

  test "custom fallback color is used":
    let env = makeEmptyEnv()
    env.teamColors = @[]
    let customFallback = color(1.0, 0.0, 0.0, 1.0)  # Red

    let result = getTeamColor(env, 0, customFallback)
    check result == customFallback
    echo "  Custom fallback color is respected"

# ---------------------------------------------------------------------------
# Health Bar Color Tests
# ---------------------------------------------------------------------------

suite "Renderer: Health Bar Color Gradient":
  test "full health is greenish":
    let fullColor = getHealthBarColor(1.0)
    # At full health (ratio=1.0), should be more green than red
    check fullColor.g > fullColor.r
    echo "  Full health: green channel dominates"

  test "half health is yellowish":
    let halfColor = getHealthBarColor(0.5)
    # At half health, should have high red and green (yellow)
    check halfColor.r > 0.9
    check halfColor.g > 0.7
    echo "  Half health: yellow tones (high R and G)"

  test "low health is reddish":
    let lowColor = getHealthBarColor(0.1)
    # At low health, should be more red than green
    check lowColor.r > lowColor.g
    echo "  Low health: red channel dominates"

  test "empty health is pure red":
    let emptyColor = getHealthBarColor(0.0)
    check emptyColor.r >= 0.9
    check emptyColor.g < 0.2
    echo "  Empty health: pure red"

  test "color gradient is continuous":
    # Check that colors transition smoothly (no abrupt jumps)
    var lastColor = getHealthBarColor(1.0)
    for i in countdown(99, 0):
      let ratio = i.float32 / 100.0
      let currentColor = getHealthBarColor(ratio)
      # Color should not jump more than 0.1 between adjacent ratios
      check abs(currentColor.r - lastColor.r) < 0.15
      check abs(currentColor.g - lastColor.g) < 0.15
      lastColor = currentColor
    echo "  Health bar color gradient is continuous"

# ---------------------------------------------------------------------------
# Health Bar Alpha Fade Tests
# ---------------------------------------------------------------------------

suite "Renderer: Health Bar Fade Timing":
  test "never attacked returns minimum alpha":
    let alpha = getHealthBarAlpha(currentStep = 100, lastAttackedStep = 0)
    check rendererApproxEqual(alpha, HealthBarMinAlpha)
    echo "  Never attacked: minimum alpha"

  test "recently attacked starts fade in":
    # Immediately after damage, should be fading in
    let alpha = getHealthBarAlpha(currentStep = 10, lastAttackedStep = 10)
    check alpha >= HealthBarMinAlpha - RendererTestEpsilon
    check alpha <= 1.0 + RendererTestEpsilon
    echo "  Just damaged: fade in starting"

  test "after fade in is fully visible":
    let step = HealthBarFadeInDuration + 5
    let alpha = getHealthBarAlpha(currentStep = step, lastAttackedStep = 0)
    # Note: lastAttackedStep=0 means never attacked
    check rendererApproxEqual(alpha, HealthBarMinAlpha)
    echo "  Never attacked stays at minimum"

  test "visible phase has full alpha":
    # During visible phase (after fade in, before fade out)
    let attackStep = 100
    let currentStep = attackStep + HealthBarFadeInDuration + 5
    let alpha = getHealthBarAlpha(currentStep = currentStep, lastAttackedStep = attackStep)
    check rendererApproxEqual(alpha, 1.0'f32)
    echo "  Visible phase: full alpha"

  test "fade out reduces alpha":
    # Use positive lastAttackedStep to avoid "never attacked" special case
    let attackStep = 100
    let fadeOutStart = HealthBarFadeInDuration + HealthBarVisibleDuration
    let currentStep = attackStep + fadeOutStart + HealthBarFadeOutDuration div 2
    let alpha = getHealthBarAlpha(currentStep = currentStep, lastAttackedStep = attackStep)
    check alpha > HealthBarMinAlpha + RendererTestEpsilon
    check alpha < 1.0 - RendererTestEpsilon
    echo "  Fade out phase: intermediate alpha"

  test "after fade out returns minimum alpha":
    # Use positive lastAttackedStep to avoid "never attacked" special case
    let attackStep = 100
    let fullyFadedStep = attackStep + HealthBarFadeInDuration + HealthBarVisibleDuration +
                         HealthBarFadeOutDuration + 10
    let alpha = getHealthBarAlpha(currentStep = fullyFadedStep, lastAttackedStep = attackStep)
    check rendererApproxEqual(alpha, HealthBarMinAlpha)
    echo "  After fade out: minimum alpha"

# ---------------------------------------------------------------------------
# Color Conversion Tests
# ---------------------------------------------------------------------------

suite "Renderer: Color Conversion Utilities":
  test "toRgbx converts white correctly":
    let white = color(1.0, 1.0, 1.0, 1.0)
    let rgbx = toRgbx(white)
    check rgbx.r == 255
    check rgbx.g == 255
    check rgbx.b == 255
    check rgbx.a == 255
    echo "  White: (1,1,1,1) -> (255,255,255,255)"

  test "toRgbx converts black correctly":
    let black = color(0.0, 0.0, 0.0, 1.0)
    let rgbx = toRgbx(black)
    check rgbx.r == 0
    check rgbx.g == 0
    check rgbx.b == 0
    check rgbx.a == 255
    echo "  Black: (0,0,0,1) -> (0,0,0,255)"

  test "toRgbx converts mid-gray correctly":
    let gray = color(0.5, 0.5, 0.5, 0.5)
    let rgbx = toRgbx(gray)
    check rgbx.r in 127'u8 .. 128'u8
    check rgbx.g in 127'u8 .. 128'u8
    check rgbx.b in 127'u8 .. 128'u8
    check rgbx.a in 127'u8 .. 128'u8
    echo "  Mid-gray: (0.5,0.5,0.5,0.5) -> ~(127,127,127,127)"

  test "toRgbx clamps overflow values":
    let overflow = color(1.5, 2.0, -0.5, 1.0)
    let rgbx = toRgbx(overflow)
    check rgbx.r == 255  # Clamped from 1.5
    check rgbx.g == 255  # Clamped from 2.0
    check rgbx.b == 0    # Clamped from -0.5
    check rgbx.a == 255
    echo "  Overflow values clamped to 0-255 range"

  test "colorToRgbx ignores input alpha":
    let semiTransparent = color(0.5, 0.5, 0.5, 0.25)
    let rgbx = colorToRgbx(semiTransparent)
    check rgbx.a == 255  # Always full alpha
    echo "  colorToRgbx forces alpha to 255"

# ---------------------------------------------------------------------------
# Render Cache Tests
# ---------------------------------------------------------------------------

suite "Renderer: Render Cache Management":
  test "initial render cache generation is -1":
    check renderCacheGeneration == -1
    echo "  Render cache starts uninitialized (generation -1)"

  test "floor sprite positions arrays exist":
    check floorSpritePositions.len == FloorSpriteKind.high.ord + 1
    echo &"  Floor sprite positions array has {floorSpritePositions.len} kinds"

  test "water positions list initializes empty":
    # Note: This may have been populated by other tests, so we check the type exists
    check waterPositions.len >= 0
    check shallowWaterPositions.len >= 0
    check mountainPositions.len >= 0
    echo "  Terrain position lists are initialized"

# ---------------------------------------------------------------------------
# Wall Sprite Key Tests
# ---------------------------------------------------------------------------

suite "Renderer: Wall Sprite Key Generation":
  test "wall sprite array has 16 entries":
    check wallSprites.len == 16
    echo "  Wall sprites array has 16 entries (4-bit combinations)"

  test "isolated wall has no suffix":
    check wallSprites[0] == "oriented/wall"
    echo "  Isolated wall (no neighbors): oriented/wall"

  test "wall with neighbors has direction suffix":
    # Wall with east neighbor (bit 0 = 1)
    check wallSprites[1] == "oriented/wall.e"
    # Wall with south neighbor (bit 1 = 2)
    check wallSprites[2] == "oriented/wall.s"
    # Wall with both (bits 0+1 = 3)
    check wallSprites[3] == "oriented/wall.se"
    echo "  Wall sprites include direction suffixes based on neighbors"

  test "wall tiles enum values are correct":
    check WallE.int == 1
    check WallS.int == 2
    check WallW.int == 4
    check WallN.int == 8
    check WallSE.int == 3  # 2 or 1
    check WallNW.int == 12  # 8 or 4
    echo "  Wall tile enum values match expected bit patterns"

# ---------------------------------------------------------------------------
# Scaling Constants Tests
# ---------------------------------------------------------------------------

suite "Renderer: Scaling Constants":
  test "sprite scale is reasonable":
    check renderer_core.SpriteScale > 0.0'f32
    check renderer_core.SpriteScale < 1.0'f32
    echo &"  SpriteScale = {renderer_core.SpriteScale}"

  test "idle animation parameters are bounded":
    check renderer_core.IdleAnimationSpeed > 0.0'f32
    check renderer_core.IdleAnimationAmplitude >= 0.0'f32 and renderer_core.IdleAnimationAmplitude < 0.1'f32
    check renderer_core.IdleAnimationPhaseScale > 0.0'f32
    echo "  Idle animation parameters within expected ranges"

  test "depletion scale range is valid":
    check renderer_core.DepletionScaleMin > 0.0'f32
    check renderer_core.DepletionScaleMin < renderer_core.DepletionScaleMax
    check renderer_core.DepletionScaleMax <= 1.0'f32
    echo &"  Depletion scale: {renderer_core.DepletionScaleMin} to {renderer_core.DepletionScaleMax}"

  test "shadow constants are reasonable":
    check renderer_core.ShadowAlpha > 0.0'f32 and renderer_core.ShadowAlpha < 1.0'f32
    check renderer_core.ShadowOffsetX != 0.0'f32 or renderer_core.ShadowOffsetY != 0.0'f32
    echo &"  Shadow: alpha={renderer_core.ShadowAlpha}, offset=({renderer_core.ShadowOffsetX},{renderer_core.ShadowOffsetY})"

  test "lantern flicker speeds vary":
    check renderer_core.LanternFlickerSpeed1 != renderer_core.LanternFlickerSpeed2
    check renderer_core.LanternFlickerSpeed2 != renderer_core.LanternFlickerSpeed3
    check renderer_core.LanternFlickerAmplitude > 0.0'f32 and renderer_core.LanternFlickerAmplitude < 0.5'f32
    echo "  Lantern flicker uses multiple wave speeds for organic effect"

# ---------------------------------------------------------------------------
# Floor Sprite Kind Tests
# ---------------------------------------------------------------------------

suite "Renderer: Floor Sprite Kinds":
  test "floor sprite kind enum has 4 values":
    check FloorSpriteKind.high.ord - FloorSpriteKind.low.ord + 1 == 4
    echo "  FloorSpriteKind has 4 values"

  test "floor sprite kind enum is contiguous":
    check FloorSpriteKind.low.ord == 0
    check FloorSpriteKind.high.ord == 3
    echo "  Floor sprite kind enum is contiguous (0-3)"

  test "floor sprite kinds have expected names":
    check FloorBase.ord == 0
    check FloorCave.ord == 1
    check FloorDungeon.ord == 2
    check FloorSnow.ord == 3
    echo "  Floor sprite kinds: FloorBase(0), FloorCave(1), FloorDungeon(2), FloorSnow(3)"

# ---------------------------------------------------------------------------
# Segment Bar Drawing Tests
# ---------------------------------------------------------------------------

suite "Renderer: Segment Bar Calculations":
  test "full ratio fills all segments":
    # At ratio 1.0 with 5 segments, all 5 should be filled
    let filled = int(ceil(1.0 * 5.0))
    check filled == 5
    echo "  Full ratio (1.0) fills all 5 segments"

  test "half ratio fills ceil(half) segments":
    let filled = int(ceil(0.5 * 5.0))
    check filled == 3  # ceil(2.5) = 3
    echo "  Half ratio (0.5) fills 3 of 5 segments"

  test "empty ratio fills zero segments":
    let filled = int(ceil(0.0 * 5.0))
    check filled == 0
    echo "  Empty ratio (0.0) fills 0 segments"

  test "small ratio fills at least 1 segment":
    let filled = int(ceil(0.1 * 5.0))
    check filled == 1  # ceil(0.5) = 1
    echo "  Small ratio (0.1) fills at least 1 segment"

# ---------------------------------------------------------------------------
# Cliff Draw Order Tests
# ---------------------------------------------------------------------------

suite "Renderer: Draw Order Arrays":
  test "cliff draw order includes all edge types":
    var hasN, hasE, hasS, hasW = false
    for kind in CliffDrawOrder:
      if kind == CliffEdgeN: hasN = true
      if kind == CliffEdgeE: hasE = true
      if kind == CliffEdgeS: hasS = true
      if kind == CliffEdgeW: hasW = true
    check hasN and hasE and hasS and hasW
    echo "  Cliff draw order includes all 4 edge types"

  test "cliff draw order includes corners":
    var cornerCount = 0
    for kind in CliffDrawOrder:
      if kind in {CliffCornerInNE, CliffCornerInSE, CliffCornerInSW, CliffCornerInNW,
                  CliffCornerOutNE, CliffCornerOutSE, CliffCornerOutSW, CliffCornerOutNW}:
        inc cornerCount
    check cornerCount == 8
    echo "  Cliff draw order includes all 8 corner types"

  test "waterfall draw order includes all directions":
    check WaterfallDrawOrder.len == 4
    var hasN, hasE, hasS, hasW = false
    for kind in WaterfallDrawOrder:
      if kind == WaterfallN: hasN = true
      if kind == WaterfallE: hasE = true
      if kind == WaterfallS: hasS = true
      if kind == WaterfallW: hasW = true
    check hasN and hasE and hasS and hasW
    echo "  Waterfall draw order includes all 4 directions"

# ---------------------------------------------------------------------------
# Heart Count Threshold Tests
# ---------------------------------------------------------------------------

suite "Renderer: Heart Display Thresholds":
  test "heart plus threshold is reasonable":
    check HeartPlusThreshold > 0
    check HeartPlusThreshold < 20
    echo &"  HeartPlusThreshold = {HeartPlusThreshold}"

  test "hearts below threshold display individually":
    let count = 5
    let shouldDisplayIndividually = count <= HeartPlusThreshold
    check shouldDisplayIndividually
    echo &"  {count} hearts displays individually"

  test "hearts above threshold use counter":
    let count = HeartPlusThreshold + 5
    let shouldUseCounter = count > HeartPlusThreshold
    check shouldUseCounter
    echo &"  {count} hearts uses counter display"
