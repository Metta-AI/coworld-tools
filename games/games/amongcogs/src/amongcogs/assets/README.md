# Among Us Asset Pipeline

This is an Among Us-scoped copy of the Tribal Village asset generator workflow.

For this branch, prefer original/generated art under `packages/mettagrid/nim/mettascope/data/amongus/` over directly
checking in downloaded official Among Us art. That keeps the asset set namespaced, reproducible, and safe to iterate.

## What It Generates

- terrain splat stamps under `packages/mettagrid/nim/mettascope/data/amongus/terrain/`
- object sprites under `packages/mettagrid/nim/mettascope/data/amongus/objects/`
- derived minimap/profile sprites under `packages/mettagrid/nim/mettascope/data/amongus/{minimap,profiles}/`
- shared vibe icons under `packages/mettagrid/nim/mettascope/data/vibe/`

Prompts live in:

- `metta/games/among_us/assets/prompts/assets.tsv`

## Requirements

- `google-genai` Python package
- Google auth:
  - `GOOGLE_API_KEY`, or
  - ADC (`gcloud auth application-default login`)

## Run

`generate_assets.py` defaults `--out-dir` to
`packages/mettagrid/nim/mettascope/data/amongus`.

Generate terrain stamps:

```bash
python metta/games/among_us/assets/scripts/generate_assets.py \
  --only terrain/repeating.among_us.png,terrain/stamp.among_us_wiring.png,terrain/stamp.among_us_reactor.png,terrain/stamp.among_us_navigation.png,terrain/stamp.among_us_oxygen.png,terrain/stamp.among_us_crew.png,terrain/stamp.among_us_impostor.png \
  --size 512 \
  --postprocess \
  --postprocess-purple-bg \
  --project "$(gcloud config get-value project)"
```

Generate object sprites:

```bash
python metta/games/among_us/assets/scripts/generate_assets.py \
  --only objects/among_us_crew_station.png,objects/among_us_impostor_station.png,objects/among_us_wiring_station.png,objects/among_us_reactor_station.png,objects/among_us_navigation_station.png,objects/among_us_oxygen_station.png \
  --size 64 \
  --postprocess \
  --postprocess-purple-bg \
  --project "$(gcloud config get-value project)"
```

Quota-safe resume mode (recommended for large batches):

```bash
python metta/games/among_us/assets/scripts/generate_assets.py \
  --only objects/among_us_crew_station.png,objects/among_us_impostor_station.png,objects/among_us_wiring_station.png,objects/among_us_reactor_station.png,objects/among_us_navigation_station.png,objects/among_us_oxygen_station.png \
  --model gemini-2.5-flash-image \
  --size 64 \
  --postprocess \
  --postprocess-purple-bg \
  --max-retries 4 \
  --retry-delay 10 \
  --skip-existing \
  --continue-on-error \
  --project "$(gcloud config get-value project)"
```

Generate vibe icon:

```bash
python metta/games/among_us/assets/scripts/generate_assets.py \
  --only vibe/junction.png \
  --size 32 \
  --postprocess \
  --postprocess-purple-bg \
  --project "$(gcloud config get-value project)"
```

Then rebuild the Mettascope atlases:

```bash
cd packages/mettagrid/nim/mettascope
nim r tools/gen_atlas.nim
```

Derive UI-specific station icons (prevents minimap/profile unknown fallbacks):

```bash
python metta/games/among_us/assets/scripts/derive_ui_assets.py
cd packages/mettagrid/nim/mettascope
nim r tools/gen_atlas.nim
```

`derive_ui_assets.py` writes:
- primary UI sprites named after Among Us render assets (for example `among_us_navigation_station.png`)
- canonical type-name aliases (`navigation_station.png`, `oxygen_station.png`, etc.) so renderer fallback paths never hit `unknown`.
