#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw
from script_paths import METTASCOPE_AMONGUS_DATA_DIR

TYPE_NAME_ALIASES = {
    "among_us_admin_station": "admin_station",
    "among_us_comms_station": "comms_station",
    "among_us_crew_station": "crew_station",
    "among_us_emergency_button": "emergency_button",
    "among_us_impostor_station": "impostor_station",
    "among_us_lights_station": "lights_station",
    "among_us_medbay_station": "medbay_station",
    "among_us_wiring_station": "wiring_station",
    "among_us_reactor_station": "reactor_station",
    "among_us_navigation_station": "navigation_station",
    "among_us_oxygen_station": "oxygen_station",
    "among_us_security_station": "security_station",
    "among_us_shields_station": "shields_station",
    "among_us_weapons_station": "weapons_station",
}


def _tight_crop(img: Image.Image) -> Image.Image:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return img
    return img.crop(bbox)


def _render_minimap(src: Path, dst: Path, size: int) -> None:
    with Image.open(src) as source:
        icon = _tight_crop(source.convert("RGBA"))

    inner = max(8, int(round(size * 0.82)))
    icon = icon.resize((inner, inner), Image.Resampling.NEAREST)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - inner) // 2
    y = (size - inner) // 2
    canvas.alpha_composite(icon, (x, y))

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst)


def _render_profile(src: Path, dst: Path, width: int, height: int) -> None:
    with Image.open(src) as source:
        icon = _tight_crop(source.convert("RGBA"))

    # Shared card background to keep station profiles visually unified.
    bg_top = ImageColor.getrgb("#1A243D")
    bg_bottom = ImageColor.getrgb("#0E1324")
    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(bg_top[0] * (1.0 - t) + bg_bottom[0] * t)
        g = int(bg_top[1] * (1.0 - t) + bg_bottom[1] * t)
        b = int(bg_top[2] * (1.0 - t) + bg_bottom[2] * t)
        draw.line((0, y, width, y), fill=(r, g, b, 255))

    border = ImageColor.getrgb("#5C7CB8")
    inset = ImageColor.getrgb("#202D4D")
    draw.rectangle((0, 0, width - 1, height - 1), outline=border + (255,), width=3)
    draw.rectangle((6, 6, width - 7, height - 7), outline=inset + (255,), width=2)

    target = int(round(min(width, height) * 0.64))
    icon = icon.resize((target, target), Image.Resampling.NEAREST)
    x = (width - target) // 2
    y = int(round(height * 0.16))
    card.alpha_composite(icon, (x, y))

    dst.parent.mkdir(parents=True, exist_ok=True)
    card.save(dst)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Derive minimap/profile assets from Among Us station object sprites.")
    parser.add_argument(
        "--objects-dir",
        default=(METTASCOPE_AMONGUS_DATA_DIR / "objects").as_posix(),
        help="Directory containing among_us_*_station object sprites.",
    )
    parser.add_argument(
        "--minimap-dir",
        default=(METTASCOPE_AMONGUS_DATA_DIR / "minimap").as_posix(),
        help="Output minimap sprite directory.",
    )
    parser.add_argument(
        "--profiles-dir",
        default=(METTASCOPE_AMONGUS_DATA_DIR / "profiles").as_posix(),
        help="Output profile sprite directory.",
    )
    parser.add_argument("--minimap-size", type=int, default=33)
    parser.add_argument("--profile-width", type=int, default=169)
    parser.add_argument("--profile-height", type=int, default=219)
    parser.add_argument(
        "--write-type-aliases",
        action="store_true",
        default=True,
        help="Also copy sprites to canonical station type names (crew_station, wiring_station, ...).",
    )
    parser.add_argument(
        "--no-write-type-aliases",
        dest="write_type_aliases",
        action="store_false",
        help="Skip writing canonical type-name aliases.",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated asset base names (without .png). Default: all among_us_*_station sprites.",
    )
    return parser.parse_args()


def _iter_asset_names(objects_dir: Path, only: set[str] | None) -> list[str]:
    if only:
        return sorted(only)
    names: list[str] = []
    for png in sorted(objects_dir.glob("among_us_*.png")):
        names.append(png.stem)
    return names


def main() -> None:
    args = _parse_args()
    objects_dir = Path(args.objects_dir)
    minimap_dir = Path(args.minimap_dir)
    profiles_dir = Path(args.profiles_dir)
    only = {v.strip() for v in args.only.split(",") if v.strip()} or None

    asset_names = _iter_asset_names(objects_dir, only)
    if not asset_names:
        raise SystemExit("No among_us station object sprites found to derive UI assets from.")

    for name in asset_names:
        source = objects_dir / f"{name}.png"
        if not source.exists():
            print(f"[skip] missing object sprite {source}")
            continue

        minimap_target = minimap_dir / f"{name}.png"
        profile_target = profiles_dir / f"{name}.png"
        _render_minimap(source, minimap_target, size=args.minimap_size)
        _render_profile(source, profile_target, width=args.profile_width, height=args.profile_height)
        print(f"[derive] {name} -> {minimap_target.name}, {profile_target.name}")

        if args.write_type_aliases and name in TYPE_NAME_ALIASES:
            alias = TYPE_NAME_ALIASES[name]
            object_alias = objects_dir / f"{alias}.png"
            minimap_alias = minimap_dir / f"{alias}.png"
            profile_alias = profiles_dir / f"{alias}.png"
            shutil.copyfile(source, object_alias)
            shutil.copyfile(minimap_target, minimap_alias)
            shutil.copyfile(profile_target, profile_alias)
            print(f"[alias] {name} -> {alias}")


if __name__ == "__main__":
    main()
