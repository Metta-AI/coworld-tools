#!/usr/bin/env python3
"""Generate Cogshambo pixel-art sprites with Retro Diffusion on Replicate.

Adapted from metta-ai/metta tools/gen_sprite.py at commit
104d3d15a851442dc28e03fe30c26d0055e41f0c.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = REPO_ROOT / "public" / "assets" / "cogshambo"

CATEGORY_DEFAULTS = {
    "cogs": {"size": (192, 192), "style_plus": "character_turnaround", "style_fast": "character_turnaround"},
    "agents": {"size": (192, 192), "style_plus": "character_turnaround", "style_fast": "character_turnaround"},
    "objects": {"size": (128, 128), "style_plus": "default", "style_fast": "game_asset"},
    "resources": {"size": (64, 64), "style_plus": "item_sheet", "style_fast": "item_sheet"},
    "terrain": {"size": (512, 512), "style_plus": "topdown_map", "style_fast": "texture"},
    "icons": {"size": (64, 64), "style_plus": "ui_element", "style_fast": "ui"},
    "actions": {"size": (64, 64), "style_plus": "skill_icon", "style_fast": "game_asset"},
}

MODEL_IDS = {
    "rd-plus": "retro-diffusion/rd-plus",
    "rd-fast": "retro-diffusion/rd-fast",
    "rd-animation": "retro-diffusion/rd-animation",
    "rd-tile": "retro-diffusion/rd-tile",
}

ANIMATION_STYLE_SIZES = {
    "four_angle_walking": (48, 48),
    "walking_and_idle": (48, 48),
    "small_sprites": (32, 32),
    "vfx": (48, 48),
}
ANIMATION_DEFAULT_STYLE = "four_angle_walking"


def parse_size(size_str: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", size_str.lower())
    if not match:
        raise argparse.ArgumentTypeError("size must be formatted as WxH, for example 192x192")
    return int(match.group(1)), int(match.group(2))


def slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "_", value.lower()).strip("._-")
    return slug[:60] or "sprite"


def resolve_output_dir(output_dir: str | None, category: str) -> Path:
    if output_dir:
        path = Path(output_dir).expanduser()
        return path if path.is_absolute() else REPO_ROOT / path
    return ASSET_DIR / category


def get_generation_config(args: argparse.Namespace) -> tuple[str, int, int]:
    cat_defaults = CATEGORY_DEFAULTS[args.category]

    if args.model == "rd-animation":
        style = args.style or ANIMATION_DEFAULT_STYLE
        width, height = args.size or ANIMATION_STYLE_SIZES.get(style, (48, 48))
        return style, width, height

    width, height = args.size or cat_defaults["size"]
    if args.style:
        style = args.style
    elif args.model == "rd-tile":
        style = "tileset"
    elif args.model == "rd-plus":
        style = cat_defaults["style_plus"]
    else:
        style = cat_defaults["style_fast"]
    return style, width, height


def read_replicate_output(file_output: Any) -> bytes:
    if hasattr(file_output, "read"):
        return file_output.read()
    if isinstance(file_output, bytes):
        return file_output
    if isinstance(file_output, bytearray):
        return bytes(file_output)

    output_url = str(file_output)
    if output_url.startswith("http://") or output_url.startswith("https://"):
        with urlopen(output_url) as response:
            return response.read()

    raise TypeError(f"Unsupported Replicate output type: {type(file_output).__name__}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Cogshambo pixel-art sprites")
    parser.add_argument("description", help="Text description of the sprite to generate")
    parser.add_argument("--model", default="rd-plus", choices=MODEL_IDS.keys(), help="Retro Diffusion model")
    parser.add_argument("--style", default=None, help="Style preset; auto-selected if omitted")
    parser.add_argument("--size", type=parse_size, default=None, help="Image dimensions, for example 192x192")
    parser.add_argument("--category", default="cogs", choices=CATEGORY_DEFAULTS.keys(), help="Asset category")
    parser.add_argument("--name", default=None, help="Output filename without extension")
    parser.add_argument("--no-remove-bg", action="store_true", help="Keep background")
    parser.add_argument("--tile-x", action="store_true", help="Enable seamless X tiling")
    parser.add_argument("--tile-y", action="store_true", help="Enable seamless Y tiling")
    parser.add_argument("--palette", default=None, help="Path to palette image")
    parser.add_argument("--num", type=int, default=1, help="Number of variants")
    parser.add_argument("--seed", type=int, default=None, help="Seed for reproducibility")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    parser.add_argument("--dry-run", action="store_true", help="Print generation settings without calling Replicate")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    style, width, height = get_generation_config(args)
    output_dir = resolve_output_dir(args.output_dir, args.category)
    base_name = slugify_filename(args.name or args.description)

    input_params: dict[str, Any] = {
        "prompt": args.description,
        "style": style,
        "width": width,
        "height": height,
    }

    if args.model not in ("rd-animation", "rd-tile"):
        input_params["remove_bg"] = not args.no_remove_bg
    if args.model != "rd-animation" and args.num > 1:
        input_params["num_images"] = args.num
    if args.model == "rd-animation":
        input_params["return_spritesheet"] = True
    if args.tile_x:
        input_params["tile_x"] = True
    if args.tile_y:
        input_params["tile_y"] = True
    if args.seed is not None:
        input_params["seed"] = args.seed

    palette_file = None
    if args.palette:
        palette_path = Path(args.palette).expanduser()
        if not palette_path.is_absolute():
            palette_path = REPO_ROOT / palette_path
        if not palette_path.exists():
            print(f"Error: Palette image not found: {palette_path}", file=sys.stderr)
            return 1
        palette_file = open(palette_path, "rb")
        input_params["input_palette"] = palette_file

    model_id = MODEL_IDS[args.model]
    print(f"Generating with {model_id}")
    print(f"  Prompt: {args.description}")
    print(f"  Style: {style}")
    print(f"  Size: {width}x{height}")
    print(f"  Category: {args.category}")
    print(f"  Output: {output_dir}")
    if "remove_bg" in input_params:
        print(f"  Remove BG: {input_params['remove_bg']}")

    if args.dry_run:
        if palette_file:
            palette_file.close()
        print("\nDry run complete; Replicate was not called.")
        return 0

    if not os.environ.get("REPLICATE_API_TOKEN"):
        if palette_file:
            palette_file.close()
        print("Error: REPLICATE_API_TOKEN environment variable not set.", file=sys.stderr)
        print("Get a token at https://replicate.com/account/api-tokens", file=sys.stderr)
        return 1

    try:
        import replicate
    except ImportError:
        if palette_file:
            palette_file.close()
        print("Error: Python package 'replicate' is not installed.", file=sys.stderr)
        print("Install it with: python3 -m pip install replicate", file=sys.stderr)
        return 1

    try:
        output = replicate.run(model_id, input=input_params)
    finally:
        if palette_file:
            palette_file.close()

    if not isinstance(output, list):
        output = [output]

    output_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    for index, file_output in enumerate(output):
        suffix = f"_{index + 1}" if len(output) > 1 else ""
        output_path = output_dir / f"{base_name}{suffix}.png"
        output_path.write_bytes(read_replicate_output(file_output))
        saved_paths.append(output_path)
        print(f"  Saved: {output_path}")
        if output_path.is_relative_to(REPO_ROOT / "public"):
            public_path = output_path.relative_to(REPO_ROOT / "public")
            print(f"  URL: /{public_path.as_posix()}")

    print(f"\nGenerated {len(saved_paths)} sprite(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
