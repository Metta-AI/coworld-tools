# This file is included by src/step.nim
# Building combat module: tower/TC attacks and garrison logic

# Building attack visual tints (colors are display-only, not in constants.nim)
const
  TowerAttackTint = TileColor(r: 0.95, g: 0.70, b: 0.25, intensity: 1.10)
  CastleAttackTint = TileColor(r: 0.35, g: 0.25, b: 0.85, intensity: 1.15)
  TownCenterAttackTint = TileColor(r: 0.85, g: 0.50, b: 0.20, intensity: 1.12)

proc stepTryTowerAttack(env: Environment, tower: Thing, range: int,
                        towerRemovals: var HashSet[Thing]) =
  ## Have a tower attack the nearest valid target in range.
  ## University techs affect tower behavior:
  ## - Murder Holes: Allow attacking adjacent units (min range 0 instead of 1)
  ## - Arrowslits: +1 attack damage for towers
  ## - Heated Shot: +2 damage vs boats
  if tower.teamId < 0:
    return
  if not tower.constructed:
    return  # Incomplete buildings cannot fire

  # Murder Holes: allow attacking adjacent units (distance 1)
  # Without Murder Holes, towers have a "dead zone" at distance 1 (can't attack adjacent)
  let hasMurderHoles = env.hasUniversityTech(tower.teamId, TechMurderHoles)
  let minRange = if hasMurderHoles: 1 else: 2

  # Use spatial index for enemy agent lookup instead of scanning all agents
  var bestTarget = findNearestEnemyInRangeSpatial(env, tower.pos, tower.teamId, minRange, range)
  var bestDist = if bestTarget.isNil: int.high
                 else: chebyshevDist(bestTarget.pos, tower.pos).int
  # Use spatial query for Tumor/Spawner targets instead of O(n) scan
  for kind in [Tumor, Spawner]:
    let nearest = findNearestThingSpatial(env, tower.pos, kind, range)
    if not nearest.isNil:
      let dist = chebyshevDist(nearest.pos, tower.pos).int
      if dist >= minRange and dist < bestDist:
        bestDist = dist
        bestTarget = nearest
  if isNil(bestTarget):
    return
  let tint = if tower.kind == Castle: CastleAttackTint else: TowerAttackTint
  let tintCode = if tower.kind == Castle: ActionTintAttackCastle else: ActionTintAttackTower
  let tintDuration = if tower.kind == Castle: CastleAttackTintDuration else: TowerAttackTintDuration
  env.applyActionTint(bestTarget.pos, tint, tintDuration, tintCode)
  let projKind = if tower.kind == Castle: ProjCastleArrow else: ProjTowerArrow
  env.spawnProjectile(tower.pos, bestTarget.pos, projKind)

  # Calculate tower damage with University tech bonuses
  var damage = tower.attackDamage

  # Arrowslits: +1 tower attack damage (only for GuardTower, not Castle)
  if tower.kind == GuardTower and env.hasUniversityTech(tower.teamId, TechArrowslits):
    damage += 1

  # Castle unique tech bonuses for tower/castle attack
  # Crenellations (Team 1 Imperial): +2 castle attack
  if tower.kind == Castle and env.hasCastleTech(tower.teamId, CastleTechCrenellations):
    damage += 2
  # Crenellations2 (Team 4 Imperial): +2 castle attack
  if tower.kind == Castle and env.hasCastleTech(tower.teamId, CastleTechCrenellations2):
    damage += 2
  # Artillery (Team 7 Imperial): +2 tower and castle attack
  if tower.kind in {GuardTower, Castle} and env.hasCastleTech(tower.teamId, CastleTechArtillery):
    damage += 2

  # Apply damage to base target (nearest enemy)
  template applyTowerHit(target: Thing) =
    case target.kind
    of Agent:
      var targetDamage = damage
      # Heated Shot: +2 damage vs boats
      if target.isWaterUnit and env.hasUniversityTech(tower.teamId, TechHeatedShot):
        targetDamage += 2
      # Greek Fire (Team 2 Castle): +2 tower attack vs siege
      if target.unitClass in {UnitBatteringRam, UnitMangonel, UnitTrebuchet} and
          env.hasCastleTech(tower.teamId, CastleTechGreekFire):
        targetDamage += 2
      when defined(combatAudit):
        let towerDmg = max(1, targetDamage)
        let tgtTeam = getTeamId(target)
        recordDamage(env.currentStep, tower.teamId, tgtTeam, -1, target.agentId,
                     towerDmg, $tower.kind, $target.unitClass, "tower")
        let died = env.applyAgentDamage(target, max(1, targetDamage))
        if died:
          recordKill(env.currentStep, tower.teamId, getTeamId(target),
                     -1, target.agentId, $tower.kind, $target.unitClass)
      else:
        discard env.applyAgentDamage(target, max(1, targetDamage))
    of Tumor, Spawner:
      if target notin towerRemovals:
        towerRemovals.incl(target)
    else:
      discard

  applyTowerHit(bestTarget)

  # Garrisoned units add extra arrows to building attacks (round-robin across all targets)
  let garrisonCount = tower.garrisonedUnits.len
  if garrisonCount > 0:
    let bonusArrows = garrisonCount * GarrisonArrowBonus
    # Reuse env temp buffer to avoid per-call heap allocation
    env.tempTowerTargets.setLen(0)
    collectEnemiesInRangeSpatial(env, tower.pos, tower.teamId, range, env.tempTowerTargets)
    # Filter by minRange in-place (swap-and-pop) to avoid second allocation
    if minRange > 1:
      var i = 0
      while i < env.tempTowerTargets.len:
        if chebyshevDist(env.tempTowerTargets[i].pos, tower.pos) < minRange:
          env.tempTowerTargets[i] = env.tempTowerTargets[^1]
          env.tempTowerTargets.setLen(env.tempTowerTargets.len - 1)
        else:
          inc i
    # Use spatial query for Tumor/Spawner targets instead of O(n) scan
    for kind in [Tumor, Spawner]:
      collectThingsInRangeSpatial(env, tower.pos, kind, range, env.tempTowerTargets)
    # Filter Tumor/Spawner by minRange after collection (spatial query doesn't support minRange)
    if minRange > 1 and env.tempTowerTargets.len > 0:
      var i = 0
      while i < env.tempTowerTargets.len:
        if env.tempTowerTargets[i].kind in {Tumor, Spawner} and
           chebyshevDist(env.tempTowerTargets[i].pos, tower.pos) < minRange:
          env.tempTowerTargets[i] = env.tempTowerTargets[^1]
          env.tempTowerTargets.setLen(env.tempTowerTargets.len - 1)
        else:
          inc i
    if env.tempTowerTargets.len > 0:
      for i in 0 ..< bonusArrows:
        let bonusTarget = env.tempTowerTargets[i mod env.tempTowerTargets.len]
        # Skip targets killed by earlier arrows in this volley
        if bonusTarget.kind == Agent and not isAgentAlive(env, bonusTarget):
          continue
        env.applyActionTint(bonusTarget.pos, tint, tintDuration, tintCode)
        env.spawnProjectile(tower.pos, bonusTarget.pos, projKind)
        applyTowerHit(bonusTarget)

proc stepTryTownCenterAttack(env: Environment, tc: Thing,
                              towerRemovals: var HashSet[Thing]) =
  ## Have a Town Center attack enemies in range. Garrisoned units add extra arrows.
  ## Each garrisoned unit fires one additional arrow at a unique target.
  if tc.teamId < 0:
    return
  if not tc.constructed:
    return  # Incomplete buildings cannot fire

  # Gather all valid targets in range using spatial index
  # Reuse env temp buffer to avoid per-call heap allocation
  env.tempTCTargets.setLen(0)
  collectEnemiesInRangeSpatial(env, tc.pos, tc.teamId, TownCenterRange, env.tempTCTargets)
  # Use spatial query for Tumor/Spawner targets instead of O(n) scan
  for kind in [Tumor, Spawner]:
    collectThingsInRangeSpatial(env, tc.pos, kind, TownCenterRange, env.tempTCTargets)

  if env.tempTCTargets.len == 0:
    return

  # Calculate number of arrows: base damage + 1 per garrisoned unit
  let garrisonCount = tc.garrisonedUnits.len
  let arrowCount = 1 + garrisonCount * GarrisonArrowBonus

  # Fire arrows at targets (round-robin if more arrows than targets)
  for i in 0 ..< arrowCount:
    let targetIdx = i mod env.tempTCTargets.len
    let target = env.tempTCTargets[targetIdx]
    # Skip targets killed by earlier arrows in this volley
    if target.kind == Agent and not isAgentAlive(env, target):
      continue
    env.applyActionTint(target.pos, TownCenterAttackTint, TownCenterAttackTintDuration,
                        ActionTintAttackTower)
    env.spawnProjectile(tc.pos, target.pos, ProjTowerArrow)
    case target.kind
    of Agent:
      when defined(combatAudit):
        let tcDmg = max(1, tc.attackDamage)
        let tcTgtTeam = getTeamId(target)
        recordDamage(env.currentStep, tc.teamId, tcTgtTeam, -1, target.agentId,
                     tcDmg, "TownCenter", $target.unitClass, "tower")
        let tcDied = env.applyAgentDamage(target, max(1, tc.attackDamage))
        if tcDied:
          recordKill(env.currentStep, tc.teamId, getTeamId(target),
                     -1, target.agentId, "TownCenter", $target.unitClass)
      else:
        discard env.applyAgentDamage(target, max(1, tc.attackDamage))
    of Tumor, Spawner:
      if target notin towerRemovals:
        towerRemovals.incl(target)
    else:
      discard

proc garrisonCapacity*(kind: ThingKind): int =
  ## Returns the garrison capacity for a building type, or 0 if it cannot garrison.
  case kind
  of TownCenter: TownCenterGarrisonCapacity
  of Castle: CastleGarrisonCapacity
  of GuardTower: GuardTowerGarrisonCapacity
  of House: HouseGarrisonCapacity
  else: 0

proc garrisonUnitInBuilding*(env: Environment, unit: Thing, building: Thing): bool =
  ## Garrison a unit inside a building. Returns true if successful.
  let capacity = garrisonCapacity(building.kind)
  if capacity == 0:
    return false
  if building.garrisonedUnits.len >= capacity:
    return false
  if not isAgentAlive(env, unit):
    return false
  if getTeamId(unit) != building.teamId:
    return false

  # Remove unit from the grid and spatial index
  env.grid[unit.pos.x][unit.pos.y] = nil
  env.updateObservations(AgentLayer, unit.pos, 0)
  env.updateObservations(AgentOrientationLayer, unit.pos, 0)
  removeFromSpatialIndex(env, unit)

  # Add to garrison
  building.garrisonedUnits.add(unit)
  unit.pos = ivec2(-1, -1)  # Mark as off-grid
  unit.isGarrisoned = true
  true

proc ungarrisonAllUnits*(env: Environment, building: Thing): seq[Thing] =
  ## Ungarrison all units from a building, placing them around it. Returns ungarrisoned units.
  result = newSeqOfCap[Thing](building.garrisonedUnits.len)
  if building.garrisonedUnits.len == 0:
    return

  # Find empty tiles around the building (5x5 grid minus center = 24 max)
  # Reuse env temp buffer to avoid per-call heap allocation
  env.tempEmptyTiles.setLen(0)
  for dy in -2 .. 2:
    for dx in -2 .. 2:
      if dx == 0 and dy == 0:
        continue
      let pos = building.pos + ivec2(dx.int32, dy.int32)
      if not isValidPos(pos):
        continue
      if not env.isEmpty(pos):
        continue
      if env.terrain[pos.x][pos.y] == Water:
        continue
      env.tempEmptyTiles.add(pos)

  var tileIdx = 0
  for unit in building.garrisonedUnits:
    if tileIdx >= env.tempEmptyTiles.len:
      break  # No more space, remaining units stay garrisoned
    let pos = env.tempEmptyTiles[tileIdx]
    unit.pos = pos
    unit.isGarrisoned = false
    env.grid[pos.x][pos.y] = unit
    addToSpatialIndex(env, unit)
    env.updateObservations(AgentLayer, pos, getTeamId(unit) + 1)
    env.updateObservations(AgentOrientationLayer, pos, unit.orientation.int)
    result.add(unit)
    inc tileIdx

  # Remove ungarrisoned units from the list
  building.garrisonedUnits = building.garrisonedUnits[result.len .. ^1]
