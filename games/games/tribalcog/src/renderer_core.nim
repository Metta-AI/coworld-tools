## renderer_core.nim - Core rendering types, constants, and helpers
##
## Contains: sprite constants, sprite selection helpers, color utilities,
## team color helpers, and other shared rendering infrastructure.

import
  boxy, pixie, vmath, math,
  common, environment, label_cache

# ─── Shared Constants ────────────────────────────────────────────────────────

const
  SpriteScale* = 1.0 / 200.0

  # Idle animation constants
  IdleAnimationSpeed* = 2.0        # Breathing cycles per second
  IdleAnimationAmplitude* = 0.02   # Scale variation (+/- 2% from base)
  IdleAnimationPhaseScale* = 0.7   # Phase offset multiplier for variation between units

  # Resource depletion animation constants
  DepletionScaleMin* = 0.5         # Minimum scale when resource is empty (50% of full size)
  DepletionScaleMax* = 1.0         # Maximum scale when resource is full (100%)

  # Health bar fade constants
  HealthBarFadeInDuration* = 5     # Steps to fade in after taking damage
  HealthBarVisibleDuration* = 60   # Steps to stay fully visible after damage
  HealthBarFadeOutDuration* = 30   # Steps to fade out after visible period
  HealthBarMinAlpha* = 0.3         # Minimum alpha when faded out (never fully invisible)

  # Shadow constants
  ShadowAlpha* = 0.25'f32
  ShadowOffsetX* = 0.15'f32
  ShadowOffsetY* = 0.10'f32

  # Fire flicker constants
  LanternFlickerSpeed1* = 0.15'f32    # Primary flicker wave speed
  LanternFlickerSpeed2* = 0.23'f32    # Secondary flicker wave speed (faster, irregular)
  LanternFlickerSpeed3* = 0.07'f32    # Tertiary slow wave for organic feel
  LanternFlickerAmplitude* = 0.12'f32 # Brightness variation (+/- 12%)
  MagmaGlowSpeed* = 0.04'f32          # Slower pulsing for magma pools
  MagmaGlowAmplitude* = 0.08'f32      # Subtle glow variation (+/- 8%)

  # Icon and label scale constants
  HeartIconScale* = 1.0 / 420.0       # Scale for heart sprites at altars
  HeartCountLabelScale* = 1.0 / 200.0 # Scale for heart count labels
  OverlayIconScale* = 1.0 / 320.0     # Scale for building overlay icons
  OverlayLabelScale* = 1.0 / 200.0    # Scale for overlay text labels
  SegmentBarDotScale* = 1.0 / 500.0   # Scale for segment/health bar dots
  ScaffoldingPostScale* = 1.0 / 600.0 # Scale for scaffolding post dots
  TradeRouteDotScale* = 1.0 / 350.0   # Scale for trade route animation dots
  DockMarkerScale* = 1.0 / 280.0      # Scale for dock gold coin indicators

  # Control group badge constants
  ControlGroupBadgeFontPath* = "data/Inter-Regular.ttf"
  ControlGroupBadgeFontSize*: float32 = 24
  ControlGroupBadgePadding* = 4.0'f32
  ControlGroupBadgeScale* = 1.0 / 180.0  # Scale for rendering in world space

  # Selection glow
  SelectionGlowScale* = 1.3'f32

  # ─── Unit Info Panel ──────────────────────────────────────────────────────
  UnitInfoFontSize* = 18.0'f32          # Default font size for unit info labels
  UnitInfoNameFontSize* = 22.0'f32      # Font size for unit/building name
  UnitInfoPanelW* = 220.0'f32           # Panel width in pixels
  UnitInfoPanelH* = 180.0'f32           # Panel height in pixels
  UnitInfoPanelPadding* = 8.0'f32       # Internal X/Y padding
  UnitInfoLineSpacingSmall* = 2.0'f32   # Small gap between stat lines
  UnitInfoLineSpacingLarge* = 4.0'f32   # Larger gap after name line
  UnitInfoBgAlpha* = 0.85'f32           # Background opacity

  # ─── Resource Bar ─────────────────────────────────────────────────────────
  ResourceBarIconMaxSize* = 20.0'f32    # Max pixel size for resource icons
  ResourceBarIconSlotW* = 24.0'f32      # Slot width allocated per icon
  ResourceBarIconGap* = 4.0'f32         # Gap between icon and count text
  ResourceBarItemSpacing* = 20.0'f32    # Spacing between resource items
  ResourceBarXStart* = 10.0'f32         # Initial x offset from left edge

  # ─── Minimap (renderer_panels) ─────────────────────────────────────────────
  MinimapPanelPadding* = 8.0'f32        # Padding around minimap in panels
  MinimapUpdateFrameInterval* = 10      # Frames between unit-layer rebuilds
  MinimapPanelBorderWidth* = 2.0'f32    # Border width around minimap
  MinimapFogDarkFactor* = 0.3'f32       # Fog-of-war darkness multiplier
  MinimapFogEdgeFactor* = 0.6'f32       # Fog edge smoothing factor
  MinimapViewportLineW* = 1.0'f32       # Viewport outline thickness
  MinimapViewportAlphaPanel* = 0.7'f32  # Viewport outline opacity
  MinimapBorderAlpha* = 0.9'f32         # Minimap border opacity
  MinimapBuildingBlockSize* = 2         # Building dot size (NxN pixels)
  MinimapBytesPerPixel* = 4             # RGBA bytes per pixel for image copy

  # ─── Trade Route Line Drawing ─────────────────────────────────────────────
  TradeRouteMinLineLength* = 0.5'f32   # Minimum drawable line length in world units
  TradeRouteSegmentSpacing* = 0.5'f32  # Line segment spacing for trade route lines

  # ─── Rally Point Line Drawing ──────────────────────────────────────────────
  RallyMinLineLength* = 0.1'f32        # Minimum rally path line length
  RallyPreviewMinLineLength* = 0.5'f32 # Minimum rally preview line length

  # ─── Command Panel Drawing ────────────────────────────────────────────────
  CommandPanelBorderOffset* = 2.0'f32   # Border outset from panel edge
  CommandPanelBorderExpand* = 4.0'f32   # Border expansion (2 * offset)
  CommandButtonBorderW* = 1.0'f32       # Button border line thickness
  CommandButtonHotkeyInset* = 2.0'f32   # Hotkey/checkmark inset from corner

  # ─── Command Panel Header/Label ────────────────────────────────────────────
  CommandPanelHeaderHeight* = 24.0'f32   # Header bar height in pixels
  CommandPanelHeaderPadX* = 10.0'f32     # Header text horizontal padding
  CommandLabelFontPath* = "data/Inter-Regular.ttf"
  CommandLabelFontSize* = 18.0'f32       # Button label font size
  CommandHotkeyFontSize* = 14.0'f32      # Hotkey hint font size
  CommandLabelPadding* = 2.0'f32         # Label texture internal padding

  # ─── Tooltip Layout ───────────────────────────────────────────────────────
  TooltipFontPath* = "data/Inter-Regular.ttf"
  TooltipTitleFontSize*: float32 = 16   # Title text font size
  TooltipTextFontSize*: float32 = 13    # Body text font size
  TooltipPadding*: float32 = 10         # Internal padding around content
  TooltipLineHeight*: float32 = 18      # Vertical space per text line
  TooltipMaxWidth*: float32 = 280       # Maximum tooltip width in pixels
  TooltipShowDelay*: float64 = 0.3      # Seconds before tooltip appears

  # ─── Tooltip Positioning ──────────────────────────────────────────────────
  TooltipScreenMargin* = 8.0'f32        # Min distance from screen edges
  TooltipAnchorGap* = 8.0'f32           # Gap between tooltip and anchor rect
  TooltipBorderOutset* = 2.0'f32        # Border outset around tooltip bg
  TooltipBorderExpand* = 4.0'f32        # Border expansion (2 * outset)
  TooltipSectionGap* = 4.0'f32          # Extra spacing between sections
  TooltipLabelPadding* = 2.0'f32        # Padding inside label textures
  TooltipMaxQueueLines* = 3             # Max production queue entries shown

  # ─── Selection Pulse Animation ────────────────────────────────────────────
  SelectionPulseSpeed* = 0.1'f32        # Selection glow pulse frequency
  SelectionPulseAmplitude* = 0.15'f32   # Selection glow pulse amplitude
  SelectionPulseBase* = 0.85'f32        # Selection glow pulse base alpha
  SelectionGlowAlpha* = 0.4'f32         # Outer glow ring alpha
  SelectionHealthBarYOffset* = -0.55'f32 # Health bar Y offset above selected units
  SelectionHealthBarSegments* = 5        # Number of segments in selection health bar

  # ─── Rally Point ──────────────────────────────────────────────────────────
  RallyPointLineWidth* = 0.06'f32       # Width of the path line in world units
  RallyPointLineSegments* = 12          # Number of segments in the path line
  RallyPointBeaconScale* = 1.0 / 280.0  # Scale for the beacon sprite
  RallyPointPulseSpeed* = 0.15'f32      # Speed of the pulsing animation
  RallyPointPulseMin* = 0.6'f32         # Minimum alpha during pulse
  RallyPointPulseMax* = 1.0'f32         # Maximum alpha during pulse
  RallyGlowScaleMult* = 3.0'f32         # Outer glow scale multiplier
  RallyGlowAlpha* = 0.3'f32             # Outer glow alpha
  RallyBeaconPulseAmount* = 0.15'f32    # Beacon scale pulse fraction
  RallyBeaconSpriteScale* = 0.8'f32     # Beacon sprite scale
  RallyBeaconFallbackScale* = 1.5'f32   # Fallback floor sprite scale
  RallyCoreScale* = 0.8'f32             # Inner core scale
  RallyCoreAlpha* = 0.8'f32             # Inner core alpha
  RallyPathAlpha* = 0.7'f32             # Dashed path line alpha
  RallyPreviewGlowScale* = 3.5'f32     # Preview outer glow scale
  RallyPreviewGlowAlpha* = 0.4'f32     # Preview outer glow alpha
  RallyPreviewSpriteScale* = 0.9'f32   # Preview beacon sprite scale
  RallyPreviewFallbackScale* = 1.8'f32 # Preview fallback floor sprite scale
  RallyPreviewCoreScale* = 0.9'f32     # Preview inner core scale
  RallyPreviewCoreAlpha* = 0.9'f32     # Preview inner core alpha
  RallyPreviewPulseAmount* = 0.2'f32   # Preview beacon pulse fraction
  RallyPreviewPathAlpha* = 0.5'f32     # Preview dashed path alpha
  RallyPreviewBaseAlpha* = 0.8'f32    # Base alpha multiplier for preview color

  # ─── Building Ghost Placement ──────────────────────────────────────────────
  GridSnapOffset* = 0.5'f32              # Offset for rounding world pos to grid cell center

  # ─── Building UI Overlays ─────────────────────────────────────────────────
  BuildingIconOffsetX* = -0.18'f32       # Resource icon X offset from center
  BuildingIconOffsetY* = -0.62'f32       # Resource icon Y offset from center
  BuildingLabelOffsetX* = 0.14'f32       # Label X offset from icon
  BuildingLabelOffsetY* = -0.08'f32      # Label Y offset from icon
  BuildingGarrisonOffsetX* = 0.22'f32    # Garrison icon X offset
  BuildingGarrisonLabelOffsetX* = 0.12'f32 # Garrison label X offset from icon
  ProductionBarOffsetY* = 0.55'f32       # Production progress bar Y offset
  ConstructionBarOffsetY* = 0.65'f32     # Construction progress bar Y offset
  ScaffoldPostOffset* = 0.35'f32         # Scaffolding post offset from center

  # ─── Trade Route ─────────────────────────────────────────────────────────
  TradeRouteLineWidth* = 0.08'f32       # World-space line width
  TradeRouteFlowDotCount* = 5           # Animated dots per route segment
  TradeRouteFlowSpeed* = 0.015'f32      # Animation speed (fraction per frame)
  TradeRouteLineSegScale* = 200.0'f32   # Divisor for line segment sprite scale
  TradeRouteTeamBlend* = 0.3'f32        # Team color weight in route blending
  TradeRouteGoldBlend* = 0.7'f32        # Gold color weight in route blending
  TradeRouteBrightnessBase* = 0.7'f32   # Base brightness for flow dots
  TradeRouteBrightnessVar* = 0.3'f32    # Brightness variation for flow dots
  TradeRouteDotColorBoostR* = 0.2'f32   # Red color boost on flow dots
  TradeRouteDotColorBoostG* = 0.1'f32   # Green color boost on flow dots
  TradeRouteDockMarkerOffsetY* = -0.4'f32 # Dock gold indicator Y offset
  TradeRouteTargetAlpha* = 0.5'f32      # Alpha for target dock route line
  TradeRouteDotAlpha* = 0.9'f32         # Alpha for flow dot indicators

  # ─── Grid Overlay ────────────────────────────────────────────────────────
  GridLineScale* = 1.0 / 800.0          # Scale for grid line sprites

  # ─── Minimap Terrain Colors (renderer_panels) ──────────────────────────
  MinimapPanelWater*        = rgbx(30, 60, 130, 255)    ## Deep water
  MinimapPanelShallowWater* = rgbx(80, 140, 200, 255)   ## Shallow water
  MinimapPanelBridge*       = rgbx(140, 110, 80, 255)   ## Bridge
  MinimapPanelRoad*         = rgbx(160, 150, 130, 255)  ## Road
  MinimapPanelSnow*         = rgbx(230, 235, 245, 255)  ## Snow
  MinimapPanelSandy*        = rgbx(210, 190, 110, 255)  ## Dune/Sand
  MinimapPanelMud*          = rgbx(100, 85, 60, 255)    ## Mud
  MinimapPanelMountain*     = rgbx(80, 75, 70, 255)     ## Mountain
  MinimapPanelTree*         = rgbx(40, 100, 40, 255)    ## Tree (dark green)
  MinimapPanelUnknownGray*  = rgbx(128, 128, 128, 255)  ## Unknown team gray

  # ─── Minimap Team Colors ─────────────────────────────────────────────────
  MinimapBrightColorMult* = 1.2'f32     # Multiplier for bright team colors
  MinimapBrightColorAdd* = 0.1'f32      # Additive boost for bright team colors
  MinimapNeutralGrayBright* = 179       # Neutral gray for non-team buildings (0.7 * 255)
  MinimapIntensityCap* = 1.3'f32        # Max biome intensity for minimap colors

  # ─── Label Style Parameters ─────────────────────────────────────────────
  UnitInfoLabelPadding* = 4.0'f32       # Padding for unit info label style
  UnitInfoLabelLineSpacing* = 0.5'f32   # Line spacing for unit info label
  ResourceBarLabelPadding* = 4.0'f32    # Padding for resource bar label style
  OverlayLabelLineSpacing* = 0.7'f32    # Line spacing for overlay labels
  InfoLabelLineSpacing* = 0.6'f32       # Line spacing for info labels

  # ─── Footer Icon Offsets ──────────────────────────────────────────────────
  FooterIconCenterShiftX* = 8.0'f32   # Icon X centering offset
  FooterIconCenterShiftY* = 9.0'f32   # Icon Y centering offset
  FooterBorderHeight* = 1.0'f32          # Footer top/bottom border thickness
  FooterHudLabelYShift* = 20.0'f32       # HUD label extra Y shift below footer

# ─── Unit Class Sprite Keys ──────────────────────────────────────────────────

const UnitClassSpriteKeys*: array[AgentUnitClass, string] = [
  "",                              # UnitVillager (uses role-based key)
  "oriented/man_at_arms",          # UnitManAtArms
  "oriented/archer",               # UnitArcher
  "oriented/scout",                # UnitScout
  "oriented/knight",               # UnitKnight
  "oriented/monk",                 # UnitMonk
  "oriented/battering_ram",        # UnitBatteringRam
  "oriented/mangonel",             # UnitMangonel
  "",                              # UnitTrebuchet (packed/unpacked)
  "oriented/goblin",               # UnitGoblin
  "oriented/boat",                 # UnitBoat
  "oriented/trade_cog",            # UnitTradeCog
  "oriented/samurai",              # UnitSamurai
  "oriented/longbowman",           # UnitLongbowman
  "oriented/cataphract",           # UnitCataphract
  "oriented/woad_raider",          # UnitWoadRaider
  "oriented/teutonic_knight",      # UnitTeutonicKnight
  "oriented/huskarl",              # UnitHuskarl
  "oriented/mameluke",             # UnitMameluke
  "oriented/janissary",            # UnitJanissary
  "oriented/king",                 # UnitKing
  "oriented/long_swordsman",       # UnitLongSwordsman
  "oriented/champion",             # UnitChampion
  "oriented/light_cavalry",        # UnitLightCavalry
  "oriented/hussar",               # UnitHussar
  "oriented/crossbowman",          # UnitCrossbowman
  "oriented/arbalester",           # UnitArbalester
  "oriented/galley",               # UnitGalley
  "oriented/fire_ship",            # UnitFireShip
  "oriented/fishing_ship",         # UnitFishingShip
  "oriented/transport_ship",       # UnitTransportShip
  "oriented/demo_ship",            # UnitDemoShip
  "oriented/cannon_galleon",       # UnitCannonGalleon
  "oriented/scorpion",             # UnitScorpion
  "oriented/cavalier",             # UnitCavalier
  "oriented/paladin",              # UnitPaladin
  "oriented/camel",                # UnitCamel
  "oriented/heavy_camel",          # UnitHeavyCamel
  "oriented/imperial_camel",       # UnitImperialCamel
  "oriented/skirmisher",           # UnitSkirmisher
  "oriented/elite_skirmisher",     # UnitEliteSkirmisher
  "oriented/cavalry_archer",       # UnitCavalryArcher
  "oriented/heavy_cavalry_archer", # UnitHeavyCavalryArcher
  "oriented/hand_cannoneer",       # UnitHandCannoneer
]

const OrientationDirKeys* = [
  "n",  # N
  "s",  # S
  "w",  # W
  "e",  # E
  "nw", # NW
  "ne", # NE
  "sw", # SW
  "se"  # SE
]

const TumorDirKeys* = [
  "n", # N
  "s", # S
  "w", # W
  "e", # E
  "w", # NW
  "e", # NE
  "w", # SW
  "e"  # SE
]

# ─── Floor Sprite Types ──────────────────────────────────────────────────────

type FloorSpriteKind* = enum
  FloorBase
  FloorCave
  FloorDungeon
  FloorSnow

# ─── Sprite Helper Procs ─────────────────────────────────────────────────────

proc getUnitSpriteBase*(unitClass: AgentUnitClass, agentId: int, packed: bool = true): string =
  ## Determine the base sprite key for a unit based on its class and role.
  ## Used for consistent sprite selection across shadow, agent, and dying unit rendering.
  ## The packed parameter is only relevant for trebuchets (defaults to true for dying units).
  let tbl = UnitClassSpriteKeys[unitClass]
  if tbl.len > 0:
    tbl
  elif unitClass == UnitTrebuchet:
    if packed: "oriented/trebuchet_packed"
    else: "oriented/trebuchet_unpacked"
  else: # UnitVillager: role-based
    case agentId mod MapAgentsPerTeam
    of 0, 1: "oriented/gatherer"
    of 2, 3: "oriented/builder"
    of 4, 5: "oriented/fighter"
    else: "oriented/gatherer"

proc selectUnitSpriteKey*(baseKey: string, orientation: Orientation): string =
  ## Select the appropriate sprite key for a unit given its base key and orientation.
  ##
  ## Attempts to find a direction-specific sprite (e.g., "oriented/gatherer.nw").
  ## Falls back to the south-facing sprite if the direction-specific one doesn't exist.
  ## Returns an empty string if neither sprite is available.
  ##
  ## Parameters:
  ##   baseKey: The base sprite key (e.g., "oriented/gatherer")
  ##   orientation: The unit's facing direction
  ##
  ## Returns:
  ##   The sprite key to use, or empty string if unavailable.
  let dirKey = OrientationDirKeys[orientation.int]
  let orientedImage = baseKey & "." & dirKey
  if orientedImage in bxy: orientedImage
  elif baseKey & ".s" in bxy: baseKey & ".s"
  else: ""

# ─── Color Helper Procs ──────────────────────────────────────────────────────

proc getTeamColor*(env: Environment, teamId: int,
                   fallback: Color = NeutralGrayLight): Color =
  ## Get team color from environment, with fallback for invalid team IDs.
  if teamId >= 0 and teamId < env.teamColors.len:
    env.teamColors[teamId]
  else:
    fallback

proc getHealthBarColor*(ratio: float32): Color =
  ## Get health bar color based on HP ratio. Gradient from green (full) to red (low).
  ## Green (1.0) -> Yellow (0.5) -> Red (0.0)
  if ratio > 0.5:
    # Green to yellow: ratio 1.0->0.5 maps to green->yellow
    let t = (ratio - 0.5) * 2.0  # t: 1.0 at full, 0.0 at half
    color(HealthBarYellow.r - t * (HealthBarYellow.r - HealthBarGreen.r),
          HealthBarYellow.g, HealthBarYellow.b, 1.0)
  else:
    # Yellow to red: ratio 0.5->0.0 maps to yellow->red
    let t = ratio * 2.0  # t: 1.0 at half, 0.0 at empty
    color(HealthBarRed.r, t * HealthBarYellow.g, HealthBarYellow.b, 1.0)

proc getHealthBarAlpha*(currentStep: int, lastAttackedStep: int): float32 =
  ## Calculate health bar alpha based on damage recency.
  ## Fades in quickly after damage, stays visible, then fades out gradually.
  let stepsSinceDamage = currentStep - lastAttackedStep
  if lastAttackedStep <= 0:
    # Never attacked - show at minimum alpha
    return HealthBarMinAlpha
  if stepsSinceDamage < HealthBarFadeInDuration:
    # Fade in phase: 0.0 -> 1.0 over FadeInDuration steps
    let progress = stepsSinceDamage.float32 / HealthBarFadeInDuration.float32
    return HealthBarMinAlpha + (1.0 - HealthBarMinAlpha) * progress
  elif stepsSinceDamage < HealthBarFadeInDuration + HealthBarVisibleDuration:
    # Fully visible phase
    return 1.0
  elif stepsSinceDamage < HealthBarFadeInDuration + HealthBarVisibleDuration + HealthBarFadeOutDuration:
    # Fade out phase: 1.0 -> MinAlpha over FadeOutDuration steps
    let fadeProgress = (stepsSinceDamage - HealthBarFadeInDuration - HealthBarVisibleDuration).float32 / HealthBarFadeOutDuration.float32
    return 1.0 - (1.0 - HealthBarMinAlpha) * fadeProgress
  else:
    # Fully faded out (to minimum alpha)
    return HealthBarMinAlpha

proc toRgbx*(c: Color): ColorRGBX {.inline.} =
  ## Convert a pixie Color (float 0-1) to ColorRGBX (uint8 0-255).
  rgbx(
    uint8(clamp(c.r * 255, 0, 255)),
    uint8(clamp(c.g * 255, 0, 255)),
    uint8(clamp(c.b * 255, 0, 255)),
    uint8(clamp(c.a * 255, 0, 255))
  )

proc colorToRgbx*(c: Color): ColorRGBX =
  rgbx(
    uint8(clamp(c.r * 255, 0, 255)),
    uint8(clamp(c.g * 255, 0, 255)),
    uint8(clamp(c.b * 255, 0, 255)),
    255
  )

# ─── Shadow Rendering ────────────────────────────────────────────────────────

proc renderAgentShadow*(agent: Thing, shadowTint: Color, shadowOffset: Vec2) =
  ## Render a shadow beneath a single agent.
  ##
  ## Draws a semi-transparent dark silhouette offset from the unit's position to
  ## create the illusion of depth. Light source is assumed to be NW, so shadows
  ## cast to the SE (positive X and Y offset).
  ##
  ## Parameters:
  ##   agent: The agent Thing to render shadow for
  ##   shadowTint: Color for the shadow (typically semi-transparent black)
  ##   shadowOffset: Offset vector from agent position to shadow position
  let pos = agent.pos
  if not isValidPos(pos) or env.grid[pos.x][pos.y] != agent or not isInViewport(pos):
    return
  let baseKey = getUnitSpriteBase(agent.unitClass, agent.agentId, agent.packed)
  let shadowSpriteKey = selectUnitSpriteKey(baseKey, agent.orientation)
  if shadowSpriteKey.len > 0:
    let shadowPos = pos.vec2 + shadowOffset
    bxy.drawImage(shadowSpriteKey, shadowPos, angle = 0,
                  scale = SpriteScale, tint = shadowTint)

# ─── Segment Bar Drawing ─────────────────────────────────────────────────────

proc drawSegmentBar*(basePos: Vec2, offset: Vec2, ratio: float32,
                     filledColor, emptyColor: Color, segments = 5, alpha = 1.0'f32) =
  let filled = int(ceil(ratio * segments.float32))
  const segStep = 0.16'f32
  let origin = basePos + vec2(-segStep * (segments.float32 - 1) / 2 + offset.x, offset.y)
  for i in 0 ..< segments:
    let baseColor = if i < filled: filledColor else: emptyColor
    let fadedColor = withAlpha(baseColor, baseColor.a * alpha)
    bxy.drawImage("floor", origin + vec2(segStep * i.float32, 0),
                  angle = 0, scale = SegmentBarDotScale,
                  tint = fadedColor)

# ─── Text Label Rendering ────────────────────────────────────────────────────

const
  HeartCountFontPath* = "data/Inter-Regular.ttf"
  HeartCountFontSize*: float32 = 40
  HeartCountPadding* = 6
  InfoLabelFontPath* = HeartCountFontPath
  InfoLabelFontSize*: float32 = 54
  InfoLabelPadding* = 18
  FooterFontPath* = HeartCountFontPath
  FooterFontSize*: float32 = 26
  FooterPadding* = 10.0'f32
  FooterButtonPaddingX* = 18.0'f32
  FooterButtonGap* = 12.0'f32
  FooterLabelPadding* = 4.0'f32
  FooterHudPadding* = 12.0'f32


# ─── Label Caches ────────────────────────────────────────────────────────────

let
  overlayLabelStyle* = labelStyle(HeartCountFontPath, HeartCountFontSize,
                                  HeartCountPadding.float32, OverlayLabelLineSpacing)
  infoLabelStyle* = labelStyle(InfoLabelFontPath, InfoLabelFontSize,
                               InfoLabelPadding.float32, InfoLabelLineSpacing)
  footerBtnLabelStyle* = labelStyle(FooterFontPath, FooterFontSize,
                                    FooterLabelPadding, 0.0)
  resourceBarLabelStyle* = labelStyle(FooterFontPath, FooterFontSize, ResourceBarLabelPadding, 0.0)

proc ensureHeartCountLabel*(count: int): string =
  ## Cache a simple "x N" label for large heart counts so we can reuse textures.
  if count <= 0: return ""
  let cached = ensureLabel("heart_count", "x " & $count, overlayLabelStyle)
  result = cached.imageKey

# ─── Cliff Draw Order ────────────────────────────────────────────────────────

const CliffDrawOrder* = [
  CliffEdgeN,
  CliffEdgeE,
  CliffEdgeS,
  CliffEdgeW,
  CliffCornerInNE,
  CliffCornerInSE,
  CliffCornerInSW,
  CliffCornerInNW,
  CliffCornerOutNE,
  CliffCornerOutSE,
  CliffCornerOutSW,
  CliffCornerOutNW
]

# ─── Waterfall Draw Order ────────────────────────────────────────────────────

const WaterfallDrawOrder* = [
  WaterfallN,
  WaterfallE,
  WaterfallS,
  WaterfallW
]

# ─── Render Cache Variables ──────────────────────────────────────────────────

var
  floorSpritePositions*: array[FloorSpriteKind, seq[IVec2]]
  waterPositions*: seq[IVec2] = @[]
  shallowWaterPositions*: seq[IVec2] = @[]
  mountainPositions*: seq[IVec2] = @[]
  renderCacheGeneration* = -1
  # Fog of war visibility buffer - reused across frames to avoid allocation overhead
  fogVisibility*: array[MapWidth, array[MapHeight, bool]]

proc rebuildRenderCaches*() =
  for kind in FloorSpriteKind:
    floorSpritePositions[kind].setLen(0)
  waterPositions.setLen(0)
  shallowWaterPositions.setLen(0)
  mountainPositions.setLen(0)

  for x in 0 ..< MapWidth:
    for y in 0 ..< MapHeight:
      let biome = env.biomes[x][y]
      let floorKind = case biome
        of BiomeCavesType: FloorCave
        of BiomeDungeonType:
          var v = uint32(x) * 374761393'u32 + uint32(y) * 668265263'u32
          v = (v xor (v shr 13)) * 1274126177'u32
          if ((v xor (v shr 16)) mod 100) < 35: FloorDungeon else: FloorBase
        of BiomeSnowType: FloorSnow
        else: FloorBase
      floorSpritePositions[floorKind].add(ivec2(x, y))

      if env.terrain[x][y] == Water:
        waterPositions.add(ivec2(x, y))
      elif env.terrain[x][y] == ShallowWater:
        shallowWaterPositions.add(ivec2(x, y))
      elif env.terrain[x][y] == Mountain:
        mountainPositions.add(ivec2(x, y))
  renderCacheGeneration = env.mapGeneration

# ─── Wall Sprites ────────────────────────────────────────────────────────────

let wallSprites* = block:
  var sprites = newSeq[string](16)
  for i in 0 .. 15:
    var suffix = ""
    if (i and 8) != 0: suffix.add("n")
    if (i and 4) != 0: suffix.add("w")
    if (i and 2) != 0: suffix.add("s")
    if (i and 1) != 0: suffix.add("e")

    if suffix.len > 0:
      sprites[i] = "oriented/wall." & suffix
    else:
      sprites[i] = "oriented/wall"
  sprites

type WallTile* = enum
  WallE = 1,
  WallS = 2,
  WallW = 4,
  WallN = 8,
  WallSE = 2 or 1,
  WallNW = 8 or 4,

# ─── Heart Plus Threshold ────────────────────────────────────────────────────

# ─── Shared UI Helpers ────────────────────────────────────────────────────────

proc resourceUiIconScale*(res: StockpileResource): float32 {.inline.} =
  ## Normalize resource icon visual footprint across mixed sprite sources.
  case res
  of ResourceStone: 0.84'f32
  of ResourceGold: 0.9'f32
  of ResourceFood: 0.93'f32
  of ResourceWood: 0.94'f32
  of ResourceWater, ResourceNone: 1.0'f32

proc stockpileResourceIcon*(res: StockpileResource): string {.inline.} =
  case res
  of ResourceFood: itemSpriteKey(ItemWheat)
  of ResourceWood: itemSpriteKey(ItemWood)
  of ResourceStone: itemSpriteKey(ItemStone)
  of ResourceGold: itemSpriteKey(ItemGold)
  of ResourceWater: itemSpriteKey(ItemWater)
  of ResourceNone: ""

proc drawUiImageScaled*(key: string, topLeft: Vec2, size: Vec2,
                        tint: Color = TintWhite) =
  ## Draw a UI image in pixel space using top-left anchoring.
  ## This matches MettaScope's widget convention and avoids center-anchor drift.
  if key.len == 0 or key notin bxy or size.x <= 0 or size.y <= 0:
    return
  bxy.drawImage(key, rect(topLeft, size), tint = tint)

# ─── Unit Debug Overlay ──────────────────────────────────────────────────────

const
  DebugLabelFontSize*: float32 = 22
  DebugLabelPadding*: float32 = 3
  DebugLabelScale* = 1.0 / 300.0  # Small labels above units
  DebugLabelYOffset* = -0.65      # Above the unit sprite

proc getUnitCategoryColor(unitClass: AgentUnitClass): Color =
  ## Color-code debug labels by unit category.
  const
    NavalUnits = {UnitBoat, UnitTradeCog, UnitGalley, UnitFireShip,
                  UnitFishingShip, UnitTransportShip, UnitDemoShip, UnitCannonGalleon}
    SiegeUnits = {UnitBatteringRam, UnitMangonel, UnitTrebuchet, UnitScorpion}
    CavalryUnits = {UnitScout, UnitKnight, UnitCavalier, UnitPaladin,
                    UnitLightCavalry, UnitHussar, UnitCataphract, UnitMameluke,
                    UnitCamel, UnitHeavyCamel, UnitImperialCamel,
                    UnitCavalryArcher, UnitHeavyCavalryArcher}
    RangedInfantry = {UnitArcher, UnitCrossbowman, UnitArbalester, UnitLongbowman,
                      UnitJanissary, UnitSkirmisher, UnitEliteSkirmisher,
                      UnitHandCannoneer}
  if unitClass == UnitVillager:
    color(1.0, 1.0, 1.0, 1.0)       # white
  elif unitClass in NavalUnits:
    color(0.0, 0.9, 0.9, 1.0)       # cyan
  elif unitClass in SiegeUnits:
    color(1.0, 0.6, 0.0, 1.0)       # orange
  elif unitClass in CavalryUnits:
    color(0.3, 0.5, 1.0, 1.0)       # blue
  elif unitClass in RangedInfantry:
    color(0.3, 1.0, 0.3, 1.0)       # green
  else:  # infantry (MAA, Longswordsman, Champion, unique infantry, Monk, King, Goblin)
    color(1.0, 0.4, 0.4, 1.0)       # red

proc drawUnitDebugOverlay*() =
  ## Draw class name and sprite key labels above every visible agent.
  ## Toggled by settings.showUnitDebug (F10).
  if not currentViewport.valid:
    return

  let debugStyle = labelStyle(
    HeartCountFontPath,
    DebugLabelFontSize,
    DebugLabelPadding,
    0.0,
    TintWhite  # base white; we tint per-category via drawImage.
  )

  for agent in env.agents:
    if not isAgentAlive(env, agent):
      continue
    let pos = agent.pos
    if not isInViewport(pos):
      continue

    let className = UnitClassLabels[agent.unitClass]
    let spriteBase = getUnitSpriteBase(agent.unitClass, agent.agentId, agent.packed)
    let teamId = getTeamId(agent)
    let labelText = className & " T" & $teamId & " [" & spriteBase & "]"

    let cached = ensureLabel("unit_debug", labelText, debugStyle)
    if cached.imageKey.len > 0 and cached.imageKey in bxy:
      let catColor = getUnitCategoryColor(agent.unitClass)
      let drawPos = pos.vec2 + vec2(0.0, DebugLabelYOffset)
      bxy.drawImage(cached.imageKey, drawPos, angle = 0,
                    scale = DebugLabelScale, tint = catColor)

const HeartPlusThreshold* = 9  # Switch to compact heart counter after this many
