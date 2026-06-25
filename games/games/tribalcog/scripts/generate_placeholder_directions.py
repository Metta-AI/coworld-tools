#!/usr/bin/env python3
"""Generate placeholder direction sprites from the .s (south) sprite.

Uses simple image transformations to create approximate direction sprites.
These are placeholders - proper AI-generated sprites should replace them.
"""
from pathlib import Path
from PIL import Image

from script_paths import DATA_DIR
from sprite_transforms import apply_transforms

# Units that need direction sprites
CASTLE_UNIQUE_UNITS = [
    "cataphract",
    "huskarl",
    "janissary",
    "longbowman",
    "mameluke",
    "samurai",
    "teutonic_knight",
    "woad_raider",
]

# All 8 directions
DIRECTIONS = ["n", "s", "e", "w", "ne", "nw", "se", "sw"]

# Transformation mappings: what to do to create each direction from south
# For a top-down isometric view:
# - s = original (facing camera)
# - n = same as s (back view would need AI generation)
# - w = flip horizontal (facing left)
# - e = original (facing right, same as w but mirrored)
# - sw = same as s or slight modification
# - se = flip of sw
# - nw = same as n or slight modification
# - ne = flip of nw
DIRECTION_TRANSFORMS: dict[str, tuple[str, ...]] = {
    "n": ("copy",),
    "e": ("copy",),
    "w": ("flip_x",),
    "ne": ("copy",),
    "nw": ("flip_x",),
    "se": ("copy",),
    "sw": ("flip_x",),
}


def generate_placeholder(src_path: Path, dst_path: Path, direction: str) -> bool:
    """Generate a placeholder sprite for the given direction."""
    if dst_path.exists():
        return False  # Already exists

    if direction not in DIRECTION_TRANSFORMS:
        return False

    with Image.open(src_path) as img:
        img = img.convert("RGBA")
        result = apply_transforms(img, DIRECTION_TRANSFORMS[direction])

        result.save(dst_path)
        return True


def main() -> None:
    data_dir = DATA_DIR / "oriented"

    generated = 0
    skipped = 0

    for unit in CASTLE_UNIQUE_UNITS:
        src = data_dir / f"{unit}.s.png"
        if not src.exists():
            print(f"Warning: {unit}.s.png not found, skipping")
            continue

        for direction in DIRECTIONS:
            if direction == "s":
                continue  # Skip south, it's the source

            dst = data_dir / f"{unit}.{direction}.png"
            if generate_placeholder(src, dst, direction):
                print(f"Generated: {unit}.{direction}.png")
                generated += 1
            else:
                skipped += 1

    print(f"\nGenerated {generated} placeholder sprites, skipped {skipped} existing")


if __name__ == "__main__":
    main()
