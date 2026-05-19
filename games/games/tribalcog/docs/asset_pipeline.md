# Asset Pipeline and Oriented Sprites

Date: 2026-02-06
Owner: Docs / Art Systems
Status: Active

## Purpose
Codex sessions repeatedly hit issues around missing sprites, incorrect orientations, and
post-processing artifacts. This doc captures the current asset pipeline, how oriented
sprites are generated, and the knobs that control cleanup.

## Asset Locations
- `data/*.png` : primary map + inventory sprites
- `data/oriented/*.png` : directional unit and edge sprites
- `data/ui/*.png` : UI-only assets
- `data/prompts/assets.tsv` : prompt source of truth
- `data/tmp/` : raw generations (kept for inspection)

## Prompt File Format
`data/prompts/assets.tsv` is TSV with 2 or 3 columns:
1. output filename (relative to `data/`)
2. prompt text
3. optional flags (comma-separated key=value pairs)

Examples:
- `barracks.png<TAB>...prompt...`
- `oriented/builder.{dir}.png<TAB>...prompt with {orientation}...<TAB>orient=unit`

Notes:
- Use `{dir}` in the filename to request oriented output.
- Use `{orientation}` (or `{dir}`) in the prompt to insert orientation text.
- `orient=unit` uses unit directions; `orient=edge` uses cliff edge directions.

## Orientation Sets
Defined in `scripts/asset_prompt_rows.py` (consumed by `scripts/generate_assets.py`):
- `unit`: n, s, e, w, ne, nw, se, sw
- `edge`: ew, ew_s, ns, ns_w

The unit orientation text is explicit about left/right facing (for example, `se` is
"looking left" and `sw` is "looking right") to avoid flipped sprites. East/west
mirroring is also supported for stable prompts via `FLIP_ORIENTATIONS`.

Cliff-specific constants and automatic cliff variant derivation are centralized in
`scripts/cliff_assets.py` (used by `generate_assets.py`, preview rendering, and audit scripts).
Shared transform operations live in `scripts/sprite_transforms.py`, and shared repo/data
path resolution for script entrypoints lives in `scripts/script_paths.py`.
Prompt/orientation row parsing lives in `scripts/asset_prompt_rows.py`, and image background
key/crop postprocessing helpers live in `scripts/asset_postprocess.py`.

## Generation Commands
Base assets:
- `python scripts/generate_assets.py --postprocess`

Oriented assets (default reference dir is `s`):
- `python scripts/generate_assets.py --oriented --postprocess --postprocess-purple-bg`

Limit to specific outputs:
- `python scripts/generate_assets.py --oriented --only oriented/builder.{dir}.png --postprocess`

Postprocess only (reuse `data/tmp`):
- `python scripts/generate_assets.py --postprocess-only --postprocess-tol 30`

## Postprocessing Pipeline
`apply_postprocess` in `scripts/asset_postprocess.py` performs:
1. Background removal (standard flood-fill or purple key).
2. Content crop using alpha connected components.
3. Resize to the requested square size.

Useful flags:
- `--postprocess-tol` adjusts chroma-key tolerance (default 35).
- `--postprocess-purple-bg` removes solid purple backgrounds before other steps.
- `--postprocess-purple-to-white` replaces purple highlights for team tinting.

## Preview Sheets
Use `render_asset_preview.py` to visually verify oriented or special assets:
- Default (cliff preview):
  `python scripts/render_asset_preview.py`
- Custom manifest (TSV):
  `python scripts/render_asset_preview.py --manifest path/to/manifest.tsv`
- Custom glob:
  `python scripts/render_asset_preview.py --glob 'data/oriented/*.png'`

Previews render a 3x3 grid with a sprite column to verify orientation and edge alignment.

## Size and Conventions
- Most item/building sprites are **256x256** with transparent backgrounds.
- Terrain tiles are top-down, full-tile coverage, and typically opaque.
- Cliff overlays commonly use **200x200** sprites.
- Oriented sprites live in `data/oriented/` and follow `{dir}` naming.

## Asset Audit (Updated 2026-02-11)

### Status: All Assets Present

**522 PNG sprites** covering all game entities. Zero missing, zero orphaned.

Previous issues (bear/wolf/cow 2-direction, mud.png, shallow_water.png) are all resolved.

### UnitClassSpriteKeys — Upgrade Unit Sprites

As of 2026-02-11, all 23 upgrade-tier units use their own dedicated sprites in
`UnitClassSpriteKeys` (renderer.nim). Previously they fell back to base-tier sprites.

| Upgrade Chain | Units with Dedicated Sprites |
|---|---|
| Infantry | man_at_arms -> long_swordsman -> champion |
| Cavalry | scout -> light_cavalry -> hussar |
| Archer | archer -> crossbowman -> arbalester |
| Heavy Cavalry | knight -> cavalier -> paladin |
| Camel | camel -> heavy_camel -> imperial_camel |
| Ranged | skirmisher -> elite_skirmisher |
| Mounted Ranged | cavalry_archer -> heavy_cavalry_archer |
| Gunpowder | janissary, hand_cannoneer |
| Siege | mangonel, scorpion |
| Naval | boat, galley, fire_ship, fishing_ship, transport_ship, demo_ship, cannon_galleon |

All sprites have 8 directional variants (n/s/e/w/ne/nw/se/sw).

### Art Quality Notes

When generating new unit sprites or updating existing ones:

1. **Upgrade tiers should look visually distinct.** Each upgrade sprite should show
   progression (heavier armor, different weapons, more ornate gear). Verify by comparing
   the base and upgrade sprites side-by-side.
2. **Orientation consistency matters.** All 8 directions for a unit should be consistent
   in pose, equipment, and color palette. Use the preview sheet to verify.
3. **Team tinting compatibility.** Sprites should have neutral/white highlights that
   accept team color tinting via the `tint` parameter in `bxy.drawImage()`.

### Sprite Coverage by Category

| Category | Count | Status |
|---|---|---|
| Base unit sprites (8 dirs each) | 21 types = 168 files | Complete |
| Upgrade unit sprites (8 dirs each) | 23 types = 184 files | Complete |
| Unique unit sprites (civ-specific) | 9 types = 72 files | Complete |
| Villager roles (gatherer/builder/fighter) | 3 types = 24 files | Complete |
| Animals (bear/wolf/cow, 8 dirs) | 3 types = 24 files | Complete |
| Buildings | 27 types = 27 files | Complete |
| Terrain | 10 types = 10 files | Complete |
| Items/Resources | 15 types = 15 files | Complete |
| Walls (oriented, 17 configs) | 18 files | Complete |
| Cliffs (edges + corners) | 12 files | Complete |
| Tumors (active + expired, 4 dirs) | 8 files | Complete |
| Trebuchet (packed + unpacked, 8 dirs) | 16 files | Complete |
| UI controls | 6 files | Complete |
| **Total** | **522 PNG files** | **Complete** |

### Finding Missing Assets

To audit assets vs code definitions:

```bash
# List all oriented sprite bases
ls data/oriented/*.n.png | sed 's/.*oriented\///' | sed 's/\.n\.png//' | sort

# List sprite keys referenced in registry
grep 'oriented/' src/registry.nim

# Check UnitClassSpriteKeys mapping
grep -A50 'UnitClassSpriteKeys' src/renderer.nim

# Cross-reference: count per-unit direction files
for unit in $(ls data/oriented/*.n.png | sed 's/.*oriented\///' | sed 's/\.n\.png//'); do
  echo "$unit: $(ls data/oriented/${unit}.*.png | wc -l) files"
done
```

## Authentication Setup

The `generate_assets.py` script requires Google Cloud authentication:

### Option A: API Key (Simplest)
```bash
export GOOGLE_API_KEY=your_api_key_here
```
Get a key from: https://makersuite.google.com/app/apikey

### Option B: Application Default Credentials (ADC)
```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

### Option C: Vertex AI (Enterprise)
```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
gcloud auth application-default login
```

## Troubleshooting Checklist
1. Confirm the prompt row exists in `data/prompts/assets.tsv`.
2. Verify the output file is in `data/` or `data/oriented/`.
3. Inspect raw output under `data/tmp/` if postprocessing fails.
4. Adjust `--postprocess-tol` and rerun `--postprocess-only`.
5. Use the preview sheet to spot misaligned orientation or transparency artifacts.
