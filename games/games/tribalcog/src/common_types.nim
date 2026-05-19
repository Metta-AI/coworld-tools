## Shared game-logic types and small utility procedures.

when defined(emscripten):
  import windy/platforms/emscripten/emdefs
else:
  import std/[times]

import vmath

proc nowSeconds*(): float64 =
  ## Returns the current time in seconds.
  when defined(emscripten):
    emscripten_get_now() / 1000.0
  else:
    epochTime()

type
  IRect* = object
    x*: int
    y*: int
    w*: int
    h*: int

  Orientation* = enum
    N = 0
    S = 1
    W = 2
    E = 3
    NW = 4
    NE = 5
    SW = 6
    SE = 7

  CommandButtonKind* = enum
    CmdNone
    CmdMove
    CmdAttack
    CmdStop
    CmdPatrol
    CmdStance
    CmdHoldPosition
    CmdFormationLine
    CmdFormationBox
    CmdFormationStaggered
    CmdFormationRangedSpread
    CmdBuild
    CmdGather
    CmdBuildBack
    CmdBuildHouse
    CmdBuildMill
    CmdBuildLumberCamp
    CmdBuildMiningCamp
    CmdBuildBarracks
    CmdBuildArcheryRange
    CmdBuildStable
    CmdBuildWall
    CmdBuildBlacksmith
    CmdBuildMarket
    CmdSetRally
    CmdUngarrison
    CmdTrainVillager
    CmdTrainManAtArms
    CmdTrainArcher
    CmdTrainScout
    CmdTrainKnight
    CmdTrainMonk
    CmdTrainBatteringRam
    CmdTrainMangonel
    CmdTrainTrebuchet
    CmdTrainBoat
    CmdTrainTradeCog
    CmdTrainGalley
    CmdTrainFireShip
    CmdTrainFishingShip
    CmdTrainTransportShip
    CmdTrainDemoShip
    CmdTrainCannonGalleon
    CmdResearchMeleeAttack
    CmdResearchArcherAttack
    CmdResearchInfantryArmor
    CmdResearchCavalryArmor
    CmdResearchArcherArmor
    CmdResearchBallistics
    CmdResearchMurderHoles
    CmdResearchMasonry
    CmdResearchArchitecture
    CmdResearchTreadmillCrane
    CmdResearchArrowslits
    CmdResearchHeatedShot
    CmdResearchSiegeEngineers
    CmdResearchChemistry
    CmdResearchCoinage
    CmdResearchCastleTech1
    CmdResearchCastleTech2
    CmdQueueFarm

{.push inline.}
proc ivec2*(x, y: int): IVec2 =
  ## Creates an integer vector from two ints.
  result.x = x.int32
  result.y = y.int32

template chebyshevDist*(a, b: IVec2): int32 =
  ## Returns the Chebyshev distance between two positions.
  max(abs(a.x - b.x), abs(a.y - b.y))

template manhattanDist*(a, b: IVec2): int32 =
  ## Returns the Manhattan distance between two positions.
  abs(a.x - b.x) + abs(a.y - b.y)
{.pop.}

const
  OrientationDeltas* = [
    ivec2(0, -1),
    ivec2(0, 1),
    ivec2(-1, 0),
    ivec2(1, 0),
    ivec2(-1, -1),
    ivec2(1, -1),
    ivec2(-1, 1),
    ivec2(1, 1),
  ]
  ActionVerbCount* = 11
  ActionArgumentCount* = 28
  ActionNoop* = 0
  ActionMove* = 1
  ActionAttack* = 2
  ActionUse* = 3
  ActionSwap* = 4
  ActionPut* = 5
  ActionPlantLantern* = 6
  ActionPlantResource* = 7
  ActionBuild* = 8
  ActionOrient* = 9
  ActionSetRallyPoint* = 10
  ActionNames*: array[ActionVerbCount, string] = [
    "noop", "move", "attack", "use", "swap", "put",
    "plant_lantern", "plant_resource", "build", "orient", "set_rally_point"
  ]

proc encodeAction*(verb: uint16, argument: uint16): uint16 =
  ## Encodes one action verb and argument into a packed action.
  uint16(verb.int * ActionArgumentCount + argument.int)

{.push inline.}
proc orientationToVec*(orientation: Orientation): IVec2 =
  ## Returns the unit vector for one orientation.
  OrientationDeltas[orientation.int]
{.pop.}

const
  ScreenShakeDecayRate* = 0.85'f
    ## Multiplicative shake decay per frame.
  ScreenShakeMaxIntensity* = 8.0'f
    ## Maximum shake intensity in pixels.
  ScreenShakeDeathIntensity* = 4.0'f
    ## Shake intensity applied when a unit dies.

var
  screenShakeIntensity*: float32 = 0.0
    ## Current shake intensity.
  screenShakeOffset*: Vec2 = vec2(0, 0)
    ## Random shake offset for the current frame.
  screenShakeRng: uint32 = 12345
    ## Simple deterministic RNG state for shake.

proc screenShakeLcg(): float32 =
  ## Returns one deterministic random sample for screen shake.
  screenShakeRng = screenShakeRng * 1103515245'u32 + 12345'u32
  let normalized = (screenShakeRng.float32 / uint32.high.float32) * 2.0 - 1.0
  normalized

proc updateScreenShake*() =
  ## Updates screen shake by decaying intensity and sampling offsets.
  if screenShakeIntensity > 0.1:
    screenShakeOffset = vec2(
      screenShakeLcg() * screenShakeIntensity,
      screenShakeLcg() * screenShakeIntensity
    )
    screenShakeIntensity *= ScreenShakeDecayRate
  else:
    screenShakeIntensity = 0.0
    screenShakeOffset = vec2(0, 0)

var
  play*: bool = true
  playSpeed*: float32 = 0.1
  lastSimTime*: float64 = nowSeconds()

const
  SlowPlaySpeed* = 0.2
  FastPlaySpeed* = 0.02
  FasterPlaySpeed* = 0.005
  SuperPlaySpeed* = 0.001

const
  CardinalOffsets* = [
    ivec2(0, -1),
    ivec2(1, 0),
    ivec2(0, 1),
    ivec2(-1, 0)
  ]
  AdjacentOffsets8* = [
    ivec2(0, -1),
    ivec2(1, 0),
    ivec2(0, 1),
    ivec2(-1, 0),
    ivec2(1, -1),
    ivec2(1, 1),
    ivec2(-1, 1),
    ivec2(-1, -1)
  ]
