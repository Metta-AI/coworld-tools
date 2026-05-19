# Silky Semantic Tree Rendering Audit

**Date:** 2026-02-11
**Auditor:** polecat/nux
**Bead:** tv-dgqwvp

## Executive Summary

Silky (treeform/silky) is an Immediate Mode GUI library for Nim that includes a semantic capture layer for text-based UI inspection. This feature allows rendering the UI widget tree as structured text instead of pixels, enabling LLM-based UI analysis and automated testing.

**Key Finding:** Silky is NOT a direct successor to boxy. They serve different purposes:
- **Boxy:** Low-level 2D GPU rendering with texture atlasing
- **Silky:** High-level Immediate Mode GUI with widget semantics

tribal_village currently uses boxy for rendering. Mettascope already uses silky but doesn't utilize the semantic capture features.

## What is Silky?

Repository: [treeform/silky](https://github.com/treeform/silky)

Silky is an Immediate Mode GUI library for Nim focused on speed:
- Single draw call to render entire UI
- Clean DSL that looks like idiomatic Nim
- 9-patch support for scalable UI elements
- Texture atlas for efficient rendering
- Inspired by Dear ImGui but reimagined for Nim

### Relationship to Other Libraries

| Library | Purpose | Used By |
|---------|---------|---------|
| **boxy** | 2D GPU rendering with tiling atlas | tribal_village |
| **silky** | Immediate Mode GUI with widgets | mettascope, vibescope |
| **pixie** | 2D graphics library | Both |
| **windy** | Windowing system | Both |

## Semantic Tree Feature

### Location

The semantic tree functionality is in `src/silky/semantic.nim` with a testing harness in `src/silky/testing.nim`.

### Core Types

```nim
type
  WidgetState = object
    enabled: bool
    focused: bool
    pressed: bool
    hovered: bool
    checked: bool
    value: string

  SemanticNode = ref object
    kind: string        # Widget type (Button, CheckBox, etc.)
    name: string        # Widget identifier
    text: string        # Display text
    rect: Rect          # Bounding box (x, y, w, h)
    state: WidgetState  # Interaction state
    children: seq[SemanticNode]
    parent: SemanticNode

  SemanticCapture = object
    stack: seq[SemanticNode]
    root: SemanticNode
    frameNumber: int
```

### Output Format

The semantic tree outputs a YAML-like text format:

```
frame: 1
TestWindow:
  type: SubWindow
  rect: 10 10 300 200
  state: enabled
  children:
    0:
      type: Button
      text: Click Me
      rect: 20 50 100 30
      state: enabled hovered
    1:
      type: Button
      text: Cancel
      rect: 130 50 80 30
      state: enabled
    2:
      type: CheckBox
      text: Option 1
      rect: 20 90 100 20
      state: checked
```

### API Usage

```nim
import silky

let sk = newSilky("atlas.png", "atlas.json")

# During UI rendering, capture semantic nodes
sk.beginWidget("Button", name = "submit", text = "Submit", rect = buttonRect)
sk.setWidgetState(enabled = true, hovered = isHovered, pressed = isPressed)
sk.endWidget()

# Get text representation
let snapshot = sk.semanticSnapshot()
echo snapshot
```

### Query Functions

```nim
# Find by path (dot-separated)
let node = sk.semantic.root.findByPath("TestWindow.0")

# Find by text content
let button = sk.semantic.root.findByText("Click Me")

# Find by name and type
let checkbox = sk.semantic.root.findByName("option1", "CheckBox")

# Find all matching nodes
let allButtons = sk.semantic.root.findAllByText("Submit", "Button")
```

### Diff Detection

```nim
let d = diff(oldSnapshot, newSnapshot)
# Returns line-by-line diff showing UI changes
```

## UI Debugging Capabilities

### What It Can Show

| Feature | Supported | Notes |
|---------|-----------|-------|
| Widget positions | Yes | `rect: x y w h` |
| Widget sizes | Yes | Via rect |
| Widget type | Yes | `type: Button`, `CheckBox`, etc. |
| Widget text | Yes | Labels, button text |
| Interaction state | Yes | enabled, focused, hovered, pressed, checked |
| Widget hierarchy | Yes | Parent-child relationships |
| Value for inputs | Yes | `value` field in state |

### What It Can Detect

- **Overlapping widgets:** Compare rect coordinates
- **Alignment issues:** Check x/y consistency across siblings
- **Missing widgets:** Query by expected name/text returns nil
- **State bugs:** Check expected state vs actual
- **Hierarchy problems:** Traverse parent-child relationships

### Limitations

- No margin/padding information (only bounding rects)
- No styling information (colors, fonts)
- No z-order information beyond tree depth
- Requires explicit `beginWidget`/`endWidget` calls in rendering code

## Integration Path for tribal_village

### Current State

tribal_village uses **boxy** for rendering:

```nim
# src/renderer.nim
import boxy, pixie, vmath, windy, ...
```

Boxy is a retained-mode renderer without UI widget semantics. It draws images and shapes directly without an intermediate widget representation.

### Option 1: Add Semantic Layer to Boxy (Custom)

Create a parallel semantic tree that tracks what boxy draws:

```nim
# Hypothetical addition to tribal_village
var semanticCapture: SemanticCapture

proc drawUIElement(name: string, rect: Rect, kind: string) =
  semanticCapture.pushNode(newSemanticNode(kind, name))
  semanticCapture.currentNode.rect = rect
  # ... actual boxy drawing ...
  semanticCapture.popNode()
```

**Pros:**
- No library switch required
- Minimal refactoring

**Cons:**
- Manual tracking of all UI elements
- Could drift from actual rendering

### Option 2: Migrate to Silky

Replace boxy with silky for UI components:

```nim
# Would need to change from:
bxy.drawImage("button", pos)

# To:
sk.beginWidget("Button", name = "action")
# silky's button widget handles drawing
sk.endWidget()
```

**Pros:**
- Built-in semantic capture
- Higher-level widget abstractions

**Cons:**
- Significant refactoring
- Different rendering paradigm (immediate vs retained)
- tribal_village has complex custom rendering that doesn't fit widget model

### Option 3: Hybrid Approach

Use silky for overlay UI panels while keeping boxy for game world rendering:

```nim
# Game world: boxy
bxy.beginFrame(windowSize)
renderGameWorld(bxy, state)
bxy.endFrame()

# UI overlay: silky with semantic capture
sk.beginUi(window, windowSize)
renderUI(sk, state)  # menus, HUD, panels
let snapshot = sk.semanticSnapshot()
sk.endUi()
```

**Pros:**
- Semantic capture for UI without rewriting game renderer
- Clean separation of concerns

**Cons:**
- Two rendering systems to maintain
- Potential performance overhead

### Recommended Approach

**Option 3 (Hybrid)** is most practical:

1. Keep boxy for game world rendering (sprites, terrain, units)
2. Add silky for UI overlay components (menus, tooltips, panels)
3. Enable semantic capture only for silky-rendered UI
4. Game world semantics could use a separate, simpler format (entity list + positions)

### Runtime Toggle

Semantic capture is enabled by default in silky. To add a toggle:

```nim
# Could add to Silky
var semanticEnabled* = true

proc beginWidget*(sk: Silky, ...) =
  if not semanticEnabled:
    return
  # ... capture logic ...
```

Or use compile-time flag:
```nim
# nim c -d:silkyTesting app.nim
when defined(silkyTesting):
  sk.semantic.enabled = true
```

## Example: tribal_village Semantic Output

If tribal_village used semantic capture, UI output might look like:

```
frame: 4521
HUD:
  type: Panel
  rect: 0 0 1280 64
  children:
    resources:
      type: ResourceBar
      rect: 10 10 400 44
      children:
        gold:
          type: Resource
          text: Gold: 1250
          rect: 10 10 100 44
        wood:
          type: Resource
          text: Wood: 830
          rect: 120 10 100 44
    selection:
      type: SelectionPanel
      rect: 440 10 400 44
      text: 5 Villagers selected
CommandPanel:
  type: Panel
  rect: 1000 500 280 300
  children:
    0:
      type: Button
      text: Build
      rect: 1010 510 120 40
      state: enabled hovered
    1:
      type: Button
      text: Attack
      rect: 1140 510 120 40
      state: enabled
```

## Testing Harness

Silky includes a testing harness for headless UI tests:

```nim
import silky

var h = newTestHarness("atlas.png", "atlas.json")

# Run a frame
let diff = h.pumpFrame do (sk: Silky, window: Window):
  # Your UI code here
  sk.beginWidget("Button", text = "Click Me")
  sk.endWidget()

# Find and click by label
let diff = h.clickLabel("Click Me", myUIProc)

# Assert on tree structure
let button = h.findByText("Click Me")
assert button != nil
assert button.state.enabled
```

## Conclusions

1. **Silky's semantic tree is production-ready** for text-based UI inspection
2. **tribal_village cannot directly use it** without significant refactoring (different rendering paradigm)
3. **Hybrid approach is feasible** for capturing UI panel semantics while keeping boxy for game rendering
4. **Mettascope could enable this today** as it already uses silky

## Next Steps

If proceeding with integration:

1. Add silky as dependency to tribal_village
2. Identify UI components suitable for silky (HUD, menus, panels)
3. Create wrapper that renders both boxy (game) and silky (UI)
4. Enable semantic capture for silky layer
5. Create snapshot export for LLM analysis

## References

- [treeform/silky](https://github.com/treeform/silky) - Silky repository
- [treeform/boxy](https://github.com/treeform/boxy) - Boxy repository
- `src/silky/semantic.nim` - Semantic capture implementation
- `src/silky/testing.nim` - Testing harness
- `tests/test_semantic.nim` - Test examples
