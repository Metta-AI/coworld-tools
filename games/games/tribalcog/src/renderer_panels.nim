## Resource bar, unit info panel, and minimap rendering helpers.

import
  boxy, bumpy, pixie, vmath,
  common, environment, label_cache, renderer_core

const
  MinimapPadding = MinimapPanelPadding
  MinimapUpdateInterval = MinimapUpdateFrameInterval
  MinimapBorderWidth = MinimapPanelBorderWidth
  MinimapImageKey = "minimap_composite"
  MinimapBuildingKinds = [
    TownCenter, House, Mill, LumberCamp, MiningCamp, Market,
    Blacksmith, Barracks, ArcheryRange, Stable, SiegeWorkshop,
    Castle, Monastery, GuardTower, Door
  ]

let
  minimapScaleX = MinimapSize.float32 / MapWidth.float32
  minimapScaleY = MinimapSize.float32 / MapHeight.float32
  minimapInvScaleX = MapWidth.float32 / MinimapSize.float32
  minimapInvScaleY = MapHeight.float32 / MinimapSize.float32

var
  minimapTerrainImage: Image
  minimapTerrainGeneration = -1
  minimapCompositeImage: Image
  minimapLastUnitFrame = -1
  minimapTeamColors: array[MapRoomObjectsTeams, ColorRGBX]
  minimapTeamBrightColors: array[MapRoomObjectsTeams, ColorRGBX]
  minimapTeamColorsInitialized = false

proc getUnitInfoLabel(
  text: string,
  fontSize: float32 = UnitInfoFontSize.float32
): (string, IVec2) =
  ## Return a cached unit info label image key and size.
  let style = labelStyle(
    InfoLabelFontPath,
    fontSize,
    UnitInfoLabelPadding,
    UnitInfoLabelLineSpacing
  )
  let cached = ensureLabel("unit_info", text, style)
  (cached.imageKey, cached.size)

proc drawUnitInfoPanel*(panelRect: IRect) =
  ## Draw the selected unit or building info panel.
  if selection.len == 0:
    return

  let selected = selection[0]
  if selected.isNil:
    return

  let
    panelW = UnitInfoPanelW
    panelH = UnitInfoPanelH
    panelX =
      panelRect.x.float32 +
      panelRect.w.float32 -
      panelW -
      MinimapPadding
    panelY =
      panelRect.y.float32 +
      panelRect.h.float32 -
      panelH -
      MinimapPadding -
      FooterHeight.float32

  bxy.drawRect(
    rect = Rect(
      x: panelX - 1.0'f,
      y: panelY - 1.0'f,
      w: panelW + 2.0'f,
      h: panelH + 2.0'f
    ),
    color = UiBorder
  )
  bxy.drawRect(
    rect = Rect(x: panelX, y: panelY, w: panelW, h: panelH),
    color = UiBgPanel
  )

  var yOffset = UnitInfoPanelPadding
  let xPadding = UnitInfoPanelPadding

  let name =
    if selected.kind == Agent:
      UnitClassLabels[selected.unitClass]
    elif isBuildingKind(selected.kind):
      BuildingRegistry[selected.kind].displayName
    else:
      $selected.kind
  let (nameKey, nameSize) = getUnitInfoLabel(name, UnitInfoNameFontSize)
  drawUiImageScaled(
    nameKey,
    vec2(panelX + xPadding, panelY + yOffset),
    vec2(nameSize.x.float32, nameSize.y.float32)
  )
  yOffset += nameSize.y.float32 + UnitInfoLineSpacingLarge

  if selected.maxHp > 0:
    let hpText = "HP: " & $selected.hp & "/" & $selected.maxHp
    let (hpKey, hpSize) = getUnitInfoLabel(hpText)
    drawUiImageScaled(
      hpKey,
      vec2(panelX + xPadding, panelY + yOffset),
      vec2(hpSize.x.float32, hpSize.y.float32)
    )
    yOffset += hpSize.y.float32 + UnitInfoLineSpacingSmall

    let
      hpBarW = panelW - xPadding * 2
      hpBarH = 4.0'f
      hpRatio = selected.hp.float32 / selected.maxHp.float32
      hpBarColor = getHealthBarColor(hpRatio)
    bxy.drawRect(
      rect = Rect(
        x: panelX + xPadding,
        y: panelY + yOffset,
        w: hpBarW,
        h: hpBarH
      ),
      color = UiHealthBg
    )
    bxy.drawRect(
      rect = Rect(
        x: panelX + xPadding,
        y: panelY + yOffset,
        w: hpBarW * hpRatio,
        h: hpBarH
      ),
      color = hpBarColor
    )
    yOffset += hpBarH + UnitInfoLineSpacingLarge

  if selected.kind == Agent:
    let atkText =
      "Atk: " &
      $selected.attackDamage &
      "  Rng: " &
      $getUnitAttackRange(selected)
    let (atkKey, atkSize) = getUnitInfoLabel(atkText)
    drawUiImageScaled(
      atkKey,
      vec2(panelX + xPadding, panelY + yOffset),
      vec2(atkSize.x.float32, atkSize.y.float32)
    )
    yOffset += atkSize.y.float32 + UnitInfoLineSpacingSmall

  let teamText = "Team: " & $selected.teamId
  let (teamKey, teamSize) = getUnitInfoLabel(teamText)
  drawUiImageScaled(
    teamKey,
    vec2(panelX + xPadding, panelY + yOffset),
    vec2(teamSize.x.float32, teamSize.y.float32)
  )
  yOffset += teamSize.y.float32 + UnitInfoLineSpacingSmall

  let posText = "Pos: " & $selected.pos.x & ", " & $selected.pos.y
  let (posKey, posSize) = getUnitInfoLabel(posText)
  drawUiImageScaled(
    posKey,
    vec2(panelX + xPadding, panelY + yOffset),
    vec2(posSize.x.float32, posSize.y.float32)
  )

proc drawResourceBar*(panelRect: IRect, teamId: int) =
  ## Draw the top resource bar for one team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return

  let
    barY = panelRect.y.float32
    barH = ResourceBarHeight.float32
    barX = panelRect.x.float32
  bxy.drawRect(
    rect = Rect(x: barX, y: barY, w: panelRect.w.float32, h: barH),
    color = UiBgBar
  )

  let stockpile = env.teamStockpiles[teamId]
  var xOffset = ResourceBarXStart

  for res in [
    ResourceFood,
    ResourceWood,
    ResourceStone,
    ResourceGold,
    ResourceWater
  ]:
    let icon = stockpileResourceIcon(res)
    if icon.len > 0 and icon in bxy:
      let
        iconBaseSize = bxy.getImageSize(icon)
        fitScale =
          min(
            ResourceBarIconMaxSize / iconBaseSize.x.float32,
            ResourceBarIconMaxSize / iconBaseSize.y.float32
          ) * resourceUiIconScale(res)
        iconSize =
          vec2(iconBaseSize.x.float32, iconBaseSize.y.float32) * fitScale
        iconX = barX + xOffset + (ResourceBarIconSlotW - iconSize.x) * 0.5'f
        iconY = barY + (barH - iconSize.y) * 0.5'f
      drawUiImageScaled(icon, vec2(iconX, iconY), iconSize)
      xOffset += ResourceBarIconSlotW + ResourceBarIconGap

      let
        count = stockpile.counts[res]
        labelCached = ensureLabel("res_bar", $count, resourceBarLabelStyle)
        labelKey = labelCached.imageKey
        labelSize = labelCached.size
        labelY = barY + (barH - labelSize.y.float32) / 2.0'f
      drawUiImageScaled(
        labelKey,
        vec2(barX + xOffset, labelY),
        vec2(labelSize.x.float32, labelSize.y.float32)
      )
      xOffset += labelSize.x.float32 + ResourceBarItemSpacing

  xOffset += ResourceBarItemSpacing
  bxy.drawRect(
    rect = Rect(
      x: barX + xOffset,
      y: barY + 4.0'f,
      w: 1.0'f,
      h: barH - 8.0'f
    ),
    color = UiBorder
  )
  xOffset += ResourceBarItemSpacing

  let
    popCount = env.stepTeamPopCounts[teamId]
    popCap = env.stepTeamPopCaps[teamId]
    popText = $popCount & "/" & $popCap
    popTextColor =
      if popCap > 0 and popCount >= popCap:
        UiDanger
      else:
        UiFgText
    popStyle = labelStyle(
      FooterFontPath,
      FooterFontSize,
      ResourceBarLabelPadding,
      0.0,
      popTextColor
    )
    popCached = ensureLabel("res_bar_pop", popText, popStyle)
    popLabelY = barY + (barH - popCached.size.y.float32) / 2.0'f
  drawUiImageScaled(
    popCached.imageKey,
    vec2(barX + xOffset, popLabelY),
    vec2(popCached.size.x.float32, popCached.size.y.float32)
  )

proc toMinimapColor(terrain: TerrainType, biome: BiomeType): ColorRGBX =
  ## Map terrain and biome state to a minimap pixel color.
  case terrain
  of Water:
    MinimapPanelWater
  of ShallowWater:
    MinimapPanelShallowWater
  of Bridge:
    MinimapPanelBridge
  of Road:
    MinimapPanelRoad
  of Snow:
    MinimapPanelSnow
  of Dune, Sand:
    MinimapPanelSandy
  of Mud:
    MinimapPanelMud
  of Mountain:
    MinimapPanelMountain
  else:
    let tileColor =
      case biome
      of BiomeForestType:
        BiomeColorForest
      of BiomeDesertType:
        BiomeColorDesert
      of BiomeCavesType:
        BiomeColorCaves
      of BiomeCityType:
        BiomeColorCity
      of BiomePlainsType:
        BiomeColorPlains
      of BiomeSwampType:
        BiomeColorSwamp
      of BiomeDungeonType:
        BiomeColorDungeon
      of BiomeSnowType:
        BiomeColorSnow
      else:
        BaseTileColorDefault
    let intensity = min(tileColor.intensity, MinimapIntensityCap)
    rgbx(
      uint8(clamp(tileColor.r * intensity * 255, 0, 255)),
      uint8(clamp(tileColor.g * intensity * 255, 0, 255)),
      uint8(clamp(tileColor.b * intensity * 255, 0, 255)),
      255
    )

proc rebuildMinimapTerrain() =
  ## Rebuild the cached minimap terrain layer.
  if minimapTerrainImage.isNil or
     minimapTerrainImage.width != MinimapSize or
     minimapTerrainImage.height != MinimapSize:
    minimapTerrainImage = newImage(MinimapSize, MinimapSize)

  let
    scaleX = MinimapSize.float32 / MapWidth.float32
    scaleY = MinimapSize.float32 / MapHeight.float32

  for py in 0 ..< MinimapSize:
    for px in 0 ..< MinimapSize:
      let
        mx = clamp(int(px.float32 / scaleX), 0, MapWidth - 1)
        my = clamp(int(py.float32 / scaleY), 0, MapHeight - 1)
        terrain = env.terrain[mx][my]
        biome = env.biomes[mx][my]
        bg = env.backgroundGrid[mx][my]
        pixelColor =
          if bg.isKind(Tree):
            MinimapPanelTree
          else:
            toMinimapColor(terrain, biome)
      minimapTerrainImage.unsafe[px, py] = pixelColor

  minimapTerrainGeneration = env.mapGeneration

proc initMinimapTeamColors() =
  ## Cache minimap team colors for repeated draws.
  for i in 0 ..< MapRoomObjectsTeams:
    let teamColor =
      if i < env.teamColors.len:
        env.teamColors[i]
      else:
        NeutralGray
    minimapTeamColors[i] = colorToRgbx(teamColor)
    minimapTeamBrightColors[i] = colorToRgbx(color(
      min(teamColor.r * MinimapBrightMul + MinimapBrightAdd, 1.0),
      min(teamColor.g * MinimapBrightMul + MinimapBrightAdd, 1.0),
      min(teamColor.b * MinimapBrightMul + MinimapBrightAdd, 1.0),
      1.0
    ))
  minimapTeamColorsInitialized = true

proc rebuildMinimapComposite(fogTeamId: int) =
  ## Rebuild the terrain, unit, building, and fog minimap composite.
  if minimapTerrainGeneration != env.mapGeneration:
    rebuildMinimapTerrain()
  if not minimapTeamColorsInitialized:
    initMinimapTeamColors()

  if minimapCompositeImage.isNil or
     minimapCompositeImage.width != MinimapSize or
     minimapCompositeImage.height != MinimapSize:
    minimapCompositeImage = newImage(MinimapSize, MinimapSize)

  copyMem(
    addr minimapCompositeImage.data[0],
    addr minimapTerrainImage.data[0],
    MinimapSize * MinimapSize * MinimapBytesPerPixel
  )

  let
    scaleX = minimapScaleX
    scaleY = minimapScaleY

  for kind in MinimapBuildingKinds:
    for thing in env.thingsByKind[kind]:
      if not isValidPos(thing.pos):
        continue
      let bright =
        if thing.teamId >= 0 and thing.teamId < MapRoomObjectsTeams:
          minimapTeamBrightColors[thing.teamId]
        else:
          rgbx(
            MinimapNeutralGrayBright.uint8,
            MinimapNeutralGrayBright.uint8,
            MinimapNeutralGrayBright.uint8,
            255
          )
      let
        px = int(thing.pos.x.float32 * scaleX)
        py = int(thing.pos.y.float32 * scaleY)
        fx0 = clamp(px, 0, MinimapSize - 1)
        fx1 = clamp(px + 1, 0, MinimapSize - 1)
        fy0 = clamp(py, 0, MinimapSize - 1)
        fy1 = clamp(py + 1, 0, MinimapSize - 1)
      minimapCompositeImage.unsafe[fx0, fy0] = bright
      minimapCompositeImage.unsafe[fx1, fy0] = bright
      minimapCompositeImage.unsafe[fx0, fy1] = bright
      minimapCompositeImage.unsafe[fx1, fy1] = bright

  for agent in env.agents:
    if not isAgentAlive(env, agent):
      continue
    let dot =
      if getTeamId(agent) >= 0 and getTeamId(agent) < MapRoomObjectsTeams:
        minimapTeamColors[getTeamId(agent)]
      else:
        MinimapPanelUnknownGray
    let
      px = clamp(int(agent.pos.x.float32 * scaleX), 0, MinimapSize - 1)
      py = clamp(int(agent.pos.y.float32 * scaleY), 0, MinimapSize - 1)
    minimapCompositeImage.unsafe[px, py] = dot

  if fogTeamId >= 0 and fogTeamId < MapRoomObjectsTeams:
    let
      invScaleX = minimapInvScaleX
      invScaleY = minimapInvScaleY
    const
      MinimapFogEdgeSmoothFactor = MinimapFogEdgeFactor
      Neighbors = [
        (-1, -1), (0, -1), (1, -1),
        (-1, 0), (1, 0),
        (-1, 1), (0, 1), (1, 1)
      ]
    for py in 0 ..< MinimapSize:
      let my = clamp(int(py.float32 * invScaleY), 0, MapHeight - 1)
      for px in 0 ..< MinimapSize:
        let mx = clamp(int(px.float32 * invScaleX), 0, MapWidth - 1)
        if not fogVisibility[mx][my]:
          var isEdge = false
          for (dx, dy) in Neighbors:
            let
              nx = mx + dx
              ny = my + dy
            if nx >= 0 and nx < MapWidth and ny >= 0 and ny < MapHeight:
              if fogVisibility[nx][ny]:
                isEdge = true
                break
          let
            pixelColor = minimapCompositeImage.unsafe[px, py]
            factor =
              if isEdge:
                MinimapFogEdgeSmoothFactor
              else:
                MinimapFogDarkFactor
          minimapCompositeImage.unsafe[px, py] = rgbx(
            uint8(pixelColor.r.float32 * factor),
            uint8(pixelColor.g.float32 * factor),
            uint8(pixelColor.b.float32 * factor),
            pixelColor.a
          )

  minimapLastUnitFrame = frame

proc drawMinimap*(panelRect: IRect, panel: Panel) =
  ## Draw the minimap panel in the lower-left corner.
  let
    minimapX = panelRect.x.float32 + MinimapPadding
    minimapY =
      panelRect.y.float32 +
      panelRect.h.float32 -
      MinimapSize.float32 -
      MinimapPadding -
      FooterHeight.float32
    fogTeamId =
      if settings.showFogOfWar:
        playerTeam
      else:
        -1
  if frame - minimapLastUnitFrame >= MinimapUpdateInterval or
     minimapTerrainGeneration != env.mapGeneration:
    rebuildMinimapComposite(fogTeamId)
    bxy.addImage(MinimapImageKey, minimapCompositeImage)

  bxy.drawRect(
    rect = Rect(
      x: minimapX - MinimapBorderWidth,
      y: minimapY - MinimapBorderWidth,
      w: MinimapSize.float32 + MinimapBorderWidth * 2,
      h: MinimapSize.float32 + MinimapBorderWidth * 2
    ),
    color = UiMinimapBorder
  )
  drawUiImageScaled(
    MinimapImageKey,
    vec2(minimapX, minimapY),
    vec2(MinimapSize.float32, MinimapSize.float32)
  )

  if currentViewport.valid:
    let
      scaleX = minimapScaleX
      scaleY = minimapScaleY
      vpX = minimapX + currentViewport.minX.float32 * scaleX
      vpY = minimapY + currentViewport.minY.float32 * scaleY
      vpW =
        (currentViewport.maxX - currentViewport.minX + 1).float32 * scaleX
      vpH =
        (currentViewport.maxY - currentViewport.minY + 1).float32 * scaleY
      lineW = MinimapViewportLineW
    bxy.drawRect(
      rect = Rect(x: vpX, y: vpY, w: vpW, h: lineW),
      color = UiViewportOutline
    )
    bxy.drawRect(
      rect = Rect(x: vpX, y: vpY + vpH - lineW, w: vpW, h: lineW),
      color = UiViewportOutline
    )
    bxy.drawRect(
      rect = Rect(x: vpX, y: vpY, w: lineW, h: vpH),
      color = UiViewportOutline
    )
    bxy.drawRect(
      rect = Rect(x: vpX + vpW - lineW, y: vpY, w: lineW, h: vpH),
      color = UiViewportOutline
    )
  discard panel
