## types.nim - Forward type declarations for tribal-village
##
## This module provides type definitions that multiple modules need access to,
## breaking circular dependency chains. All fundamental types should be defined here.
##
## Import order for modules using these types:
##   1. types (this file) - for type definitions
##   2. Other modules that use these types

import std/[tables, sets, hashes], vmath, chroma
import terrain, items, common_types, constants
export terrain, items, common_types, constants

# Re-export key types from dependencies
export tables, vmath, chroma

const
  # Map Layout
  MapLayoutRoomsX* = 1
  MapLayoutRoomsY* = 1
  MapBorder* = 1
  MapRoomWidth* = 305  # ~6% larger than 288
  MapRoomHeight* = 191  # ~6% larger than 180
  MapRoomBorder* = 0

  # World Objects
  # Eight teams with 125 agents each -> 1000 agents total.
  MapRoomObjectsTeams* = 8
  GoblinTeamId* = MapRoomObjectsTeams
  MapAgentsPerTeam* = 125
  MapRoomObjectsGoblinAgents* = 6
  MapRoomObjectsAgents* = MapRoomObjectsTeams * MapAgentsPerTeam + MapRoomObjectsGoblinAgents
    ## Agent slots across all teams plus goblins
  MapRoomObjectsMagmaPools* = 72
  MapRoomObjectsMagmaClusters* = 36
  MapRoomObjectsStoneClusters* = 48
  MapRoomObjectsStoneClusterCount* = 28
  MapRoomObjectsGoldClusters* = 48
  MapRoomObjectsGoldClusterCount* = 28
  MapRoomObjectsWalls* = 30
  MapRoomObjectsCows* = 24
  MapRoomObjectsBears* = 6
  MapRoomObjectsWolves* = 12
  MapRoomObjectsRelics* = 18
  MapRoomObjectsGoblinHuts* = 3
  MapRoomObjectsGoblinTotems* = 2

  # Agent Parameters
  MapObjectAgentMaxInventory* = 5

  # Building Parameters
  MapObjectAltarInitialHearts* = 5
  MapObjectAltarCooldown* = 0
  MapObjectAltarRespawnCost* = 0
  MapObjectAltarAutoSpawnThreshold* = 5
  BuildIndexGuardTower* = 23
  BuildIndexMangonelWorkshop* = 24
  BuildIndexWall* = 14
  BuildIndexRoad* = 15
  BuildIndexDoor* = 19

  # Gameplay
  MinTintEpsilon* = 5

  # Observation System
  ObservationWidth* = 11
  ObservationHeight* = 11

  # Action tint observation codes (TintLayer values)
  ActionTintNone* = 0'u8
  ActionTintAttackVillager* = 1'u8
  ActionTintAttackManAtArms* = 2'u8
  ActionTintAttackArcher* = 3'u8
  ActionTintAttackScout* = 4'u8
  ActionTintAttackKnight* = 5'u8
  ActionTintAttackMonk* = 6'u8
  ActionTintAttackBatteringRam* = 7'u8
  ActionTintAttackMangonel* = 8'u8
  ActionTintAttackTrebuchet* = 9'u8
  ActionTintAttackBoat* = 10'u8
  ActionTintAttackTower* = 11'u8
  ActionTintAttackCastle* = 12'u8
  ActionTintAttackBonus* = 13'u8
  ActionTintBonusArcher* = 14'u8     # Archer counter bonus (vs infantry)
  ActionTintBonusInfantry* = 15'u8   # Infantry counter bonus (vs cavalry)
  ActionTintBonusScout* = 16'u8      # Scout counter bonus (vs archers)
  ActionTintBonusKnight* = 17'u8     # Knight counter bonus (vs archers)
  ActionTintBonusBatteringRam* = 18'u8  # Battering ram siege bonus (vs structures)
  ActionTintBonusMangonel* = 19'u8   # Mangonel siege bonus (vs structures)
  ActionTintBonusTrebuchet* = 20'u8  # Trebuchet siege bonus (vs structures)
  ActionTintShield* = 21'u8
  ActionTintHealMonk* = 30'u8
  ActionTintHealBread* = 31'u8
  ActionTintConvertMonk* = 32'u8  # Monk conversion (enemy to friendly)
  ActionTintMixed* = 200'u8
  # Castle unique unit attack tints
  ActionTintAttackSamurai* = 40'u8
  ActionTintAttackLongbowman* = 41'u8
  ActionTintAttackCataphract* = 42'u8
  ActionTintAttackWoadRaider* = 43'u8
  ActionTintAttackTeutonicKnight* = 44'u8
  ActionTintAttackHuskarl* = 45'u8
  ActionTintAttackMameluke* = 46'u8
  ActionTintAttackJanissary* = 47'u8
  ActionTintAttackKing* = 48'u8
  # Unit upgrade tier attack tints
  ActionTintAttackLongSwordsman* = 49'u8
  ActionTintAttackChampion* = 50'u8
  ActionTintAttackLightCavalry* = 51'u8
  ActionTintAttackHussar* = 52'u8
  ActionTintAttackCrossbowman* = 53'u8
  ActionTintAttackArbalester* = 54'u8
  # Naval combat units
  ActionTintAttackGalley* = 55'u8
  ActionTintAttackFireShip* = 56'u8
  # Additional siege unit
  ActionTintAttackScorpion* = 57'u8
  ActionTintDeath* = 60'u8            # Death animation tint at kill location

  # Computed Values
  MapAgents* = MapRoomObjectsAgents * MapLayoutRoomsX * MapLayoutRoomsY
  MapWidth* = MapLayoutRoomsX * (MapRoomWidth + MapRoomBorder) + MapBorder
  MapHeight* = MapLayoutRoomsY * (MapRoomHeight + MapRoomBorder) + MapBorder

  # Compile-time optimization constants
  ObservationRadius* = ObservationWidth div 2  # 5 - computed once

type
  ## Team bitmask for O(1) team membership checks
  ## Each team (0-7) is represented by a single bit: Team N = 1 << N
  ## This enables bitwise operations for alliance/visibility checks
  TeamMask* = uint8

const
  ## Pre-computed team masks for teams 0-7
  ## TeamMasks[N] = 1 << N, with special case for invalid teams
  TeamMasks*: array[MapRoomObjectsTeams + 1, TeamMask] = [
    0b00000001'u8,  # Team 0
    0b00000010'u8,  # Team 1
    0b00000100'u8,  # Team 2
    0b00001000'u8,  # Team 3
    0b00010000'u8,  # Team 4
    0b00100000'u8,  # Team 5
    0b01000000'u8,  # Team 6
    0b10000000'u8,  # Team 7
    0b00000000'u8   # Goblins/invalid (no team affiliation)
  ]

  ## Mask with all valid teams set (for alliance systems)
  AllTeamsMask*: TeamMask = 0b11111111'u8

  ## Empty mask (no team affiliation)
  NoTeamMask*: TeamMask = 0b00000000'u8

{.push inline.}
proc getTeamId*(agentId: int): int =
  ## Inline team ID calculation - frequently used
  agentId div MapAgentsPerTeam

proc getTeamMask*(teamId: int): TeamMask =
  ## Convert team ID to bitmask for O(1) bitwise team checks.
  ## Returns NoTeamMask for invalid team IDs (< 0 or >= MapRoomObjectsTeams).
  if teamId >= 0 and teamId < MapRoomObjectsTeams:
    TeamMasks[teamId]
  else:
    NoTeamMask

proc isTeamInMask*(teamId: int, mask: TeamMask): bool =
  ## Check if a team is included in a bitmask. O(1) operation.
  (getTeamMask(teamId) and mask) != 0

proc teamsShareMask*(maskA, maskB: TeamMask): bool =
  ## Check if two masks have any overlapping teams (for alliance checks).
  (maskA and maskB) != 0


template isValidPos*(pos: IVec2): bool =
  ## Inline bounds checking template - very frequently used
  pos.x >= 0 and pos.x < MapWidth and pos.y >= 0 and pos.y < MapHeight

const
  MaxTintAccum* = 50_000_000'i32

template safeTintAdd*(tintMod: var int32, delta: int): void =
  ## Safe tint accumulation with overflow protection
  let clampedDelta = max(-MaxTintAccum, min(MaxTintAccum, delta.int32))
  tintMod = max(-MaxTintAccum, min(MaxTintAccum, tintMod + clampedDelta))
{.pop.}

type
  ObservationName* = enum
    TerrainEmptyLayer = 0
    TerrainWaterLayer
    TerrainBridgeLayer
    TerrainFertileLayer
    TerrainRoadLayer
    TerrainGrassLayer
    TerrainDuneLayer
    TerrainSandLayer
    TerrainSnowLayer
    TerrainMountainLayer
    TerrainRampUpNLayer
    TerrainRampUpSLayer
    TerrainRampUpWLayer
    TerrainRampUpELayer
    TerrainRampDownNLayer
    TerrainRampDownSLayer
    TerrainRampDownWLayer
    TerrainRampDownELayer

    ThingAgentLayer
    ThingWallLayer
    ThingDoorLayer
    ThingTreeLayer
    ThingWheatLayer
    ThingFishLayer
    ThingRelicLayer
    ThingStoneLayer
    ThingGoldLayer
    ThingBushLayer
    ThingCactusLayer
    ThingStalagmiteLayer
    ThingMagmaLayer
    ThingAltarLayer
    ThingSpawnerLayer
    ThingTumorLayer
    ThingCowLayer
    ThingBearLayer
    ThingWolfLayer
    ThingCorpseLayer
    ThingSkeletonLayer
    ThingClayOvenLayer
    ThingWeavingLoomLayer
    ThingOutpostLayer
    ThingGuardTowerLayer
    ThingBarrelLayer
    ThingMillLayer
    ThingGranaryLayer
    ThingLumberCampLayer
    ThingQuarryLayer
    ThingMiningCampLayer
    ThingStumpLayer
    ThingLanternLayer
    ThingTownCenterLayer
    ThingHouseLayer
    ThingBarracksLayer
    ThingArcheryRangeLayer
    ThingStableLayer
    ThingSiegeWorkshopLayer
    ThingMangonelWorkshopLayer
    ThingTrebuchetWorkshopLayer
    ThingBlacksmithLayer
    ThingMarketLayer
    ThingDockLayer
    ThingMonasteryLayer
    ThingUniversityLayer
    ThingCastleLayer
    ThingWonderLayer
    ThingGoblinHiveLayer
    ThingGoblinHutLayer
    ThingGoblinTotemLayer
    ThingStubbleLayer
    ThingCliffEdgeNLayer
    ThingCliffEdgeELayer
    ThingCliffEdgeSLayer
    ThingCliffEdgeWLayer
    ThingCliffCornerInNELayer
    ThingCliffCornerInSELayer
    ThingCliffCornerInSWLayer
    ThingCliffCornerInNWLayer
    ThingCliffCornerOutNELayer
    ThingCliffCornerOutSELayer
    ThingCliffCornerOutSWLayer
    ThingCliffCornerOutNWLayer
    ThingWaterfallNLayer
    ThingWaterfallELayer
    ThingWaterfallSLayer
    ThingWaterfallWLayer

    TeamLayer                 # Team id + 1, 0 = none/neutral
    AgentOrientationLayer     # Orientation enum + 1, 0 = none
    AgentUnitClassLayer       # Unit class enum + 1, 0 = none
    AgentIdleLayer            # 1 if agent is idle (NOOP/ORIENT action), 0 otherwise
    TintLayer                 # Action/combat tint codes
    RallyPointLayer           # 1 if a friendly building has its rally point on this tile
    BiomeLayer                # Biome type enum value
    GarrisonCountLayer        # Garrison fill ratio: (count * 255) div capacity, 0 = empty/not garrisonable
    RelicCountLayer           # Monastery relic count (direct value, 0-255)
    ProductionQueueLenLayer   # Number of units in production queue (direct value, 0-255)
    BuildingHpLayer           # Building HP ratio: (hp * 255) div maxHp, 0 = none
    MonkFaithLayer            # Monk faith ratio: (faith * 255) div MonkMaxFaith
    TrebuchetPackedLayer      # 1 if trebuchet is packed (mobile), 0 if unpacked (stationary)
    UnitStanceLayer           # AgentStance enum + 1 (0 = none/not an agent)
    ObscuredLayer             # 1 when target tile is above observer elevation

const
  ## Layer aliases for semantic clarity. These map to Thing layers since
  ## updateObservations is a no-op (observations rebuilt in batch at step end).
  AgentLayer* = ThingAgentLayer
  altarHeartsLayer* = ThingAltarLayer

type
  AgentStance* = enum
    StanceAggressive    ## Chase enemies, attack anything in sight
    StanceDefensive     ## Only attack if attacked (retaliation mode)
    StanceStandGround   ## Don't move, only attack what's in range (hold position)
    StanceNoAttack      ## Never auto-attack, useful for scouts

  AgentUnitClass* = enum
    UnitVillager
    UnitManAtArms
    UnitArcher
    UnitScout
    UnitKnight
    UnitMonk
    UnitBatteringRam
    UnitMangonel
    UnitTrebuchet
    UnitGoblin
    UnitBoat
    UnitTradeCog   # Water-based trade unit, generates gold between Docks
    # Castle unique units (one per civilization/team)
    UnitSamurai        # Team 0: Fast infantry, high damage
    UnitLongbowman     # Team 1: Extended range archer
    UnitCataphract     # Team 2: Heavy cavalry
    UnitWoadRaider     # Team 3: Fast infantry
    UnitTeutonicKnight # Team 4: Slow but very tough
    UnitHuskarl        # Team 5: Anti-archer infantry
    UnitMameluke       # Team 6: Ranged cavalry
    UnitJanissary      # Team 7: Powerful ranged unit
    UnitKing           # Regicide mode: team leader, high HP, limited combat
    # Unit upgrade tiers (AoE2-style promotion chains)
    UnitLongSwordsman  # ManAtArms upgrade tier 2
    UnitChampion       # ManAtArms upgrade tier 3
    UnitLightCavalry   # Scout upgrade tier 2
    UnitHussar         # Scout upgrade tier 3
    UnitCrossbowman    # Archer upgrade tier 2
    UnitArbalester     # Archer upgrade tier 3
    # Naval combat units
    UnitGalley         # Combat warship, ranged attack on water
    UnitFireShip       # Anti-ship fire unit, bonus vs water units
    UnitFishingShip    # Economic fishing unit, gathers fish
    UnitTransportShip  # Cargo transport, carries embarked units
    UnitDemoShip       # Demolition ship, bonus vs buildings and ships
    UnitCannonGalleon  # Late-game artillery ship, ranged siege
    # Additional siege unit
    UnitScorpion       # Anti-infantry siege ballista, ranged
    # Stable cavalry upgrades (AoE2-style)
    UnitCavalier       # Knight upgrade tier 2
    UnitPaladin        # Knight upgrade tier 3
    # Camel line (trained at Stable, counters cavalry)
    UnitCamel          # Base camel rider
    UnitHeavyCamel     # Camel upgrade tier 2
    UnitImperialCamel  # Camel upgrade tier 3
    # Archery Range units (AoE2-style)
    UnitSkirmisher        # Anti-archer ranged unit
    UnitEliteSkirmisher   # Skirmisher upgrade tier 2
    UnitCavalryArcher     # Mounted ranged unit
    UnitHeavyCavalryArcher # Cavalry Archer upgrade tier 2
    UnitHandCannoneer     # Powerful gunpowder ranged unit (no upgrades)

const
  ## Tank units with shield auras (ManAtArms and Knight)
  ## Used for optimized aura processing collections
  TankUnitClasses*: set[AgentUnitClass] = {UnitManAtArms, UnitKnight, UnitCavalier, UnitPaladin}

  ## Ranged units that benefit from spread formations to avoid friendly fire
  ## Includes archers, ranged siege, and ranged unique units
  RangedUnitClasses*: set[AgentUnitClass] = {
    UnitArcher, UnitLongbowman, UnitJanissary, UnitCrossbowman, UnitArbalester,
    UnitMangonel, UnitTrebuchet, UnitGalley, UnitCannonGalleon, UnitScorpion,
    UnitSkirmisher, UnitEliteSkirmisher, UnitCavalryArcher, UnitHeavyCavalryArcher,
    UnitHandCannoneer
  }

  ## Display labels for AgentStance
  StanceLabels*: array[AgentStance, string] = [
    "Aggressive",
    "Defensive",
    "Stand Ground",
    "No Attack"
  ]

  ## Display labels for AgentUnitClass
  UnitClassLabels*: array[AgentUnitClass, string] = [
    "Villager",
    "Man-at-Arms",
    "Archer",
    "Scout",
    "Knight",
    "Monk",
    "Battering Ram",
    "Mangonel",
    "Trebuchet",
    "Goblin",
    "Boat",
    "Trade Cog",
    # Castle unique units
    "Samurai",
    "Longbowman",
    "Cataphract",
    "Woad Raider",
    "Teutonic Knight",
    "Huskarl",
    "Mameluke",
    "Janissary",
    "King",
    # Unit upgrade tiers
    "Long Swordsman",
    "Champion",
    "Light Cavalry",
    "Hussar",
    "Crossbowman",
    "Arbalester",
    # Naval combat units
    "Galley",
    "Fire Ship",
    "Fishing Ship",
    "Transport Ship",
    "Demolition Ship",
    "Cannon Galleon",
    # Additional siege unit
    "Scorpion",
    # Stable cavalry upgrades
    "Cavalier",
    "Paladin",
    # Camel line
    "Camel Rider",
    "Heavy Camel Rider",
    "Imperial Camel Rider",
    # Archery Range units
    "Skirmisher",
    "Elite Skirmisher",
    "Cavalry Archer",
    "Heavy Cavalry Archer",
    "Hand Cannoneer"
  ]

type
  ThingKind* = enum
    Agent
    Wall
    Door
    Tree
    Wheat
    Fish
    Relic
    Stone
    Gold
    Bush
    Cactus
    Stalagmite
    Magma  # Smelts gold into bars
    Altar
    Spawner
    Tumor
    Cow
    Bear
    Wolf
    Corpse
    Skeleton
    ClayOven
    WeavingLoom
    Outpost
    GuardTower
    Barrel
    Mill
    Granary
    LumberCamp
    Quarry
    MiningCamp
    Stump
    Lantern  # Lanterns that spread team colors
    TownCenter
    House
    Barracks
    ArcheryRange
    Stable
    SiegeWorkshop
    MangonelWorkshop
    TrebuchetWorkshop
    Blacksmith
    Market
    Dock
    Monastery
    Temple
    University
    Castle
    Wonder             # AoE2-style Wonder victory building
    ControlPoint       # King of the Hill control point
    GoblinHive
    GoblinHut
    GoblinTotem
    Stubble  # Harvested wheat residue
    CliffEdgeN
    CliffEdgeE
    CliffEdgeS
    CliffEdgeW
    CliffCornerInNE
    CliffCornerInSE
    CliffCornerInSW
    CliffCornerInNW
    CliffCornerOutNE
    CliffCornerOutSE
    CliffCornerOutSW
    CliffCornerOutNW
    WaterfallN         # Waterfall where water flows north (higher ground to north)
    WaterfallE         # Waterfall where water flows east
    WaterfallS         # Waterfall where water flows south
    WaterfallW         # Waterfall where water flows west

const
  TerrainLayerStart* = ord(TerrainEmptyLayer)
  TerrainLayerCount* = ord(TerrainType.high) + 1
  ThingLayerStart* = ord(ThingAgentLayer)
  ThingLayerCount* = ord(ThingKind.high) + 1
  ObservationLayers* = ord(ObservationName.high) + 1
  ## Tank units with shield auras (ManAtArms and Knight)
  TankAuraUnits*: set[AgentUnitClass] = {
    UnitManAtArms, UnitKnight, UnitCavalier, UnitPaladin
  }

type
  ProductionQueueEntry* = object
    ## A single entry in a building's production queue (AoE2-style)
    unitClass*: AgentUnitClass
    totalSteps*: int        ## Original training duration for progress calculation
    remainingSteps*: int

  ProductionQueue* = object
    ## Building production queue for training units over time (AoE2-style)
    entries*: seq[ProductionQueueEntry]

  Thing* = ref object
    kind*: ThingKind
    pos*: IVec2
    id*: int
    layer*: int
    cooldown*: int
    frozen*: int
    thingsIndex*: int
    kindListIndex*: int

    # Agent:
    agentId*: int
    orientation*: Orientation
    inventory*: Inventory
    barrelCapacity*: int
    reward*: float32
    hp*: int
    maxHp*: int
    attackDamage*: int
    kills*: int                 # Number of enemy units killed (for veterancy)
    unitClass*: AgentUnitClass
    stance*: AgentStance        # Combat stance mode (Aggressive/Defensive/StandGround/NoAttack)
    lastAttackedStep*: int      # Step when this unit was last attacked (for defensive stance retaliation)
    isIdle*: bool               # True if agent took NOOP/ORIENT action last step (AoE2-style idle detection)
    embarkedUnitClass*: AgentUnitClass
    teamIdOverride*: int
    homeAltar*: IVec2      # Position of agent's home altar for respawning
    isGarrisoned*: bool    # True if this agent is garrisoned inside a building
    isSettler*: bool               # Whether this agent is migrating to found a new town
    settlerTarget*: IVec2          # Target position for settler migration (-1,-1 = none)
    settlerArrived*: bool          # Whether settler has arrived at the target site
    movementDebt*: float32     # Accumulated terrain penalty (movement skipped when >= 1.0)
    herdId*: int               # Cow herd grouping id
    packId*: int               # Wolf pack grouping id
    isPackLeader*: bool        # Whether this wolf is the pack leader
    scatteredSteps*: int       # Remaining steps of scattered state after leader death
    # Trebuchet:
    packed*: bool              # Trebuchet pack state (true=packed/mobile, false=unpacked/stationary)
    # Trade Cog:
    tradeHomeDock*: IVec2      # Position of origin dock for trade route gold calculation
    # Monk:
    faith*: int                # Current faith points for conversion (AoE2-style)
    # Tumor:
    homeSpawner*: IVec2     # Position of tumor's home spawner
    hasClaimedTerritory*: bool  # Whether this tumor has already branched and is now inert
    turnsAlive*: int            # Number of turns this tumor has been alive

    # Lantern:
    teamId*: int               # Which team this lantern belongs to (for color spreading)
    teamMask*: TeamMask        # Cached team bitmask (1 shl teamId) for O(1) spatial queries
    lanternHealthy*: bool      # Whether lantern is active (not destroyed by tumor)

    # Garrison (TownCenter, Castle, GuardTower, House):
    garrisonedUnits*: seq[Thing]  # Units currently garrisoned inside this building
    townBellActive*: bool         # True when town bell is ringing, recalling villagers

    # Monastery:
    garrisonedRelics*: int     # Number of relics garrisoned for gold generation

    # Production queue (AoE2-style):
    productionQueue*: ProductionQueue  # Queue of units being trained at this building

    # Rally point (AoE2-style):
    rallyPoint*: IVec2  # Building: where trained units auto-move after spawning (-1,-1 = none)
    rallyTarget*: IVec2  # Agent: assigned rally destination after training (-1,-1 = none)

    # Wonder victory:
    constructed*: bool            # True once building first reaches maxHp (distinguishes repair from construction)
    wonderVictoryCountdown*: int  # Steps remaining to hold Wonder for victory

    # Tint tracking:
    lastTintPos*: IVec2        # Last position where tint was applied (for delta optimization)

    # Mill farm queue (AoE2-style auto-reseed):
    farmQueue*: seq[IVec2]     # Queue of farm positions to auto-reseed when stubble appears
    queuedFarmReseeds*: int    # Pre-paid farm reseeds (player queues these at Mill)

    # Spawner: (no longer needs altar targeting for new creep spread behavior)

  PoolStats* = object
    acquired*: int
    released*: int
    poolSize*: int

  ThingPool* = object
    free*: array[ThingKind, seq[Thing]]
    stats*: PoolStats

  ProjectilePool* = object
    ## Pool statistics for projectile allocation tracking.
    ## Projectiles use seq with pre-allocated capacity to avoid growth allocations.
    stats*: PoolStats

proc hash*(t: Thing): Hash =
  hash(cast[pointer](t))

const
  ## Thing kinds eligible for object pooling (frequently created/destroyed)
  PoolableKinds* = {Tumor, Corpse, Skeleton, Stubble, Lantern, Stump}

  ## Initial capacity for projectile pool (avoids growth allocations during combat)
  ProjectilePoolCapacity* = 128

  ## Initial capacity for action tint positions (avoids growth during combat)
  ActionTintPoolCapacity* = 256

  ## Default capacity for arena-backed sequences
  ArenaDefaultCap* = 1024

type
  Arena* = object
    ## Collection of pre-allocated temporary sequences for per-step use.
    ## All sequences reset to len=0 at step start but retain their capacity.

    # Thing-typed scratch buffers (most common case)
    things1*: seq[Thing]
    things2*: seq[Thing]
    things3*: seq[Thing]
    things4*: seq[Thing]

    # Position scratch buffers
    positions1*: seq[IVec2]
    positions2*: seq[IVec2]

    # Int scratch buffers (for indices, counts, etc.)
    ints1*: seq[int]
    ints2*: seq[int]

    # Generic tuple buffer for inventory-like data
    itemCounts*: seq[tuple[key: ItemKey, count: int]]

    # String buffer for formatting
    strings*: seq[string]

const
  # Spatial index constants
  SpatialCellSize* = 16  # Tiles per spatial cell
  SpatialCellsX* = (MapWidth + SpatialCellSize - 1) div SpatialCellSize
  SpatialCellsY* = (MapHeight + SpatialCellSize - 1) div SpatialCellSize

when defined(spatialAutoTune):
  const
    SpatialAutoTuneThreshold* = 32  ## Max entities per cell before rebalance
    SpatialMinCellSize* = 4         ## Minimum cell size in tiles
    SpatialMaxCellSize* = 64        ## Maximum cell size in tiles
    SpatialAutoTuneInterval* = 100  ## Steps between density checks

type
  SpatialCell* = object
    things*: seq[Thing]

  SpatialIndex* = object
    cells*: array[SpatialCellsX, array[SpatialCellsY, SpatialCell]]
    # Per-kind indices for faster filtered queries
    kindCells*: array[ThingKind, array[SpatialCellsX, array[SpatialCellsY, seq[Thing]]]]
    when defined(spatialAutoTune):
      activeCellSize*: int        ## Current runtime cell size (tiles)
      activeCellsX*: int          ## Current grid width in cells
      activeCellsY*: int          ## Current grid height in cells
      dynCells*: seq[seq[SpatialCell]]
      dynKindCells*: array[ThingKind, seq[seq[seq[Thing]]]]
      lastTuneStep*: int          ## Step when tuning was last checked

  Stats* = ref object
    # Agent Stats - simplified actions:
    actionInvalid*: int
    actionNoop*: int     # Action 0: NOOP
    actionMove*: int     # Action 1: MOVE
    actionAttack*: int   # Action 2: ATTACK
    actionUse*: int      # Action 3: USE (terrain/buildings)
    actionSwap*: int     # Action 4: SWAP
    actionPlant*: int    # Action 6: PLANT lantern
    actionPut*: int      # Action 5: GIVE to teammate
    actionBuild*: int    # Action 8: BUILD
    actionPlantResource*: int  # Action 7: Plant wheat/tree onto fertile tile
    actionOrient*: int   # Action 9: ORIENT
    actionSetRallyPoint*: int  # Action 10: SET_RALLY_POINT

  TempleInteraction* = object
    agentId*: int
    teamId*: int
    pos*: IVec2

  TempleHybridRequest* = object
    parentA*: int
    parentB*: int
    childId*: int
    teamId*: int
    pos*: IVec2

  TileColor* = object
    r*, g*, b*: float32      # RGB color components
    intensity*: float32      # Overall intensity/brightness modifier

  # Tint modification layers for efficient batch updates
  TintModification* = object
    r*, g*, b*: int32       # Accumulated color contributions (scaled)

  # Track active tiles for sparse processing
  ActiveTiles* = object
    positions*: seq[IVec2]  # Linear list of active tiles
    flags*: array[MapWidth, array[MapHeight, bool]]  # Dedup mask per tile

  # Action tint overlay (short-lived highlights for combat/effects)
  ActionTintCountdown* = array[MapWidth, array[MapHeight, int8]]
  ActionTintColor* = array[MapWidth, array[MapHeight, TileColor]]
  ActionTintFlags* = array[MapWidth, array[MapHeight, bool]]
  ActionTintCode* = array[MapWidth, array[MapHeight, uint8]]

  ProjectileKind* = enum
    ProjArrow        ## Archer/crossbow/arbalester arrows
    ProjLongbow      ## Longbowman arrows (slightly different color)
    ProjJanissary    ## Janissary bullets
    ProjTowerArrow   ## Guard tower / town center arrows
    ProjCastleArrow  ## Castle arrows
    ProjMangonel     ## Mangonel projectile (stone)
    ProjTrebuchet    ## Trebuchet projectile (boulder)

  Projectile* = object
    ## A visual-only projectile traveling from source to target.
    ## Does not affect gameplay - damage is applied instantly (hitscan).
    ## Exists purely for rendering combat readability.
    source*: IVec2       ## Where the projectile was fired from
    target*: IVec2       ## Where it lands (damage already applied)
    kind*: ProjectileKind
    countdown*: int8     ## Frames remaining before removal (starts at lifetime)
    lifetime*: int8      ## Total frames this projectile lives (for interpolation)

  DamageNumberKind* = enum
    DmgNumDamage       ## Red damage number
    DmgNumHeal         ## Green heal number
    DmgNumCritical     ## Yellow/orange critical/bonus damage

  DamageNumber* = object
    ## A floating damage number for combat feedback.
    ## Floats upward and fades out over its lifetime.
    pos*: IVec2          ## World position where damage occurred
    amount*: int         ## Damage/heal amount to display
    kind*: DamageNumberKind
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for fade calculation)

const
  ## Damage number visual constants
  DamageNumberLifetime* = 12'i8   ## Frames damage numbers persist
  DamageNumberPoolCapacity* = 64  ## Initial capacity for damage number pool

type
  RagdollBody* = object
    ## A ragdoll body for death animation physics.
    ## Tumbles away from damage source and fades out.
    pos*: Vec2           ## World position (continuous, not grid-based)
    velocity*: Vec2      ## Movement velocity (world units per frame)
    angle*: float32      ## Current rotation angle (radians)
    angularVel*: float32 ## Rotation speed (radians per frame)
    unitClass*: AgentUnitClass  ## Unit type for sprite selection
    teamId*: int         ## Team for color tinting
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for fade calculation)

const
  ## Ragdoll physics constants
  RagdollLifetime* = 24'i8        ## Frames ragdoll persists (longer than damage number)
  RagdollGravity* = 0.08'f32      ## Downward acceleration per frame
  RagdollFriction* = 0.92'f32     ## Velocity damping per frame
  RagdollInitialSpeed* = 0.3'f32  ## Initial tumble velocity magnitude
  RagdollAngularSpeed* = 0.4'f32  ## Initial rotation speed (radians/frame)
  RagdollPoolCapacity* = 32       ## Initial capacity for ragdoll pool

type
  DebrisKind* = enum
    DebrisWood         ## Wood debris from wooden structures
    DebrisStone        ## Stone debris from walls, towers, castles
    DebrisBrick        ## Brick/mixed debris from town centers, houses

  Debris* = object
    ## A debris particle spawned when buildings are destroyed.
    ## Falls outward from destruction point and fades out over lifetime.
    pos*: Vec2           ## Current world position (float for smooth animation)
    velocity*: Vec2      ## Movement velocity (outward + downward drift)
    kind*: DebrisKind    ## Type affects color/appearance
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for fade calculation)

const
  ## Debris visual constants
  DebrisLifetime* = 18'i8          ## Frames debris particles persist
  DebrisPoolCapacity* = 128        ## Initial capacity for debris pool
  DebrisParticlesPerBuilding* = 8  ## Number of debris particles per destroyed building

type
  SpawnEffect* = object
    ## A visual effect when a unit spawns from a training building.
    ## Shows a pulsing/expanding ring that fades out.
    pos*: IVec2          ## World position where unit spawned
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for animation calculation)

const
  ## Spawn effect visual constants
  SpawnEffectLifetime* = 16'i8   ## Frames spawn effects persist (~1 second)
  SpawnEffectPoolCapacity* = 16  ## Initial capacity for spawn effect pool

type
  DyingUnit* = object
    ## A unit in the process of dying, rendered with fade-out animation.
    ## The actual unit is already removed from the grid; this is visual-only.
    pos*: IVec2              ## World position where unit died
    orientation*: Orientation ## Unit's orientation at death
    unitClass*: AgentUnitClass ## What type of unit this was
    agentId*: int            ## Original agent ID (for team color lookup)
    countdown*: int8         ## Frames remaining before removal
    lifetime*: int8          ## Total frames (for fade calculation)

const
  ## Dying unit visual constants
  DyingUnitLifetime* = 8'i8      ## Steps dying unit animation persists
  DyingUnitPoolCapacity* = 32    ## Initial capacity for dying unit pool

type
  GatherSparkle* = object
    ## A sparkle particle spawned when workers collect resources.
    ## Bursts outward from the resource node and fades out.
    pos*: Vec2           ## Current world position (float for smooth animation)
    velocity*: Vec2      ## Movement velocity (outward burst)
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for fade calculation)

const
  ## Gather sparkle visual constants
  GatherSparkleLifetime* = 18'i8       ## Frames sparkle particles persist
  GatherSparklePoolCapacity* = 64      ## Initial capacity for sparkle pool
  GatherSparkleParticleCount* = 5      ## Number of sparkle particles per gather

type
  ConstructionDust* = object
    ## A dust particle spawned during building construction.
    ## Rises upward from the construction site and fades out.
    pos*: Vec2           ## Current world position (float for smooth animation)
    velocity*: Vec2      ## Movement velocity (upward drift)
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for fade calculation)

const
  ## Construction dust visual constants
  ConstructionDustLifetime* = 24'i8       ## Frames dust particles persist
  ConstructionDustPoolCapacity* = 64      ## Initial capacity for dust pool
  ConstructionDustParticleCount* = 3      ## Number of dust particles per construction tick

type
  UnitTrail* = object
    ## A dust/footprint particle spawned behind moving units.
    ## Creates a trail effect that fades out as units move across the map.
    pos*: Vec2           ## World position where trail was left
    velocity*: Vec2      ## Slight drift velocity (for dust dispersal)
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for fade calculation)
    teamId*: int8        ## Team of the unit that left this trail (for coloring)

const
  ## Unit trail visual constants
  UnitTrailLifetime* = 20'i8          ## Frames trail particles persist
  UnitTrailPoolCapacity* = 256        ## Initial capacity for trail pool (many units moving)
  UnitTrailSpawnChance* = 3           ## Spawn trail every N moves (reduces particle count)

type
  DustParticle* = object
    ## A dust particle kicked up by walking units based on terrain type.
    ## Small particles that drift upward and fade out quickly.
    pos*: Vec2           ## Current world position (float for smooth animation)
    velocity*: Vec2      ## Movement velocity (upward drift with horizontal spread)
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for fade calculation)
    terrainColor*: uint8 ## Terrain type index for color lookup (0=sand, 1=snow, 2=mud, etc.)

const
  ## Dust particle visual constants
  DustParticleLifetime* = 8'i8        ## Frames dust particles persist (quick puff)
  DustParticlePoolCapacity* = 128     ## Initial capacity for dust pool
  DustParticleCount* = 3              ## Number of dust particles per footstep

type
  WaterRipple* = object
    ## A ripple effect when units walk through water.
    ## Expands outward and fades over its lifetime.
    pos*: Vec2           ## World position where ripple originated
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for fade/expansion calculation)

const
  ## Water ripple visual constants
  WaterRippleLifetime* = 16'i8        ## Frames ripples persist (~1 second)
  WaterRipplePoolCapacity* = 64       ## Initial capacity for ripple pool

type
  AttackImpact* = object
    ## A burst particle spawned when attacks hit targets.
    ## Particles radiate outward from the impact point and fade quickly.
    pos*: Vec2           ## Current world position (float for smooth animation)
    velocity*: Vec2      ## Movement velocity (outward burst)
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for fade calculation)

const
  ## Attack impact visual constants
  AttackImpactLifetime* = 10'i8          ## Frames impact particles persist (quick burst)
  AttackImpactPoolCapacity* = 128        ## Initial capacity for impact pool
  AttackImpactParticleCount* = 6         ## Number of particles per impact

type
  ConversionEffect* = object
    ## A pulsing visual effect when a monk converts an enemy unit.
    ## Displays as a golden/divine glow on the converted unit.
    pos*: Vec2           ## World position (at converted unit)
    countdown*: int8     ## Frames remaining before removal
    lifetime*: int8      ## Total frames (for pulse calculation)
    teamColor*: Color    ## Team color of the monk (new owner)

const
  ## Conversion effect visual constants
  ConversionEffectLifetime* = 20'i8      ## Frames conversion effect persists (pulsing glow)
  ConversionEffectPoolCapacity* = 32     ## Initial capacity for effect pool
  ConversionTintDuration* = 4'i8         ## Duration of tile tint for conversion

const
  TeamOwnedKinds* = {
    Agent,
    Door,
    Lantern,
    Altar,
    TownCenter,
    House,
    Barracks,
    ArcheryRange,
    Stable,
    SiegeWorkshop,
    MangonelWorkshop,
    TrebuchetWorkshop,
    Blacksmith,
    Market,
    Dock,
    Monastery,
    University,
    Castle,
    Wonder,
    Outpost,
    GuardTower,
    ClayOven,
    WeavingLoom,
    Mill,
    Granary,
    LumberCamp,
    Quarry,
    MiningCamp
  }

const
  CliffKinds* = {
    CliffEdgeN,
    CliffEdgeE,
    CliffEdgeS,
    CliffEdgeW,
    CliffCornerInNE,
    CliffCornerInSE,
    CliffCornerInSW,
    CliffCornerInNW,
    CliffCornerOutNE,
    CliffCornerOutSE,
    CliffCornerOutSW,
    CliffCornerOutNW
  }

  WaterfallKinds* = {
    WaterfallN,
    WaterfallE,
    WaterfallS,
    WaterfallW
  }

const
  BackgroundThingKinds* = {
    Door,
    Wheat,
    Stubble,
    Tree,
    Fish,
    Relic,
    Lantern,
    Corpse,
    Skeleton,
    Dock,
    ControlPoint
  } + CliffKinds + WaterfallKinds

proc getTeamId*(agent: Thing): int =
  ## Team ID lookup that respects conversions.
  if agent.teamIdOverride >= 0:
    agent.teamIdOverride
  else:
    getTeamId(agent.agentId)

proc updateTeamMask*(thing: Thing) {.inline.} =
  ## Update the cached teamMask field from current teamId/teamIdOverride.
  ## Call this whenever teamId or teamIdOverride changes.
  if thing.isNil:
    return
  thing.teamMask = getTeamMask(getTeamId(thing))

proc getTeamMask*(agent: Thing): TeamMask {.inline.} =
  ## Get cached team bitmask for a Thing. O(1) lookup.
  ## Returns NoTeamMask for nil agents.
  ## IMPORTANT: Caller must ensure updateTeamMask was called after any teamId changes.
  if agent.isNil:
    return NoTeamMask
  agent.teamMask

proc sameTeamMask*(a, b: Thing): bool =
  ## Check if two Things are on the same team using bitwise AND.
  ## More efficient than getTeamId comparison when masks are cached.
  if a.isNil or b.isNil:
    return false
  (getTeamMask(a) and getTeamMask(b)) != 0

proc isEnemyMask*(a, b: Thing): bool =
  ## Check if two Things are enemies (different valid teams) using bitwise ops.
  ## Returns false if either is nil or has invalid team.
  if a.isNil or b.isNil:
    return false
  let maskA = getTeamMask(a)
  let maskB = getTeamMask(b)
  # Both must have valid teams, and they must be different
  maskA != NoTeamMask and maskB != NoTeamMask and (maskA and maskB) == 0

const
  BaseTileColorDefault* = TileColor(r: 0.7, g: 0.65, b: 0.6, intensity: 1.0)
  BiomeColorForest* = TileColor(r: 0.45, g: 0.60, b: 0.40, intensity: 1.0)
  BiomeColorDesert* = TileColor(r: 0.98, g: 0.90, b: 0.25, intensity: 1.05)
  BiomeColorCaves* = TileColor(r: 0.45, g: 0.50, b: 0.58, intensity: 0.95)
  BiomeColorCity* = TileColor(r: 0.62, g: 0.62, b: 0.66, intensity: 1.0)
  BiomeColorPlains* = TileColor(r: 0.55, g: 0.70, b: 0.50, intensity: 1.0)
  BiomeColorSwamp* = TileColor(r: 0.32, g: 0.48, b: 0.38, intensity: 0.95)
  BiomeColorDungeon* = TileColor(r: 0.40, g: 0.36, b: 0.48, intensity: 0.9)
  BiomeColorSnow* = TileColor(r: 0.93, g: 0.95, b: 0.98, intensity: 1.0)
  BiomeEdgeBlendRadius* = 6
  BiomeBlendPasses* = 2
  BiomeBlendNeighborWeight* = 0.18'f32
  # Tiles at peak clippy tint (fully saturated creep hue) count as frozen.
  # Single source of truth for the clippy/creep tint; aligned to clamp limits so tiles can actually reach it.
  ClippyTint* = TileColor(r: 0.30'f32, g: 0.30'f32, b: 1.20'f32, intensity: 0.80'f32)
  ClippyTintTolerance* = 0.06'f32

  ContestedZoneTint* = TileColor(r: 0.75, g: 0.80, b: 0.55, intensity: 1.05)

  TotalRelicsOnMap* = MapRoomObjectsRelics  # Total relics placed on map

type
  VictoryCondition* = enum
    VictoryNone         ## No victory condition (time limit only)
    VictoryConquest     ## Win when all enemy units and buildings destroyed
    VictoryWonder       ## Build Wonder, survive countdown
    VictoryRelic        ## Hold all relics in Monasteries for countdown
    VictoryRegicide     ## Win by killing all enemy kings
    VictoryKingOfTheHill ## Control the hill for consecutive steps
    VictoryAll          ## Any of the above can trigger victory

  VictoryState* = object
    ## Per-team victory tracking
    wonderBuiltStep*: int          ## Step when Wonder was built (-1 = no wonder)
    relicHoldStartStep*: int       ## Step when team started holding all relics (-1 = not holding)
    kingAgentId*: int              ## Agent ID of this team's king (-1 = no king)
    hillControlStartStep*: int     ## Step when team started controlling the hill (-1 = not controlling)

  # Configuration structure for environment - ONLY runtime parameters
  # Structural constants (map size, agent count, observation dimensions) remain compile-time constants
  EnvironmentConfig* = object
    # Core game parameters
    maxSteps*: int
    victoryCondition*: VictoryCondition  ## Which victory conditions are active

    # Combat configuration
    tumorSpawnRate*: float

    # Reward configuration
    heartReward*: float
    oreReward*: float # Gold mining reward
    barReward*: float
    woodReward*: float
    waterReward*: float
    wheatReward*: float
    spearReward*: float
    armorReward*: float
    foodReward*: float
    clothReward*: float
    tumorKillReward*: float
    survivalPenalty*: float
    deathPenalty*: float

proc defaultEnvironmentConfig*(): EnvironmentConfig =
  ## Create default environment configuration
  EnvironmentConfig(
    # Core game parameters
    maxSteps: 3000,
    victoryCondition: VictoryAll,

    # Combat configuration
    tumorSpawnRate: 0.1,

    # Reward configuration (only arena_basic_easy_shaped rewards active)
    heartReward: 1.0,      # Arena: heart reward
    oreReward: 0.1,        # Arena: gold mining reward
    barReward: 0.8,        # Arena: bar smelting reward
    woodReward: 0.0,       # Disabled - not in arena
    waterReward: 0.0,      # Disabled - not in arena
    wheatReward: 0.0,      # Disabled - not in arena
    spearReward: 0.0,      # Disabled - not in arena
    armorReward: 0.0,      # Disabled - not in arena
    foodReward: 0.0,       # Disabled - not in arena
    clothReward: 0.0,      # Disabled - not in arena
    tumorKillReward: 0.0,  # Disabled - not in arena
    survivalPenalty: -0.01,
    deathPenalty: -5.0
  )

type
  CivBonus* = object
    ## Civilization-style asymmetry multipliers for team differentiation.
    ## All multipliers default to 1.0 (no effect). Applied at point of use.
    gatherRateMultiplier*: float32    ## Multiplier for resource gathering speed (1.0 = normal)
    buildSpeedMultiplier*: float32    ## Multiplier for construction/repair speed (1.0 = normal)
    unitHpMultiplier*: float32        ## Multiplier for trained unit max HP (1.0 = normal)
    unitAttackMultiplier*: float32    ## Multiplier for trained unit attack damage (1.0 = normal)
    buildingHpMultiplier*: float32    ## Multiplier for building max HP (1.0 = normal)
    woodCostMultiplier*: float32      ## Multiplier for wood building costs (1.0 = normal)
    foodCostMultiplier*: float32      ## Multiplier for food unit costs (1.0 = normal)

  TerritoryScore* = object
    teamTiles*: array[MapRoomObjectsTeams, int]
    clippyTiles*: int
    neutralTiles*: int
    scoredTiles*: int

  TeamStockpile* = object
    counts*: array[StockpileResource, int]

  TeamModifiers* = object
    ## Civilization-style asymmetry modifiers for team differentiation
    gatherRateMultiplier*: float32  ## 1.0 = normal gather rate
    buildCostMultiplier*: float32   ## 1.0 = normal build costs
    unitHpBonus*: array[AgentUnitClass, int]      ## Bonus HP per unit class
    unitAttackBonus*: array[AgentUnitClass, int]  ## Bonus attack per unit class
    # Runtime configuration for building/unit availability
    disabledBuildings*: set[ThingKind]            ## Buildings this team cannot build
    disabledUnits*: set[AgentUnitClass]           ## Unit classes this team cannot train
    # Base stat overrides (0 = use default, >0 = override value)
    unitBaseHpOverride*: array[AgentUnitClass, int]
    unitBaseAttackOverride*: array[AgentUnitClass, int]
    # Per-building and per-unit cost multipliers (0.0 or 1.0 = normal, other = multiplied)
    buildingCostMultiplier*: array[ThingKind, float32]
    trainCostMultiplier*: array[AgentUnitClass, float32]

  MarketPrices* = object
    ## AoE2-style dynamic market prices per resource (in gold per 100 units)
    ## Gold is the base currency and not traded
    prices*: array[StockpileResource, int]  ## Current price for each resource

  BlacksmithUpgradeType* = enum
    ## AoE2-style Blacksmith upgrade lines (5 lines, 3 tiers each)
    UpgradeMeleeAttack       ## Forging → Iron Casting → Blast Furnace (infantry + cavalry)
    UpgradeArcherAttack      ## Fletching → Bodkin Arrow → Bracer (archers + towers)
    UpgradeInfantryArmor     ## Scale Mail → Chain Mail → Plate Mail
    UpgradeCavalryArmor      ## Scale Barding → Chain Barding → Plate Barding
    UpgradeArcherArmor       ## Padded Archer → Leather Archer → Ring Archer

  BlacksmithUpgrades* = object
    ## Team-level Blacksmith upgrade progress (AoE2-style named tech tree)
    ## Each line can be researched up to 3 tiers with variable bonuses per tier
    levels*: array[BlacksmithUpgradeType, int]  ## Current tier (0-3) for each line

type

  UniversityTechType* = enum
    ## AoE2-style University technologies
    TechBallistics       ## Projectiles lead moving targets (ranged accuracy)
    TechMurderHoles      ## Towers attack adjacent units (no minimum range)
    TechMasonry          ## +10% building HP, +1/+1 building armor
    TechArchitecture     ## +10% building HP, +1/+1 building armor (stacks with Masonry)
    TechTreadmillCrane   ## +20% construction speed
    TechArrowslits       ## +1 tower attack damage
    TechHeatedShot       ## +2 attack vs ships (bonus damage)
    TechSiegeEngineers   ## +1 range, +20% building damage for siege units
    TechChemistry        ## Enables gunpowder units (future tech)
    TechCoinage          ## Reduces tribute tax rate from 20% to 10%

  UniversityTechs* = object
    ## Team-level University tech progress (AoE2-style)
    ## Each tech is either researched (true) or not (false)
    researched*: array[UniversityTechType, bool]

  CastleTechType* = enum
    ## AoE2-style Castle unique technologies (2 per civilization/team)
    ## Each team has one Castle Age tech and one Imperial Age tech.
    ## Index: team * 2 = Castle Age tech, team * 2 + 1 = Imperial Age tech
    CastleTechYeomen          ## Team 0 Castle: +1 archer range, +2 tower attack
    CastleTechKataparuto      ## Team 0 Imperial: +3 trebuchet attack
    CastleTechLogistica        ## Team 1 Castle: +1 infantry attack
    CastleTechCrenellations    ## Team 1 Imperial: +2 castle attack
    CastleTechGreekFire        ## Team 2 Castle: +2 tower attack vs siege
    CastleTechFurorCeltica     ## Team 2 Imperial: +2 siege attack
    CastleTechAnarchy          ## Team 3 Castle: +1 infantry HP per unit
    CastleTechPerfusion        ## Team 3 Imperial: military units train faster (not modeled, +2 all attack)
    CastleTechIronclad         ## Team 4 Castle: +3 siege unit armor (modeled as +3 siege HP)
    CastleTechCrenellations2   ## Team 4 Imperial: +2 castle attack
    CastleTechBerserkergang    ## Team 5 Castle: +2 infantry HP
    CastleTechChieftains       ## Team 5 Imperial: +1 cavalry attack bonus
    CastleTechZealotry         ## Team 6 Castle: +2 cavalry HP
    CastleTechMahayana         ## Team 6 Imperial: +1 monk conversion (modeled as +1 monk attack)
    CastleTechSipahi           ## Team 7 Castle: +2 archer HP
    CastleTechArtillery        ## Team 7 Imperial: +2 tower and castle attack

  CastleTechs* = object
    ## Team-level Castle unique tech progress (AoE2-style)
    ## Each team can research exactly 2 techs (their own civilization's unique techs)
    researched*: array[CastleTechType, bool]

  UnitUpgradeType* = enum
    ## AoE2-style unit promotion chains (researched at military buildings)
    UpgradeLongSwordsman     ## ManAtArms → LongSwordsman (Barracks)
    UpgradeChampion          ## LongSwordsman → Champion (Barracks)
    UpgradeLightCavalry      ## Scout → LightCavalry (Stable)
    UpgradeHussar            ## LightCavalry → Hussar (Stable)
    UpgradeKnight            ## Unlocks Knight at Stable (replaces Scout line)
    UpgradeCrossbowman       ## Archer → Crossbowman (Archery Range)
    UpgradeArbalester        ## Crossbowman → Arbalester (Archery Range)
    UpgradeSkirmisher        ## Unlocks Skirmisher at Archery Range
    UpgradeEliteSkirmisher   ## Skirmisher → Elite Skirmisher (Archery Range)
    UpgradeCavalryArcher     ## Unlocks Cavalry Archer at Archery Range
    UpgradeHeavyCavalryArcher ## Cavalry Archer → Heavy Cavalry Archer (Archery Range)

  UnitUpgrades* = object
    ## Team-level unit upgrade progress (AoE2-style promotion chains)
    ## Each upgrade is either researched (true) or not (false)
    researched*: array[UnitUpgradeType, bool]

  EconomyTechType* = enum
    ## AoE2-style economy technologies (researched at various buildings)
    ## Town Center techs (villager improvements)
    TechWheelbarrow       ## +10% villager speed, +3 carry capacity
    TechHandCart          ## +10% villager speed, +7 carry capacity (stacks)
    ## Lumber Camp techs (wood gathering improvements)
    TechDoubleBitAxe      ## +20% wood gathering rate
    TechBowSaw            ## +20% wood gathering rate (stacks)
    TechTwoManSaw         ## +10% wood gathering rate (stacks)
    ## Mining Camp techs (gold/stone gathering improvements)
    TechGoldMining        ## +15% gold gathering rate
    TechGoldShaftMining   ## +15% gold gathering rate (stacks)
    TechStoneMining       ## +15% stone gathering rate
    TechStoneShaftMining  ## +15% stone gathering rate (stacks)
    ## Mill techs (farm improvements)
    TechHorseCollar       ## +75 farm food, enables auto-reseed
    TechHeavyPlow         ## +125 farm food (stacks)
    TechCropRotation      ## +175 farm food (stacks)

  EconomyTechs* = object
    ## Team-level economy tech progress (AoE2-style)
    ## Each tech is either researched (true) or not (false)
    researched*: array[EconomyTechType, bool]

  ElevationGrid* = array[MapWidth, array[MapHeight, int8]]

  # Fog of war: tracks which tiles each team has explored (AoE2-style)
  RevealedMap* = array[MapWidth, array[MapHeight, bool]]

  Environment* = ref object
    currentStep*: int
    gameSeed*: int       # Seed for this game instance (used for step RNG variation)
    mapGeneration*: int  # Bumps each time the map is rebuilt (for render caches)
    config*: EnvironmentConfig  # Configuration for this environment
    shouldReset*: bool  # Track if environment needs reset
    observationsInitialized*: bool  # Track whether observation tensors are populated
    observationsDirty*: bool  # Track if observations need rebuilding (lazy rebuild)
    things*: seq[Thing]
    agents*: seq[Thing]
    grid*: array[MapWidth, array[MapHeight, Thing]]          # Blocking units
    backgroundGrid*: array[MapWidth, array[MapHeight, Thing]]   # Background (non-blocking) units
    elevation*: ElevationGrid
    teamStockpiles*: array[MapRoomObjectsTeams, TeamStockpile]
    teamModifiers*: array[MapRoomObjectsTeams, TeamModifiers]
    teamCivBonuses*: array[MapRoomObjectsTeams, CivBonus]  # Civilization asymmetry multipliers
    teamMarketPrices*: array[MapRoomObjectsTeams, MarketPrices]  # AoE2-style dynamic market prices
    teamBlacksmithUpgrades*: array[MapRoomObjectsTeams, BlacksmithUpgrades]  # AoE2-style Blacksmith upgrades
    teamUniversityTechs*: array[MapRoomObjectsTeams, UniversityTechs]  # AoE2-style University techs
    teamCastleTechs*: array[MapRoomObjectsTeams, CastleTechs]  # AoE2-style Castle unique techs
    teamUnitUpgrades*: array[MapRoomObjectsTeams, UnitUpgrades]  # AoE2-style unit promotion chains
    teamEconomyTechs*: array[MapRoomObjectsTeams, EconomyTechs]  # AoE2-style economy techs
    teamTributesSent*: array[MapRoomObjectsTeams, int]     # Cumulative resources sent via tribute
    teamTributesReceived*: array[MapRoomObjectsTeams, int] # Cumulative resources received via tribute
    revealedMaps*: array[MapRoomObjectsTeams, RevealedMap]  # Fog of war: explored tiles per team
    terrain*: TerrainGrid
    biomes*: BiomeGrid
    baseTintColors*: array[MapWidth, array[MapHeight, TileColor]]  # Basemost biome tint layer (static)
    computedTintColors*: array[MapWidth, array[MapHeight, TileColor]]  # Dynamic tint overlay (lanterns/tumors)
    tintLocked*: array[MapWidth, array[MapHeight, bool]]  # Tiles that ignore dynamic tint overlays
    tintMods*: array[MapWidth, array[MapHeight, TintModification]]  # Unified tint modifications
    tintStrength*: array[MapWidth, array[MapHeight, int32]]  # Tint strength accumulation
    activeTiles*: ActiveTiles  # Sparse list of tiles to process
    tumorTintMods*: array[MapWidth, array[MapHeight, TintModification]]  # Persistent tumor tint contributions
    tumorStrength*: array[MapWidth, array[MapHeight, int32]]  # Tumor tint strength accumulation
    tumorActiveTiles*: ActiveTiles  # Sparse list of tiles touched by tumors
    stepDirtyFlags*: array[MapWidth, array[MapHeight, bool]]  # Tiles modified by entity contributions this step
    stepDirtyPositions*: seq[IVec2]  # Position list for clearing stepDirtyFlags
    frozenTiles*: array[MapWidth, array[MapHeight, bool]]  # Cached frozen state (avoids recomputing combinedTileTint)
    tintColorsDirty*: bool  # True when computedTintColors needs rebuilding (lazy computation)
    actionTintCountdown*: ActionTintCountdown  # Short-lived combat/heal highlights
    actionTintColor*: ActionTintColor
    actionTintFlags*: ActionTintFlags
    actionTintCode*: ActionTintCode
    actionTintPositions*: seq[IVec2]
    projectiles*: seq[Projectile]  # Visual-only projectile sprites for ranged attacks
    damageNumbers*: seq[DamageNumber]  # Floating damage numbers for combat feedback
    ragdolls*: seq[RagdollBody]  # Death ragdoll bodies with physics
    debris*: seq[Debris]  # Debris particles from destroyed buildings
    spawnEffects*: seq[SpawnEffect]    # Visual effects when units spawn from buildings
    dyingUnits*: seq[DyingUnit]  # Units in death animation (fade-out before corpse)
    gatherSparkles*: seq[GatherSparkle]  # Sparkle particles when collecting resources
    constructionDust*: seq[ConstructionDust]  # Dust particles during building construction
    unitTrails*: seq[UnitTrail]  # Dust/footprint trails behind moving units
    dustParticles*: seq[DustParticle]  # Dust kicked up by walking units on dusty terrain
    waterRipples*: seq[WaterRipple]  # Ripple effects when units walk through water
    attackImpacts*: seq[AttackImpact]  # Burst particles when attacks hit targets
    conversionEffects*: seq[ConversionEffect]  # Pulsing glow when monks convert units
    thingsByKind*: array[ThingKind, seq[Thing]]
    spatialIndex*: SpatialIndex  # Spatial partitioning for O(1) nearest queries
    # Aura unit tracking for O(1) iteration (avoids scanning all agents)
    tankUnits*: seq[Thing]  # ManAtArms and Knight units with auras
    monkUnits*: seq[Thing]  # Monk units with auras
    # Villager tracking per team for O(team_size) town bell garrison
    teamVillagers*: array[MapRoomObjectsTeams, seq[Thing]]
    # Town Bell: per-team toggle for recall/garrison mechanic
    townBellActive*: array[MapRoomObjectsTeams, bool]
    cowHerdCounts*: seq[int]
    cowHerdSumX*: seq[int]
    cowHerdSumY*: seq[int]
    cowHerdDrift*: seq[IVec2]
    cowHerdTargets*: seq[IVec2]
    cowHerdCenters*: seq[IVec2]  # Precomputed herd centers for movement loops
    wolfPackCounts*: seq[int]
    wolfPackSumX*: seq[int]
    wolfPackSumY*: seq[int]
    wolfPackDrift*: seq[IVec2]
    wolfPackTargets*: seq[IVec2]
    wolfPackCenters*: seq[IVec2]  # Precomputed pack centers for movement loops
    wolfPackLeaders*: seq[Thing]  # Leader wolf for each pack (nil if dead)
    shieldCountdown*: array[MapAgents, int8]  # shield active timer per agent
    territoryScore*: TerritoryScore
    territoryScored*: bool
    observations*: array[
      MapAgents,
      array[ObservationLayers,
        array[ObservationWidth, array[ObservationHeight, uint8]]
      ]
    ]
    rewards*: array[MapAgents, float32]
    terminated*: array[MapAgents, float32]
    truncated*: array[MapAgents, float32]
    stats*: seq[Stats]
    templeInteractions*: seq[TempleInteraction]
    templeHybridRequests*: seq[TempleHybridRequest]
    # Tint tracking for incremental updates
    lastAgentPos*: array[MapAgents, IVec2]  # Track agent positions for delta tint
    lastLanternPos*: seq[IVec2]              # Track lantern positions for delta tint
    # Observation tracking for incremental updates
    lastObsAgentPos*: array[MapAgents, IVec2]  # Track agent positions for delta observations
    agentObsDirty*: array[MapAgents, bool]  # Per-agent dirty bits for observation rebuilding
    # Color management
    agentColors*: seq[Color]           ## Per-agent colors for rendering
    teamColors*: seq[Color]            ## Per-team colors for rendering
    altarColors*: Table[IVec2, Color]  ## Altar position to color mapping
    # Victory conditions tracking
    victoryStates*: array[MapRoomObjectsTeams, VictoryState]
    victoryWinner*: int              ## Team that won (-1 = no winner yet)
    victoryWinners*: TeamMask        ## Bitmask of all winning teams (includes allies)
    # Alliance tracking
    teamAlliances*: array[MapRoomObjectsTeams, TeamMask]  ## Per-team alliance bitmask (symmetric)
    # Reusable scratch seqs for step() to avoid per-frame heap allocations
    tempTumorsToSpawn*: seq[Thing]
    tempTumorsToProcess*: seq[Thing]
    tempTowerRemovals*: HashSet[Thing]
    # Additional scratch buffers for hot-path allocations
    tempTowerTargets*: seq[Thing]      ## Tower attack target candidates
    tempTCTargets*: seq[Thing]         ## Town center attack targets
    tempMonkAuraAllies*: seq[Thing]    ## Nearby allies for monk auras
    tempEmptyTiles*: seq[IVec2]        ## Empty tiles for ungarrisoning
    tempLanternSpacing*: seq[Thing]    ## Lantern spacing check buffer
    tempAIAllies*: seq[Thing]          ## AI phase: reusable ally collect buffer
    # Reusable per-step state to avoid heap allocations
    constructionBuilders*: Table[IVec2, int]  ## Builder count per construction site
    agentOrder*: array[MapAgents, int]        ## Shuffle buffer for action processing
    stepTeamPopCaps*: array[MapRoomObjectsTeams, int]   ## Pre-computed pop caps
    stepTeamPopCounts*: array[MapRoomObjectsTeams, int] ## Pre-computed pop counts
    # Object pool for frequently created/destroyed things
    thingPool*: ThingPool
    # Object pool for projectiles (pre-allocated capacity, stats tracking)
    projectilePool*: ProjectilePool
    # Arena allocator for per-step temporary allocations
    arena*: Arena

# Global environment instance
var env*: Environment

# Control group constants
const
  ControlGroupCount* = 10  # Groups 0-9, bound to keys 0-9

# Selection state (for UI)
var selection*: seq[Thing] = @[]
var selectedPos*: IVec2 = ivec2(-1, -1)

# Control groups (AoE2-style: Ctrl+N assigns, N recalls, double-tap N centers camera)
var controlGroups*: array[ControlGroupCount, seq[Thing]] = default(array[ControlGroupCount, seq[Thing]])
var lastGroupKeyTime*: array[ControlGroupCount, float64]  # For double-tap detection
var lastGroupKeyIndex*: int = -1  # Last group key pressed (for double-tap)

# Building placement mode (for ghost preview)
var buildingPlacementMode*: bool = false
var buildingPlacementKind*: ThingKind = Wall  # Default to wall
var buildingPlacementValid*: bool = false     # Whether current position is valid

# Rally point mode (for setting rally points on production buildings)
var rallyPointMode*: bool = false

# Helper function for checking if agent is alive
proc isAgentAlive*(env: Environment, agent: Thing): bool {.inline.} =
  not agent.isNil and
    agent.agentId >= 0 and agent.agentId < MapAgents and
    env.terminated[agent.agentId] == 0.0 and
    isValidPos(agent.pos) and
    env.grid[agent.pos.x][agent.pos.y] == agent

# ─── Nil-safe Thing Helpers ───────────────────────────────────────────────────
#
# These helpers consolidate common nil check patterns throughout the codebase.
# Using them improves readability and reduces boilerplate in hot paths.

proc hasValue*(thing: Thing): bool {.inline.} =
  ## Returns true if thing is not nil. Inverse of isNil for semantic clarity.
  ## Useful when checking if a find/query returned a result.
  not thing.isNil

proc isKind*(thing: Thing, kind: ThingKind): bool {.inline.} =
  ## Nil-safe kind check. Returns true only if thing is not nil AND matches kind.
  ## Replaces the common pattern: `if not thing.isNil and thing.kind == X`
  not thing.isNil and thing.kind == kind

iterator liveAgents*(env: Environment): Thing =
  ## Yields only non-nil agents from env.agents.
  ## Replaces the common pattern:
  ##   for agent in env.agents:
  ##     if agent.isNil: continue
  for agent in env.agents:
    if not agent.isNil:
      yield agent

iterator liveAgentsWithId*(env: Environment): tuple[id: int, agent: Thing] =
  ## Yields (agentId, agent) pairs for non-nil agents.
  ## Replaces the common pattern:
  ##   for id, agent in env.agents:
  ##     if agent.isNil: continue
  for id, agent in env.agents:
    if not agent.isNil:
      yield (id, agent)

proc defaultCivBonus*(): CivBonus {.inline.} =
  ## Create a default (neutral) CivBonus with all multipliers at 1.0.
  CivBonus(
    gatherRateMultiplier: 1.0'f32,
    buildSpeedMultiplier: 1.0'f32,
    unitHpMultiplier: 1.0'f32,
    unitAttackMultiplier: 1.0'f32,
    buildingHpMultiplier: 1.0'f32,
    woodCostMultiplier: 1.0'f32,
    foodCostMultiplier: 1.0'f32
  )

const
  ## Predefined civilization bonus profiles (AoE2-inspired).
  ## Bonuses are subtle (5-15%) to avoid breaking balance.
  CivNeutral* = CivBonus(
    gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.0'f32,
    unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.0'f32,
    buildingHpMultiplier: 1.0'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 1.0'f32)

  CivBritons* = CivBonus(
    gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.0'f32,
    unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.1'f32,  # +10% attack
    buildingHpMultiplier: 1.0'f32, woodCostMultiplier: 0.9'f32, foodCostMultiplier: 1.0'f32)  # -10% wood costs

  CivFranks* = CivBonus(
    gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.0'f32,
    unitHpMultiplier: 1.1'f32, unitAttackMultiplier: 1.0'f32,  # +10% unit HP
    buildingHpMultiplier: 1.0'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 0.9'f32)  # -10% food costs

  CivByzantines* = CivBonus(
    gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.1'f32,  # +10% build speed
    unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.0'f32,
    buildingHpMultiplier: 1.15'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 1.0'f32)  # +15% building HP

  CivMongols* = CivBonus(
    gatherRateMultiplier: 1.15'f32, buildSpeedMultiplier: 1.0'f32,  # +15% gather rate
    unitHpMultiplier: 1.0'f32, unitAttackMultiplier: 1.05'f32,  # +5% attack
    buildingHpMultiplier: 0.9'f32, woodCostMultiplier: 1.0'f32, foodCostMultiplier: 1.0'f32)  # -10% building HP (tradeoff)

  CivTeutons* = CivBonus(
    gatherRateMultiplier: 1.0'f32, buildSpeedMultiplier: 1.0'f32,
    unitHpMultiplier: 1.05'f32, unitAttackMultiplier: 1.05'f32,  # +5% both
    buildingHpMultiplier: 1.1'f32, woodCostMultiplier: 1.05'f32, foodCostMultiplier: 1.05'f32)  # strong but expensive

  ## Array of all civs for random assignment
  AllCivBonuses* = [CivNeutral, CivBritons, CivFranks, CivByzantines, CivMongols, CivTeutons]

proc getUnitAttackRange*(agent: Thing): int =
  ## Get the attack range for a unit based on its class.
  case agent.unitClass
  of UnitArcher, UnitCrossbowman, UnitArbalester:
    ArcherBaseRange
  of UnitLongbowman:
    ArcherBaseRange + 2  # Extended range
  of UnitMangonel:
    MangonelBaseRange
  of UnitTrebuchet:
    TrebuchetBaseRange
  of UnitMameluke, UnitJanissary:
    2  # Short ranged
  else:
    1  # Melee
