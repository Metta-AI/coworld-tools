# Observation Space Reference

Date: 2026-01-31
Owner: Engineering / AI
Status: Active

## Shape and layout
- **Spatial size:** `ObservationWidth` x `ObservationHeight` = **11 x 11**.
- **Radius:** `ObservationRadius` = 5 (centered on the agent).
- **Layers:** `ObservationLayers` = `ord(ObservationName.high) + 1` = **96**.
- **Type:** `uint8` values per layer cell.

The canonical enum lives in `src/types.nim` under `ObservationName`.

## Layer groups
The observation tensor is grouped into three conceptual blocks:

### 1) Terrain layers (17 layers, indices 0-16, one-hot)

| Index | Layer Name | Description |
|-------|------------|-------------|
| 0 | `TerrainEmptyLayer` | Impassable void/empty terrain |
| 1 | `TerrainWaterLayer` | Water (passable by boats) |
| 2 | `TerrainBridgeLayer` | Bridge over water |
| 3 | `TerrainFertileLayer` | Fertile soil (plantable) |
| 4 | `TerrainRoadLayer` | Road (faster movement) |
| 5 | `TerrainGrassLayer` | Standard grass terrain |
| 6 | `TerrainDuneLayer` | Sand dune terrain |
| 7 | `TerrainSandLayer` | Sandy terrain |
| 8 | `TerrainSnowLayer` | Snow-covered terrain |
| 9 | `TerrainRampUpNLayer` | Elevation ramp going up (north) |
| 10 | `TerrainRampUpSLayer` | Elevation ramp going up (south) |
| 11 | `TerrainRampUpWLayer` | Elevation ramp going up (west) |
| 12 | `TerrainRampUpELayer` | Elevation ramp going up (east) |
| 13 | `TerrainRampDownNLayer` | Elevation ramp going down (north) |
| 14 | `TerrainRampDownSLayer` | Elevation ramp going down (south) |
| 15 | `TerrainRampDownWLayer` | Elevation ramp going down (west) |
| 16 | `TerrainRampDownELayer` | Elevation ramp going down (east) |

### 2) Thing layers (64 layers, indices 17-80, one-hot)

These correspond to `ThingKind` entries. Both blocking and background things
are written to the same layer for that tile.

| Index | Layer Name | Description |
|-------|------------|-------------|
| 17 | `ThingAgentLayer` | Mobile units (villagers, military, animals controlled by teams) |
| 18 | `ThingWallLayer` | Stone/palisade walls (blocking structures) |
| 19 | `ThingDoorLayer` | Gates/doors in walls (passable by friendlies) |
| 20 | `ThingTreeLayer` | Trees (harvestable for wood) |
| 21 | `ThingWheatLayer` | Wheat fields (harvestable for food) |
| 22 | `ThingFishLayer` | Fish in water (harvestable for food) |
| 23 | `ThingRelicLayer` | Relics (can be garrisoned in Monasteries for gold) |
| 24 | `ThingStoneLayer` | Stone deposits (harvestable for stone) |
| 25 | `ThingGoldLayer` | Gold deposits (harvestable for gold) |
| 26 | `ThingBushLayer` | Berry bushes (harvestable for food) |
| 27 | `ThingCactusLayer` | Cacti (desert flora, blocking) |
| 28 | `ThingStalagmiteLayer` | Stalagmites (cave formations, blocking) |
| 29 | `ThingMagmaLayer` | Magma pools (smelts gold into bars) |
| 30 | `ThingAltarLayer` | Team altars (respawn points) |
| 31 | `ThingSpawnerLayer` | Creep spawners (enemy tumor source) |
| 32 | `ThingTumorLayer` | Tumors (spreading creep hazard) |
| 33 | `ThingCowLayer` | Cows (herdable livestock) |
| 34 | `ThingBearLayer` | Bears (hostile wildlife) |
| 35 | `ThingWolfLayer` | Wolves (hostile wildlife, pack behavior) |
| 36 | `ThingCorpseLayer` | Fresh corpses (decay to skeletons) |
| 37 | `ThingSkeletonLayer` | Skeletons (decayed corpses) |
| 38 | `ThingClayOvenLayer` | Clay oven (crafting building) |
| 39 | `ThingWeavingLoomLayer` | Weaving loom (crafting building) |
| 40 | `ThingOutpostLayer` | Outpost (vision building, no attack) |
| 41 | `ThingGuardTowerLayer` | Guard tower (defensive structure, ranged attack) |
| 42 | `ThingBarrelLayer` | Storage barrels |
| 43 | `ThingMillLayer` | Mill (food processing drop-off) |
| 44 | `ThingGranaryLayer` | Granary (food storage drop-off) |
| 45 | `ThingLumberCampLayer` | Lumber camp (wood drop-off) |
| 46 | `ThingQuarryLayer` | Quarry (stone drop-off) |
| 47 | `ThingMiningCampLayer` | Mining camp (gold drop-off) |
| 48 | `ThingStumpLayer` | Tree stumps (harvested tree remains) |
| 49 | `ThingLanternLayer` | Lanterns (team color markers) |
| 50 | `ThingTownCenterLayer` | Town center (main building, unit production, garrisonable) |
| 51 | `ThingHouseLayer` | Houses (population support, garrisonable) |
| 52 | `ThingBarracksLayer` | Barracks (infantry training) |
| 53 | `ThingArcheryRangeLayer` | Archery range (archer training) |
| 54 | `ThingStableLayer` | Stable (cavalry training) |
| 55 | `ThingSiegeWorkshopLayer` | Siege workshop (battering ram training) |
| 56 | `ThingMangonelWorkshopLayer` | Mangonel workshop (mangonel training) |
| 57 | `ThingTrebuchetWorkshopLayer` | Trebuchet workshop (trebuchet training) |
| 58 | `ThingBlacksmithLayer` | Blacksmith (unit upgrades) |
| 59 | `ThingMarketLayer` | Market (resource trading) |
| 60 | `ThingDockLayer` | Dock (boat training, water access) |
| 61 | `ThingMonasteryLayer` | Monastery (monk training, relic storage) |
| 62 | `ThingUniversityLayer` | University (technology research) |
| 63 | `ThingCastleLayer` | Castle (defensive fortress, unique units, garrisonable) |
| 64 | `ThingWonderLayer` | Wonder (victory building) |
| 65 | `ThingGoblinHiveLayer` | Goblin hive (goblin spawner) |
| 66 | `ThingGoblinHutLayer` | Goblin hut (goblin structure) |
| 67 | `ThingGoblinTotemLayer` | Goblin totem (goblin structure) |
| 68 | `ThingStubbleLayer` | Stubble (harvested wheat residue) |
| 69 | `ThingCliffEdgeNLayer` | Cliff edge facing north |
| 70 | `ThingCliffEdgeELayer` | Cliff edge facing east |
| 71 | `ThingCliffEdgeSLayer` | Cliff edge facing south |
| 72 | `ThingCliffEdgeWLayer` | Cliff edge facing west |
| 73 | `ThingCliffCornerInNELayer` | Cliff inside corner (northeast) |
| 74 | `ThingCliffCornerInSELayer` | Cliff inside corner (southeast) |
| 75 | `ThingCliffCornerInSWLayer` | Cliff inside corner (southwest) |
| 76 | `ThingCliffCornerInNWLayer` | Cliff inside corner (northwest) |
| 77 | `ThingCliffCornerOutNELayer` | Cliff outside corner (northeast) |
| 78 | `ThingCliffCornerOutSELayer` | Cliff outside corner (southeast) |
| 79 | `ThingCliffCornerOutSWLayer` | Cliff outside corner (southwest) |
| 80 | `ThingCliffCornerOutNWLayer` | Cliff outside corner (northwest) |

**Note:** `ThingKind` in types.nim includes `Temple` and `ControlPoint` which do
not have corresponding observation layers (they are `BackgroundThingKinds`).

### 3) Meta layers (15 layers, indices 81-95)

These layers encode non-spatial entity state and game mechanics.

| Index | Layer Name | Description |
|-------|------------|-------------|
| 81 | `TeamLayer` | Team ID + 1 (0 = neutral/none) |
| 82 | `AgentOrientationLayer` | Orientation enum + 1 (0 = none/not an agent) |
| 83 | `AgentUnitClassLayer` | Unit class enum + 1 (0 = none/not an agent) |
| 84 | `AgentIdleLayer` | 1 if agent is idle (NOOP/ORIENT action), 0 otherwise |
| 85 | `TintLayer` | Action/combat tint codes (see below) |
| 86 | `RallyPointLayer` | 1 if a friendly building has its rally point here |
| 87 | `BiomeLayer` | Biome type enum value |
| 88 | `GarrisonCountLayer` | Garrison fill ratio: `(count * 255) div capacity` |
| 89 | `RelicCountLayer` | Monastery relic count (direct value, 0-255) |
| 90 | `ProductionQueueLenLayer` | Units in production queue (direct value, 0-255) |
| 91 | `BuildingHpLayer` | Building HP ratio: `(hp * 255) div maxHp` |
| 92 | `MonkFaithLayer` | Monk faith ratio: `(faith * 255) div MonkMaxFaith` |
| 93 | `TrebuchetPackedLayer` | 1 if trebuchet is packed (mobile), 0 if unpacked |
| 94 | `UnitStanceLayer` | AgentStance enum + 1 (0 = not an agent) |
| 95 | `ObscuredLayer` | 1 when target tile is above observer elevation |

**Layer details:**

- `GarrisonCountLayer`: Only non-zero for garrisonable buildings (TownCenter,
  Castle, GuardTower, House).
- `RelicCountLayer`: Only non-zero for Monasteries with garrisoned relics.
- `ProductionQueueLenLayer`: Number of units in a building's production queue
  (max 10 typically).
- `BuildingHpLayer`: Non-zero for any building with `maxHp > 0`.
- `MonkFaithLayer`: Non-zero only for Monk agents with faith > 0.
- `TrebuchetPackedLayer`: Only non-zero for Trebuchet agents.
- `UnitStanceLayer`: Values are 1=Aggressive, 2=Defensive, 3=StandGround,
  4=NoAttack.
- `ObscuredLayer`: Applied in the FFI path (`src/ffi.nim`); when a tile is
  obscured, other layers for that tile are zeroed.

## Action tint codes (TintLayer)
Defined in `src/types.nim`:

**Attack codes (per unit class):**
- `ActionTintNone` = 0
- `ActionTintAttackVillager` = 1
- `ActionTintAttackManAtArms` = 2
- `ActionTintAttackArcher` = 3
- `ActionTintAttackScout` = 4
- `ActionTintAttackKnight` = 5
- `ActionTintAttackMonk` = 6
- `ActionTintAttackBatteringRam` = 7
- `ActionTintAttackMangonel` = 8
- `ActionTintAttackTrebuchet` = 9
- `ActionTintAttackBoat` = 10
- `ActionTintAttackTower` = 11
- `ActionTintAttackCastle` = 12

**Counter/bonus codes:**
- `ActionTintAttackBonus` = 13 (generic bonus, rarely used)
- `ActionTintBonusArcher` = 14 (archer counter bonus vs infantry)
- `ActionTintBonusInfantry` = 15 (infantry counter bonus vs cavalry)
- `ActionTintBonusScout` = 16 (scout counter bonus vs archers)
- `ActionTintBonusKnight` = 17 (knight counter bonus vs archers)
- `ActionTintBonusBatteringRam` = 18 (battering ram siege bonus vs structures)
- `ActionTintBonusMangonel` = 19 (mangonel siege bonus vs structures)
- `ActionTintBonusTrebuchet` = 20 (trebuchet siege bonus vs structures)
- `ActionTintShield` = 21

**Heal codes:**
- `ActionTintHealMonk` = 30
- `ActionTintHealBread` = 31
- `ActionTintConvertMonk` = 32 (monk conversion of enemy unit)

**Castle unique unit attack tints (40-48):**
- `ActionTintAttackSamurai` = 40 through `ActionTintAttackKing` = 48

**Unit upgrade tier attack tints (49-57):**
- `ActionTintAttackLongSwordsman` = 49 through `ActionTintAttackScorpion` = 57

**Special codes:**
- `ActionTintDeath` = 60 (death animation tint at kill location)
- `ActionTintMixed` = 200 (multiple events overlap on same tile)

These codes are written into the tint layer per world tile as events occur.

## Update mechanics
- `updateObservations()` is a no-op; observations are rebuilt in batch at the
  end of each `step()` call for efficiency.
- `rebuildObservations()` reconstructs full observation buffers from scratch
  (O(agents * tiles) instead of O(updates * agents)).
- The FFI entrypoints copy the buffer directly and apply the obscured mask.

Notes:
- Inventory counts are not encoded in the spatial layers. Inventory update
  hooks exist but are currently no-ops, so inventories must be tracked outside
  the observation tensor.

If you change the observation layout (layers or meanings), update:
- `ObservationName` and related constants in `src/types.nim`.
- Any docs or README sections describing the observation space.
- Any Python wrappers that assume layer indices.
