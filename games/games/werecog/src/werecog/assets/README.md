# Werecog Assets

This folder contains the reproducible asset pipeline for Werecog.

## Generate assets

```bash
uv run python src/werecog/assets/scripts/generate_assets.py
```

By default this writes generated sprites into `generated/mettascope-data/` inside this repo.
If you want to update an upstream `mettagrid` checkout directly, pass its Mettascope data directory explicitly:

```bash
uv run python src/werecog/assets/scripts/generate_assets.py \
  --data-root /path/to/mettagrid/nim/mettascope/data
```

## Rebuild atlases upstream

After copying generated art into `mettagrid`, rebuild the atlas there:

```bash
( cd /path/to/mettagrid/nim/mettascope && ./tools/gen_atlas )
```

## Notes

- The script is deterministic and does not require external API keys.
- Prompt templates are kept in `assets/prompts/assets.tsv` for future model-based regeneration.
- Asset keys still use the historical `werewolf_mafia_*` prefix until the upstream render contracts are renamed.
