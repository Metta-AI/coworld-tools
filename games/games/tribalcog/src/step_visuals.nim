# Visual effects decay module - extracted from step.nim
# This file is included by step.nim
#
# All procs follow the same countdown decay pattern with in-place compaction.
# The pattern: decrement countdown, if > 0 keep in array, else remove.
# Using in-place compaction with setLen preserves seq capacity for pool reuse.

proc spawnProjectile(env: Environment, source, target: IVec2, kind: ProjectileKind) {.inline.} =
  ## Spawn a visual-only projectile from source to target.
  ## Lifetime scales with distance for natural flight speed.
  ## Uses pre-allocated pool to minimize heap allocations.
  let dist = max(abs(target.x - source.x), abs(target.y - source.y))
  if dist <= 0:
    return
  # Siege projectiles travel slower (more frames), arrows faster
  let lifetime = case kind
    of ProjMangonel: min(dist + ProjMangonelAddedFrames, ProjMangonelMaxLifetime).int8
    of ProjTrebuchet: min(dist + ProjTrebuchetAddedFrames, ProjTrebuchetMaxLifetime).int8
    else: min(dist + ProjArrowBaseLifetime, ProjArrowMaxLifetime).int8
  env.projectiles.add(Projectile(
    source: source, target: target, kind: kind,
    countdown: lifetime, lifetime: lifetime))
  env.projectilePool.stats.acquired += 1
  env.projectilePool.stats.poolSize = env.projectiles.len

proc stepDecayProjectiles(env: Environment) =
  ## Decay and remove expired projectiles.
  ## Uses in-place compaction - setLen preserves capacity for pool reuse.
  if env.projectiles.len > 0:
    var writeIdx = 0
    let startLen = env.projectiles.len
    for readIdx in 0 ..< env.projectiles.len:
      env.projectiles[readIdx].countdown -= 1
      if env.projectiles[readIdx].countdown > 0:
        env.projectiles[writeIdx] = env.projectiles[readIdx]
        inc writeIdx
    env.projectiles.setLen(writeIdx)
    # Track released projectiles for pool stats
    let released = startLen - writeIdx
    env.projectilePool.stats.released += released
    env.projectilePool.stats.poolSize = writeIdx

proc stepDecayDamageNumbers(env: Environment) =
  ## Decay and remove expired damage numbers.
  ## Uses in-place compaction - setLen preserves capacity for pool reuse.
  if env.damageNumbers.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.damageNumbers.len:
      env.damageNumbers[readIdx].countdown -= 1
      if env.damageNumbers[readIdx].countdown > 0:
        env.damageNumbers[writeIdx] = env.damageNumbers[readIdx]
        inc writeIdx
    env.damageNumbers.setLen(writeIdx)

proc stepRagdolls(env: Environment) =
  ## Update ragdoll physics and remove expired ragdolls.
  ## Applies velocity, gravity, friction, and rotation each frame.
  if env.ragdolls.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.ragdolls.len:
      var ragdoll = env.ragdolls[readIdx]
      ragdoll.countdown -= 1
      if ragdoll.countdown > 0:
        # Apply physics: velocity, gravity, friction, rotation
        ragdoll.pos.x += ragdoll.velocity.x
        ragdoll.pos.y += ragdoll.velocity.y
        ragdoll.velocity.y += RagdollGravity  # Gravity pulls "down" (positive Y)
        ragdoll.velocity.x *= RagdollFriction
        ragdoll.velocity.y *= RagdollFriction
        ragdoll.angle += ragdoll.angularVel
        ragdoll.angularVel *= RagdollFriction  # Angular friction
        env.ragdolls[writeIdx] = ragdoll
        inc writeIdx
    env.ragdolls.setLen(writeIdx)

proc stepDecayDebris(env: Environment) =
  ## Update debris particle positions and remove expired ones.
  ## Particles move outward with velocity and fade over time.
  if env.debris.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.debris.len:
      env.debris[readIdx].countdown -= 1
      if env.debris[readIdx].countdown > 0:
        # Update position based on velocity
        env.debris[readIdx].pos.x += env.debris[readIdx].velocity.x
        env.debris[readIdx].pos.y += env.debris[readIdx].velocity.y
        # Apply slight gravity/drag to velocity
        env.debris[readIdx].velocity.y += 0.005  # Gravity pulls down
        env.debris[readIdx].velocity.x *= 0.95   # Horizontal drag
        env.debris[writeIdx] = env.debris[readIdx]
        inc writeIdx
    env.debris.setLen(writeIdx)

proc stepDecaySpawnEffects(env: Environment) =
  ## Decay and remove expired spawn effects.
  ## Uses in-place compaction - setLen preserves capacity for pool reuse.
  if env.spawnEffects.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.spawnEffects.len:
      env.spawnEffects[readIdx].countdown -= 1
      if env.spawnEffects[readIdx].countdown > 0:
        env.spawnEffects[writeIdx] = env.spawnEffects[readIdx]
        inc writeIdx
    env.spawnEffects.setLen(writeIdx)

proc stepDecayDyingUnits(env: Environment) =
  ## Decay and remove expired dying unit animations.
  ## Uses in-place compaction - setLen preserves capacity for pool reuse.
  if env.dyingUnits.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.dyingUnits.len:
      env.dyingUnits[readIdx].countdown -= 1
      if env.dyingUnits[readIdx].countdown > 0:
        env.dyingUnits[writeIdx] = env.dyingUnits[readIdx]
        inc writeIdx
    env.dyingUnits.setLen(writeIdx)

proc stepDecayGatherSparkles(env: Environment) =
  ## Update gather sparkle particle positions and remove expired ones.
  ## Particles burst outward and fade over time.
  if env.gatherSparkles.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.gatherSparkles.len:
      env.gatherSparkles[readIdx].countdown -= 1
      if env.gatherSparkles[readIdx].countdown > 0:
        # Update position based on velocity
        env.gatherSparkles[readIdx].pos.x += env.gatherSparkles[readIdx].velocity.x
        env.gatherSparkles[readIdx].pos.y += env.gatherSparkles[readIdx].velocity.y
        # Apply slight deceleration (sparkles slow down as they expand)
        env.gatherSparkles[readIdx].velocity.x *= 0.92
        env.gatherSparkles[readIdx].velocity.y *= 0.92
        env.gatherSparkles[writeIdx] = env.gatherSparkles[readIdx]
        inc writeIdx
    env.gatherSparkles.setLen(writeIdx)

proc stepDecayConstructionDust(env: Environment) =
  ## Update construction dust particle positions and remove expired ones.
  ## Particles rise upward and fade over time.
  if env.constructionDust.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.constructionDust.len:
      env.constructionDust[readIdx].countdown -= 1
      if env.constructionDust[readIdx].countdown > 0:
        # Update position based on velocity (rising upward)
        env.constructionDust[readIdx].pos.x += env.constructionDust[readIdx].velocity.x
        env.constructionDust[readIdx].pos.y += env.constructionDust[readIdx].velocity.y
        # Dust slows down as it rises and spreads slightly
        env.constructionDust[readIdx].velocity.y *= 0.96
        env.constructionDust[readIdx].velocity.x *= 0.98
        env.constructionDust[writeIdx] = env.constructionDust[readIdx]
        inc writeIdx
    env.constructionDust.setLen(writeIdx)

proc stepDecayUnitTrails(env: Environment) =
  ## Update unit trail particle positions and remove expired ones.
  ## Trails drift slightly and fade over time.
  if env.unitTrails.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.unitTrails.len:
      env.unitTrails[readIdx].countdown -= 1
      if env.unitTrails[readIdx].countdown > 0:
        # Update position based on velocity (slight drift)
        env.unitTrails[readIdx].pos.x += env.unitTrails[readIdx].velocity.x
        env.unitTrails[readIdx].pos.y += env.unitTrails[readIdx].velocity.y
        # Trails settle quickly (reduce drift)
        env.unitTrails[readIdx].velocity.x *= 0.9
        env.unitTrails[readIdx].velocity.y *= 0.9
        env.unitTrails[writeIdx] = env.unitTrails[readIdx]
        inc writeIdx
    env.unitTrails.setLen(writeIdx)

proc stepDecayDustParticles(env: Environment) =
  ## Update dust particle positions and remove expired ones.
  ## Particles drift upward and fade out quickly.
  if env.dustParticles.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.dustParticles.len:
      env.dustParticles[readIdx].countdown -= 1
      if env.dustParticles[readIdx].countdown > 0:
        # Update position based on velocity (upward drift)
        env.dustParticles[readIdx].pos.x += env.dustParticles[readIdx].velocity.x
        env.dustParticles[readIdx].pos.y += env.dustParticles[readIdx].velocity.y
        # Slow down horizontal drift
        env.dustParticles[readIdx].velocity.x *= 0.85
        env.dustParticles[writeIdx] = env.dustParticles[readIdx]
        inc writeIdx
    env.dustParticles.setLen(writeIdx)

proc stepDecayWaterRipples(env: Environment) =
  ## Decay and remove expired water ripples.
  ## Ripples expand and fade over time.
  if env.waterRipples.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.waterRipples.len:
      env.waterRipples[readIdx].countdown -= 1
      if env.waterRipples[readIdx].countdown > 0:
        env.waterRipples[writeIdx] = env.waterRipples[readIdx]
        inc writeIdx
    env.waterRipples.setLen(writeIdx)

proc stepDecayAttackImpacts(env: Environment) =
  ## Update attack impact particle positions and remove expired ones.
  ## Particles burst outward and fade quickly.
  if env.attackImpacts.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.attackImpacts.len:
      env.attackImpacts[readIdx].countdown -= 1
      if env.attackImpacts[readIdx].countdown > 0:
        # Update position based on velocity
        env.attackImpacts[readIdx].pos.x += env.attackImpacts[readIdx].velocity.x
        env.attackImpacts[readIdx].pos.y += env.attackImpacts[readIdx].velocity.y
        # Apply drag to slow particles
        env.attackImpacts[readIdx].velocity.x *= 0.85
        env.attackImpacts[readIdx].velocity.y *= 0.85
        env.attackImpacts[writeIdx] = env.attackImpacts[readIdx]
        inc writeIdx
    env.attackImpacts.setLen(writeIdx)

proc stepDecayConversionEffects(env: Environment) =
  ## Update conversion effect countdowns and remove expired ones.
  ## Conversion effects display as pulsing glows on converted units.
  if env.conversionEffects.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.conversionEffects.len:
      env.conversionEffects[readIdx].countdown -= 1
      if env.conversionEffects[readIdx].countdown > 0:
        env.conversionEffects[writeIdx] = env.conversionEffects[readIdx]
        inc writeIdx
    env.conversionEffects.setLen(writeIdx)

proc stepDecayActionTints(env: Environment) =
  ## Decay short-lived action tints, removing expired ones
  if env.actionTintPositions.len > 0:
    var writeIdx = 0
    for readIdx in 0 ..< env.actionTintPositions.len:
      let pos = env.actionTintPositions[readIdx]
      if not isValidPos(pos):
        continue
      let x = pos.x
      let y = pos.y
      let countdown = env.actionTintCountdown[x][y]
      if countdown > 0:
        let next = countdown - 1
        env.actionTintCountdown[x][y] = next
        if next == 0:
          env.actionTintFlags[x][y] = false
          env.actionTintCode[x][y] = ActionTintNone
          env.updateObservations(TintLayer, pos, 0)
        env.actionTintPositions[writeIdx] = pos
        inc writeIdx
      else:
        env.actionTintFlags[x][y] = false
        env.actionTintCode[x][y] = ActionTintNone
        env.updateObservations(TintLayer, pos, 0)
    env.actionTintPositions.setLen(writeIdx)

proc stepDecayShields(env: Environment) =
  ## Decay shield countdown timers for all agents
  for i in 0 ..< MapAgents:
    if env.shieldCountdown[i] > 0:
      env.shieldCountdown[i] = env.shieldCountdown[i] - 1
