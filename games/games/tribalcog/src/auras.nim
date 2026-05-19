# Auras - Tank armor and monk healing aura processing
# This file is included by step.nim

# ============================================================================
# Aura Constants
# ============================================================================

const
  # Aura tints (colors are display-only, not in constants.nim)
  TankAuraTint = TileColor(r: 0.95, g: 0.75, b: 0.25, intensity: 1.05)
  MonkAuraTint = TileColor(r: 0.35, g: 0.85, b: 0.35, intensity: 1.05)

  ## Aura radius per unit class (-1 = no aura)
  UnitAuraRadius: array[AgentUnitClass, int] = [
    UnitVillager: -1, UnitManAtArms: ManAtArmsAuraRadius, UnitArcher: -1,
    UnitScout: -1, UnitKnight: KnightAuraRadius, UnitMonk: -1,
    UnitBatteringRam: -1, UnitMangonel: -1, UnitTrebuchet: -1,
    UnitGoblin: -1, UnitBoat: -1, UnitTradeCog: -1,
    UnitSamurai: -1, UnitLongbowman: -1, UnitCataphract: -1,
    UnitWoadRaider: -1, UnitTeutonicKnight: -1, UnitHuskarl: -1,
    UnitMameluke: -1, UnitJanissary: -1, UnitKing: -1,
    UnitLongSwordsman: -1, UnitChampion: -1,
    UnitLightCavalry: -1, UnitHussar: -1,
    UnitCrossbowman: -1, UnitArbalester: -1,
    UnitGalley: -1, UnitFireShip: -1,
    UnitFishingShip: -1, UnitTransportShip: -1, UnitDemoShip: -1, UnitCannonGalleon: -1,
    UnitScorpion: -1,
    UnitCavalier: KnightAuraRadius, UnitPaladin: KnightAuraRadius,
    UnitCamel: -1, UnitHeavyCamel: -1, UnitImperialCamel: -1,
    # Archery Range units
    UnitSkirmisher: -1, UnitEliteSkirmisher: -1,
    UnitCavalryArcher: -1, UnitHeavyCavalryArcher: -1,
    UnitHandCannoneer: -1,
  ]

# ============================================================================
# Aura Processing
# ============================================================================

proc stepApplyTankAuras(env: Environment) =
  ## Apply tank (ManAtArms/Knight) aura tints to nearby tiles
  ## Optimized: iterates only tankUnits collection instead of all agents
  for tank in env.tankUnits:
    if not isAgentAlive(env, tank):
      continue
    if isThingFrozen(tank, env):
      continue
    let radius = UnitAuraRadius[tank.unitClass]
    for dx in -radius .. radius:
      for dy in -radius .. radius:
        let pos = tank.pos + ivec2(dx.int32, dy.int32)
        if not isValidPos(pos):
          continue
        let existingCountdown = env.actionTintCountdown[pos.x][pos.y]
        let existingCode = env.actionTintCode[pos.x][pos.y]
        if existingCountdown > 0 and existingCode notin {ActionTintNone, ActionTintShield}:
          if existingCode != ActionTintMixed:
            env.actionTintCode[pos.x][pos.y] = ActionTintMixed
            env.updateObservations(TintLayer, pos, ActionTintMixed.int)
          continue
        env.applyActionTint(pos, TankAuraTint, TankAuraTintDuration, ActionTintShield)

proc stepApplyMonkAuras(env: Environment) =
  ## Apply monk aura tints and heal nearby allies
  ## Optimized: iterates only monkUnits collection instead of all agents
  for monk in env.monkUnits:
    if not isAgentAlive(env, monk):
      continue
    if isThingFrozen(monk, env):
      continue
    let teamId = getTeamId(monk)
    # Use spatial index to find nearby allies - reuse pre-allocated buffer
    env.tempMonkAuraAllies.setLen(0)
    collectAlliesInRangeSpatial(env, monk.pos, teamId, MonkAuraRadius, env.tempMonkAuraAllies)
    # Single-pass: apply healing directly while tracking if any ally was healed
    var healedAny = false
    for ally in env.tempMonkAuraAllies:
      if ally.hp < ally.maxHp and not isThingFrozen(ally, env):
        if env.applyAgentHeal(ally, 1, monk) > 0:
          healedAny = true
    if not healedAny:
      continue

    for dx in -MonkAuraRadius .. MonkAuraRadius:
      for dy in -MonkAuraRadius .. MonkAuraRadius:
        let pos = monk.pos + ivec2(dx.int32, dy.int32)
        if not isValidPos(pos):
          continue
        let existingCountdown = env.actionTintCountdown[pos.x][pos.y]
        let existingCode = env.actionTintCode[pos.x][pos.y]
        if existingCountdown > 0 and existingCode notin {ActionTintNone, ActionTintShield, ActionTintHealMonk}:
          if existingCode != ActionTintMixed:
            env.actionTintCode[pos.x][pos.y] = ActionTintMixed
            env.updateObservations(TintLayer, pos, ActionTintMixed.int)
          continue
        env.applyActionTint(pos, MonkAuraTint, MonkAuraTintDuration, ActionTintHealMonk)

proc stepRechargeMonkFaith(env: Environment) =
  ## Regenerate faith for monks over time (AoE2-style faith recharge)
  ## Optimized: iterates only monkUnits collection instead of all agents
  for monk in env.monkUnits:
    if not isAgentAlive(env, monk):
      continue
    if isThingFrozen(monk, env):
      continue
    if monk.faith < MonkMaxFaith:
      monk.faith = min(MonkMaxFaith, monk.faith + MonkFaithRechargeRate)
