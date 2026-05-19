## Visual effects and particle rendering helpers.

import
  boxy, pixie, vmath,
  common, environment, label_cache, renderer_core

const
  Pi = 3.14159265'f32              # π for trigonometric calculations
  TwoPi = 6.28318530'f32           # 2π for full-cycle sine waves

  SmokeParticleCount = 3           # Number of smoke particles per building
  SmokeParticleScale = 1.0 / 500.0 # Smaller than sprites for wispy look
  SmokeBaseHeight = -0.4           # Start position above building center
  SmokeMaxHeight = 1.2             # How high particles rise
  SmokeAnimSpeed = 12              # Frames per animation cycle
  SmokeDriftAmount = 0.15          # Horizontal drift amplitude
  SmokeMaxAlpha = 0.6'f32          # Maximum opacity for smoke particles
  SmokeExpansionRate = 0.5'f32     # How much particles expand as they rise
  SmokeGrayVariation = 0.1'f32     # Gray tint variation per particle
  SmokeDriftFrameRate = 0.05'f32   # Frame-based phase contribution to drift
  SmokeDriftPhaseRate = 0.1'f32    # Phase offset contribution to drift
  SmokeDriftParticleSpread = 2.1'f32 # Per-particle phase spread for drift variety

  WeatherParticleDensity = 0.015   # Particles per tile (0.015 = ~1 particle per 67 tiles)
  WeatherParticleScale = 1.0 / 600.0  # Small particles for weather

  RainFallSpeed = 0.25'f32         # World units per frame (downward)
  RainDriftSpeed = 0.03'f32        # Slight horizontal drift
  RainCycleFrames = 48             # Frames for one full rain cycle
  RainAlpha = 0.5'f32              # Rain particle opacity
  RainStreakLength = 3             # Number of particles per streak
  RainPatchTileSize = 18           # World-space cell size for localized rainy patches
  RainPatchChancePercent = 48      # Chance a weather cell contains a raining cloud
  RainPatchMinRadius = 4.0'f32     # Minimum rain patch radius (tiles)
  RainPatchRadiusJitter = 3.0'f32  # Additional radius variation
  RainCloudPuffCount = 4           # Cloud puffs per active patch
  RainCloudAlpha = 0.16'f32        # Cloud puff opacity
  RainCloudScale = 1.0 / 130.0     # Cloud puff sprite scale
  RainCloudMinDist = 0.15'f32      # Minimum cloud puff distance from center
  RainCloudYOffsetMult = 0.75'f32  # Cloud Y offset radius multiplier
  RainCloudYJitterMult = 0.18'f32  # Cloud Y sine jitter amplitude
  RainCloudAlphaBase = 0.75'f32    # Cloud puff alpha variation base
  RainPatchDriftSpeed = 0.004'f32  # Rain patch drift animation speed
  RainPatchDriftPhaseJitter = 0.1'f32 # Phase offset jitter per cell
  RainPatchDriftXAmplitude = 0.7'f32  # X drift amplitude in tiles
  RainPatchDriftYFreqMult = 0.73'f32  # Y drift frequency multiplier
  RainPatchDriftYAmplitude = 0.35'f32 # Y drift amplitude in tiles
  RainXSpreadMult = 0.9'f32        # X noise spread as fraction of radius
  RainYStartOffset = 1.15'f32      # Rain starts this far above patch center
  RainYNoiseMult = 0.35'f32        # Y noise spread as fraction of radius
  RainFallDistMult = 2.25'f32      # Fall distance multiplier relative to radius
  RainFallDistBase = 2.0'f32       # Base fall distance in tiles
  RainEllipseYMult = 1.2'f32       # Y axis ellipse multiplier for containment
  RainEllipseThreshold = 1.35'f32  # Ellipse boundary cutoff for containment
  RainBlueBase = 0.7'f32           # Base blue channel for rain color
  RainStreakSpacingMult = 2.0'f32   # Streak particle spacing multiplier

  WindBlowSpeed = 0.18'f32         # World units per frame (horizontal)
  WindDriftSpeed = 0.02'f32        # Vertical drift
  WindCycleFrames = 64             # Frames for one full wind cycle
  WindAlpha = 0.35'f32             # Wind particle opacity (subtle)
  WindDriftAmplitude = 4.0'f32     # Vertical drift amplitude multiplier

  SnowFallSpeed = 0.08'f32         # World units per frame (slow descent)
  SnowDriftSpeed = 0.04'f32        # Horizontal sway amplitude
  SnowDriftFreq = 0.03'f32         # Sway frequency (slow sinusoidal)
  SnowCycleFrames = 96             # Frames for one full snow cycle (slower than rain)
  SnowAlpha = 0.7'f32              # Snow particle opacity (visible white)
  SnowParticleScale = 1.0 / 500.0  # Small snowflake particles

  WeatherViewportMargin = 2.0'f32  # Extra margin around viewport for seamless edges
  WeatherViewportClipMargin = 1.0'f32 # Clip margin for wind particle culling
  RainFallbackRadiusExtra = 1.5'f32 # Extra radius added to fallback rain patch
  RainNoiseCenterOffset = 0.5'f32  # Center offset for y-axis noise distribution

  DamageNumberFontPath = "data/Inter-Regular.ttf"
  DamageNumberFontSize: float32 = 28
  DamageNumberFloatHeight: float32 = 0.8  # World units to float upward
  DamageNumberOutlineWidth = 2.0'f32       # Outline stroke width for damage labels
  DamageNumberLabelScale = 1.0 / 200.0     # World-space scale for damage labels

  ProjectileTrailMaxAlpha = 0.7'f32  # Max opacity for trail points (70%)
  ProjectileTrailMinScale = 0.5'f32  # Trail shrinks to 50% at tail end

  DebrisParticleScale = 1.0 / 350.0  # Slightly smaller than projectiles

  SpawnEffectScaleMin = 0.3'f32      # Starting scale fraction (30%)
  SpawnEffectScaleRange = 0.7'f32    # Scale range from min to full (70%)
  SpawnEffectMaxAlpha = 0.6'f32      # Max alpha to avoid being too bright
  SpawnEffectRotationSpeed = TwoPi   # Full rotation over effect lifetime

  GatherSparkleScale = 1.0 / 450.0   # Small sparkle particles
  GatherSparkleMaxAlpha = 0.8'f32    # Max sparkle opacity
  GatherSparkleScaleMin = 0.5'f32    # Min scale fraction

  ConstructionDustScale = 1.0 / 400.0 # Scale for dust particles
  ConstructionDustMaxAlpha = 0.5'f32  # Max dust opacity
  ConstructionDustScaleBase = 0.7'f32 # Base scale fraction
  ConstructionDustScaleRange = 0.3'f32 # Scale variation range

  UnitTrailScale = 1.0 / 500.0       # Small trail dots
  UnitTrailMaxAlpha = 0.4'f32        # Trail max opacity

  WalkingDustScale = 1.0 / 600.0     # Small walking dust particles
  WalkingDustMaxAlpha = 0.6'f32      # Max walking dust opacity
  WalkingDustScaleMin = 0.5'f32      # Min scale fraction

  RippleScaleMin = 0.2'f32           # Starting ripple scale (20%)
  RippleScaleRange = 0.8'f32         # Ripple scale range (80%)
  RippleMaxAlpha = 0.5'f32           # Max ripple opacity (subtle)

  AttackImpactScale = 1.0 / 400.0    # Impact particle scale
  AttackImpactMaxAlpha = 0.9'f32     # Impact max opacity (punchy)
  AttackImpactScaleMin = 0.3'f32     # Min scale fraction
  AttackImpactScaleRange = 0.7'f32   # Scale range

  ConversionPulseFreq = 2.0'f32      # Number of pulses over lifetime
  ConversionAlphaBlend = 0.8'f32     # Alpha multiplier for color blending
  ConversionBaseScale = 1.0 / 400.0  # Base scale for conversion ring
  ConversionExpandMult = 1.5'f32     # Expansion multiplier as effect fades
  ConversionAlphaBase = 0.5'f32      # Base alpha contribution (before pulse modulation)
  ConversionAlphaPulseRange = 0.5'f32 # Additional alpha from pulse (0 to this value)

proc getDamageNumberLabel(amount: int, kind: DamageNumberKind): (string, IVec2) =
  ## Get or create a cached damage number label image.
  let textColor = case kind
    of DmgNumDamage: DmgColorDamage
    of DmgNumHeal: DmgColorHeal
    of DmgNumCritical: DmgColorCritical
  let prefix = case kind
    of DmgNumDamage: "d"
    of DmgNumHeal: "h"
    of DmgNumCritical: "c"
  let style = labelStyle(
    DamageNumberFontPath,
    DamageNumberFontSize,
    DamageNumberOutlineWidth,
    0.0,
    textColor,
    true
  )
  let cached = ensureLabel("dmgnum", prefix & $amount, style)
  return (cached.imageKey, cached.size)

const
  ProjArrowScale = (1.0 / 400.0).float32      # Small arrow
  ProjLongbowScale = (1.0 / 380.0).float32    # Slightly larger arrow
  ProjJanissaryScale = (1.0 / 350.0).float32  # Medium projectile
  ProjTowerArrowScale = (1.0 / 380.0).float32 # Tower arrow (small)
  ProjCastleArrowScale = (1.0 / 350.0).float32 # Castle arrow (medium)
  ProjMangonelScale = (1.0 / 280.0).float32   # Large siege projectile
  ProjTrebuchetScale = (1.0 / 240.0).float32  # Very large siege projectile

  ProjectileColors: array[ProjectileKind, Color] = [
    ProjArrowColor,       # ProjArrow - brown
    ProjLongbowColor,     # ProjLongbow - darker brown
    ProjJanissaryColor,   # ProjJanissary - yellow
    ProjTowerArrowColor,  # ProjTowerArrow - brown
    ProjCastleArrowColor, # ProjCastleArrow - tan
    ProjMangonelColor,    # ProjMangonel - gray
    ProjTrebuchetColor,   # ProjTrebuchet - dark gray
  ]

  ProjectileScales: array[ProjectileKind, float32] = [
    ProjArrowScale,        # ProjArrow - small
    ProjLongbowScale,      # ProjLongbow - slightly larger
    ProjJanissaryScale,    # ProjJanissary - medium
    ProjTowerArrowScale,   # ProjTowerArrow - small
    ProjCastleArrowScale,  # ProjCastleArrow - medium
    ProjMangonelScale,     # ProjMangonel - large
    ProjTrebuchetScale,    # ProjTrebuchet - very large
  ]

  ProjectileTrailPoints = 5     # Number of trail segments behind projectile
  ProjectileTrailStep = 0.12'f32  # Time step between trail points (fraction of lifetime)

const DebrisColors: array[DebrisKind, Color] = [
  DebrisWoodColor,   # DebrisWood - brown
  DebrisStoneColor,  # DebrisStone - gray
  DebrisBrickColor,  # DebrisBrick - terracotta/orange-brown
]

proc drawBuildingSmoke*(buildingPos: Vec2, buildingId: int) =
  ## Draw procedural smoke particles rising from an active building.
  ## Uses deterministic noise based on frame and building ID for consistent animation.
  for i in 0 ..< SmokeParticleCount:
    let phase = (buildingId * 7 + i * 13) mod 100
    let cycleFrame = (frame + phase * 3) mod (SmokeAnimSpeed * SmokeParticleCount)

    let particleCycle = (cycleFrame + i * SmokeAnimSpeed) mod (SmokeAnimSpeed * SmokeParticleCount)
    let t = particleCycle.float32 / (SmokeAnimSpeed * SmokeParticleCount).float32

    let rise = t * t * SmokeMaxHeight

    let driftPhase = (frame.float32 * SmokeDriftFrameRate + phase.float32 * SmokeDriftPhaseRate + i.float32 * SmokeDriftParticleSpread)
    let drift = sin(driftPhase) * SmokeDriftAmount * t

    let particlePos = buildingPos + vec2(drift, SmokeBaseHeight - rise)

    let alpha = (1.0 - t) * SmokeMaxAlpha

    let sizeScale = SmokeParticleScale * (1.0 + t * SmokeExpansionRate)

    let grayVal = SmokeBaseGray + (i.float32 * SmokeGrayVariation)
    let smokeTint = color(grayVal, grayVal, grayVal, alpha)

    bxy.drawImage("floor", particlePos, angle = 0, scale = sizeScale, tint = smokeTint)

proc drawProjectiles*() =
  ## Draw visual-only projectiles traveling from source to target.
  ## Renders a trail of fading points behind the projectile head.
  for proj in env.projectiles:
    if proj.lifetime <= 0:
      continue
    # Interpolate position: t=1 at source, t=0 at target
    let t = proj.countdown.float32 / proj.lifetime.float32
    let c = ProjectileColors[proj.kind]
    let sc = ProjectileScales[proj.kind]
    let srcX = proj.source.x.float32
    let srcY = proj.source.y.float32
    let tgtX = proj.target.x.float32
    let tgtY = proj.target.y.float32

    for i in countdown(ProjectileTrailPoints - 1, 0):
      let trailT = t + ProjectileTrailStep * (i + 1).float32
      if trailT > 1.0:
        continue
      let trailPos = vec2(
        srcX * trailT + tgtX * (1.0 - trailT),
        srcY * trailT + tgtY * (1.0 - trailT))
      let fadeRatio = 1.0 - (i + 1).float32 / (ProjectileTrailPoints + 1).float32
      let trailAlpha = c.a * fadeRatio * ProjectileTrailMaxAlpha
      let trailScale = sc * (ProjectileTrailMinScale + ProjectileTrailMinScale * fadeRatio)
      let trailColor = withAlpha(c, trailAlpha)
      bxy.drawImage("floor", trailPos, angle = 0, scale = trailScale, tint = trailColor)

    let pos = vec2(srcX * t + tgtX * (1.0 - t), srcY * t + tgtY * (1.0 - t))
    bxy.drawImage("floor", pos, angle = 0, scale = sc, tint = c)

proc drawDamageNumbers*() =
  ## Draw floating damage numbers for combat feedback.
  ## Numbers float upward and fade out over their lifetime.
  if not currentViewport.valid:
    return
  for dmg in env.damageNumbers:
    if dmg.lifetime <= 0 or not isInViewport(dmg.pos):
      continue
    # Calculate progress (1.0 at spawn, 0.0 at expire)
    let t = dmg.countdown.float32 / dmg.lifetime.float32
    # Float upward as time progresses
    let floatOffset = (1.0 - t) * DamageNumberFloatHeight
    let worldPos = vec2(dmg.pos.x.float32, dmg.pos.y.float32 - floatOffset)
    # Fade out
    let alpha = t * t  # Quadratic ease for smoother fade
    let (imageKey, _) = getDamageNumberLabel(dmg.amount, dmg.kind)
    # Scale for world-space rendering (similar to HP bars)
    let scale = DamageNumberLabelScale
    bxy.drawImage(imageKey, worldPos, angle = 0, scale = scale,
                  tint = withAlpha(TintWhite, alpha))

proc drawRagdolls*() =
  ## Draw ragdoll death bodies with physics-based tumbling.
  ## Bodies tumble away from damage source and fade out.
  if not currentViewport.valid:
    return
  for ragdoll in env.ragdolls:
    if ragdoll.lifetime <= 0:
      continue
    # Check viewport bounds using integer position
    let ipos = ivec2(ragdoll.pos.x.int32, ragdoll.pos.y.int32)
    if not isInViewport(ipos):
      continue
    # Get sprite key for the unit class
    let baseKey = UnitClassSpriteKeys[ragdoll.unitClass]
    # Fall back to villager sprites for villager-like units
    let spriteKey = if baseKey.len > 0 and baseKey & ".s" in bxy:
      baseKey & ".s"  # Use south-facing sprite as death pose
    elif "oriented/gatherer.s" in bxy:
      "oriented/gatherer.s"  # Fallback for villagers
    else:
      ""
    if spriteKey.len == 0:
      continue
    # Calculate alpha fade (quadratic ease for smoother fade)
    let t = ragdoll.countdown.float32 / ragdoll.lifetime.float32
    let alpha = t * t
    # Get team color with alpha applied
    let teamColor = getTeamColor(env, ragdoll.teamId)
    let tint = withAlpha(teamColor, alpha)
    # Draw with rotation
    bxy.drawImage(spriteKey, ragdoll.pos, angle = ragdoll.angle, scale = SpriteScale, tint = tint)

proc drawDebris*() =
  ## Draw debris particles from destroyed buildings.
  ## Particles move outward and fade out over their lifetime.
  if not currentViewport.valid:
    return
  for deb in env.debris:
    if deb.lifetime <= 0:
      continue
    # Check viewport bounds (convert float pos to int for check)
    let ipos = ivec2(deb.pos.x.int32, deb.pos.y.int32)
    if not isInViewport(ipos):
      continue
    # Calculate progress (1.0 at spawn, 0.0 at expire)
    let t = deb.countdown.float32 / deb.lifetime.float32
    # Fade out
    let alpha = t * t  # Quadratic ease for smoother fade
    let baseColor = DebrisColors[deb.kind]
    let tintColor = withAlpha(baseColor, alpha)
    # Draw as small colored dot using floor sprite
    let scale = DebrisParticleScale.float32
    bxy.drawImage("floor", deb.pos, angle = 0, scale = scale, tint = tintColor)

proc drawSpawnEffects*() =
  ## Draw visual effects for unit spawning from buildings.
  ## Shows an expanding, fading glow at the spawn location.
  if not currentViewport.valid:
    return
  for effect in env.spawnEffects:
    if effect.lifetime <= 0 or not isInViewport(effect.pos):
      continue
    # Calculate progress (1.0 at spawn, 0.0 at expire)
    let t = effect.countdown.float32 / effect.lifetime.float32
    let progress = 1.0 - t  # 0.0 at spawn, 1.0 at expire
    # Expand from small to large as effect progresses
    let baseScale = SpriteScale * (SpawnEffectScaleMin + progress * SpawnEffectScaleRange)
    # Fade out with quadratic ease (bright at start, fades smoothly)
    let alpha = t * t * SpawnEffectMaxAlpha
    # Rotate during expansion for visual flair
    let rotation = progress * SpawnEffectRotationSpeed
    # Use a bright cyan/white tint for spawn effect
    let tint = withAlpha(SpawnEffectTint, alpha)
    bxy.drawImage("floor", effect.pos.vec2, angle = rotation, scale = baseScale, tint = tint)

proc drawGatherSparkles*() =
  ## Draw sparkle particles when workers collect resources.
  ## Golden particles burst outward and fade out over their lifetime.
  if not currentViewport.valid:
    return
  for sparkle in env.gatherSparkles:
    if sparkle.lifetime <= 0:
      continue
    # Check viewport bounds (convert float pos to int for check)
    let ipos = ivec2(sparkle.pos.x.int32, sparkle.pos.y.int32)
    if not isInViewport(ipos):
      continue
    # Calculate progress (1.0 at spawn, 0.0 at expire)
    let t = sparkle.countdown.float32 / sparkle.lifetime.float32
    # Fade out with quadratic ease
    let alpha = t * t * GatherSparkleMaxAlpha
    # Golden sparkle color
    let tintColor = withAlpha(GatherSparkleTint, alpha)
    # Small particles
    let scale = GatherSparkleScale.float32 * (GatherSparkleScaleMin + t * GatherSparkleScaleMin)
    bxy.drawImage("floor", sparkle.pos, angle = 0, scale = scale, tint = tintColor)

proc drawConstructionDust*() =
  ## Draw dust particles at construction sites.
  ## Brown/tan particles rise and spread out as they fade.
  if not currentViewport.valid:
    return
  for dust in env.constructionDust:
    if dust.lifetime <= 0:
      continue
    # Check viewport bounds
    let ipos = ivec2(dust.pos.x.int32, dust.pos.y.int32)
    if not isInViewport(ipos):
      continue
    # Calculate progress
    let t = dust.countdown.float32 / dust.lifetime.float32
    # Fade out
    let alpha = t * t * ConstructionDustMaxAlpha
    # Dusty brown color
    let tintColor = withAlpha(ConstructionDustTint, alpha)
    # Particles that grow slightly as they rise
    let scale = ConstructionDustScale.float32 * (ConstructionDustScaleBase + (1.0 - t) * ConstructionDustScaleRange)
    bxy.drawImage("floor", dust.pos, angle = 0, scale = scale, tint = tintColor)

proc drawUnitTrails*() =
  ## Draw movement trails behind fast-moving units.
  ## Fading afterimages showing recent movement path.
  if not currentViewport.valid:
    return
  for trail in env.unitTrails:
    if trail.lifetime <= 0:
      continue
    # Check viewport bounds
    let ipos = ivec2(trail.pos.x.int32, trail.pos.y.int32)
    if not isInViewport(ipos):
      continue
    # Calculate progress
    let t = trail.countdown.float32 / trail.lifetime.float32
    # Fade out quickly
    let alpha = t * t * UnitTrailMaxAlpha
    # Light team-colored trail
    let teamColor = getTeamColor(env, trail.teamId)
    let tintColor = withAlpha(teamColor, alpha)
    # Small trail dots
    let scale = UnitTrailScale.float32
    bxy.drawImage("floor", trail.pos, angle = 0, scale = scale, tint = tintColor)

proc drawDustParticles*() =
  ## Draw dust particles kicked up by walking units.
  ## Color varies based on terrain type.
  if not currentViewport.valid:
    return
  for dust in env.dustParticles:
    if dust.lifetime <= 0:
      continue
    # Check viewport bounds
    let ipos = ivec2(dust.pos.x.int32, dust.pos.y.int32)
    if not isInViewport(ipos):
      continue
    # Calculate progress (1.0 at spawn, 0.0 at expire)
    let t = dust.countdown.float32 / dust.lifetime.float32
    # Fade out with quadratic ease
    let alpha = t * t * WalkingDustMaxAlpha
    # Color based on terrain type
    let dustBase = case dust.terrainColor
      of 0: DustSandColor
      of 1: DustSnowColor
      of 2: DustMudColor
      of 3: DustGrassColor
      of 4: DustRoadColor
      else: DustDefaultColor
    let tintColor = withAlpha(dustBase, alpha)
    # Small particles that shrink slightly as they fade
    let scale = WalkingDustScale.float32 * (WalkingDustScaleMin + t * WalkingDustScaleMin)
    bxy.drawImage("floor", dust.pos, angle = 0, scale = scale, tint = tintColor)

proc drawWaterRipples*() =
  ## Draw ripple effects when units walk through water.
  ## Expanding rings that fade out over their lifetime.
  if not currentViewport.valid:
    return
  for ripple in env.waterRipples:
    if ripple.lifetime <= 0:
      continue
    # Check viewport bounds (convert float pos to int for check)
    let ipos = ivec2(ripple.pos.x.int32, ripple.pos.y.int32)
    if not isInViewport(ipos):
      continue
    # Calculate progress (1.0 at spawn, 0.0 at expire)
    let t = ripple.countdown.float32 / ripple.lifetime.float32
    let progress = 1.0 - t  # 0.0 at spawn, 1.0 at expire
    # Expand from small to large as effect progresses
    let baseScale = SpriteScale * (RippleScaleMin + progress * RippleScaleRange)
    # Fade out with quadratic ease (visible at start, fades smoothly)
    let alpha = t * t * RippleMaxAlpha
    # Use a light cyan/blue tint for water ripple
    let tint = withAlpha(RippleTint, alpha)
    bxy.drawImage("floor", ripple.pos, angle = 0, scale = baseScale, tint = tint)

proc drawAttackImpacts*() =
  ## Draw attack impact burst particles when attacks hit targets.
  ## Particles radiate outward and fade quickly for a sharp impact effect.
  if not currentViewport.valid:
    return
  for impact in env.attackImpacts:
    if impact.lifetime <= 0:
      continue
    # Check viewport bounds (convert float pos to int for check)
    let ipos = ivec2(impact.pos.x.int32, impact.pos.y.int32)
    if not isInViewport(ipos):
      continue
    # Calculate progress (1.0 at spawn, 0.0 at expire)
    let t = impact.countdown.float32 / impact.lifetime.float32
    # Fade out quickly with quadratic ease for punchy effect
    let alpha = t * t * AttackImpactMaxAlpha
    # Orange/red impact color for combat feedback
    let tintColor = withAlpha(AttackImpactTint, alpha)
    # Small particles that shrink as they fade
    let scale = AttackImpactScale.float32 * (AttackImpactScaleMin + t * AttackImpactScaleRange)
    bxy.drawImage("floor", impact.pos, angle = 0, scale = scale, tint = tintColor)

proc drawConversionEffects*() =
  ## Draw pulsing glow effects when monks convert enemy units.
  ## Displays as a golden/team-colored radial glow that pulses and fades.
  if not currentViewport.valid:
    return
  for effect in env.conversionEffects:
    if effect.lifetime <= 0:
      continue
    # Check viewport bounds
    let ipos = ivec2(effect.pos.x.int32, effect.pos.y.int32)
    if not isInViewport(ipos):
      continue
    # Calculate progress (1.0 at spawn, 0.0 at expire)
    let t = effect.countdown.float32 / effect.lifetime.float32
    # Pulsing effect: sine wave for divine/spiritual feel (2 pulses over lifetime)
    let pulse = (sin(t * TwoPi * ConversionPulseFreq) + 1.0) * 0.5  # 0 to 1
    # Fade out over time with pulsing intensity
    let alpha = t * (ConversionAlphaBase + pulse * ConversionAlphaPulseRange)
    # Blend between golden divine color and team color
    let golden = withAlpha(ConversionGoldenTint, alpha)
    let teamAlpha = effect.teamColor
    let blendT = 1.0 - t  # More team color as time progresses
    let tintColor = color(
      golden.r * (1.0 - blendT) + teamAlpha.r * blendT,
      golden.g * (1.0 - blendT) + teamAlpha.g * blendT,
      golden.b * (1.0 - blendT) + teamAlpha.b * blendT,
      alpha * ConversionAlphaBlend)
    # Draw expanding ring effect
    let baseScale = ConversionBaseScale.float32
    let expandScale = baseScale * (1.0 + (1.0 - t) * ConversionExpandMult)
    bxy.drawImage("floor", effect.pos, angle = 0, scale = expandScale, tint = tintColor)

proc drawWeatherEffects*() =
  ## Draw ambient weather effects (rain or wind particles) across the viewport.
  ## Uses deterministic animation based on frame counter for consistent effects.
  if not currentViewport.valid or settings.weatherType == WeatherNone:
    return

  let viewWidth = currentViewport.maxX - currentViewport.minX + 1
  let viewHeight = currentViewport.maxY - currentViewport.minY + 1
  let viewArea = viewWidth * viewHeight

  # Calculate number of particles based on viewport size
  let particleCount = max(10, int(viewArea.float32 * WeatherParticleDensity))

  case settings.weatherType
  of WeatherRain:
    type RainPatch = object
      center: Vec2
      radius: float32
      seed: uint32

    proc mix32(v: uint32): uint32 {.inline.} =
      ## Small deterministic mixer for stable world-space weather cells.
      var x = v
      x = x xor (x shr 16)
      x *= 2246822519'u32
      x = x xor (x shr 13)
      x *= 3266489917'u32
      x = x xor (x shr 16)
      x

    var rainPatches: seq[RainPatch] = @[]
    let minCellX = max(0, currentViewport.minX div RainPatchTileSize - 1)
    let maxCellX = min((MapWidth - 1) div RainPatchTileSize, currentViewport.maxX div RainPatchTileSize + 1)
    let minCellY = max(0, currentViewport.minY div RainPatchTileSize - 1)
    let maxCellY = min((MapHeight - 1) div RainPatchTileSize, currentViewport.maxY div RainPatchTileSize + 1)
    let viewportMinX = currentViewport.minX.float32 - WeatherViewportMargin
    let viewportMaxX = currentViewport.maxX.float32 + WeatherViewportMargin
    let viewportMinY = currentViewport.minY.float32 - WeatherViewportMargin
    let viewportMaxY = currentViewport.maxY.float32 + WeatherViewportMargin

    for cellX in minCellX .. maxCellX:
      for cellY in minCellY .. maxCellY:
        let rawSeed = uint32(cellX + 1) * 374761393'u32 +
                      uint32(cellY + 1) * 668265263'u32 +
                      uint32(env.gameSeed) * 2246822519'u32
        let cellSeed = mix32(rawSeed)
        if int(cellSeed mod 100'u32) >= RainPatchChancePercent:
          continue

        let cellOffsetX = (mix32(cellSeed xor 0xA511E9B3'u32) mod 1000'u32).float32 / 1000.0
        let cellOffsetY = (mix32(cellSeed xor 0x63D5A993'u32) mod 1000'u32).float32 / 1000.0
        let baseCenter = vec2(
          (cellX.float32 + cellOffsetX) * RainPatchTileSize.float32,
          (cellY.float32 + cellOffsetY) * RainPatchTileSize.float32
        )

        let driftPhase = frame.float32 * RainPatchDriftSpeed + (cellSeed mod 97'u32).float32 * RainPatchDriftPhaseJitter
        let drift = vec2(sin(driftPhase) * RainPatchDriftXAmplitude, cos(driftPhase * RainPatchDriftYFreqMult) * RainPatchDriftYAmplitude)
        let center = baseCenter + drift
        let radiusNoise = (mix32(cellSeed xor 0x9E3779B9'u32) mod 1000'u32).float32 / 1000.0
        let radius = RainPatchMinRadius + radiusNoise * RainPatchRadiusJitter

        # Skip patches fully outside viewport.
        if center.x + radius < viewportMinX or center.x - radius > viewportMaxX or
           center.y + radius < viewportMinY or center.y - radius > viewportMaxY:
          continue

        rainPatches.add(RainPatch(center: center, radius: radius, seed: cellSeed))

    if rainPatches.len == 0:
      let fallbackCenter = vec2(
        (currentViewport.minX + viewWidth div 2).float32,
        (currentViewport.minY + viewHeight div 2).float32)
      rainPatches.add(RainPatch(center: fallbackCenter, radius: RainPatchMinRadius + RainFallbackRadiusExtra, seed: 1'u32))

    # Draw translucent cloud puffs above active rain patches.
    for patch in rainPatches:
      for puffIdx in 0 ..< RainCloudPuffCount:
        let puffSeed = mix32(patch.seed + uint32((puffIdx + 1) * 101))
        let angle = (puffSeed mod 628'u32).float32 / 100.0
        let dist = patch.radius * (RainCloudMinDist + ((puffSeed shr 11) mod 55'u32).float32 / 100.0)
        let cloudPos = patch.center + vec2(cos(angle) * dist, -patch.radius * RainCloudYOffsetMult + sin(angle) * RainCloudYJitterMult)
        let scaleNoise = ((puffSeed shr 7) mod 40'u32).float32 / 100.0
        let alphaNoise = ((puffSeed shr 17) mod 30'u32).float32 / 100.0
        let cloudScale = RainCloudScale * (1.0 + scaleNoise)
        let cloudAlpha = RainCloudAlpha * (RainCloudAlphaBase + alphaNoise)
        bxy.drawImage("floor", cloudPos, angle = 0, scale = cloudScale,
                      tint = withAlpha(CloudPuffTint, cloudAlpha))

    let rainParticleCount = max(particleCount, rainPatches.len * 10)

    # Rain particles fall within active cloud patch ellipses (localized storms).
    for i in 0 ..< rainParticleCount:
      let seed = i * 17 + 31
      let patch = rainPatches[seed mod rainPatches.len]
      let cycleOffset = (seed * 7) mod RainCycleFrames
      let cycleFrame = (frame + cycleOffset) mod RainCycleFrames
      let t = cycleFrame.float32 / RainCycleFrames.float32

      let xNoise = ((seed * 13) mod 2000).float32 / 1000.0 - 1.0
      let yNoise = ((seed * 29) mod 1000).float32 / 1000.0 - RainNoiseCenterOffset
      let xBase = patch.center.x + xNoise * patch.radius * RainXSpreadMult
      let yBase = patch.center.y - patch.radius * RainYStartOffset + yNoise * patch.radius * RainYNoiseMult
      let xDrift = t * RainDriftSpeed * RainCycleFrames.float32
      let yFall = t * (patch.radius * RainFallDistMult + RainFallDistBase)
      let particlePos = vec2(xBase + xDrift, yBase + yFall)

      # Keep rain localized to the patch footprint.
      let normX = (particlePos.x - patch.center.x) / max(0.1, patch.radius)
      let normY = (particlePos.y - patch.center.y) / max(0.1, patch.radius * RainEllipseYMult)
      if normX * normX + normY * normY > RainEllipseThreshold:
        continue

      if particlePos.x < viewportMinX or particlePos.x > viewportMaxX or
         particlePos.y < viewportMinY or particlePos.y > viewportMaxY:
        continue

      let blueVal = RainBlueBase + ((seed * 3) mod 30).float32 / 100.0
      let rainTint = color(RainBaseR, RainBaseG, blueVal, RainAlpha)

      for s in 0 ..< RainStreakLength:
        let streakOffset = vec2(
          -RainDriftSpeed * s.float32 * RainStreakSpacingMult,
          -RainFallSpeed * s.float32 * RainStreakSpacingMult
        )
        let streakAlpha = RainAlpha * (1.0 - s.float32 / RainStreakLength.float32)
        let streakTint = withAlpha(rainTint, streakAlpha)
        bxy.drawImage("floor", particlePos + streakOffset, angle = 0,
                      scale = WeatherParticleScale, tint = streakTint)

  of WeatherWind:
    # Wind particles blowing horizontally with slight vertical drift
    for i in 0 ..< particleCount:
      let seed = i * 23 + 47
      let cycleOffset = (seed * 11) mod WindCycleFrames
      let cycleFrame = (frame + cycleOffset) mod WindCycleFrames
      let t = cycleFrame.float32 / WindCycleFrames.float32

      # Vertical position: spread across viewport
      let yBase = currentViewport.minY.float32 +
                  ((seed * 19) mod (viewHeight * 100)).float32 / 100.0
      let yDrift = sin(t * Pi * 2.0) * WindDriftSpeed * WindDriftAmplitude

      # Horizontal position: cycle from left to right of viewport
      let xBase = currentViewport.minX.float32 - WeatherViewportMargin  # Start left of viewport
      let xBlow = t * WindBlowSpeed * WindCycleFrames.float32

      let particlePos = vec2(xBase + xBlow, yBase + yDrift)

      # Skip if outside viewport
      if particlePos.x < currentViewport.minX.float32 - WeatherViewportClipMargin or
         particlePos.x > currentViewport.maxX.float32 + WeatherViewportClipMargin:
        continue

      # Wind color: gray-white with variation
      let grayVal = SmokeBaseGray + ((seed * 5) mod 20).float32 / 100.0
      let windTint = color(grayVal, grayVal, grayVal, WindAlpha)

      bxy.drawImage("floor", particlePos, angle = 0,
                    scale = WeatherParticleScale, tint = windTint)

  of WeatherSnow:
    # Snow particles drifting gently downward with sinusoidal sway
    for i in 0 ..< particleCount:
      let seed = i * 19 + 53
      let cycleOffset = (seed * 11) mod SnowCycleFrames
      let cycleFrame = (frame + cycleOffset) mod SnowCycleFrames
      let t = cycleFrame.float32 / SnowCycleFrames.float32

      # Horizontal position: spread across viewport with sinusoidal sway
      let xBase = currentViewport.minX.float32 +
                  ((seed * 17) mod (viewWidth * 100)).float32 / 100.0
      let xSway = sin((frame.float32 + seed.float32) * SnowDriftFreq) * SnowDriftSpeed *
                  SnowCycleFrames.float32

      # Vertical position: fall from top to bottom of viewport
      let yBase = currentViewport.minY.float32 - WeatherViewportMargin
      let yFall = t * SnowFallSpeed * SnowCycleFrames.float32

      let particlePos = vec2(xBase + xSway, yBase + yFall)

      # Skip if outside viewport
      if particlePos.x < currentViewport.minX.float32 - WeatherViewportClipMargin or
         particlePos.x > currentViewport.maxX.float32 + WeatherViewportClipMargin or
         particlePos.y < currentViewport.minY.float32 - WeatherViewportMargin or
         particlePos.y > currentViewport.maxY.float32 + WeatherViewportMargin:
        continue

      # White snowflake with slight size variation
      let sizeVar = 1.0 + ((seed * 3) mod 40).float32 / 100.0
      let snowTint = color(1.0, 1.0, 1.0, SnowAlpha)

      bxy.drawImage("floor", particlePos, angle = 0,
                    scale = SnowParticleScale * sizeVar, tint = snowTint)

  of WeatherNone:
    discard  # No weather effects
