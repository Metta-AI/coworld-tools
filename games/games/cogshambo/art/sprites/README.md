# Sprite Sheet Specs

Save sprite descriptions as markdown files in this directory, then run:

```bash
npm run art:sheet -- art/sprites/cute-scout-cog.md
```

The command loads `REPLICATE_API_TOKEN` from `.env`, asks Retro Diffusion for either one complete animation sheet or a
set of still sprite options, normalizes the result into frames, renders a preview, and writes a `manifest.json`.

Default output:

```text
public/assets/cogshambo/sprite-sheets/<name>/
  <name>-sheet.png
  <name>-preview.png
  manifest.json
  frames/
    <name>-01.png
    <name>-02.png
```

## Spec Format

```markdown
---
name: cute-scout-cog
category: cogs
model: rd-animation
style: four_angle_walking
size: 48x48
frame_width: 48
frame_height: 48
columns: 4
seed: 5101
---

## Prompt

Cute mint scout cog with a round gear body, tiny smiling face, bright eyes, and readable teal silhouette.
Four-direction walking sprite sheet, transparent background, crisp pixel art.
```

Useful fields:

| Field | Default | Notes |
| --- | --- | --- |
| `name` | file stem | Stable output folder and filename prefix. |
| `model` | `rd-animation` | Use `rd-animation` for animation sheets and `rd-plus` for high-resolution still sprite options. |
| `style` | `four_angle_walking` | Retro Diffusion animation style. |
| `size` | `48x48` | Per-frame generation size for animation sheets. Cog-builder still options use `192x192`. |
| `frame_width` / `frame_height` | `size` | Used to slice the returned sheet. |
| `columns` / `rows` | inferred | Set when the sheet has padding or a fixed layout. |
| `variants` | `1` | For non-animation models, generate this many still sprite options and manifest each one as a frame. |
| `seed` | random | Set for reproducible generations. |
| `append_defaults` | `true` | Appends Cogshambo sprite-sheet invariants to the prompt. |

For a no-API smoke check against an existing sheet:

```bash
npm run art:sheet -- art/sprites/cute-scout-cog.md \
  --skip-generate \
  --sheet public/assets/cogshambo/cogs/cog-default.png \
  --output-dir /tmp/cogshambo-art-smoke
```
