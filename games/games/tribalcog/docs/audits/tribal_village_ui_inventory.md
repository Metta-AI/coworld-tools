# Tribal Village UI Inventory for Silky Migration

## Overview

This document catalogs all UI elements in tribal_village that could benefit from silky migration. The codebase uses boxy for rendering with pixie for text/image generation.

## UI Component Inventory

### 1. Footer Panel
**Location:** `src/renderer.nim:292-416` (buildFooterButtons, drawFooter)
**Layout Constants:** `src/common.nim:62`
- `FooterHeight = 64` pixels
- `FooterPadding = 10.0` pixels
- `FooterButtonPaddingX = 18.0` pixels
- `FooterButtonGap = 12.0` pixels

**Description:** Horizontal strip at bottom of screen with playback controls.

**Buttons:**
- Play/Pause (toggles icon)
- Step (single frame advance)
- Slow/Fast/Faster/Super (speed controls)

**Positioning Approach:**
```nim
let fy = panelRect.y.float32 + panelRect.h.float32 - FooterHeight.float32
let startX = panelRect.x.float32 + (panelRect.w.float32 - totalWidth) * 0.5  # Center-aligned
```
- Buttons are horizontally centered within footer
- Each button has dynamic width based on label + icon
- Uses `FooterButtonGap` between buttons

---

### 2. Resource Bar (HUD)
**Location:** `src/renderer.nim:2540-2620` (drawResourceBar)
**Layout Constants:** `src/common.nim:63`
- `ResourceBarHeight = 32` pixels

**Description:** Top-of-screen resource display showing team stockpiles.

**Elements:**
- Food/Wood/Stone/Gold/Water icons with counts
- Population counter (current/cap)
- Step counter

**Positioning Approach:**
- Fixed height at top of viewport
- Icons with label spacing
- Horizontal layout with gaps between resource groups

---

### 3. Minimap
**Location:** `src/minimap.nim` (complete module)
**Layout Constants:** `src/common.nim:66-67`
- `MinimapSize = 200` pixels (square)
- `MinimapMargin = 8` pixels
- `MinimapBorderWidth = 2.0` pixels
- `MinimapViewportLineWidth = 1.5` pixels

**Description:** Bird's-eye view of terrain with units/buildings and viewport rectangle.

**Positioning Approach:**
```nim
proc minimapRect*(panelRect: IRect): Rect =
  let x = panelRect.x.float32 + MinimapMargin.float32
  let y = panelRect.y.float32 + panelRect.h.float32 -
          FooterHeight.float32 - MinimapMargin.float32 - MinimapSize.float32
  Rect(x: x, y: y, w: MinimapSize.float32, h: MinimapSize.float32)
```
- Bottom-left corner, above footer
- Fixed size square
- Viewport rectangle drawn as 4 separate line rects

---

### 4. Command Panel
**Location:** `src/command_panel.nim` (complete module)
**Layout Constants:** `src/common.nim:78-83`
- `CommandPanelWidth = 240` pixels
- `CommandPanelMargin = 8` pixels
- `CommandButtonSize = 48` pixels (square)
- `CommandButtonGap = 6` pixels
- `CommandButtonCols = 4` (buttons per row)
- `CommandPanelPadding = 10` pixels

**Description:** Context-sensitive action buttons (move/attack/build/train).

**Positioning Approach:**
```nim
proc commandPanelRect*(panelRect: IRect): Rect =
  let x = panelRect.x.float32 + panelRect.w.float32 - CommandPanelWidth.float32 - CommandPanelMargin.float32
  let y = panelRect.y.float32 + panelRect.h.float32 - FooterHeight.float32 - MinimapSize.float32 - CommandPanelMargin.float32 * 2
  let h = MinimapSize.float32  # Same height as minimap for visual balance
```
- Bottom-right corner, same vertical extent as minimap
- Grid layout: 4 columns, dynamic rows
- Button positions calculated via `col = i mod CommandButtonCols`, `row = i div CommandButtonCols`

---

### 5. Tooltips
**Location:** `src/tooltips.nim` (complete module)
**Layout Constants:** (in-module)
- `TooltipPadding = 10` pixels
- `TooltipLineHeight = 18` pixels
- `TooltipMaxWidth = 280` pixels
- `TooltipShowDelay = 0.3` seconds

**Description:** Hover tooltips for command buttons, units, buildings.

**Positioning Approach:**
```nim
proc positionTooltip(anchorRect: Rect, tooltipSize: Vec2, screenSize: Vec2): Vec2 =
  var x = anchorRect.x - tooltipSize.x - 8  # Position to left of anchor
  # If would go off left edge, position to right
  if x < 8:
    x = anchorRect.x + anchorRect.w + 8
  # Keep on screen vertically...
```
- Positioned relative to hovered element
- Prefers left-of-anchor, falls back to right
- Clamped to screen bounds

---

### 6. Selection Box (Drag Rectangle)
**Location:** `tribal_village.nim:595-634` (drag selection logic)
**Rendering:** `src/renderer.nim` (drawSelectionBox)
**Layout Constants:** `src/constants.nim:562-567`
- `SelectionBoxLineWidth = 0.05` world units
- `SelectionBoxColorRGBA` for styling

**Description:** Green rectangle shown during drag-select.

**Positioning Approach:**
- World-space coordinates from drag start to current mouse
- Converted via `bxy.getTransform().inverse`

---

### 7. Health Bars
**Location:** `src/renderer.nim:1084-1088` (drawAgentDecorations)
**Layout Constants:** `src/renderer.nim:24-27`
- `HealthBarFadeInDuration = 5` steps
- `HealthBarVisibleDuration = 60` steps
- `HealthBarFadeOutDuration = 30` steps
- `HealthBarMinAlpha = 0.3`

**Description:** Segmented health bars above units when damaged.

**Positioning Approach:**
```nim
drawSegmentBar(posVec, vec2(0, -0.55), hpRatio, ...)
```
- World-space offset from unit center
- Uses `drawSegmentBar` helper with fixed segment count (5)
- Segment width: `0.16` world units

---

### 8. Damage Numbers
**Location:** `src/renderer.nim:1253-1272` (drawDamageNumbers)
**Layout Constants:** `src/renderer.nim:52-54`
- `DamageNumberFontSize = 28`
- `DamageNumberFloatHeight = 0.8` world units

**Description:** Floating combat feedback numbers.

**Positioning Approach:**
```nim
let floatOffset = (1.0 - t) * DamageNumberFloatHeight
let worldPos = vec2(dmg.pos.x.float32, dmg.pos.y.float32 - floatOffset)
```
- World-space, floats upward over time
- Scale `1.0 / 200.0` for world rendering

---

### 9. Control Group Badges
**Location:** `src/renderer.nim:488-500, 1111-1119`
**Layout Constants:** `src/renderer.nim:56-59`
- `ControlGroupBadgeFontSize = 24`
- `ControlGroupBadgePadding = 4.0`
- `ControlGroupBadgeScale = 1.0 / 180.0`

**Description:** Number badges (1-9) above units in control groups.

**Positioning Approach:**
```nim
let badgeOffset = vec2(0.35, -0.45)
bxy.drawImage(badgeKey, posVec + badgeOffset, ...)
```
- Upper-right of unit, world-space offset
- Fixed offset, doesn't account for health bar

---

### 10. Building Overlays
**Location:** `src/renderer.nim:907-976`

**Elements:**
- Production queue progress bars (`vec2(0, 0.55)`)
- Construction scaffolding and progress bars (`vec2(0, 0.65)`)
- Stockpile icons and counts (`vec2(-0.18, -0.62)`)
- Garrison indicators (`vec2(0.22, -0.62)`)
- Population counters on Town Center

**Positioning Approach:**
- All use fixed world-space offsets from building center
- `OverlayIconScale = 1/320`, `OverlayLabelScale = 1/200`

---

### 11. Veterancy Stars
**Location:** `src/renderer.nim:1098-1133`

**Description:** Gold stars above HP bar for units with kills.

**Positioning Approach:**
```nim
const VeterancyStarScale = 1.0 / 500.0
let starY = -0.72'f32  # Above HP bar
let startX = -starSpacing * (starsToShow - 1).float32 / 2.0
```
- Centered horizontally above unit
- Fixed vertical offset above health bar

---

## Problem Areas (Git History Analysis)

### Commits with positioning-related changes:

1. **`42296d6` - Fix behavior test assertions: settlement bounds, trade cog land restriction, UI hit boundary**
   - UI hit testing boundary corrections

2. **`23873c8` - feat(visual): add garrison visual indicator on buildings**
   - Added new overlay element with offset positioning

3. **`02fbceb` - feat(ui): add shift-queue commands for AoE2-style command queueing**
   - Command panel button additions

4. **`9c041a6` - feat: implement research and production queue UI panels**
   - Complex UI additions to command panel

5. **`e9a5c61` - feat: add G key rally point mode for production buildings**
   - Rally point mode state management

### Common Positioning Patterns That Needed Tweaks:

1. **Fixed pixel offsets** - Many elements use hardcoded offsets like `vec2(0.35, -0.45)` that don't scale
2. **Footer/minimap coordination** - Multiple elements position relative to footer height
3. **Content scale handling** - HiDPI scaling via `window.contentScale` requires careful coordinate conversion
4. **World vs screen space** - Health bars, badges use world units; UI panels use screen pixels

---

## Rendering Code Locations

### Main Entry Points:
- **`tribal_village.nim:120-800`** - Main display() loop with input handling
- **`src/renderer.nim`** - All world-space rendering (2000+ lines)
- **`src/minimap.nim`** - Minimap rendering (200 lines)
- **`src/command_panel.nim`** - Command panel (580 lines)
- **`src/tooltips.nim`** - Tooltip system (675 lines)

### Boxy Usage Patterns:
```nim
# Screen-space UI elements:
bxy.drawRect(rect = Rect(...), color = ...)
bxy.drawImage(key, pos, angle = 0, scale = 1)

# World-space elements (after transform):
bxy.drawImage(spriteKey, worldPos.vec2, angle = 0, scale = SpriteScale, tint = ...)
```

### Transform Stack:
```nim
bxy.pushLayer()
bxy.saveTransform()
bxy.translate(...)  # Panel offset
bxy.scale(vec2(zoomScaled, zoomScaled))  # World zoom
# ... world rendering ...
bxy.restoreTransform()
# ... screen-space UI ...
bxy.popLayer()
```

---

## Semantic Tree Candidates

### High Priority (Complex Nested Layouts):

1. **Command Panel** - Grid of buttons with dynamic content, hotkeys, icons
   - Would benefit from: layout debugging, hit testing visualization
   - Complexity: Button grid with variable rows, context-sensitive content

2. **Tooltips** - Multi-section layout with title, description, costs, stats
   - Would benefit from: text measurement debugging, positioning validation
   - Complexity: Dynamic sizing based on content, screen-edge clamping

3. **Resource Bar** - Horizontal icon+label groups with alignment
   - Would benefit from: spacing/gap debugging
   - Complexity: Multiple resource types with counts

### Medium Priority (Fixed Layouts):

4. **Footer** - Button row with icons and labels
   - Would benefit from: centering validation
   - Currently stable but uses manual width calculation

5. **Minimap** - Coordinate conversion debugging
   - Would benefit from: viewport rectangle alignment inspection
   - Complexity: World-to-minimap coordinate mapping

### Lower Priority (World-Space Elements):

6. **Health Bars / Progress Bars** - Consistent offset debugging
   - Would benefit from: offset visualization across zoom levels

7. **Building Overlays** - Multiple overlapping elements
   - Would benefit from: z-order and positioning audit

---

## Migration Priority Ranking

| Rank | Component | Benefit | Effort | Notes |
|------|-----------|---------|--------|-------|
| 1 | **Command Panel** | High | Medium | Most dynamic, context-sensitive |
| 2 | **Tooltips** | High | Medium | Complex layout + positioning logic |
| 3 | **Resource Bar** | Medium | Low | Simple but frequently visible |
| 4 | **Footer** | Medium | Low | Stable but good test case |
| 5 | **Minimap** | Medium | Medium | Coordinate conversion complexity |
| 6 | **Health Bars** | Low | Low | World-space, simpler pattern |
| 7 | **Building Overlays** | Low | Medium | Many small elements |

### Quick Wins:
- Footer (simple horizontal layout)
- Resource Bar (repeated pattern)

### Complex Migrations:
- Command Panel (needs full state inspection)
- Tooltips (dynamic sizing, positioning rules)

### Dependencies:
- Command Panel and Tooltips share label rendering cache
- Footer, Minimap, Command Panel all use `panelRect` and `FooterHeight`

---

## File Summary

| File | Lines | UI Components |
|------|-------|---------------|
| `src/renderer.nim` | 2600+ | Health bars, damage numbers, overlays, footer |
| `src/minimap.nim` | 191 | Minimap |
| `src/command_panel.nim` | 579 | Command buttons |
| `src/tooltips.nim` | 675 | Tooltip system |
| `src/common.nim` | 250+ | Layout constants |
| `src/constants.nim` | 600 | Game + UI constants |
| `tribal_village.nim` | 800+ | Input handling, main loop |
| `tests/behavior_ui.nim` | 667 | UI state tests |
| `tests/ui_harness.nim` | 220+ | Test helpers |
