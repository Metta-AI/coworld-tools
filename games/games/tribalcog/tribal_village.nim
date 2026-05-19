import std/[os, strutils, math],
  boxy, windy, vmath, pixie,
  src/environment, src/common, src/renderer, src/agent_control, src/tileset,
  src/minimap, src/command_panel, src/tooltips, src/semantic, src/gui_assets

when compileOption("profiler"):
  import std/nimprof

when defined(renderTiming):
  import std/monotimes

when defined(audio):
  import src/audio, src/audio_events

# Initialize the global environment for the renderer/game loop.
env = newEnvironment()

let profileStepsStr = getEnv("TV_PROFILE_STEPS", "")
if profileStepsStr.len > 0:
  let profileSteps = parseInt(profileStepsStr)
  if globalController.isNil:
    let profileExternal = existsEnv("TRIBAL_PYTHON_CONTROL") or existsEnv("TRIBAL_EXTERNAL_CONTROL")
    initGlobalController(if profileExternal: ExternalNN else: BuiltinAI)
  var actionsArray: array[MapAgents, uint16]
  for _ in 0 ..< profileSteps:
    actionsArray = getActions(env)
    env.step(addr actionsArray)
  quit(QuitSuccess)

when defined(renderTiming):
  let renderTimingStartStr = getEnv("TV_RENDER_TIMING", "")
  let renderTimingWindowStr = getEnv("TV_RENDER_TIMING_WINDOW", "0")
  let renderTimingEveryStr = getEnv("TV_RENDER_TIMING_EVERY", "1")
  let renderTimingStart = block:
    if renderTimingStartStr.len == 0:
      -1
    else:
      try:
        parseInt(renderTimingStartStr)
      except ValueError:
        -1
  let renderTimingWindow = block:
    if renderTimingWindowStr.len == 0:
      0
    else:
      try:
        parseInt(renderTimingWindowStr)
      except ValueError:
        0
  let renderTimingEvery = block:
    if renderTimingEveryStr.len == 0:
      1
    else:
      try:
        max(1, parseInt(renderTimingEveryStr))
      except ValueError:
        1
  let renderTimingExitStr = getEnv("TV_RENDER_TIMING_EXIT", "")
  let renderTimingExit = block:
    if renderTimingExitStr.len == 0:
      -1
    else:
      try:
        parseInt(renderTimingExitStr)
      except ValueError:
        -1

  proc msBetween(a, b: MonoTime): float64 =
    (b.ticks - a.ticks).float64 / 1_000_000.0

when not defined(emscripten):
  import opengl

let baseWindowSize = ivec2(1280, 800)
let initialWindowSize = block:
  ## Choose a large window that fits on the primary screen
  when defined(emscripten):
    ivec2(baseWindowSize.x * 2, baseWindowSize.y * 2)
  elif defined(linux):
    # Windy does not expose getScreens on Linux; fall back to a safe default.
    baseWindowSize
  else:
    let screens = getScreens()
    var target = ivec2(baseWindowSize.x * 2, baseWindowSize.y * 2)
    for s in screens:
      if s.primary:
        let sz = s.size()
        target = ivec2(min(target.x, sz.x), min(target.y, sz.y))
        break
    target

window = newWindow("Tribal Village", initialWindowSize)
makeContextCurrent(window)

when not defined(emscripten):
  loadExtensions()

bxy = newBoxy()
rootArea = Area(layout: Horizontal)
worldMapPanel = Panel(panelType: WorldMap, name: "World Map")

rootArea.areas.add(Area(layout: Horizontal))
rootArea.panels.add(worldMapPanel)

# Initialize the UI layout system
uiLayout = createDefaultLayout()

let mapCenter = vec2(
  (MapWidth.float32 - 1.0'f32) / 2.0'f32,
  (MapHeight.float32 - 1.0'f32) / 2.0'f32
)

var lastPanelSize = ivec2(0, 0)
var lastContentScale: float32 = 0.0
var dragStartWorld: Vec2 = vec2(0, 0)
var isDragging: bool = false

# Gatherable resource kinds for right-click gather command
const GatherableResourceKinds* = {Tree, Wheat, Fish, Stone, Gold, Bush, Cactus}

var actionsArray: array[MapAgents, uint16]

proc display() =
  # Begin semantic capture for this frame (no-op if disabled)
  beginSemanticFrame()

  when defined(renderTiming):
    # Early frame timing - capture from the very start
    let timingActive = renderTimingStart >= 0 and frame >= renderTimingStart and
      frame <= renderTimingStart + renderTimingWindow
    var tFrameStart: MonoTime
    var tPhaseStart: MonoTime
    var tInputMs, tSimMs, tBeginFrameMs, tSetupMs, tInteractionMs: float64
    if timingActive:
      tFrameStart = getMonoTime()
      tPhaseStart = tFrameStart

  # Handle mouse capture release
  if window.buttonReleased[MouseLeft]:
    common.mouseCaptured = false
    common.mouseCapturedPanel = nil

  if window.buttonPressed[KeySpace]:
    if play:
      play = false
    else:
      lastSimTime = nowSeconds()
      actionsArray = getActions(env)
      env.step(addr actionsArray)
  if window.buttonPressed[KeyMinus] or window.buttonPressed[KeyLeftBracket]:
    playSpeed *= 0.5
    playSpeed = clamp(playSpeed, 0.00001, 60.0)
    play = true
  if window.buttonPressed[KeyEqual] or window.buttonPressed[KeyRightBracket]:
    playSpeed *= 2
    playSpeed = clamp(playSpeed, 0.00001, 60.0)
    play = true

  if window.buttonPressed[KeyN]:
    dec settings.showObservations
  if window.buttonPressed[KeyM]:
    inc settings.showObservations
  settings.showObservations = clamp(settings.showObservations, -1, 23)

  # AI takeover toggle: Tab cycles Observer -> Team 0-7 -> Observer
  if window.buttonPressed[KeyTab]:
    let oldTeam = playerTeam
    playerTeam = (playerTeam + 2) mod (MapRoomObjectsTeams + 1) - 1
    # Cycles: -1 -> 0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> -1
    # Clear commands for agents on the old team when switching modes
    if oldTeam >= 0:
      for agent in env.thingsByKind[Agent]:
        if not isNil(agent) and agent.getTeamId() == oldTeam:
          stopAgent(agent.agentId)

  # F1-F8 to switch team - also clears commands on old team
  template switchTeam(newTeam: int) =
    let oldTeam = playerTeam
    playerTeam = newTeam
    if oldTeam >= 0 and oldTeam != newTeam:
      for agent in env.thingsByKind[Agent]:
        if not isNil(agent) and agent.getTeamId() == oldTeam:
          stopAgent(agent.agentId)

  if window.buttonPressed[KeyF1]: switchTeam(0)
  if window.buttonPressed[KeyF2]: switchTeam(1)
  if window.buttonPressed[KeyF3]: switchTeam(2)
  if window.buttonPressed[KeyF4]: switchTeam(3)
  if window.buttonPressed[KeyF5]: switchTeam(4)
  if window.buttonPressed[KeyF6]: switchTeam(5)
  if window.buttonPressed[KeyF7]: switchTeam(6)
  if window.buttonPressed[KeyF8]: switchTeam(7)

  # F9 cycles weather effects: Rain -> Wind -> Snow -> None -> Rain
  if window.buttonPressed[KeyF9]:
    settings.weatherType = case settings.weatherType
      of WeatherRain: WeatherWind
      of WeatherWind: WeatherSnow
      of WeatherSnow: WeatherNone
      of WeatherNone: WeatherRain

  # F10 toggles unit debug overlay (class name + sprite key)
  if window.buttonPressed[KeyF10]:
    settings.showUnitDebug = not settings.showUnitDebug

  # F11 toggles fullscreen
  when not defined(emscripten):
    if window.buttonPressed[KeyF11]:
      window.fullscreen = not window.fullscreen

  # Home key centers camera on player's TC (or map center for observer)
  if window.buttonPressed[KeyHome]:
    var centerPos = mapCenter
    if playerTeam >= 0:
      # Find this team's TC
      for thing in env.thingsByKind[TownCenter]:
        if not thing.isNil and thing.teamId == playerTeam:
          centerPos = vec2(thing.pos.x.float32, thing.pos.y.float32)
          break
    let scaleF = window.contentScale.float32
    let logicalW = worldMapPanel.rect.w.float32 / scaleF
    let logicalH = worldMapPanel.rect.h.float32 / scaleF
    let zs = worldMapPanel.zoom * worldMapPanel.zoom
    worldMapPanel.pos = vec2(logicalW / 2.0'f32 - centerPos.x * zs,
                             logicalH / 2.0'f32 - centerPos.y * zs)
    worldMapPanel.vel = vec2(0, 0)

  when defined(renderTiming):
    if timingActive:
      let tNow = getMonoTime()
      tInputMs = msBetween(tPhaseStart, tNow)
      tPhaseStart = tNow

  let now = nowSeconds()
  while play and (lastSimTime + playSpeed < now):
    lastSimTime += playSpeed
    actionsArray = getActions(env)
    env.step(addr actionsArray)
    updateDayNightCycle()  # Advance day/night cycle with simulation

  when defined(renderTiming):
    if timingActive:
      let tNow = getMonoTime()
      tSimMs = msBetween(tPhaseStart, tNow)
      tPhaseStart = tNow

  bxy.beginFrame(window.size)
  resetTransform()  # Reset custom transform stack at frame start

  when defined(renderTiming):
    if timingActive:
      let tNow = getMonoTime()
      tBeginFrameMs = msBetween(tPhaseStart, tNow)
      tPhaseStart = tNow

  # Panels fill the window; simple recursive sizing
  rootArea.rect = IRect(x: 0, y: 0, w: window.size.x, h: window.size.y)
  proc updateArea(area: Area) =
    for panel in area.panels:
      panel.rect = area.rect
    for sub in area.areas:
      sub.rect = area.rect
      updateArea(sub)
  updateArea(rootArea)

  # Update UI layout system for current window size
  updateLayout(
    uiLayout,
    window.size.x.float32,
    window.size.y.float32,
    MinimapSize.float32,
    CommandPanelWidth.float32,
    ResourceBarHeight.float32,
    FooterHeight.float32,
    MinimapMargin.float32
  )

  let panelRectInt = worldMapPanel.rect
  let panelRect = Rect(
    x: panelRectInt.x.float32,
    y: panelRectInt.y.float32,
    w: panelRectInt.w.float32,
    h: panelRectInt.h.float32
  )

  if panelRectInt.w != lastPanelSize.x or
     panelRectInt.h != lastPanelSize.y or
     window.contentScale.float32 != lastContentScale:
    # Centers the map and chooses a zoom that fits the viewport when the window is resized.
    let scaleF = window.contentScale.float32
    let logicalW = panelRectInt.w.float32 / scaleF
    let logicalH = panelRectInt.h.float32 / scaleF
    if logicalW > 0 and logicalH > 0:
      let padding = 1.0'f32  # Zoom in one more notch
      let zoomForW = sqrt(logicalW / MapWidth.float32) * padding
      let zoomForH = sqrt(logicalH / MapHeight.float32) * padding
      let targetZoom = min(zoomForW, zoomForH).clamp(worldMapPanel.minZoom, worldMapPanel.maxZoom)
      worldMapPanel.zoom = targetZoom
      worldMapPanel.zoomTarget = targetZoom

      let zoomScale = worldMapPanel.zoom * worldMapPanel.zoom
      worldMapPanel.pos = vec2(
        logicalW / 2.0'f32 - mapCenter.x * zoomScale,
        logicalH / 2.0'f32 - mapCenter.y * zoomScale
      )
      worldMapPanel.vel = vec2(0, 0)
    lastPanelSize = ivec2(panelRectInt.w, panelRectInt.h)
    lastContentScale = window.contentScale.float32

  bxy.pushLayer()
  bxy.saveTransform()
  saveTransform()
  bxy.translate(vec2(panelRect.x, panelRect.y))
  translateTransform(vec2(panelRect.x, panelRect.y))  # Keep custom stack in sync

  # Pan and zoom handling
  bxy.saveTransform()
  saveTransform()

  let scaleVal = window.contentScale
  let logicalRect = Rect(
    x: panelRect.x / scaleVal,
    y: panelRect.y / scaleVal,
    w: panelRect.w / scaleVal,
    h: panelRect.h / scaleVal
  )
  let footerHeightLogical = FooterHeight.float32 / scaleVal
  let footerRectLogical = Rect(
    x: logicalRect.x,
    y: logicalRect.y + logicalRect.h - footerHeightLogical,
    w: logicalRect.w,
    h: footerHeightLogical
  )

  let mousePos = logicalMousePos(window)
  let insideRect = mousePos.x >= logicalRect.x and mousePos.x <= logicalRect.x + logicalRect.w and
    mousePos.y >= logicalRect.y and mousePos.y <= logicalRect.y + logicalRect.h and
    not (mousePos.x >= footerRectLogical.x and mousePos.x <= footerRectLogical.x + footerRectLogical.w and
      mousePos.y >= footerRectLogical.y and mousePos.y <= footerRectLogical.y + footerRectLogical.h)

  let onMinimap = isInMinimap(panelRectInt, window.mousePos.vec2)
  let onCommandPanel = isInCommandPanel(panelRectInt, window.mousePos.vec2)
  worldMapPanel.hasMouse = worldMapPanel.visible and not onMinimap and not onCommandPanel and not minimapCaptured and
    ((not mouseCaptured and insideRect) or
    (mouseCaptured and mouseCapturedPanel == worldMapPanel))

  if worldMapPanel.hasMouse and window.buttonPressed[MouseLeft]:
    mouseCaptured = true
    mouseCapturedPanel = worldMapPanel
    mouseDownPos = logicalMousePos(window)

  if worldMapPanel.hasMouse:
    if window.scrollDelta.y != 0:
      let zoomSensitivity = when defined(emscripten): ZoomSensitivityWeb else: ZoomSensitivityDesktop
      # Update zoom target; smooth interpolation happens below
      let zoomFactor64 = pow(1.0 - zoomSensitivity, window.scrollDelta.y.float64)
      let zoomFactor = zoomFactor64.float32
      worldMapPanel.zoomTarget = clamp(worldMapPanel.zoomTarget * zoomFactor, worldMapPanel.minZoom, worldMapPanel.maxZoom)

  # Smooth zoom interpolation toward target (runs every frame)
  let zoomDiff = worldMapPanel.zoomTarget - worldMapPanel.zoom
  if abs(zoomDiff) > 0.001'f32:
    let scaleF = window.contentScale.float32
    let rectOrigin = vec2(panelRect.x / scaleF, panelRect.y / scaleF)
    let localMouse = logicalMousePos(window) - rectOrigin

    let oldMat = translate(worldMapPanel.pos) * scale(vec2(worldMapPanel.zoom*worldMapPanel.zoom, worldMapPanel.zoom*worldMapPanel.zoom))
    let oldWorldPoint = oldMat.inverse() * localMouse

    worldMapPanel.zoom = worldMapPanel.zoom + zoomDiff * ZoomSmoothRate

    let newMat = translate(worldMapPanel.pos) * scale(vec2(worldMapPanel.zoom*worldMapPanel.zoom, worldMapPanel.zoom*worldMapPanel.zoom))
    let newWorldPoint = newMat.inverse() * localMouse
    worldMapPanel.pos += (newWorldPoint - oldWorldPoint) * (worldMapPanel.zoom * worldMapPanel.zoom)
  else:
    worldMapPanel.zoom = worldMapPanel.zoomTarget

  let zoomScale = worldMapPanel.zoom * worldMapPanel.zoom
  if zoomScale > 0:
    let scaleF = window.contentScale.float32
    let rectW = panelRect.w / scaleF
    let rectH = panelRect.h / scaleF

    if rectW > 0 and rectH > 0:
      let mapMinX = -0.5'f32
      let mapMinY = -0.5'f32
      let mapMaxX = MapWidth.float32 - 0.5'f32
      let mapMaxY = MapHeight.float32 - 0.5'f32
      let mapWidthF = mapMaxX - mapMinX
      let mapHeightF = mapMaxY - mapMinY

      let viewHalfW = rectW / (2.0'f32 * zoomScale)
      let viewHalfH = rectH / (2.0'f32 * zoomScale)

      var cx = (rectW / 2.0'f32 - worldMapPanel.pos.x) / zoomScale
      var cy = (rectH / 2.0'f32 - worldMapPanel.pos.y) / zoomScale

      let minVisiblePixels = min(MinVisibleMapPixels, min(rectW, rectH) * 0.5'f32)
      let minVisibleWorld = minVisiblePixels / zoomScale
      let maxVisibleUnitsX = min(minVisibleWorld, mapWidthF / 2.0'f32)
      let maxVisibleUnitsY = min(minVisibleWorld, mapHeightF / 2.0'f32)

      let minCenterX = mapMinX + maxVisibleUnitsX - viewHalfW
      let maxCenterX = mapMaxX - maxVisibleUnitsX + viewHalfW
      let minCenterY = mapMinY + maxVisibleUnitsY - viewHalfH
      let maxCenterY = mapMaxY - maxVisibleUnitsY + viewHalfH

      cx = cx.clamp(minCenterX, maxCenterX)
      cy = cy.clamp(minCenterY, maxCenterY)

      worldMapPanel.pos.x = rectW / 2.0'f32 - cx * zoomScale
      worldMapPanel.pos.y = rectH / 2.0'f32 - cy * zoomScale

  let scaleF = window.contentScale.float32
  # Update screen shake for combat feedback
  updateScreenShake()
  bxy.translate((worldMapPanel.pos + screenShakeOffset) * scaleF)
  translateTransform((worldMapPanel.pos + screenShakeOffset) * scaleF)  # Keep custom stack in sync
  let zoomScaled = worldMapPanel.zoom * worldMapPanel.zoom * scaleF
  bxy.scale(vec2(zoomScaled, zoomScaled))
  scaleTransform(vec2(zoomScaled, zoomScaled))  # Keep custom stack in sync

  # Update viewport bounds for culling (before any rendering)
  updateViewport(worldMapPanel, panelRectInt, MapWidth, MapHeight, scaleF)

  when defined(renderTiming):
    if timingActive:
      let tNow = getMonoTime()
      tSetupMs = msBetween(tPhaseStart, tNow)
      tPhaseStart = tNow

  let footerRect = Rect(
    x: panelRect.x,
    y: panelRect.y + panelRect.h - FooterHeight.float32,
    w: panelRect.w,
    h: FooterHeight.float32
  )
  let mousePosPx = window.mousePos.vec2
  var blockSelection = uiMouseCaptured or minimapCaptured
  var clearUiCapture = false

  # Minimap click-to-center: click or drag on minimap pans the camera
  if window.buttonPressed[MouseLeft] and isInMinimap(panelRectInt, mousePosPx):
    minimapCaptured = true
    blockSelection = true
    worldMapPanel.vel = vec2(0, 0)
    # Center camera on clicked world position
    let worldPos = minimapToWorld(panelRectInt, mousePosPx)
    let scaleF = window.contentScale.float32
    let rectW = panelRect.w / scaleF
    let rectH = panelRect.h / scaleF
    let zs = worldMapPanel.zoom * worldMapPanel.zoom
    worldMapPanel.pos = vec2(rectW / 2.0'f32 - worldPos.x * zs,
                             rectH / 2.0'f32 - worldPos.y * zs)

  # Minimap drag continues to pan camera
  if minimapCaptured and window.buttonDown[MouseLeft] and not window.buttonPressed[MouseLeft]:
    if isInMinimap(panelRectInt, mousePosPx):
      blockSelection = true
      worldMapPanel.vel = vec2(0, 0)
      let worldPos = minimapToWorld(panelRectInt, mousePosPx)
      let scaleF = window.contentScale.float32
      let rectW = panelRect.w / scaleF
      let rectH = panelRect.h / scaleF
      let zs = worldMapPanel.zoom * worldMapPanel.zoom
      worldMapPanel.pos = vec2(rectW / 2.0'f32 - worldPos.x * zs,
                               rectH / 2.0'f32 - worldPos.y * zs)

  if minimapCaptured and window.buttonReleased[MouseLeft]:
    minimapCaptured = false

  # Command panel click handling
  if window.buttonPressed[MouseLeft] and isInCommandPanel(panelRectInt, mousePosPx):
    blockSelection = true
    let clickedCmd = handleCommandPanelClick(panelRectInt, mousePosPx)
    # Process the clicked command
    case clickedCmd
    of CmdBuild:
      buildMenuOpen = true
    of CmdBuildBack:
      buildMenuOpen = false
      buildingPlacementMode = false
    of CmdBuildHouse, CmdBuildMill, CmdBuildLumberCamp, CmdBuildMiningCamp,
       CmdBuildBarracks, CmdBuildArcheryRange, CmdBuildStable, CmdBuildWall,
       CmdBuildBlacksmith, CmdBuildMarket:
      buildingPlacementMode = true
      buildingPlacementKind = commandKindToBuildingKind(clickedCmd)
    of CmdStop:
      for sel in selection:
        if not isNil(sel) and sel.kind == Agent:
          stopAgent(sel.agentId)
    of CmdHoldPosition:
      for sel in selection:
        if not isNil(sel) and sel.kind == Agent:
          setAgentHoldPosition(sel.agentId, sel.pos)
    of CmdFormationLine, CmdFormationBox, CmdFormationStaggered:
      # Find which control group the selection belongs to
      # or create a new control group from the selection
      var targetGroup = -1
      if selection.len > 0 and not isNil(selection[0]) and selection[0].kind == Agent:
        targetGroup = findAgentControlGroup(selection[0].agentId)
      if targetGroup < 0 and selection.len > 1:
        # No existing group - assign selection to first empty group
        for g in 0 ..< ControlGroupCount:
          if controlGroups[g].len == 0:
            controlGroups[g] = selection
            targetGroup = g
            break
        # If no empty group, use group 0
        if targetGroup < 0:
          controlGroups[0] = selection
          targetGroup = 0
      if targetGroup >= 0:
        let ftype = case clickedCmd
          of CmdFormationLine: FormationLine
          of CmdFormationBox: FormationBox
          of CmdFormationStaggered: FormationStaggered
          else: FormationNone
        setFormation(targetGroup, ftype)
    of CmdSetRally:
      # Enter rally point mode when clicking the Set Rally button on a building
      if selection.len == 1 and isBuildingKind(selection[0].kind) and
         selection[0].teamId == playerTeam:
        rallyPointMode = true
    # Training commands - queue unit production
    of CmdTrainVillager, CmdTrainManAtArms, CmdTrainArcher, CmdTrainScout,
       CmdTrainKnight, CmdTrainMonk, CmdTrainBatteringRam, CmdTrainMangonel,
       CmdTrainTrebuchet, CmdTrainBoat, CmdTrainTradeCog:
      if selection.len == 1 and isBuildingKind(selection[0].kind) and
         selection[0].teamId == playerTeam:
        let building = selection[0]
        let unitClass = case clickedCmd
          of CmdTrainVillager: UnitVillager
          of CmdTrainManAtArms: UnitManAtArms
          of CmdTrainArcher: UnitArcher
          of CmdTrainScout: UnitScout
          of CmdTrainKnight: UnitKnight
          of CmdTrainMonk: UnitMonk
          of CmdTrainBatteringRam: UnitBatteringRam
          of CmdTrainMangonel: UnitMangonel
          of CmdTrainTrebuchet: UnitTrebuchet
          of CmdTrainBoat: UnitBoat
          of CmdTrainTradeCog: UnitTradeCog
          else: UnitVillager
        # Shift-click to train 5 units, normal click trains 1
        let count = if window.buttonDown[KeyLeftShift] or window.buttonDown[KeyRightShift]: 5 else: 1
        discard env.uiQueueTrainUnit(building, unitClass, count)
    # Blacksmith research commands
    of CmdResearchMeleeAttack, CmdResearchArcherAttack, CmdResearchInfantryArmor,
       CmdResearchCavalryArmor, CmdResearchArcherArmor:
      if selection.len == 1 and selection[0].kind == Blacksmith and
         selection[0].teamId == playerTeam:
        let upgradeType = case clickedCmd
          of CmdResearchMeleeAttack: UpgradeMeleeAttack
          of CmdResearchArcherAttack: UpgradeArcherAttack
          of CmdResearchInfantryArmor: UpgradeInfantryArmor
          of CmdResearchCavalryArmor: UpgradeCavalryArmor
          of CmdResearchArcherArmor: UpgradeArcherArmor
          else: UpgradeMeleeAttack
        discard env.uiResearchBlacksmithUpgrade(selection[0], upgradeType)
    # University research commands
    of CmdResearchBallistics, CmdResearchMurderHoles, CmdResearchMasonry,
       CmdResearchArchitecture, CmdResearchTreadmillCrane, CmdResearchArrowslits,
       CmdResearchHeatedShot, CmdResearchSiegeEngineers, CmdResearchChemistry:
      if selection.len == 1 and selection[0].kind == University and
         selection[0].teamId == playerTeam:
        let techType = case clickedCmd
          of CmdResearchBallistics: TechBallistics
          of CmdResearchMurderHoles: TechMurderHoles
          of CmdResearchMasonry: TechMasonry
          of CmdResearchArchitecture: TechArchitecture
          of CmdResearchTreadmillCrane: TechTreadmillCrane
          of CmdResearchArrowslits: TechArrowslits
          of CmdResearchHeatedShot: TechHeatedShot
          of CmdResearchSiegeEngineers: TechSiegeEngineers
          of CmdResearchChemistry: TechChemistry
          else: TechBallistics
        discard env.uiResearchUniversityTech(selection[0], techType)
    # Castle unique tech research commands
    of CmdResearchCastleTech1:
      if selection.len == 1 and selection[0].kind == Castle and
         selection[0].teamId == playerTeam:
        discard env.uiResearchCastleTech(selection[0], 0)
    of CmdResearchCastleTech2:
      if selection.len == 1 and selection[0].kind == Castle and
         selection[0].teamId == playerTeam:
        discard env.uiResearchCastleTech(selection[0], 1)
    else:
      discard

  if window.buttonPressed[MouseLeft] and not minimapCaptured and
      mousePosPx.x >= footerRect.x and mousePosPx.x <= footerRect.x + footerRect.w and
      mousePosPx.y >= footerRect.y and mousePosPx.y <= footerRect.y + footerRect.h:
    uiMouseCaptured = true
    blockSelection = true
  if uiMouseCaptured and window.buttonReleased[MouseLeft]:
    let buttons = buildFooterButtons(panelRectInt)
    for button in buttons:
      if mousePosPx.x >= button.rect.x.float32 and mousePosPx.x <= (button.rect.x + button.rect.w).float32 and
          mousePosPx.y >= button.rect.y.float32 and mousePosPx.y <= (button.rect.y + button.rect.h).float32:
        case button.kind
        of FooterPlayPause:
          if play:
            play = false
          else:
            play = true
            lastSimTime = nowSeconds()
        of FooterStep:
          play = false
          lastSimTime = nowSeconds()
          actionsArray = getActions(env)
          env.step(addr actionsArray)
        of FooterSlow:
          playSpeed = SlowPlaySpeed
          play = true
          lastSimTime = nowSeconds()
        of FooterFast:
          playSpeed = FastPlaySpeed
          play = true
          lastSimTime = nowSeconds()
        of FooterFaster:
          playSpeed = FasterPlaySpeed
          play = true
          lastSimTime = nowSeconds()
        break
    clearUiCapture = true
    blockSelection = true

  # Queue cancel button handling is not yet implemented
  # TODO: Add queueCancelButtons from command_panel rendering

  if not blockSelection:
    if window.buttonPressed[MouseLeft]:
      mouseDownPos = logicalMousePos(window)
      dragStartWorld = getTransform().inverse * window.mousePos.vec2
      isDragging = false

    if window.buttonDown[MouseLeft] and not window.buttonPressed[MouseLeft]:
      let dragDist = (logicalMousePos(window) - mouseDownPos).length
      if dragDist > DragDistanceThreshold:
        isDragging = true

    if window.buttonReleased[MouseLeft]:
      if isDragging:
        # Drag-box multi-select: find all agents within the rectangle
        let dragEndWorld = getTransform().inverse * window.mousePos.vec2
        let minX = min(dragStartWorld.x, dragEndWorld.x)
        let maxX = max(dragStartWorld.x, dragEndWorld.x)
        let minY = min(dragStartWorld.y, dragEndWorld.y)
        let maxY = max(dragStartWorld.y, dragEndWorld.y)
        var boxSelection: seq[Thing] = @[]
        for agent in env.thingsByKind[Agent]:
          if not isNil(agent) and isValidPos(agent.pos) and
             env.isAgentAlive(agent):
            # Filter by player team when in player control mode
            if playerTeam >= 0 and agent.getTeamId() != playerTeam:
              continue
            let ax = agent.pos.x.float32
            let ay = agent.pos.y.float32
            if ax >= minX and ax <= maxX and ay >= minY and ay <= maxY:
              boxSelection.add(agent)
        if boxSelection.len > 0:
          selection = boxSelection
          selectedPos = boxSelection[0].pos
          # Play selection sound for first selected unit
          when defined(audio):
            if boxSelection[0].kind == Agent:
              audioOnUnitSelected(boxSelection[0].unitClass)
        else:
          selection = @[]
        isDragging = false
      else:
        # Click select (existing behavior)
        selection = @[]
        let
          mousePos = getTransform().inverse * window.mousePos.vec2
          gridPos = (mousePos + vec2(0.5, 0.5)).ivec2
        if gridPos.x >= 0 and gridPos.x < MapWidth and
           gridPos.y >= 0 and gridPos.y < MapHeight:
          selectedPos = gridPos
          let thing = env.grid[gridPos.x][gridPos.y]
          if not isNil(thing):
            if window.buttonDown[KeyLeftShift] or window.buttonDown[KeyRightShift]:
              # Shift-click: toggle unit in selection
              var found = false
              for i, s in selection:
                if s == thing:
                  selection.delete(i)
                  found = true
                  break
              if not found:
                selection.add(thing)
            else:
              selection = @[thing]
              # Play selection sound when selecting a unit
              when defined(audio):
                if thing.kind == Agent:
                  audioOnUnitSelected(thing.unitClass)

    # Right-click command handling (AoE2-style)
    if window.buttonPressed[MouseRight] and selection.len > 0 and playerTeam >= 0:
      let
        mousePos = getTransform().inverse * window.mousePos.vec2
        gridPos = (mousePos + vec2(0.5, 0.5)).ivec2
      if gridPos.x >= 0 and gridPos.x < MapWidth and
         gridPos.y >= 0 and gridPos.y < MapHeight:
        let shiftDown = window.buttonDown[KeyLeftShift] or window.buttonDown[KeyRightShift]
        let targetThing = env.grid[gridPos.x][gridPos.y]
        let bgThing = env.backgroundGrid[gridPos.x][gridPos.y]

        # Play command acknowledgment sound for first selected unit
        when defined(audio):
          if selection.len > 0 and not isNil(selection[0]) and selection[0].kind == Agent:
            audioOnUnitCommand(selection[0].unitClass)

        # Check if selection is a single production building for rally point setting
        if selection.len == 1 and isBuildingKind(selection[0].kind) and
           selection[0].teamId == playerTeam and
           (buildingHasTrain(selection[0].kind) or selection[0].kind == TownCenter):
          # Set rally point for the building (AoE2-style)
          setBuildingRallyPoint(env, selection[0].pos.x, selection[0].pos.y, gridPos.x, gridPos.y)
          # Exit rally point mode if active
          rallyPointMode = false
        # Determine command type based on target
        # Check if there's something at the target position
        elif not isNil(targetThing):
          if targetThing.kind == Agent:
            # Right-click on agent
            let targetTeam = getTeamId(targetThing)
            if targetTeam != playerTeam:
              # Enemy agent: attack-move to target
              for sel in selection:
                if not isNil(sel) and sel.kind == Agent and env.isAgentAlive(sel):
                  if shiftDown:
                    # Shift+right-click: queue command (AoE2-style shift-queue)
                    queueAgentAttackMove(sel.agentId, gridPos)
                  else:
                    # Normal click: clear queue and issue immediate command
                    clearAgentCommandQueue(sel.agentId)
                    setAgentAttackMoveTarget(sel.agentId, gridPos)
            else:
              # Friendly agent: follow
              for sel in selection:
                if not isNil(sel) and sel.kind == Agent and env.isAgentAlive(sel):
                  if shiftDown:
                    queueAgentFollow(sel.agentId, targetThing.agentId)
                  else:
                    clearAgentCommandQueue(sel.agentId)
                    setAgentFollowTarget(sel.agentId, targetThing.agentId)
          elif targetThing.kind in GatherableResourceKinds:
            # Resource: gather command (attack-move for villagers)
            for sel in selection:
              if not isNil(sel) and sel.kind == Agent and env.isAgentAlive(sel):
                if shiftDown:
                  queueAgentAttackMove(sel.agentId, gridPos)
                else:
                  clearAgentCommandQueue(sel.agentId)
                  setAgentAttackMoveTarget(sel.agentId, gridPos)
          elif isBuildingKind(targetThing.kind):
            # Building: check if friendly or enemy
            if targetThing.teamId == playerTeam:
              # Friendly building: garrison/dropoff (attack-move to building)
              for sel in selection:
                if not isNil(sel) and sel.kind == Agent and env.isAgentAlive(sel):
                  if shiftDown:
                    queueAgentAttackMove(sel.agentId, gridPos)
                  else:
                    clearAgentCommandQueue(sel.agentId)
                    setAgentAttackMoveTarget(sel.agentId, gridPos)
            else:
              # Enemy building: attack-move
              for sel in selection:
                if not isNil(sel) and sel.kind == Agent and env.isAgentAlive(sel):
                  if shiftDown:
                    queueAgentAttackMove(sel.agentId, gridPos)
                  else:
                    clearAgentCommandQueue(sel.agentId)
                    setAgentAttackMoveTarget(sel.agentId, gridPos)
          else:
            # Other things (Tumor, Spawner, etc.): attack-move
            for sel in selection:
              if not isNil(sel) and sel.kind == Agent and env.isAgentAlive(sel):
                if shiftDown:
                  queueAgentAttackMove(sel.agentId, gridPos)
                else:
                  clearAgentCommandQueue(sel.agentId)
                  setAgentAttackMoveTarget(sel.agentId, gridPos)
        elif not isNil(bgThing) and bgThing.kind in GatherableResourceKinds:
          # Background thing is a gatherable resource (like Fish)
          for sel in selection:
            if not isNil(sel) and sel.kind == Agent and env.isAgentAlive(sel):
              if shiftDown:
                queueAgentAttackMove(sel.agentId, gridPos)
              else:
                clearAgentCommandQueue(sel.agentId)
                setAgentAttackMoveTarget(sel.agentId, gridPos)
        else:
          # Empty tile: move command
          for sel in selection:
            if not isNil(sel) and sel.kind == Agent and env.isAgentAlive(sel):
              if shiftDown:
                # Shift+right-click: queue command (AoE2-style shift-queue)
                queueAgentAttackMove(sel.agentId, gridPos)
              else:
                # Normal click: clear queue and issue immediate command
                clearAgentCommandQueue(sel.agentId)
                setAgentAttackMoveTarget(sel.agentId, gridPos)

  # Control group handling (AoE2-style: Ctrl+N assigns, N recalls, double-tap centers)
  let ctrlDown = window.buttonDown[KeyLeftControl] or window.buttonDown[KeyRightControl]
  const numberKeys = [Key0, Key1, Key2, Key3, Key4, Key5, Key6, Key7, Key8, Key9]
  let groupNow = nowSeconds()
  let doubleTapThreshold = DoubleTapThreshold  # Use named constant

  for i in 0 ..< ControlGroupCount:
    if window.buttonPressed[numberKeys[i]]:
      if ctrlDown:
        # Ctrl+N: assign current selection to group N
        controlGroups[i] = selection
      else:
        # N: recall group N
        # Filter out dead/nil units before recalling
        var alive: seq[Thing] = @[]
        for thing in controlGroups[i]:
          if not isNil(thing) and thing.kind == Agent and
             env.isAgentAlive(thing):
            alive.add(thing)
        controlGroups[i] = alive

        if alive.len > 0:
          # Double-tap detection: center camera on group
          if lastGroupKeyIndex == i and (groupNow - lastGroupKeyTime[i]) < doubleTapThreshold:
            # Double-tap: center camera on group centroid
            var cx, cy: float32 = 0
            for thing in alive:
              cx += thing.pos.x.float32
              cy += thing.pos.y.float32
            cx /= alive.len.float32
            cy /= alive.len.float32
            let scaleF = window.contentScale.float32
            let rectW = panelRect.w / scaleF
            let rectH = panelRect.h / scaleF
            let zoomScale = worldMapPanel.zoom * worldMapPanel.zoom
            worldMapPanel.pos = vec2(
              rectW / 2.0'f32 - cx * zoomScale,
              rectH / 2.0'f32 - cy * zoomScale
            )
            worldMapPanel.vel = vec2(0, 0)
          else:
            # Single tap: select the group
            selection = alive
            if alive.len > 0:
              selectedPos = alive[0].pos

          lastGroupKeyTime[i] = groupNow
          lastGroupKeyIndex = i

  # Escape key: cancel building placement mode, rally point mode, or close build menu
  if window.buttonPressed[KeyEscape]:
    if buildingPlacementMode:
      buildingPlacementMode = false
    elif rallyPointMode:
      rallyPointMode = false
    elif buildMenuOpen:
      buildMenuOpen = false

  # Command panel hotkeys (when not in building placement mode or rally point mode)
  if not buildingPlacementMode and not rallyPointMode and selection.len > 0 and playerTeam >= 0:
    # Check if a production building is selected (for rally point hotkey)
    let isBuildingSelected = selection.len == 1 and isBuildingKind(selection[0].kind) and
                             selection[0].teamId == playerTeam and
                             (buildingHasTrain(selection[0].kind) or selection[0].kind == TownCenter)
    if isBuildingSelected:
      # Building hotkeys
      if window.buttonPressed[KeyG]:
        rallyPointMode = true

    let isVillagerSelected = selection.len == 1 and selection[0].kind == Agent and
                             selection[0].unitClass == UnitVillager
    if isVillagerSelected:
      if buildMenuOpen:
        # Build submenu hotkeys
        if window.buttonPressed[KeyQ]:
          buildingPlacementMode = true
          buildingPlacementKind = House
        elif window.buttonPressed[KeyW]:
          buildingPlacementMode = true
          buildingPlacementKind = Mill
        elif window.buttonPressed[KeyE]:
          buildingPlacementMode = true
          buildingPlacementKind = LumberCamp
        elif window.buttonPressed[KeyR]:
          buildingPlacementMode = true
          buildingPlacementKind = MiningCamp
        elif window.buttonPressed[KeyA]:
          buildingPlacementMode = true
          buildingPlacementKind = Barracks
        elif window.buttonPressed[KeyS]:
          buildingPlacementMode = true
          buildingPlacementKind = ArcheryRange
        elif window.buttonPressed[KeyD]:
          buildingPlacementMode = true
          buildingPlacementKind = Stable
        elif window.buttonPressed[KeyF]:
          buildingPlacementMode = true
          buildingPlacementKind = Wall
        elif window.buttonPressed[KeyZ]:
          buildingPlacementMode = true
          buildingPlacementKind = Blacksmith
        elif window.buttonPressed[KeyX]:
          buildingPlacementMode = true
          buildingPlacementKind = Market
      else:
        # Main command hotkeys for villager
        if window.buttonPressed[KeyB]:
          buildMenuOpen = true
        elif window.buttonPressed[KeyS]:
          for sel in selection:
            if not isNil(sel) and sel.kind == Agent:
              stopAgent(sel.agentId)
    else:
      # Non-villager unit hotkeys
      if window.buttonPressed[KeyS]:
        for sel in selection:
          if not isNil(sel) and sel.kind == Agent:
            stopAgent(sel.agentId)
      elif window.buttonPressed[KeyH]:
        for sel in selection:
          if not isNil(sel) and sel.kind == Agent:
            setAgentHoldPosition(sel.agentId, sel.pos)
      # Formation hotkeys (L=Line, O=Box, T=Staggered)
      elif window.buttonPressed[KeyL] or window.buttonPressed[KeyO] or window.buttonPressed[KeyT]:
        var targetGroup = -1
        if selection.len > 0 and not isNil(selection[0]) and selection[0].kind == Agent:
          targetGroup = findAgentControlGroup(selection[0].agentId)
        if targetGroup < 0 and selection.len > 1:
          # No existing group - assign selection to first empty group
          for g in 0 ..< ControlGroupCount:
            if controlGroups[g].len == 0:
              controlGroups[g] = selection
              targetGroup = g
              break
          if targetGroup < 0:
            controlGroups[0] = selection
            targetGroup = 0
        if targetGroup >= 0:
          let ftype = if window.buttonPressed[KeyL]: FormationLine
                      elif window.buttonPressed[KeyO]: FormationBox
                      else: FormationStaggered
          setFormation(targetGroup, ftype)

  # Building placement click handling
  if buildingPlacementMode and window.buttonPressed[MouseLeft] and not blockSelection:
    let mousePos = getTransform().inverse * window.mousePos.vec2
    let gridPos = (mousePos + vec2(0.5, 0.5)).ivec2
    if canPlaceBuildingAt(gridPos) and playerTeam >= 0:
      # Place the building (using a villager if available)
      for sel in selection:
        if not isNil(sel) and sel.kind == Agent and sel.unitClass == UnitVillager:
          # Set the villager to build at this location
          setAgentAttackMoveTarget(sel.agentId, gridPos)
          break
      # Exit placement mode (unless shift is held for multiple placements)
      if not (window.buttonDown[KeyLeftShift] or window.buttonDown[KeyRightShift]):
        buildingPlacementMode = false
        buildMenuOpen = false
    blockSelection = true

  # Rally point mode click handling
  if rallyPointMode and window.buttonPressed[MouseLeft] and not blockSelection:
    let mousePos = getTransform().inverse * window.mousePos.vec2
    let gridPos = (mousePos + vec2(0.5, 0.5)).ivec2
    if gridPos.x >= 0 and gridPos.x < MapWidth and
       gridPos.y >= 0 and gridPos.y < MapHeight:
      # Set rally point for the selected building
      if selection.len == 1 and isBuildingKind(selection[0].kind) and
         selection[0].teamId == playerTeam:
        setBuildingRallyPoint(env, selection[0].pos.x, selection[0].pos.y, gridPos.x, gridPos.y)
      rallyPointMode = false
    blockSelection = true

  if selection.len > 0 and selection[0].kind == Agent:
    let agent = selection[0]

    template overrideAndStep(action: uint16) =
      actionsArray = getActions(env)
      for sel in selection:
        if not isNil(sel) and sel.kind == Agent:
          actionsArray[sel.agentId] = action
      env.step(addr actionsArray)

    if window.buttonPressed[KeyW] or window.buttonPressed[KeyUp]:
      overrideAndStep(encodeAction(1'u16, Orientation.N.uint16))
    elif window.buttonPressed[KeyS] or window.buttonPressed[KeyDown]:
      overrideAndStep(encodeAction(1'u16, Orientation.S.uint16))
    elif window.buttonPressed[KeyD] or window.buttonPressed[KeyRight]:
      overrideAndStep(encodeAction(1'u16, Orientation.E.uint16))
    elif window.buttonPressed[KeyA] or window.buttonPressed[KeyLeft]:
      overrideAndStep(encodeAction(1'u16, Orientation.W.uint16))
    elif window.buttonPressed[KeyQ]:
      overrideAndStep(encodeAction(1'u16, Orientation.NW.uint16))
    elif window.buttonPressed[KeyE]:
      overrideAndStep(encodeAction(1'u16, Orientation.NE.uint16))
    elif window.buttonPressed[KeyZ]:
      overrideAndStep(encodeAction(1'u16, Orientation.SW.uint16))
    elif window.buttonPressed[KeyC]:
      overrideAndStep(encodeAction(1'u16, Orientation.SE.uint16))

    if window.buttonPressed[KeyU]:
      let useDir = agent.orientation.uint16
      overrideAndStep(encodeAction(3'u16, useDir))
  else:
    # Camera panning with WASD/arrow keys (when no agent selected)
    # Uses acceleration + velocity decay for smooth movement
    var panAccel = vec2(0, 0)
    if window.buttonDown[KeyW] or window.buttonDown[KeyUp]:
      panAccel.y += CameraPanAccel
    if window.buttonDown[KeyS] or window.buttonDown[KeyDown]:
      panAccel.y -= CameraPanAccel
    if window.buttonDown[KeyA] or window.buttonDown[KeyLeft]:
      panAccel.x += CameraPanAccel
    if window.buttonDown[KeyD] or window.buttonDown[KeyRight]:
      panAccel.x -= CameraPanAccel
    # Apply acceleration and clamp speed
    worldMapPanel.vel = worldMapPanel.vel + panAccel
    let speed = sqrt(worldMapPanel.vel.x * worldMapPanel.vel.x +
                     worldMapPanel.vel.y * worldMapPanel.vel.y)
    if speed > CameraPanMaxSpeed:
      worldMapPanel.vel = worldMapPanel.vel * (CameraPanMaxSpeed / speed)

  # Apply velocity to position and decay
  if abs(worldMapPanel.vel.x) > CameraSnapThreshold or
     abs(worldMapPanel.vel.y) > CameraSnapThreshold:
    worldMapPanel.pos += worldMapPanel.vel
    worldMapPanel.vel = worldMapPanel.vel * VelocityDecayRate
  else:
    worldMapPanel.vel = vec2(0, 0)

  when defined(renderTiming):
    # Capture interaction phase timing (world selection, mouse handling)
    if timingActive:
      let tNow = getMonoTime()
      tInteractionMs = msBetween(tPhaseStart, tNow)
      tPhaseStart = tNow

    # Render phase timing variables
    var tNow: MonoTime
    var tStart: MonoTime
    var tRenderStart: MonoTime
    var tFloorMs: float64
    var tTerrainMs: float64
    var tWallsMs: float64
    var tObjectsMs: float64
    # Decoration breakdown (previously combined into tDecorMs)
    var tAgentDecorMs: float64
    var tProjectilesMs: float64
    var tDamageNumsMs: float64
    var tRagdollsMs: float64
    var tDebrisMs: float64
    var tDustMs: float64
    var tTrailsMs: float64
    # Effects breakdown (previously combined into tSpawnMs)
    var tRipplesMs: float64
    var tImpactsMs: float64
    var tConversionMs: float64
    var tSpawnMs: float64
    var tTradeMs: float64
    var tWeatherMs: float64
    var tVisualMs: float64
    var tGridMs: float64
    var tFogMs: float64
    # Selection breakdown
    var tSelectionMs: float64
    var tRallyMs: float64
    var tGhostMs: float64
    # UI breakdown (previously combined into tUiMs)
    var tResourceBarMs: float64
    var tMinimapMs: float64
    var tFooterMs: float64
    var tInfoPanelMs: float64
    var tCommandPanelMs: float64
    var tTooltipMs: float64
    var tLabelsMs: float64
    var tUiMs: float64
    var tMaskMs: float64
    var tEndFrameMs: float64
    var tSwapMs: float64
    if timingActive:
      tRenderStart = getMonoTime()
      tStart = tRenderStart

  drawFloor()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tFloorMs = msBetween(tStart, tNow)
      tStart = tNow

  drawTerrain()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tTerrainMs = msBetween(tStart, tNow)
      tStart = tNow

  drawWalls()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tWallsMs = msBetween(tStart, tNow)
      tStart = tNow

  drawObjects()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tObjectsMs = msBetween(tStart, tNow)
      tStart = tNow

  drawAgentDecorations()
  if settings.showUnitDebug:
    drawUnitDebugOverlay()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tAgentDecorMs = msBetween(tStart, tNow)
      tStart = tNow

  drawProjectiles()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tProjectilesMs = msBetween(tStart, tNow)
      tStart = tNow

  drawDamageNumbers()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tDamageNumsMs = msBetween(tStart, tNow)
      tStart = tNow

  drawRagdolls()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tRagdollsMs = msBetween(tStart, tNow)
      tStart = tNow

  drawDebris()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tDebrisMs = msBetween(tStart, tNow)
      tStart = tNow

  drawConstructionDust()
  drawGatherSparkles()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tDustMs = msBetween(tStart, tNow)
      tStart = tNow

  drawUnitTrails()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tTrailsMs = msBetween(tStart, tNow)
      tStart = tNow

  drawDustParticles()

  drawWaterRipples()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tRipplesMs = msBetween(tStart, tNow)
      tStart = tNow

  drawAttackImpacts()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tImpactsMs = msBetween(tStart, tNow)
      tStart = tNow

  drawConversionEffects()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tConversionMs = msBetween(tStart, tNow)
      tStart = tNow

  drawSpawnEffects()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tSpawnMs = msBetween(tStart, tNow)
      tStart = tNow

  drawTradeRoutes()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tTradeMs = msBetween(tStart, tNow)
      tStart = tNow

  drawWeatherEffects()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tWeatherMs = msBetween(tStart, tNow)
      tStart = tNow

  if settings.showVisualRange:
    drawVisualRanges()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tVisualMs = msBetween(tStart, tNow)
      tStart = tNow

  if settings.showGrid:
    drawGrid()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tGridMs = msBetween(tStart, tNow)
      tStart = tNow

  if settings.showFogOfWar:
    drawVisualRanges(alpha = 1.0)
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tFogMs = msBetween(tStart, tNow)
      tStart = tNow

  drawSelection()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tSelectionMs = msBetween(tStart, tNow)
      tStart = tNow

  drawRallyPoints()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tRallyMs = msBetween(tStart, tNow)
      tStart = tNow

  # Draw building ghost preview if in placement mode
  if buildingPlacementMode:
    let mousePos = getTransform().inverse * window.mousePos.vec2
    drawBuildingGhost(mousePos)

  # Draw rally point preview if in rally point mode
  if rallyPointMode and selection.len == 1 and isBuildingKind(selection[0].kind):
    let mousePos = getTransform().inverse * window.mousePos.vec2
    let buildingPos = selection[0].pos.vec2
    drawRallyPointPreview(buildingPos, mousePos)

  # Draw drag-box selection rectangle
  if isDragging and window.buttonDown[MouseLeft]:
    let dragEndWorld = getTransform().inverse * window.mousePos.vec2
    let minX = min(dragStartWorld.x, dragEndWorld.x)
    let maxX = max(dragStartWorld.x, dragEndWorld.x)
    let minY = min(dragStartWorld.y, dragEndWorld.y)
    let maxY = max(dragStartWorld.y, dragEndWorld.y)
    let lineWidth = SelectionBoxLineWidth
    let dragColor = color(SelectionBoxColorR, SelectionBoxColorG, SelectionBoxColorB, SelectionBoxAlpha)
    # Top edge
    bxy.drawRect(Rect(x: minX, y: minY, w: maxX - minX, h: lineWidth), dragColor)
    # Bottom edge
    bxy.drawRect(Rect(x: minX, y: maxY - lineWidth, w: maxX - minX, h: lineWidth), dragColor)
    # Left edge
    bxy.drawRect(Rect(x: minX, y: minY, w: lineWidth, h: maxY - minY), dragColor)
    # Right edge
    bxy.drawRect(Rect(x: maxX - lineWidth, y: minY, w: lineWidth, h: maxY - minY), dragColor)

  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tGhostMs = msBetween(tStart, tNow)
      tStart = tNow

  bxy.restoreTransform()
  restoreTransform()

  bxy.restoreTransform()
  restoreTransform()
  # Draw UI elements
  drawResourceBar(panelRectInt, playerTeam)
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tResourceBarMs = msBetween(tStart, tNow)
      tStart = tNow

  let footerButtons = buildFooterButtons(panelRectInt)
  drawMinimap(panelRectInt, worldMapPanel)
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tMinimapMs = msBetween(tStart, tNow)
      tStart = tNow

  drawFooter(panelRectInt, footerButtons)
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tFooterMs = msBetween(tStart, tNow)
      tStart = tNow

  drawUnitInfoPanel(panelRectInt)
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tInfoPanelMs = msBetween(tStart, tNow)
      tStart = tNow

  drawCommandPanel(panelRectInt, mousePosPx)
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tCommandPanelMs = msBetween(tStart, tNow)
      tStart = tNow

  # Update and draw tooltips (after command panel so tooltip appears on top)
  updateTooltip()
  drawTooltip(vec2(panelRectInt.w.float32, panelRectInt.h.float32))
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tTooltipMs = msBetween(tStart, tNow)
      tStart = tNow

  drawSelectionLabel(panelRectInt)
  drawStepLabel(panelRectInt)
  drawControlModeLabel(panelRectInt)
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tLabelsMs = msBetween(tStart, tNow)
      tStart = tNow

  if clearUiCapture:
    uiMouseCaptured = false
  when defined(renderTiming):
    if timingActive:
      # Compute combined UI time for backwards compatibility
      tUiMs = tResourceBarMs + tMinimapMs + tFooterMs + tInfoPanelMs +
              tCommandPanelMs + tTooltipMs + tLabelsMs
  bxy.pushLayer()
  bxy.drawRect(rect = panelRect, color = color(1, 0, 0, 1.0))
  bxy.popLayer(blendMode = MaskBlend)
  bxy.popLayer()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tMaskMs = msBetween(tStart, tNow)
      tStart = tNow

  bxy.endFrame()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tEndFrameMs = msBetween(tStart, tNow)
      tStart = tNow
  window.swapBuffers()
  when defined(renderTiming):
    if timingActive:
      tNow = getMonoTime()
      tSwapMs = msBetween(tStart, tNow)
      let shouldLog = (frame - renderTimingStart) mod renderTimingEvery == 0
      if shouldLog:
        let totalMs = msBetween(tFrameStart, tNow)
        let renderMs = msBetween(tRenderStart, tNow)
        # Sum decoration timings for backwards-compatible decor_ms
        let tDecorMs = tAgentDecorMs + tProjectilesMs + tDamageNumsMs +
          tRagdollsMs + tDebrisMs + tDustMs + tTrailsMs +
          tRipplesMs + tImpactsMs + tConversionMs + tSpawnMs +
          tTradeMs + tWeatherMs
        # Sum effects timings for backwards-compatible spawn_combined_ms
        let tEffectsMs = tRipplesMs + tImpactsMs + tConversionMs + tSpawnMs
        # Sum selection timings for backwards-compatible selection_combined_ms
        let tSelectionCombinedMs = tSelectionMs + tRallyMs + tGhostMs
        echo "frame=", frame,
          " total_ms=", totalMs,
          # Early frame phases
          " input_ms=", tInputMs,
          " sim_ms=", tSimMs,
          " beginframe_ms=", tBeginFrameMs,
          " setup_ms=", tSetupMs,
          " interaction_ms=", tInteractionMs,
          # Render phases
          " render_ms=", renderMs,
          " floor_ms=", tFloorMs,
          " terrain_ms=", tTerrainMs,
          " walls_ms=", tWallsMs,
          " objects_ms=", tObjectsMs,
          # Decoration breakdown (and combined for compatibility)
          " decor_ms=", tDecorMs,
          " agentdecor_ms=", tAgentDecorMs,
          " projectiles_ms=", tProjectilesMs,
          " damagenums_ms=", tDamageNumsMs,
          " ragdolls_ms=", tRagdollsMs,
          " debris_ms=", tDebrisMs,
          " dust_ms=", tDustMs,
          " trails_ms=", tTrailsMs,
          # Effects breakdown (previously grouped into spawn_ms)
          " effects_ms=", tEffectsMs,
          " ripples_ms=", tRipplesMs,
          " impacts_ms=", tImpactsMs,
          " conversion_ms=", tConversionMs,
          " spawn_ms=", tSpawnMs,
          " trade_ms=", tTradeMs,
          " weather_ms=", tWeatherMs,
          # Other render phases
          " visual_ms=", tVisualMs,
          " grid_ms=", tGridMs,
          " fog_ms=", tFogMs,
          # Selection breakdown
          " selection_combined_ms=", tSelectionCombinedMs,
          " selection_ms=", tSelectionMs,
          " rally_ms=", tRallyMs,
          " ghost_ms=", tGhostMs,
          # UI breakdown
          " ui_ms=", tUiMs,
          " resourcebar_ms=", tResourceBarMs,
          " minimap_ms=", tMinimapMs,
          " footer_ms=", tFooterMs,
          " infopanel_ms=", tInfoPanelMs,
          " commandpanel_ms=", tCommandPanelMs,
          " tooltip_ms=", tTooltipMs,
          " labels_ms=", tLabelsMs,
          # Final phases
          " mask_ms=", tMaskMs,
          " end_ms=", tEndFrameMs,
          " swap_ms=", tSwapMs,
          " things=", env.things.len,
          " agents=", env.agents.len,
          " tumors=", env.thingsByKind[Tumor].len
  # Output semantic capture if enabled
  if semanticEnabled:
    let semanticOutput = endSemanticFrame(frame)
    if semanticOutput.len > 0:
      echo semanticOutput

  inc frame
  when defined(renderTiming):
    if renderTimingExit >= 0 and frame >= renderTimingExit:
      quit(QuitSuccess)


# Build any missing DF tileset sprites before loading assets.
generateDfViewAssets()

# Build the atlas with progress feedback and error handling.
echo "🎨 Loading tribal assets..."
var loadedCount = 0
var skippedCount = 0
var filteredCount = 0
var totalBytes = 0

for path in walkDirRec("data/"):
  if not path.endsWith(".png"):
    continue
  if not shouldPreloadGuiAsset(path):
    inc filteredCount
    continue
  try:
    let key = guiAssetKey(path)
    let image = readImage(path)
    bxy.addImage(key, image)
    inc loadedCount
    totalBytes += getFileSize(path).int
  except Exception as e:
    echo "⚠️  Skipping ", path, ": ", e.msg
    inc skippedCount

echo "✅ Loaded ", loadedCount, " assets (", totalBytes div 1024 div 1024, " MB)"
if filteredCount > 0:
  echo "🧹 Filtered ", filteredCount, " non-game assets from GUI preload"
if skippedCount > 0:
  echo "⚠️  Skipped ", skippedCount, " files due to errors"

# Check for command line arguments to determine controller type and features
var useExternalController = false
for i in 1..paramCount():
  let param = paramStr(i)
  if param == "--external-controller":
    useExternalController = true
    # Command line: Requested external controller mode
  elif param == "--semantic":
    enableSemanticCapture()
    echo "Semantic capture enabled - will output UI hierarchy each frame"

# Decide controller source.
# Priority: explicit CLI flag --> env vars --> fallback to built-in AI.
let envExternal = existsEnv("TRIBAL_PYTHON_CONTROL") or existsEnv("TRIBAL_EXTERNAL_CONTROL")

if useExternalController:
  initGlobalController(ExternalNN)
elif envExternal:
  initGlobalController(ExternalNN)
elif globalController != nil:
  discard  # keep existing
else:
  initGlobalController(BuiltinAI)

# Check if external controller is active and start playing if so
if globalController != nil and globalController.controllerType == ExternalNN:
  play = true
  lastSimTime = nowSeconds()

# Initialize audio system if enabled
when defined(audio):
  echo "🔊 Initializing audio system..."
  initAudio()

when defined(emscripten):
  proc main() {.cdecl.} =
    display()
    when defined(audio):
      updateAudio()
    pollEvents()
  window.run(main)
else:
  while not window.closeRequested:
    display()
    when defined(audio):
      updateAudio()
    pollEvents()
