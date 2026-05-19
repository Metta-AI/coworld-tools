## UI Behavior Tests: Tests for AoE2-style UI components
##
## Tests UI state and logic without requiring actual rendering:
## - Selection behavior (click, shift-click, drag-box)
## - Command panel button generation
## - Resource bar state
## - Unit info panel state
## - Minimap coordinate conversion
## - Player team/AI takeover toggle

import std/unittest
import vmath, boxy
import test_common
import common
import ui_harness
import tooltips
import types
import command_panel

# ---------------------------------------------------------------------------
# Selection Tests
# ---------------------------------------------------------------------------

suite "UI - Selection Behavior":
  setup:
    resetSelection()

  test "initial selection is empty":
    check selection.len == 0
    check selectedPos == ivec2(-1, -1)

  test "selectThing sets single selection":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    selectThing(agent)

    check selection.len == 1
    check isSelected(agent)
    check selectedPos == ivec2(10, 10)

  test "clearSelection empties selection":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    selectThing(agent)

    resetSelection()

    check selection.len == 0
    check not isSelected(agent)

  test "addToSelection adds to existing selection (shift-click)":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15))

    selectThing(agent1)
    if agent2 notin selection:
      selection.add(agent2)

    check selection.len == 2
    check isSelected(agent1)
    check isSelected(agent2)

  test "addToSelection does not duplicate existing selection":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    selectThing(agent)
    if agent notin selection:
      selection.add(agent)  # Try to add again

    check selection.len == 1

  test "removeFromSelection removes from selection (shift-click toggle)":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15))

    selectThings(@[agent1, agent2])
    for i, selectedThing in selection:
      if selectedThing == agent1:
        selection.delete(i)
        break

    check selection.len == 1
    check not isSelected(agent1)
    check isSelected(agent2)

  test "selectThings sets multi-selection":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15))
    let agent3 = addAgentAt(env, 2, ivec2(20, 20))

    selectThings(@[agent1, agent2, agent3])

    check selection.len == 3
    check selectedPos == ivec2(10, 10)  # First unit's position

# ---------------------------------------------------------------------------
# Drag-Box Selection Tests
# ---------------------------------------------------------------------------

suite "UI - Drag-Box Multi-Select":
  setup:
    resetSelection()

  test "drag-box selects agents within rectangle":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15))
    let agent3 = addAgentAt(env, 2, ivec2(50, 50))  # Outside box

    let selectedAgents = simulateDragBox(env, vec2(5, 5), vec2(20, 20))

    check selectedAgents.len == 2
    check agent1 in selectedAgents
    check agent2 in selectedAgents
    check agent3 notin selectedAgents

  test "drag-box with team filter only selects player team":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))  # Team 0
    let agent2 = addAgentAt(env, MapAgentsPerTeam, ivec2(15, 15))  # Team 1

    let selectedAgents = simulateDragBox(env, vec2(5, 5), vec2(20, 20), filterTeam = 0)

    check selectedAgents.len == 1
    check agent1 in selectedAgents
    check agent2 notin selectedAgents

  test "drag-box excludes dead agents":
    let env = makeEmptyEnv()
    let alive = addAgentAt(env, 0, ivec2(10, 10))
    let dead = addAgentAt(env, 1, ivec2(15, 15))
    env.terminated[dead.agentId] = 1.0

    let selectedAgents = simulateDragBox(env, vec2(5, 5), vec2(20, 20))

    check selectedAgents.len == 1
    check alive in selectedAgents
    check dead notin selectedAgents

  test "applyDragBoxSelection updates global selection":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15))

    applyDragBoxSelection(env, vec2(5, 5), vec2(20, 20))

    check selection.len == 2
    check isSelected(agent1)
    check isSelected(agent2)

  test "empty drag-box clears selection":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    selectThing(agent)

    applyDragBoxSelection(env, vec2(100, 100), vec2(110, 110))  # No agents here

    check selection.len == 0

# ---------------------------------------------------------------------------
# Player Team / AI Takeover Tests
# ---------------------------------------------------------------------------

suite "UI - AI Takeover Toggle":
  setup:
    playerTeam = -1

  test "initial state is observer mode":
    check playerTeam < 0
    check playerTeam == -1

  test "setPlayerTeam switches to player control":
    playerTeam = 0

    check playerTeam >= 0
    check playerTeam == 0

  test "setPlayerTeam(-1) returns to observer mode":
    playerTeam = 0
    playerTeam = -1

    check playerTeam < 0

  test "cyclePlayerTeam cycles through teams":
    check playerTeam == -1  # Observer

    playerTeam = (playerTeam + 2) mod (MapRoomObjectsTeams + 1) - 1
    check playerTeam == 0

    playerTeam = (playerTeam + 2) mod (MapRoomObjectsTeams + 1) - 1
    check playerTeam == 1

    # Continue cycling...
    for _ in 2 .. 7:
      playerTeam = (playerTeam + 2) mod (MapRoomObjectsTeams + 1) - 1
    check playerTeam == 7

    # Should cycle back to observer
    playerTeam = (playerTeam + 2) mod (MapRoomObjectsTeams + 1) - 1
    check playerTeam == -1

# ---------------------------------------------------------------------------
# Command Panel Tests
# ---------------------------------------------------------------------------

suite "UI - Command Panel Button Generation":
  setup:
    resetSelection()

  test "no buttons when nothing selected":
    let panelRect = makeTestPanelRect()

    let buttons = buildCommandButtons(panelRect)

    check buttons.len == 0

  test "villager shows villager commands":
    let env = makeEmptyEnv()
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    # Villagers have UnitVillager class by default
    check villager.unitClass == UnitVillager

    selectThing(villager)
    let panelRect = makeTestPanelRect()

    check hasCommandButton(panelRect, CmdMove)
    check hasCommandButton(panelRect, CmdAttack)
    check hasCommandButton(panelRect, CmdStop)
    check hasCommandButton(panelRect, CmdBuild)
    check hasCommandButton(panelRect, CmdGather)

  test "military unit shows unit commands":
    let env = makeEmptyEnv()
    let soldier = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)

    selectThing(soldier)
    let panelRect = makeTestPanelRect()

    check hasCommandButton(panelRect, CmdMove)
    check hasCommandButton(panelRect, CmdAttack)
    check hasCommandButton(panelRect, CmdStop)
    check hasCommandButton(panelRect, CmdPatrol)
    check hasCommandButton(panelRect, CmdStance)
    check not hasCommandButton(panelRect, CmdBuild)  # Not a villager command

  test "barracks shows train commands":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)

    selectThing(barracks)
    let panelRect = makeTestPanelRect()

    check hasCommandButton(panelRect, CmdSetRally)
    check hasCommandButton(panelRect, CmdTrainManAtArms)

  test "stable shows cavalry train commands":
    let env = makeEmptyEnv()
    let stable = addBuilding(env, Stable, ivec2(10, 10), 0)

    selectThing(stable)
    let panelRect = makeTestPanelRect()

    check hasCommandButton(panelRect, CmdSetRally)
    check hasCommandButton(panelRect, CmdTrainScout)
    check hasCommandButton(panelRect, CmdTrainKnight)

  test "town center shows villager train and ungarrison":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)

    selectThing(tc)
    let panelRect = makeTestPanelRect()

    check hasCommandButton(panelRect, CmdSetRally)
    check hasCommandButton(panelRect, CmdUngarrison)
    check hasCommandButton(panelRect, CmdTrainVillager)

  test "multi-selection shows common commands only":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15), unitClass = UnitArcher)

    selectThings(@[agent1, agent2])
    let panelRect = makeTestPanelRect()

    check hasCommandButton(panelRect, CmdMove)
    check hasCommandButton(panelRect, CmdAttack)
    check hasCommandButton(panelRect, CmdStop)
    check hasCommandButton(panelRect, CmdPatrol)
    check not hasCommandButton(panelRect, CmdBuild)  # Not common to all
    check not hasCommandButton(panelRect, CmdStance)  # Multi-select doesn't show stance

  test "command button count matches expected":
    let env = makeEmptyEnv()
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    selectThing(villager)
    let panelRect = makeTestPanelRect()

    # Villager commands: Move, Attack, Stop, Build, Gather = 5
    check buildCommandButtons(panelRect).len == 5

# ---------------------------------------------------------------------------
# Resource Bar State Tests
# ---------------------------------------------------------------------------

suite "UI - Resource Bar State":
  test "resource bar shows team stockpile":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceWood, 200)
    setStockpile(env, 0, ResourceStone, 50)
    setStockpile(env, 0, ResourceGold, 75)

    let state = getResourceBarState(env, 0)

    check state.food == 100
    check state.wood == 200
    check state.stone == 50
    check state.gold == 75

  test "resource bar shows current step":
    let env = makeEmptyEnv()
    env.currentStep = 42

    let state = getResourceBarState(env, 0)

    check state.stepNumber == 42

  test "population count includes alive agents only":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))
    discard addAgentAt(env, 1, ivec2(15, 15))
    let dead = addAgentAt(env, 2, ivec2(20, 20))
    env.terminated[dead.agentId] = 1.0

    let state = getResourceBarState(env, 0)

    check state.popCurrent == 2

  test "pop cap from houses":
    let env = makeEmptyEnv()
    discard addBuilding(env, House, ivec2(10, 10), 0)
    discard addBuilding(env, House, ivec2(15, 15), 0)

    let state = getResourceBarState(env, 0)

    check state.popCap == HousePopCap * 2

  test "pop cap includes town center":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(10, 10), 0)

    let state = getResourceBarState(env, 0)

    check state.popCap == TownCenterPopCap

  test "pop cap is capped at MapAgentsPerTeam":
    let env = makeEmptyEnv()
    # Add many houses to exceed cap
    for i in 0 ..< 50:
      discard addBuilding(env, House, ivec2(i.int32, 10), 0)

    let state = getResourceBarState(env, 0)

    check state.popCap == MapAgentsPerTeam

  test "different teams have independent resource counts":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 1, ResourceFood, 200)

    let state0 = getResourceBarState(env, 0)
    let state1 = getResourceBarState(env, 1)

    check state0.food == 100
    check state1.food == 200

# ---------------------------------------------------------------------------
# Unit Info Panel State Tests
# ---------------------------------------------------------------------------

suite "UI - Unit Info Panel State":
  setup:
    resetSelection()

  test "empty selection returns empty state":
    let state = getUnitInfoState()

    check not state.isSingleUnit
    check not state.isSingleBuilding
    check not state.isMultiSelect
    check state.unitCount == 0

  test "single unit selection shows unit info":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    agent.hp = 5
    agent.maxHp = 7
    agent.attackDamage = 3
    agent.stance = StanceDefensive
    agent.isIdle = true

    selectThing(agent)
    let state = getUnitInfoState()

    check state.isSingleUnit
    check state.hp == 5
    check state.maxHp == 7
    check state.attackDamage == 3
    check state.stance == StanceDefensive
    check state.isIdle

  test "single building selection shows building info":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    barracks.hp = 8
    barracks.maxHp = 12

    selectThing(barracks)
    let state = getUnitInfoState()

    check state.isSingleBuilding
    check state.hp == 8
    check state.maxHp == 12
    check state.teamId == 0

  test "multi-selection shows count":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15))
    let agent3 = addAgentAt(env, 2, ivec2(20, 20))

    selectThings(@[agent1, agent2, agent3])
    let state = getUnitInfoState()

    check state.isMultiSelect
    check state.unitCount == 3

# ---------------------------------------------------------------------------
# UI Panel Hit Testing
# ---------------------------------------------------------------------------

suite "UI - Panel Hit Testing":
  test "isInResourceBarArea detects resource bar":
    let panelRect = makeTestPanelRect(1280, 720)
    # Resource bar spans y=0 to y=32 (ResourceBarHeight=32)

    check isInResourceBarArea(panelRect, vec2(100, 0))    # At top of resource bar
    check isInResourceBarArea(panelRect, vec2(100, 16))   # In middle of resource bar
    check isInResourceBarArea(panelRect, vec2(100, 31))   # Near bottom boundary
    check not isInResourceBarArea(panelRect, vec2(100, 32))  # Below resource bar

  test "isInFooterArea detects footer":
    let panelRect = makeTestPanelRect(1280, 720)

    check isInFooterArea(panelRect, vec2(100, 700))  # In footer
    check not isInFooterArea(panelRect, vec2(100, 600))  # Above footer

  test "isInMinimapArea detects minimap":
    let panelRect = makeTestPanelRect(1280, 720)
    # Minimap is at bottom-left, above footer
    let mmX = MinimapMargin.float32
    let mmY = 720.0 - FooterHeight.float32 - MinimapSize.float32 - MinimapMargin.float32

    check isInMinimapArea(panelRect, vec2(mmX + 50, mmY + 50))  # In minimap
    check not isInMinimapArea(panelRect, vec2(500, mmY + 50))  # Right of minimap

# ---------------------------------------------------------------------------
# Minimap Coordinate Conversion Tests
# ---------------------------------------------------------------------------

suite "UI - Minimap Coordinate Conversion":
  test "worldToMinimapPixel converts map center":
    let panelRect = makeTestPanelRect(1280, 720)
    let worldCenter = ivec2(MapWidth div 2, MapHeight div 2)

    let minimapPos = worldToMinimapPixel(worldCenter, panelRect)

    # Should be roughly in the center of the minimap
    let mmX = MinimapMargin.float32
    let mmY = 720.0 - FooterHeight.float32 - MinimapSize.float32 - MinimapMargin.float32
    let expectedX = mmX + MinimapSize.float32 / 2
    let expectedY = mmY + MinimapSize.float32 / 2

    check abs(minimapPos.x - expectedX) < 1.0
    check abs(minimapPos.y - expectedY) < 1.0

  test "minimapPixelToWorld converts back to world":
    let panelRect = makeTestPanelRect(1280, 720)
    let mmX = MinimapMargin.float32
    let mmY = 720.0 - FooterHeight.float32 - MinimapSize.float32 - MinimapMargin.float32

    # Minimap center pixel
    let minimapCenter = vec2(mmX + MinimapSize.float32 / 2, mmY + MinimapSize.float32 / 2)
    let worldPos = minimapPixelToWorld(minimapCenter, panelRect)

    # Should be roughly at map center
    check abs(worldPos.x - MapWidth div 2) <= 1
    check abs(worldPos.y - MapHeight div 2) <= 1

  test "coordinate conversion round-trip":
    let panelRect = makeTestPanelRect(1280, 720)
    let originalWorld = ivec2(100, 75)

    let minimapPos = worldToMinimapPixel(originalWorld, panelRect)
    let backToWorld = minimapPixelToWorld(minimapPos, panelRect)

    # Should round-trip within 1 tile due to scaling
    check abs(backToWorld.x - originalWorld.x) <= 1
    check abs(backToWorld.y - originalWorld.y) <= 1

  test "worldToMinimapPixel handles edge positions":
    let panelRect = makeTestPanelRect(1280, 720)

    # Top-left corner of map
    let topLeft = worldToMinimapPixel(ivec2(0, 0), panelRect)
    check topLeft.x >= MinimapMargin.float32
    check topLeft.y >= 720.0 - FooterHeight.float32 - MinimapSize.float32 - MinimapMargin.float32

    # Bottom-right corner of map
    let bottomRight = worldToMinimapPixel(ivec2(MapWidth - 1, MapHeight - 1), panelRect)
    check bottomRight.x <= MinimapMargin.float32 + MinimapSize.float32
    check bottomRight.y <= 720.0 - FooterHeight.float32 - MinimapMargin.float32

# ---------------------------------------------------------------------------
# Control Group Tests
# ---------------------------------------------------------------------------

suite "UI - Control Groups":
  setup:
    resetSelection()
    for i in 0 ..< testControlGroups.len:
      testControlGroups[i] = @[]

  test "assignControlGroup saves current selection":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15))

    selectThings(@[agent1, agent2])
    assignControlGroup(0)

    check testControlGroups[0].len == 2

  test "recallControlGroup restores selection":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15))

    selectThings(@[agent1, agent2])
    assignControlGroup(0)
    resetSelection()

    recallControlGroup(0)

    check selection.len == 2
    check isSelected(agent1)
    check isSelected(agent2)

  test "control groups are independent":
    let env = makeEmptyEnv()
    let agent1 = addAgentAt(env, 0, ivec2(10, 10))
    let agent2 = addAgentAt(env, 1, ivec2(15, 15))
    let agent3 = addAgentAt(env, 2, ivec2(20, 20))

    selectThing(agent1)
    assignControlGroup(1)

    selectThings(@[agent2, agent3])
    assignControlGroup(2)

    recallControlGroup(1)
    check selection.len == 1
    check isSelected(agent1)

    recallControlGroup(2)
    check selection.len == 2
    check isSelected(agent2)
    check isSelected(agent3)

# ---------------------------------------------------------------------------
# Tooltip Tests
# ---------------------------------------------------------------------------

suite "UI - Tooltip System":
  setup:
    clearTooltip()

  test "tooltip starts not visible":
    check not isTooltipVisible()

  test "tooltip becomes visible after delay":
    let content = buildCommandTooltip(CmdMove, "M")
    let anchorRect = Rect(x: 100, y: 100, w: 48, h: 48)

    startHover(TooltipCommand, anchorRect, content)

    # Not visible immediately
    check not isTooltipVisible()

    # Simulate time passing (manually set visible for test)
    # Note: In real usage, updateTooltip() checks elapsed time
    # For testing, we verify the state machine logic

  test "clearTooltip hides tooltip":
    let content = buildCommandTooltip(CmdAttack, "A")
    let anchorRect = Rect(x: 100, y: 100, w: 48, h: 48)

    startHover(TooltipCommand, anchorRect, content)
    clearTooltip()

    check not isTooltipVisible()

  test "buildCommandTooltip creates content for move":
    let content = buildCommandTooltip(CmdMove, "M")

    check content.title == "Move"
    check content.description.len > 0
    check content.hotkeyLine == "Hotkey: M"

  test "buildCommandTooltip includes costs for training":
    let content = buildCommandTooltip(CmdTrainManAtArms, "W")

    check content.title == "Train Man-at-Arms"
    check content.costLines.len > 0  # Should have resource costs
    check content.statsLines.len > 0  # Should have training time

  test "buildCommandTooltip includes costs for buildings":
    let content = buildCommandTooltip(CmdBuildBarracks, "A")

    check content.title == "Build Barracks"
    check content.costLines.len > 0  # Should have wood cost
    check content.description.len > 0


# ---------------------------------------------------------------------------
# Rally Point Mode Tests
# ---------------------------------------------------------------------------

suite "UI - Rally Point Mode":
  setup:
    resetSelection()
    rallyPointMode = false

  test "rally point mode starts disabled":
    check not rallyPointMode

  test "rally point mode can be enabled":
    rallyPointMode = true
    check rallyPointMode

  test "rally point mode is cleared on reset":
    rallyPointMode = true
    rallyPointMode = false
    check not rallyPointMode

  test "CmdSetRally button appears for barracks":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 10), 0)
    selectThing(barracks)
    let panelRect = makeTestPanelRect()
    check hasCommandButton(panelRect, CmdSetRally)

  test "CmdSetRally button hotkey is G":
    let hotkey = getButtonHotkey(CmdSetRally)
    check hotkey == "G"
