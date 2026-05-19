## constants.nim - Centralized game balance constants for tribal-village
##
## All gameplay-tunable numeric constants live here: damage values, HP, ranges,
## timings, costs, radii, and probabilities. This is the single source of truth
## for game balance tuning.
##
## Import order: This module has NO dependencies on other game modules.
## types.nim imports and re-exports this module.

const
  # ============================================================================
  # Agent Base Stats
  # ============================================================================
  AgentMaxHp* = 5

  # ============================================================================
  # Building HP
  # ============================================================================
  WallMaxHp* = 10
  OutpostMaxHp* = 8
  GuardTowerMaxHp* = 14
  TownCenterMaxHp* = 20
  CastleMaxHp* = 30
  MonasteryMaxHp* = 12
  WonderMaxHp* = 80
  DoorMaxHearts* = 5

  # ============================================================================
  # Building Attack
  # ============================================================================
  GuardTowerAttackDamage* = 2
  CastleAttackDamage* = 3
  TownCenterAttackDamage* = 2
  GuardTowerRange* = 4
  CastleRange* = 6
  TownCenterRange* = 6

  # ============================================================================
  # Building Garrison (AoE2-style)
  # ============================================================================
  TownCenterGarrisonCapacity* = 15
  CastleGarrisonCapacity* = 20
  GuardTowerGarrisonCapacity* = 5
  HouseGarrisonCapacity* = 5
  GarrisonArrowBonus* = 1
  GarrisonSeekRadius* = 15  # Max distance AI villagers will seek garrisonable buildings under threat
  TownBellAutoTriggerRadius* = 20  # Distance from TC to detect enemy army for auto-bell
  TownBellAutoTriggerCount* = 3    # Min enemies near base to auto-trigger bell
  TownBellAutoCheckInterval* = 10  # Steps between auto-trigger checks

  # ============================================================================
  # Siege
  # ============================================================================
  SiegeStructureMultiplier* = 3

  # ============================================================================
  # Construction
  # ============================================================================
  ConstructionBonusTable* = [1.0'f32, 1.0, 1.5, 1.83, 2.08, 2.28, 2.45, 2.59, 2.72]
  ConstructionHpPerAction* = 1
  RepairHpPerAction* = 2  ## Repair rate: faster than initial construction (AoE2-style)
  RoadWoodCost* = 1
  OutpostWoodCost* = 1

  # ============================================================================
  # Resource & Economy
  # ============================================================================
  ResourceCarryCapacity* = 5
  MineDepositAmount* = 100
  BarrelCapacity* = 50
  TeamColorNames* = [
    "RED", "ORANGE", "YELLOW", "GREEN", "MAGENTA", "BLUE", "GRAY", "PINK"
  ]
  ResourceNodeInitial* = 25
  TownCenterPopCap* = 5
  HousePopCap* = 4

  # ============================================================================
  # Wildlife Stats
  # ============================================================================
  CowMilkCooldown* = 25
  BearMaxHp* = 6
  BearAttackDamage* = 2

  BearAggroRadius* = 6
  WolfMaxHp* = 3
  WolfAttackDamage* = 1
  WolfPackMinSize* = 3
  WolfPackMaxSize* = 5
  WolfPackAggroRadius* = 7
  WolfPackCohesionRadius* = 3
  ScatteredDuration* = 10

  # Wildlife movement probabilities
  CowHerdFollowChance* = 0.6
  CowRandomMoveChance* = 0.08
  WolfPackFollowChance* = 0.55
  WolfRandomMoveChance* = 0.1
  WolfScatteredMoveChance* = 0.4
  BearRandomMoveChance* = 0.12

  # ============================================================================
  # Villager & Gatherer
  # ============================================================================
  VillagerAttackDamage* = 1
  GathererFleeRadius* = 8  # Radius at which gatherers flee from predators
  BuilderFleeRadius* = 8     # Radius at which builders flee from enemies
  BuilderThreatRadius* = 15  # Radius at which builder detects threat to base
  EarlyGameThreshold* = 0.25  # First quarter of game (steps 0-200 in 800-step game)
  MidGameThreshold* = 0.50    # Middle of game (steps 200-400)
  LateGameThreshold* = 0.75   # Last quarter of game (steps 600+)
  TaskSwitchHysteresis* = 5.0

  # Phase-dependent role allocation ratios (gatherer:builder:fighter out of 6 slots)
  # Early: 3 gatherers, 2 builders, 1 fighter (economy-heavy start)
  EarlyGameGatherers* = 3
  EarlyGameBuilders* = 2
  EarlyGameFighters* = 1
  # Mid: 2 gatherers, 2 builders, 2 fighters (balanced transition)
  MidGameGatherers* = 2
  MidGameBuilders* = 2
  MidGameFighters* = 2
  # Late: 2 gatherers, 1 builder, 3 fighters (military-heavy)
  LateGameGatherers* = 2
  LateGameBuilders* = 1
  LateGameFighters* = 3

  # Dynamic role re-assignment interval (steps between re-evaluations)
  RoleReassignInterval* = 50

  # Resource clustering / AoE-style gathering
  DropoffProximityRadius* = 10   # Resources within this radius of a drop-off building get a bonus
  MaxGatherersPerPatch* = 6      # Max gatherers before a patch is considered full
  PatchRadius* = 6               # Radius used to define a resource patch around a drop-off
  IdleAutoAssignSteps* = 8       # Steps idle before auto-assigning to a resource patch
  # ============================================================================
  # Military Unit Stats
  # ============================================================================
  # Man-at-Arms
  ManAtArmsAttackDamage* = 2
  ManAtArmsMaxHp* = 7

  # Archer
  ArcherAttackDamage* = 1
  ArcherMaxHp* = 5
  ArcherBaseRange* = 4

  # Scout
  ScoutAttackDamage* = 1
  ScoutMaxHp* = 6

  # Knight
  KnightAttackDamage* = 2
  KnightMaxHp* = 8

  # Monk
  MonkAttackDamage* = 0
  MonkMaxHp* = 20

  # Siege Units
  BatteringRamAttackDamage* = 2
  BatteringRamMaxHp* = 18
  MangonelAttackDamage* = 2
  MangonelMaxHp* = 12
  MangonelBaseRange* = 3
  MangonelAoELength* = 5
  TrebuchetAttackDamage* = 3
  TrebuchetMaxHp* = 14
  TrebuchetBaseRange* = 6
  TrebuchetPackDuration* = 15

  # Goblin
  GoblinAttackDamage* = 1
  GoblinMaxHp* = 4

  # Boat (embarked unit form)
  BoatAttackDamage* = 1
  BoatMaxHp* = 15

  # Trade Cog
  TradeCogAttackDamage* = 1
  TradeCogMaxHp* = 15
  TradeCogGoldPerDistance* = 1
  TradeCogDistanceDivisor* = 10

  # ============================================================================
  # Castle Unique Unit Stats
  # ============================================================================
  SamuraiMaxHp* = 12
  SamuraiAttackDamage* = 3
  LongbowmanMaxHp* = 10
  LongbowmanAttackDamage* = 2
  CataphractMaxHp* = 14
  CataphractAttackDamage* = 2
  WoadRaiderMaxHp* = 10
  WoadRaiderAttackDamage* = 2
  TeutonicKnightMaxHp* = 16
  TeutonicKnightAttackDamage* = 3
  HuskarlMaxHp* = 12
  HuskarlAttackDamage* = 2
  MamelukeMaxHp* = 10
  MamelukeAttackDamage* = 2
  JanissaryMaxHp* = 10
  JanissaryAttackDamage* = 3
  KingMaxHp* = 15
  KingAttackDamage* = 2

  # ============================================================================
  # Unit Upgrade Tiers (AoE2-style promotion chains)
  # ============================================================================
  LongSwordsmanMaxHp* = 9
  LongSwordsmanAttackDamage* = 3
  ChampionMaxHp* = 11
  ChampionAttackDamage* = 4
  LightCavalryMaxHp* = 8
  LightCavalryAttackDamage* = 2
  HussarMaxHp* = 10
  HussarAttackDamage* = 2
  CrossbowmanMaxHp* = 5
  CrossbowmanAttackDamage* = 2
  ArbalesterMaxHp* = 6
  ArbalesterAttackDamage* = 3

  # ============================================================================
  # Naval Combat Units
  # ============================================================================
  GalleyMaxHp* = 45
  GalleyAttackDamage* = 6
  GalleyBaseRange* = 3
  FireShipMaxHp* = 6
  FireShipAttackDamage* = 3
  FishingShipMaxHp* = 5
  FishingShipAttackDamage* = 0
  TransportShipMaxHp* = 10
  TransportShipAttackDamage* = 0
  TransportShipCapacity* = 5  # Max embarked units
  DemoShipMaxHp* = 4
  DemoShipAttackDamage* = 8  # High damage, single-use kamikaze
  CannonGalleonMaxHp* = 12
  CannonGalleonAttackDamage* = 4
  CannonGalleonBaseRange* = 5

  # ============================================================================
  # Additional Siege Units
  # ============================================================================
  ScorpionMaxHp* = 8
  ScorpionAttackDamage* = 2
  ScorpionBaseRange* = 4

  # ============================================================================
  # Stable Cavalry Upgrades (AoE2-style Knight line)
  # ============================================================================
  CavalierMaxHp* = 10
  CavalierAttackDamage* = 3
  PaladinMaxHp* = 12
  PaladinAttackDamage* = 4

  # ============================================================================
  # Camel Line (Counters cavalry, trained at Stable)
  # ============================================================================
  CamelMaxHp* = 7
  CamelAttackDamage* = 2
  HeavyCamelMaxHp* = 9
  HeavyCamelAttackDamage* = 2
  ImperialCamelMaxHp* = 11
  ImperialCamelAttackDamage* = 3

  # ============================================================================
  # Archery Range Units (AoE2-style)
  # ============================================================================
  # Skirmisher line (anti-archer ranged unit)
  SkirmisherMaxHp* = 5
  SkirmisherAttackDamage* = 2
  SkirmisherBaseRange* = 3
  EliteSkirmisherMaxHp* = 6
  EliteSkirmisherAttackDamage* = 3

  # Cavalry Archer line (mounted ranged unit)
  CavalryArcherMaxHp* = 6
  CavalryArcherAttackDamage* = 2
  CavalryArcherBaseRange* = 3
  HeavyCavalryArcherMaxHp* = 8
  HeavyCavalryArcherAttackDamage* = 3

  # Hand Cannoneer (powerful gunpowder ranged unit, no upgrades)
  HandCannoneerMaxHp* = 5
  HandCannoneerAttackDamage* = 4
  HandCannoneerBaseRange* = 4

  # ============================================================================
  # Monk Mechanics (AoE2-style)
  # ============================================================================
  MonkMaxFaith* = 10
  MonkConversionFaithCost* = 10
  MonkFaithRechargeRate* = 1
  MonasteryRelicGoldInterval* = 20
  MonasteryRelicGoldAmount* = 1

  # ============================================================================
  # Tech Costs
  # ============================================================================
  # Blacksmith upgrades
  BlacksmithUpgradeMaxLevel* = 3
  BlacksmithUpgradeFoodCost* = 3
  BlacksmithUpgradeGoldCost* = 2

  # University techs
  UniversityTechFoodCost* = 5
  UniversityTechGoldCost* = 1
  UniversityTechWoodCost* = 2

  # Castle unique techs
  CastleTechFoodCost* = 2
  CastleTechGoldCost* = 2
  CastleTechImperialFoodCost* = 4
  CastleTechImperialGoldCost* = 3

  # Unit upgrade costs
  UnitUpgradeTier2FoodCost* = 3
  UnitUpgradeTier2GoldCost* = 2
  UnitUpgradeTier3FoodCost* = 6
  UnitUpgradeTier3GoldCost* = 4

  # Economy techs (AoE2-style)
  # Town Center techs
  WheelbarrowFoodCost* = 4
  WheelbarrowWoodCost* = 2
  WheelbarrowCarryBonus* = 3
  WheelbarrowSpeedBonus* = 10  # +10% speed
  HandCartFoodCost* = 6
  HandCartWoodCost* = 3
  HandCartCarryBonus* = 7
  HandCartSpeedBonus* = 10  # +10% speed (stacks)

  # Lumber Camp techs
  DoubleBitAxeFoodCost* = 2
  DoubleBitAxeWoodCost* = 1
  DoubleBitAxeGatherBonus* = 20  # +20%
  BowSawFoodCost* = 3
  BowSawWoodCost* = 2
  BowSawGatherBonus* = 20  # +20% (stacks)
  TwoManSawFoodCost* = 4
  TwoManSawWoodCost* = 2
  TwoManSawGatherBonus* = 10  # +10% (stacks)

  # Mining Camp techs
  GoldMiningFoodCost* = 2
  GoldMiningWoodCost* = 1
  GoldMiningGatherBonus* = 15  # +15%
  GoldShaftMiningFoodCost* = 3
  GoldShaftMiningWoodCost* = 2
  GoldShaftMiningGatherBonus* = 15  # +15% (stacks)
  StoneMiningFoodCost* = 2
  StoneMiningWoodCost* = 1
  StoneMiningGatherBonus* = 15  # +15%
  StoneShaftMiningFoodCost* = 3
  StoneShaftMiningWoodCost* = 2
  StoneShaftMiningGatherBonus* = 15  # +15% (stacks)

  # Mill techs
  HorseCollarFoodCost* = 3
  HorseCollarWoodCost* = 2
  HorseCollarFarmBonus* = 75  # +75 farm food
  HeavyPlowFoodCost* = 4
  HeavyPlowWoodCost* = 2
  HeavyPlowFarmBonus* = 125  # +125 farm food (stacks)
  CropRotationFoodCost* = 5
  CropRotationWoodCost* = 3
  CropRotationFarmBonus* = 175  # +175 farm food (stacks)

  # Training costs (tooltip display; units without registry lookup)
  VillagerTrainFoodCost* = 2
  KnightTrainFoodCost* = 4
  KnightTrainGoldCost* = 3
  BoatTrainWoodCost* = 3

  # Farm auto-reseed cost
  FarmReseedWoodCost* = 1
  FarmReseedFoodCost* = 0

  # ============================================================================
  # Blacksmith Upgrade Bonuses
  # ============================================================================
  BlacksmithMeleeAttackBonus*: array[4, int] = [0, 1, 2, 4]
  BlacksmithArcherAttackBonus*: array[4, int] = [0, 1, 2, 3]
  BlacksmithInfantryArmorBonus*: array[4, int] = [0, 1, 2, 4]
  BlacksmithCavalryArmorBonus*: array[4, int] = [0, 1, 2, 4]
  BlacksmithArcherArmorBonus*: array[4, int] = [0, 1, 2, 4]

  BlacksmithMeleeAttackNames*: array[3, string] = ["Forging", "Iron Casting", "Blast Furnace"]
  BlacksmithArcherAttackNames*: array[3, string] = ["Fletching", "Bodkin Arrow", "Bracer"]
  BlacksmithInfantryArmorNames*: array[3, string] = ["Scale Mail", "Chain Mail", "Plate Mail"]
  BlacksmithCavalryArmorNames*: array[3, string] = ["Scale Barding", "Chain Barding", "Plate Barding"]
  BlacksmithArcherArmorNames*: array[3, string] = ["Padded Archer", "Leather Archer", "Ring Archer"]

  # ============================================================================
  # Production Queue (AoE2-style)
  # ============================================================================
  ProductionQueueMaxSize* = 10
  BatchTrainSmall* = 5
  BatchTrainLarge* = 10

  # ============================================================================
  # Victory Conditions
  # ============================================================================
  WonderVictoryCountdown* = 600
  RelicVictoryCountdown* = 200
  VictoryReward* = 10.0'f32
  HillControlRadius* = 5
  HillVictoryCountdown* = 300

  # ============================================================================
  # Attack Tint Durations
  # ============================================================================
  TowerAttackTintDuration* = 2'i8
  CastleAttackTintDuration* = 3'i8
  TownCenterAttackTintDuration* = 2'i8
  TankAuraTintDuration* = 1'i8
  MonkAuraTintDuration* = 1'i8
  DeathTintDuration* = 3'i8           # Death animation tint duration (steps)

  # ============================================================================
  # Aura Radii
  # ============================================================================
  ManAtArmsAuraRadius* = 1
  KnightAuraRadius* = 2
  MonkAuraRadius* = 2

  # ============================================================================
  # Mill & Spawner
  # ============================================================================
  MillFertileCooldown* = 10
  MaxTumorsPerSpawner* = 3
  MaxGlobalTumors* = int.high
  TumorSpawnCooldownBase* = 20.0
  TumorSpawnDisabledCooldown* = 1000

  # ============================================================================
  # Temple Cooldowns
  # ============================================================================
  TempleInteractionCooldown* = 12
  TempleHybridCooldown* = 25

  # ============================================================================
  # Combat AI Constants
  # ============================================================================
  # Target evaluation
  TargetSwapInterval* = 25     # Re-evaluate target every N ticks (perf: reduced from 10)
  LowHpThreshold* = 0.33      # Enemies below this HP ratio get priority
  AllyThreatRadius* = 2       # Distance at which enemy is considered threatening an ally
  EscortRadius* = 3           # Stay within this distance of the protected unit
  HoldPositionReturnRadius* = 3  # Max distance to drift from hold position
  HoldPositionEngageRadius* = 5  # Max distance to move toward enemies while holding position
  FollowProximityRadius* = 3  # Stay within this distance of followed target
  GuardRadius* = 5            # Stay within this distance of guarded target

  # Divider wall building
  DividerDoorSpacing* = 5
  DividerDoorOffset* = 0
  DividerHalfLengthMin* = 6
  DividerHalfLengthMax* = 18

  # Healing
  HealerSeekRadius* = 30      # Max distance to search for friendly monks
  MonkHealRadius* = 2         # Distance to stay near monk for healing (matches MonkAuraRadius)

  # Retreat
  RetreatAllySeekRadius* = 15 # Max distance to search for allied combat units when retreating
  RetreatAllyMinDist* = 3     # Minimum distance to ally (don't retreat if already close)

  # Kiting and siege detection
  KiteTriggerDistance* = 3    # Distance at which kiting triggers
  AntiSiegeDetectionRadius* = 12  # Distance to detect enemy siege units
  SiegeNearStructureRadius* = 5   # Siege units this close to structures get priority

  # Attack move
  AttackMoveDetectionRadius* = 8  # Distance to detect enemies while attack-moving
  FormationArrivalThreshold* = 1  # Distance at which formation slot is reached

  # Ranged formation
  RangedFormationSpacing* = 3     # Wider spacing for ranged units to avoid friendly fire
  RangedFormationRowOffset* = 2   # Offset between rows in ranged formation

  # Rally grouping
  RallyWaitSteps* = 15        # Max steps to wait at rally point for allies
  RallyMinGroupSize* = 3      # Min nearby allies to consider group formed

  # Scout behavior
  ScoutFleeRadius* = 10       # Distance at which scouts flee from enemies
  ScoutFleeRecoverySteps* = 30  # Steps after enemy sighting before resuming
  ScoutExploreGrowth* = 3     # How much to expand explore radius each cycle
  ScoutSectorRotationSteps* = 60  # Steps per sector rotation (cycles through NE/SE/SW/NW)

  # ============================================================================
  # Settlement (per-altar building association)
  # ============================================================================
  SettlementRadius*: int32 = 15  # Buildings within this Chebyshev distance of an altar belong to that settlement

  # ============================================================================
  # Wall Ring (Builder AI)
  # ============================================================================
  WallRingBaseRadius* = 5
  WallRingMaxRadius* = 12
  WallRingBuildingsPerRadius* = 4
  WallRingRadiusSlack* = 1
  WallRingMaxDoors* = 2
  MaxWallsPerTeam* = 40  # Reduced from 60 to limit wall obsession (tv-il11vv)

  # ============================================================================
  # Fortification
  # ============================================================================
  EnemyWallFortifyRadius* = 12

  # ============================================================================
  # AI Threat & Vision
  # ============================================================================
  ThreatVisionRange* = 12     # Range to detect threats
  ScoutVisionRange* = 18      # Scout extended vision range (50% larger than normal)
  ThreatDecaySteps* = 50      # Steps before threat decays
  ThreatUpdateStagger* = 4    # Only update threat map every N steps per agent

  # ============================================================================
  # Shadow Casting
  # ============================================================================
  # Light direction determines shadow offset (opposite to light source)
  # Using NW light source, so shadows cast to SE (positive X and Y)
  ShadowOffsetX* = 0.15'f32      # Shadow offset in X direction (positive = east)
  ShadowOffsetY* = 0.15'f32      # Shadow offset in Y direction (positive = south)
  ShadowAlpha* = 0.35'f32        # Shadow transparency (0.0 = invisible, 1.0 = opaque)

  # ============================================================================
  # Town Split (AI Settlement Expansion)
  # ============================================================================
  TownSplitPopulationThreshold* = 25  # Villagers per altar before split triggers
  TownSplitSettlerCount* = 10         # Number of settlers to send to new town
  TownSplitMinDistance* = 18          # Minimum tiles from old altar to new site
  TownSplitMaxDistance* = 25          # Maximum tiles from old altar to new site
  TownSplitCooldownSteps* = 200      # Steps between splits for the same team
  TownSplitCheckInterval* = 50       # Only check every N steps to save CPU
  TownSplitOpenSpaceRadius* = 1      # Radius around center that must be empty (3x3)

  # ============================================================================
  # Map Generation & Spawn
  # ============================================================================
  # Trading hub wall generation
  TradingHubWallChance* = 0.6          # Probability of placing wall segment
  TradingHubDriftChance* = 0.45        # Probability of wall edge drifting
  TradingHubSpurCountMin* = 8          # Minimum interior wall spurs
  TradingHubSpurCountMax* = 14         # Maximum interior wall spurs
  TradingHubSpurLengthMin* = 2         # Minimum spur length
  TradingHubSpurLengthMax* = 4         # Maximum spur length
  TradingHubTowerSlots* = 4            # Max guard towers per hub
  TradingHubCoreMultiplier* = 2        # Building count multiplier for core
  TradingHubScatterMultiplier* = 3     # Building count multiplier for scatter
  TradingHubMainBuildingMin* = 10      # Min core buildings per multiplier
  TradingHubMainBuildingMax* = 14      # Max core buildings per multiplier
  TradingHubExtraBuildingMin* = 6      # Min extra buildings per multiplier
  TradingHubExtraBuildingMax* = 10     # Max extra buildings per multiplier
  TradingHubScatterBuildingMin* = 24   # Min scatter buildings per multiplier
  TradingHubScatterBuildingMax* = 36   # Max scatter buildings per multiplier
  TradingHubScatterPadding* = 18       # Scatter radius beyond hub edge
  TradingHubScatterInnerPad* = 4       # Inner exclusion radius
  TradingHubBuildingAttempts* = 80     # Max attempts per building placement

  # Temple placement
  TempleMinDistance* = 10              # Min Chebyshev distance from village centers
  TemplePlacementAttempts* = 200       # Max attempts to place temple
  TemplePlacementRange* = 14           # Max offset from map center

  # Village structure
  VillageStructureSize* = 7            # Village layout grid size
  VillageStructureRadius* = 3          # Village center radius
  VillageFloorDistance* = 2            # Floor tile manhattan distance from center
  VillageTownCenterRange* = 3          # TC placement distance from altar

  # Resource cluster generation
  ClusterDensityHigh* = 0.85           # Dense resource placement probability
  ClusterDensityMedium* = 0.75         # Medium resource placement probability
  ClusterDensityLow* = 0.65            # Sparse resource placement probability
  ClusterFalloffSteep* = 0.45          # Fast density falloff from center
  ClusterFalloffNormal* = 0.4          # Normal density falloff
  ClusterMineSizeMin* = 3              # Minimum mine cluster size
  ClusterMineSizeMax* = 4              # Maximum mine cluster size

  # Fish cluster generation
  FishClusterSizeMin* = 3              # Minimum fish cluster size
  FishClusterSizeMax* = 7              # Maximum fish cluster size
  FishPlacementAttempts* = 20          # Max attempts per fish cluster

  # Bush/Foliage generation
  BushClusterCount* = 30               # Number of bush clusters to generate
  BushClusterSizeMin* = 3              # Minimum bush cluster size
  BushClusterSizeMax* = 7              # Maximum bush cluster size
  BushWaterProximity* = 4              # Prefer placing bushes near water

  # Contested resource zones (central map)
  ContestedZoneCount* = 3              # Number of contested resource zones
  ContestedZoneRadius* = 9             # Radius of each zone in tiles
  ContestedZoneGoldCount* = 4          # Gold mines per zone
  ContestedZoneStoneCount* = 3         # Stone mines per zone
  ContestedZoneWheatSize* = 6          # Wheat cluster size per zone
  ContestedZoneBushSize* = 5           # Bush cluster size per zone
  ContestedZoneCowCount* = 4           # Cows per zone
  ContestedZoneRelics* = 1             # Relics per zone
  ContestedZoneHubClearance* = 12      # Min distance from trading hub center

  # ============================================================================
  # UI Interaction
  # ============================================================================
  DragDistanceThreshold* = 5.0'f32     # Pixels to trigger drag mode
  DoubleTapThreshold* = 0.3            # Seconds between taps for double-tap
  ZoomSensitivityDesktop* = 0.005      # Zoom scroll sensitivity (desktop)
  ZoomSensitivityWeb* = 0.002          # Zoom scroll sensitivity (emscripten)
  VelocityDecayRate* = 0.85'f32        # Camera velocity decay per frame (lower = faster stop)
  CameraPanAccel* = 1.8'f32           # Camera pan acceleration per frame (pixels)
  CameraPanMaxSpeed* = 14.0'f32       # Maximum camera pan speed (pixels/frame)
  CameraSnapThreshold* = 0.5'f32      # Stop velocity below this threshold
  ZoomSmoothRate* = 0.15'f32          # Zoom interpolation rate per frame (0-1)
  MinVisibleMapPixels* = 500.0'f32     # Minimum visible map area in pixels

  # Selection box rendering
  SelectionBoxLineWidth* = 0.05'f32    # Line width in world units
  SelectionBoxColorR* = 0.2'f32        # Selection box red component
  SelectionBoxColorG* = 0.9'f32        # Selection box green component
  SelectionBoxColorB* = 0.2'f32        # Selection box blue component
  SelectionBoxAlpha* = 0.8'f32         # Selection box opacity

  # ============================================================================
  # Minimap
  # ============================================================================
  MinimapBrightnessMult* = 280         # Agent color brightness multiplier
  MinimapBrightnessMin* = 60           # Minimum agent color component
  MinimapWallGray* = 100               # Wall color (gray value 0-255)
  MinimapRebuildInterval* = 10         # Frames between full rebuilds
  MinimapBorderWidth* = 2.0'f32        # Border line width in pixels
  MinimapBorderExpand* = 4.0'f32       # Border expansion amount
  MinimapViewportLineWidth* = 1.5'f32  # Viewport indicator line width
  MinimapViewportAlpha* = 0.85'f32     # Viewport indicator opacity

  # ============================================================================
  # Projectile Timing
  # ============================================================================
  ProjArrowBaseLifetime* = 1           # Base arrow flight frames
  ProjArrowMaxLifetime* = 4            # Maximum arrow flight frames
  ProjMangonelAddedFrames* = 2         # Extra frames for mangonel
  ProjMangonelMaxLifetime* = 6         # Maximum mangonel flight frames
  ProjTrebuchetAddedFrames* = 3        # Extra frames for trebuchet
  ProjTrebuchetMaxLifetime* = 8        # Maximum trebuchet flight frames

  # ============================================================================
  # Tribute System (AoE2-style resource transfer between teams)
  # ============================================================================
  TributeTaxRate* = 0.20          ## 20% fee on tributes (AoE2 default)
  CoinageTaxReduction* = 0.10     ## Coinage tech reduces fee to 10%
  TributeMinAmount* = 1           ## Minimum tribute amount

  # Derived constants
  VillagerMaxHp* = AgentMaxHp

proc teamColorName*(teamId: int): string {.inline.} =
  if teamId >= 0 and teamId < TeamColorNames.len:
    TeamColorNames[teamId]
  elif teamId == TeamColorNames.len:
    "GOBLIN"
  else:
    "NEUTRAL"
