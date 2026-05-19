## Shared UI state, viewport helpers, and day-night lighting utilities.

import
  boxy, windy, vmath,
  common_types, layout

export common_types, layout

type
  PanelType* = enum
    WorldMap

  Panel* = ref object
    panelType*: PanelType
    rect*: IRect
    name*: string

    pos*: Vec2
    vel*: Vec2
    zoom*: float32 = 1.25     # preferred default zoom (start further out)
    zoomTarget*: float32 = 1.25  # smooth zoom target (interpolated toward)
    zoomVel*: float32
    minZoom*: float32 = 1.0   # allow further zoom-out
    maxZoom*: float32 = 8.0   # reduce maximum zoom-out
    hasMouse*: bool = false
    visible*: bool = true

  AreaLayout* = enum
    Horizontal
    Vertical

  WeatherType* = enum
    WeatherNone     ## No weather effects
    WeatherRain     ## Rain particles falling
    WeatherWind     ## Wind particles blowing horizontally
    WeatherSnow     ## Snow particles drifting down

  Area* = ref object
    layout*: AreaLayout
    rect*: IRect
    areas*: seq[Area]
    panels*: seq[Panel]

  Settings* = object
    showFogOfWar* = false
    showVisualRange* = true
    showGrid* = true
    showObservations* = -1
    showDayNightCycle* = true  ## Whether to show day/night lighting cycle
    weatherType* = WeatherRain  ## Current weather effect (Rain, Wind, or None)
    showUnitDebug* = false       ## Show unit class + sprite key labels above agents

var
  window*: Window
  rootArea*: Area
  bxy*: Boxy           # World rendering (sprites, terrain, UI)
  frame*: int

  # Transform stack (parallel to boxy's transform management)
  transformMat*: Mat3 = mat3()
  transformStack*: seq[Mat3]

  # UI Layout system - binary tree for panel positioning
  uiLayout*: UILayout

  worldMapPanel*: Panel
  globalFooterPanel*: Panel

  settings* = Settings()

const
  FooterHeight* = 64
  ResourceBarHeight* = 32  ## Resource bar HUD at top of viewport

const
  MinimapSize* = 200  ## Minimap width/height in pixels
  MinimapMargin* = 8  ## Margin from edges in pixels

  # Day/Night cycle constants
  DayNightCycleDuration* = 3000  ## Frames per full day cycle (5 minutes at 10fps)
  DawnStart* = 0.05'f32          ## Dawn begins at 5% of cycle (after night->dawn transition)
  DayStart* = 0.15'f32           ## Full day begins at 15% of cycle
  DuskStart* = 0.65'f32          ## Dusk begins at 65% of cycle
  NightStart* = 0.80'f32         ## Full night begins at 80% of cycle
  NightToDawnStart* = 0.95'f32   ## Night->Dawn transition begins at 95% of cycle

  # Command Panel constants (Phase 3: context-sensitive action buttons)
  CommandPanelWidth* = 240     ## Width in pixels
  CommandPanelMargin* = 8      ## Margin from edges
  CommandButtonSize* = 48      ## Button size in pixels (square)
  CommandButtonGap* = 6        ## Gap between buttons
  CommandButtonCols* = 4       ## Buttons per row
  CommandPanelPadding* = 10    ## Internal padding

  # Speed multiplier thresholds (used in footer button state checks)
  SpeedSlow* = 0.5'f32          ## Slow-motion speed
  SpeedFast* = 2.0'f32          ## Fast forward speed
  SpeedFaster* = 4.0'f32        ## Faster forward speed
  SpeedSuperMin* = 10.0'f32     ## Minimum threshold for "super" speed

var
  mouseCaptured*: bool = false
  mouseCapturedPanel*: Panel = nil
  mouseDownPos*: Vec2 = vec2(0, 0)
  uiMouseCaptured*: bool = false
  minimapCaptured*: bool = false  ## Mouse is currently dragging on minimap
  playerTeam*: int = -1  ## AI takeover: -1 = observer, 0-7 = controlling that team
  paused*: bool = false  ## Whether simulation is paused
  speedMultiplier*: float32 = 1.0  ## Simulation speed multiplier

  # Day/Night cycle state
  dayNightEnabled*: bool = true              ## Whether day/night cycle is active
  dayTimeProgress*: float32 = 0.25'f32       ## Current time of day (0.0-1.0), starts at mid-day

proc logicalMousePos*(window: Window): Vec2 =
  ## Mouse position in logical coordinates (accounts for HiDPI scaling).
  window.mousePos.vec2 / window.contentScale

proc saveTransform*() =
  ## Push the current transform onto the stack.
  transformStack.add(transformMat)

proc restoreTransform*() =
  ## Pop a transform off the stack.
  transformMat = transformStack.pop()

proc getTransform*(): Mat3 =
  ## Get the current transform matrix.
  transformMat

proc resetTransform*() =
  ## Reset transform to identity and clear stack.
  transformMat = mat3()
  transformStack.setLen(0)

proc translateTransform*(v: Vec2) =
  ## Translate the current transform.
  transformMat = transformMat * translate(v)

proc scaleTransform*(s: Vec2) =
  ## Scale the current transform.
  transformMat = transformMat * scale(s)
type
  ViewportBounds* = object
    ## Visible tile bounds for viewport culling.
    ## All bounds are inclusive and clamped to map dimensions.
    minX*, maxX*: int
    minY*, maxY*: int
    valid*: bool  ## False if viewport calculation failed

var
  currentViewport*: ViewportBounds  ## Updated each frame by updateViewport

proc updateViewport*(panel: Panel, panelRect: IRect, mapWidth, mapHeight: int, contentScale: float32) =
  ## Calculate visible tile bounds for viewport culling.
  ## Call this once per frame before rendering.
  let scaleVal = contentScale
  let rectW = panelRect.w.float32 / scaleVal
  let rectH = panelRect.h.float32 / scaleVal
  let zoomScale = panel.zoom * panel.zoom

  if zoomScale <= 0 or rectW <= 0 or rectH <= 0:
    currentViewport = ViewportBounds(valid: false)
    return

  # Compute the camera center in world coordinates.
  let cx = (rectW / 2.0'f32 - panel.pos.x) / zoomScale
  let cy = (rectH / 2.0'f32 - panel.pos.y) / zoomScale
  let halfW = rectW / (2.0'f32 * zoomScale)
  let halfH = rectH / (2.0'f32 * zoomScale)

  # Expand tile bounds slightly for sprite overhang.
  const margin = 2
  currentViewport = ViewportBounds(
    minX: max(0, int(cx - halfW) - margin),
    maxX: min(mapWidth - 1, int(cx + halfW) + margin),
    minY: max(0, int(cy - halfH) - margin),
    maxY: min(mapHeight - 1, int(cy + halfH) + margin),
    valid: true
  )

{.push inline.}
proc isInViewport*(x, y: int): bool =
  ## Check if a tile position is within the current viewport.
  currentViewport.valid and
    x >= currentViewport.minX and x <= currentViewport.maxX and
    y >= currentViewport.minY and y <= currentViewport.maxY

proc isInViewport*(pos: IVec2): bool =
  ## Checks whether a tile position is within the current viewport.
  isInViewport(pos.x, pos.y)
{.pop.}

type
  AmbientLight* = object
    ## Ambient light color and intensity for day/night cycle
    r*, g*, b*: float32      ## Color multipliers (0.0-1.5)
    intensity*: float32      ## Overall brightness (0.0-1.0)

proc updateDayNightCycle*() =
  ## Advance the day/night cycle by one frame.
  ## Call this once per simulation step when day/night is enabled.
  if not dayNightEnabled or not settings.showDayNightCycle:
    return
  dayTimeProgress = (dayTimeProgress + 1.0'f32 / DayNightCycleDuration.float32) mod 1.0'f32

proc lerp(a, b, t: float32): float32 {.inline.} =
  ## Linearly interpolates between two values.
  a + (b - a) * t

proc smoothstep(t: float32): float32 {.inline.} =
  ## Returns smooth interpolation for gradual transitions.
  let clamped = max(0.0'f32, min(1.0'f32, t))
  clamped * clamped * (3.0'f32 - 2.0'f32 * clamped)

proc getAmbientLight*(): AmbientLight =
  ## Calculate ambient light color based on current time of day.
  ## Returns warm tones during day, cool tones during night, with smooth transitions.
  if not dayNightEnabled or not settings.showDayNightCycle:
    # Default to neutral white when the cycle is disabled.
    return AmbientLight(r: 1.0, g: 1.0, b: 1.0, intensity: 1.0)

  let t = dayTimeProgress

  # Define key colors for each phase.
  const dawnR = 1.1'f32
  const dawnG = 0.85'f32
  const dawnB = 0.7'f32
  const dawnI = 0.85'f32

  const dayR = 1.05'f32
  const dayG = 1.0'f32
  const dayB = 0.95'f32
  const dayI = 1.0'f32

  const duskR = 1.15'f32
  const duskG = 0.75'f32
  const duskB = 0.55'f32
  const duskI = 0.8'f32

  const nightR = 0.6'f32
  const nightG = 0.65'f32
  const nightB = 0.9'f32
  const nightI = 0.55'f32

  var r, g, b, intensity: float32

  if t < DawnStart:
    # Blend from night into dawn at the start of the cycle.
    let phase = t / DawnStart
    let s = smoothstep(phase)
    r = lerp(nightR, dawnR, s)
    g = lerp(nightG, dawnG, s)
    b = lerp(nightB, dawnB, s)
    intensity = lerp(nightI, dawnI, s)

  elif t < DayStart:
    # Blend from dawn into day.
    let phase = (t - DawnStart) / (DayStart - DawnStart)
    let s = smoothstep(phase)
    r = lerp(dawnR, dayR, s)
    g = lerp(dawnG, dayG, s)
    b = lerp(dawnB, dayB, s)
    intensity = lerp(dawnI, dayI, s)

  elif t < DuskStart:
    # Hold stable daytime lighting.
    r = dayR
    g = dayG
    b = dayB
    intensity = dayI

  elif t < NightStart:
    # Blend through dusk before reaching night.
    let phase = (t - DuskStart) / (NightStart - DuskStart)
    if phase < 0.5:
      # Blend from day into dusk.
      let halfS = smoothstep(phase * 2.0)
      r = lerp(dayR, duskR, halfS)
      g = lerp(dayG, duskG, halfS)
      b = lerp(dayB, duskB, halfS)
      intensity = lerp(dayI, duskI, halfS)
    else:
      # Blend from dusk into night.
      let halfS = smoothstep((phase - 0.5) * 2.0)
      r = lerp(duskR, nightR, halfS)
      g = lerp(duskG, nightG, halfS)
      b = lerp(duskB, nightB, halfS)
      intensity = lerp(duskI, nightI, halfS)

  elif t < NightToDawnStart:
    # Hold stable nighttime lighting.
    r = nightR
    g = nightG
    b = nightB
    intensity = nightI

  else:
    # Wrap from late night back into dawn.
    let phase = (t - NightToDawnStart) / (1.0'f32 - NightToDawnStart)
    let s = smoothstep(phase)
    r = lerp(nightR, dawnR, s)
    g = lerp(nightG, dawnG, s)
    b = lerp(nightB, dawnB, s)
    intensity = lerp(nightI, dawnI, s)

  AmbientLight(r: r, g: g, b: b, intensity: intensity)

proc applyAmbient*(baseR, baseG, baseB, baseI: float32, ambient: AmbientLight): tuple[r, g, b, i: float32] {.inline.} =
  ## Apply ambient light to a base color, returning modified values.
  ## Multiplies color channels by ambient and modulates intensity.
  (
    r: min(1.5'f32, baseR * ambient.r),
    g: min(1.5'f32, baseG * ambient.g),
    b: min(1.5'f32, baseB * ambient.b),
    i: baseI * ambient.intensity
  )
