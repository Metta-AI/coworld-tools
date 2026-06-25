## Item catalog and container definitions for future stockpile/storage work.
## This keeps the "what exists" separate from game logic.

import std/tables
import std/hashes

type
  ## Type-safe enum for all item kinds
  ItemKind* = enum
    ikNone = "none"
    ikGold = "gold"
    ikStone = "stone"
    ikBar = "bar"
    ikWater = "water"
    ikWheat = "wheat"
    ikWood = "wood"
    ikSpear = "spear"
    ikLantern = "lantern"
    ikArmor = "armor"
    ikBread = "bread"
    ikPlant = "plant"
    ikFish = "fish"
    ikMeat = "meat"
    ikRelic = "relic"
    ikHearts = "hearts"

  ItemKeyKind* = enum
    ItemKeyNone
    ItemKeyItem
    ItemKeyThing
    ItemKeyOther

  ## ItemKey represents inventory entries and craft/build outputs.
  ## - ItemKeyItem: core item kinds (typed)
  ## - ItemKeyThing: buildable/placeable things by name
  ## - ItemKeyOther: extra recipe-only items
  ItemKey* = object
    case kind*: ItemKeyKind
    of ItemKeyNone:
      discard
    of ItemKeyItem:
      item*: ItemKind
    of ItemKeyThing, ItemKeyOther:
      name*: string

  ## Optimized inventory: array for ItemKind, Table for rare items
  Inventory* = object
    items*: array[ItemKind, int16]  # O(1) direct indexing for common items
    extra*: Table[ItemKey, int16]   # Hash table for ItemKeyThing/ItemKeyOther

const
  SpearCharges* = 5       # Spears forged per craft & max carried
  ArmorPoints* = 5        # Armor durability granted per craft
  BreadHealAmount* = 999  # Effectively "heal to full" per bread use

  ItemKindNames*: array[ItemKind, string] = [
    "",        # ikNone
    "gold",
    "stone",
    "bar",
    "water",
    "wheat",
    "wood",
    "spear",
    "lantern",
    "armor",
    "bread",
    "plant",
    "fish",
    "meat",
    "relic",
    "hearts"
  ]

  ItemNone* = ItemKey(kind: ItemKeyNone)
  ItemGold* = ItemKey(kind: ItemKeyItem, item: ikGold)
  ItemStone* = ItemKey(kind: ItemKeyItem, item: ikStone)
  ItemBar* = ItemKey(kind: ItemKeyItem, item: ikBar)
  ItemWater* = ItemKey(kind: ItemKeyItem, item: ikWater)
  ItemWheat* = ItemKey(kind: ItemKeyItem, item: ikWheat)
  ItemWood* = ItemKey(kind: ItemKeyItem, item: ikWood)
  ItemSpear* = ItemKey(kind: ItemKeyItem, item: ikSpear)
  ItemLantern* = ItemKey(kind: ItemKeyItem, item: ikLantern)
  ItemArmor* = ItemKey(kind: ItemKeyItem, item: ikArmor)
  ItemBread* = ItemKey(kind: ItemKeyItem, item: ikBread)
  ItemPlant* = ItemKey(kind: ItemKeyItem, item: ikPlant)
  ItemFish* = ItemKey(kind: ItemKeyItem, item: ikFish)
  ItemMeat* = ItemKey(kind: ItemKeyItem, item: ikMeat)
  ItemRelic* = ItemKey(kind: ItemKeyItem, item: ikRelic)
  ItemHearts* = ItemKey(kind: ItemKeyItem, item: ikHearts)

  ObservedItemKeys* = [
    ItemGold,
    ItemStone,
    ItemBar,
    ItemWater,
    ItemWheat,
    ItemWood,
    ItemSpear,
    ItemLantern,
    ItemArmor,
    ItemBread,
    ItemMeat,
    ItemFish,
    ItemPlant
  ]

proc toItemKey*(kind: ItemKind): ItemKey {.inline.} =
  ## Convert ItemKind enum to ItemKey
  if kind == ikNone:
    ItemNone
  else:
    ItemKey(kind: ItemKeyItem, item: kind)

proc `$`*(key: ItemKey): string =
  case key.kind
  of ItemKeyNone:
    ""
  of ItemKeyItem:
    ItemKindNames[key.item]
  of ItemKeyThing, ItemKeyOther:
    key.name

proc isThingKey*(key: ItemKey): bool =
  key.kind == ItemKeyThing

proc `==`*(a, b: ItemKey): bool =
  if a.kind != b.kind:
    return false
  case a.kind
  of ItemKeyNone:
    true
  of ItemKeyItem:
    a.item == b.item
  of ItemKeyThing, ItemKeyOther:
    a.name == b.name

proc hash*(key: ItemKey): Hash =
  var h = hash(key.kind)
  case key.kind
  of ItemKeyNone:
    discard
  of ItemKeyItem:
    h = h !& hash(key.item)
  of ItemKeyThing, ItemKeyOther:
    h = h !& hash(key.name)
  result = !$h

type
  StockpileResource* = enum
    ResourceFood
    ResourceWood
    ResourceGold
    ResourceStone
    ResourceWater
    ResourceNone

proc isFoodItem*(key: ItemKey): bool =
  ## Check if an ItemKey is a food item
  key.kind == ItemKeyItem and key.item in {ikWheat, ikBread, ikFish, ikMeat, ikPlant}

proc stockpileResourceForItem*(key: ItemKey): StockpileResource =
  if isFoodItem(key):
    return ResourceFood
  if key.kind != ItemKeyItem:
    return ResourceNone
  case key.item
  of ikWood: ResourceWood
  of ikGold: ResourceGold
  of ikStone: ResourceStone
  of ikWater: ResourceWater
  else: ResourceNone

proc isStockpileResourceKey*(key: ItemKey): bool =
  stockpileResourceForItem(key) != ResourceNone

proc emptyInventory*(): Inventory =
  Inventory(extra: initTable[ItemKey, int16]())

proc len*(inv: Inventory): int {.inline.} =
  ## Count non-zero items in inventory
  result = inv.extra.len
  for kind in ItemKind:
    if kind != ikNone and inv.items[kind] > 0:
      inc result

proc hasKey*(inv: Inventory, key: ItemKey): bool {.inline.} =
  ## Check if inventory has non-zero count for key
  case key.kind
  of ItemKeyNone:
    false
  of ItemKeyItem:
    inv.items[key.item] > 0
  of ItemKeyThing, ItemKeyOther:
    inv.extra.hasKey(key)

iterator pairs*(inv: Inventory): (ItemKey, int) =
  ## Iterate over all non-zero items in inventory
  for kind in ItemKind:
    if kind != ikNone and inv.items[kind] > 0:
      yield (toItemKey(kind), inv.items[kind])
  for key, count in inv.extra.pairs:
    yield (key, count)

proc `[]=`*(inv: var Inventory, key: ItemKey, value: int) {.inline.} =
  ## Set inventory value by ItemKey
  case key.kind
  of ItemKeyNone:
    discard
  of ItemKeyItem:
    inv.items[key.item] = max(0, value).int16
  of ItemKeyThing, ItemKeyOther:
    if value <= 0:
      inv.extra.del(key)
    else:
      inv.extra[key] = value.int16

proc `[]`*(inv: Inventory, key: ItemKey): int {.inline.} =
  ## Get inventory value by ItemKey
  case key.kind
  of ItemKeyNone:
    0
  of ItemKeyItem:
    inv.items[key.item]
  of ItemKeyThing, ItemKeyOther:
    inv.extra.getOrDefault(key, 0)

proc del*(inv: var Inventory, key: ItemKey) {.inline.} =
  ## Remove item from inventory (set to 0)
  case key.kind
  of ItemKeyNone:
    discard
  of ItemKeyItem:
    inv.items[key.item] = 0
  of ItemKeyThing, ItemKeyOther:
    inv.extra.del(key)

{.push inline.}
proc getInv*[T](thing: T, key: ItemKey): int =
  thing.inventory[key]

proc getInv*[T](thing: T, kind: ItemKind): int =
  thing.inventory.items[kind]

proc setInv*[T](thing: T, key: ItemKey, value: int) =
  thing.inventory[key] = value

proc setInv*[T](thing: T, kind: ItemKind, value: int) =
  thing.inventory.items[kind] = max(0, value).int16

proc canSpendInventory*[T](agent: T, costs: openArray[tuple[key: ItemKey, count: int]]): bool =
  for cost in costs:
    if getInv(agent, cost.key) < cost.count:
      return false
  true
{.pop.}

type PaymentSource* = enum
  PayNone
  PayInventory
  PayStockpile

template defineInventoryAccessors(name, key: untyped) =
  proc `name`*[T](agent: T): int =
    getInv(agent, key)

  proc `name=`*[T](agent: T, value: int) =
    setInv(agent, key, value)

defineInventoryAccessors(inventoryGold, ItemGold)
defineInventoryAccessors(inventoryStone, ItemStone)
defineInventoryAccessors(inventoryBar, ItemBar)
defineInventoryAccessors(inventoryWater, ItemWater)
defineInventoryAccessors(inventoryWheat, ItemWheat)
defineInventoryAccessors(inventoryWood, ItemWood)
defineInventoryAccessors(inventorySpear, ItemSpear)
defineInventoryAccessors(inventoryLantern, ItemLantern)
defineInventoryAccessors(inventoryArmor, ItemArmor)
defineInventoryAccessors(inventoryBread, ItemBread)
defineInventoryAccessors(inventoryRelic, ItemRelic)
defineInventoryAccessors(hearts, ItemHearts)

type
  ItemAmount* = tuple[key: ItemKey, count: int]

  CraftStation* = enum
    StationNone
    StationBlacksmith
    StationLoom
    StationOven
    StationTable
    StationSiegeWorkshop

  CraftRecipe* = object
    id*: string
    station*: CraftStation
    inputs*: seq[ItemAmount]
    outputs*: seq[ItemAmount]

proc addRecipe*(recipes: var seq[CraftRecipe], id: string, station: CraftStation,
                inputs, outputs: seq[ItemAmount]) =
  recipes.add(CraftRecipe(id: id, station: station, inputs: inputs, outputs: outputs))

proc thingItem*(name: string): ItemKey =
  ItemKey(kind: ItemKeyThing, name: name)

proc otherItem*(name: string): ItemKey =
  ItemKey(kind: ItemKeyOther, name: name)

proc initCraftRecipesBase*(): seq[CraftRecipe] =
  var recipes: seq[CraftRecipe] = @[]

  # Table/workbench: wood and stone crafts.
  # Siege workshop crafts for walls/roads (1/20 AoE2 scale).
  addRecipe(recipes, "wall", StationSiegeWorkshop, @[(ItemWood, 1)], @[(thingItem("Wall"), 1)])
  addRecipe(recipes, "road", StationSiegeWorkshop, @[(ItemWood, 1)], @[(thingItem("Road"), 1)])
  addRecipe(recipes, "bucket", StationTable, @[(ItemWood, 1)], @[(otherItem("bucket"), 1)])
  addRecipe(recipes, "box", StationTable, @[(ItemWood, 1)], @[(otherItem("box"), 1)])
  addRecipe(recipes, "bin", StationTable, @[(ItemWood, 2)], @[(otherItem("bin"), 1)])
  addRecipe(recipes, "cabinet", StationTable, @[(ItemWood, 2)], @[(otherItem("cabinet"), 1)])
  addRecipe(recipes, "cage", StationTable, @[(ItemWood, 2)], @[(otherItem("cage"), 1)])
  addRecipe(recipes, "animaltrap", StationTable, @[(ItemWood, 1)], @[(otherItem("animaltrap"), 1)])
  addRecipe(recipes, "armorstand_wood", StationTable, @[(ItemWood, 2)], @[(otherItem("armorstand"), 1)])
  addRecipe(recipes, "weaponrack_wood", StationTable, @[(ItemWood, 2)], @[(otherItem("weaponrack"), 1)])
  # Blacksmith: metalworking and mechanisms.
  addRecipe(recipes, "spear", StationBlacksmith, @[(ItemWood, 1)], @[(ItemSpear, SpearCharges)])
  addRecipe(recipes, "armor_metal", StationBlacksmith, @[(ItemBar, 2)], @[(ItemArmor, ArmorPoints)])
  addRecipe(recipes, "spear_metal", StationBlacksmith, @[(ItemBar, 1)], @[(ItemSpear, SpearCharges)])
  addRecipe(recipes, "shield_metal", StationBlacksmith, @[(ItemBar, 1)], @[(otherItem("shield"), 1)])
  addRecipe(recipes, "anvil", StationBlacksmith, @[(ItemBar, 2)], @[(otherItem("anvil"), 1)])
  addRecipe(recipes, "goblet", StationBlacksmith, @[(ItemBar, 1)], @[(otherItem("goblet"), 1)])
  addRecipe(recipes, "crown", StationBlacksmith, @[(ItemBar, 1)], @[(otherItem("crown"), 1)])
  addRecipe(recipes, "armorstand_metal", StationBlacksmith, @[(ItemBar, 1)], @[(otherItem("armorstand"), 1)])
  addRecipe(recipes, "weaponrack_metal", StationBlacksmith, @[(ItemBar, 1)], @[(otherItem("weaponrack"), 1)])
  # Oven: food.
  addRecipe(recipes, "bread", StationOven, @[(ItemWheat, 1)], @[(ItemBread, 1)])

  recipes

var CraftRecipes*: seq[CraftRecipe] = initCraftRecipesBase()
