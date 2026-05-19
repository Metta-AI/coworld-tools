#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance
from script_paths import ASSETS_ROOT, METTASCOPE_AMONGUS_DATA_DIR

DIRECTIONS = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
ROLES = ("crewmate", "impostor")
STATES = ("body", "discussion", "ballot", "vote_impostor", "vote_skip", "ejected")


def _scale_box(size: tuple[int, int], rel: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    width, height = size
    return (
        round(width * rel[0]),
        round(height * rel[1]),
        round(width * rel[2]),
        round(height * rel[3]),
    )


def _draw_badge(draw: ImageDraw.ImageDraw, size: tuple[int, int], fill: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    box = _scale_box(size, (0.62, 0.06, 0.94, 0.38))
    draw.ellipse(box, fill=fill, outline=(255, 255, 255, 255), width=max(2, size[0] // 48))
    return box


def _draw_discussion(draw: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    x1, y1, x2, y2 = _draw_badge(draw, size, (43, 200, 232, 230))
    w = x2 - x1
    h = y2 - y1
    draw.rectangle((x1 + w // 4, y1 + h // 3, x2 - w // 4, y1 + h // 2), fill=(8, 31, 50, 255))
    draw.polygon(
        [(x1 + w // 2, y1 + h // 2), (x1 + w // 2 + w // 8, y1 + h // 2), (x1 + w // 2, y1 + h * 2 // 3)],
        fill=(8, 31, 50, 255),
    )


def _draw_ballot(draw: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    x1, y1, x2, y2 = _draw_badge(draw, size, (140, 84, 255, 230))
    w = x2 - x1
    h = y2 - y1
    draw.rectangle((x1 + w // 3, y1 + h // 4, x2 - w // 3, y2 - h // 5), fill=(255, 255, 255, 255))
    draw.line((x1 + w // 3, y1 + h // 4, x2 - w // 3, y2 - h // 5), fill=(43, 27, 88, 255), width=max(2, size[0] // 64))


def _draw_vote_impostor(draw: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    x1, y1, x2, y2 = _draw_badge(draw, size, (231, 48, 72, 235))
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    r = max(3, (x2 - x1) // 5)
    width = max(2, size[0] // 48)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 255), width=width)
    draw.line((cx - r * 2, cy, cx + r * 2, cy), fill=(255, 255, 255, 255), width=width)
    draw.line((cx, cy - r * 2, cx, cy + r * 2), fill=(255, 255, 255, 255), width=width)


def _draw_vote_skip(draw: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    x1, y1, x2, y2 = _draw_badge(draw, size, (246, 206, 65, 235))
    width = max(3, size[0] // 32)
    y = (y1 + y2) // 2
    draw.line((x1 + width * 2, y, x2 - width * 2, y), fill=(28, 24, 12, 255), width=width)


def _draw_ejected(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    overlay = Image.new("RGBA", image.size, (34, 14, 28, 86))
    image.alpha_composite(overlay)
    width = max(5, image.size[0] // 24)
    box = _scale_box(image.size, (0.23, 0.18, 0.77, 0.72))
    draw.line((box[0], box[1], box[2], box[3]), fill=(239, 48, 64, 255), width=width)
    draw.line((box[0], box[3], box[2], box[1]), fill=(239, 48, 64, 255), width=width)


def _make_body(image: Image.Image) -> Image.Image:
    body = ImageEnhance.Brightness(image.rotate(90, resample=Image.Resampling.BICUBIC)).enhance(0.78)
    overlay = Image.new("RGBA", body.size, (22, 20, 28, 76))
    body.alpha_composite(overlay)
    draw = ImageDraw.Draw(body)
    box = _scale_box(body.size, (0.36, 0.15, 0.66, 0.47))
    width = max(3, body.size[0] // 48)
    draw.line(
        ((box[0] + box[2]) // 2, box[1], (box[0] + box[2]) // 2, box[3]),
        fill=(247, 248, 230, 255),
        width=width,
    )
    draw.line(
        (box[0], (box[1] + box[3]) // 2, box[2], (box[1] + box[3]) // 2),
        fill=(247, 248, 230, 255),
        width=width,
    )
    draw.line(
        (box[0], box[1], box[2], box[3]),
        fill=(47, 55, 70, 210),
        width=max(2, width // 2),
    )
    return body


def _decorate(source: Path, state: str, target: Path) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    if state == "body":
        image = _make_body(image)
    if state == "ejected":
        image = ImageEnhance.Brightness(image).enhance(0.7)
    draw = ImageDraw.Draw(image)
    if state == "discussion":
        _draw_discussion(draw, image.size)
    elif state == "ballot":
        _draw_ballot(draw, image.size)
    elif state == "vote_impostor":
        _draw_vote_impostor(draw, image.size)
    elif state == "vote_skip":
        _draw_vote_skip(draw, image.size)
    elif state == "ejected":
        _draw_ejected(image, draw)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, optimize=True)


def _parse_args() -> argparse.Namespace:
    local_data_dir = ASSETS_ROOT / "mettascope" / "data" / "amongus"
    default_data_dir = local_data_dir if local_data_dir.exists() else METTASCOPE_AMONGUS_DATA_DIR
    parser = argparse.ArgumentParser(description="Derive role-preserving meeting/vote agent sprites.")
    parser.add_argument("--data-dir", default=default_data_dir.as_posix())
    return parser.parse_args()


def main() -> None:
    data_dir = Path(_parse_args().data_dir)
    for role in ROLES:
        for state in STATES:
            asset_name = f"{state}_{role}"
            for direction in DIRECTIONS:
                _decorate(
                    data_dir / "agents" / f"{role}.{direction}.png",
                    state,
                    data_dir / "agents" / f"{asset_name}.{direction}.png",
                )
            _decorate(data_dir / "profiles" / f"{role}.png", state, data_dir / "profiles" / f"{asset_name}.png")
            _decorate(data_dir / "minimap" / f"{role}.png", state, data_dir / "minimap" / f"{asset_name}.png")
            print(f"[derive] {asset_name}")


if __name__ == "__main__":
    main()
