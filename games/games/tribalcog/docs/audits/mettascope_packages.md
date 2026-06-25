# Mettascope Package Dependencies Audit

Comparison of mettascope's Nim dependencies with tribal_village, focusing on treeform-authored packages.

## Summary

| Status | Count |
|--------|-------|
| Shared packages | 11 |
| Missing from tribal_village | 8 |
| tribal_village only | 0 |

## Direct Dependencies

### mettascope.nimble
```nim
requires "nim >= 2.2.4"
requires "cligen >= 1.9.0"    # CLI parser
requires "fidget2 >= 0.1.2"   # UI framework
requires "genny >= 0.1.1"     # FFI bindings generator
```

### tribal_village.nimble
```nim
requires "nim >= 2.2.4"
requires "vmath >= 2.0.0"
requires "chroma >= 0.2.7"
requires "boxy"
requires "windy"
```

## Full Dependency Comparison

### Treeform Packages

| Package | mettascope | tribal_village | Purpose |
|---------|------------|----------------|---------|
| vmath | 2.0.1 | 2.0.1 | Vector/matrix math |
| chroma | 1.0.0 | 1.0.0 | Color manipulation |
| boxy | 0.7.0 | 0.7.0 | 2D graphics batching (OpenGL) |
| windy | 0.4.4 | 0.4.4 | Cross-platform window management |
| pixie | 5.1.0 | 5.1.0 | 2D graphics/image processing |
| shady | 0.1.4 | 0.1.4 | GLSL shader DSL |
| flatty | 0.3.4 | 0.3.4 | Binary serialization |
| bumpy | 1.1.3 | 1.1.3 | Collision detection (AABB, circles) |
| bitty | 0.1.4 | 0.1.4 | Bit manipulation |
| urlly | 1.1.1 | 1.1.1 | URL parsing |
| ws | 0.5.0 | 0.5.0 | WebSocket client |
| **fidget2** | 0.1.2 | - | Immediate-mode UI framework |
| **genny** | 0.1.1 | - | FFI bindings generator |
| **jsony** | 1.1.5 | - | Fast JSON serialization |
| **puppy** | 2.1.2 | - | Simple HTTP client |
| **silky** | 0.0.1 | - | UI toolkit with atlas/9-patch support |
| **webby** | 0.2.1 | - | HTTP client with async support |

### Guzba Packages

| Package | mettascope | tribal_village | Purpose |
|---------|------------|----------------|---------|
| zippy | 0.10.16 | 0.10.16 | zlib/gzip compression |
| nimsimd | 1.3.2 | 1.3.2 | SIMD intrinsics |
| crunchy | 0.1.11 | 0.1.11 | SIMD-optimized algorithms |
| **supersnappy** | 2.1.3 | - | Snappy compression |

### Other Packages

| Package | mettascope | tribal_village | Purpose |
|---------|------------|----------------|---------|
| opengl | 1.2.9 | 1.2.9 | OpenGL bindings |
| **cligen** | 1.9.3 | - | CLI argument parsing |
| **libcurl** | 1.0.0 | - | libcurl bindings |

## Silky vs Boxy

**boxy** is a low-level 2D graphics batching library that sits on top of OpenGL. It handles:
- Sprite batching
- Texture atlas management
- Efficient draw call batching

**silky** is a higher-level UI toolkit that uses boxy underneath. It provides:
- 9-patch rendering for scalable UI elements
- Atlas-based sprite management with JSON metadata
- Mouse interaction helpers
- UI state management

From `mettascope.nim:276-277`:
```nim
sk = newSilky(dataDir / "silky.atlas.png", dataDir / "silky.atlas.json")
bxy = newBoxy()
```

Mettascope uses both:
- `bxy` (boxy) for world rendering
- `sk` (silky) for UI panels, buttons, and HUD elements

**tribal_village currently uses boxy for all rendering.** Adding silky would be beneficial if tribal_village needs structured UI elements with 9-patch scaling, atlas-based widgets, or consistent UI theming.

## Recommendations

### Priority 1: Consider Adding

| Package | Rationale |
|---------|-----------|
| **silky** | If tribal_village needs UI panels, menus, or HUD elements beyond basic sprites. Provides 9-patch scaling and atlas-based UI. |
| **jsony** | Faster than std/json. Useful for config files or replay data. |

### Priority 2: Add If Needed

| Package | Rationale |
|---------|-----------|
| **genny** | Only needed if generating Python/C bindings. mettascope uses it for its Python bindings. |
| **cligen** | Only if tribal_village needs CLI argument parsing beyond nimble tasks. |
| **puppy/webby** | Only if tribal_village needs HTTP fetching (e.g., remote replays). |
| **fidget2** | Full immediate-mode UI framework. May be overkill if silky suffices. |

### Not Recommended

| Package | Rationale |
|---------|-----------|
| **libcurl** | puppy is simpler. Only use libcurl for complex HTTP needs. |
| **supersnappy** | zippy already provides compression. Snappy is only faster for specific workloads. |

## Breaking Changes to Expect

All treeform packages use semantic versioning. Since tribal_village already uses the same versions as mettascope for shared packages, no breaking changes are expected when adding new packages.

Note: silky 0.0.1 indicates early development. API may change. Review usage in mettascope before adopting.

## Files Examined

- `/home/relh/gt/metta/mayor/rig/packages/mettagrid/nim/mettascope/mettascope.nimble`
- `/home/relh/gt/metta/mayor/rig/packages/mettagrid/nim/mettascope/nimby.lock`
- `/home/relh/gt/metta/mayor/rig/packages/mettagrid/nim/mettascope/src/mettascope.nim`
- `/home/relh/gt/tribal_village/polecats/furiosa/tribal_village/tribal_village.nimble`
- `/home/relh/gt/tribal_village/polecats/furiosa/tribal_village/nimby.lock`
