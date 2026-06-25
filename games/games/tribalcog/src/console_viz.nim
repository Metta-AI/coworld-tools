## ANSI console rendering helpers for headless map visualization.

import
  envconfig, items, registry, types

const
  Esc = "\e["
  Reset = Esc & "0m"
  Bold = Esc & "1m"
  ClearScreen = Esc & "2J" & Esc & "H"
  TeamFg: array[8, array[3, int]] = [
    [232, 107, 107],
    [240, 166, 107],
    [240, 209, 107],
    [153, 214, 128],
    [199, 97, 224],
    [107, 184, 240],
    [222, 222, 222],
    [237, 143, 209]
  ]

let
  consoleVizEnabled* = parseEnvBool("TV_CONSOLE_VIZ", false)
  consoleVizInterval* = max(1, parseEnvInt("TV_VIZ_INTERVAL", 10))

proc fg(r, g, b: int): string =
  ## Return one ANSI foreground color escape sequence.
  Esc & "38;2;" & $r & ";" & $g & ";" & $b & "m"

proc bg(r, g, b: int): string =
  ## Return one ANSI background color escape sequence.
  Esc & "48;2;" & $r & ";" & $g & ";" & $b & "m"

proc terrainBg(terrainType: TerrainType): string =
  ## Return the console background color for one terrain type.
  case terrainType
  of Water:
    bg(20, 40, 120)
  of ShallowWater:
    bg(40, 80, 150)
  of Bridge:
    bg(120, 90, 50)
  of Fertile:
    bg(50, 100, 30)
  of Road:
    bg(130, 120, 100)
  of Grass:
    bg(40, 80, 30)
  of Dune, Sand:
    bg(160, 140, 80)
  of Snow:
    bg(200, 200, 210)
  of Mud:
    bg(80, 60, 40)
  of Mountain:
    bg(60, 55, 50)
  of Empty:
    bg(10, 10, 10)
  of RampUpN, RampUpS, RampUpW, RampUpE,
     RampDownN, RampDownS, RampDownW, RampDownE:
    bg(90, 85, 75)

proc thingChar(kind: ThingKind): char =
  ## Return the console glyph for one thing kind.
  case kind
  of Agent:
    'A'
  of Wall:
    '#'
  of Door:
    '+'
  of Tree:
    'T'
  of Wheat:
    'w'
  of Fish:
    'f'
  of Stone:
    'o'
  of Gold:
    '$'
  of Bush, Cactus:
    ','
  of Stalagmite:
    '^'
  of Relic:
    '*'
  of Magma:
    '~'
  of Altar:
    '&'
  of Spawner:
    'S'
  of Tumor:
    '%'
  of Cow:
    'c'
  of Bear:
    'B'
  of Wolf:
    'W'
  of Corpse, Skeleton:
    'x'
  of TownCenter:
    'H'
  of House:
    'h'
  of Barracks:
    'b'
  of ArcheryRange:
    'a'
  of Stable:
    's'
  of SiegeWorkshop, MangonelWorkshop, TrebuchetWorkshop:
    'E'
  of Castle:
    'C'
  of Monastery:
    'm'
  of Temple:
    'P'
  of University:
    'u'
  of Wonder:
    '!'
  of ControlPoint:
    '@'
  of Market:
    'M'
  of Blacksmith:
    'K'
  of GuardTower, Outpost:
    't'
  of Dock:
    'D'
  of Mill:
    'i'
  of Granary:
    'g'
  of LumberCamp:
    'l'
  of Quarry:
    'q'
  of MiningCamp:
    'n'
  of Lantern:
    '.'
  of Barrel:
    'O'
  of Stump, Stubble:
    '`'
  of ClayOven:
    'v'
  of WeavingLoom:
    '='
  of GoblinHive:
    'Z'
  of GoblinHut:
    'z'
  of GoblinTotem:
    'j'
  of CliffEdgeN, CliffEdgeE, CliffEdgeS, CliffEdgeW,
     CliffCornerInNE, CliffCornerInSE, CliffCornerInSW, CliffCornerInNW,
     CliffCornerOutNE, CliffCornerOutSE, CliffCornerOutSW, CliffCornerOutNW:
    '|'
  of WaterfallN, WaterfallE, WaterfallS, WaterfallW:
    '~'

proc unitClassChar(unitClass: AgentUnitClass): char =
  ## Return the console glyph for one unit class.
  case unitClass
  of UnitVillager:
    'v'
  of UnitManAtArms, UnitLongSwordsman, UnitChampion:
    'm'
  of UnitArcher, UnitCrossbowman, UnitArbalester:
    'a'
  of UnitScout, UnitLightCavalry, UnitHussar:
    's'
  of UnitKnight:
    'k'
  of UnitMonk:
    'p'
  of UnitBatteringRam:
    'r'
  of UnitMangonel:
    'g'
  of UnitTrebuchet:
    't'
  of UnitGoblin:
    'G'
  of UnitBoat:
    'b'
  of UnitTradeCog:
    'c'
  of UnitSamurai:
    'S'
  of UnitLongbowman:
    'L'
  of UnitCataphract:
    'C'
  of UnitWoadRaider:
    'W'
  of UnitTeutonicKnight:
    'T'
  of UnitHuskarl:
    'H'
  of UnitMameluke:
    'M'
  of UnitJanissary:
    'J'
  of UnitKing:
    'K'
  of UnitGalley:
    'y'
  of UnitFireShip:
    'f'
  of UnitFishingShip:
    'F'
  of UnitTransportShip:
    'P'
  of UnitDemoShip:
    'D'
  of UnitCannonGalleon:
    'N'
  of UnitScorpion:
    'x'
  of UnitCavalier, UnitPaladin:
    'k'
  of UnitCamel, UnitHeavyCamel, UnitImperialCamel:
    'l'
  of UnitSkirmisher, UnitEliteSkirmisher:
    'i'
  of UnitCavalryArcher, UnitHeavyCavalryArcher:
    'q'
  of UnitHandCannoneer:
    'h'

proc printGameMap*(env: Environment) =
  ## Render the map as ANSI-colored text with one glyph per tile.
  var buf = newStringOfCap(MapWidth * MapHeight * 20)
  buf.add(ClearScreen)
  buf.add(Bold & "=== tribal-village step " & $env.currentStep & " ===")
  buf.add(Reset & "\n")

  for y in 0 ..< MapHeight:
    for x in 0 ..< MapWidth:
      let
        terrainType = env.terrain[x][y]
        gridThing = env.grid[x][y]
        bgThing = env.backgroundGrid[x][y]
        terrainColor = terrainBg(terrainType)

      if not gridThing.isNil:
        if gridThing.kind == Agent:
          let teamColor = TeamFg[getTeamId(gridThing) mod 8]
          buf.add(terrainColor & fg(teamColor[0], teamColor[1], teamColor[2]))
          buf.add(Bold)
          buf.add(unitClassChar(gridThing.unitClass))
          buf.add(Reset)
        else:
          if gridThing.teamId >= 0 and gridThing.teamId < 8:
            let teamColor = TeamFg[gridThing.teamId]
            buf.add(
              terrainColor & fg(teamColor[0], teamColor[1], teamColor[2]) &
              Bold
            )
          else:
            buf.add(terrainColor & fg(180, 180, 180))
          buf.add(thingChar(gridThing.kind))
          buf.add(Reset)
      elif not bgThing.isNil:
        case bgThing.kind
        of Tree, Bush, Cactus, Stalagmite, Stubble:
          buf.add(terrainColor & fg(30, 140, 30))
        of Gold:
          buf.add(terrainColor & fg(255, 215, 0))
        of Stone:
          buf.add(terrainColor & fg(160, 160, 160))
        of Wheat:
          buf.add(terrainColor & fg(220, 200, 80))
        of Fish:
          buf.add(terrainColor & fg(100, 180, 220))
        of Relic:
          buf.add(terrainColor & fg(255, 100, 255))
        of Magma:
          buf.add(terrainColor & fg(255, 80, 20))
        else:
          buf.add(terrainColor & fg(140, 140, 140))
        buf.add(thingChar(bgThing.kind))
        buf.add(Reset)
      else:
        buf.add(terrainColor & " " & Reset)
    buf.add("\n")

  stdout.write(buf)
  stdout.flushFile()

proc printGameHUD*(env: Environment) =
  ## Print the per-team resource summary below the map.
  var buf = newStringOfCap(2048)
  buf.add("\n" & Bold & "--- HUD ---" & Reset & "\n")

  for teamId in 0 ..< MapRoomObjectsTeams:
    let
      teamColor = TeamFg[teamId]
      stockpile = env.teamStockpiles[teamId]
    var
      pop = 0
      mil = 0
      buildingCount = 0

    for agent in env.liveAgents:
      if not isAgentAlive(env, agent):
        continue
      if getTeamId(agent) != teamId:
        continue
      inc pop
      if agent.unitClass != UnitVillager:
        inc mil

    for kind in ThingKind:
      if not isBuildingKind(kind):
        continue
      for thing in env.thingsByKind[kind]:
        if not thing.hasValue:
          continue
        if thing.teamId == teamId:
          inc buildingCount

    buf.add(fg(teamColor[0], teamColor[1], teamColor[2]) & Bold)
    buf.add("T" & $teamId)
    buf.add(Reset & " ")
    buf.add("F:" & $stockpile.counts[ResourceFood])
    buf.add(" W:" & $stockpile.counts[ResourceWood])
    buf.add(" G:" & $stockpile.counts[ResourceGold])
    buf.add(" S:" & $stockpile.counts[ResourceStone])
    buf.add(" | Pop:" & $pop)
    buf.add(" Mil:" & $mil)
    buf.add(" Bld:" & $buildingCount)
    buf.add("\n")

  stdout.write(buf)
  stdout.flushFile()

proc maybeRenderConsole*(env: Environment) =
  ## Render the console view when the feature flag and interval match.
  if not consoleVizEnabled:
    return
  if env.currentStep mod consoleVizInterval != 0:
    return
  env.printGameMap()
  env.printGameHUD()
