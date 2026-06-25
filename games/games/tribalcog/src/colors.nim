## Shared color constants and tint helpers.

const
  # Primary colors
  Turquoise*   = parseHtmlColor("#1abc9c").color  ## Turquoise
  Teal*        = parseHtmlColor("#16a085").color  ## Green Sea
  Green*       = parseHtmlColor("#2ecc71").color  ## Emerald
  DarkGreen*   = parseHtmlColor("#27ae60").color  ## Nephritis
  Blue*        = parseHtmlColor("#3498db").color  ## Peter River
  DarkBlue*    = parseHtmlColor("#2980b9").color  ## Belize Hole
  Purple*      = parseHtmlColor("#9b59b6").color  ## Amethyst
  DarkPurple*  = parseHtmlColor("#8e44ad").color  ## Wisteria

  # Neutrals (dark theme base)
  Slate*       = parseHtmlColor("#34495e").color  ## Wet Asphalt
  MidnightBlue* = parseHtmlColor("#2c3e50").color ## Midnight Blue

  # Warm accent colors
  Yellow*      = parseHtmlColor("#f1c40f").color  ## Sun Flower
  Orange*      = parseHtmlColor("#f39c12").color  ## Orange
  DarkOrange*  = parseHtmlColor("#e67e22").color  ## Carrot
  Pumpkin*     = parseHtmlColor("#d35400").color  ## Pumpkin
  Red*         = parseHtmlColor("#e74c3c").color  ## Alizarin
  DarkRed*     = parseHtmlColor("#c0392b").color  ## Pomegranate

  # Light neutrals
  Cloud*       = parseHtmlColor("#ecf0f1").color  ## Clouds
  Silver*      = parseHtmlColor("#bdc3c7").color  ## Silver
  Gray*        = parseHtmlColor("#95a5a6").color  ## Concrete
  DarkGray*    = parseHtmlColor("#7f8c8d").color  ## Asbestos

const
  # Panel backgrounds
  UiBg*         = color(0.08, 0.10, 0.14, 0.95)   ## Main panel background (near MidnightBlue)
  UiBgHeader*   = color(0.15, 0.19, 0.25, 0.95)   ## Header/footer background (Slate-based)
  UiBgButton*   = color(0.20, 0.24, 0.28, 0.90)   ## Button background
  UiBgButtonHover* = color(0.28, 0.32, 0.38, 0.95) ## Button hover state
  UiBgButtonDisabled* = color(0.15, 0.18, 0.22, 0.70) ## Button disabled state
  UiBgButtonActive* = color(0.20, 0.50, 0.70, 0.95) ## Button active/pressed state

  # Text colors
  UiFgText*     = color(0.90, 0.90, 0.90, 1.0)    ## Primary text
  UiFgBright*   = color(1.0, 0.9, 0.7, 1.0)       ## Highlight text (titles, emphasis)
  UiFgDim*      = color(0.60, 0.65, 0.70, 1.0)    ## Dimmed/disabled text
  UiFgMuted*    = color(0.50, 0.55, 0.60, 1.0)    ## Very muted text

  # Border colors
  UiBorder*     = color(0.30, 0.35, 0.40, 0.80)   ## Standard border
  UiBorderBright* = color(0.50, 0.60, 0.70, 0.80) ## Highlighted border (hover)

  # Semantic colors (status indicators)
  UiSuccess*    = color(0.18, 0.80, 0.44, 1.0)    ## Success/positive (Green-based)
  UiWarning*    = color(0.95, 0.77, 0.06, 1.0)    ## Warning (Yellow-based)
  UiDanger*     = color(0.91, 0.30, 0.24, 1.0)    ## Error/danger (Red-based)
  UiInfo*       = color(0.20, 0.60, 0.86, 1.0)    ## Info/neutral (Blue-based)

  # Tooltip-specific colors
  UiTooltipBg*  = color(0.08, 0.10, 0.14, 0.95)   ## Tooltip background
  UiTooltipBorder* = color(0.30, 0.35, 0.40, 0.80) ## Tooltip border
  UiTooltipTitle* = color(1.0, 0.9, 0.7, 1.0)     ## Tooltip title
  UiTooltipText* = color(0.90, 0.90, 0.90, 1.0)   ## Tooltip body text
  UiTooltipCost* = color(0.70, 0.85, 1.0, 1.0)    ## Tooltip cost lines
  UiTooltipHotkey* = color(0.60, 0.80, 0.60, 1.0) ## Tooltip hotkey hints
  UiTooltipRequirement* = color(1.0, 0.70, 0.50, 1.0) ## Tooltip requirements

  # Health bar colors
  UiHealthHigh* = color(0.10, 0.80, 0.10, 1.0)    ## Health > 50%
  UiHealthMid*  = color(0.90, 0.70, 0.10, 1.0)    ## Health 25-50%
  UiHealthLow*  = color(0.90, 0.20, 0.10, 1.0)    ## Health < 25%
  UiHealthBg*   = color(0.20, 0.20, 0.20, 0.90)   ## Health bar background

  # Selection/highlight colors
  UiSelection*  = color(0.20, 0.90, 0.20, 1.0)    ## Selection highlight
  UiHover*      = color(0.30, 0.70, 0.90, 0.80)   ## Hover highlight

  # Selection glow
  UiSelectionGlow* = color(0.3, 0.7, 1.0, 0.4)    ## Blue selection glow base

  # Panel backgrounds (used in renderer_panels, minimap)
  UiBgPanel*     = color(0.1, 0.1, 0.15, 0.85)    ## Info panel background
  UiBgBar*       = color(0.1, 0.1, 0.15, 0.8)     ## Resource bar background
  UiMinimapBorder* = color(0.2, 0.2, 0.25, 0.9)   ## Minimap border (panels)
  UiMinimapBorderDark* = color(0.15, 0.15, 0.15, 0.95) ## Minimap border (minimap.nim)

  # Viewport indicator
  UiViewportOutline* = color(1.0, 1.0, 1.0, 0.7)  ## Minimap viewport outline

const
  # Neutral/fallback colors
  NeutralGray*       = color(0.5, 0.5, 0.5, 1.0)  ## Neutral/unaffiliated gray
  NeutralGrayLight*  = color(0.6, 0.6, 0.6, 1.0)  ## Default team fallback
  NeutralGrayDim*    = color(0.6, 0.6, 0.6, 0.9)  ## Building default tint
  NeutralGrayMinimap* = color(0.7, 0.7, 0.7, 1.0) ## Minimap neutral building
  RallyPointFallback* = color(0.8, 0.8, 0.8, 1.0) ## Rally point default team color

  # Construction/scaffolding
  ScaffoldTint*      = color(0.7, 0.5, 0.2, 0.8)  ## Brown/wood scaffolding
  ScaffoldBarTint*   = color(0.6, 0.4, 0.15, 0.7) ## Scaffold cross-bar tint
  ConstructionBarFill* = color(0.9, 0.7, 0.1, 1.0) ## Construction progress fill (yellow)
  BarBgColor*        = color(0.3, 0.3, 0.3, 0.7)  ## Progress bar empty/background
  ProductionBarFill* = color(0.2, 0.5, 1.0, 1.0)  ## Production queue progress fill (blue)

  # Building ghost placement
  GhostValidColor*   = color(0.3, 1.0, 0.3, 0.6)  ## Valid placement (semi-transparent green)
  GhostInvalidColor* = color(1.0, 0.3, 0.3, 0.6)  ## Invalid placement (semi-transparent red)

  # Default white tint (for overlay icons)
  TintWhite*         = color(1, 1, 1, 1)           ## Full-opacity white tint

  # Wall rendering
  WallTintColor*     = color(0.3, 0.3, 0.3, 1.0)  ## Wall sprite tint (dark gray)

  # Grid overlay
  GridLineColor*     = color(0.4, 0.4, 0.4, 0.3)  ## Grid line overlay

  # Damage number colors
  DmgColorDamage*    = color(1.0, 0.3, 0.3, 1.0)  ## Damage text (red)
  DmgColorHeal*      = color(0.3, 1.0, 0.3, 1.0)  ## Heal text (green)
  DmgColorCritical*  = color(1.0, 0.8, 0.2, 1.0)  ## Critical hit text (yellow/gold)
  TextOutlineColor*  = color(0, 0, 0, 0.6)         ## Text outline for visibility

  # Effect colors - Spawn and particle
  SpawnEffectTint*   = color(0.6, 0.9, 1.0, 1.0)  ## Spawn glow (cyan) - alpha applied at runtime
  RippleTint*        = color(0.5, 0.7, 0.9, 1.0)  ## Water ripple (light cyan/blue) - alpha applied
  AttackImpactTint*  = color(1.0, 0.5, 0.2, 1.0)  ## Attack impact (orange/red) - alpha applied
  GatherSparkleTint* = color(1.0, 0.85, 0.3, 1.0) ## Gather sparkle (golden) - alpha applied
  ConstructionDustTint* = color(0.7, 0.6, 0.4, 1.0) ## Construction dust (brown) - alpha applied
  ConversionGoldenTint* = color(0.95, 0.85, 0.35, 1.0) ## Conversion effect golden base
  CloudPuffTint*     = color(0.82, 0.84, 0.9, 1.0) ## Rain cloud puff base - alpha applied

  # Rally point preview
  RallyPreviewColor* = color(0.3, 1.0, 0.3, 1.0)  ## Rally preview (green) - alpha applied

  # Dust terrain colors (base, alpha applied at runtime)
  DustSandColor*     = color(0.85, 0.75, 0.55, 1.0) ## Sand/Dune terrain dust
  DustSnowColor*     = color(0.95, 0.95, 1.0, 1.0)  ## Snow terrain dust
  DustMudColor*      = color(0.45, 0.35, 0.25, 1.0)  ## Mud terrain dust
  DustGrassColor*    = color(0.6, 0.55, 0.4, 1.0)    ## Grass/Fertile terrain dust
  DustRoadColor*     = color(0.5, 0.5, 0.5, 1.0)     ## Road terrain dust
  DustDefaultColor*  = color(0.7, 0.6, 0.4, 1.0)     ## Default terrain dust (tan)

  # Trade route
  TradeRouteGoldTint* = color(0.95, 0.78, 0.15, 0.7) ## Gold color for trade route lines

  # Goblin
  GoblinTint*        = color(0.35, 0.80, 0.35, 1.0) ## Goblin spawn tint (green)

  # Shadow
  ShadowTint*        = color(0.0, 0.0, 0.0, 0.25)   ## Unit shadow (semi-transparent black)

  # Health bar gradient endpoints
  HealthBarGreen*    = color(0.1, 0.8, 0.1, 1.0)    ## Health bar at full HP
  HealthBarYellow*   = color(1.0, 0.8, 0.1, 1.0)    ## Health bar at half HP
  HealthBarRed*      = color(1.0, 0.0, 0.1, 1.0)    ## Health bar at empty HP

  # Rally point / selection white core
  RallyCoreTint*     = color(1.0, 1.0, 1.0, 1.0)    ## Rally point inner core (white, alpha applied at runtime)

  # Label rendering
  LabelBgBlack*      = color(0, 0, 0, 1)             ## Label background base (black, alpha applied at runtime)

  # Weather base tints (R/G fixed, B varies at runtime per particle)
  RainBaseR*         = 0.8'f32                        ## Rain particle base red
  RainBaseG*         = 0.85'f32                       ## Rain particle base green

  # Smoke/wind base brightness (per-particle variation at runtime)
  SmokeBaseGray*     = 0.7'f32                        ## Smoke particle base gray value

  # Terrain ambient base colors (used with applyAmbient)
  ShallowWaterBase*  = color(0.6, 0.85, 0.95, 1.0)   ## Shallow water ambient tint base
  MountainBase*      = color(0.35, 0.32, 0.30, 1.0)   ## Mountain ambient tint base

  # Resource icon dim opacity
  ResourceIconDimAlpha* = 0.35'f32                    ## Opacity for empty stockpile icons

  # Building team tint modifiers
  BuildingTeamTintMul* = 0.75'f32                     ## Team color multiplier for building tint
  BuildingTeamTintAdd* = 0.1'f32                      ## Team color additive for building tint
  BuildingTeamTintAlpha* = 0.9'f32                    ## Building team tint alpha

  # Minimap bright team color boost
  MinimapBrightMul* = 1.2'f32                         ## Brightness multiplier for minimap team colors
  MinimapBrightAdd* = 0.1'f32                         ## Additive brightness for minimap team colors

  # Trade route target dock alpha variant
  TradeRouteGoldTarget* = color(0.95, 0.78, 0.15, 0.35) ## Trade route gold at target dock (TradeRouteGoldTint * TargetAlpha)

  # Projectile colors
  ProjArrowColor*      = color(0.6, 0.4, 0.2, 1.0)   ## Arrow projectile (brown)
  ProjLongbowColor*    = color(0.5, 0.3, 0.2, 1.0)   ## Longbow projectile (darker brown)
  ProjJanissaryColor*  = color(0.9, 0.9, 0.3, 1.0)   ## Janissary projectile (yellow)
  ProjTowerArrowColor* = color(0.6, 0.4, 0.2, 1.0)   ## Tower arrow projectile (brown)
  ProjCastleArrowColor* = color(0.7, 0.5, 0.3, 1.0)  ## Castle arrow projectile (tan)
  ProjMangonelColor*   = color(0.4, 0.4, 0.4, 1.0)   ## Mangonel projectile (gray)
  ProjTrebuchetColor*  = color(0.5, 0.5, 0.5, 1.0)   ## Trebuchet projectile (dark gray)

  # Debris colors
  DebrisWoodColor*   = color(0.55, 0.35, 0.15, 1.0)  ## Wood debris (brown)
  DebrisStoneColor*  = color(0.50, 0.50, 0.50, 1.0)  ## Stone debris (gray)
  DebrisBrickColor*  = color(0.70, 0.40, 0.25, 1.0)  ## Brick debris (terracotta)

const WarmTeamPalette* = [
  # Eight bright, evenly spaced tints (similar brightness, varied hue; away from clippy purple)
  color(0.910, 0.420, 0.420, 1.0),  # team 0: soft red        (#e86b6b)
  color(0.940, 0.650, 0.420, 1.0),  # team 1: soft orange     (#f0a86b)
  color(0.940, 0.820, 0.420, 1.0),  # team 2: soft yellow     (#f0d56b)
  color(0.600, 0.840, 0.500, 1.0),  # team 3: soft olive-lime (#99d680)
  color(0.780, 0.380, 0.880, 1.0),  # team 4: warm magenta    (#c763e0)
  color(0.420, 0.720, 0.940, 1.0),  # team 5: soft sky        (#6ab8f0)
  color(0.870, 0.870, 0.870, 1.0),  # team 6: light gray      (#dedede)
  color(0.930, 0.560, 0.820, 1.0)   # team 7: soft pink       (#ed8fd1)
]

proc withAlpha*(c: Color, a: float32): Color {.inline.} =
  ## Returns a copy of `c` with its alpha replaced by `a`.
  color(c.r, c.g, c.b, a)

proc applyActionTint(env: Environment, pos: IVec2, tintColor: TileColor, duration: int8, tintCode: uint8) =
  ## Applies one action tint and keeps observation tint state in sync.
  if not isValidPos(pos) or env.tintLocked[pos.x][pos.y]:
    return
  env.actionTintColor[pos.x][pos.y] = tintColor
  env.actionTintCountdown[pos.x][pos.y] = duration
  let existing = env.actionTintCode[pos.x][pos.y]
  let nextCode =
    if existing == ActionTintNone or existing == tintCode: tintCode else: ActionTintMixed
  env.actionTintCode[pos.x][pos.y] = nextCode
  # Keep observation tint state in sync with recent combat actions.
  env.updateObservations(TintLayer, pos, nextCode.int)
  if not env.actionTintFlags[pos.x][pos.y]:
    env.actionTintFlags[pos.x][pos.y] = true
    env.actionTintPositions.add(pos)

proc combinedTileTint*(env: Environment, x, y: int): TileColor =
  ## Returns the combined base and overlay tint for one tile.
  let base = env.baseTintColors[x][y]
  if env.tintLocked[x][y]:
    return base
  let overlay = env.computedTintColors[x][y]
  let alpha = max(0.0'f32, min(1.0'f32, overlay.intensity))
  let invAlpha = 1.0'f32 - alpha
  TileColor(
    r: base.r * invAlpha + overlay.r * alpha,
    g: base.g * invAlpha + overlay.g * alpha,
    b: base.b * invAlpha + overlay.b * alpha,
    intensity: base.intensity + (1.0'f32 - base.intensity) * alpha
  )

proc isTileFrozen*(pos: IVec2, env: Environment): bool {.inline.} =
  ## Check if a tile is frozen (covered by clippy/tumor tint).
  ## Uses cached frozen state updated during tint modifications for O(1) lookup.
  if not isValidPos(pos):
    return false
  env.frozenTiles[pos.x][pos.y]

proc isThingFrozen*(thing: Thing, env: Environment): bool {.inline.} =
  ## Anything explicitly frozen or sitting on a frozen tile counts as non-interactable.
  thing.frozen > 0 or isTileFrozen(thing.pos, env)

proc applyBiomeBaseColors*(env: Environment) =
  ## Rebuilds cached base tint colors from biome layout and edge blending.
  template baseColor(biome: BiomeType): TileColor =
    case biome:
    of BiomeBaseType: BaseTileColorDefault
    of BiomeForestType: BiomeColorForest
    of BiomeDesertType: BiomeColorDesert
    of BiomeCavesType: BiomeColorCaves
    of BiomeCityType: BiomeColorCity
    of BiomePlainsType: BiomeColorPlains
    of BiomeSnowType: BiomeColorSnow
    of BiomeSwampType: BiomeColorSwamp
    of BiomeDungeonType: BiomeColorDungeon
    else: BaseTileColorDefault

  var colors: array[MapWidth, array[MapHeight, TileColor]]
  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      let baseBiome = env.biomes[x][y]
      var color = baseColor(baseBiome)
      if BiomeEdgeBlendRadius > 0 and baseBiome != BiomeNone:
        var minDist = BiomeEdgeBlendRadius + 1
        var sumR = 0.0'f32
        var sumG = 0.0'f32
        var sumB = 0.0'f32
        var sumI = 0.0'f32
        var count = 0

        for dx in -BiomeEdgeBlendRadius .. BiomeEdgeBlendRadius:
          let nx = x + dx
          if nx < 0 or nx >= MapWidth:
            continue
          for dy in -BiomeEdgeBlendRadius .. BiomeEdgeBlendRadius:
            if dx == 0 and dy == 0:
              continue
            let ny = y + dy
            if ny < 0 or ny >= MapHeight:
              continue
            let dist = max(abs(dx), abs(dy))
            if dist > BiomeEdgeBlendRadius:
              continue
            let otherBiome = env.biomes[nx][ny]
            if otherBiome == baseBiome or otherBiome == BiomeNone:
              continue
            let otherColor = baseColor(otherBiome)
            if dist < minDist:
              minDist = dist
              sumR = otherColor.r
              sumG = otherColor.g
              sumB = otherColor.b
              sumI = otherColor.intensity
              count = 1
            elif dist == minDist:
              sumR += otherColor.r
              sumG += otherColor.g
              sumB += otherColor.b
              sumI += otherColor.intensity
              inc count

        if count > 0:
          let invCount = 1.0'f32 / count.float32
          let neighborColor = TileColor(
            r: sumR * invCount,
            g: sumG * invCount,
            b: sumB * invCount,
            intensity: sumI * invCount
          )

          let blendT = max(0.0'f32, min(1.0'f32,
            1.0'f32 - (float32(minDist - 1) / float32(BiomeEdgeBlendRadius))))
          let easeT = blendT * blendT * (3.0'f32 - 2.0'f32 * blendT)
          let invT = 1.0'f32 - easeT
          color = TileColor(
            r: color.r * invT + neighborColor.r * easeT,
            g: color.g * invT + neighborColor.g * easeT,
            b: color.b * invT + neighborColor.b * easeT,
            intensity: color.intensity * invT + neighborColor.intensity * easeT
          )
      colors[x][y] = color

  if BiomeBlendPasses > 0:
    var temp: array[MapWidth, array[MapHeight, TileColor]]
    let centerWeight = 1.0'f32
    let neighborWeight = BiomeBlendNeighborWeight
    for _ in 0 ..< BiomeBlendPasses:
      for x in 0 ..< MapWidth:
        for y in 0 ..< MapHeight:
          var sumR = colors[x][y].r * centerWeight
          var sumG = colors[x][y].g * centerWeight
          var sumB = colors[x][y].b * centerWeight
          var sumI = colors[x][y].intensity * centerWeight
          var total = centerWeight
          for dx in -1 .. 1:
            for dy in -1 .. 1:
              if dx == 0 and dy == 0:
                continue
              let nx = x + dx
              let ny = y + dy
              if nx < 0 or nx >= MapWidth or ny < 0 or ny >= MapHeight:
                continue
              let neighborColor = colors[nx][ny]
              sumR += neighborColor.r * neighborWeight
              sumG += neighborColor.g * neighborWeight
              sumB += neighborColor.b * neighborWeight
              sumI += neighborColor.intensity * neighborWeight
              total += neighborWeight
          temp[x][y] = TileColor(
            r: sumR / total,
            g: sumG / total,
            b: sumB / total,
            intensity: sumI / total
          )
      colors = temp

  env.baseTintColors = colors
