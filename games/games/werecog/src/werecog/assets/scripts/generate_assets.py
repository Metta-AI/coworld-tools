#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


@dataclass(frozen=True)
class Palette:
    outline: tuple[int, int, int, int] = (25, 18, 28, 255)
    villager_a: tuple[int, int, int, int] = (214, 188, 124, 255)
    villager_b: tuple[int, int, int, int] = (95, 131, 184, 255)
    werewolf_a: tuple[int, int, int, int] = (78, 76, 110, 255)
    werewolf_b: tuple[int, int, int, int] = (188, 62, 75, 255)
    station_a: tuple[int, int, int, int] = (131, 95, 72, 255)
    station_b: tuple[int, int, int, int] = (208, 172, 108, 255)
    moon: tuple[int, int, int, int] = (236, 221, 147, 255)
    bell: tuple[int, int, int, int] = (232, 170, 70, 255)
    fire_a: tuple[int, int, int, int] = (255, 176, 74, 255)
    fire_b: tuple[int, int, int, int] = (214, 88, 40, 255)
    ground_a: tuple[int, int, int, int] = (78, 104, 66, 255)
    ground_b: tuple[int, int, int, int] = (101, 76, 52, 255)
    sky_top: tuple[int, int, int, int] = (34, 42, 74, 255)
    sky_bottom: tuple[int, int, int, int] = (119, 94, 84, 255)
    mist: tuple[int, int, int, int] = (214, 224, 238, 56)
    profile_bg: tuple[int, int, int, int] = (30, 32, 42, 255)


ORIENTATIONS = ("n", "s", "e", "w")
ROLE_SOURCE_NAMES = {
    "villager": "gatherer",
    "werewolf": "wolf",
}
SOURCE_ART_SIZE = 192
OBJECT_SIZE = 192
ICON_SIZE = 64
MINIMAP_SIZE = 32
RESOURCE_SIZE = 64
BACKGROUND_SIZE = 768
GROUND_TILE_SIZE = 256


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _data_root() -> Path:
    return _repo_root() / "generated" / "mettascope-data"


def _source_root() -> Path:
    return Path(__file__).resolve().parents[1] / "source"


def _canvas(size: int) -> Image.Image:
    return Image.new("RGBA", (size, size), (0, 0, 0, 0))


def _source_image(name: str, size: int, *, tint: tuple[int, int, int], brightness: float, color: float) -> Image.Image:
    source_path = _source_root() / name
    assert source_path.exists(), f"Missing source asset {source_path}"
    image = Image.open(source_path).convert("RGBA")
    assert image.size == (SOURCE_ART_SIZE, SOURCE_ART_SIZE), (
        f"Expected {source_path.name} to be {SOURCE_ART_SIZE}x{SOURCE_ART_SIZE}, got {image.width}x{image.height}"
    )
    image = image.resize((size, size), Image.NEAREST)
    image = ImageEnhance.Color(image).enhance(color)
    image = ImageEnhance.Brightness(image).enhance(brightness)
    tinted = Image.blend(image, Image.new("RGBA", image.size, (*tint, 255)), 0.18)
    tinted.putalpha(image.getchannel("A"))
    return tinted


def _source_oriented_image(
    name: str,
    orient: str,
    size: int,
    *,
    tint: tuple[int, int, int],
    brightness: float,
    color: float,
) -> Image.Image:
    return _source_image(f"{name}.{orient}.png", size, tint=tint, brightness=brightness, color=color)


def _ground_shadow(size: int, *, alpha: int = 78) -> Image.Image:
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    d.ellipse(
        [int(size * 0.18), int(size * 0.73), int(size * 0.82), int(size * 0.92)],
        fill=(16, 18, 24, alpha),
    )
    return img.filter(ImageFilter.GaussianBlur(radius=max(1.2, size / 48)))


def _draw_agent(role: str, orient: str, size: int, palette: Palette) -> Image.Image:
    img = _canvas(size)
    img.alpha_composite(_ground_shadow(size, alpha=84 if role == "villager" else 72))

    sprite_size = int(size * (0.92 if role == "villager" else 0.9))
    sprite = _source_oriented_image(
        ROLE_SOURCE_NAMES[role],
        orient,
        sprite_size,
        tint=(236, 214, 190) if role == "villager" else (182, 192, 218),
        brightness=1.04 if role == "villager" else 0.94,
        color=1.04 if role == "villager" else 0.92,
    )
    x = (size - sprite_size) // 2
    y = size - sprite_size - (4 if role == "villager" else 2)
    img.alpha_composite(sprite, (x, y))

    return img


def _draw_dead_agent(orient: str, size: int, palette: Palette) -> Image.Image:
    img = _draw_agent("villager", orient, size, palette)
    veil = Image.new("RGBA", img.size, (44, 18, 26, 128))
    img.alpha_composite(veil)
    d = ImageDraw.Draw(img)
    d.line((34, 34, size - 34, size - 34), fill=(58, 12, 18, 255), width=26)
    d.line((size - 34, 34, 34, size - 34), fill=(58, 12, 18, 255), width=26)
    d.line((34, 34, size - 34, size - 34), fill=(238, 62, 70, 255), width=14)
    d.line((size - 34, 34, 34, size - 34), fill=(238, 62, 70, 255), width=14)
    return img


def _draw_villager_station(size: int, palette: Palette) -> Image.Image:
    img = _source_image("town_center.png", size, tint=(126, 102, 74), brightness=0.9, color=0.82)
    d = ImageDraw.Draw(img)
    for window in ((42, 104, 70, 132), (122, 104, 150, 132), (82, 112, 110, 146)):
        d.rectangle(window, fill=(255, 214, 136, 96))
    d.ellipse([18, 150, size - 18, size - 10], fill=(28, 30, 38, 60))
    return img


def _draw_werewolf_station(size: int, palette: Palette) -> Image.Image:
    img = _source_image("goblin_hut.png", size, tint=(66, 64, 86), brightness=0.82, color=0.62)
    d = ImageDraw.Draw(img)
    cx = size // 2
    d.pieslice([cx - 40, 30, cx + 40, 110], start=35, end=325, fill=palette.moon, outline=palette.outline, width=3)
    d.ellipse([cx - 16, 36, cx + 24, 116], fill=(58, 55, 94, 255), outline=(58, 55, 94, 255))
    d.rectangle([76, 118, 116, 144], fill=(206, 72, 72, 64))
    d.ellipse([18, 150, size - 18, size - 10], fill=(18, 20, 26, 74))
    return img


def _draw_meeting_bell(size: int, palette: Palette) -> Image.Image:
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    cx = size // 2
    d.rectangle([cx - 52, 68, cx + 52, 88], fill=(110, 82, 52, 255), outline=palette.outline, width=4)
    d.rectangle([cx - 8, 68, cx + 8, 144], fill=(96, 70, 48, 255), outline=palette.outline, width=4)
    d.pieslice([cx - 38, 80, cx + 38, 156], start=180, end=360, fill=palette.bell, outline=palette.outline, width=4)
    d.ellipse([cx - 12, 124, cx + 12, 148], fill=(188, 122, 40, 255), outline=palette.outline, width=3)
    fire = [(cx - 34, 156), (cx - 10, 112), (cx + 0, 150), (cx + 18, 98), (cx + 34, 156)]
    d.polygon(fire, fill=palette.fire_a, outline=palette.outline)
    inner_fire = [(cx - 16, 156), (cx - 2, 126), (cx + 8, 152), (cx + 18, 120), (cx + 24, 156)]
    d.polygon(inner_fire, fill=palette.fire_b)
    d.rectangle([cx - 42, 156, cx + 42, 170], fill=(74, 58, 46, 255), outline=palette.outline, width=3)
    return img


def _draw_tree(size: int, palette: Palette) -> Image.Image:
    img = _source_image("tree.png", size, tint=(72, 86, 118), brightness=0.84, color=0.92)
    d = ImageDraw.Draw(img)
    d.ellipse([22, 146, size - 22, size - 8], fill=(28, 30, 38, 60))
    d.rectangle([86, 128, 106, 174], fill=(78, 60, 42, 255), outline=palette.outline, width=3)
    return img


def _draw_cottage(size: int, palette: Palette) -> Image.Image:
    img = _source_image("house.png", size, tint=(112, 92, 70), brightness=0.9, color=0.78)
    d = ImageDraw.Draw(img)
    d.rectangle([42, 128, 70, 152], fill=(255, 208, 128, 86))
    d.rectangle([122, 128, 150, 152], fill=(255, 208, 128, 86))
    d.ellipse([18, 150, size - 18, size - 10], fill=(28, 30, 38, 56))
    return img


def _draw_lantern(size: int, palette: Palette) -> Image.Image:
    img = _source_image("lantern.png", size, tint=(138, 96, 56), brightness=0.94, color=0.84)
    d = ImageDraw.Draw(img)
    d.ellipse([48, 92, 144, 178], fill=(255, 210, 128, 48))
    d.ellipse([62, 108, 130, 170], fill=(255, 218, 148, 82))
    d.rectangle([88, 30, 104, 176], fill=(86, 62, 42, 255), outline=palette.outline, width=2)
    d.ellipse([18, 156, size - 18, size - 10], fill=(18, 20, 26, 54))
    return img


def _draw_background_sky(size: int, palette: Palette) -> Image.Image:
    img = Image.new("RGBA", (size, size), palette.sky_top)
    pixels = img.load()
    for y in range(size):
        blend = y / max(1, size - 1)
        r = int(palette.sky_top[0] * (1.0 - blend) + palette.sky_bottom[0] * blend)
        g = int(palette.sky_top[1] * (1.0 - blend) + palette.sky_bottom[1] * blend)
        b = int(palette.sky_top[2] * (1.0 - blend) + palette.sky_bottom[2] * blend)
        for x in range(size):
            pixels[x, y] = (r, g, b, 255)
    d = ImageDraw.Draw(img)
    d.ellipse([size - 172, 38, size - 92, 118], fill=palette.moon, outline=(0, 0, 0, 0))
    d.ellipse([size - 146, 44, size - 74, 124], fill=(58, 60, 92, 255), outline=(0, 0, 0, 0))
    treeline = []
    for x in range(-32, size + 64, 64):
        treeline.extend([(x, size), (x + 22, size - 120), (x + 44, size)])
    d.polygon(treeline, fill=(28, 28, 34, 255))
    return img.filter(ImageFilter.GaussianBlur(radius=0.4))


def _draw_mist_overlay(size: int, palette: Palette) -> Image.Image:
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    for top in (int(size * 0.54), int(size * 0.66), int(size * 0.78)):
        d.ellipse([-80, top, size + 80, top + 120], fill=palette.mist)
    return img.filter(ImageFilter.GaussianBlur(radius=5.5))


def _draw_ground_tile(size: int, palette: Palette) -> Image.Image:
    img = Image.new("RGBA", (size, size), palette.ground_a)
    d = ImageDraw.Draw(img)
    for row in range(0, size, 16):
        offset = (row // 16) % 2 * 8
        d.rectangle([offset, row, min(size, offset + size), row + 7], fill=(86, 108, 72, 255))
    for index in range(0, size, 20):
        d.ellipse([index - 8, 18, index + 18, 34], fill=(92, 118, 76, 255))
        d.ellipse([size - index - 20, 120, size - index + 6, 138], fill=palette.ground_b)
    for x in range(12, size, 36):
        d.line((x, size - 26, x + 24, size - 6), fill=(116, 94, 64, 180), width=7)
    for y in range(26, size, 40):
        d.line((0, y, size, y + 6), fill=(104, 84, 58, 90), width=4)
    return img.filter(ImageFilter.GaussianBlur(radius=0.45))


def _draw_resource(name: str, size: int, palette: Palette) -> Image.Image:
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    if name == "alive":
        d.ellipse([8, 8, size - 8, size - 8], fill=(90, 188, 110, 255), outline=palette.outline, width=4)
        d.polygon(
            [(size // 2, 16), (size - 16, size // 2), (size // 2, size - 16), (16, size // 2)],
            fill=(160, 236, 176, 255),
            outline=palette.outline,
        )
    elif name == "vote_token":
        d.ellipse([8, 8, size - 8, size - 8], fill=(86, 136, 228, 255), outline=palette.outline, width=4)
        d.rectangle([size // 2 - 5, 16, size // 2 + 5, size - 16], fill=(245, 245, 255, 255))
        d.rectangle([16, size // 2 - 5, size - 16, size // 2 + 5], fill=(245, 245, 255, 255))
    elif name == "day_phase":
        d.ellipse([10, 10, size - 10, size - 10], fill=(244, 196, 76, 255), outline=palette.outline, width=4)
        for dx, dy in ((0, -18), (0, 18), (-18, 0), (18, 0), (-13, -13), (13, 13), (-13, 13), (13, -13)):
            d.line((size // 2, size // 2, size // 2 + dx, size // 2 + dy), fill=(255, 226, 120, 255), width=4)
    elif name == "night_phase":
        d.ellipse([8, 8, size - 8, size - 8], fill=(58, 55, 94, 255), outline=palette.outline, width=4)
        d.pieslice(
            [16, 14, size - 12, size - 10],
            start=35,
            end=325,
            fill=palette.moon,
            outline=palette.outline,
            width=3,
        )
        d.ellipse([28, 18, size - 8, size - 2], fill=(58, 55, 94, 255), outline=(58, 55, 94, 255))
    elif name == "day_vote_open":
        d.rounded_rectangle([10, 10, size - 10, size - 10], radius=12, fill=(54, 126, 214, 255), outline=palette.outline, width=4)
        d.rectangle([18, 18, size - 18, size - 18], fill=(208, 226, 255, 60))
        d.rectangle([size // 2 - 5, 16, size // 2 + 5, size - 16], fill=(248, 248, 255, 255))
        d.rectangle([16, size // 2 - 5, size - 16, size // 2 + 5], fill=(248, 248, 255, 255))
    elif name == "night_hunt_open":
        d.rounded_rectangle([10, 10, size - 10, size - 10], radius=12, fill=(142, 54, 70, 255), outline=palette.outline, width=4)
        d.polygon([(18, size - 18), (size // 2 - 6, 18), (size - 18, size - 18)], fill=(240, 214, 188, 255), outline=palette.outline)
        d.line((size // 2 - 10, 24, size // 2 + 12, size - 22), fill=(92, 22, 30, 255), width=5)
    elif name == "accusation":
        d.ellipse([8, 8, size - 8, size - 8], fill=(186, 82, 66, 255), outline=palette.outline, width=4)
        d.polygon(
            [
                (22, size - 18),
                (42, size // 2 + 4),
                (size - 14, 18),
                (size - 18, 34),
                (46, size // 2 + 18),
                (30, size - 14),
            ],
            fill=(236, 214, 188, 255),
            outline=palette.outline,
        )
    elif name == "suspicion":
        d.ellipse([8, 8, size - 8, size - 8], fill=(232, 88, 86, 255), outline=palette.outline, width=4)
        d.polygon(
            [(size // 2, 14), (size - 14, size - 14), (14, size - 14)],
            fill=(255, 206, 88, 255),
            outline=palette.outline,
        )
        d.rectangle([size // 2 - 3, size // 2 - 8, size // 2 + 3, size // 2 + 10], fill=(90, 42, 24, 255))
        d.rectangle([size // 2 - 3, size // 2 + 14, size // 2 + 3, size // 2 + 18], fill=(90, 42, 24, 255))
    elif name == "villager":
        d.ellipse([8, 8, size - 8, size - 8], fill=palette.villager_b, outline=palette.outline, width=4)
        sprite = _draw_agent("villager", "s", size - 12, palette)
        img.alpha_composite(sprite, (6, 6))
    elif name == "werewolf":
        d.ellipse([8, 8, size - 8, size - 8], fill=palette.werewolf_a, outline=palette.outline, width=4)
        sprite = _draw_agent("werewolf", "s", size - 12, palette)
        img.alpha_composite(sprite, (6, 6))
    return img


def _profile_from(sprite: Image.Image, palette: Palette) -> Image.Image:
    width, height = 169, 219
    profile = Image.new("RGBA", (width, height), palette.profile_bg)
    pixels = profile.load()
    for y in range(height):
        blend = y / max(1, height - 1)
        r = int(palette.profile_bg[0] * (1.0 - blend) + palette.sky_bottom[0] * blend)
        g = int(palette.profile_bg[1] * (1.0 - blend) + palette.sky_bottom[1] * blend)
        b = int(palette.profile_bg[2] * (1.0 - blend) + palette.sky_bottom[2] * blend)
        for x in range(width):
            pixels[x, y] = (r, g, b, 255)
    d = ImageDraw.Draw(profile)
    d.rectangle([0, int(height * 0.76), width, height], fill=(38, 44, 38, 255))
    d.ellipse([width - 52, 18, width - 20, 50], fill=(244, 226, 164, 255))
    d.ellipse([width - 42, 16, width - 10, 48], fill=palette.sky_top)
    profile.alpha_composite(_ground_shadow(width, alpha=54), (0, 26))
    preview = sprite.resize((132, 132), Image.NEAREST)
    profile.alpha_composite(preview, ((width - 132) // 2, 30))
    frame = ImageDraw.Draw(profile)
    frame.rounded_rectangle([8, 8, width - 9, height - 9], radius=12, outline=(72, 76, 96, 255), width=3)
    return profile


def _save(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _write_object_asset(name: str, image: Image.Image, data_root: Path, palette: Palette) -> None:
    _save(image, data_root / "objects" / f"{name}.png")
    _save(
        image.resize((ICON_SIZE, ICON_SIZE), Image.NEAREST),
        data_root / "icons" / "objects" / f"{name}.png",
    )
    _save(
        image.resize((MINIMAP_SIZE, MINIMAP_SIZE), Image.NEAREST),
        data_root / "minimap" / f"{name}.png",
    )
    _save(_profile_from(image, palette), data_root / "profiles" / f"{name}.png")


def build_assets(data_root: Path) -> None:
    palette = Palette()

    objects = {
        "werewolf_mafia_tree": _draw_tree(OBJECT_SIZE, palette),
        "werewolf_mafia_cottage": _draw_cottage(OBJECT_SIZE, palette),
        "werewolf_mafia_lantern": _draw_lantern(OBJECT_SIZE, palette),
        "werewolf_mafia_villager_station": _draw_villager_station(OBJECT_SIZE, palette),
        "werewolf_mafia_werewolf_station": _draw_werewolf_station(OBJECT_SIZE, palette),
        "werewolf_mafia_meeting_bell": _draw_meeting_bell(OBJECT_SIZE, palette),
    }

    for name, image in objects.items():
        _write_object_asset(name, image, data_root, palette)

    for role in ("villager", "werewolf"):
        base_name = f"werewolf_mafia_{role}"
        for orient in ORIENTATIONS:
            sprite = _draw_agent(role, orient, OBJECT_SIZE, palette)
            _save(sprite, data_root / "agents" / f"{base_name}.{orient}.png")
            if orient == "s":
                _save(
                    sprite.resize((ICON_SIZE, ICON_SIZE), Image.NEAREST),
                    data_root / "icons" / "agents" / f"{base_name}.png",
                )
                _save(
                    sprite.resize((MINIMAP_SIZE, MINIMAP_SIZE), Image.NEAREST),
                    data_root / "minimap" / f"{base_name}.png",
                )
                _save(_profile_from(sprite, palette), data_root / "profiles" / f"{base_name}.png")

    for orient in ORIENTATIONS:
        sprite = _draw_dead_agent(orient, OBJECT_SIZE, palette)
        _save(sprite, data_root / "agents" / f"werewolf_mafia_dead.{orient}.png")
        if orient == "s":
            _save(
                sprite.resize((ICON_SIZE, ICON_SIZE), Image.NEAREST),
                data_root / "icons" / "agents" / "werewolf_mafia_dead.png",
            )
            _save(
                sprite.resize((MINIMAP_SIZE, MINIMAP_SIZE), Image.NEAREST),
                data_root / "minimap" / "werewolf_mafia_dead.png",
            )
            _save(_profile_from(sprite, palette), data_root / "profiles" / "werewolf_mafia_dead.png")

    resource_names = (
        "alive",
        "vote_token",
        "day_phase",
        "night_phase",
        "day_vote_open",
        "night_hunt_open",
        "accusation",
        "suspicion",
    )
    for resource_name in resource_names:
        _save(
            _draw_resource(resource_name, RESOURCE_SIZE, palette),
            data_root / "resources" / f"{resource_name}.png",
        )

    _save(
        _draw_background_sky(BACKGROUND_SIZE, palette),
        data_root / "backgrounds" / "werewolf_mafia_sky.png",
    )
    _save(
        _draw_mist_overlay(BACKGROUND_SIZE, palette),
        data_root / "backgrounds" / "werewolf_mafia_mist.png",
    )
    _save(
        _draw_ground_tile(GROUND_TILE_SIZE, palette),
        data_root / "terrain" / "repeating.werewolf_mafia_ground.png",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic Werecog mettascope assets.")
    parser.add_argument(
        "--data-root",
        default=_data_root().as_posix(),
        help="Path to mettascope data directory.",
    )
    args = parser.parse_args()

    data_root = Path(args.data_root)
    build_assets(data_root)
    print(f"Generated Werecog assets in {data_root}")


if __name__ == "__main__":
    main()
