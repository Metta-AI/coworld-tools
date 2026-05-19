## Building construction, overlays, and placement preview rendering.

import
  boxy, pixie, vmath,
  common, constants, environment, label_cache, renderer_core
from renderer_effects import drawBuildingSmoke

const
  GarrisonOverlayKinds = {TownCenter, Castle, GuardTower, House}

proc drawOverlayImage(
  imageKey: string,
  pos: Vec2,
  scale: float32,
  tint: Color
) =
  ## Draw an overlay sprite when the cached image is available.
  if imageKey.len == 0 or imageKey notin bxy:
    return

  bxy.drawImage(
    imageKey,
    pos,
    angle = 0,
    scale = scale,
    tint = tint
  )

proc drawOverlayLabel(text: string, pos: Vec2) =
  ## Draw an overlay label when the cached label image is available.
  let imageKey = ensureLabel("overlay", text, overlayLabelStyle).imageKey
  if imageKey.len == 0 or imageKey notin bxy:
    return

  bxy.drawImage(
    imageKey,
    pos,
    angle = 0,
    scale = OverlayLabelScale,
    tint = TintWhite
  )

proc renderBuildingConstruction*(pos: IVec2, constructionRatio: float32) =
  ## Render construction scaffolding for a building under construction.
  let
    scaffoldTint = ScaffoldTint
    scaffoldScale = ScaffoldingPostScale
    offsets = [
      vec2(-ScaffoldPostOffset, -ScaffoldPostOffset),
      vec2(ScaffoldPostOffset, -ScaffoldPostOffset),
      vec2(-ScaffoldPostOffset, ScaffoldPostOffset),
      vec2(ScaffoldPostOffset, ScaffoldPostOffset)
    ]
  for offset in offsets:
    bxy.drawImage(
      "floor",
      pos.vec2 + offset,
      angle = 0,
      scale = scaffoldScale,
      tint = scaffoldTint
    )

  let barTint = ScaffoldBarTint
  for yOff in [-ScaffoldPostOffset, ScaffoldPostOffset]:
    bxy.drawImage(
      "floor",
      pos.vec2 + vec2(0, yOff),
      angle = 0,
      scale = scaffoldScale,
      tint = barTint
    )

  drawSegmentBar(
    pos.vec2,
    vec2(0, ConstructionBarOffsetY),
    constructionRatio,
    ConstructionBarFill,
    BarBgColor
  )

proc renderBuildingUI*(
  thing: Thing,
  pos: IVec2,
  teamPopCounts, teamHouseCounts: array[MapRoomObjectsTeams, int]
) =
  ## Render building overlays for stockpiles, population, and garrisons.
  if thing.productionQueue.entries.len > 0:
    let entry = thing.productionQueue.entries[0]
    if entry.totalSteps > 0 and entry.remainingSteps > 0:
      let ratio = clamp(
        1.0'f - entry.remainingSteps.float32 / entry.totalSteps.float32,
        0.0'f,
        1.0'f
      )
      drawSegmentBar(
        pos.vec2,
        vec2(0, ProductionBarOffsetY),
        ratio,
        ProductionBarFill,
        BarBgColor
      )
      drawBuildingSmoke(pos.vec2, thing.id)

  let res = buildingStockpileRes(thing.kind)
  if res != ResourceNone:
    let teamId = thing.teamId
    if teamId < 0 or teamId >= MapRoomObjectsTeams:
      return

    let
      icon = stockpileResourceIcon(res)
      count = env.teamStockpiles[teamId].counts[res]
      iconPos = pos.vec2 + vec2(BuildingIconOffsetX, BuildingIconOffsetY)
    drawOverlayImage(
      icon,
      iconPos,
      OverlayIconScale * resourceUiIconScale(res),
      withAlpha(
        TintWhite,
        if count > 0:
          1.0
        else:
          ResourceIconDimAlpha
      )
    )
    if count > 0:
      drawOverlayImage(
        ensureHeartCountLabel(count),
        iconPos + vec2(BuildingLabelOffsetX, BuildingLabelOffsetY),
        OverlayLabelScale,
        TintWhite
      )

  if thing.kind == TownCenter:
    let teamId = thing.teamId
    if teamId >= 0 and teamId < MapRoomObjectsTeams:
      let iconPos = pos.vec2 + vec2(BuildingIconOffsetX, BuildingIconOffsetY)
      drawOverlayImage(
        "oriented/gatherer.s",
        iconPos,
        OverlayIconScale,
        TintWhite
      )
      let
        popText =
          "x " & $teamPopCounts[teamId] & "/" &
          $min(MapAgentsPerTeam, teamHouseCounts[teamId] * HousePopCap)
      drawOverlayLabel(
        popText,
        iconPos + vec2(BuildingLabelOffsetX, BuildingLabelOffsetY)
      )

  if thing.kind in GarrisonOverlayKinds:
    let garrisonCount = thing.garrisonedUnits.len
    if garrisonCount > 0:
      let garrisonIconPos =
        pos.vec2 + vec2(BuildingGarrisonOffsetX, BuildingIconOffsetY)
      drawOverlayImage(
        "oriented/fighter.s",
        garrisonIconPos,
        OverlayIconScale,
        TintWhite
      )
      drawOverlayLabel(
        "x" & $garrisonCount,
        garrisonIconPos +
          vec2(BuildingGarrisonLabelOffsetX, BuildingLabelOffsetY)
      )

proc canPlaceBuildingAt*(pos: IVec2): bool =
  ## Return whether a building can be placed at the given position.
  if not isValidPos(pos):
    return false

  let
    terrain = env.terrain[pos.x][pos.y]
    blocking = env.grid[pos.x][pos.y]
    background = env.backgroundGrid[pos.x][pos.y]
  not isWaterTerrain(terrain) and
    blocking.isNil and
    (background.isNil or background.kind notin CliffKinds)

proc drawBuildingGhost*(worldPos: Vec2) =
  ## Draw the current building placement ghost.
  if not buildingPlacementMode:
    return

  let
    gridPos = (worldPos + vec2(GridSnapOffset, GridSnapOffset)).ivec2
    spriteKey = buildingSpriteKey(buildingPlacementKind)
  if spriteKey.len == 0 or spriteKey notin bxy:
    return

  let valid = canPlaceBuildingAt(gridPos)
  buildingPlacementValid = valid

  let tint =
    if valid:
      GhostValidColor
    else:
      GhostInvalidColor
  bxy.drawImage(
    spriteKey,
    gridPos.vec2,
    angle = 0,
    scale = SpriteScale,
    tint = tint
  )
