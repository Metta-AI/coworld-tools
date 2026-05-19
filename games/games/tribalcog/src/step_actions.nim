# Step Actions - Agent action constants and dispatch tables
# This file is included by step.nim

# ============================================================================
# Action Visual Constants
# ============================================================================

const
  ConversionTint = TileColor(r: 0.95, g: 0.85, b: 0.35, intensity: 1.25)  # Golden divine glow

# ============================================================================
# Compile-Time Dispatch Tables
# ============================================================================
# Replace runtime case/branching with array lookups indexed by AgentUnitClass
# enum ordinal. This eliminates branch mispredictions in hot paths by converting
# conditional logic to direct memory loads.

const
  ## Base ranged attack range per unit class (0 = melee)
  UnitRangedRange: array[AgentUnitClass, int] = [
    UnitVillager: 0, UnitManAtArms: 0, UnitArcher: ArcherBaseRange,
    UnitScout: 0, UnitKnight: 0, UnitMonk: 0,
    UnitBatteringRam: 0, UnitMangonel: 0, UnitTrebuchet: TrebuchetBaseRange,
    UnitGoblin: 0, UnitBoat: 0, UnitTradeCog: 0,
    UnitSamurai: 0, UnitLongbowman: ArcherBaseRange + 2, UnitCataphract: 0,
    UnitWoadRaider: 0, UnitTeutonicKnight: 0, UnitHuskarl: 0,
    UnitMameluke: 2, UnitJanissary: 2, UnitKing: 0,
    UnitLongSwordsman: 0, UnitChampion: 0,
    UnitLightCavalry: 0, UnitHussar: 0,
    UnitCrossbowman: ArcherBaseRange, UnitArbalester: ArcherBaseRange,
    UnitGalley: GalleyBaseRange, UnitFireShip: 0,
    UnitFishingShip: 0, UnitTransportShip: 0, UnitDemoShip: 0, UnitCannonGalleon: CannonGalleonBaseRange,
    UnitScorpion: ScorpionBaseRange,
    UnitCavalier: 0, UnitPaladin: 0,
    UnitCamel: 0, UnitHeavyCamel: 0, UnitImperialCamel: 0,
    # Archery Range units
    UnitSkirmisher: SkirmisherBaseRange, UnitEliteSkirmisher: SkirmisherBaseRange,
    UnitCavalryArcher: CavalryArcherBaseRange, UnitHeavyCavalryArcher: CavalryArcherBaseRange,
    UnitHandCannoneer: HandCannoneerBaseRange,
  ]

  ## Units eligible for Ballistics tech damage bonus
  BallisticsUnits: set[AgentUnitClass] = {
    UnitArcher, UnitLongbowman, UnitJanissary, UnitCrossbowman, UnitArbalester,
    UnitGalley, UnitScorpion, UnitSkirmisher, UnitEliteSkirmisher,
    UnitCavalryArcher, UnitHeavyCavalryArcher, UnitHandCannoneer
  }

  ## Units eligible for Siege Engineers tech range bonus
  SiegeUnits: set[AgentUnitClass] = {
    UnitBatteringRam, UnitMangonel, UnitTrebuchet
  }

  ## Cavalry units that get double-move in step
  CavalryMoveUnits: set[AgentUnitClass] = {
    UnitScout, UnitKnight, UnitLightCavalry, UnitHussar,
    UnitCavalier, UnitPaladin, UnitCamel, UnitHeavyCamel, UnitImperialCamel,
    UnitCavalryArcher, UnitHeavyCavalryArcher
  }

  ## Units with charge attack (2-tile forward attack)
  ChargeAttackUnits: set[AgentUnitClass] = {
    UnitScout, UnitBatteringRam
  }

# ============================================================================
# Production Queue Ready Entry Handling
# ============================================================================

proc tryConsumeProductionQueue*(env: Environment, agent, thing: Thing): bool =
  ## If building has a ready production queue entry, convert villager to that unit.
  ## Returns true if conversion happened, false otherwise.
  if not thing.productionQueueHasReady():
    return false
  let unitClass = thing.consumeReadyQueueEntry()
  applyUnitClass(env, agent, unitClass)
  env.spawnSpawnEffect(agent.pos)
  if agent.inventorySpear > 0:
    agent.inventorySpear = 0
  if thing.hasRallyPoint():
    agent.rallyTarget = thing.rallyPoint
  return true

proc tryCraftAtBuilding*(env: Environment, agent, thing: Thing): bool =
  ## Try to craft at a building if it has a craft station and is off cooldown.
  ## Returns true if crafting happened, false otherwise.
  if thing.cooldown == 0 and buildingHasCraftStation(thing.kind):
    return env.tryCraftAtStation(agent, buildingCraftStation(thing.kind), thing)
  return false
