## Minimap rendering and minimap coordinate helpers.

import
  boxy, chroma, pixie, vmath, windy,
  common, constants, environment, semantic

const
  MinimapImageKey = "minimap_image"
  MinimapWater = rgbx(25, 50, 120, 255)
  MinimapShallowWater = rgbx(60, 110, 160, 255)
  MinimapBridge = rgbx(140, 110, 70, 255)
  MinimapFertile = rgbx(50, 100, 30, 255)
  MinimapRoad = rgbx(140, 130, 110, 255)
  MinimapGrass = rgbx(60, 120, 40, 255)
  MinimapDune = rgbx(190, 170, 100, 255)
  MinimapSand = rgbx(180, 160, 90, 255)
  MinimapSnow = rgbx(220, 230, 240, 255)
  MinimapMud = rgbx(90, 70, 50, 255)
  MinimapMountain = rgbx(80, 75, 70, 255)
  MinimapRamp = rgbx(130, 120, 100, 255)
  MinimapEmpty = rgbx(50, 80, 40, 255)

var
  minimapCacheGeneration = -1
  minimapCacheStep = -1
  minimapFullRebuildCounter = 0
  minimapBaseImage: Image

proc terrainColor(terrain: TerrainType): ColorRGBX =
  ## Return the minimap color for a terrain tile.
  case terrain
  of Water:
    MinimapWater
  of ShallowWater:
    MinimapShallowWater
  of Bridge:
    MinimapBridge
  of Fertile:
    MinimapFertile
  of Road:
    MinimapRoad
  of Grass:
    MinimapGrass
  of Dune:
    MinimapDune
  of Sand:
    MinimapSand
  of Snow:
    MinimapSnow
  of Mud:
    MinimapMud
  of Mountain:
    MinimapMountain
  of RampUpN, RampUpS, RampUpW, RampUpE,
     RampDownN, RampDownS, RampDownW, RampDownE:
    MinimapRamp
  of Empty:
    MinimapEmpty

proc rebuildMinimapBase() =
  ## Rebuild the cached terrain-only minimap image.
  let
    minimapW = MinimapSize
    minimapH = MinimapSize
    scaleX = MapWidth.float32 / minimapW.float32
    scaleY = MapHeight.float32 / minimapH.float32
  minimapBaseImage = newImage(minimapW, minimapH)
  for py in 0 ..< minimapH:
    for px in 0 ..< minimapW:
      let
        tileX = clamp(int(px.float32 * scaleX), 0, MapWidth - 1)
        tileY = clamp(int(py.float32 * scaleY), 0, MapHeight - 1)
      minimapBaseImage.unsafe[px, py] = terrainColor(env.terrain[tileX][tileY])
  minimapCacheGeneration = env.mapGeneration

proc minimapRect*(panelRect: IRect): Rect =
  ## Return the minimap rectangle within the panel.
  if uiLayout.minimapArea != nil and uiLayout.minimapArea.rect.w > 0:
    return uiLayout.minimapArea.rect

  let
    x = panelRect.x.float32 + MinimapMargin.float32
    y =
      panelRect.y.float32 +
      panelRect.h.float32 -
      FooterHeight.float32 -
      MinimapMargin.float32 -
      MinimapSize.float32
  Rect(x: x, y: y, w: MinimapSize.float32, h: MinimapSize.float32)

proc isInMinimap*(panelRect: IRect, mousePosPx: Vec2): bool =
  ## Return true when a mouse position is inside the minimap.
  let rect = minimapRect(panelRect)
  mousePosPx.x >= rect.x and
    mousePosPx.x <= rect.x + rect.w and
    mousePosPx.y >= rect.y and
    mousePosPx.y <= rect.y + rect.h

proc minimapToWorld*(panelRect: IRect, mousePosPx: Vec2): Vec2 =
  ## Convert a minimap mouse position to world coordinates.
  let
    rect = minimapRect(panelRect)
    relX = (mousePosPx.x - rect.x) / rect.w
    relY = (mousePosPx.y - rect.y) / rect.h
  vec2(relX * MapWidth.float32, relY * MapHeight.float32)

proc drawMinimap*(panelRect: IRect, cameraPos: Vec2, zoom: float32) =
  ## Draw the minimap overlay and viewport rectangle.
  let
    minimapW = MinimapSize
    minimapH = MinimapSize

  if minimapCacheGeneration != env.mapGeneration:
    rebuildMinimapBase()

  let needsRebuild =
    minimapCacheStep != env.currentStep or
    (minimapFullRebuildCounter mod MinimapRebuildInterval == 0)
  inc minimapFullRebuildCounter

  if needsRebuild:
    minimapCacheStep = env.currentStep
    var image = minimapBaseImage.copy()
    let
      scaleX = MapWidth.float32 / minimapW.float32
      scaleY = MapHeight.float32 / minimapH.float32

    for kind in ThingKind:
      if not isBuildingKind(kind):
        continue
      for thing in env.thingsByKind[kind]:
        if not isValidPos(thing.pos):
          continue
        let
          px = clamp(int(thing.pos.x.float32 / scaleX), 0, minimapW - 1)
          py = clamp(int(thing.pos.y.float32 / scaleY), 0, minimapH - 1)
          color =
            if thing.teamId >= 0 and thing.teamId < env.teamColors.len:
              env.teamColors[thing.teamId]
            else:
              NeutralGrayMinimap
        image.unsafe[px, py] = rgbx(
          uint8(clamp(color.r * 255, 0, 255)),
          uint8(clamp(color.g * 255, 0, 255)),
          uint8(clamp(color.b * 255, 0, 255)),
          255
        )

    for agent in env.agents:
      if not isAgentAlive(env, agent):
        continue
      if not isValidPos(agent.pos):
        continue
      let
        px = clamp(int(agent.pos.x.float32 / scaleX), 0, minimapW - 1)
        py = clamp(int(agent.pos.y.float32 / scaleY), 0, minimapH - 1)
        color = env.agentColors[agent.agentId]
      image.unsafe[px, py] = rgbx(
        uint8(clamp(
          color.r * MinimapBrightnessMult.float32,
          MinimapBrightnessMin.float32,
          255
        )),
        uint8(clamp(
          color.g * MinimapBrightnessMult.float32,
          MinimapBrightnessMin.float32,
          255
        )),
        uint8(clamp(
          color.b * MinimapBrightnessMult.float32,
          MinimapBrightnessMin.float32,
          255
        )),
        255
      )

    for wall in env.thingsByKind[Wall]:
      if not isValidPos(wall.pos):
        continue
      let
        px = clamp(int(wall.pos.x.float32 / scaleX), 0, minimapW - 1)
        py = clamp(int(wall.pos.y.float32 / scaleY), 0, minimapH - 1)
      image.unsafe[px, py] = rgbx(
        MinimapWallGray.uint8,
        MinimapWallGray.uint8,
        MinimapWallGray.uint8,
        255
      )

    bxy.addImage(MinimapImageKey, image)

  let rect = minimapRect(panelRect)
  let
    borderPos = vec2(
      rect.x - MinimapBorderWidth,
      rect.y - MinimapBorderWidth
    )
    borderSize = vec2(
      rect.w + MinimapBorderExpand,
      rect.h + MinimapBorderExpand
    )
  bxy.drawRect(
    rect = Rect(
      x: borderPos.x,
      y: borderPos.y,
      w: borderSize.x,
      h: borderSize.y
    ),
    color = UiMinimapBorderDark
  )
  bxy.drawImage(MinimapImageKey, vec2(rect.x, rect.y))

  pushSemanticContext("Minimap")
  capturePanel("Minimap", vec2(rect.x, rect.y), vec2(rect.w, rect.h))

  let
    scaleF = window.contentScale.float32
    rectW = panelRect.w.float32 / scaleF
    rectH = panelRect.h.float32 / scaleF
    zoomScale = zoom * zoom
    cx = (rectW / 2.0'f - cameraPos.x) / zoomScale
    cy = (rectH / 2.0'f - cameraPos.y) / zoomScale
    viewHalfW = rectW / (2.0'f * zoomScale)
    viewHalfH =
      (rectH - FooterHeight.float32 / scaleF) / (2.0'f * zoomScale)
    minimapScaleX = rect.w / MapWidth.float32
    minimapScaleY = rect.h / MapHeight.float32
    vpLeft = rect.x + (cx - viewHalfW) * minimapScaleX
    vpTop = rect.y + (cy - viewHalfH) * minimapScaleY
    vpW = viewHalfW * 2.0'f * minimapScaleX
    vpH = viewHalfH * 2.0'f * minimapScaleY
    clampedLeft = max(vpLeft, rect.x)
    clampedTop = max(vpTop, rect.y)
    clampedRight = min(vpLeft + vpW, rect.x + rect.w)
    clampedBottom = min(vpTop + vpH, rect.y + rect.h)

  if clampedRight > clampedLeft and clampedBottom > clampedTop:
    let
      lineW = MinimapViewportLineWidth
      viewportColor = withAlpha(UiViewportOutline, MinimapViewportAlpha)
    bxy.drawRect(
      rect = Rect(
        x: clampedLeft,
        y: clampedTop,
        w: clampedRight - clampedLeft,
        h: lineW
      ),
      color = viewportColor
    )
    bxy.drawRect(
      rect = Rect(
        x: clampedLeft,
        y: clampedBottom - lineW,
        w: clampedRight - clampedLeft,
        h: lineW
      ),
      color = viewportColor
    )
    bxy.drawRect(
      rect = Rect(
        x: clampedLeft,
        y: clampedTop,
        w: lineW,
        h: clampedBottom - clampedTop
      ),
      color = viewportColor
    )
    bxy.drawRect(
      rect = Rect(
        x: clampedRight - lineW,
        y: clampedTop,
        w: lineW,
        h: clampedBottom - clampedTop
      ),
      color = viewportColor
    )

  popSemanticContext()
