---
name: cg.gen-sprite
description: Generate Cogshambo or Mettascope-style pixel art sprites using Retro Diffusion on Replicate
args:
  <description> [--model rd-plus|rd-fast|rd-animation|rd-tile] [--style STYLE] [--size WxH] [--category
  cogs|agents|objects|resources|terrain|icons|actions] [--name filename]
---

# Generate Cogshambo Sprite

Generate pixel art sprites with `tools/gen_sprite.py`.

Source: copied and adapted from `metta-ai/metta` `skills/cg.gen-sprite` and `tools/gen_sprite.py` at commit
`104d3d15a851442dc28e03fe30c26d0055e41f0c`.

## Prerequisites

- `REPLICATE_API_TOKEN` is set.
- The Python `replicate` package is installed, or run through `uv` with `--with replicate`.

## Workflow

1. Parse the desired cog or game asset description and choose a category.
2. Prefer `--category cogs` for custom Cogshambo cog sprites.
3. Run `tools/gen_sprite.py` with an explicit `--name` so the generated file is stable.
4. Show the generated image to the user for review.
5. Generated files default to `public/assets/cogshambo/<category>`, which Vite serves at
   `/assets/cogshambo/<category>/<name>.png`.
6. If preparing a Mettascope-style directional agent strip, use `--model rd-animation --style four_angle_walking`.

## Command

```bash
uv run --with replicate python tools/gen_sprite.py "<description>" [options]
```

Key options:

| Flag                   | Default   | Notes                                                                  |
| ---------------------- | --------- | ---------------------------------------------------------------------- |
| `--model`              | `rd-plus` | `rd-plus`, `rd-fast`, `rd-animation`, `rd-tile`                        |
| `--category`           | `cogs`    | `cogs`, `agents`, `objects`, `resources`, `terrain`, `icons`, `actions` |
| `--style`              | auto      | style preset for the model                                             |
| `--size`               | auto      | `WxH`; cogs and agents default to `192x192`                            |
| `--name`               | auto      | output filename without extension                                      |
| `--num`                | `1`       | variants                                                               |
| `--seed`               | random    | reproducibility                                                        |
| `--palette`            | none      | match an existing sprite palette                                       |
| `--tile-x`, `--tile-y` | false     | seamless tiling                                                        |
| `--no-remove-bg`       | false     | keep background                                                        |
| `--output-dir`         | auto      | override output directory                                              |
| `--dry-run`            | false     | print settings without calling Replicate                               |

Common category defaults: cogs/agents `192x192`, objects `128x128`, resources/icons/actions `64x64`, terrain
`512x512`.

## Prompting Rules

- Ask for transparent background unless there is a deliberate reason not to.
- Keep the silhouette readable at board scale.
- For cog sprites, include the faction/personality cues, palette, facing direction, and key mechanical features.
- For frame strips, request the full strip in one generation call; do not generate individual animation frames one by
  one.

## Examples

```bash
uv run --with replicate python tools/gen_sprite.py \
  "brass debate cog with teal glass eye, readable top-down game sprite, transparent background" \
  --category cogs \
  --name brass_debate_cog

uv run --with replicate python tools/gen_sprite.py \
  "armored scout cog, four directional walking cycle, pixel art, transparent background" \
  --category agents \
  --model rd-animation \
  --style four_angle_walking \
  --name scout_cog_walk

uv run --with replicate python tools/gen_sprite.py \
  "glowing argument token, teal and amber, crisp pixel art icon" \
  --category icons \
  --name argument_token
```
