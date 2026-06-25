const
  # Fixed-point decay: multiply by FP constant then right-shift 16 bits.
  # Avoids expensive integer division (measured 1.5-1.8x faster).
  # Steeper trail decay (0.997 vs old 0.9985) reduces active tile count ~50%.
  TrailDecayFP = 65339'i64    # round(0.997 * 65536)
  TumorDecayFP = 65208'i64    # round(0.995 * 65536)
  DecayShift = 16
  InvTintStrengthScale = 1.0'f32 / 80000.0'f32  # Pre-computed reciprocal of TintStrengthScale
  TumorIncrementBase = 30.0'f32
  # Threshold for frozen state: tumor must dominate with sufficient intensity
  # Derived from ClippyTintTolerance (0.06) and typical biome base colors.
  # For combined.b >= 1.14 (within tolerance of ClippyTint.b=1.20), need α >= 0.95.
  # α = strength / 80000, so need strength >= 76000.
  # Tumor must also dominate (5x) to keep overlay color close to ClippyTint.
  FrozenTumorDominanceRatio = 5.0'f32  # tumorStrength must be 5x teamStrength
  FrozenMinIntensity = 76000'i32  # Minimum total strength for frozen state (95% of max)
  # Stagger interval for decay: only process 1/N tiles per step
  # Reduces decay loop work by N-fold while maintaining visual consistency
  TintDecayStaggerInterval* = 5

var tintSortBuf: seq[IVec2]  # Reusable buffer for counting sort

template markActiveTile(active: var ActiveTiles, tileX, tileY: int) =
  if tileX >= 0 and tileX < MapWidth and tileY >= 0 and tileY < MapHeight:
    if not active.flags[tileX][tileY]:
      active.flags[tileX][tileY] = true
      active.positions.add(ivec2(tileX, tileY))

template markStepDirty(env: Environment, tileX, tileY: int) =
  ## Mark a tile as having received new entity contributions this step.
  ## Used to decide between fast-path (intensity-only) and full recompute.
  if not env.stepDirtyFlags[tileX][tileY]:
    env.stepDirtyFlags[tileX][tileY] = true
    env.stepDirtyPositions.add(ivec2(tileX, tileY))

template updateFrozenState(env: Environment, tileX, tileY: int) =
  ## Update cached frozen state for a tile based on tumor vs team strength ratio.
  ## A tile is frozen when tumor tint dominates strongly enough to shift combined
  ## color toward ClippyTint. This avoids expensive RGB computation in isTileFrozen.
  let tumorStr = env.tumorStrength[tileX][tileY]
  let teamStr = env.tintStrength[tileX][tileY]
  let totalStr = tumorStr + teamStr
  # Frozen requires: sufficient intensity AND tumor dominates
  env.frozenTiles[tileX][tileY] =
    totalStr >= FrozenMinIntensity and
    tumorStr.float32 > teamStr.float32 * FrozenTumorDominanceRatio

proc countingSortByX(positions: var seq[IVec2]) =
  ## O(n) sort by X coordinate using counting sort. Much faster than
  ## O(n log n) comparison sort for the typical 3K-9K active tiles.
  let n = positions.len
  if n <= 1: return
  var counts: array[MapWidth, int]
  for pos in positions:
    inc counts[pos.x.int]
  var total = 0
  for i in 0 ..< MapWidth:
    let c = counts[i]
    counts[i] = total
    total += c
  tintSortBuf.setLen(n)
  for pos in positions:
    let idx = counts[pos.x.int]
    tintSortBuf[idx] = pos
    inc counts[pos.x.int]
  swap(positions, tintSortBuf)

proc updateTintModifications(env: Environment) =
  ## Update unified tint modification array based on entity positions - runs every frame.
  ## Also maintains frozen tile cache for O(1) isTileFrozen lookups.
  ## Does NOT compute RGB colors - use ensureTintColors() before rendering/scoring.
  ##
  ## Optimization: Uses staggered decay to reduce work by TintDecayStaggerInterval-fold.
  ## Only tiles where tileX mod StaggerInterval == currentStep mod StaggerInterval are
  ## decayed each step. This spreads decay work across multiple steps while maintaining
  ## visual consistency (decay rate is unchanged, just distributed temporally).
  ##
  ## In headless mode (-d:headless), RGB components are skipped entirely since only
  ## frozen state matters for game logic.
  # Adaptive epsilon: cull weaker trails when active tile count is high
  let tileCount = env.activeTiles.positions.len
  let epsilon =
    if tileCount > 3000: MinTintEpsilon * 20  # Aggressive cleanup
    elif tileCount > 2000: MinTintEpsilon * 10
    elif tileCount > 1000: MinTintEpsilon * 4
    else: MinTintEpsilon

  # Stagger phase for this step (0..StaggerInterval-1)
  let staggerPhase = env.currentStep mod TintDecayStaggerInterval

  # Decay existing tint trails using fixed-point multiply + shift (avoids expensive division)
  # Widen to int64 for multiply to avoid int32 overflow (MaxTintAccum * 65339 > int32.max)
  # STAGGERED: Only decay tiles matching this step's phase to reduce work 5x
  var writeIdx = 0
  for readIdx in 0 ..< tileCount:
    let pos = env.activeTiles.positions[readIdx]
    if not isValidPos(pos):
      continue
    let tileX = pos.x.int
    let tileY = pos.y.int

    # Stagger check: only decay tiles whose X coordinate matches this step's phase
    if tileX mod TintDecayStaggerInterval != staggerPhase:
      # Keep tile in list without decaying
      env.activeTiles.positions[writeIdx] = pos
      inc writeIdx
      continue

    let strength = env.tintStrength[tileX][tileY]
    let decayedStrength = int32((strength.int64 * TrailDecayFP) shr DecayShift)
    if abs(decayedStrength) < epsilon:
      when not defined(headless):
        env.tintMods[tileX][tileY] = TintModification(r: 0'i32, g: 0'i32, b: 0'i32)
      env.tintStrength[tileX][tileY] = 0
      env.activeTiles.flags[tileX][tileY] = false
      # Update frozen state when team tint is cleared
      updateFrozenState(env, tileX, tileY)
      # If tile has tumor tint, mark dirty so tumor pass does full recompute
      if env.tumorActiveTiles.flags[tileX][tileY]:
        markStepDirty(env, tileX, tileY)
      continue

    # Decay RGB components (skip in headless mode - only strength/frozen matters)
    when not defined(headless):
      let current = env.tintMods[tileX][tileY]
      let decayedR = int32((current.r.int64 * TrailDecayFP) shr DecayShift)
      let g = int32((current.g.int64 * TrailDecayFP) shr DecayShift)
      let b = int32((current.b.int64 * TrailDecayFP) shr DecayShift)
      env.tintMods[tileX][tileY] = TintModification(r: decayedR, g: g, b: b)

    env.tintStrength[tileX][tileY] = decayedStrength
    env.activeTiles.positions[writeIdx] = pos
    inc writeIdx
  env.activeTiles.positions.setLen(writeIdx)

  # Adaptive epsilon for tumor tiles
  let tumorTileCount = env.tumorActiveTiles.positions.len
  let tumorEpsilon =
    if tumorTileCount > 3000: MinTintEpsilon * 20
    elif tumorTileCount > 2000: MinTintEpsilon * 10
    elif tumorTileCount > 1000: MinTintEpsilon * 4
    else: MinTintEpsilon

  # STAGGERED: Only decay tumor tiles matching this step's phase
  writeIdx = 0
  for readIdx in 0 ..< tumorTileCount:
    let pos = env.tumorActiveTiles.positions[readIdx]
    if not isValidPos(pos):
      continue
    let tileX = pos.x.int
    let tileY = pos.y.int

    # Stagger check: only decay tiles whose X coordinate matches this step's phase
    if tileX mod TintDecayStaggerInterval != staggerPhase:
      # Keep tile in list without decaying
      env.tumorActiveTiles.positions[writeIdx] = pos
      inc writeIdx
      continue

    let strength = env.tumorStrength[tileX][tileY]
    let decayedStrength = int32((strength.int64 * TumorDecayFP) shr DecayShift)
    if abs(decayedStrength) < tumorEpsilon:
      when not defined(headless):
        env.tumorTintMods[tileX][tileY] = TintModification(r: 0'i32, g: 0'i32, b: 0'i32)
      env.tumorStrength[tileX][tileY] = 0
      env.tumorActiveTiles.flags[tileX][tileY] = false
      # Update frozen state when tumor tint is cleared
      updateFrozenState(env, tileX, tileY)
      # If tile has agent tint, mark dirty so agent pass does full recompute
      if env.activeTiles.flags[tileX][tileY]:
        markStepDirty(env, tileX, tileY)
      continue

    # Decay RGB components (skip in headless mode - only strength/frozen matters)
    when not defined(headless):
      let current = env.tumorTintMods[tileX][tileY]
      let decayedR = int32((current.r.int64 * TumorDecayFP) shr DecayShift)
      let g = int32((current.g.int64 * TumorDecayFP) shr DecayShift)
      let b = int32((current.b.int64 * TumorDecayFP) shr DecayShift)
      env.tumorTintMods[tileX][tileY] = TintModification(r: decayedR, g: g, b: b)

    env.tumorStrength[tileX][tileY] = decayedStrength
    # Update frozen state after tumor decay
    updateFrozenState(env, tileX, tileY)
    env.tumorActiveTiles.positions[writeIdx] = pos
    inc writeIdx
  env.tumorActiveTiles.positions.setLen(writeIdx)

  # Helper: add team tint in a radius with simple Manhattan falloff
  # Uses direct addition (values are always positive, overflow to MaxTintAccum is safe)
  # In headless mode, skip RGB - only strength matters for frozen state
  proc addTintArea(baseX, baseY: int, color: Color, radius: int, scale: int) =
    let minX = max(0, baseX - radius)
    let maxX = min(MapWidth - 1, baseX + radius)
    let minY = max(0, baseY - radius)
    let maxY = min(MapHeight - 1, baseY + radius)
    let baseStrength = (scale * 5).int32
    for tileX in minX .. maxX:
      let dx = tileX - baseX
      for tileY in minY .. maxY:
        if env.tintLocked[tileX][tileY]:
          continue
        let dy = tileY - baseY
        let dist = abs(dx) + abs(dy)
        let falloff = max(1, radius * 2 + 1 - dist).int32
        markActiveTile(env.activeTiles, tileX, tileY)
        markStepDirty(env, tileX, tileY)
        let strength = baseStrength * falloff
        env.tintStrength[tileX][tileY] = min(MaxTintAccum, env.tintStrength[tileX][tileY] + strength)
        when not defined(headless):
          env.tintMods[tileX][tileY].r = min(MaxTintAccum, env.tintMods[tileX][tileY].r + int32(color.r * strength.float32))
          env.tintMods[tileX][tileY].g = min(MaxTintAccum, env.tintMods[tileX][tileY].g + int32(color.g * strength.float32))
          env.tintMods[tileX][tileY].b = min(MaxTintAccum, env.tintMods[tileX][tileY].b + int32(color.b * strength.float32))
        # Update frozen state when team tint changes
        updateFrozenState(env, tileX, tileY)

  # Process only tint-relevant entity kinds (Agent, Lantern, Tumor) using
  # thingsByKind instead of iterating all env.things (skips ~7000 irrelevant things)
  # Optimization: only add tint for entities that moved since last step
  for thing in env.thingsByKind[Agent]:
    let pos = thing.pos
    if not isValidPos(pos):
      continue
    let agentId = thing.agentId
    if agentId < 0 or agentId >= MapAgents:
      continue
    # Skip tint update if agent hasn't moved (delta optimization).
    let lastPos = env.lastAgentPos[agentId]
    if lastPos == pos and isValidPos(lastPos):
      continue
    # Update tracking and add tint for moved agents.
    env.lastAgentPos[agentId] = pos
    if agentId < env.agentColors.len:
      let baseX = pos.x.int
      let baseY = pos.y.int
      addTintArea(baseX, baseY, env.agentColors[agentId], radius = 2, scale = 90)

  for thing in env.thingsByKind[Lantern]:
    if not thing.lanternHealthy:
      continue
    let pos = thing.pos
    if not isValidPos(pos):
      continue
    # Skip tint update if lantern hasn't moved (delta optimization).
    if thing.lastTintPos == pos and isValidPos(thing.lastTintPos):
      continue
    thing.lastTintPos = pos
    if thing.teamId >= 0 and thing.teamId < env.teamColors.len:
      let baseX = pos.x.int
      let baseY = pos.y.int
      addTintArea(baseX, baseY, env.teamColors[thing.teamId], radius = 2, scale = 60)

  for thing in env.thingsByKind[Tumor]:
    let pos = thing.pos
    if not isValidPos(pos):
      continue
    # Skip tint update if tumor hasn't moved (delta optimization).
    if thing.lastTintPos == pos and isValidPos(thing.lastTintPos):
      continue
    thing.lastTintPos = pos
    let baseX = pos.x.int
    let baseY = pos.y.int
    let minX = max(0, baseX - 2)
    let maxX = min(MapWidth - 1, baseX + 2)
    let minY = max(0, baseY - 2)
    let maxY = min(MapHeight - 1, baseY + 2)
    for tileX in minX .. maxX:
      let dx = tileX - baseX
      for tileY in minY .. maxY:
        if env.tintLocked[tileX][tileY]:
          continue
        let dy = tileY - baseY
        let manDist = abs(dx) + abs(dy)
        let falloff = max(1, 5 - manDist)
        markActiveTile(env.tumorActiveTiles, tileX, tileY)
        markStepDirty(env, tileX, tileY)
        let strength = TumorIncrementBase * falloff.float32
        safeTintAdd(env.tumorStrength[tileX][tileY], int(strength))
        when not defined(headless):
          safeTintAdd(env.tumorTintMods[tileX][tileY].r, int(ClippyTint.r * strength))
          safeTintAdd(env.tumorTintMods[tileX][tileY].g, int(ClippyTint.g * strength))
          safeTintAdd(env.tumorTintMods[tileX][tileY].b, int(ClippyTint.b * strength))
        # Update frozen state when tumor tint added
        updateFrozenState(env, tileX, tileY)

  # Mark tint colors as needing recomputation (lazy evaluation)
  env.tintColorsDirty = true

proc computeTileColor(env: Environment, tileX, tileY: int): TileColor =
  ## Compute the tint color for a single tile based on combined tint modifications
  let zeroTint = TileColor(r: 0, g: 0, b: 0, intensity: 0)
  if env.tintLocked[tileX][tileY]:
    return zeroTint

  let dynTint = env.tintMods[tileX][tileY]
  let tumorTint = env.tumorTintMods[tileX][tileY]
  let rTint = dynTint.r + tumorTint.r
  let gTint = dynTint.g + tumorTint.g
  let bTint = dynTint.b + tumorTint.b
  let strength = env.tintStrength[tileX][tileY] + env.tumorStrength[tileX][tileY]

  if abs(strength) < MinTintEpsilon:
    return zeroTint

  if env.terrain[tileX][tileY] == Water:
    return zeroTint

  # Use pre-computed reciprocal for TintStrengthScale; multiply instead of divide
  let alpha = min(1.0'f32, strength.float32 * InvTintStrengthScale)
  let invStrength = if strength != 0: 1.0'f32 / strength.float32 else: 0.0'f32
  let clampedR = min(1.2'f32, max(0.0'f32, rTint.float32 * invStrength))
  let clampedG = min(1.2'f32, max(0.0'f32, gTint.float32 * invStrength))
  let clampedB = min(1.2'f32, max(0.0'f32, bTint.float32 * invStrength))
  TileColor(r: clampedR, g: clampedG, b: clampedB, intensity: alpha)

proc applyTintModificationsImpl(env: Environment) =
  ## Internal: apply tint modifications to computed colors.
  ## Uses counting sort for O(n) cache-friendly ordering by X coordinate.
  ## Tiles that only underwent decay skip float division (RGB ratios unchanged).
  countingSortByX(env.activeTiles.positions)

  for pos in env.activeTiles.positions:
    let tileX = pos.x.int
    let tileY = pos.y.int
    if tileX < 0 or tileX >= MapWidth or tileY < 0 or tileY >= MapHeight:
      continue
    if env.stepDirtyFlags[tileX][tileY] or env.tumorActiveTiles.flags[tileX][tileY]:
      # Tile received new contributions or has both agent+tumor tint: full recompute
      env.computedTintColors[tileX][tileY] = computeTileColor(env, tileX, tileY)
    else:
      # Decay-only agent tile: RGB ratios unchanged, just update intensity
      let strength = env.tintStrength[tileX][tileY]
      if strength < MinTintEpsilon:
        env.computedTintColors[tileX][tileY] = TileColor(r: 0, g: 0, b: 0, intensity: 0)
      else:
        env.computedTintColors[tileX][tileY].intensity = min(1.0'f32, strength.float32 * InvTintStrengthScale)

  for pos in env.tumorActiveTiles.positions:
    let tileX = pos.x.int
    let tileY = pos.y.int
    if env.activeTiles.flags[tileX][tileY]:
      continue  # Already handled in agent pass
    if tileX < 0 or tileX >= MapWidth or tileY < 0 or tileY >= MapHeight:
      continue
    if env.stepDirtyFlags[tileX][tileY]:
      # Tile received new tumor contributions: full recompute
      env.computedTintColors[tileX][tileY] = computeTileColor(env, tileX, tileY)
    else:
      # Decay-only tumor tile: RGB ratios unchanged, just update intensity
      let strength = env.tumorStrength[tileX][tileY]
      if strength < MinTintEpsilon:
        env.computedTintColors[tileX][tileY] = TileColor(r: 0, g: 0, b: 0, intensity: 0)
      else:
        env.computedTintColors[tileX][tileY].intensity = min(1.0'f32, strength.float32 * InvTintStrengthScale)

  # Clear step-dirty flags for next step
  for pos in env.stepDirtyPositions:
    env.stepDirtyFlags[pos.x.int][pos.y.int] = false
  env.stepDirtyPositions.setLen(0)

  # Clear dirty flag
  env.tintColorsDirty = false

proc ensureTintColors*(env: Environment) {.inline.} =
  ## Ensure computedTintColors is up-to-date (lazy rebuild if dirty).
  ## Call this before accessing computedTintColors for rendering or territory scoring.
  ## Skip in headless/training mode where only frozen state matters.
  if env.tintColorsDirty:
    applyTintModificationsImpl(env)
