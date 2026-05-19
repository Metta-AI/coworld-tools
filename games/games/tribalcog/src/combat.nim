const BonusDamageByClass*: array[AgentUnitClass, array[AgentUnitClass, int]] = block:
  var table: array[AgentUnitClass, array[AgentUnitClass, int]]
  for (attacker, target, value) in [
    # Infantry > cavalry (rock-paper-scissors core)
    (UnitManAtArms, UnitScout, 1),
    (UnitManAtArms, UnitKnight, 1),
    (UnitManAtArms, UnitLightCavalry, 1),
    (UnitManAtArms, UnitHussar, 1),
    # Archer > infantry
    (UnitArcher, UnitManAtArms, 1),
    (UnitArcher, UnitLongSwordsman, 1),
    (UnitArcher, UnitChampion, 1),
    # Cavalry > archer
    (UnitScout, UnitArcher, 1),
    (UnitScout, UnitCrossbowman, 1),
    (UnitScout, UnitArbalester, 1),
    (UnitKnight, UnitArcher, 1),
    (UnitKnight, UnitCrossbowman, 1),
    (UnitKnight, UnitArbalester, 1),

    # Infantry > all cavalry (upgrade tiers inherit counter relationships)
    # ManAtArms also counters Cavalier/Paladin/Camel line
    (UnitManAtArms, UnitCavalier, 1),
    (UnitManAtArms, UnitPaladin, 1),
    (UnitManAtArms, UnitCamel, 1),
    (UnitManAtArms, UnitHeavyCamel, 1),
    (UnitManAtArms, UnitImperialCamel, 1),
    (UnitLongSwordsman, UnitScout, 1),
    (UnitLongSwordsman, UnitKnight, 1),
    (UnitLongSwordsman, UnitLightCavalry, 1),
    (UnitLongSwordsman, UnitHussar, 1),
    (UnitLongSwordsman, UnitCavalier, 1),
    (UnitLongSwordsman, UnitPaladin, 1),
    (UnitLongSwordsman, UnitCamel, 1),
    (UnitLongSwordsman, UnitHeavyCamel, 1),
    (UnitLongSwordsman, UnitImperialCamel, 1),
    (UnitChampion, UnitScout, 2),
    (UnitChampion, UnitKnight, 2),
    (UnitChampion, UnitLightCavalry, 2),
    (UnitChampion, UnitHussar, 2),
    (UnitChampion, UnitCavalier, 2),
    (UnitChampion, UnitPaladin, 2),
    (UnitChampion, UnitCamel, 2),
    (UnitChampion, UnitHeavyCamel, 2),
    (UnitChampion, UnitImperialCamel, 2),

    # Archer > all infantry (including castle infantry)
    (UnitArcher, UnitSamurai, 1),
    (UnitArcher, UnitWoadRaider, 1),
    (UnitArcher, UnitTeutonicKnight, 1),
    (UnitCrossbowman, UnitManAtArms, 1),
    (UnitCrossbowman, UnitLongSwordsman, 1),
    (UnitCrossbowman, UnitChampion, 1),
    (UnitCrossbowman, UnitSamurai, 1),
    (UnitCrossbowman, UnitWoadRaider, 1),
    (UnitCrossbowman, UnitTeutonicKnight, 1),
    (UnitArbalester, UnitManAtArms, 2),
    (UnitArbalester, UnitLongSwordsman, 2),
    (UnitArbalester, UnitChampion, 2),
    (UnitArbalester, UnitSamurai, 2),
    (UnitArbalester, UnitWoadRaider, 2),
    (UnitArbalester, UnitTeutonicKnight, 2),

    # Cavalry > all archers (including castle/new archer units)
    (UnitScout, UnitLongbowman, 1),
    (UnitScout, UnitJanissary, 1),
    (UnitScout, UnitSkirmisher, 1),
    (UnitScout, UnitEliteSkirmisher, 1),
    (UnitScout, UnitCavalryArcher, 1),
    (UnitScout, UnitHeavyCavalryArcher, 1),
    (UnitScout, UnitHandCannoneer, 1),
    (UnitKnight, UnitLongbowman, 1),
    (UnitKnight, UnitJanissary, 1),
    (UnitKnight, UnitSkirmisher, 1),
    (UnitKnight, UnitEliteSkirmisher, 1),
    (UnitKnight, UnitCavalryArcher, 1),
    (UnitKnight, UnitHeavyCavalryArcher, 1),
    (UnitKnight, UnitHandCannoneer, 1),
    (UnitLightCavalry, UnitArcher, 1),
    (UnitLightCavalry, UnitCrossbowman, 1),
    (UnitLightCavalry, UnitArbalester, 1),
    (UnitLightCavalry, UnitLongbowman, 1),
    (UnitLightCavalry, UnitJanissary, 1),
    (UnitLightCavalry, UnitSkirmisher, 1),
    (UnitLightCavalry, UnitEliteSkirmisher, 1),
    (UnitLightCavalry, UnitCavalryArcher, 1),
    (UnitLightCavalry, UnitHeavyCavalryArcher, 1),
    (UnitLightCavalry, UnitHandCannoneer, 1),
    (UnitHussar, UnitArcher, 2),
    (UnitHussar, UnitCrossbowman, 2),
    (UnitHussar, UnitArbalester, 2),
    (UnitHussar, UnitLongbowman, 2),
    (UnitHussar, UnitJanissary, 2),
    (UnitHussar, UnitSkirmisher, 2),
    (UnitHussar, UnitEliteSkirmisher, 2),
    (UnitHussar, UnitCavalryArcher, 2),
    (UnitHussar, UnitHeavyCavalryArcher, 2),
    (UnitHussar, UnitHandCannoneer, 2),
    # Cavalier/Paladin (Knight upgrades) > all archers
    (UnitCavalier, UnitArcher, 1),
    (UnitCavalier, UnitCrossbowman, 1),
    (UnitCavalier, UnitArbalester, 1),
    (UnitCavalier, UnitLongbowman, 1),
    (UnitCavalier, UnitJanissary, 1),
    (UnitCavalier, UnitSkirmisher, 1),
    (UnitCavalier, UnitEliteSkirmisher, 1),
    (UnitCavalier, UnitCavalryArcher, 1),
    (UnitCavalier, UnitHeavyCavalryArcher, 1),
    (UnitCavalier, UnitHandCannoneer, 1),
    (UnitPaladin, UnitArcher, 2),
    (UnitPaladin, UnitCrossbowman, 2),
    (UnitPaladin, UnitArbalester, 2),
    (UnitPaladin, UnitLongbowman, 2),
    (UnitPaladin, UnitJanissary, 2),
    (UnitPaladin, UnitSkirmisher, 2),
    (UnitPaladin, UnitEliteSkirmisher, 2),
    (UnitPaladin, UnitCavalryArcher, 2),
    (UnitPaladin, UnitHeavyCavalryArcher, 2),
    (UnitPaladin, UnitHandCannoneer, 2),

    # Camel line > cavalry (anti-cavalry specialist)
    (UnitCamel, UnitScout, 1),
    (UnitCamel, UnitKnight, 1),
    (UnitCamel, UnitLightCavalry, 1),
    (UnitCamel, UnitHussar, 1),
    (UnitCamel, UnitCavalier, 1),
    (UnitCamel, UnitPaladin, 1),
    (UnitCamel, UnitCataphract, 1),
    (UnitHeavyCamel, UnitScout, 2),
    (UnitHeavyCamel, UnitKnight, 2),
    (UnitHeavyCamel, UnitLightCavalry, 2),
    (UnitHeavyCamel, UnitHussar, 2),
    (UnitHeavyCamel, UnitCavalier, 2),
    (UnitHeavyCamel, UnitPaladin, 2),
    (UnitHeavyCamel, UnitCataphract, 2),
    (UnitImperialCamel, UnitScout, 3),
    (UnitImperialCamel, UnitKnight, 3),
    (UnitImperialCamel, UnitLightCavalry, 3),
    (UnitImperialCamel, UnitHussar, 3),
    (UnitImperialCamel, UnitCavalier, 3),
    (UnitImperialCamel, UnitPaladin, 3),
    (UnitImperialCamel, UnitCataphract, 3),

    # Skirmisher > archers (anti-archer ranged)
    (UnitSkirmisher, UnitArcher, 1),
    (UnitSkirmisher, UnitCrossbowman, 1),
    (UnitSkirmisher, UnitArbalester, 1),
    (UnitSkirmisher, UnitLongbowman, 1),
    (UnitSkirmisher, UnitJanissary, 1),
    (UnitEliteSkirmisher, UnitArcher, 2),
    (UnitEliteSkirmisher, UnitCrossbowman, 2),
    (UnitEliteSkirmisher, UnitArbalester, 2),
    (UnitEliteSkirmisher, UnitLongbowman, 2),
    (UnitEliteSkirmisher, UnitJanissary, 2),

    # Castle unique units - specialized counters
    # Samurai (fast infantry) > other infantry
    (UnitSamurai, UnitManAtArms, 1),
    (UnitSamurai, UnitLongSwordsman, 1),
    (UnitSamurai, UnitChampion, 1),
    # Cataphract (heavy cavalry) > infantry
    (UnitCataphract, UnitManAtArms, 1),
    (UnitCataphract, UnitLongSwordsman, 1),
    (UnitCataphract, UnitChampion, 1),
    # Huskarl (anti-archer) > archers
    (UnitHuskarl, UnitArcher, 2),
    (UnitHuskarl, UnitCrossbowman, 2),
    (UnitHuskarl, UnitArbalester, 2),
    (UnitHuskarl, UnitLongbowman, 2),
    (UnitHuskarl, UnitSkirmisher, 2),
    (UnitHuskarl, UnitEliteSkirmisher, 2),
    (UnitHuskarl, UnitCavalryArcher, 2),
    (UnitHuskarl, UnitHeavyCavalryArcher, 2),
    (UnitHuskarl, UnitHandCannoneer, 2),

    # Fire Ship (anti-ship) > water units
    (UnitFireShip, UnitBoat, 2),
    (UnitFireShip, UnitTradeCog, 2),
    (UnitFireShip, UnitGalley, 2),
    (UnitFireShip, UnitFireShip, 1),  # Less effective vs other fire ships
    (UnitFireShip, UnitFishingShip, 2),
    (UnitFireShip, UnitTransportShip, 2),
    (UnitFireShip, UnitDemoShip, 2),
    (UnitFireShip, UnitCannonGalleon, 2),

    # Demo Ship (kamikaze) > all ships and buildings (high base damage handles this)

    # Scorpion (anti-infantry) > infantry
    (UnitScorpion, UnitManAtArms, 2),
    (UnitScorpion, UnitLongSwordsman, 2),
    (UnitScorpion, UnitChampion, 2),
    (UnitScorpion, UnitSamurai, 2),
    (UnitScorpion, UnitWoadRaider, 2),
    (UnitScorpion, UnitTeutonicKnight, 2),
    (UnitScorpion, UnitHuskarl, 2)
  ]:
    table[attacker][target] = value
  table

const BonusDamageTintByClass: array[AgentUnitClass, TileColor] = [
  # UnitVillager
  TileColor(r: 1.00, g: 0.35, b: 0.30, intensity: 1.20),
  # UnitManAtArms (infantry counter - orange)
  TileColor(r: 1.00, g: 0.65, b: 0.20, intensity: 1.20),
  # UnitArcher (archer counter - yellow)
  TileColor(r: 1.00, g: 0.90, b: 0.25, intensity: 1.20),
  # UnitScout (cavalry counter - green)
  TileColor(r: 0.30, g: 1.00, b: 0.35, intensity: 1.18),
  # UnitKnight (cavalry counter - cyan)
  TileColor(r: 0.25, g: 0.95, b: 0.90, intensity: 1.18),
  # UnitMonk
  TileColor(r: 0.30, g: 0.60, b: 1.00, intensity: 1.18),
  # UnitBatteringRam (siege - stronger purple, higher intensity)
  TileColor(r: 0.55, g: 0.40, b: 1.00, intensity: 1.40),
  # UnitMangonel (siege - stronger pink-purple, higher intensity)
  TileColor(r: 0.85, g: 0.40, b: 1.00, intensity: 1.40),
  # UnitTrebuchet (siege - deep purple, highest intensity)
  TileColor(r: 0.70, g: 0.25, b: 1.00, intensity: 1.45),
  # UnitGoblin
  TileColor(r: 0.35, g: 0.85, b: 0.35, intensity: 1.18),
  # UnitBoat
  TileColor(r: 1.00, g: 0.40, b: 0.80, intensity: 1.18),
  # UnitTradeCog
  TileColor(r: 1.00, g: 0.85, b: 0.30, intensity: 1.10),
  # Castle unique units
  # UnitSamurai
  TileColor(r: 0.95, g: 0.40, b: 0.25, intensity: 1.22),
  # UnitLongbowman
  TileColor(r: 0.70, g: 0.90, b: 0.25, intensity: 1.20),
  # UnitCataphract
  TileColor(r: 0.85, g: 0.70, b: 0.30, intensity: 1.22),
  # UnitWoadRaider
  TileColor(r: 0.30, g: 0.60, b: 0.85, intensity: 1.20),
  # UnitTeutonicKnight
  TileColor(r: 0.60, g: 0.65, b: 0.70, intensity: 1.25),
  # UnitHuskarl
  TileColor(r: 0.55, g: 0.40, b: 0.80, intensity: 1.20),
  # UnitMameluke
  TileColor(r: 0.90, g: 0.80, b: 0.50, intensity: 1.20),
  # UnitJanissary
  TileColor(r: 0.90, g: 0.30, b: 0.35, intensity: 1.22),
  # UnitKing
  TileColor(r: 0.95, g: 0.80, b: 0.20, intensity: 1.25),
  # Unit upgrade tiers (same tint family as base unit)
  # UnitLongSwordsman (infantry - orange)
  TileColor(r: 1.00, g: 0.65, b: 0.20, intensity: 1.25),
  # UnitChampion (infantry - orange, stronger)
  TileColor(r: 1.00, g: 0.65, b: 0.20, intensity: 1.30),
  # UnitLightCavalry (cavalry - green)
  TileColor(r: 0.30, g: 1.00, b: 0.35, intensity: 1.22),
  # UnitHussar (cavalry - green, stronger)
  TileColor(r: 0.30, g: 1.00, b: 0.35, intensity: 1.28),
  # UnitCrossbowman (archer - yellow)
  TileColor(r: 1.00, g: 0.90, b: 0.25, intensity: 1.25),
  # UnitArbalester (archer - yellow, stronger)
  TileColor(r: 1.00, g: 0.90, b: 0.25, intensity: 1.30),
  # Naval combat units
  # UnitGalley (naval - blue)
  TileColor(r: 0.30, g: 0.50, b: 0.95, intensity: 1.25),
  # UnitFireShip (naval fire - orange-red)
  TileColor(r: 1.00, g: 0.50, b: 0.20, intensity: 1.35),
  # UnitFishingShip (naval economic - light blue)
  TileColor(r: 0.40, g: 0.70, b: 0.90, intensity: 1.10),
  # UnitTransportShip (naval transport - teal)
  TileColor(r: 0.35, g: 0.75, b: 0.75, intensity: 1.15),
  # UnitDemoShip (naval kamikaze - bright red)
  TileColor(r: 1.00, g: 0.25, b: 0.15, intensity: 1.40),
  # UnitCannonGalleon (naval artillery - dark blue)
  TileColor(r: 0.20, g: 0.35, b: 0.85, intensity: 1.35),
  # UnitScorpion (siege - cyan-purple)
  TileColor(r: 0.60, g: 0.50, b: 0.90, intensity: 1.35),
  # Stable cavalry upgrades (same cyan family as Knight)
  # UnitCavalier
  TileColor(r: 0.25, g: 0.95, b: 0.90, intensity: 1.22),
  # UnitPaladin
  TileColor(r: 0.25, g: 0.95, b: 0.90, intensity: 1.28),
  # Camel line (sandy brown - anti-cavalry specialists)
  # UnitCamel
  TileColor(r: 0.85, g: 0.70, b: 0.40, intensity: 1.20),
  # UnitHeavyCamel
  TileColor(r: 0.85, g: 0.70, b: 0.40, intensity: 1.25),
  # UnitImperialCamel
  TileColor(r: 0.85, g: 0.70, b: 0.40, intensity: 1.30),
  # Archery Range units (yellow-green archer family)
  # UnitSkirmisher
  TileColor(r: 0.70, g: 0.95, b: 0.30, intensity: 1.18),
  # UnitEliteSkirmisher
  TileColor(r: 0.70, g: 0.95, b: 0.30, intensity: 1.25),
  # UnitCavalryArcher (cyan - mounted ranged)
  TileColor(r: 0.35, g: 0.90, b: 0.85, intensity: 1.20),
  # UnitHeavyCavalryArcher
  TileColor(r: 0.35, g: 0.90, b: 0.85, intensity: 1.28),
  # UnitHandCannoneer (orange-red gunpowder)
  TileColor(r: 0.95, g: 0.45, b: 0.25, intensity: 1.35),
]

# Action tint codes for per-unit bonus damage
# Maps attacker unit class to the appropriate observation code
const BonusTintCodeByClass: array[AgentUnitClass, uint8] = [
  # UnitVillager - no counter bonus
  ActionTintAttackBonus,
  # UnitManAtArms - infantry counter (beats cavalry)
  ActionTintBonusInfantry,
  # UnitArcher - archer counter (beats infantry)
  ActionTintBonusArcher,
  # UnitScout - scout counter (beats archers)
  ActionTintBonusScout,
  # UnitKnight - knight counter (beats archers)
  ActionTintBonusKnight,
  # UnitMonk - no counter bonus
  ActionTintAttackBonus,
  # UnitBatteringRam - battering ram siege bonus (beats structures)
  ActionTintBonusBatteringRam,
  # UnitMangonel - mangonel siege bonus (beats structures)
  ActionTintBonusMangonel,
  # UnitTrebuchet - trebuchet siege bonus (beats structures)
  ActionTintBonusTrebuchet,
  # UnitGoblin - no counter bonus
  ActionTintAttackBonus,
  # UnitBoat - no counter bonus
  ActionTintAttackBonus,
  # UnitTradeCog - no counter bonus
  ActionTintAttackBonus,
  # Castle unique units - generic bonus tint
  ActionTintAttackBonus,  # UnitSamurai
  ActionTintAttackBonus,  # UnitLongbowman
  ActionTintAttackBonus,  # UnitCataphract
  ActionTintAttackBonus,  # UnitWoadRaider
  ActionTintAttackBonus,  # UnitTeutonicKnight
  ActionTintAttackBonus,  # UnitHuskarl
  ActionTintAttackBonus,  # UnitMameluke
  ActionTintAttackBonus,  # UnitJanissary
  ActionTintAttackBonus,  # UnitKing
  # Unit upgrade tiers (same counter as base unit)
  ActionTintBonusInfantry,  # UnitLongSwordsman
  ActionTintBonusInfantry,  # UnitChampion
  ActionTintBonusScout,     # UnitLightCavalry
  ActionTintBonusScout,     # UnitHussar
  ActionTintBonusArcher,    # UnitCrossbowman
  ActionTintBonusArcher,    # UnitArbalester
  # Naval combat units
  ActionTintAttackBonus,    # UnitGalley - ranged naval
  ActionTintAttackBonus,    # UnitFireShip - anti-ship
  ActionTintAttackBonus,    # UnitFishingShip - economic
  ActionTintAttackBonus,    # UnitTransportShip - transport
  ActionTintAttackBonus,    # UnitDemoShip - kamikaze
  ActionTintAttackBonus,    # UnitCannonGalleon - artillery
  # Additional siege unit
  ActionTintAttackBonus,    # UnitScorpion - anti-infantry siege
  # Stable cavalry upgrades (same counter as Knight)
  ActionTintBonusKnight,    # UnitCavalier
  ActionTintBonusKnight,    # UnitPaladin
  # Camel line (anti-cavalry specialists - unique bonus tint)
  ActionTintAttackBonus,    # UnitCamel
  ActionTintAttackBonus,    # UnitHeavyCamel
  ActionTintAttackBonus,    # UnitImperialCamel
  # Archery Range units (archer bonus tints)
  ActionTintBonusArcher,    # UnitSkirmisher - anti-archer
  ActionTintBonusArcher,    # UnitEliteSkirmisher
  ActionTintBonusArcher,    # UnitCavalryArcher
  ActionTintBonusArcher,    # UnitHeavyCavalryArcher
  ActionTintBonusArcher,    # UnitHandCannoneer
]

# Death animation tint: dark red flash at kill location
const DeathTint = TileColor(r: 0.80, g: 0.15, b: 0.15, intensity: 1.20)

const AttackableStructures* = {Wall, Door, Outpost, GuardTower, Castle, TownCenter, Monastery, Wonder}

proc killAgent(env: Environment, victim: Thing, attacker: Thing = nil)
  ## Forward declaration: defined below applyStructureDamage

proc applyStructureDamage*(env: Environment, target: Thing, amount: int,
                           attacker: Thing = nil): bool =
  ## Apply damage to a structure (Wall, Tower, Castle, etc).
  ## University techs affect structure combat:
  ## - Masonry: +1/+1 building armor (reduces damage by 1)
  ## - Architecture: +1/+1 building armor (stacks with Masonry, reduces by 1 more)
  ## - Siege Engineers: +20% building damage for siege units
  var damage = max(1, amount)
  if not attacker.isNil and attacker.unitClass in {UnitBatteringRam, UnitMangonel, UnitTrebuchet}:
    env.applyActionTint(target.pos, BonusDamageTintByClass[attacker.unitClass], 2, BonusTintCodeByClass[attacker.unitClass])
    damage *= SiegeStructureMultiplier
    # Siege Engineers: +20% building damage for siege units
    let attackerTeam = getTeamId(attacker)
    if attackerTeam >= 0 and env.hasUniversityTech(attackerTeam, TechSiegeEngineers):
      damage = (damage * 6 + 2) div 5  # +20% with rounding, no float

  # Apply building armor from Masonry and Architecture (defender's team)
  if target.teamId >= 0:
    let armorReduction = ord(env.hasUniversityTech(target.teamId, TechMasonry)) +
                         ord(env.hasUniversityTech(target.teamId, TechArchitecture))
    if armorReduction > 0:
      damage = max(1, damage - armorReduction)

  target.hp = max(0, target.hp - damage)
  # Spawn floating damage number for structure damage feedback
  let isSiege = not attacker.isNil and attacker.unitClass in {UnitBatteringRam, UnitMangonel, UnitTrebuchet}
  env.spawnDamageNumber(target.pos, damage, if isSiege: DmgNumCritical else: DmgNumDamage)
  when defined(combatAudit):
    if not attacker.isNil:
      let aTeam = getTeamId(attacker)
      recordSiegeDamage(env.currentStep, aTeam, $target.kind,
                        target.teamId, damage, $attacker.unitClass,
                        target.hp <= 0)
  if target.hp > 0:
    return false

  when defined(eventLog):
    logEvent(
      ecBuildDestroy,
      target.teamId,
      $target.kind & " destroyed at (" & $target.pos.x & "," & $target.pos.y & ")",
      env.currentStep,
    )

  when defined(audio):
    audioOnBuildingDestroyed(target.pos)

  if target.kind == Wall:
    if isValidPos(target.pos):
      env.updateObservations(ThingAgentLayer, target.pos, 0)
  # Eject garrisoned units when building is destroyed
  if target.kind in {TownCenter, Castle, GuardTower, House} and target.garrisonedUnits.len > 0:
    var emptyTiles: seq[IVec2] = @[]
    for dy in -2 .. 2:
      for dx in -2 .. 2:
        if dx == 0 and dy == 0: continue
        let pos = target.pos + ivec2(dx.int32, dy.int32)
        if isValidPos(pos) and env.isEmpty(pos) and env.terrain[pos.x][pos.y] != Water:
          emptyTiles.add(pos)
    var tileIdx = 0
    for unit in target.garrisonedUnits:
      unit.isGarrisoned = false
      if tileIdx >= emptyTiles.len:
        killAgent(env, unit)  # Proper cleanup: aura tracking, rewards, inventory
      else:
        unit.pos = emptyTiles[tileIdx]
        env.grid[unit.pos.x][unit.pos.y] = unit
        addToSpatialIndex(env, unit)
        env.updateObservations(AgentLayer, unit.pos, getTeamId(unit) + 1)
        env.updateObservations(AgentOrientationLayer, unit.pos, unit.orientation.int)
        inc tileIdx
    target.garrisonedUnits.setLen(0)
  # Drop garrisoned relics when a Monastery is destroyed
  if target.kind == Monastery and target.garrisonedRelics > 0:
    var bgCandidates: seq[IVec2] = @[]
    # Search progressively wider radius to find enough empty tiles
    var radius = 2
    while bgCandidates.len < target.garrisonedRelics and radius <= 5:
      bgCandidates.setLen(0)
      for dy in -radius .. radius:
        for dx in -radius .. radius:
          if dx == 0 and dy == 0: continue
          let pos = target.pos + ivec2(dx.int32, dy.int32)
          if isValidPos(pos) and env.terrain[pos.x][pos.y] != Water and
              isNil(env.backgroundGrid[pos.x][pos.y]):
            bgCandidates.add(pos)
      inc radius
    for i in 0 ..< min(target.garrisonedRelics, bgCandidates.len):
      let relic = Thing(kind: Relic, pos: bgCandidates[i])
      relic.inventory = emptyInventory()
      env.add(relic)
    target.garrisonedRelics = 0
  # Refund production queue resources before destroying the building
  while target.productionQueue.entries.len > 0:
    target.productionQueue.entries.setLen(target.productionQueue.entries.len - 1)
    env.refundTrainCosts(target)
  # Spawn debris particles for visual feedback on building destruction
  env.spawnDebris(target.pos, target.kind)
  removeThing(env, target)
  true

proc killAgent(env: Environment, victim: Thing, attacker: Thing = nil) =
  ## Remove an agent from the board and mark for respawn.
  ## If attacker is provided, spawn ragdoll tumbling away from damage source.

  # Guard against invalid agentId
  if victim.agentId < 0 or victim.agentId >= MapAgents:
    return
  # Already dead — avoid double-kill
  if env.terminated[victim.agentId] != 0.0:
    return

  let deathPos = victim.pos

  # Guard against invalid position (e.g., garrisoned unit with pos = (-1,-1))
  if not isValidPos(deathPos):
    env.terminated[victim.agentId] = 1.0
    victim.hp = 0
    env.rewards[victim.agentId] += env.config.deathPenalty
    # Remove from aura unit collections (same cleanup as normal death path)
    if victim.unitClass in TankAuraUnits:
      for i in 0 ..< env.tankUnits.len:
        if env.tankUnits[i] == victim:
          env.tankUnits[i] = env.tankUnits[^1]
          env.tankUnits.setLen(env.tankUnits.len - 1)
          break
    elif victim.unitClass == UnitMonk:
      for i in 0 ..< env.monkUnits.len:
        if env.monkUnits[i] == victim:
          env.monkUnits[i] = env.monkUnits[^1]
          env.monkUnits.setLen(env.monkUnits.len - 1)
          break
    elif victim.unitClass == UnitVillager:
      let teamId = getTeamId(victim)
      if teamId >= 0 and teamId < MapRoomObjectsTeams:
        for i in 0 ..< env.teamVillagers[teamId].len:
          if env.teamVillagers[teamId][i] == victim:
            env.teamVillagers[teamId][i] = env.teamVillagers[teamId][^1]
            env.teamVillagers[teamId].setLen(env.teamVillagers[teamId].len - 1)
            break
    victim.inventory = emptyInventory()
    return

  # Create dying unit for fade-out animation before removing from grid
  env.dyingUnits.add(DyingUnit(
    pos: deathPos,
    orientation: victim.orientation,
    unitClass: victim.unitClass,
    agentId: victim.agentId,
    countdown: DyingUnitLifetime,
    lifetime: DyingUnitLifetime
  ))

  env.grid[deathPos.x][deathPos.y] = nil
  env.updateObservations(AgentLayer, victim.pos, 0)
  env.updateObservations(AgentOrientationLayer, victim.pos, 0)

  # Remove from aura unit collections (swap-and-pop for O(1))
  if victim.unitClass in TankAuraUnits:
    for i in 0 ..< env.tankUnits.len:
      if env.tankUnits[i] == victim:
        env.tankUnits[i] = env.tankUnits[^1]
        env.tankUnits.setLen(env.tankUnits.len - 1)
        break
  elif victim.unitClass == UnitMonk:
    for i in 0 ..< env.monkUnits.len:
      if env.monkUnits[i] == victim:
        env.monkUnits[i] = env.monkUnits[^1]
        env.monkUnits.setLen(env.monkUnits.len - 1)
        break
  elif victim.unitClass == UnitVillager:
    # Remove from teamVillagers cache (swap-and-pop for O(1))
    let teamId = getTeamId(victim)
    if teamId >= 0 and teamId < MapRoomObjectsTeams:
      for i in 0 ..< env.teamVillagers[teamId].len:
        if env.teamVillagers[teamId][i] == victim:
          env.teamVillagers[teamId][i] = env.teamVillagers[teamId][^1]
          env.teamVillagers[teamId].setLen(env.teamVillagers[teamId].len - 1)
          break

  when defined(eventLog):
    logEvent(
      ecDeath,
      getTeamId(victim),
      $victim.unitClass & " died at (" & $deathPos.x & "," & $deathPos.y & ")",
      env.currentStep,
    )

  env.terminated[victim.agentId] = 1.0
  victim.hp = 0
  env.rewards[victim.agentId] += env.config.deathPenalty
  let lanternCount = getInv(victim, ItemLantern)
  let relicCount = getInv(victim, ItemRelic)
  if lanternCount > 0: setInv(victim, ItemLantern, 0)
  if relicCount > 0: setInv(victim, ItemRelic, 0)
  let dropInv = victim.inventory
  # Use object pool for Corpse/Skeleton (both are PoolableKinds)
  let corpseKind = if dropInv.len > 0: Corpse else: Skeleton
  let corpse = acquireThing(env, corpseKind)
  corpse.pos = deathPos
  corpse.inventory = dropInv
  env.add(corpse)

  # Apply death animation tint at kill location
  env.applyActionTint(deathPos, DeathTint, DeathTintDuration, ActionTintDeath)

  # Spawn ragdoll body tumbling away from damage source
  let ragdollDir = if not attacker.isNil:
    vec2((deathPos.x - attacker.pos.x).float32, (deathPos.y - attacker.pos.y).float32)
  else:
    vec2(0.0, 0.0)  # No direction if no attacker (falls in place)
  env.spawnRagdoll(deathPos, ragdollDir, victim.unitClass, getTeamId(victim))

  if lanternCount > 0 or relicCount > 0:
    let totalNeeded = lanternCount + relicCount
    var candidates: seq[IVec2] = @[]
    var searchRadius = 1
    while candidates.len < totalNeeded and searchRadius <= 4:
      candidates.setLen(0)
      for dy in -searchRadius .. searchRadius:
        for dx in -searchRadius .. searchRadius:
          if dx == 0 and dy == 0: continue
          let cand = deathPos + ivec2(dx.int32, dy.int32)
          if isValidPos(cand) and env.isEmpty(cand) and not env.hasDoor(cand) and
              not isBlockedTerrain(env.terrain[cand.x][cand.y]) and not isTileFrozen(cand, env):
            candidates.add(cand)
      inc searchRadius
    let lanternSlots = min(lanternCount, candidates.len)
    for i in 0 ..< lanternSlots:
      let lantern = acquireThing(env, Lantern)
      lantern.pos = candidates[i]
      lantern.teamId = getTeamId(victim)
      lantern.lanternHealthy = true
      env.add(lantern)
    let relicSlots = min(relicCount, candidates.len - lanternSlots)
    for i in 0 ..< relicSlots:
      let relic = Thing(kind: Relic, pos: candidates[lanternSlots + i])
      relic.inventory = emptyInventory()
      env.add(relic)

  victim.inventory = emptyInventory()
  # Remove from spatial index before clearing position (prevents stale entries
  # accumulating across death/respawn cycles since updateSpatialIndex skips
  # removal when oldPos is invalid (-1,-1))
  removeFromSpatialIndex(env, victim)
  victim.pos = ivec2(-1, -1)

# Apply damage to an agent; respects armor and marks terminated when HP <= 0.
# Returns true if the agent died this call.
proc applyAgentDamage(env: Environment, target: Thing, amount: int, attacker: Thing = nil): bool =
  # Guard: skip agents with invalid agentId or already terminated
  if target.agentId < 0 or target.agentId >= MapAgents:
    return false
  if env.terminated[target.agentId] != 0.0:
    return false
  # Track when this unit was attacked (for defensive stance retaliation)
  target.lastAttackedStep = env.currentStep

  var remaining = max(1, amount)

  # Apply Blacksmith attack upgrade bonus from attacker
  if not attacker.isNil:
    let attackerTeamId = getTeamId(attacker)
    if attackerTeamId >= 0 and attackerTeamId < MapRoomObjectsTeams:
      let attackBonus = env.getBlacksmithAttackBonus(attackerTeamId, attacker.unitClass)
      remaining += attackBonus

  let bonus = if attacker.isNil: 0 else: BonusDamageByClass[attacker.unitClass][target.unitClass]
  if bonus > 0:
    env.applyActionTint(target.pos, BonusDamageTintByClass[attacker.unitClass], 2, BonusTintCodeByClass[attacker.unitClass])
    remaining = max(1, remaining + bonus)
  let teamId = getTeamId(target)
  if teamId >= 0:
    # Iterate tankUnits directly (no allocation, avoids collecting all allies then filtering)
    # Cache target position to avoid repeated field access in hot loop
    let targetX = target.pos.x
    let targetY = target.pos.y
    for tank in env.tankUnits:
      if getTeamId(tank) != teamId: continue
      if not isAgentAlive(env, tank): continue
      # Fast frozen check: skip explicit frozen first, then tile check
      if tank.frozen > 0 or isTileFrozen(tank.pos, env): continue
      let radius = if tank.unitClass in {UnitKnight, UnitCavalier, UnitPaladin}: KnightAuraRadius else: ManAtArmsAuraRadius
      if max(abs(tank.pos.x - targetX), abs(tank.pos.y - targetY)) <= radius:
        remaining = max(1, (remaining + 1) div 2)
        break

  # Apply combined armor reduction (blacksmith + inventory) as a single pool
  # so neither source eclipses the other
  var totalArmor = 0
  if teamId >= 0 and teamId < MapRoomObjectsTeams:
    totalArmor += env.getBlacksmithArmorBonus(teamId, target.unitClass)
  totalArmor += target.inventoryArmor

  if totalArmor > 0:
    let absorbed = min(remaining, totalArmor)
    remaining -= absorbed
    # Deplete inventory armor by whatever portion it contributed
    if target.inventoryArmor > 0:
      let inventoryUsed = min(target.inventoryArmor, absorbed)
      target.inventoryArmor = target.inventoryArmor - inventoryUsed

  # Guarantee minimum 1 damage (AoE2 rule: attacks always deal at least 1)
  remaining = max(1, remaining)

  if remaining > 0:
    target.hp = max(0, target.hp - remaining)
    # Spawn floating damage number for combat feedback
    let dmgKind = if bonus > 0: DmgNumCritical else: DmgNumDamage
    env.spawnDamageNumber(target.pos, remaining, dmgKind)
    # Spawn attack impact particles for visual hit feedback
    env.spawnAttackImpact(target.pos)

  when defined(combatAudit):
    if remaining > 0 and not attacker.isNil:
      let aTeam = getTeamId(attacker)
      let tTeam = getTeamId(target)
      let dmgType = if attacker.unitClass in {UnitArcher, UnitLongbowman, UnitJanissary,
          UnitCrossbowman, UnitArbalester}: "ranged"
        elif attacker.unitClass in {UnitBatteringRam, UnitMangonel, UnitTrebuchet}: "siege"
        else: "melee"
      recordDamage(env.currentStep, aTeam, tTeam, attacker.agentId, target.agentId,
                   remaining, $attacker.unitClass, $target.unitClass, dmgType)

  when defined(eventLog):
    if remaining > 0 and not attacker.isNil:
      logCombatHit(getTeamId(attacker), getTeamId(target),
                   $attacker.unitClass, $target.unitClass, remaining, env.currentStep)

  when defined(audio):
    if remaining > 0 and not attacker.isNil:
      audioOnAttack(attacker.unitClass, attacker.pos)
      audioOnHit(target.unitClass, target.pos, remaining)

  if target.hp <= 0:
    # Track veterancy: increment killer's kill count
    if not attacker.isNil:
      inc attacker.kills
    when defined(combatAudit):
      if not attacker.isNil:
        recordKill(env.currentStep, getTeamId(attacker), getTeamId(target),
                   attacker.agentId, target.agentId,
                   $attacker.unitClass, $target.unitClass)
    when defined(audio):
      audioOnDeath(target.unitClass, target.pos)
    env.killAgent(target, attacker)
    return true
  false

# Heal an agent up to its max HP. Returns the amount actually healed.
# Optional healer param for audit tracking.
proc applyAgentHeal(env: Environment, target: Thing, amount: int,
                    healer: Thing = nil): int =
  let before = target.hp
  target.hp = min(target.maxHp, target.hp + amount)
  result = target.hp - before
  # Spawn floating heal number for feedback
  if result > 0:
    env.spawnDamageNumber(target.pos, result, DmgNumHeal)
  when defined(combatAudit):
    if result > 0 and not healer.isNil:
      recordHeal(env.currentStep, getTeamId(healer), getTeamId(target),
                 healer.agentId, target.agentId, result,
                 $healer.unitClass, $target.unitClass)

# Centralized zero-HP handling so agents instantly freeze/die when drained
proc enforceZeroHpDeaths(env: Environment) =
  for agent in env.agents:
    if env.terminated[agent.agentId] == 0.0 and agent.hp <= 0:
      env.killAgent(agent)
