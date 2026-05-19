## Rich tooltip helpers for UI elements.
##
## Uses boxy for background rectangles and cached text labels.

import
  std/[strutils, strformat],
  boxy, pixie, vmath, windy,
  common, constants, environment, items, label_cache, registry,
  renderer_core, types

type
  TooltipKind* = enum
    TooltipNone
    TooltipCommand

  TooltipContent* = object
    title*: string
    description*: string
    costLines*: seq[string]
    statsLines*: seq[string]
    hotkeyLine*: string

  TooltipState* = object
    kind*: TooltipKind
    visible*: bool
    content*: TooltipContent
    position*: Vec2
    anchorRect*: Rect
    hoverStartTime*: float64
    showDelay*: float64

const
  # Reuse the shared UI palette for tooltip colors.
  TooltipBgColor = UiTooltipBg
  TooltipBorderColor = UiTooltipBorder
  TooltipTitleColor = UiTooltipTitle
  TooltipTextColor = UiTooltipText
  TooltipCostColor = UiTooltipCost
  TooltipHotkeyColor = UiTooltipHotkey

  # Tooltip layout values live in renderer_core.nim.

var
  tooltipState*: TooltipState

proc renderTooltipLabel(
  text: string,
  fontSize: float32,
  textColor: Color
): (string, IVec2) =
  ## Render a text label and return the image key and size.
  let style = labelStyle(
    TooltipFontPath,
    fontSize,
    TooltipLabelPadding,
    0.0,
    textColor
  )
  let cached = ensureLabel("tooltip", text, style)
  return (cached.imageKey, cached.size)

proc resourceName(res: StockpileResource): string =
  ## Return the display name for a stockpile resource.
  case res
  of ResourceFood: "Food"
  of ResourceWood: "Wood"
  of ResourceStone: "Stone"
  of ResourceGold: "Gold"
  of ResourceWater: "Water"
  of ResourceNone: ""

proc itemKeyName(key: ItemKey): string =
  ## Return the display name for an item key.
  case key.kind
  of ItemKeyItem:
    # Capitalize the item name for display.
    let name = ItemKindNames[key.item]
    if name.len > 0:
      name[0].toUpperAscii & name[1..^1]
    else:
      ""
  of ItemKeyOther, ItemKeyThing:
    key.name
  of ItemKeyNone:
    ""

proc getCommandDescription*(kind: CommandButtonKind): string =
  ## Get detailed description for a command button.
  case kind
  of CmdNone: ""
  of CmdMove: "Move selected units to a target location."
  of CmdAttack: "Attack an enemy unit or building. Right-click to attack-move."
  of CmdStop: "Stop all current actions and hold position."
  of CmdPatrol: "Patrol between current position and target. Units attack enemies in range."
  of CmdStance: "Cycle combat stance: Aggressive, Defensive, Stand Ground, No Attack."
  of CmdHoldPosition: "Hold current position. Units attack nearby enemies but don't chase."
  of CmdBuild: "Open the building menu to construct structures."
  of CmdGather: "Gather resources from trees, farms, mines, or fishing spots."
  of CmdBuildBack: "Return to main command menu."
  of CmdBuildHouse: "Provides 5 population capacity."
  of CmdBuildMill: "Drop off food. Creates fertile land for farms nearby."
  of CmdBuildLumberCamp: "Drop off wood closer to tree lines."
  of CmdBuildMiningCamp: "Drop off gold and stone closer to mines."
  of CmdBuildBarracks: "Train infantry: Man-at-Arms."
  of CmdBuildArcheryRange: "Train ranged units: Archers."
  of CmdBuildStable: "Train cavalry: Scouts, Knights."
  of CmdBuildWall: "Defensive wall segment."
  of CmdBuildBlacksmith: "Research weapon and armor upgrades."
  of CmdBuildMarket: "Trade resources and research economy techs."
  of CmdSetRally: "Set rally point for newly trained units."
  of CmdUngarrison: "Ungarrison all units from this building."
  of CmdTrainVillager: "Train a villager to gather resources and construct buildings."
  of CmdTrainManAtArms: "Infantry unit with balanced stats."
  of CmdTrainArcher: "Ranged unit effective against infantry."
  of CmdTrainScout: "Fast cavalry for exploration and raiding."
  of CmdTrainKnight: "Heavy cavalry with high attack and armor."
  of CmdTrainMonk: "Can heal friendly units and convert enemies."
  of CmdTrainBatteringRam: "Siege unit effective against buildings."
  of CmdTrainMangonel: "Ranged siege unit with area damage."
  of CmdTrainTrebuchet: "Long-range siege unit. Must unpack to fire."
  of CmdTrainBoat: "Naval unit for water control."
  of CmdTrainTradeCog: "Trade ship that generates gold on trade routes."
  of CmdTrainGalley: "Combat warship with ranged attack."
  of CmdTrainFireShip: "Anti-ship unit with fire attack. Bonus vs ships."
  of CmdTrainFishingShip: "Economic ship that gathers fish resources."
  of CmdTrainTransportShip: "Transport ship that carries land units across water."
  of CmdTrainDemoShip: "Demolition ship. Explodes on contact for massive damage."
  of CmdTrainCannonGalleon: "Long-range artillery ship. Effective vs buildings."
  of CmdFormationLine: "Arrange selected units in a horizontal line formation."
  of CmdFormationBox: "Arrange selected units in a defensive box formation."
  of CmdFormationStaggered: "Arrange selected units in a staggered formation for ranged combat."
  of CmdFormationRangedSpread: "Spread ranged units to avoid friendly fire."
  # Blacksmith research descriptions.
  of CmdResearchMeleeAttack: "Forging line: +1 melee attack per tier. Affects infantry and cavalry."
  of CmdResearchArcherAttack: "Fletching line: +1 ranged attack per tier. Affects archers and towers."
  of CmdResearchInfantryArmor: "Scale Mail line: +1 infantry armor per tier."
  of CmdResearchCavalryArmor: "Scale Barding line: +1 cavalry armor per tier."
  of CmdResearchArcherArmor: "Padded Archer line: +1 archer armor per tier."
  # University research descriptions.
  of CmdResearchBallistics: "Projectiles lead moving targets for better accuracy."
  of CmdResearchMurderHoles: "Towers can attack adjacent units (no minimum range)."
  of CmdResearchMasonry: "+10% building HP, +1/+1 building armor."
  of CmdResearchArchitecture: "+10% building HP, +1/+1 building armor (stacks with Masonry)."
  of CmdResearchTreadmillCrane: "+20% construction speed for villagers."
  of CmdResearchArrowslits: "+1 tower attack damage."
  of CmdResearchHeatedShot: "+2 attack vs ships for towers and castles."
  of CmdResearchSiegeEngineers: "+1 range, +20% building damage for siege units."
  of CmdResearchChemistry: "Enables gunpowder units (future tech)."
  of CmdResearchCoinage: "Reduces tribute tax rate from 20% to 10%."
  # Castle research descriptions.
  of CmdResearchCastleTech1: "Team's unique Castle Age technology."
  of CmdResearchCastleTech2: "Team's unique Imperial Age technology."
  # Mill commands.
  of CmdQueueFarm: "Queue a farm reseed. When a farm within range is exhausted, it auto-rebuilds."

proc getCommandCosts*(kind: CommandButtonKind): seq[string] =
  ## Get resource costs for a command (building or training).
  result = @[]

  # Add building costs.
  case kind
  of CmdBuildHouse:
    let info = BuildingRegistry[House]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  of CmdBuildMill:
    let info = BuildingRegistry[Mill]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  of CmdBuildLumberCamp:
    let info = BuildingRegistry[LumberCamp]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  of CmdBuildMiningCamp:
    let info = BuildingRegistry[MiningCamp]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  of CmdBuildBarracks:
    let info = BuildingRegistry[Barracks]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  of CmdBuildArcheryRange:
    let info = BuildingRegistry[ArcheryRange]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  of CmdBuildStable:
    let info = BuildingRegistry[Stable]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  of CmdBuildWall:
    let info = BuildingRegistry[Wall]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  of CmdBuildBlacksmith:
    let info = BuildingRegistry[Blacksmith]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  of CmdBuildMarket:
    let info = BuildingRegistry[Market]
    for item in info.buildCost:
      result.add(&"{itemKeyName(item.key)}: {item.count}")
  # Add training costs.
  of CmdTrainVillager:
    result.add(&"Food: {VillagerTrainFoodCost}")
  of CmdTrainManAtArms:
    let costs = buildingTrainCosts(Barracks)
    for cost in costs:
      result.add(&"{resourceName(cost.res)}: {cost.count}")
  of CmdTrainArcher:
    let costs = buildingTrainCosts(ArcheryRange)
    for cost in costs:
      result.add(&"{resourceName(cost.res)}: {cost.count}")
  of CmdTrainScout:
    let costs = buildingTrainCosts(Stable)
    for cost in costs:
      result.add(&"{resourceName(cost.res)}: {cost.count}")
  of CmdTrainKnight:
    result.add(&"Food: {KnightTrainFoodCost}")
    result.add(&"Gold: {KnightTrainGoldCost}")
  of CmdTrainMonk:
    let costs = buildingTrainCosts(Monastery)
    for cost in costs:
      result.add(&"{resourceName(cost.res)}: {cost.count}")
  of CmdTrainBatteringRam:
    let costs = buildingTrainCosts(SiegeWorkshop)
    for cost in costs:
      result.add(&"{resourceName(cost.res)}: {cost.count}")
  of CmdTrainMangonel:
    let costs = buildingTrainCosts(MangonelWorkshop)
    for cost in costs:
      result.add(&"{resourceName(cost.res)}: {cost.count}")
  of CmdTrainTrebuchet:
    let costs = buildingTrainCosts(TrebuchetWorkshop)
    for cost in costs:
      result.add(&"{resourceName(cost.res)}: {cost.count}")
  of CmdTrainBoat:
    result.add(&"Wood: {BoatTrainWoodCost}")
  of CmdTrainTradeCog, CmdTrainGalley, CmdTrainFireShip, CmdTrainFishingShip,
     CmdTrainTransportShip, CmdTrainDemoShip, CmdTrainCannonGalleon:
    let costs = buildingTrainCosts(Dock)
    for cost in costs:
      result.add(&"{resourceName(cost.res)}: {cost.count}")
  # Add blacksmith research costs.
  of CmdResearchMeleeAttack, CmdResearchArcherAttack, CmdResearchInfantryArmor,
     CmdResearchCavalryArmor, CmdResearchArcherArmor:
    # Show the tier-1 base cost and note that later tiers scale up.
    result.add(&"Food: {BlacksmithUpgradeFoodCost} per tier")
    result.add(&"Gold: {BlacksmithUpgradeGoldCost} per tier")
  # Add university research costs.
  of CmdResearchBallistics, CmdResearchMurderHoles, CmdResearchMasonry,
     CmdResearchArchitecture, CmdResearchTreadmillCrane, CmdResearchArrowslits,
     CmdResearchHeatedShot, CmdResearchSiegeEngineers, CmdResearchChemistry,
     CmdResearchCoinage:
    result.add(&"Food: {UniversityTechFoodCost}+ (scales)")
    result.add(&"Gold: {UniversityTechGoldCost}+ (scales)")
    result.add(&"Wood: {UniversityTechWoodCost}+ (scales)")
  # Add castle research costs.
  of CmdResearchCastleTech1:
    result.add(&"Food: {CastleTechFoodCost}")
    result.add(&"Gold: {CastleTechGoldCost}")
  of CmdResearchCastleTech2:
    result.add(&"Food: {CastleTechImperialFoodCost}")
    result.add(&"Gold: {CastleTechImperialGoldCost}")
  # Add mill command costs.
  of CmdQueueFarm:
    result.add(&"Wood: {FarmReseedWoodCost}")
  else:
    discard

proc getTrainingTime*(kind: CommandButtonKind): string =
  ## Get training time for training commands.
  case kind
  of CmdTrainVillager: &"Train time: {unitTrainTime(UnitVillager)} steps"
  of CmdTrainManAtArms: &"Train time: {unitTrainTime(UnitManAtArms)} steps"
  of CmdTrainArcher: &"Train time: {unitTrainTime(UnitArcher)} steps"
  of CmdTrainScout: &"Train time: {unitTrainTime(UnitScout)} steps"
  of CmdTrainKnight: &"Train time: {unitTrainTime(UnitKnight)} steps"
  of CmdTrainMonk: &"Train time: {unitTrainTime(UnitMonk)} steps"
  of CmdTrainBatteringRam:
    &"Train time: {unitTrainTime(UnitBatteringRam)} steps"
  of CmdTrainMangonel: &"Train time: {unitTrainTime(UnitMangonel)} steps"
  of CmdTrainTrebuchet: &"Train time: {unitTrainTime(UnitTrebuchet)} steps"
  of CmdTrainBoat: &"Train time: {unitTrainTime(UnitBoat)} steps"
  of CmdTrainTradeCog: &"Train time: {unitTrainTime(UnitTradeCog)} steps"
  of CmdTrainGalley: &"Train time: {unitTrainTime(UnitGalley)} steps"
  of CmdTrainFireShip: &"Train time: {unitTrainTime(UnitFireShip)} steps"
  of CmdTrainFishingShip: &"Train time: {unitTrainTime(UnitFishingShip)} steps"
  of CmdTrainTransportShip:
    &"Train time: {unitTrainTime(UnitTransportShip)} steps"
  of CmdTrainDemoShip: &"Train time: {unitTrainTime(UnitDemoShip)} steps"
  of CmdTrainCannonGalleon:
    &"Train time: {unitTrainTime(UnitCannonGalleon)} steps"
  else: ""

proc buildCommandTooltip*(
  kind: CommandButtonKind,
  hotkey: string
): TooltipContent =
  ## Build tooltip content for a command button.
  result.title = case kind
    of CmdNone: ""
    of CmdMove: "Move"
    of CmdAttack: "Attack"
    of CmdStop: "Stop"
    of CmdPatrol: "Patrol"
    of CmdStance: "Change Stance"
    of CmdHoldPosition: "Hold Position"
    of CmdBuild: "Build Menu"
    of CmdGather: "Gather"
    of CmdBuildBack: "Back"
    of CmdBuildHouse: "Build House"
    of CmdBuildMill: "Build Mill"
    of CmdBuildLumberCamp: "Build Lumber Camp"
    of CmdBuildMiningCamp: "Build Mining Camp"
    of CmdBuildBarracks: "Build Barracks"
    of CmdBuildArcheryRange: "Build Archery Range"
    of CmdBuildStable: "Build Stable"
    of CmdBuildWall: "Build Wall"
    of CmdBuildBlacksmith: "Build Blacksmith"
    of CmdBuildMarket: "Build Market"
    of CmdSetRally: "Set Rally Point"
    of CmdUngarrison: "Ungarrison All"
    of CmdTrainVillager: "Train Villager"
    of CmdTrainManAtArms: "Train Man-at-Arms"
    of CmdTrainArcher: "Train Archer"
    of CmdTrainScout: "Train Scout"
    of CmdTrainKnight: "Train Knight"
    of CmdTrainMonk: "Train Monk"
    of CmdTrainBatteringRam: "Train Battering Ram"
    of CmdTrainMangonel: "Train Mangonel"
    of CmdTrainTrebuchet: "Train Trebuchet"
    of CmdTrainBoat: "Train Boat"
    of CmdTrainTradeCog: "Train Trade Cog"
    of CmdTrainGalley: "Train Galley"
    of CmdTrainFireShip: "Train Fire Ship"
    of CmdTrainFishingShip: "Train Fishing Ship"
    of CmdTrainTransportShip: "Train Transport Ship"
    of CmdTrainDemoShip: "Train Demolition Ship"
    of CmdTrainCannonGalleon: "Train Cannon Galleon"
    of CmdFormationLine: "Line Formation"
    of CmdFormationBox: "Box Formation"
    of CmdFormationStaggered: "Staggered Formation"
    of CmdFormationRangedSpread: "Ranged Spread Formation"
    # Blacksmith research.
    of CmdResearchMeleeAttack: "Forging Line"
    of CmdResearchArcherAttack: "Fletching Line"
    of CmdResearchInfantryArmor: "Infantry Armor"
    of CmdResearchCavalryArmor: "Cavalry Armor"
    of CmdResearchArcherArmor: "Archer Armor"
    # University research.
    of CmdResearchBallistics: "Ballistics"
    of CmdResearchMurderHoles: "Murder Holes"
    of CmdResearchMasonry: "Masonry"
    of CmdResearchArchitecture: "Architecture"
    of CmdResearchTreadmillCrane: "Treadmill Crane"
    of CmdResearchArrowslits: "Arrowslits"
    of CmdResearchHeatedShot: "Heated Shot"
    of CmdResearchSiegeEngineers: "Siege Engineers"
    of CmdResearchChemistry: "Chemistry"
    of CmdResearchCoinage: "Coinage"
    # Castle research.
    of CmdResearchCastleTech1: "Unique Tech I"
    of CmdResearchCastleTech2: "Unique Tech II"
    # Mill commands.
    of CmdQueueFarm: "Queue Farm Reseed"

  result.description = getCommandDescription(kind)
  result.costLines = getCommandCosts(kind)

  let trainTime = getTrainingTime(kind)
  if trainTime.len > 0:
    result.statsLines.add(trainTime)

  if hotkey.len > 0:
    result.hotkeyLine = &"Hotkey: {hotkey}"

proc startHover*(kind: TooltipKind, anchorRect: Rect, content: TooltipContent) =
  ## Start tracking a hover for potential tooltip display.
  if tooltipState.kind != kind or tooltipState.anchorRect != anchorRect:
    tooltipState = TooltipState(
      kind: kind,
      visible: false,
      content: content,
      anchorRect: anchorRect,
      hoverStartTime: nowSeconds(),
      showDelay: TooltipShowDelay
    )

proc updateTooltip*() =
  ## Update tooltip visibility based on hover duration.
  if tooltipState.kind == TooltipNone:
    return

  let elapsed = nowSeconds() - tooltipState.hoverStartTime
  if elapsed >= tooltipState.showDelay:
    tooltipState.visible = true

proc clearTooltip*() =
  ## Clear the current tooltip state.
  tooltipState = TooltipState(kind: TooltipNone)

proc isTooltipVisible*(): bool =
  ## Return true when the active tooltip should be drawn.
  tooltipState.visible

proc calculateTooltipSize(content: TooltipContent): Vec2 =
  ## Calculate the on-screen size needed for a tooltip.
  var maxWidth: float32 = 0
  var totalHeight: float32 = TooltipPadding * 2

  # Measure the title.
  if content.title.len > 0:
    let (_, titleSize) = renderTooltipLabel(
      content.title,
      TooltipTitleFontSize,
      TooltipTitleColor
    )
    maxWidth = max(maxWidth, titleSize.x.float32)
    totalHeight += TooltipLineHeight + TooltipSectionGap

  # Measure the description.
  if content.description.len > 0:
    let
      (_, descSize) = renderTooltipLabel(
        content.description,
        TooltipTextFontSize,
        TooltipTextColor
      )
      innerWidth = TooltipMaxWidth - TooltipPadding * 2
    maxWidth = max(maxWidth, min(descSize.x.float32, innerWidth))
    # Estimate line wrapping.
    let lines =
      (descSize.x.float32 / (TooltipMaxWidth - TooltipPadding * 2)).int + 1
    totalHeight += TooltipLineHeight * lines.float32 + TooltipSectionGap * 2

  # Measure the cost lines.
  for line in content.costLines:
    let (_, lineSize) = renderTooltipLabel(
      line,
      TooltipTextFontSize,
      TooltipCostColor
    )
    maxWidth = max(maxWidth, lineSize.x.float32)
    totalHeight += TooltipLineHeight

  # Measure the stats lines.
  for line in content.statsLines:
    let (_, lineSize) = renderTooltipLabel(
      line,
      TooltipTextFontSize,
      TooltipTextColor
    )
    maxWidth = max(maxWidth, lineSize.x.float32)
    totalHeight += TooltipLineHeight

  # Measure the hotkey line.
  if content.hotkeyLine.len > 0:
    let (_, hotkeySize) = renderTooltipLabel(
      content.hotkeyLine,
      TooltipTextFontSize,
      TooltipHotkeyColor
    )
    maxWidth = max(maxWidth, hotkeySize.x.float32)
    totalHeight += TooltipLineHeight + TooltipSectionGap

  result = vec2(
    min(maxWidth + TooltipPadding * 2, TooltipMaxWidth),
    totalHeight
  )

proc positionTooltip(
  anchorRect: Rect,
  tooltipSize: Vec2,
  screenSize: Vec2
): Vec2 =
  ## Position the tooltip while keeping it on screen.
  var x = anchorRect.x - tooltipSize.x - TooltipAnchorGap
  var y = anchorRect.y

  # Move to the right side if the tooltip would leave the screen.
  if x < TooltipScreenMargin:
    x = anchorRect.x + anchorRect.w + TooltipAnchorGap

  # Fall back to the left side if the right side would overflow.
  if x + tooltipSize.x > screenSize.x - TooltipScreenMargin:
    x = anchorRect.x - tooltipSize.x - TooltipAnchorGap

  # Clamp the tooltip vertically to the screen.
  if y + tooltipSize.y > screenSize.y - TooltipScreenMargin:
    y = screenSize.y - tooltipSize.y - TooltipScreenMargin
  if y < TooltipScreenMargin:
    y = TooltipScreenMargin

  result = vec2(x, y)

proc drawTooltip*(screenSize: Vec2) =
  ## Draw the current tooltip if visible.
  if not tooltipState.visible:
    return

  let content = tooltipState.content
  let size = calculateTooltipSize(content)
  let pos = positionTooltip(tooltipState.anchorRect, size, screenSize)

  # Draw the background and border.
  bxy.drawRect(
    rect = Rect(
      x: pos.x - TooltipBorderOutset,
      y: pos.y - TooltipBorderOutset,
      w: size.x + TooltipBorderExpand,
      h: size.y + TooltipBorderExpand
    ),
    color = TooltipBorderColor
  )
  bxy.drawRect(
    rect = Rect(x: pos.x, y: pos.y, w: size.x, h: size.y),
    color = TooltipBgColor
  )

  var yOffset = pos.y + TooltipPadding

  # Draw the title.
  if content.title.len > 0:
    let (titleKey, _) = renderTooltipLabel(
      content.title,
      TooltipTitleFontSize,
      TooltipTitleColor
    )
    bxy.drawImage(titleKey, vec2(pos.x + TooltipPadding, yOffset))
    yOffset += TooltipLineHeight + TooltipSectionGap

  # Draw the description.
  if content.description.len > 0:
    let (descKey, descSize) = renderTooltipLabel(
      content.description,
      TooltipTextFontSize,
      TooltipTextColor
    )
    bxy.drawImage(descKey, vec2(pos.x + TooltipPadding, yOffset))
    let lines =
      (descSize.x.float32 / (TooltipMaxWidth - TooltipPadding * 2)).int + 1
    yOffset += TooltipLineHeight * lines.float32 + TooltipSectionGap * 2

  # Draw the cost lines with a separator.
  if content.costLines.len > 0:
    bxy.drawRect(
      rect = Rect(
        x: pos.x + TooltipPadding,
        y: yOffset,
        w: size.x - TooltipPadding * 2,
        h: 1.0
      ),
      color = TooltipBorderColor
    )
    yOffset += TooltipSectionGap
    for line in content.costLines:
      let (lineKey, _) = renderTooltipLabel(
        line,
        TooltipTextFontSize,
        TooltipCostColor
      )
      bxy.drawImage(lineKey, vec2(pos.x + TooltipPadding, yOffset))
      yOffset += TooltipLineHeight

  # Draw the stats lines.
  if content.statsLines.len > 0:
    if content.costLines.len > 0:
      yOffset += TooltipSectionGap
    for line in content.statsLines:
      let (lineKey, _) = renderTooltipLabel(
        line,
        TooltipTextFontSize,
        TooltipTextColor
      )
      bxy.drawImage(lineKey, vec2(pos.x + TooltipPadding, yOffset))
      yOffset += TooltipLineHeight

  # Draw the hotkey line with a separator.
  if content.hotkeyLine.len > 0:
    yOffset += TooltipSectionGap
    bxy.drawRect(
      rect = Rect(
        x: pos.x + TooltipPadding,
        y: yOffset,
        w: size.x - TooltipPadding * 2,
        h: 1.0
      ),
      color = TooltipBorderColor
    )
    yOffset += TooltipSectionGap
    let (hotkeyKey, _) = renderTooltipLabel(
      content.hotkeyLine,
      TooltipTextFontSize,
      TooltipHotkeyColor
    )
    bxy.drawImage(hotkeyKey, vec2(pos.x + TooltipPadding, yOffset))
    yOffset += TooltipLineHeight
