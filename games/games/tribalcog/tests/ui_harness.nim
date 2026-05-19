## UI test harness for AoE2-style UI components.
##
## Provides selection helpers, hit testing, and simple state snapshots for
## UI-focused tests.

import
  agent_control, command_panel, common, environment, items, types

export agent_control.clearSelection

const
  ControlGroupCount = 10

type
  ResourceBarState* = object
    ## Snapshot of resource bar values for assertions.
    food*: int
    wood*: int
    stone*: int
    gold*: int
    popCurrent*: int
    popCap*: int
    stepNumber*: int32

  UnitInfoState* = object
    ## Snapshot of the unit info panel for assertions.
    isSingleUnit*: bool
    isSingleBuilding*: bool
    isMultiSelect*: bool
    teamId*: int
    hp*: int
    maxHp*: int
    attackDamage*: int
    stance*: AgentStance
    isIdle*: bool
    unitCount*: int

var
  testControlGroups*: array[ControlGroupCount, seq[Thing]]

proc resetSelection*() =
  ## Clear the current selection and reset the selected position.
  selection = @[]
  selectedPos = ivec2(-1, -1)

proc selectThing*(thing: Thing) =
  ## Select a single thing.
  selection = @[thing]
  if not isNil(thing) and isValidPos(thing.pos):
    selectedPos = thing.pos

proc selectThings*(things: seq[Thing]) =
  ## Select multiple things.
  selection = things
  if things.len > 0 and
    not isNil(things[0]) and
    isValidPos(things[0].pos):
      selectedPos = things[0].pos
  else:
    selectedPos = ivec2(-1, -1)

proc isSelected*(thing: Thing): bool =
  ## Return true when a thing is currently selected.
  for current in selection:
    if current == thing:
      return true
  false

proc hasCommandButton*(panelRect: IRect, kind: CommandButtonKind): bool =
  ## Return true when a command button is available in the panel.
  let buttons = buildCommandButtons(panelRect)
  for button in buttons:
    if button.kind == kind:
      return true
  false

proc simulateDragBox*(
  env: Environment,
  startWorld: Vec2,
  endWorld: Vec2,
  filterTeam: int = -1
): seq[Thing] =
  ## Return the living agents inside a drag-box selection.
  let
    minX = min(startWorld.x, endWorld.x)
    maxX = max(startWorld.x, endWorld.x)
    minY = min(startWorld.y, endWorld.y)
    maxY = max(startWorld.y, endWorld.y)

  result = @[]
  for agent in env.thingsByKind[Agent]:
    if not env.isAgentAlive(agent):
      continue
    let
      agentX = agent.pos.x.float32
      agentY = agent.pos.y.float32
    if agentX >= minX and agentX <= maxX and
      agentY >= minY and agentY <= maxY:
        if filterTeam >= 0:
          let agentTeam = getTeamId(agent)
          if agentTeam == filterTeam:
            result.add(agent)
        else:
          result.add(agent)

proc applyDragBoxSelection*(
  env: Environment,
  startWorld: Vec2,
  endWorld: Vec2,
  filterTeam: int = -1
) =
  ## Apply a drag-box selection to the global UI state.
  let selectedAgents = simulateDragBox(env, startWorld, endWorld, filterTeam)
  if selectedAgents.len > 0:
    selection = selectedAgents
    selectedPos = selectedAgents[0].pos
  else:
    selection = @[]

proc makeTestPanelRect*(width: int = 1280, height: int = 720): IRect =
  ## Return a standard test panel rectangle.
  IRect(x: 0, y: 0, w: width, h: height)

proc isInResourceBarArea*(panelRect: IRect, screenPos: Vec2): bool =
  ## Return true when a screen position is inside the resource bar.
  let barTop = panelRect.y.float32
  screenPos.y >= barTop and
    screenPos.y < barTop + ResourceBarHeight.float32

proc isInFooterArea*(panelRect: IRect, screenPos: Vec2): bool =
  ## Return true when a screen position is inside the footer.
  let footerY = panelRect.y.float32 + panelRect.h.float32 - FooterHeight.float32
  screenPos.y >= footerY and
    screenPos.y <= panelRect.y.float32 + panelRect.h.float32

proc isInMinimapArea*(panelRect: IRect, screenPos: Vec2): bool =
  ## Return true when a screen position is inside the minimap.
  let
    minimapX = panelRect.x.float32 + MinimapMargin.float32
    minimapY = panelRect.y.float32 + panelRect.h.float32 -
      FooterHeight.float32 - MinimapSize.float32 - MinimapMargin.float32
  screenPos.x >= minimapX and
    screenPos.x <= minimapX + MinimapSize.float32 and
    screenPos.y >= minimapY and
    screenPos.y <= minimapY + MinimapSize.float32

proc worldToMinimapPixel*(worldPos: IVec2, panelRect: IRect): Vec2 =
  ## Convert world coordinates to minimap pixel coordinates.
  let
    minimapX = panelRect.x.float32 + MinimapMargin.float32
    minimapY = panelRect.y.float32 + panelRect.h.float32 -
      FooterHeight.float32 - MinimapSize.float32 - MinimapMargin.float32
    scaleX = MinimapSize.float32 / MapWidth.float32
    scaleY = MinimapSize.float32 / MapHeight.float32
  vec2(
    minimapX + worldPos.x.float32 * scaleX,
    minimapY + worldPos.y.float32 * scaleY
  )

proc minimapPixelToWorld*(minimapPos: Vec2, panelRect: IRect): IVec2 =
  ## Convert minimap pixel coordinates to world coordinates.
  let
    minimapX = panelRect.x.float32 + MinimapMargin.float32
    minimapY = panelRect.y.float32 + panelRect.h.float32 -
      FooterHeight.float32 - MinimapSize.float32 - MinimapMargin.float32
    scaleX = MinimapSize.float32 / MapWidth.float32
    scaleY = MinimapSize.float32 / MapHeight.float32
    worldX = int((minimapPos.x - minimapX) / scaleX)
    worldY = int((minimapPos.y - minimapY) / scaleY)
  ivec2(
    clamp(worldX, 0, MapWidth - 1),
    clamp(worldY, 0, MapHeight - 1)
  )

proc getResourceBarState*(env: Environment, teamId: int): ResourceBarState =
  ## Return the values that the resource bar would display.
  let validTeamId =
    if teamId >= 0 and teamId < MapRoomObjectsTeams:
      teamId
    else:
      0

  result.food = env.teamStockpiles[validTeamId].counts[ResourceFood]
  result.wood = env.teamStockpiles[validTeamId].counts[ResourceWood]
  result.stone = env.teamStockpiles[validTeamId].counts[ResourceStone]
  result.gold = env.teamStockpiles[validTeamId].counts[ResourceGold]
  result.stepNumber = env.currentStep.int32

  # Count the current population for this team.
  result.popCurrent = 0
  for agent in env.agents:
    if isAgentAlive(env, agent) and getTeamId(agent) == validTeamId:
      inc result.popCurrent

  # Calculate the population cap from houses and town centers.
  result.popCap = 0
  for house in env.thingsByKind[House]:
    if house.teamId == validTeamId:
      result.popCap += HousePopCap
  for townCenter in env.thingsByKind[TownCenter]:
    if townCenter.teamId == validTeamId:
      result.popCap += TownCenterPopCap
  result.popCap = min(result.popCap, MapAgentsPerTeam)

proc getUnitInfoState*(): UnitInfoState =
  ## Return the values that the unit info panel would display.
  if selection.len == 0:
    return UnitInfoState()

  if selection.len == 1:
    let thing = selection[0]
    if thing.kind == Agent:
      result.isSingleUnit = true
      result.teamId = getTeamId(thing)
      result.hp = thing.hp
      result.maxHp = thing.maxHp
      result.attackDamage = thing.attackDamage
      result.stance = thing.stance
      result.isIdle = thing.isIdle
      result.unitCount = 1
    elif isBuildingKind(thing.kind):
      result.isSingleBuilding = true
      result.teamId = thing.teamId
      result.hp = thing.hp
      result.maxHp = thing.maxHp
      result.unitCount = 1
  else:
    result.isMultiSelect = true
    result.unitCount = selection.len

proc assignControlGroup*(groupIndex: int) =
  ## Assign the current selection to a control group.
  if groupIndex >= 0 and groupIndex < ControlGroupCount:
    testControlGroups[groupIndex] = selection

proc recallControlGroup*(groupIndex: int) =
  ## Recall a control group into the current selection.
  if groupIndex >= 0 and groupIndex < ControlGroupCount:
    selection = testControlGroups[groupIndex]
    if selection.len > 0 and
      not isNil(selection[0]) and
      isValidPos(selection[0].pos):
        selectedPos = selection[0].pos
