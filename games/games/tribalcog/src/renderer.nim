## renderer.nim - Main rendering module
##
## This module provides the main rendering functionality for the game.
## It imports and re-exports from focused sub-modules:
##   - renderer_core: Shared types, constants, and helper procs
##   - renderer_effects: Visual effects and particle rendering
##   - renderer_ui: UI overlays and HUD rendering
##
## This module contains the core drawing routines:
##   - drawFloor, drawTerrain, drawWalls, drawObjects
##   - drawGrid, drawVisualRanges, drawAgentDecorations

import
  boxy, pixie, vmath, windy, tables,
  std/[math, os],
  common, constants, environment

# Import and re-export sub-modules
import renderer_core
export renderer_core

import renderer_effects
export renderer_effects

import renderer_ui
export renderer_ui

# ─── Core Drawing Procs ──────────────────────────────────────────────────────

proc drawFloor*() =
  if renderCacheGeneration != env.mapGeneration:
    rebuildRenderCaches()
  # Ensure tint colors are computed (lazy evaluation from step)
  env.ensureTintColors()
  # Draw the floor tiles everywhere first as the base layer
  # Use viewport culling to skip off-screen tiles
  let ambient = getAmbientLight()
  for floorKind in FloorSpriteKind:
    let floorSprite = case floorKind
      of FloorCave: "cave"
      of FloorDungeon: "dungeon"
      of FloorSnow: "snow"
      of FloorBase: "floor"
    for pos in floorSpritePositions[floorKind]:
      if not isInViewport(pos):
        continue
      let bc = combinedTileTint(env, pos.x, pos.y)
      # Apply ambient light to tile color
      let lit = applyAmbient(bc.r, bc.g, bc.b, bc.intensity, ambient)
      bxy.drawImage(floorSprite, pos.vec2, angle = 0, scale = SpriteScale,
        tint = color(min(lit.r * lit.i, 1.5), min(lit.g * lit.i, 1.5),
                     min(lit.b * lit.i, 1.5), 1.0))

proc drawTerrain*() =
  # Only iterate over visible tiles for viewport culling
  if not currentViewport.valid:
    return
  for x in currentViewport.minX .. currentViewport.maxX:
    for y in currentViewport.minY .. currentViewport.maxY:
      let terrain = env.terrain[x][y]
      if terrain in {Water, ShallowWater, Mountain}: continue
      let spriteKey = terrainSpriteKey(terrain)
      if spriteKey.len > 0 and spriteKey in bxy:
        bxy.drawImage(spriteKey, ivec2(x, y).vec2, angle = 0, scale = SpriteScale)

proc drawWalls*() =
  template hasWall(x: int, y: int): bool =
    x >= 0 and x < MapWidth and
    y >= 0 and y < MapHeight and
    not isNil(env.grid[x][y]) and
    env.grid[x][y].kind == Wall

  if not currentViewport.valid:
    return
  var wallFills: seq[IVec2]
  let wallTint = WallTintColor
  # Only iterate over visible tiles for viewport culling
  for x in currentViewport.minX .. currentViewport.maxX:
    for y in currentViewport.minY .. currentViewport.maxY:
      let thing = env.grid[x][y]
      if not isNil(thing) and thing.kind == Wall:
        var tile = 0'u16
        if hasWall(x, y + 1): tile = tile or WallS.uint16
        if hasWall(x + 1, y): tile = tile or WallE.uint16
        if hasWall(x, y - 1): tile = tile or WallN.uint16
        if hasWall(x - 1, y): tile = tile or WallW.uint16

        if (tile and WallSE.uint16) == WallSE.uint16 and
            hasWall(x + 1, y + 1):
          wallFills.add(ivec2(x.int32, y.int32))
          if (tile and WallNW.uint16) == WallNW.uint16 and
              hasWall(x - 1, y - 1) and
              hasWall(x - 1, y + 1) and
              hasWall(x + 1, y - 1):
            continue

        let wallSpriteKey = wallSprites[tile]
        if wallSpriteKey in bxy:
          bxy.drawImage(wallSpriteKey, vec2(x.float32, y.float32),
                       angle = 0, scale = SpriteScale, tint = wallTint)

  let fillSpriteKey = "oriented/wall.fill"
  if fillSpriteKey in bxy:
    for fillPos in wallFills:
      bxy.drawImage(fillSpriteKey, fillPos.vec2 + vec2(0.5, 0.3),
                    angle = 0, scale = SpriteScale, tint = wallTint)

proc drawObjects*() =
  var teamPopCounts: array[MapRoomObjectsTeams, int]
  var teamHouseCounts: array[MapRoomObjectsTeams, int]
  for agent in env.agents:
    if isAgentAlive(env, agent):
      let teamId = getTeamId(agent)
      if teamId >= 0 and teamId < MapRoomObjectsTeams:
        inc teamPopCounts[teamId]
  for house in env.thingsByKind[House]:
    let teamId = house.teamId
    if teamId >= 0 and teamId < MapRoomObjectsTeams:
      inc teamHouseCounts[teamId]

  # Get ambient light for day/night cycle
  let ambient = getAmbientLight()

  for pos in env.actionTintPositions:
    if not isValidPos(pos) or not isInViewport(pos):
      continue
    if env.actionTintCountdown[pos.x][pos.y] > 0:
      let c = env.actionTintColor[pos.x][pos.y]
      # Apply ambient light to action tint overlay
      let lit = applyAmbient(c.r, c.g, c.b, 1.0, ambient)
      # Render the short-lived action overlay fully opaque so it sits above the
      # normal tint layer and clearly masks the underlying tile color.
      bxy.drawImage("floor", pos.vec2, angle = 0, scale = SpriteScale, tint = color(lit.r, lit.g, lit.b, 1.0))

  let waterKey = terrainSpriteKey(Water)

  # Draw water from terrain so agents can occupy those tiles while keeping visuals.
  # Deep water (center of rivers) renders darker, shallow water (edges) renders lighter.
  if renderCacheGeneration != env.mapGeneration:
    rebuildRenderCaches()
  if waterKey.len > 0 and waterKey in bxy:
    # Draw deep water (impassable) with ambient-lit tint
    let waterLit = applyAmbient(1.0, 1.0, 1.0, 1.0, ambient)
    let waterTint = color(waterLit.r * waterLit.i, waterLit.g * waterLit.i, waterLit.b * waterLit.i, 1.0)
    for pos in waterPositions:
      if isInViewport(pos):
        bxy.drawImage(waterKey, pos.vec2, angle = 0, scale = SpriteScale, tint = waterTint)
    # Draw shallow water (passable but slow) with lighter tint to distinguish
    let shallowLit = applyAmbient(ShallowWaterBase.r, ShallowWaterBase.g, ShallowWaterBase.b, 1.0, ambient)
    let shallowTint = color(shallowLit.r * shallowLit.i, shallowLit.g * shallowLit.i, shallowLit.b * shallowLit.i, 1.0)
    for pos in shallowWaterPositions:
      if isInViewport(pos):
        bxy.drawImage(waterKey, pos.vec2, angle = 0, scale = SpriteScale, tint = shallowTint)

  # Draw mountain terrain (impassable) with dark gray-brown rocky tint
  let mountainKey = terrainSpriteKey(Mountain)
  if mountainKey.len > 0 and mountainKey in bxy:
    let mountainLit = applyAmbient(MountainBase.r, MountainBase.g, MountainBase.b, 1.0, ambient)
    let mountainTint = color(mountainLit.r * mountainLit.i, mountainLit.g * mountainLit.i, mountainLit.b * mountainLit.i, 1.0)
    for pos in mountainPositions:
      if isInViewport(pos):
        bxy.drawImage(mountainKey, pos.vec2, angle = 0, scale = SpriteScale, tint = mountainTint)

  # Draw waterfalls (between water and cliffs for proper layering)
  for kind in WaterfallDrawOrder:
    let spriteKey = thingSpriteKey(kind)
    if spriteKey.len > 0 and spriteKey in bxy:
      for wf in env.thingsByKind[kind]:
        if isInViewport(wf.pos):
          bxy.drawImage(spriteKey, wf.pos.vec2, angle = 0, scale = SpriteScale)

  for kind in CliffDrawOrder:
    let spriteKey = thingSpriteKey(kind)
    if spriteKey.len > 0 and spriteKey in bxy:
      for cliff in env.thingsByKind[kind]:
        if isInViewport(cliff.pos):
          bxy.drawImage(spriteKey, cliff.pos.vec2, angle = 0, scale = SpriteScale)

  template drawThings(thingKind: ThingKind, body: untyped) =
    ## Iterates over all visible things of a given kind and executes `body` for each.
    ## Automatically culls things outside the current viewport.
    ##
    ## **Injected variables:**
    ## - `thing: Thing` - The current thing being iterated over
    ## - `thingPos: IVec2` - The position of the current thing (shorthand for thing.pos)
    ##
    ## **Example:**
    ## ```nim
    ## drawThings(Tree):
    ##   bxy.drawImage("tree", thingPos.vec2, scale = SpriteScale)
    ##   if thing.health < thing.maxHealth:
    ##     drawHealthBar(thingPos, thing.health, thing.maxHealth)
    ## ```
    for it in env.thingsByKind[thingKind]:
      if not isInViewport(it.pos):
        continue
      let thing {.inject.} = it
      let thingPos {.inject.} = it.pos
      body

  proc getResourceDepletionScale(thing: Thing): float32 =
    ## Calculates a visual scale factor for resource nodes based on remaining resources.
    let (itemKey, maxAmount) = case thing.kind
      of Tree, Stump: (ItemWood, ResourceNodeInitial)
      of Wheat, Stubble: (ItemWheat, ResourceNodeInitial)
      of Stone, Stalagmite: (ItemStone, ResourceNodeInitial)
      of Gold: (ItemGold, ResourceNodeInitial)
      of Bush, Cactus: (ItemPlant, ResourceNodeInitial)
      of Fish: (ItemFish, ResourceNodeInitial)
      else: (ItemNone, 1)
    if itemKey == ItemNone or maxAmount <= 0:
      return SpriteScale
    let remaining = getInv(thing, itemKey)
    let ratio = remaining.float32 / maxAmount.float32
    # Scale from DepletionScaleMax (1.0) to DepletionScaleMin (0.5) based on remaining
    let depletionScale = SpriteScale * (DepletionScaleMin + ratio * (DepletionScaleMax - DepletionScaleMin))
    # Per-resource visual normalization so bulky source art does not dominate tile footprint.
    let visualScale = case thing.kind
      of Stone, Stalagmite: 0.82'f32
      of Gold: 0.88'f32
      of Stump, Stubble: 0.9'f32
      else: 1.0'f32
    depletionScale * visualScale

  for kind in [Tree, Wheat, Stubble]:
    let spriteKey = thingSpriteKey(kind)
    if spriteKey.len > 0 and spriteKey in bxy:
      for thing in env.thingsByKind[kind]:
        let pos = thing.pos
        if not isInViewport(pos):
          continue
        let depletionScale = getResourceDepletionScale(thing)
        bxy.drawImage(spriteKey, pos.vec2, angle = 0, scale = depletionScale)
        if isTileFrozen(pos, env):
          bxy.drawImage("frozen", pos.vec2, angle = 0, scale = depletionScale)

  # Draw unit shadows first (before agents, so shadows appear underneath)
  # Light source is NW, so shadows cast to SE (positive X and Y offset)
  let shadowTint = ShadowTint
  let shadowOffset = vec2(constants.ShadowOffsetX, constants.ShadowOffsetY)
  for agent in env.agents:
    if not isAgentAlive(env, agent):
      continue
    renderAgentShadow(agent, shadowTint, shadowOffset)

  drawThings(Agent):
    let agent = thing
    let baseKey = getUnitSpriteBase(agent.unitClass, agent.agentId, agent.packed)
    let agentSpriteKey = selectUnitSpriteKey(baseKey, agent.orientation)
    if agentSpriteKey.len > 0 and agent.agentId >= 0 and agent.agentId < env.agentColors.len:
      # Apply subtle breathing animation when idle
      let animScale = if agent.isIdle:
        # Use agent position for phase offset so units don't breathe in sync
        let phaseOffset = (thingPos.x.float32 + thingPos.y.float32 * 1.3) * IdleAnimationPhaseScale
        let breathPhase = nowSeconds() * IdleAnimationSpeed * 2 * PI + phaseOffset
        SpriteScale * (1.0 + IdleAnimationAmplitude * sin(breathPhase))
      else:
        SpriteScale
      bxy.drawImage(agentSpriteKey, thingPos.vec2, angle = 0,
                    scale = animScale, tint = env.agentColors[agent.agentId])

  # Draw dying units with fade-out animation
  for dying in env.dyingUnits:
    if not isInViewport(dying.pos):
      continue
    if dying.agentId < 0 or dying.agentId >= env.agentColors.len:
      continue
    let dyingBaseKey = getUnitSpriteBase(dying.unitClass, dying.agentId)
    let dyingSpriteKey = selectUnitSpriteKey(dyingBaseKey, dying.orientation)
    if dyingSpriteKey.len > 0:
      # Calculate fade: starts at 1.0 (full opacity), fades to 0.0
      let fade = dying.countdown.float32 / dying.lifetime.float32
      # Calculate scale: starts at 1.0, shrinks to 0.3 for collapse effect
      let dyingScale = SpriteScale * (0.3 + 0.7 * fade)
      # Get base unit color and apply alpha fade
      let baseColor = env.agentColors[dying.agentId]
      # Tint towards red during death, then fade out
      let deathTint = color(
        min(1.0, baseColor.r + 0.3 * (1.0 - fade)),
        baseColor.g * fade,
        baseColor.b * fade,
        fade * 0.9 + 0.1  # Never fully transparent until removed
      )
      bxy.drawImage(dyingSpriteKey, dying.pos.vec2, angle = 0,
                    scale = dyingScale, tint = deathTint)

  drawThings(Altar):
    let altarTint = if env.altarColors.hasKey(thingPos): env.altarColors[thingPos]
      elif thingPos.x >= 0 and thingPos.x < MapWidth and thingPos.y >= 0 and thingPos.y < MapHeight:
        let base = env.baseTintColors[thingPos.x][thingPos.y]
        color(base.r, base.g, base.b, 1.0)
      else: TintWhite
    let posVec = thingPos.vec2
    bxy.drawImage("floor", posVec, angle = 0, scale = SpriteScale,
                  tint = withAlpha(altarTint, ResourceIconDimAlpha))
    bxy.drawImage("altar", posVec, angle = 0, scale = SpriteScale,
                  tint = withAlpha(altarTint, 1.0))
    const heartAnchor = vec2(-0.48, -0.64)
    let amt = max(0, thing.hearts)
    let heartPos = posVec + heartAnchor
    if amt == 0:
      bxy.drawImage("heart", heartPos, angle = 0, scale = HeartIconScale,
                    tint = withAlpha(altarTint, ResourceIconDimAlpha))
    elif amt <= HeartPlusThreshold:
      for i in 0 ..< amt:
        bxy.drawImage("heart", heartPos + vec2(0.12 * i.float32, 0.0),
                      angle = 0, scale = HeartIconScale, tint = altarTint)
    else:
      bxy.drawImage("heart", heartPos, angle = 0, scale = HeartIconScale, tint = altarTint)
      let labelKey = ensureHeartCountLabel(amt)
      bxy.drawImage(labelKey, heartPos + vec2(0.14, -0.08), angle = 0,
                    scale = HeartCountLabelScale, tint = TintWhite)
    if isTileFrozen(thingPos, env):
      bxy.drawImage("frozen", posVec, angle = 0, scale = SpriteScale)

  drawThings(Tumor):
    let prefix = if thing.hasClaimedTerritory: "oriented/tumor.expired." else: "oriented/tumor."
    let key = prefix & TumorDirKeys[thing.orientation.int]
    if key in bxy:
      bxy.drawImage(key, thingPos.vec2, angle = 0, scale = SpriteScale)

  template drawOrientedThings(thingKind: ThingKind, prefix: string) =
    ## Draws all visible things of a given kind using orientation-based sprites.
    ## Builds sprite keys by combining the prefix with the thing's orientation.
    ##
    ## **Injected variables (from drawThings):**
    ## - `thing: Thing` - The current thing being iterated over
    ## - `thingPos: IVec2` - The position of the current thing
    ##
    ## **Parameters:**
    ## - `thingKind` - The ThingKind to iterate over
    ## - `prefix` - Sprite key prefix (e.g., "oriented/cow." -> "oriented/cow.N")
    ##
    ## **Example:**
    ## ```nim
    ## drawOrientedThings(Cow, "oriented/cow.")
    ## # Draws cows using sprites like "oriented/cow.N", "oriented/cow.SE", etc.
    ## ```
    drawThings(thingKind):
      let key = prefix & OrientationDirKeys[thing.orientation.int]
      if key in bxy:
        bxy.drawImage(key, thingPos.vec2, angle = 0, scale = SpriteScale)

  drawOrientedThings(Cow, "oriented/cow.")
  drawOrientedThings(Bear, "oriented/bear.")
  drawOrientedThings(Wolf, "oriented/wolf.")

  drawThings(Lantern):
    if "lantern" in bxy:
      let tint = if thing.lanternHealthy:
        let teamId = thing.teamId
        let baseColor = if teamId >= 0 and teamId < env.teamColors.len: env.teamColors[teamId]
                        else: NeutralGrayLight
        # Multi-wave fire flicker using position-based phase offset for independent animation
        let posHash = (thingPos.x * 73 + thingPos.y * 137).float32
        let wave1 = sin((frame.float32 * LanternFlickerSpeed1) + posHash * 0.1)
        let wave2 = sin((frame.float32 * LanternFlickerSpeed2) + posHash * 0.17)
        let wave3 = sin((frame.float32 * LanternFlickerSpeed3) + posHash * 0.23)
        let flicker = 1.0 + LanternFlickerAmplitude * (wave1 * 0.5 + wave2 * 0.3 + wave3 * 0.2)
        color(min(1.2, baseColor.r * flicker), min(1.2, baseColor.g * flicker),
              min(1.2, baseColor.b * flicker), baseColor.a)
      else: NeutralGray
      bxy.drawImage("lantern", thingPos.vec2, angle = 0, scale = SpriteScale, tint = tint)

  template isPlacedAt(thing: Thing): bool =
    isValidPos(thing.pos) and (
      if thingBlocksMovement(thing.kind): env.grid[thing.pos.x][thing.pos.y] == thing
      else: env.backgroundGrid[thing.pos.x][thing.pos.y] == thing)

  # ---------------------------------------------------------------------------
  # Building and Object Rendering
  # ---------------------------------------------------------------------------
  for kind in ThingKind:
    if kind in {Wall, Tree, Wheat, Stubble, Agent, Altar, Tumor, Cow, Bear, Wolf, Lantern} or
        kind in CliffKinds or kind in WaterfallKinds:
      continue
    if isBuildingKind(kind):
      let spriteKey = buildingSpriteKey(kind)
      if spriteKey.len == 0 or spriteKey notin bxy:
        continue
      for thing in env.thingsByKind[kind]:
        if not isPlacedAt(thing) or not isInViewport(thing.pos):
          continue
        let pos = thing.pos
        # Check if building is under construction
        let isUnderConstruction = thing.maxHp > 0 and thing.hp < thing.maxHp
        let baseTint =
          if thing.kind in {Door, TownCenter, Barracks, ArcheryRange, Stable, SiegeWorkshop, Castle}:
            let teamId = thing.teamId
            let base = if teamId >= 0 and teamId < env.teamColors.len:
              env.teamColors[teamId]
            else:
              NeutralGrayDim
            color(base.r * BuildingTeamTintMul + BuildingTeamTintAdd,
                  base.g * BuildingTeamTintMul + BuildingTeamTintAdd,
                  base.b * BuildingTeamTintMul + BuildingTeamTintAdd, BuildingTeamTintAlpha)
          else:
            TintWhite
        # Apply scaffolding effect: desaturate and add transparency when under construction
        let tint = if isUnderConstruction:
          let constructionProgress = thing.hp.float32 / thing.maxHp.float32
          # Desaturate: blend toward gray, more gray at lower progress
          let desatFactor = 0.4 + 0.6 * constructionProgress  # 0.4 to 1.0
          let gray = (baseTint.r + baseTint.g + baseTint.b) / 3.0
          color(
            baseTint.r * desatFactor + gray * (1.0 - desatFactor),
            baseTint.g * desatFactor + gray * (1.0 - desatFactor),
            baseTint.b * desatFactor + gray * (1.0 - desatFactor),
            0.7 + 0.3 * constructionProgress  # 0.7 to 1.0 alpha
          )
        else:
          baseTint

        bxy.drawImage(spriteKey, pos.vec2, angle = 0, scale = SpriteScale, tint = tint)

        # Draw construction scaffolding and progress bar if under construction
        if isUnderConstruction:
          let constructionRatio = thing.hp.float32 / thing.maxHp.float32
          renderBuildingConstruction(pos, constructionRatio)

        # Draw building UI overlays (stockpiles, population, garrison, production queue)
        renderBuildingUI(thing, pos, teamPopCounts, teamHouseCounts)

        # Draw health bar for damaged buildings (not under construction — those show progress bar)
        if not isUnderConstruction and thing.maxHp > 0 and thing.hp < thing.maxHp:
          let hpRatio = thing.hp.float32 / thing.maxHp.float32
          let hpColor = getHealthBarColor(hpRatio)
          drawSegmentBar(pos.vec2, vec2(0, -0.55), hpRatio, hpColor, BarBgColor)

        # Draw frozen overlay if applicable
        if isTileFrozen(pos, env):
          bxy.drawImage("frozen", pos.vec2, angle = 0, scale = SpriteScale)

    else:
      # Non-building things
      let spriteKey = thingSpriteKey(kind)
      if spriteKey.len == 0 or spriteKey notin bxy:
        continue
      for thing in env.thingsByKind[kind]:
        if not isInViewport(thing.pos):
          continue
        let pos = thing.pos
        let scale = case kind
          of Stone, Stalagmite, Gold, Bush, Cactus, Fish, Stump:
            getResourceDepletionScale(thing)
          else:
            SpriteScale
        bxy.drawImage(spriteKey, pos.vec2, angle = 0, scale = scale)
        if isTileFrozen(pos, env):
          bxy.drawImage("frozen", pos.vec2, angle = 0, scale = scale)

proc drawVisualRanges*(alpha = 0.2) =
  ## Draw visual range circles for selected units/buildings.
  ## Shows attack range, vision range, etc.
  if selection.len == 0 or not settings.showVisualRange:
    return

  for thing in selection:
    if thing.isNil or not isInViewport(thing.pos):
      continue

    # Get the appropriate range based on thing type
    let range = if thing.kind == Agent:
      getUnitAttackRange(thing)
    elif isBuildingKind(thing.kind):
      if thing.kind == GuardTower:
        GuardTowerRange
      elif thing.kind == Castle:
        CastleRange
      else:
        0
    else:
      0

    if range <= 0:
      continue

    let center = thing.pos.vec2
    let teamColor = getTeamColor(env, thing.teamId)
    let rangeColor = withAlpha(teamColor, alpha)

    # Draw range as filled circles using floor sprites
    let rangeSq = range * range
    for dx in -range .. range:
      for dy in -range .. range:
        let distSq = dx * dx + dy * dy
        if distSq <= rangeSq:
          let pos = center + vec2(dx.float32, dy.float32)
          let gridPos = ivec2(pos.x.int, pos.y.int)
          if isInViewport(gridPos):
            bxy.drawImage("floor", pos, angle = 0, scale = SpriteScale * 0.8,
                          tint = rangeColor)

proc drawAgentDecorations*() =
  ## Draw health bars, control group badges, and other unit decorations.
  if not currentViewport.valid:
    return

  for agent in env.agents:
    if not isAgentAlive(env, agent):
      continue
    let pos = agent.pos
    if not isInViewport(pos):
      continue

    # Draw health bar above unit (always visible for all units)
    if agent.maxHp > 0:
      let hpRatio = agent.hp.float32 / agent.maxHp.float32
      let hpAlpha = if agent.hp < agent.maxHp:
        getHealthBarAlpha(env.currentStep, agent.lastAttackedStep)
      else:
        HealthBarMinAlpha  # Full HP: show at minimum alpha
      let hpColor = getHealthBarColor(hpRatio)
      drawSegmentBar(pos.vec2, vec2(0, -0.5), hpRatio, hpColor,
                     BarBgColor, 5, hpAlpha)

proc drawGrid*() =
  ## Draw grid lines for tile boundaries.
  if not settings.showGrid or not currentViewport.valid:
    return

  let gridColor = GridLineColor

  # Draw vertical lines
  for x in currentViewport.minX .. currentViewport.maxX + 1:
    for y in currentViewport.minY .. currentViewport.maxY:
      bxy.drawImage("floor", vec2(x.float32 - 0.5, y.float32), angle = 0,
                    scale = GridLineScale, tint = gridColor)

  # Draw horizontal lines
  for y in currentViewport.minY .. currentViewport.maxY + 1:
    for x in currentViewport.minX .. currentViewport.maxX:
      bxy.drawImage("floor", vec2(x.float32, y.float32 - 0.5), angle = 0,
                    scale = GridLineScale, tint = gridColor)
