import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import spatial_index
import test_utils

suite "Terrain - Elevation Traversal":
  test "flat movement allowed (same elevation)":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 0
    check env.canTraverseElevation(ivec2(50, 50), ivec2(51, 50)) == true

  test "cannot go up without ramp":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 1
    env.terrain[50][50] = Empty
    env.terrain[51][50] = Empty
    check env.canTraverseElevation(ivec2(50, 50), ivec2(51, 50)) == false

  test "can go up with ramp terrain":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 1
    env.terrain[50][50] = RampUpE  # Ramp going east (up)
    check env.canTraverseElevation(ivec2(50, 50), ivec2(51, 50)) == true

  test "can go up via road":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 1
    env.terrain[50][50] = Road
    check env.canTraverseElevation(ivec2(50, 50), ivec2(51, 50)) == true

  test "can always go down (drop off)":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 1
    env.elevation[51][50] = 0
    env.terrain[50][50] = Empty
    env.terrain[51][50] = Empty
    check env.canTraverseElevation(ivec2(50, 50), ivec2(51, 50)) == true

  test "cannot traverse more than 1 elevation difference":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 2
    check env.canTraverseElevation(ivec2(50, 50), ivec2(51, 50)) == false

  test "only cardinal movement (no diagonal)":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][51] = 0
    # Diagonal is abs(dx) + abs(dy) == 2, not 1
    check env.canTraverseElevation(ivec2(50, 50), ivec2(51, 51)) == false

suite "Terrain - Cliff Fall Damage":
  test "falling down without ramp causes damage":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 1
    env.elevation[51][50] = 0
    env.terrain[50][50] = Empty
    env.terrain[51][50] = Empty
    check env.willCauseCliffFallDamage(ivec2(50, 50), ivec2(51, 50)) == true

  test "going down with ramp does not cause damage":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 1
    env.elevation[51][50] = 0
    env.terrain[50][50] = RampDownE
    check env.willCauseCliffFallDamage(ivec2(50, 50), ivec2(51, 50)) == false

  test "going down via road does not cause damage":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 1
    env.elevation[51][50] = 0
    env.terrain[51][50] = Road
    check env.willCauseCliffFallDamage(ivec2(50, 50), ivec2(51, 50)) == false

  test "flat movement never causes fall damage":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 0
    check env.willCauseCliffFallDamage(ivec2(50, 50), ivec2(51, 50)) == false

  test "going up never causes fall damage":
    var env = makeEmptyEnv()
    env.elevation[50][50] = 0
    env.elevation[51][50] = 1
    env.terrain[50][50] = RampUpE
    check env.willCauseCliffFallDamage(ivec2(50, 50), ivec2(51, 50)) == false

suite "Terrain - Speed Modifiers":
  test "empty terrain has normal speed":
    check getTerrainSpeedModifier(Empty) == 1.0'f32

  test "mud is slowest terrain":
    check getTerrainSpeedModifier(Mud) == 0.7'f32

  test "snow slows movement":
    check getTerrainSpeedModifier(Snow) == 0.8'f32

  test "sand slows movement slightly":
    check getTerrainSpeedModifier(Sand) == 0.9'f32

  test "shallow water is slow":
    check getTerrainSpeedModifier(ShallowWater) == 0.5'f32

  test "road has normal speed":
    check getTerrainSpeedModifier(Road) == 1.0'f32

suite "Terrain - Terrain Classification":
  test "water is blocked terrain":
    check isBlockedTerrain(Water) == true

  test "empty is not blocked":
    check isBlockedTerrain(Empty) == false

  test "shallow water is water terrain":
    check isWaterTerrain(ShallowWater) == true
    check isWaterTerrain(Water) == true

  test "non-water is not water terrain":
    check isWaterTerrain(Empty) == false
    check isWaterTerrain(Grass) == false

  test "ramps are ramp terrain":
    check isRampTerrain(RampUpN) == true
    check isRampTerrain(RampDownS) == true
    check isRampTerrain(RampUpE) == true
    check isRampTerrain(RampDownW) == true

  test "non-ramps are not ramp terrain":
    check isRampTerrain(Empty) == false
    check isRampTerrain(Road) == false

  test "buildable terrain includes common types":
    check isBuildableTerrain(Empty) == true
    check isBuildableTerrain(Grass) == true
    check isBuildableTerrain(Sand) == true
    check isBuildableTerrain(Road) == true

  test "water is not buildable":
    check isBuildableTerrain(Water) == false
    check isBuildableTerrain(ShallowWater) == false

suite "Terrain - Placement Validation":
  test "canPlace checks terrain and emptiness":
    var env = makeEmptyEnv()
    env.terrain[50][50] = Empty
    check env.canPlace(ivec2(50, 50)) == true

  test "canPlace rejects water terrain":
    var env = makeEmptyEnv()
    env.terrain[50][50] = Water
    check env.canPlace(ivec2(50, 50)) == false

  test "canPlace rejects occupied tile":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    env.terrain[50][50] = Empty
    let agent = env.addAgentAt(0, ivec2(50, 50))
    check env.canPlace(ivec2(50, 50)) == false

  test "canPlaceDock requires water":
    var env = makeEmptyEnv()
    env.terrain[50][50] = Water
    check env.canPlaceDock(ivec2(50, 50)) == true

  test "canPlaceDock rejects land":
    var env = makeEmptyEnv()
    env.terrain[50][50] = Empty
    check env.canPlaceDock(ivec2(50, 50)) == false

  test "invalid position rejected":
    var env = makeEmptyEnv()
    check env.canPlace(ivec2(-1, -1)) == false
    check env.canTraverseElevation(ivec2(-1, -1), ivec2(50, 50)) == false
