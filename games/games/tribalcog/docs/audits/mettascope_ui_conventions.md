# Mettascope UI Coding Conventions Audit

This document catalogs the UI coding patterns and conventions used in Mettascope for potential adoption in tribal_village.

**Source location:** `/home/relh/gt/metta/mayor/rig/packages/mettagrid/nim/mettascope/src/`

## 1. File/Module Organization

### Directory Structure

```
mettascope/src/
  mettascope.nim          # Main entry point
  mettascope.nims         # Nimble config
  mettascope/             # All modules
    common.nim            # Shared types, state, utilities
    colors.nim            # Color constants/theme
    configs.nim           # Persistence and serialization
    panels.nim            # Panel/area layout system
    header.nim            # Header bar component
    footer.nim            # Footer bar component
    timeline.nim          # Timeline scrubber
    panels/               # Individual panel implementations
      widgets.nim         # Shared panel widgets
      objectpanel.nim     # Object info panel
      vibespanel.nim      # Vibe selection panel
      collectivepanel.nim # Collective stats panel
      scorepanel.nim      # Score display panel
      envpanel.nim        # Environment panel
      aoepanel.nim        # Area of effect panel
```

### Naming Conventions

- **Files:** lowercase, snake_case for multi-word (e.g., `objectpanel.nim`)
- **Types:** PascalCase (e.g., `Panel`, `Area`, `ZoomInfo`)
- **Procs:** camelCase (e.g., `drawHeader`, `saveUIState`)
- **Constants:** PascalCase (e.g., `AreaHeaderHeight`, `HeaderColor`)
- **Panel draw procs:** `drawXxxPanel` or `drawXxx` pattern

### Module Dependencies

```nim
# Standard pattern for panel files
import
  std/[json, tables, strformat],  # Standard library
  vmath, silky, windy,             # External libraries
  ../common, ../replays, ../configs  # Internal modules
```

- Explicit imports (no `*` wildcards)
- Standard library first, then external, then internal
- Relative paths for internal modules

## 2. Widget Patterns

### Silky UI Framework

Mettascope uses **Silky**, an immediate-mode UI library. Key concepts:

- `sk` - Global Silky instance
- `sk.at` - Current cursor position
- `sk.size` - Available size for current context
- `sk.advance(vec2)` - Move cursor forward

### Panel Signature

All panels follow this signature:

```nim
proc drawObjectInfo*(panel: Panel, frameId: string, contentPos: Vec2, contentSize: Vec2) =
  frame(frameId, contentPos, contentSize):
    # Panel content here
    if selection.isNil:
      text("No selection")
      return
    # ...
```

- `panel`: Panel metadata (name, parentArea)
- `frameId`: Unique identifier for scrolling state
- `contentPos`, `contentSize`: Panel bounds

### Core Widgets

```nim
# Text widgets
text("Simple text")
h1text("Header text")

# Buttons
button("Label"):
  # Click handler
  doSomething()

iconButton("ui/icon-name"):
  # Click handler
  doSomething()

clickableIcon("ui/icon", isEnabled):
  # Click handler when enabled
  doSomething()

# Icons
icon("resources/heart")
image("ui/logo")

# Tooltips (must follow interactive widget)
iconButton("ui/help"):
  openHelp()
if sk.shouldShowTooltip:
  tooltip("Help & Documentation")

# Grouping
group(vec2(4, 4), LeftToRight):
  icon("resources/gold")
  text("x10")
```

### Custom Widgets Example

From `panels/widgets.nim`:

```nim
template smallIconLabel*(imageName: string, labelText: string) =
  ## Draw a small icon with a text label, properly aligned.
  let startX = sk.at.x
  let startY = sk.at.y
  sk.at.x += 8  # Indent

  # Draw icon (use undefined if not found)
  let actualIcon =
    if imageName in sk.atlas.entries:
      imageName
    else:
      "icons/undefined"
  drawImageScaled(sk, actualIcon, sk.at, vec2(IconSize, IconSize))

  sk.at.x += IconSize + 6  # Advance past icon + gap
  sk.at.y += 6  # Center text vertically with icon
  text(labelText)

  sk.at.x = startX  # Reset x for next line
  sk.at.y = startY + IconSize + 2  # Move to next line
```

### 9-Patch Rendering

```nim
sk.draw9Patch("panel.header.9patch", 3, headerRect.xy, headerRect.wh)
sk.draw9Patch("panel.tab.selected.9patch", 3, tabRect.xy, tabRect.wh, rgbx(255, 255, 255, 255))
```

## 3. Layout Patterns

### Area-Based Layout System

The UI uses a binary tree of Areas for flexible panel layouts:

```nim
type
  AreaLayout* = enum
    Horizontal  # Split top/bottom
    Vertical    # Split left/right

  Area* = ref object
    layout*: AreaLayout
    areas*: seq[Area]          # Child areas (always 0 or 2)
    panels*: seq[Panel]        # Panels in leaf areas
    split*: float32            # Split ratio (0.0-1.0)
    selectedPanelNum*: int     # Active tab
    rect*: Rect                # Calculated bounds
```

### Layout Constants

```nim
const
  AreaHeaderHeight = 32.0
  AreaMargin = 6.0
```

### Creating Default Layout

```nim
proc createDefaultPanelLayout() =
  rootArea = Area()
  rootArea.split(Vertical)
  rootArea.split = 0.22

  rootArea.areas[0].split(Horizontal)
  rootArea.areas[0].split = 0.7

  rootArea.areas[1].split(Vertical)
  rootArea.areas[1].split = 0.85

  rootArea.areas[0].areas[0].addPanel("Object", drawObjectInfo)
  rootArea.areas[0].areas[0].addPanel("Environment", drawEnvironmentInfo)
  rootArea.areas[1].areas[0].addPanel("Map", drawWorldMap)
  # ...
```

### Panel Management

```nim
proc addPanel*(area: Area, name: string, draw: PanelDraw)
proc movePanel*(area: Area, panel: Panel)
proc insertPanel*(area: Area, panel: Panel, index: int)
proc split*(area: Area, layout: AreaLayout)
```

### Ribbon Component

For header/footer bars:

```nim
proc drawFooter*(pos, size: Vec2) =
  ribbon(pos, size, FooterColor):
    sk.at = pos + vec2(16, 16)
    group(vec2(0, 0), LeftToRight):
      clickableIcon("ui/rewindToStart", step != 0):
        step = 0
      if sk.shouldShowTooltip:
        tooltip("Rewind to Start")
      # ...
```

### Positioning Patterns

```nim
# Absolute positioning within context
sk.at = sk.pos + vec2(sk.size.x - 100, 16)

# Relative advancement
sk.advance(vec2(0, sk.theme.spacing.float32))

# Wrapping content
let buttonWidth = 32.0f + sk.padding
let startX = sk.at.x
for i, item in items:
  if sk.at.x + buttonWidth > sk.pos.x + sk.size.x - margin:
    sk.at.x = startX
    sk.at.y += 32 + margin
  # draw item...
```

## 4. Color/Theming

### Color Palette (Flat UI)

`colors.nim` defines the theme using Flat UI colors:

```nim
import chroma

const
  # Primary colors
  Turquoise*   = parseHtmlColor("#1abc9c").rgbx
  Green*       = parseHtmlColor("#2ecc71").rgbx
  Blue*        = parseHtmlColor("#3498db").rgbx
  Purple*      = parseHtmlColor("#9b59b6").rgbx
  Yellow*      = parseHtmlColor("#f1c40f").rgbx
  Orange*      = parseHtmlColor("#f39c12").rgbx
  Red*         = parseHtmlColor("#e74c3c").rgbx

  # Dark variants
  Teal*        = parseHtmlColor("#16a085").rgbx
  DarkGreen*   = parseHtmlColor("#27ae60").rgbx
  DarkBlue*    = parseHtmlColor("#2980b9").rgbx
  DarkPurple*  = parseHtmlColor("#8e44ad").rgbx
  DarkOrange*  = parseHtmlColor("#e67e22").rgbx
  DarkRed*     = parseHtmlColor("#c0392b").rgbx

  # Neutrals
  Slate*       = parseHtmlColor("#34495e").rgbx
  MidnightBlue*= parseHtmlColor("#2c3e50").rgbx
  Cloud*       = parseHtmlColor("#ecf0f1").rgbx
  Silver*      = parseHtmlColor("#bdc3c7").rgbx
  Gray*        = parseHtmlColor("#95a5a6").rgbx
  DarkGray*    = parseHtmlColor("#7f8c8d").rgbx
```

### Component Colors

```nim
const
  HeaderColor = parseHtmlColor("#273646").rgbx
  FooterColor = parseHtmlColor("#273646").rgbx
  ScrubberColor = parseHtmlColor("#1D1D1D").rgbx
```

### Dynamic Coloring

```nim
proc getCollectiveColor*(collectiveId: int): ColorRGBX =
  let name = getCollectiveName(collectiveId)
  case name
    of "clips": Red
    of "cogs", "cogs_green": Green
    of "cogs_blue": Blue
    # ...
    else: Gray
```

## 5. Event Handling

### Mouse Input

```nim
# Check button state
if window.buttonPressed[MouseLeft]:   # Just pressed this frame
  startDrag()
if window.buttonDown[MouseLeft]:      # Currently held
  continueDrag()
if not window.buttonDown[MouseLeft]:  # Released
  endDrag()

# Mouse position
let mousePos = window.mousePos.vec2
let localMousePos = mousePos - rect.xy

# Scroll
if window.scrollDelta.y != 0:
  applyZoom(window.scrollDelta.y)

# Hit testing
if mousePos.overlaps(buttonRect):
  handleHover()
```

### Keyboard Input

```nim
if window.buttonPressed[KeySpace]:
  play = not play
if window.buttonPressed[KeyMinus]:
  playSpeed *= 0.5
if window.buttonPressed[KeyEqual]:
  playSpeed *= 2

# Modifier keys
let shiftDown = window.buttonDown[KeyLeftShift] or window.buttonDown[KeyRightShift]
```

### Widget Callbacks

Template-based immediate-mode pattern:

```nim
clickableIcon("ui/play", enabled):
  # This block executes on click
  play = true
  saveUIState()
```

### Cursor Management

```nim
sk.cursor = Cursor(kind: ArrowCursor)
sk.cursor = Cursor(kind: ResizeUpDownCursor)
sk.cursor = Cursor(kind: ResizeLeftRightCursor)

# Apply at frame end
if window.cursor.kind != sk.cursor.kind:
  window.cursor = sk.cursor
```

## 6. State Management

### Global State Pattern

`common.nim` declares all shared state as module-level vars:

```nim
var
  sk*: Silky
  bxy*: Boxy
  window*: Window
  frame*: int

  settings* = Settings()
  selection*: Entity
  activeCollective*: int = 1

  step*: int = 0
  stepFloat*: float32 = 0
  previousStep*: int = -1
  replay*: Replay
  play*: bool
  playSpeed*: float32 = 10.0

  rootArea*: Area
```

### Settings Object

Group related settings into an object:

```nim
type
  Settings* = object
    showFogOfWar* = false
    showVisualRange* = true
    showGrid* = true
    showResources* = true
    showHeatmap* = false
    showObservations* = -1
    lockFocus* = false
```

### Config Persistence

```nim
type
  MettascopeConfig* = object
    windowWidth*: int32
    windowHeight*: int32
    panelLayout*: AreaLayoutConfig
    playSpeed*: float32
    settings*: SettingsConfig
    selectedAgentId*: int
    gameMode*: GameMode

proc saveConfig*(config: MettascopeConfig) =
  setConfig("mettascope", "config.json", config.toJson())

proc loadConfig*(): MettascopeConfig =
  let jsonStr = getConfig("mettascope", "config.json")
  if jsonStr != "":
    try:
      result = jsonStr.fromJson(MettascopeConfig)
    except:
      result = DefaultConfig
      saveConfig(result)
  else:
    result = DefaultConfig
    saveConfig(result)
```

### UI State Save/Load

```nim
proc saveUIState*() =
  var config = loadConfig()
  config.playSpeed = playSpeed
  config.settings.showFogOfWar = settings.showFogOfWar
  # ...
  saveConfig(config)

proc applyUIState*(config: MettascopeConfig) =
  playSpeed = config.playSpeed
  settings.showFogOfWar = config.settings.showFogOfWar
  # ...
```

## 7. Recommendations for tribal_village

### Patterns to Adopt

1. **Unified color palette module** - Define all theme colors in one place
2. **Panel signature pattern** - Consistent function signature for all panels
3. **Frame template** - Wrap panel content in `frame()` for scroll/clip
4. **Widget templates** - Use templates for reusable widget patterns
5. **Settings object pattern** - Group related settings together
6. **Config serialization** - Use jsony for simple JSON persistence
7. **Tooltip pattern** - `if sk.shouldShowTooltip: tooltip("text")` after interactive widgets

### Suggested Refactoring

1. **Create `colors.nim`** - Centralize color constants
2. **Create `widgets.nim`** - Extract reusable widget templates
3. **Standardize panel signatures** - All panels should take `(panel, frameId, pos, size)`
4. **Use ribbon for toolbars** - Consistent header/footer rendering
5. **Separate state from rendering** - Global state in `common.nim`, UI in component files

### Code Organization Changes

```
tribal_village/
  src/
    ui/
      common.nim        # Shared types, global state
      colors.nim        # Theme colors
      configs.nim       # Persistence
      widgets.nim       # Reusable widget templates
      panels.nim        # Panel layout system
      panels/           # Individual panel implementations
        objectpanel.nim
        inventorypanel.nim
        ...
```

### Key Differences to Note

- Mettascope uses immediate-mode UI (Silky) - if tribal_village uses retained mode, patterns will differ
- Layout system is binary-tree based - may need adaptation for different layout needs
- Heavy use of templates for zero-overhead abstraction - leverage this in Nim
