import std/[tables, strutils, options]

import common
import nlanky_types
import nlanky_entity_map

const
  SpawnRow = 100
  SpawnCol = 100

proc powBase(base: int, power: int): int =
  result = 1
  for _ in 0 ..< power:
    result *= base

proc parseDigitString(value: string): int =
  result = 0
  for ch in value:
    result = result * 10 + (ord(ch) - ord('0'))

type
  ObsParser* = ref object
    obsHr: int
    obsWr: int
    tagNames: seq[string]              # tag_id -> name (alphabetical)
    vibeNames: seq[string]             # vibe_id -> name, derived from action names
    featureNameById: Table[int, string] # feature_id -> feature name

proc newObsParser*(cfg: Config): ObsParser =
  var featureNameById = initTable[int, string]()
  for f in cfg.config.obsFeatures:
    featureNameById[f.id] = f.name

  ObsParser(
    obsHr: cfg.config.obsHeight div 2,
    obsWr: cfg.config.obsWidth div 2,
    tagNames: cfg.config.tags,
    # Prefer config-derived vibe names (from change_vibe_* actions).
    vibeNames: cfg.vibeNames,
    featureNameById: featureNameById,
  )

proc getVibeName(parser: ObsParser, vibeId: int): string =
  if vibeId >= 0 and vibeId < parser.vibeNames.len:
    return parser.vibeNames[vibeId]
  "default"

proc resolveObjectName(parser: ObsParser, tagIds: seq[int]): string =
  # Priority: type:* tags
  for tid in tagIds:
    if tid >= 0 and tid < parser.tagNames.len:
      let tag = parser.tagNames[tid]
      if tag.startsWith("type:"):
        return tag[5 .. ^1]
  # Otherwise: non-team tags
  for tid in tagIds:
    if tid >= 0 and tid < parser.tagNames.len:
      let tag = parser.tagNames[tid]
      if tag.len > 0 and not tag.startsWith("team:"):
        return tag
  "unknown"

proc deriveAlignment(objName: string, territory: int, tagNames: seq[string], tagIds: seq[int]): Alignment =
  for tid in tagIds:
    if tid >= 0 and tid < tagNames.len:
      let tag = tagNames[tid]
      if tag == "team:cogs":
        return alCogs
      if tag == "team:clips":
        return alClips
  # Territory influence should not imply ownership for neutral junctions.
  if "junction" in objName:
    return alNone
  if "c:" in objName:
    return alCogs
  if "clips" in objName:
    return alClips
  if territory == 1:
    return alCogs
  if territory == 2:
    return alClips
  alNone

proc parse*(
  parser: ObsParser,
  cfg: Config,
  visible: Table[Location, seq[FeatureValue]],
  step: int,
  lastPos: Option[Location] = none(Location)
): tuple[state: StateSnapshot, visibleEntities: Table[Location, Entity]] {.raises: [].} =
  discard lastPos
  var s: StateSnapshot
  let lpOffset = cfg.getLocalPositionOffset(visible)
  s.position = Location(x: SpawnCol + lpOffset.x, y: SpawnRow + lpOffset.y)

  # Inventory (center cell)
  s.energy = cfg.getInventory(visible, cfg.features.invEnergy)
  s.hp = cfg.getInventory(visible, cfg.features.invHp)
  s.carbon = cfg.getInventory(visible, cfg.features.invCarbon)
  s.oxygen = cfg.getInventory(visible, cfg.features.invOxygen)
  s.germanium = cfg.getInventory(visible, cfg.features.invGermanium)
  s.silicon = cfg.getInventory(visible, cfg.features.invSilicon)
  s.heart = cfg.getInventory(visible, cfg.features.invHeart)
  s.influence =
    if cfg.features.invInfluence != 0:
      cfg.getInventory(visible, cfg.features.invInfluence)
    else:
      0

  s.minerGear = cfg.getInventory(visible, cfg.features.invMiner) > 0
  s.scoutGear = cfg.getInventory(visible, cfg.features.invScout) > 0
  s.alignerGear = cfg.getInventory(visible, cfg.features.invAligner) > 0
  s.scramblerGear = cfg.getInventory(visible, cfg.features.invScrambler) > 0

  let vibeId = cfg.getVibe(visible, Location(x: 0, y: 0))
  s.vibe = parser.getVibeName(vibeId)

  # Team inventory (global inv tokens are also mapped to (0,0)).
  s.teamCarbon = cfg.getInventory(visible, cfg.features.invTeamCarbon)
  s.teamOxygen = cfg.getInventory(visible, cfg.features.invTeamOxygen)
  s.teamGermanium = cfg.getInventory(visible, cfg.features.invTeamGermanium)
  s.teamSilicon = cfg.getInventory(visible, cfg.features.invTeamSilicon)
  # Optional; keep 0 if missing.
  s.teamHeart = cfg.getInventory(visible, cfg.features.invTeamHeart)
  s.teamInfluence = cfg.getInventory(visible, cfg.features.invTeamInfluence)

  let territoryByLocation = cfg.reconstructTerritory(visible)
  var ents = initTable[Location, Entity]()

  for relLoc, feats in visible:
    # Skip center cell; it is used for self inventory/vibe.
    if relLoc.x == 0 and relLoc.y == 0:
      continue

    var tagIds: seq[int] = @[]
    var invByName = initTable[string, int]()

    for fv in feats:
      if fv.featureId == cfg.features.tag:
        tagIds.add(fv.value)
      else:
        # Best-effort per-cell inventory reconstruction (extractor inventories).
        let fname = parser.featureNameById.getOrDefault(fv.featureId, "")
        if fname.startsWith("inv:"):
          let suffix = fname[4 .. ^1]
          let powerIndex = suffix.rfind(":p")
          let inventoryBase = if cfg.inventoryTokenBase > 1: cfg.inventoryTokenBase else: 256
          if powerIndex != -1:
            let baseName = suffix[0 ..< powerIndex]
            let powerStr = suffix[powerIndex + 2 .. ^1]
            if baseName.len > 0 and powerStr.len > 0 and powerStr.allCharsInSet({'0' .. '9'}):
              let power = parseDigitString(powerStr)
              invByName[baseName] = invByName.getOrDefault(baseName, 0) + fv.value * powBase(inventoryBase, power)
            else:
              invByName[suffix] = invByName.getOrDefault(suffix, 0) + fv.value
          else:
            invByName[suffix] = invByName.getOrDefault(suffix, 0) + fv.value

    if tagIds.len == 0:
      continue

    let objName = parser.resolveObjectName(tagIds)
    if objName == "unknown":
      continue

    var invAmount = -1
    if invByName.len > 0:
      invAmount = 0
      for _, v in invByName:
        invAmount += v

    let absPos = Location(x: s.position.x + relLoc.x, y: s.position.y + relLoc.y)
    let territory = territoryByLocation.getOrDefault(relLoc, 0)
    let alignment = deriveAlignment(objName, territory, parser.tagNames, tagIds)

    let entityVibeId = cfg.getVibe(visible, relLoc)
    let entityVibe = parser.getVibeName(entityVibeId)

    ents[absPos] = Entity(
      kind: objName,
      alignment: alignment,
      inventoryAmount: invAmount,
      lastSeen: step,
      vibe: entityVibe,
    )

  (state: s, visibleEntities: ents)

proc obsHalfHeight*(parser: ObsParser): int =
  parser.obsHr

proc obsHalfWidth*(parser: ObsParser): int =
  parser.obsWr
