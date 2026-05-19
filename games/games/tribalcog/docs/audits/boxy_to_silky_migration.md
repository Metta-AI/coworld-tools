# Boxy to Silky Migration Audit

**Date:** 2026-02-11
**Author:** tribal_village/polecats/rictus
**Status:** Investigation Complete

## Executive Summary

This audit documents the changes required to migrate tribal_village from the [boxy](https://github.com/treeform/boxy) rendering library to [silky](https://github.com/treeform/silky). Mettascope has already completed this migration successfully, providing a reference implementation.

### Key Finding

The migration is **substantial** but achievable. The main challenges are:
1. Silky uses a static pre-built atlas vs boxy's dynamic runtime atlas
2. Silky has no built-in transform stack - requires custom implementation
3. Drawing API signatures differ significantly
4. Layer/blend mode support is more limited in silky

---

## 1. Files Requiring Changes

### Direct boxy imports (7 files)

| File | Role | Complexity |
|------|------|------------|
| `tribal_village.nimble` | Package deps | Low |
| `tribal_village.nim` | Main entry | High |
| `src/common.nim` | Global `bxy: Boxy` | High |
| `src/renderer.nim` | Rendering (~2000 lines) | Very High |
| `src/minimap.nim` | Minimap rendering | Medium |
| `src/tooltips.nim` | Tooltip rendering | Medium |
| `src/command_panel.nim` | Command panel UI | Medium |
| `tests/behavior_ui.nim` | UI tests | Low |

### Current dependency versions (nimby.lock)
```
boxy 0.7.0 https://github.com/treeform/boxy
windy 0.4.4 https://github.com/treeform/windy
pixie 5.1.0 https://github.com/treeform/pixie
```

---

## 2. API Differences

### 2.1 Initialization

**Boxy (current):**
```nim
import boxy
bxy = newBoxy()
bxy.addImage("key", readImage("path/to/image.png"))
```

**Silky (target):**
```nim
import silky
sk = newSilky("data/silky.atlas.png", "data/silky.atlas.json")
# Images must be pre-built into atlas - no runtime addImage
```

**Migration:** Requires building a static atlas from all PNG assets at build time. See mettascope's `data/silky.atlas.png` and `data/silky.atlas.json`.

### 2.2 Transform Stack

**Boxy (current):**
```nim
bxy.saveTransform()
bxy.translate(pos)
bxy.scale(vec2(zoom, zoom))
# ... drawing code uses bxy.getTransform()
bxy.restoreTransform()
```

**Silky (target):**
```nim
# Silky has NO built-in transform stack
# Must implement custom transform management
```

**Migration:** Mettascope implements a custom transform stack in `common.nim`:
```nim
var
  transformMat*: Mat3 = mat3()
  transformStack*: seq[Mat3]

proc saveTransform*() =
  transformStack.add(transformMat)

proc restoreTransform*() =
  transformMat = transformStack.pop()

proc getTransform*(): Mat3 =
  transformMat

proc translateTransform*(v: Vec2) =
  transformMat = transformMat * translate(v)

proc scaleTransform*(s: Vec2) =
  transformMat = transformMat * scale(s)
```

All world-space drawing must manually apply transforms before passing positions to silky.

### 2.3 Frame Lifecycle

**Boxy:**
```nim
bxy.beginFrame(window.size)
# ... drawing ...
bxy.endFrame()
window.swapBuffers()
```

**Silky:**
```nim
sk.beginUI(window, window.size)
# ... drawing ...
sk.endUI()
window.swapBuffers()
```

### 2.4 Drawing API

#### drawImage

**Boxy:**
```nim
bxy.drawImage("key", pos, angle = 0.0, scale = 1.0, tint = color(1,1,1,1))
bxy.drawImage("key", center, angle, tint, scale)  # rotated version
```

**Silky:**
```nim
sk.drawImage("key", pos, color = rgbx(255,255,255,255))
# NO rotation or scale - must be pre-computed!
```

**Migration:** All rotation and scaling must be pre-computed and applied to the position. Rotation is only achievable via pre-rotated atlas sprites.

#### drawRect

**Boxy:**
```nim
bxy.drawRect(Rect(x: 0, y: 0, w: 100, h: 50), color(1, 0, 0, 1))
```

**Silky:**
```nim
sk.drawRect(vec2(0, 0), vec2(100, 50), rgbx(255, 0, 0, 255))
```

#### Color Types

**Boxy:** Uses `Color` (float r,g,b,a 0.0-1.0)
**Silky:** Uses `ColorRGBX` (uint8 r,g,b,a 0-255)

### 2.5 Layer System

**Boxy:**
```nim
bxy.pushLayer()
# ... draw to layer ...
bxy.popLayer(blendMode = MaskBlend)  # or NormalBlend, ScreenBlend, etc.
```

**Silky:**
```nim
sk.pushLayer(NormalLayer)  # or PopupsLayer
sk.popLayer()
# Only 2 layers, limited blend modes
```

**Migration:** The mask layer technique used in tribal_village for viewport clipping will need an alternative approach (e.g., `glScissor` as mettascope uses).

---

## 3. Breaking Changes

### 3.1 Removed/Changed Functions

| Boxy Function | Silky Equivalent | Notes |
|---------------|-----------------|-------|
| `newBoxy()` | `newSilky(png, json)` | Requires pre-built atlas |
| `addImage(key, image)` | None | Must use atlas |
| `drawImage(..., angle, scale)` | `drawImage(..., color)` | No rotation/scale |
| `beginFrame(size)` | `beginUI(window, size)` | Different signature |
| `endFrame()` | `endUI()` | Same concept |
| `saveTransform()` | Custom impl | See section 2.2 |
| `restoreTransform()` | Custom impl | See section 2.2 |
| `translate(v)` | Custom impl | See section 2.2 |
| `scale(v)` | Custom impl | See section 2.2 |
| `rotate(angle)` | Not supported | Pre-rotate in atlas |
| `getTransform()` | Custom impl | See section 2.2 |
| `pushLayer()` | `pushLayer(int)` | Different API |
| `popLayer(blendMode)` | `popLayer()` | No blend modes |
| `flush()` | Not needed | Silky batches differently |

### 3.2 New Silky Features

| Feature | Description |
|---------|-------------|
| `draw9Patch()` | 9-slice drawing for scalable UI panels |
| `drawText()` | Built-in atlas-based text rendering |
| `drawQuad()` | Low-level quad drawing with UV control |
| `pushLayout()` / `popLayout()` | Layout stack for UI positioning |
| `pushClipRect()` / `popClipRect()` | Clipping rectangles |
| UI widgets | Various UI widget helpers |

---

## 4. Migration Checklist

### 4.1 Pre-Migration (Build System)

- [ ] Create atlas builder script for tribal_village sprites
- [ ] Generate `silky.atlas.png` and `silky.atlas.json`
- [ ] Include all oriented sprites (161+ variants)
- [ ] Include UI sprites, icons, tiles
- [ ] Add atlas generation to build pipeline

### 4.2 Dependencies (tribal_village.nimble)

```nim
# Remove:
requires "boxy"

# Add:
requires "silky >= 0.0.1"
```

### 4.3 Core Changes (src/common.nim)

- [ ] Replace `bxy*: Boxy` with `sk*: Silky`
- [ ] Add custom transform stack (see section 2.2)
- [ ] Add transform helper procs

### 4.4 Main Entry (tribal_village.nim)

- [ ] Replace `newBoxy()` with `newSilky(...)`
- [ ] Update `beginFrame` to `beginUI`
- [ ] Update `endFrame` to `endUI`
- [ ] Remove all `bxy.addImage()` calls (use atlas)
- [ ] Replace layer mask technique with glScissor

### 4.5 Renderer (src/renderer.nim)

This is the largest change - approximately 100+ call sites:

- [ ] Replace all `bxy.drawImage()` calls
  - Compute world-to-screen transform manually
  - Remove angle/scale parameters
  - Convert Color to ColorRGBX
- [ ] Replace all `bxy.drawRect()` calls
  - Update to `sk.drawRect(pos, size, color)` signature
- [ ] Replace transform stack usage
- [ ] Update dynamic image generation (labels, etc.)
  - Current: `bxy.addImage(key, ctx.image)`
  - New: Pre-render all text labels in atlas OR use `sk.drawText()`

### 4.6 UI Components

**src/minimap.nim:**
- [ ] Update drawing calls
- [ ] Replace transform usage

**src/tooltips.nim:**
- [ ] Replace `bxy.addImage()` for dynamic text labels
- [ ] Consider using `sk.drawText()` instead

**src/command_panel.nim:**
- [ ] Update drawing calls
- [ ] Replace transform usage

### 4.7 Tests

- [ ] Update `tests/behavior_ui.nim`

---

## 5. Compatibility

### 5.1 Can boxy and silky coexist?

**Yes**, but not recommended. Both libraries:
- Use OpenGL
- Manage their own state
- Have conflicting shader/texture management

Coexistence would require careful state management between the two, increasing complexity significantly.

### 5.2 Gradual Migration Strategy

A gradual migration is **not practical** because:
1. The global `bxy` is used throughout the codebase
2. Transform stack is incompatible
3. Atlas systems are fundamentally different

**Recommended approach:** Complete migration in a single branch.

---

## 6. Reference Implementation

Mettascope's migration provides a working reference:

**Key files to study:**
- `mettascope/src/mettascope.nim` - Main entry with silky initialization
- `mettascope/src/mettascope/common.nim` - Custom transform stack
- `mettascope/src/mettascope/worldmap.nim` - World rendering with transforms
- `mettascope/data/silky.atlas.png` - Pre-built atlas
- `mettascope/data/silky.atlas.json` - Atlas metadata

**Location in monorepo:**
```
/home/relh/gt/metta/refinery/rig/packages/mettagrid/nim/mettascope/
```

---

## 7. Effort Estimate

| Component | Files | Est. LOC Changes |
|-----------|-------|------------------|
| Build system (atlas) | 2-3 | 100-200 |
| Dependencies | 2 | 5 |
| Common/transform | 1 | 50-100 |
| Main entry | 1 | 50-100 |
| Renderer | 1 | 300-500 |
| Minimap | 1 | 50-100 |
| Tooltips | 1 | 50-100 |
| Command panel | 1 | 50-100 |
| Tests | 1 | 20-50 |
| **Total** | **~10** | **~700-1300** |

---

## 8. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Dynamic text labels | High | Use `sk.drawText()` or pre-render all text variations |
| Rotated sprites | Medium | Ensure all orientations are in atlas (already done for agents) |
| Layer blending | Medium | Use glScissor for clipping, redesign blend effects |
| Performance | Low | Silky is designed for efficient batched rendering |
| Atlas size limits | Low | Current assets are modest; monitor texture size |

---

## 9. Recommendations

1. **Start with atlas builder** - This is the foundational change that enables everything else
2. **Migrate common.nim first** - Establish the new patterns (transform stack, sk global)
3. **Migrate renderer.nim incrementally** - Break into logical chunks (floor, terrain, objects, UI)
4. **Keep mettascope open as reference** - Many patterns can be adapted directly
5. **Test WASM build** - Ensure emscripten compatibility is maintained

---

## 10. Appendix: API Quick Reference

### Silky Drawing API (from silky/drawing.nim)

```nim
# Initialization
proc newSilky*(imagePath, jsonPath: string): Silky

# Frame management
proc beginUI*(sk: Silky, window: Window, size: IVec2)
proc endUI*(sk: Silky)
proc clearScreen*(sk: Silky, color: ColorRGBX)

# Drawing
proc drawImage*(sk: Silky, name: string, pos: Vec2, color = rgbx(255,255,255,255))
proc drawRect*(sk: Silky, pos: Vec2, size: Vec2, color: ColorRGBX)
proc draw9Patch*(sk: Silky, name: string, patch: int, pos: Vec2, size: Vec2, color = rgbx(255,255,255,255))
proc drawQuad*(sk: Silky, pos, size, uvPos, uvSize: Vec2, color: ColorRGBX)
proc drawText*(sk: Silky, font: string, text: string, pos: Vec2, color: ColorRGBX, maxWidth, maxHeight: float32 = float32.high): Vec2

# Atlas queries
proc getImageSize*(sk: Silky, image: string): Vec2
proc getTextSize*(sk: Silky, font: string, text: string): Vec2
proc contains*(sk: Silky, name: string): bool

# Layout
proc pushLayout*(sk: Silky, pos, size: Vec2, direction: StackDirection = TopToBottom)
proc popLayout*(sk: Silky)
proc pos*(sk: Silky): Vec2
proc size*(sk: Silky): Vec2
proc advance*(sk: Silky, amount: Vec2)

# Clipping
proc pushClipRect*(sk: Silky, rect: Rect)
proc popClipRect*(sk: Silky)
proc clipRect*(sk: Silky): Rect

# Layers
proc pushLayer*(sk: Silky, layer: int)  # NormalLayer=0, PopupsLayer=1
proc popLayer*(sk: Silky)
```
