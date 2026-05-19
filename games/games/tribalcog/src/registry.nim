## registry.nim - Building, terrain, and thing registries for tribal-village
##
## This module provides lookup tables and metadata for all game entities.

import std/[tables, strutils]
import types, items
export types, items

type
  BuildingUseKind* = enum
    UseNone
    UseAltar
    UseClayOven
    UseWeavingLoom
    UseBlacksmith
    UseMarket
    UseDropoff
    UseDropoffAndStorage
    UseStorage
    UseTrain
    UseTrainAndCraft
    UseCraft
    UseDropoffAndTrain  # Dock: resource dropoff + unit training
    UseUniversity  # Research University techs
    UseCastle      # Train unique units + research unique techs

  BuildingInfo* = object
    displayName*: string
    spriteKey*: string
    ascii*: char
    renderColor*: tuple[r, g, b: uint8]
    buildIndex*: int
    buildCost*: seq[ItemAmount]
    buildCooldown*: int

let BuildingRegistry* = block:
  var reg: array[ThingKind, BuildingInfo]
  for kind in ThingKind:
    reg[kind] = BuildingInfo(
      displayName: "",
      spriteKey: "",
      ascii: '?',
      renderColor: (r: 180'u8, g: 180'u8, b: 180'u8),
      buildIndex: -1,
      buildCost: @[],
      buildCooldown: 0
    )

  for entry in [
    (Altar, "Altar", "altar", 'a', (r: 220'u8, g: 0'u8, b: 220'u8), -1, @[], 0),
    (TownCenter, "Town Center", "town_center", 'N', (r: 190'u8, g: 180'u8, b: 140'u8),
      1, @[(ItemWood, 14)], 16),
    (House, "House", "house", 'h', (r: 170'u8, g: 140'u8, b: 110'u8),
      0, @[(ItemWood, 1)], 10),
    (Door, "Door", "door", 'D', (r: 120'u8, g: 100'u8, b: 80'u8),
      BuildIndexDoor, @[(ItemWood, 1)], 6),
    (Wall, "Wall", "oriented/wall", '#', (r: 150'u8, g: 150'u8, b: 150'u8),
      BuildIndexWall, @[(ItemWood, 1)], 6),
    (ClayOven, "Clay Oven", "clay_oven", 'C', (r: 255'u8, g: 180'u8, b: 120'u8),
      20, @[(ItemWood, 4)], 12),
    (WeavingLoom, "Weaving Loom", "weaving_loom", 'W', (r: 0'u8, g: 180'u8, b: 255'u8),
      21, @[(ItemWood, 3)], 12),
    (Outpost, "Outpost", "outpost", '^', (r: 120'u8, g: 120'u8, b: 140'u8),
      13, @[(ItemWood, 1)], 8),
    (GuardTower, "Guard Tower", "guard_tower", 'T', (r: 110'u8, g: 110'u8, b: 130'u8),
      BuildIndexGuardTower, @[(ItemWood, 5)], 12),
    (Barrel, "Barrel", "barrel", 'b', (r: 150'u8, g: 110'u8, b: 60'u8),
      22, @[(ItemWood, 2)], 10),
    (Mill, "Mill", "mill", 'm', (r: 210'u8, g: 200'u8, b: 170'u8),
      2, @[(ItemWood, 5)], 12),
    (Granary, "Granary", "granary", 'n', (r: 220'u8, g: 200'u8, b: 150'u8),
      5, @[(ItemWood, 5)], 12),
    (LumberCamp, "Lumber Camp", "lumber_camp", 'L', (r: 140'u8, g: 100'u8, b: 60'u8),
      3, @[(ItemWood, 5)], 10),
    (Quarry, "Quarry", "quarry", 'Q', (r: 120'u8, g: 120'u8, b: 120'u8),
      4, @[(ItemWood, 5)], 12),
    (MiningCamp, "Mining Camp", "mining_camp", 'M', (r: 200'u8, g: 190'u8, b: 120'u8),
      27, @[(ItemWood, 5)], 12),
    (Barracks, "Barracks", "barracks", 'r', (r: 160'u8, g: 90'u8, b: 60'u8),
      8, @[(ItemWood, 5)], 12),
    (ArcheryRange, "Archery Range", "archery_range", 'g', (r: 140'u8, g: 120'u8, b: 180'u8),
      9, @[(ItemWood, 5)], 12),
    (Stable, "Stable", "stable", 's', (r: 120'u8, g: 90'u8, b: 60'u8),
      10, @[(ItemWood, 5)], 12),
    (SiegeWorkshop, "Siege Workshop", "siege_workshop", 'i', (r: 120'u8, g: 120'u8, b: 160'u8),
      11, @[(ItemWood, 5)], 14),
    (MangonelWorkshop, "Mangonel Workshop", "mangonel_workshop", 'j', (r: 120'u8, g: 130'u8, b: 160'u8),
      BuildIndexMangonelWorkshop, @[(ItemWood, 5), (ItemStone, 2)], 14),
    (TrebuchetWorkshop, "Trebuchet Workshop", "trebuchet_workshop", 'T', (r: 100'u8, g: 110'u8, b: 150'u8),
      25, @[(ItemWood, 5), (ItemStone, 3)], 16),
    (Blacksmith, "Blacksmith", "blacksmith", 'k', (r: 90'u8, g: 90'u8, b: 90'u8),
      16, @[(ItemWood, 5)], 12),
    (Market, "Market", "market", 'e', (r: 200'u8, g: 170'u8, b: 120'u8),
      7, @[(ItemWood, 5)], 12),
    (Dock, "Dock", "dock", 'd', (r: 80'u8, g: 140'u8, b: 200'u8),
      6, @[(ItemWood, 5)], 12),
    (Monastery, "Monastery", "monastery", 'y', (r: 220'u8, g: 200'u8, b: 120'u8),
      17, @[(ItemWood, 5)], 12),
    (University, "University", "university", 'u', (r: 140'u8, g: 160'u8, b: 200'u8),
      18, @[(ItemWood, 5)], 14),
    (Castle, "Castle", "castle", 'c', (r: 120'u8, g: 120'u8, b: 120'u8),
      12, @[(ItemWood, 2), (ItemStone, 5)], 20),
    (Wonder, "Wonder", "wonder", 'W', (r: 255'u8, g: 215'u8, b: 0'u8),
      26, @[(ItemWood, 6), (ItemStone, 2), (ItemGold, 3)], 50),
    (GoblinHive, "Goblin Hive", "goblin_hive", 'H', (r: 120'u8, g: 170'u8, b: 90'u8),
      -1, @[], 0),
    (GoblinHut, "Goblin Hut", "goblin_hut", 'g', (r: 110'u8, g: 150'u8, b: 90'u8),
      -1, @[], 0),
    (GoblinTotem, "Goblin Totem", "goblin_totem", 'T', (r: 90'u8, g: 140'u8, b: 100'u8),
      -1, @[], 0)
  ]:
    let (kind, displayName, spriteKey, ascii, renderColor, buildIndex, buildCost, buildCooldown) = entry
    reg[kind] = BuildingInfo(
      displayName: displayName,
      spriteKey: spriteKey,
      ascii: ascii,
      renderColor: renderColor,
      buildIndex: buildIndex,
      buildCost: buildCost,
      buildCooldown: buildCooldown
    )

  reg

proc toSnakeCase(name: string): string =
  result = ""
  for ch in name:
    if ch.isUpperAscii:
      if result.len > 0:
        result.add('_')
      result.add(ch.toLowerAscii)
    else:
      result.add(ch)

{.push inline.}
proc isBuildingKind*(kind: ThingKind): bool =
  BuildingRegistry[kind].displayName.len > 0

proc thingBlocksMovement*(kind: ThingKind): bool =
  kind notin BackgroundThingKinds
{.pop.}

proc buildingSpriteKey*(kind: ThingKind): string =
  let key = BuildingRegistry[kind].spriteKey
  if key.len == 0: toSnakeCase($kind) else: key

type
  CatalogEntry* = object
    displayName*: string
    spriteKey*: string
    ascii*: char

let TerrainCatalog* = block:
  var reg: array[TerrainType, CatalogEntry]
  for terrain in TerrainType:
    reg[terrain] = CatalogEntry(displayName: "", spriteKey: "", ascii: '?')

  for (terrain, displayName, spriteKey, ascii) in [
    (Empty, "Empty", "", ' '),
    (Water, "Water", "water", '~'),
    (ShallowWater, "Shallow Water", "shallow_water", '.'),
    (Bridge, "Bridge", "bridge", '='),
    (Fertile, "Fertile", "fertile", 'f'),
    (Road, "Road", "road", 'r'),
    (Grass, "Grass", "grass", 'g'),
    (Dune, "Dune", "dune", 'd'),
    (Sand, "Sand", "sand", 's'),
    (Snow, "Snow", "snow", 'n'),
    (Mud, "Mud", "mud", 'm'),
    (Mountain, "Mountain", "dune", 'M'),
    (RampUpN, "Ramp Up North", "oriented/ramp_up_n", '/'),
    (RampUpS, "Ramp Up South", "oriented/ramp_up_s", '/'),
    (RampUpW, "Ramp Up West", "oriented/ramp_up_w", '/'),
    (RampUpE, "Ramp Up East", "oriented/ramp_up_e", '/'),
    (RampDownN, "Ramp Down North", "oriented/ramp_down_n", '\\'),
    (RampDownS, "Ramp Down South", "oriented/ramp_down_s", '\\'),
    (RampDownW, "Ramp Down West", "oriented/ramp_down_w", '\\'),
    (RampDownE, "Ramp Down East", "oriented/ramp_down_e", '\\')
  ]:
    reg[terrain] = CatalogEntry(displayName: displayName, spriteKey: spriteKey, ascii: ascii)
  reg

let ThingCatalog* = block:
  var reg: array[ThingKind, CatalogEntry]
  for kind in ThingKind:
    reg[kind] = CatalogEntry(displayName: "", spriteKey: "", ascii: '?')

  for (kind, displayName, spriteKey, ascii) in [
    (Agent, "Agent", "gatherer", '@'),
    (Wall, "Wall", "oriented/wall", '#'),
    (Tree, "Tree", "tree", 't'),
    (Wheat, "Wheat", "wheat", 'w'),
    (Fish, "Fish", "fish", 'f'),
    (Relic, "Relic", "goblet", 'r'),
    (Stone, "Stone", "stone", 'S'),
    (Gold, "Gold", "gold", 'G'),
    (Bush, "Bush", "bush", 'b'),
    (Cactus, "Cactus", "cactus", 'c'),
    (Stalagmite, "Stalagmite", "stalagmite", 'm'),
    (Magma, "Magma", "magma", 'v'),
    (Spawner, "Spawner", "spawner", 'Z'),
    (Tumor, "Tumor", "tumor", 'X'),
    (Cow, "Cow", "oriented/cow", 'w'),
    (Bear, "Bear", "oriented/bear", 'B'),
    (Wolf, "Wolf", "oriented/wolf", 'W'),
    (Corpse, "Corpse", "corpse", 'C'),
    (Skeleton, "Skeleton", "skeleton", 'K'),
    (Stump, "Stump", "stump", 'p'),
    (Stubble, "Stubble", "stubble", 'u'),
    (Lantern, "Lantern", "lantern", 'l'),
    (Temple, "Temple", "temple", 'T'),
    (ControlPoint, "Control Point", "control_point", 'P'),
    (CliffEdgeN, "Cliff Edge North", "cliff_edge_ew_s", '^'),
    (CliffEdgeE, "Cliff Edge East", "cliff_edge_ns_w", '^'),
    (CliffEdgeS, "Cliff Edge South", "cliff_edge_ew", '^'),
    (CliffEdgeW, "Cliff Edge West", "cliff_edge_ns", '^'),
    (CliffCornerInNE, "Cliff Corner In NE", "oriented/cliff_corner_in_ne", '^'),
    (CliffCornerInSE, "Cliff Corner In SE", "oriented/cliff_corner_in_se", '^'),
    (CliffCornerInSW, "Cliff Corner In SW", "oriented/cliff_corner_in_sw", '^'),
    (CliffCornerInNW, "Cliff Corner In NW", "oriented/cliff_corner_in_nw", '^'),
    (CliffCornerOutNE, "Cliff Corner Out NE", "oriented/cliff_corner_out_ne", '^'),
    (CliffCornerOutSE, "Cliff Corner Out SE", "oriented/cliff_corner_out_se", '^'),
    (CliffCornerOutSW, "Cliff Corner Out SW", "oriented/cliff_corner_out_sw", '^'),
    (CliffCornerOutNW, "Cliff Corner Out NW", "oriented/cliff_corner_out_nw", '^'),
    (WaterfallN, "Waterfall North", "waterfall_n", '~'),
    (WaterfallE, "Waterfall East", "waterfall_e", '~'),
    (WaterfallS, "Waterfall South", "waterfall_s", '~'),
    (WaterfallW, "Waterfall West", "waterfall_w", '~')
  ]:
    reg[kind] = CatalogEntry(displayName: displayName, spriteKey: spriteKey, ascii: ascii)
  reg

let ItemCatalog* = block:
  var reg = initTable[ItemKey, CatalogEntry]()
  for entry in [
    (ItemGold, "Gold", "gold", '$'),
    (ItemStone, "Stone", "stone", 'S'),
    (ItemBar, "Bar", "bar", 'B'),
    (ItemWater, "Water", "droplet", '~'),
    (ItemWheat, "Wheat", "bushel", 'w'),
    (ItemWood, "Wood", "wood", 't'),
    (ItemSpear, "Spear", "spear", 's'),
    (ItemLantern, "Lantern", "lantern", 'l'),
    (ItemArmor, "Armor", "shield", 'a'),
    (ItemBread, "Bread", "bread", 'b'),
    (ItemPlant, "Plant", "plant", 'p'),
    (ItemFish, "Fish", "fish", 'f'),
    (ItemMeat, "Meat", "meat", 'm'),
    (ItemRelic, "Relic", "goblet", 'r'),
    (ItemHearts, "Hearts", "heart", 'h')
  ]:
    let (key, displayName, spriteKey, ascii) = entry
    reg[key] = CatalogEntry(displayName: displayName, spriteKey: spriteKey, ascii: ascii)
  reg

proc terrainSpriteKey*(terrain: TerrainType): string =
  if terrain == Empty:
    return ""
  let key = TerrainCatalog[terrain].spriteKey
  assert key.len > 0, "Missing spriteKey for terrain: " & $terrain
  key


proc thingSpriteKey*(kind: ThingKind): string =
  if isBuildingKind(kind):
    return buildingSpriteKey(kind)
  let key = ThingCatalog[kind].spriteKey
  if key.len > 0:
    return key
  toSnakeCase($kind)

proc itemSpriteKey*(key: ItemKey): string =
  if isThingKey(key):
    for kind in ThingKind:
      if $kind == key.name:
        return thingSpriteKey(kind)
    return key.name
  if ItemCatalog.hasKey(key):
    return ItemCatalog[key].spriteKey
  case key.kind
  of ItemKeyOther:
    key.name
  of ItemKeyItem:
    ItemKindNames[key.item]
  else:
    ""

proc buildingUseKind*(kind: ThingKind): BuildingUseKind =
  case kind
  of Altar: UseAltar
  of ClayOven: UseClayOven
  of WeavingLoom: UseWeavingLoom
  of Blacksmith: UseBlacksmith
  of Market: UseMarket
  of TownCenter, Mill, LumberCamp, Quarry, MiningCamp: UseDropoff
  of Dock: UseDropoffAndTrain
  of Granary: UseDropoffAndStorage
  of Barrel: UseStorage
  of University: UseUniversity
  of Barracks, ArcheryRange, Stable, Monastery, MangonelWorkshop, TrebuchetWorkshop: UseTrain
  of Castle: UseCastle
  of SiegeWorkshop: UseTrainAndCraft
  else: UseNone

proc buildingStockpileRes*(kind: ThingKind): StockpileResource =
  case kind
  of Granary: ResourceFood
  of LumberCamp: ResourceWood
  of Quarry: ResourceStone
  of MiningCamp: ResourceGold
  else: ResourceNone

proc buildingBuildable*(kind: ThingKind): bool =
  let info = BuildingRegistry[kind]
  info.buildIndex >= 0 and info.buildCost.len > 0

proc buildingPopCap*(kind: ThingKind): int =
  case kind
  of TownCenter: TownCenterPopCap
  of House: HousePopCap
  else: 0

proc buildingBarrelCapacity*(kind: ThingKind): int =
  case kind
  of Barrel, Granary, Blacksmith: BarrelCapacity
  else: 0

proc buildingFertileRadius*(kind: ThingKind): int =
  case kind
  of Mill: 2
  else: 0

proc buildingDropoffResources*(kind: ThingKind): set[StockpileResource] =
  case kind
  of TownCenter: {ResourceFood, ResourceWood, ResourceGold, ResourceStone}
  of Granary, Mill: {ResourceFood}
  of LumberCamp: {ResourceWood}
  of Quarry: {ResourceStone}
  of MiningCamp: {ResourceGold}
  of Dock: {ResourceFood}
  else: {}

proc buildingStorageItems*(kind: ThingKind): seq[ItemKey] =
  case kind
  of Granary: @[ItemWheat]
  of Blacksmith: @[ItemArmor, ItemSpear]
  of Barrel: @[
    ItemBread,
    ItemMeat,
    ItemFish,
    ItemPlant,
    ItemLantern,
    ItemSpear,
    ItemArmor,
    ItemBar,
    ItemRelic
  ]
  else: @[]

proc buildingCraftStation*(kind: ThingKind): CraftStation =
  case kind
  of ClayOven: StationOven
  of WeavingLoom: StationLoom
  of Blacksmith: StationBlacksmith
  of University: StationTable
  of SiegeWorkshop: StationSiegeWorkshop
  else: StationNone

proc buildingHasCraftStation*(kind: ThingKind): bool =
  buildingCraftStation(kind) != StationNone

proc buildingHasTrain*(kind: ThingKind): bool =
  kind in {Barracks, ArcheryRange, Stable, SiegeWorkshop, MangonelWorkshop, TrebuchetWorkshop, Monastery, Castle, Dock}

# Castle unique units by team (civilization)
const CastleUniqueUnits*: array[MapRoomObjectsTeams, AgentUnitClass] = [
  UnitSamurai,        # Team 0
  UnitLongbowman,     # Team 1
  UnitCataphract,     # Team 2
  UnitWoadRaider,     # Team 3
  UnitTeutonicKnight, # Team 4
  UnitHuskarl,        # Team 5
  UnitMameluke,       # Team 6
  UnitJanissary       # Team 7
]

proc buildingTrainUnit*(kind: ThingKind, teamId: int = -1): AgentUnitClass =
  ## Returns the unit class trained by a building.
  ## For castles, each team has a unique unit (AoE2-style).
  case kind
  of Barracks: UnitManAtArms
  of ArcheryRange: UnitArcher
  of Stable: UnitScout
  of SiegeWorkshop: UnitBatteringRam
  of MangonelWorkshop: UnitMangonel
  of TrebuchetWorkshop: UnitTrebuchet
  of Monastery: UnitMonk
  of Castle:
    if teamId >= 0 and teamId < MapRoomObjectsTeams:
      CastleUniqueUnits[teamId]
    else:
      UnitKnight  # Fallback for invalid/unknown team
  of Dock: UnitGalley
  else: UnitVillager

proc buildingTrainCosts*(kind: ThingKind): seq[tuple[res: StockpileResource, count: int]] =
  case kind
  of Barracks: @[(res: ResourceFood, count: 3), (res: ResourceGold, count: 1)]
  of ArcheryRange: @[(res: ResourceWood, count: 2), (res: ResourceGold, count: 2)]
  of Stable: @[(res: ResourceFood, count: 3)]
  of SiegeWorkshop: @[(res: ResourceWood, count: 2)]
  of MangonelWorkshop: @[(res: ResourceWood, count: 4)]
  of TrebuchetWorkshop: @[(res: ResourceWood, count: 4), (res: ResourceGold, count: 3)]
  of Monastery: @[(res: ResourceGold, count: 2)]
  of Castle: @[(res: ResourceFood, count: 4), (res: ResourceGold, count: 2)]
  of Dock: @[(res: ResourceWood, count: 3), (res: ResourceGold, count: 2)]
  else: @[]

proc unitTrainTime*(unitClass: AgentUnitClass): int =
  ## Training duration in game steps for each unit type (AoE2-style).
  ## More powerful units take longer to train.
  case unitClass
  of UnitVillager: 50
  of UnitManAtArms: 40
  of UnitArcher: 35
  of UnitScout: 30
  of UnitKnight: 60
  of UnitMonk: 50
  of UnitBatteringRam: 50
  of UnitMangonel: 80
  of UnitTrebuchet: 80
  of UnitGoblin: 30
  of UnitBoat: 60
  # Castle unique units
  of UnitSamurai: 50
  of UnitLongbowman: 45
  of UnitCataphract: 60
  of UnitWoadRaider: 40
  of UnitTeutonicKnight: 55
  of UnitHuskarl: 45
  of UnitMameluke: 55
  of UnitJanissary: 50
  of UnitKing: 0  # Kings are not trainable (placed at game start for Regicide)
  of UnitTradeCog: 60  # Trade Cogs trained at Docks
  # Unit upgrade tiers (use same training time as their base building)
  of UnitLongSwordsman: 45
  of UnitChampion: 50
  of UnitLightCavalry: 35
  of UnitHussar: 40
  of UnitCrossbowman: 40
  of UnitArbalester: 45
  # Naval combat units (trained at Dock)
  of UnitGalley: 60
  of UnitFireShip: 50
  of UnitFishingShip: 40
  of UnitTransportShip: 55
  of UnitDemoShip: 45
  of UnitCannonGalleon: 80
  # Additional siege unit (trained at SiegeWorkshop)
  of UnitScorpion: 70
  # Stable cavalry upgrades
  of UnitCavalier: 65
  of UnitPaladin: 70
  # Camel line (trained at Stable)
  of UnitCamel: 55
  of UnitHeavyCamel: 60
  of UnitImperialCamel: 65
  # Archery Range units
  of UnitSkirmisher: 35
  of UnitEliteSkirmisher: 40
  of UnitCavalryArcher: 45
  of UnitHeavyCavalryArcher: 50
  of UnitHandCannoneer: 45

proc buildIndexFor*(kind: ThingKind): int =
  BuildingRegistry[kind].buildIndex

proc appendBuildingRecipes*(recipes: var seq[CraftRecipe]) =
  for kind in ThingKind:
    if not isBuildingKind(kind):
      continue
    if not buildingBuildable(kind):
      continue
    let info = BuildingRegistry[kind]
    addRecipe(
      recipes,
      toSnakeCase($kind),
      StationTable,
      info.buildCost,
      @[(thingItem($kind), 1)]
    )
