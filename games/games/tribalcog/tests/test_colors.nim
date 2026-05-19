## Color and Tint Tests: Tests for color constants, tint calculations, and frozen state
##
## Tests verify:
## - TileColor constants are valid
## - combinedTileTint blends base and overlay colors correctly
## - isTileFrozen/isThingFrozen check frozen state accurately
## - Team color palette is distinct and valid

import std/unittest
import environment
import common
import types
import test_utils

const
  Epsilon = 0.001'f32  # Tolerance for float comparisons

proc approxEqual(a, b: float32, eps: float32 = Epsilon): bool =
  abs(a - b) < eps

# ---------------------------------------------------------------------------
# TileColor Constants Tests
# ---------------------------------------------------------------------------

suite "Colors: TileColor Constants":
  test "BaseTileColorDefault has valid values":
    check BaseTileColorDefault.r >= 0 and BaseTileColorDefault.r <= 1
    check BaseTileColorDefault.g >= 0 and BaseTileColorDefault.g <= 1
    check BaseTileColorDefault.b >= 0 and BaseTileColorDefault.b <= 1
    check BaseTileColorDefault.intensity > 0
    echo "  BaseTileColorDefault: r=", BaseTileColorDefault.r, " g=", BaseTileColorDefault.g, " b=", BaseTileColorDefault.b

  test "biome colors have valid RGB values":
    let biomeColors = [
      BiomeColorForest,
      BiomeColorDesert,
      BiomeColorCaves,
      BiomeColorCity,
      BiomeColorPlains,
      BiomeColorSwamp,
      BiomeColorDungeon,
      BiomeColorSnow
    ]
    for bc in biomeColors:
      check bc.r >= 0 and bc.r <= 1.5  # Allow slight overbright for intensity
      check bc.g >= 0 and bc.g <= 1.5
      check bc.b >= 0 and bc.b <= 1.5
      check bc.intensity >= 0.5 and bc.intensity <= 1.5
    echo "  All 8 biome colors have valid RGB/intensity values"

  test "biome colors are visually distinct":
    let biomeColors = [
      BiomeColorForest,
      BiomeColorDesert,
      BiomeColorCaves,
      BiomeColorCity,
      BiomeColorPlains,
      BiomeColorSwamp,
      BiomeColorDungeon,
      BiomeColorSnow
    ]
    # Check that no two biome colors are identical
    for i in 0 ..< biomeColors.len:
      for j in (i + 1) ..< biomeColors.len:
        let c1 = biomeColors[i]
        let c2 = biomeColors[j]
        let diff = abs(c1.r - c2.r) + abs(c1.g - c2.g) + abs(c1.b - c2.b)
        check diff > 0.1  # Must differ by at least 0.1 total
    echo "  All biome colors are visually distinct"

  test "ClippyTint has expected purple tint":
    # Clippy tint should be bluish/purple
    check ClippyTint.b > ClippyTint.r
    check ClippyTint.b > ClippyTint.g
    check ClippyTint.intensity > 0
    echo "  ClippyTint: r=", ClippyTint.r, " g=", ClippyTint.g, " b=", ClippyTint.b

# ---------------------------------------------------------------------------
# Team Color Palette Tests
# ---------------------------------------------------------------------------

suite "Colors: Team Color Palette":
  test "WarmTeamPalette has 8 distinct colors":
    check WarmTeamPalette.len == 8
    echo "  WarmTeamPalette has ", WarmTeamPalette.len, " colors"

  test "team colors have valid RGBA values":
    for i, tc in WarmTeamPalette:
      check tc.r >= 0 and tc.r <= 1
      check tc.g >= 0 and tc.g <= 1
      check tc.b >= 0 and tc.b <= 1
      check tc.a == 1.0  # Full opacity for team colors
    echo "  All team colors have valid RGBA (alpha=1.0)"

  test "team colors are visually distinct":
    for i in 0 ..< WarmTeamPalette.len:
      for j in (i + 1) ..< WarmTeamPalette.len:
        let c1 = WarmTeamPalette[i]
        let c2 = WarmTeamPalette[j]
        let diff = abs(c1.r - c2.r) + abs(c1.g - c2.g) + abs(c1.b - c2.b)
        check diff > 0.15  # Teams must be visually distinguishable
    echo "  All 8 team colors are visually distinct"

  test "team 0 is reddish (soft red)":
    let team0 = WarmTeamPalette[0]
    check team0.r > team0.g
    check team0.r > team0.b
    echo "  Team 0 has dominant red channel"

  test "team 5 is bluish (soft sky)":
    let team5 = WarmTeamPalette[5]
    check team5.b > team5.r
    check team5.b > team5.g
    echo "  Team 5 has dominant blue channel"

# ---------------------------------------------------------------------------
# Combined Tile Tint Tests
# ---------------------------------------------------------------------------

suite "Colors: Combined Tile Tint Blending":
  test "no overlay returns base color":
    let env = makeEmptyEnv()
    let x = 50
    let y = 50
    env.baseTintColors[x][y] = BaseTileColorDefault
    env.computedTintColors[x][y] = TileColor(r: 0, g: 0, b: 0, intensity: 0)
    env.tintLocked[x][y] = false

    let result = combinedTileTint(env, x, y)

    check approxEqual(result.r, BaseTileColorDefault.r)
    check approxEqual(result.g, BaseTileColorDefault.g)
    check approxEqual(result.b, BaseTileColorDefault.b)
    echo "  Zero-alpha overlay returns base color unchanged"

  test "full overlay replaces base color":
    let env = makeEmptyEnv()
    let x = 50
    let y = 50
    env.baseTintColors[x][y] = BaseTileColorDefault
    let overlayColor = TileColor(r: 1.0, g: 0.0, b: 0.0, intensity: 1.0)
    env.computedTintColors[x][y] = overlayColor
    env.tintLocked[x][y] = false

    let result = combinedTileTint(env, x, y)

    # With intensity=1.0, overlay should dominate
    check result.r > 0.9
    check result.g < 0.1
    check result.b < 0.1
    echo "  Full-intensity overlay dominates base color"

  test "half-alpha blends base and overlay":
    let env = makeEmptyEnv()
    let x = 50
    let y = 50
    let baseColor = TileColor(r: 1.0, g: 1.0, b: 1.0, intensity: 1.0)  # White
    let overlayColor = TileColor(r: 0.0, g: 0.0, b: 0.0, intensity: 0.5)  # 50% black
    env.baseTintColors[x][y] = baseColor
    env.computedTintColors[x][y] = overlayColor
    env.tintLocked[x][y] = false

    let result = combinedTileTint(env, x, y)

    # Should be roughly 50% gray
    check result.r > 0.4 and result.r < 0.6
    check result.g > 0.4 and result.g < 0.6
    check result.b > 0.4 and result.b < 0.6
    echo "  Half-alpha overlay creates 50% blend"

  test "locked tile ignores overlay":
    let env = makeEmptyEnv()
    let x = 50
    let y = 50
    env.baseTintColors[x][y] = BaseTileColorDefault
    env.computedTintColors[x][y] = TileColor(r: 1.0, g: 0.0, b: 0.0, intensity: 1.0)
    env.tintLocked[x][y] = true  # Locked!

    let result = combinedTileTint(env, x, y)

    # Should return base color unchanged due to lock
    check approxEqual(result.r, BaseTileColorDefault.r)
    check approxEqual(result.g, BaseTileColorDefault.g)
    check approxEqual(result.b, BaseTileColorDefault.b)
    echo "  Locked tiles return base color only"

  test "clamps overlay intensity to 0-1 range":
    let env = makeEmptyEnv()
    let x = 50
    let y = 50
    env.baseTintColors[x][y] = BaseTileColorDefault
    # Negative intensity should be clamped to 0
    env.computedTintColors[x][y] = TileColor(r: 1.0, g: 0.0, b: 0.0, intensity: -0.5)
    env.tintLocked[x][y] = false

    let result = combinedTileTint(env, x, y)

    # Negative intensity clamped to 0 means no overlay effect
    check approxEqual(result.r, BaseTileColorDefault.r)
    echo "  Negative intensity clamped to zero"

# ---------------------------------------------------------------------------
# Frozen State Tests
# ---------------------------------------------------------------------------

suite "Colors: Frozen State Detection":
  test "unfrozen tile returns false":
    let env = makeEmptyEnv()
    let pos = ivec2(50, 50)
    env.frozenTiles[pos.x][pos.y] = false

    check not isTileFrozen(pos, env)
    echo "  Unfrozen tile correctly detected"

  test "frozen tile returns true":
    let env = makeEmptyEnv()
    let pos = ivec2(50, 50)
    env.frozenTiles[pos.x][pos.y] = true

    check isTileFrozen(pos, env)
    echo "  Frozen tile correctly detected"

  test "invalid position returns false":
    let env = makeEmptyEnv()
    let invalidPos = ivec2(-1, -1)

    check not isTileFrozen(invalidPos, env)
    echo "  Invalid position safely returns false"

  test "edge positions are valid":
    let env = makeEmptyEnv()
    # Test corners
    env.frozenTiles[0][0] = true
    env.frozenTiles[MapWidth-1][MapHeight-1] = true

    check isTileFrozen(ivec2(0, 0), env)
    check isTileFrozen(ivec2(MapWidth-1, MapHeight-1), env)
    echo "  Edge positions work correctly"

  test "unfrozen thing on unfrozen tile returns false":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.frozen = 0
    env.frozenTiles[50][50] = false

    check not isThingFrozen(agent, env)
    echo "  Unfrozen thing on unfrozen tile = not frozen"

  test "frozen thing returns true regardless of tile":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.frozen = 1  # Explicitly frozen
    env.frozenTiles[50][50] = false

    check isThingFrozen(agent, env)
    echo "  Explicitly frozen thing = frozen"

  test "unfrozen thing on frozen tile returns true":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.frozen = 0
    env.frozenTiles[50][50] = true  # Tile is frozen

    check isThingFrozen(agent, env)
    echo "  Thing on frozen tile = frozen"

  test "frozen thing on frozen tile returns true":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(50, 50))
    agent.frozen = 1
    env.frozenTiles[50][50] = true

    check isThingFrozen(agent, env)
    echo "  Frozen thing on frozen tile = frozen"

# ---------------------------------------------------------------------------
# UI Colors Tests
# ---------------------------------------------------------------------------

suite "Colors: UI Color Constants":
  test "UI background colors have alpha":
    check UiBg.a > 0.9
    check UiBgHeader.a > 0.9
    check UiBgButton.a > 0.8
    echo "  UI backgrounds have high alpha"

  test "UI text colors are readable":
    # Primary text should be light (for dark theme)
    check UiFgText.r > 0.8
    check UiFgText.g > 0.8
    check UiFgText.b > 0.8
    # Dim text should be less bright
    check UiFgDim.r < UiFgText.r
    echo "  Text colors have proper contrast hierarchy"

  test "health bar colors follow traffic light pattern":
    # High health = green
    check UiHealthHigh.g > UiHealthHigh.r
    check UiHealthHigh.g > UiHealthHigh.b
    # Mid health = yellow/orange
    check UiHealthMid.r > UiHealthMid.b
    check UiHealthMid.g > UiHealthMid.b
    # Low health = red
    check UiHealthLow.r > UiHealthLow.g
    check UiHealthLow.r > UiHealthLow.b
    echo "  Health bars: green->yellow->red"

  test "semantic colors are distinct":
    # Success = green
    check UiSuccess.g > UiSuccess.r and UiSuccess.g > UiSuccess.b
    # Warning = yellow
    check UiWarning.r > UiWarning.b and UiWarning.g > UiWarning.b
    # Danger = red
    check UiDanger.r > UiDanger.g and UiDanger.r > UiDanger.b
    # Info = blue
    check UiInfo.b > UiInfo.r
    echo "  Semantic colors follow conventions"
