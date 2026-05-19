#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from cliff_assets import CLIFF_PREVIEW_SPECS
from script_paths import DATA_DIR


SPRITE = tuple[str, Path, set[tuple[int, int]]]

DEFAULT_SPRITES: list[SPRITE] = [
    (label, DATA_DIR / relative_path, low_cells)
    for label, relative_path, low_cells in CLIFF_PREVIEW_SPECS
]


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = DATA_DIR / "Inter-Regular.ttf"
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


def parse_low_cells(raw: str) -> set[tuple[int, int]]:
    if not raw:
        return set()
    cells: set[tuple[int, int]] = set()
    for token in raw.replace("|", ";").split(";"):
        token = token.strip()
        if not token:
            continue
        if "," not in token:
            raise ValueError(f"Invalid low cell token '{token}', expected 'dx,dy'. sees examples: -1,0;0,1")
        dx_raw, dy_raw = token.split(",", 1)
        cells.add((int(dx_raw), int(dy_raw)))
    return cells


def load_manifest(path: Path) -> list[SPRITE]:
    sprites: list[SPRITE] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) not in (2, 3):
            raise ValueError(f"Invalid manifest line (expected 2-3 columns): {raw}")
        label = parts[0].strip()
        sprite_path = Path(parts[1].strip())
        low_cells = parse_low_cells(parts[2].strip()) if len(parts) == 3 else set()
        sprites.append((label, sprite_path, low_cells))
    return sprites


def label_from_path(path: Path) -> str:
    return path.stem.replace("_", " ").replace(".", " ")


def load_from_globs(patterns: list[str]) -> list[SPRITE]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = [Path(p) for p in glob.glob(pattern)]
        paths.extend(sorted(matches))
    sprites: list[SPRITE] = []
    for path in paths:
        sprites.append((label_from_path(path), path, set()))
    return sprites


def draw_grid(low_cells: set[tuple[int, int]], cell: int, padding: int) -> Image.Image:
    grid_size = cell * 3
    img = Image.new("RGBA", (grid_size + padding * 2, grid_size + padding * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    high_color = (210, 230, 200, 255)
    low_color = (120, 145, 110, 255)
    border = (30, 30, 30, 255)
    center_color = (240, 245, 235, 255)

    font = load_font(int(cell * 0.45))

    for row in range(3):
        for col in range(3):
            dx = col - 1
            dy = row - 1
            is_center = dx == 0 and dy == 0
            is_low = (dx, dy) in low_cells
            fill = center_color if is_center else (low_color if is_low else high_color)
            x0 = padding + col * cell
            y0 = padding + row * cell
            x1 = x0 + cell
            y1 = y0 + cell
            draw.rectangle([x0, y0, x1, y1], fill=fill, outline=border, width=1)
            label = "H" if is_center or not is_low else "L"
            bbox = draw.textbbox((0, 0), label, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            draw.text(
                (x0 + (cell - w) / 2, y0 + (cell - h) / 2 - 1),
                label,
                fill=(20, 20, 20, 255),
                font=font,
            )
    return img


def render_preview(
    output_path: Path,
    sprites: list[SPRITE],
    title: str,
    sprite_size: int,
    show_paths: bool,
) -> None:
    label_font = load_font(16)
    small_font = load_font(12)

    cell = 26
    padding = 4
    grid_img = draw_grid(set(), cell, padding)
    grid_w, grid_h = grid_img.size

    sprite_w = sprite_h = sprite_size
    row_height = max(sprite_h, grid_h) + 16
    label_width = 160
    gap = 16
    width = label_width + grid_w + gap + sprite_w + gap
    height = row_height * len(sprites) + 20

    canvas = Image.new("RGBA", (width, height), (15, 15, 15, 255))
    draw = ImageDraw.Draw(canvas)

    draw.text((12, 8), title, fill=(235, 235, 235, 255), font=label_font)

    y = 28
    for label, sprite_path, low_cells in sprites:
        row_top = y
        # label
        draw.text((12, row_top + 6), label, fill=(235, 235, 235, 255), font=label_font)
        if show_paths:
            draw.text(
                (12, row_top + 26),
                sprite_path.as_posix(),
                fill=(150, 150, 150, 255),
                font=small_font,
            )

        # grid
        grid_img = draw_grid(low_cells, cell, padding)
        grid_x = label_width
        grid_y = row_top + (row_height - grid_img.size[1]) // 2
        canvas.paste(grid_img, (grid_x, grid_y), grid_img)

        # sprite
        sprite_x = label_width + grid_w + gap
        sprite_y = row_top + (row_height - sprite_h) // 2
        if sprite_path.exists():
            sprite = Image.open(sprite_path).convert("RGBA")
            if sprite.size != (sprite_w, sprite_h):
                sprite = sprite.resize((sprite_w, sprite_h), Image.NEAREST)
            canvas.paste(sprite, (sprite_x, sprite_y), sprite)
        else:
            draw.rectangle(
                [sprite_x, sprite_y, sprite_x + sprite_w, sprite_y + sprite_h],
                outline=(200, 80, 80, 255),
                width=2,
            )
            draw.text(
                (sprite_x + 8, sprite_y + 8),
                "missing",
                fill=(200, 80, 80, 255),
                font=label_font,
            )

        y += row_height

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render an asset preview sheet with a 3x3 grid and sprite column."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DATA_DIR / "tmp" / "asset_preview.png",
        help="Output path for the preview image.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Optional TSV: label<TAB>path<TAB>low_cells (dx,dy;dx,dy).",
    )
    parser.add_argument(
        "--glob",
        action="append",
        default=[],
        help="Glob pattern for sprite paths (repeatable).",
    )
    parser.add_argument(
        "--title",
        type=str,
        help="Custom preview title.",
    )
    parser.add_argument(
        "--sprite-size",
        type=int,
        default=200,
        help="Sprite render size (default: 200).",
    )
    parser.add_argument(
        "--no-paths",
        action="store_true",
        help="Hide sprite file paths under labels.",
    )
    args = parser.parse_args()
    if args.manifest:
        sprites = load_manifest(args.manifest)
        title = args.title or f"Asset Preview ({args.manifest.as_posix()})"
    elif args.glob:
        sprites = load_from_globs(args.glob)
        title = args.title or "Asset Preview (Glob)"
    else:
        sprites = DEFAULT_SPRITES
        title = args.title or "Asset Preview (Cliff Set)"

    if not sprites:
        raise SystemExit("No sprites found to render.")

    render_preview(
        args.out,
        sprites,
        title,
        sprite_size=args.sprite_size,
        show_paths=not args.no_paths,
    )


if __name__ == "__main__":
    main()
