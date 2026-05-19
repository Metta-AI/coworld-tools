## Render and handle the context-sensitive command panel.
## The panel exposes unit, villager, building, and multi-select actions.

import
  boxy, pixie, vmath, windy,
  common, environment, tooltips, semantic, renderer_core, label_cache

type
  CommandButton* = object
    kind*: CommandButtonKind
    rect*: Rect
    label*: string
    hotkey*: string
    enabled*: bool

const
  CommandPanelBgColor = UiBg
  CommandPanelHeaderColor = UiBgHeader
  CommandButtonBgColor = UiBgButton
  CommandButtonHoverColor = UiBgButtonHover
  CommandButtonDisabledColor = UiBgButtonDisabled
  ResearchCommandKinds = {
    CmdResearchMeleeAttack, CmdResearchArcherAttack,
    CmdResearchInfantryArmor, CmdResearchCavalryArmor,
    CmdResearchArcherArmor, CmdResearchBallistics,
    CmdResearchMurderHoles, CmdResearchMasonry,
    CmdResearchArchitecture, CmdResearchTreadmillCrane,
    CmdResearchArrowslits, CmdResearchHeatedShot,
    CmdResearchSiegeEngineers, CmdResearchChemistry,
    CmdResearchCoinage, CmdResearchCastleTech1,
    CmdResearchCastleTech2
  }

let
  commandLabelStyle = labelStyle(
    CommandLabelFontPath,
    CommandLabelFontSize,
    CommandLabelPadding,
    0.0
  )
  commandHotkeyStyle = labelStyle(
    CommandLabelFontPath,
    CommandHotkeyFontSize,
    CommandLabelPadding,
    0.0
  )

var
  buildMenuOpen*: bool = false

proc isPointInRect(rect: Rect, point: Vec2): bool =
  ## Return whether the point lies inside the rectangle.
  point.x >= rect.x and point.x <= rect.x + rect.w and
    point.y >= rect.y and point.y <= rect.y + rect.h

proc getButtonLabel(kind: CommandButtonKind): string =
  ## Return the display label for a command button.
  case kind
  of CmdNone: ""
  of CmdMove: "Move"
  of CmdAttack: "Attack"
  of CmdStop: "Stop"
  of CmdPatrol: "Patrol"
  of CmdStance: "Stance"
  of CmdHoldPosition: "Hold"
  of CmdBuild: "Build"
  of CmdGather: "Gather"
  of CmdBuildBack: "Back"
  of CmdBuildHouse: "House"
  of CmdBuildMill: "Mill"
  of CmdBuildLumberCamp: "Lumber"
  of CmdBuildMiningCamp: "Mining"
  of CmdBuildBarracks: "Barracks"
  of CmdBuildArcheryRange: "Archery"
  of CmdBuildStable: "Stable"
  of CmdBuildWall: "Wall"
  of CmdBuildBlacksmith: "Smith"
  of CmdBuildMarket: "Market"
  of CmdSetRally: "Rally"
  of CmdUngarrison: "Ungarr"
  of CmdTrainVillager: "Villgr"
  of CmdTrainManAtArms: "M@Arms"
  of CmdTrainArcher: "Archer"
  of CmdTrainScout: "Scout"
  of CmdTrainKnight: "Knight"
  of CmdTrainMonk: "Monk"
  of CmdTrainBatteringRam: "Ram"
  of CmdTrainMangonel: "Mangon"
  of CmdTrainTrebuchet: "Trebuc"
  of CmdTrainBoat: "Boat"
  of CmdTrainTradeCog: "T.Cog"
  of CmdTrainGalley: "Galley"
  of CmdTrainFireShip: "F.Ship"
  of CmdTrainFishingShip: "Fisher"
  of CmdTrainTransportShip: "Transp"
  of CmdTrainDemoShip: "Demo"
  of CmdTrainCannonGalleon: "C.Galln"
  of CmdFormationLine: "Line"
  of CmdFormationBox: "Box"
  of CmdFormationStaggered: "Stagger"
  of CmdFormationRangedSpread: "Spread"
  of CmdResearchMeleeAttack: "MeleeAtk"
  of CmdResearchArcherAttack: "RangeAtk"
  of CmdResearchInfantryArmor: "InfArmor"
  of CmdResearchCavalryArmor: "CavArmor"
  of CmdResearchArcherArmor: "ArcArmor"
  of CmdResearchBallistics: "Ballist"
  of CmdResearchMurderHoles: "MrdHole"
  of CmdResearchMasonry: "Masonry"
  of CmdResearchArchitecture: "Archit"
  of CmdResearchTreadmillCrane: "Treadml"
  of CmdResearchArrowslits: "Arrowsl"
  of CmdResearchHeatedShot: "HeatSht"
  of CmdResearchSiegeEngineers: "SiegeEn"
  of CmdResearchChemistry: "Chemist"
  of CmdResearchCoinage: "Coinage"
  of CmdResearchCastleTech1: "CstlT1"
  of CmdResearchCastleTech2: "CstlT2"
  of CmdQueueFarm: "QFarm"

proc getButtonHotkey*(kind: CommandButtonKind): string =
  ## Return the hotkey label for a command button.
  case kind
  of CmdNone: ""
  of CmdMove: "M"
  of CmdAttack: "A"
  of CmdStop: "S"
  of CmdPatrol: "P"
  of CmdStance: "D"
  of CmdHoldPosition: "H"
  of CmdBuild: "B"
  of CmdGather: "G"
  of CmdBuildBack: "Esc"
  of CmdBuildHouse: "Q"
  of CmdBuildMill: "W"
  of CmdBuildLumberCamp: "E"
  of CmdBuildMiningCamp: "R"
  of CmdBuildBarracks: "A"
  of CmdBuildArcheryRange: "S"
  of CmdBuildStable: "D"
  of CmdBuildWall: "F"
  of CmdBuildBlacksmith: "Z"
  of CmdBuildMarket: "X"
  of CmdSetRally: "G"
  of CmdUngarrison: "V"
  of CmdTrainVillager: "Q"
  of CmdTrainManAtArms: "W"
  of CmdTrainArcher: "E"
  of CmdTrainScout: "R"
  of CmdTrainKnight: "T"
  of CmdTrainMonk: "Y"
  of CmdTrainBatteringRam: "Q"
  of CmdTrainMangonel: "W"
  of CmdTrainTrebuchet: "E"
  of CmdTrainBoat: "Q"
  of CmdTrainTradeCog: "W"
  of CmdTrainGalley: "E"
  of CmdTrainFireShip: "R"
  of CmdTrainFishingShip: "A"
  of CmdTrainTransportShip: "S"
  of CmdTrainDemoShip: "D"
  of CmdTrainCannonGalleon: "F"
  of CmdFormationLine: "1"
  of CmdFormationBox: "2"
  of CmdFormationStaggered: "3"
  of CmdFormationRangedSpread: "4"
  of CmdResearchMeleeAttack: "Q"
  of CmdResearchArcherAttack: "W"
  of CmdResearchInfantryArmor: "E"
  of CmdResearchCavalryArmor: "R"
  of CmdResearchArcherArmor: "T"
  of CmdResearchBallistics: "Q"
  of CmdResearchMurderHoles: "W"
  of CmdResearchMasonry: "E"
  of CmdResearchArchitecture: "R"
  of CmdResearchTreadmillCrane: "T"
  of CmdResearchArrowslits: "A"
  of CmdResearchHeatedShot: "S"
  of CmdResearchSiegeEngineers: "D"
  of CmdResearchChemistry: "F"
  of CmdResearchCoinage: "G"
  of CmdResearchCastleTech1: "Q"
  of CmdResearchCastleTech2: "W"
  of CmdQueueFarm: "Q"

proc commandKindToBuildingKind*(cmd: CommandButtonKind): ThingKind =
  ## Convert a build command to the corresponding ThingKind.
  case cmd
  of CmdBuildHouse: House
  of CmdBuildMill: Mill
  of CmdBuildLumberCamp: LumberCamp
  of CmdBuildMiningCamp: MiningCamp
  of CmdBuildBarracks: Barracks
  of CmdBuildArcheryRange: ArcheryRange
  of CmdBuildStable: Stable
  of CmdBuildWall: Wall
  of CmdBuildBlacksmith: Blacksmith
  of CmdBuildMarket: Market
  else: Wall

proc buildBuildingCommands(thing: Thing): seq[CommandButtonKind] =
  ## Commands available for selected building.
  result = @[CmdSetRally]

  if thing.kind in {TownCenter, Castle, GuardTower, House}:
    result.add(CmdUngarrison)

  case thing.kind
  of TownCenter:
    result.add(CmdTrainVillager)
  of Barracks:
    result.add(CmdTrainManAtArms)
  of ArcheryRange:
    result.add(CmdTrainArcher)
  of Stable:
    result.add(CmdTrainScout)
    result.add(CmdTrainKnight)
  of Monastery:
    result.add(CmdTrainMonk)
  of SiegeWorkshop:
    result.add(CmdTrainBatteringRam)
  of MangonelWorkshop:
    result.add(CmdTrainMangonel)
  of TrebuchetWorkshop:
    result.add(CmdTrainTrebuchet)
  of Dock:
    result.add(CmdTrainBoat)
    result.add(CmdTrainTradeCog)
    result.add(CmdTrainGalley)
    result.add(CmdTrainFireShip)
    result.add(CmdTrainFishingShip)
    result.add(CmdTrainTransportShip)
    result.add(CmdTrainDemoShip)
    result.add(CmdTrainCannonGalleon)
  of Blacksmith:
    result.add(CmdResearchMeleeAttack)
    result.add(CmdResearchArcherAttack)
    result.add(CmdResearchInfantryArmor)
    result.add(CmdResearchCavalryArmor)
    result.add(CmdResearchArcherArmor)
  of University:
    result.add(CmdResearchBallistics)
    result.add(CmdResearchMurderHoles)
    result.add(CmdResearchMasonry)
    result.add(CmdResearchArchitecture)
    result.add(CmdResearchTreadmillCrane)
    result.add(CmdResearchArrowslits)
    result.add(CmdResearchHeatedShot)
    result.add(CmdResearchSiegeEngineers)
    result.add(CmdResearchChemistry)
    result.add(CmdResearchCoinage)
  of Castle:
    result.add(CmdResearchCastleTech1)
    result.add(CmdResearchCastleTech2)
  of Mill:
    result.add(CmdQueueFarm)
  else:
    discard

proc buildMultiSelectCommands(): seq[CommandButtonKind] =
  ## Commands for multi-selection (common commands only).
  @[CmdMove, CmdAttack, CmdStop, CmdHoldPosition, CmdPatrol]

proc isResearchButtonEnabled*(kind: CommandButtonKind, building: Thing): bool =
  ## Check if a research button should be enabled (not yet researched).
  let teamId = building.teamId
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return false

  case kind
  of CmdResearchMeleeAttack:
    env.teamBlacksmithUpgrades[teamId].levels[UpgradeMeleeAttack] <
      BlacksmithUpgradeMaxLevel
  of CmdResearchArcherAttack:
    env.teamBlacksmithUpgrades[teamId].levels[UpgradeArcherAttack] <
      BlacksmithUpgradeMaxLevel
  of CmdResearchInfantryArmor:
    env.teamBlacksmithUpgrades[teamId].levels[UpgradeInfantryArmor] <
      BlacksmithUpgradeMaxLevel
  of CmdResearchCavalryArmor:
    env.teamBlacksmithUpgrades[teamId].levels[UpgradeCavalryArmor] <
      BlacksmithUpgradeMaxLevel
  of CmdResearchArcherArmor:
    env.teamBlacksmithUpgrades[teamId].levels[UpgradeArcherArmor] <
      BlacksmithUpgradeMaxLevel
  of CmdResearchBallistics:
    not env.teamUniversityTechs[teamId].researched[TechBallistics]
  of CmdResearchMurderHoles:
    not env.teamUniversityTechs[teamId].researched[TechMurderHoles]
  of CmdResearchMasonry:
    not env.teamUniversityTechs[teamId].researched[TechMasonry]
  of CmdResearchArchitecture:
    not env.teamUniversityTechs[teamId].researched[TechArchitecture]
  of CmdResearchTreadmillCrane:
    not env.teamUniversityTechs[teamId].researched[TechTreadmillCrane]
  of CmdResearchArrowslits:
    not env.teamUniversityTechs[teamId].researched[TechArrowslits]
  of CmdResearchHeatedShot:
    not env.teamUniversityTechs[teamId].researched[TechHeatedShot]
  of CmdResearchSiegeEngineers:
    not env.teamUniversityTechs[teamId].researched[TechSiegeEngineers]
  of CmdResearchChemistry:
    not env.teamUniversityTechs[teamId].researched[TechChemistry]
  of CmdResearchCoinage:
    not env.teamUniversityTechs[teamId].researched[TechCoinage]
  of CmdResearchCastleTech1:
    let (castleAge, _) = castleTechsForTeam(teamId)
    not env.teamCastleTechs[teamId].researched[castleAge]
  of CmdResearchCastleTech2:
    let (castleAge, imperialAge) = castleTechsForTeam(teamId)
    env.teamCastleTechs[teamId].researched[castleAge] and
      not env.teamCastleTechs[teamId].researched[imperialAge]
  else:
    true

proc commandPanelRect*(panelRect: IRect): Rect =
  ## Calculate the command panel rectangle (right side, above footer).
  ## Uses the layout system if available, falls back to calculated position.
  if uiLayout.commandPanelArea != nil and uiLayout.commandPanelArea.rect.w > 0:
    return uiLayout.commandPanelArea.rect

  let x = panelRect.x.float32 + panelRect.w.float32 -
    CommandPanelWidth.float32 - CommandPanelMargin.float32
  let y = panelRect.y.float32 + panelRect.h.float32 -
    FooterHeight.float32 - MinimapSize.float32 -
    CommandPanelMargin.float32 * 2
  let h = MinimapSize.float32
  Rect(x: x, y: y, w: CommandPanelWidth.float32, h: h)

proc isInCommandPanel*(panelRect: IRect, mousePosPx: Vec2): bool =
  ## Check if mouse position is inside the command panel.
  isPointInRect(commandPanelRect(panelRect), mousePosPx)

proc buildCommandButtons*(panelRect: IRect): seq[CommandButton] =
  ## Build the list of command buttons based on current selection.
  let cpRect = commandPanelRect(panelRect)
  var commandKinds: seq[CommandButtonKind] = @[]

  if selection.len == 0:
    return @[]
  elif selection.len == 1:
    let thing = selection[0]
    if thing.kind == Agent:
      if thing.unitClass == UnitVillager:
        commandKinds =
          if buildMenuOpen:
            @[CmdBuildBack, CmdBuildHouse, CmdBuildMill, CmdBuildLumberCamp,
              CmdBuildMiningCamp, CmdBuildBarracks, CmdBuildArcheryRange,
              CmdBuildStable, CmdBuildWall, CmdBuildBlacksmith, CmdBuildMarket]
          else:
            @[CmdMove, CmdAttack, CmdStop, CmdBuild, CmdGather]
      else:
        commandKinds =
          @[CmdMove, CmdAttack, CmdStop, CmdHoldPosition, CmdPatrol, CmdStance]
    elif isBuildingKind(thing.kind):
      commandKinds = buildBuildingCommands(thing)
    else:
      return @[]
  else:
    var allAgents = true
    for thing in selection:
      if thing.kind != Agent:
        allAgents = false
        break
    if allAgents:
      commandKinds = buildMultiSelectCommands()
    else:
      return @[]

  let startX = cpRect.x + CommandPanelPadding.float32
  let startY = cpRect.y + CommandPanelHeaderHeight +
    CommandPanelPadding.float32

  let selectedBuilding =
    if selection.len == 1 and isBuildingKind(selection[0].kind):
      selection[0]
    else:
      nil

  for i, kind in commandKinds:
    let
      col = i mod CommandButtonCols
      row = i div CommandButtonCols
      x = startX + col.float32 *
        (CommandButtonSize.float32 + CommandButtonGap.float32)
      y = startY + row.float32 *
        (CommandButtonSize.float32 + CommandButtonGap.float32)
      buttonEnabled =
        if not isNil(selectedBuilding):
          isResearchButtonEnabled(kind, selectedBuilding)
        else:
          true

    result.add(
      CommandButton(
        kind: kind,
        rect: Rect(
          x: x,
          y: y,
          w: CommandButtonSize.float32,
          h: CommandButtonSize.float32
        ),
        label: getButtonLabel(kind),
        hotkey: getButtonHotkey(kind),
        enabled: buttonEnabled
      )
    )

proc ensureCommandLabelColored(
  text: string,
  style: LabelStyle,
  textColor: Color
): (string, IVec2) =
  ## Return the cached image key and size for colored command text.
  let coloredStyle = labelStyle(
    style.fontPath,
    style.fontSize,
    style.padding,
    0.0,
    textColor
  )
  let cached = ensureLabel("cmd_panel", text, coloredStyle)
  (cached.imageKey, cached.size)

proc drawCommandPanel*(panelRect: IRect, mousePosPx: Vec2) =
  ## Draw the command panel with context-sensitive buttons.
  if selection.len == 0:
    return

  let cpRect = commandPanelRect(panelRect)

  pushSemanticContext("CommandPanel")
  capturePanel(
    "CommandPanel",
    vec2(cpRect.x, cpRect.y),
    vec2(cpRect.w, cpRect.h)
  )

  bxy.drawRect(
    rect = Rect(
      x: cpRect.x - CommandPanelBorderOffset,
      y: cpRect.y - CommandPanelBorderOffset,
      w: cpRect.w + CommandPanelBorderExpand,
      h: cpRect.h + CommandPanelBorderExpand
    ),
    color = UiBorder
  )
  bxy.drawRect(
    rect = Rect(x: cpRect.x, y: cpRect.y, w: cpRect.w, h: cpRect.h),
    color = CommandPanelBgColor
  )
  bxy.drawRect(
    rect = Rect(
      x: cpRect.x,
      y: cpRect.y,
      w: cpRect.w,
      h: CommandPanelHeaderHeight
    ),
    color = CommandPanelHeaderColor
  )
  bxy.drawRect(
    rect = Rect(
      x: cpRect.x,
      y: cpRect.y + CommandPanelHeaderHeight,
      w: cpRect.w,
      h: 1.0
    ),
    color = UiBorderBright
  )

  let headerText =
    if selection.len == 1:
      if selection[0].kind == Agent:
        "Commands"
      elif isBuildingKind(selection[0].kind):
        "Production"
      else:
        "Commands"
    else:
      "Commands (" & $selection.len & ")"

  let
    (headerKey, headerSize) = ensureCommandLabelColored(
      headerText,
      commandLabelStyle,
      UiFgBright
    )
    headerX = cpRect.x + CommandPanelHeaderPadX
    headerY =
      cpRect.y +
      (CommandPanelHeaderHeight - headerSize.y.float32) * 0.5
  drawUiImageScaled(
    headerKey,
    vec2(headerX, headerY),
    vec2(headerSize.x.float32, headerSize.y.float32)
  )
  captureLabel(
    headerText,
    vec2(headerX, headerY),
    vec2(headerSize.x.float32, headerSize.y.float32)
  )

  let buttons = buildCommandButtons(panelRect)
  var anyButtonHovered = false

  for button in buttons:
    let hovered = isPointInRect(button.rect, mousePosPx)

    if hovered and button.enabled:
      anyButtonHovered = true
      let tooltipContent = buildCommandTooltip(button.kind, button.hotkey)
      startHover(TooltipCommand, button.rect, tooltipContent)

    let bgColor =
      if not button.enabled:
        CommandButtonDisabledColor
      elif hovered:
        CommandButtonHoverColor
      else:
        CommandButtonBgColor
    bxy.drawRect(
      rect = Rect(
        x: button.rect.x,
        y: button.rect.y,
        w: button.rect.w,
        h: button.rect.h
      ),
      color = bgColor
    )

    let borderColor = if hovered: UiBorderBright else: UiBorder
    let bw = CommandButtonBorderW
    bxy.drawRect(
      rect = Rect(
        x: button.rect.x,
        y: button.rect.y,
        w: button.rect.w,
        h: bw
      ),
      color = borderColor
    )
    bxy.drawRect(
      rect = Rect(
        x: button.rect.x,
        y: button.rect.y + button.rect.h - bw,
        w: button.rect.w,
        h: bw
      ),
      color = borderColor
    )
    bxy.drawRect(
      rect = Rect(
        x: button.rect.x,
        y: button.rect.y,
        w: bw,
        h: button.rect.h
      ),
      color = borderColor
    )
    bxy.drawRect(
      rect = Rect(
        x: button.rect.x + button.rect.w - bw,
        y: button.rect.y,
        w: bw,
        h: button.rect.h
      ),
      color = borderColor
    )

    let labelTextColor = if button.enabled: UiFgText else: UiFgDim
    let
      (lblKey, lblSize) = ensureCommandLabelColored(
        button.label,
        commandLabelStyle,
        labelTextColor
      )
      labelX = button.rect.x + (button.rect.w - lblSize.x.float32) * 0.5
      labelY = button.rect.y + (button.rect.h - lblSize.y.float32) * 0.5
    drawUiImageScaled(
      lblKey,
      vec2(labelX, labelY),
      vec2(lblSize.x.float32, lblSize.y.float32)
    )

    captureButton(
      button.label,
      vec2(button.rect.x, button.rect.y),
      vec2(button.rect.w, button.rect.h)
    )

    if button.hotkey.len > 0:
      let
        (hkKey, hkSize) = ensureCommandLabelColored(
          button.hotkey,
          commandHotkeyStyle,
          UiFgMuted
        )
        hotkeyX =
          button.rect.x +
          button.rect.w -
          hkSize.x.float32 -
          CommandButtonHotkeyInset
        hotkeyY = button.rect.y + CommandButtonHotkeyInset
      drawUiImageScaled(
        hkKey,
        vec2(hotkeyX, hotkeyY),
        vec2(hkSize.x.float32, hkSize.y.float32)
      )

    if not button.enabled and button.kind in ResearchCommandKinds:
      let
        (okKey, okSize) = ensureCommandLabelColored(
          "OK",
          commandHotkeyStyle,
          UiSuccess
        )
        checkX = button.rect.x + CommandButtonHotkeyInset
        checkY = button.rect.y + CommandButtonHotkeyInset
      drawUiImageScaled(
        okKey,
        vec2(checkX, checkY),
        vec2(okSize.x.float32, okSize.y.float32)
      )

  if not anyButtonHovered:
    clearTooltip()

  popSemanticContext()

proc handleCommandPanelClick*(panelRect: IRect, mousePosPx: Vec2): CommandButtonKind =
  ## Handle a click on the command panel, returning the clicked button kind.
  if not isPointInRect(commandPanelRect(panelRect), mousePosPx):
    return CmdNone

  let buttons = buildCommandButtons(panelRect)
  for button in buttons:
    if isPointInRect(button.rect, mousePosPx):
      if button.enabled:
        return button.kind

  return CmdNone
