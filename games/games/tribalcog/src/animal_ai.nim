# Animal AI - Wildlife behavior for cows, wolves, and bears
# This file is included by step.nim

# ============================================================================
# Movement Helpers
# ============================================================================

proc stepToward*(fromPos, toPos: IVec2): IVec2 =
  ## Calculate a single cardinal step from fromPos toward toPos.
  ## Returns zero vector if positions are equal.
  let dx = toPos.x - fromPos.x
  let dy = toPos.y - fromPos.y
  if dx == 0 and dy == 0:
    return ivec2(0, 0)
  if abs(dx) >= abs(dy):
    return ivec2((if dx > 0: 1 else: -1), 0)
  return ivec2(0, (if dy > 0: 1 else: -1))

proc tryMoveWildlife*(env: Environment, thing: Thing, desired: IVec2) =
  ## Try to move a wildlife entity (cow/wolf/bear) by the desired delta.
  ## Updates grid and spatial index if move is valid.
  if desired.x == 0 and desired.y == 0:
    return
  let nextPos = thing.pos + desired
  if isValidPos(nextPos) and not env.hasDoor(nextPos) and
     not isBlockedTerrain(env.terrain[nextPos.x][nextPos.y]) and env.isEmpty(nextPos):
    let oldPos = thing.pos
    env.grid[thing.pos.x][thing.pos.y] = nil
    thing.pos = nextPos
    env.grid[nextPos.x][nextPos.y] = thing
    updateSpatialIndex(env, thing, oldPos)
    if desired.x < 0:
      thing.orientation = Orientation.W
    elif desired.x > 0:
      thing.orientation = Orientation.E

# ============================================================================
# Corner Target Selection (for herd/pack wandering)
# ============================================================================

proc selectNewCornerTarget(center, currentTarget: IVec2, rng: var Rand): IVec2 =
  ## Select a new corner target, preferring the farthest corner from center
  let cornerMin = (MapBorder + 2).int32
  let cornerMaxX = (MapWidth - MapBorder - 3).int32
  let cornerMaxY = (MapHeight - MapBorder - 3).int32
  let cornerTargets = [
    ivec2(cornerMin, cornerMin),
    ivec2(cornerMaxX, cornerMin),
    ivec2(cornerMin, cornerMaxY),
    ivec2(cornerMaxX, cornerMaxY)
  ]
  var bestDist = -1
  var candidates: array[4, IVec2]
  var candidateCount = 0
  for corner in cornerTargets:
    if corner == currentTarget:
      continue
    let dist = max(abs(center.x - corner.x), abs(center.y - corner.y))
    if dist > bestDist:
      candidateCount = 0
      candidates[candidateCount] = corner
      inc candidateCount
      bestDist = dist
    elif dist == bestDist:
      candidates[candidateCount] = corner
      inc candidateCount
  if candidateCount == 0:
    cornerTargets[randIntInclusive(rng, 0, 3)]
  else:
    candidates[randIntInclusive(rng, 0, candidateCount - 1)]

proc needsNewCornerTarget(center, target: IVec2): bool =
  ## Check if herd/pack needs a new corner target
  let cornerMin = (MapBorder + 2).int32
  let cornerMaxX = (MapWidth - MapBorder - 3).int32
  let cornerMaxY = (MapHeight - MapBorder - 3).int32
  let targetInvalid = target.x < 0 or target.y < 0
  if targetInvalid:
    return true
  let distToTarget = max(abs(center.x - target.x), abs(center.y - target.y))
  let nearBorder = center.x <= cornerMin or center.y <= cornerMin or
                   center.x >= cornerMaxX or center.y >= cornerMaxY
  nearBorder and distToTarget <= 3

# ============================================================================
# Animal AI Step - Main behavior orchestration
# ============================================================================

proc stepAnimalAI*(env: Environment, rng: var Rand) =
  ## Process all wildlife behavior: aggregation, movement, and attacks.
  ## Called once per step from the main step() function.

  # -------------------------------------------------------------------------
  # Reset Aggregation Counters
  # -------------------------------------------------------------------------
  for i in 0 ..< env.cowHerdCounts.len:
    env.cowHerdCounts[i] = 0
    env.cowHerdSumX[i] = 0
    env.cowHerdSumY[i] = 0

  for i in 0 ..< env.wolfPackCounts.len:
    env.wolfPackCounts[i] = 0
    env.wolfPackSumX[i] = 0
    env.wolfPackSumY[i] = 0

  # -------------------------------------------------------------------------
  # Cow Herd Aggregation
  # -------------------------------------------------------------------------
  for thing in env.thingsByKind[Cow]:
    let herd = thing.herdId
    if herd >= env.cowHerdCounts.len:
      let oldLen = env.cowHerdCounts.len
      let newLen = herd + 1
      env.cowHerdCounts.setLen(newLen)
      env.cowHerdSumX.setLen(newLen)
      env.cowHerdSumY.setLen(newLen)
      env.cowHerdDrift.setLen(newLen)
      env.cowHerdTargets.setLen(newLen)
      env.cowHerdCenters.setLen(newLen)
      for i in oldLen ..< newLen:
        env.cowHerdTargets[i] = ivec2(-1, -1)
        env.cowHerdCenters[i] = ivec2(0, 0)
    env.cowHerdCounts[herd] += 1
    env.cowHerdSumX[herd] += thing.pos.x.int
    env.cowHerdSumY[herd] += thing.pos.y.int

  # -------------------------------------------------------------------------
  # Wolf Pack Aggregation
  # -------------------------------------------------------------------------
  for thing in env.thingsByKind[Wolf]:
    let pack = thing.packId
    if pack >= env.wolfPackCounts.len:
      let oldLen = env.wolfPackCounts.len
      let newLen = pack + 1
      env.wolfPackCounts.setLen(newLen)
      env.wolfPackSumX.setLen(newLen)
      env.wolfPackSumY.setLen(newLen)
      env.wolfPackDrift.setLen(newLen)
      env.wolfPackTargets.setLen(newLen)
      env.wolfPackCenters.setLen(newLen)
      for i in oldLen ..< newLen:
        env.wolfPackTargets[i] = ivec2(-1, -1)
        env.wolfPackCenters[i] = ivec2(0, 0)
    env.wolfPackCounts[pack] += 1
    env.wolfPackSumX[pack] += thing.pos.x.int
    env.wolfPackSumY[pack] += thing.pos.y.int

  # -------------------------------------------------------------------------
  # Update Herd/Pack Targets and Drifts
  # -------------------------------------------------------------------------

  # Precompute herd/pack centers and update drift/targets
  # This avoids recomputing centers for every animal in the movement loops

  # Cow herds: compute centers and wander toward map corners
  for herdId in 0 ..< env.cowHerdCounts.len:
    if env.cowHerdCounts[herdId] <= 0:
      env.cowHerdDrift[herdId] = ivec2(0, 0)
      env.cowHerdCenters[herdId] = ivec2(0, 0)
      continue
    let herdAccCount = max(1, env.cowHerdCounts[herdId])
    let center = ivec2((env.cowHerdSumX[herdId] div herdAccCount).int32,
                       (env.cowHerdSumY[herdId] div herdAccCount).int32)
    env.cowHerdCenters[herdId] = center
    let target = env.cowHerdTargets[herdId]
    if needsNewCornerTarget(center, target):
      env.cowHerdTargets[herdId] = selectNewCornerTarget(center, target, rng)
    env.cowHerdDrift[herdId] = stepToward(center, env.cowHerdTargets[herdId])

  # Wolf packs: compute centers and hunt targets or wander toward corners
  for packId in 0 ..< env.wolfPackCounts.len:
    if env.wolfPackCounts[packId] <= 0:
      env.wolfPackDrift[packId] = ivec2(0, 0)
      env.wolfPackCenters[packId] = ivec2(0, 0)
      continue
    let packAccCount = max(1, env.wolfPackCounts[packId])
    let center = ivec2((env.wolfPackSumX[packId] div packAccCount).int32,
                       (env.wolfPackSumY[packId] div packAccCount).int32)
    env.wolfPackCenters[packId] = center
    let huntTarget = findNearestPredatorTargetSpatial(env, center, WolfPackAggroRadius)
    if huntTarget.x >= 0:
      env.wolfPackTargets[packId] = huntTarget
    elif needsNewCornerTarget(center, env.wolfPackTargets[packId]):
      env.wolfPackTargets[packId] = selectNewCornerTarget(center, env.wolfPackTargets[packId], rng)
    env.wolfPackDrift[packId] = stepToward(center, env.wolfPackTargets[packId])

  # -------------------------------------------------------------------------
  # Cow Movement (uses precomputed centers from above)
  # -------------------------------------------------------------------------
  for thing in env.thingsByKind[Cow]:
    if thing.cooldown > 0:
      thing.cooldown -= 1
    let herd = thing.herdId
    let center = env.cowHerdCenters[herd]  # Use precomputed center
    let drift = env.cowHerdDrift[herd]
    let herdTarget = if drift.x != 0 or drift.y != 0:
      center + drift * 3
    else:
      center
    let dist = max(abs(herdTarget.x - thing.pos.x), abs(herdTarget.y - thing.pos.y))

    var desired = ivec2(0, 0)
    if dist > 1:
      desired = stepToward(thing.pos, herdTarget)
    elif (drift.x != 0 or drift.y != 0) and randFloat(rng) < CowHerdFollowChance:
      desired = stepToward(thing.pos, herdTarget)
    elif randFloat(rng) < CowRandomMoveChance:
      desired = CardinalOffsets[randIntInclusive(rng, 0, 3)]

    env.tryMoveWildlife(thing, desired)

  # -------------------------------------------------------------------------
  # Wolf Movement (uses precomputed centers from above)
  # -------------------------------------------------------------------------
  for thing in env.thingsByKind[Wolf]:
    if thing.cooldown > 0:
      thing.cooldown -= 1

    # Handle scattered state - wolves move randomly after pack leader dies
    if thing.scatteredSteps > 0:
      thing.scatteredSteps -= 1
      # Scattered wolves wander randomly
      if randFloat(rng) < WolfScatteredMoveChance:
        let desired = CardinalOffsets[randIntInclusive(rng, 0, 3)]
        env.tryMoveWildlife(thing, desired)
      continue

    let pack = thing.packId
    let center = env.wolfPackCenters[pack]  # Use precomputed center
    let packTarget = env.wolfPackTargets[pack]
    let drift = env.wolfPackDrift[pack]
    let distFromCenter = max(abs(center.x - thing.pos.x), abs(center.y - thing.pos.y))
    var desired = ivec2(0, 0)
    if distFromCenter > WolfPackCohesionRadius:
      desired = stepToward(thing.pos, center)
    elif packTarget.x >= 0:
      let distToTarget = max(abs(packTarget.x - thing.pos.x), abs(packTarget.y - thing.pos.y))
      if distToTarget > 1:
        desired = stepToward(thing.pos, packTarget)
    elif (drift.x != 0 or drift.y != 0) and randFloat(rng) < WolfPackFollowChance:
      desired = stepToward(thing.pos, center + drift * 3)
    elif randFloat(rng) < WolfRandomMoveChance:
      desired = CardinalOffsets[randIntInclusive(rng, 0, 3)]

    env.tryMoveWildlife(thing, desired)

  # -------------------------------------------------------------------------
  # Bear Movement
  # -------------------------------------------------------------------------
  for thing in env.thingsByKind[Bear]:
    if thing.cooldown > 0:
      thing.cooldown -= 1
    let target = findNearestPredatorTargetSpatial(env, thing.pos, BearAggroRadius)
    var desired = ivec2(0, 0)
    if target.x >= 0:
      let dist = max(abs(target.x - thing.pos.x), abs(target.y - thing.pos.y))
      if dist > 1:
        desired = stepToward(thing.pos, target)
    elif randFloat(rng) < BearRandomMoveChance:
      desired = CardinalOffsets[randIntInclusive(rng, 0, 3)]

    env.tryMoveWildlife(thing, desired)

  # -------------------------------------------------------------------------
  # Predator Attacks (wolves and bears)
  # -------------------------------------------------------------------------
  for kind in [Wolf, Bear]:
    for predator in env.thingsByKind[kind]:
      block predatorAttack:
        var agentTarget: Thing = nil
        for offset in CardinalOffsets:
          let pos = predator.pos + offset
          if not isValidPos(pos):
            continue
          let target = env.getThing(pos)
          if isNil(target):
            continue
          if target.kind == Tumor and not target.hasClaimedTerritory:
            removeThing(env, target)
            break predatorAttack
          if target.kind == Agent and isAgentAlive(env, target) and agentTarget.isNil:
            agentTarget = target
        if not agentTarget.isNil:
          discard env.applyAgentDamage(agentTarget, max(1, predator.attackDamage))
