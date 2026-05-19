"""Build pixel-art sprites for the euchre game.

Card faces (24 face cards) come from Byron Knoll's public-domain SVG deck via
the notpeter/Vector-Playing-Cards mirror, rendered small via cairosvg and then
NEAREST-upscaled to give the chunky pixel-art look the rest of the mettagrid
sprite atlas uses.

Card back, hand-slot placeholder, play-slot placeholder, and the central
controller marker are drawn procedurally with Pillow (no upstream sources).

Run: `uv run --with cairosvg --with pillow python tools/build_card_sprites.py`
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw

REPO_BASE = "https://raw.githubusercontent.com/notpeter/Vector-Playing-Cards/master/cards-svg"
RANKS = ["9", "10", "J", "Q", "K", "A"]
SUITS = ["H", "D", "C", "S"]

SPRITE_SIZE = 128
SMALL_HEIGHT = 64  # render height before NEAREST upscale (chunkier = lower)
CARD_ASPECT = 5 / 7  # poker card width:height

OUT_DIR = Path(__file__).resolve().parent.parent / "src/cogame_euchre/assets/objects"


def fetch_svg(rank: str, suit: str) -> bytes:
    url = f"{REPO_BASE}/{rank}{suit}.svg"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.read()


def render_card(svg: bytes) -> Image.Image:
    small_w = max(1, round(SMALL_HEIGHT * CARD_ASPECT))
    png = cairosvg.svg2png(bytestring=svg, output_width=small_w, output_height=SMALL_HEIGHT)
    small = Image.open(io.BytesIO(png)).convert("RGBA")

    big_h = SPRITE_SIZE
    big_w = max(1, round(big_h * CARD_ASPECT))
    big = small.resize((big_w, big_h), Image.NEAREST)

    canvas = Image.new("RGBA", (SPRITE_SIZE, SPRITE_SIZE), (0, 0, 0, 0))
    canvas.paste(big, ((SPRITE_SIZE - big_w) // 2, 0), big)
    return canvas


PIXEL = 4  # one "pixel" = PIXEL screen px (matches NEAREST chunkiness of cards)


def _card_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw, int, int]:
    big_h = SPRITE_SIZE
    big_w = max(1, round(big_h * CARD_ASPECT))
    small_w = big_w // PIXEL
    small_h = big_h // PIXEL
    small = Image.new("RGBA", (small_w, small_h), (0, 0, 0, 0))
    return small, ImageDraw.Draw(small), big_w, big_h


def _finalize(small: Image.Image, big_w: int, big_h: int) -> Image.Image:
    big = small.resize((big_w, big_h), Image.NEAREST)
    canvas = Image.new("RGBA", (SPRITE_SIZE, SPRITE_SIZE), (0, 0, 0, 0))
    canvas.paste(big, ((SPRITE_SIZE - big_w) // 2, 0), big)
    return canvas


def render_back() -> Image.Image:
    small, draw, big_w, big_h = _card_canvas()
    sw, sh = small.size
    bg = (140, 30, 30, 255)
    fg = (220, 200, 160, 255)
    draw.rectangle((0, 0, sw - 1, sh - 1), fill=bg, outline=(40, 10, 10, 255))
    for y in range(2, sh - 2):
        for x in range(2, sw - 2):
            if (x + y) % 2 == 0:
                small.putpixel((x, y), fg)
    return _finalize(small, big_w, big_h)


def render_card_slot() -> Image.Image:
    small, draw, big_w, big_h = _card_canvas()
    sw, sh = small.size
    border = (90, 90, 110, 200)
    draw.rectangle((0, 0, sw - 1, sh - 1), outline=border)
    for x in range(2, sw - 2, 2):
        small.putpixel((x, 0), border)
        small.putpixel((x, sh - 1), border)
    for y in range(2, sh - 2, 2):
        small.putpixel((0, y), border)
        small.putpixel((sw - 1, y), border)
    return _finalize(small, big_w, big_h)


def render_play_slot() -> Image.Image:
    small, draw, big_w, big_h = _card_canvas()
    sw, sh = small.size
    border = (200, 180, 80, 220)
    fill = (200, 180, 80, 40)
    draw.rectangle((0, 0, sw - 1, sh - 1), fill=fill, outline=border)
    draw.rectangle((1, 1, sw - 2, sh - 2), outline=border)
    return _finalize(small, big_w, big_h)


def render_controller() -> Image.Image:
    small_size = SPRITE_SIZE // PIXEL
    small = Image.new("RGBA", (small_size, small_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(small)
    cx = cy = small_size // 2
    r = small_size // 2 - 2
    body = (60, 60, 80, 255)
    rim = (220, 220, 230, 255)
    stripe = (200, 70, 70, 255)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=body, outline=rim)
    draw.rectangle((cx - r + 1, cy - 1, cx + r - 1, cy + 1), fill=stripe)
    big = small.resize((SPRITE_SIZE, SPRITE_SIZE), Image.NEAREST)
    return big


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for rank in RANKS:
        for suit in SUITS:
            svg = fetch_svg(rank, suit)
            img = render_card(svg)
            out = OUT_DIR / f"card_{rank.lower()}{suit.lower()}.png"
            img.save(out)
            print(f"  {out.name}")
    for name, fn in [
        ("card_back", render_back),
        ("card_slot", render_card_slot),
        ("play_slot", render_play_slot),
        ("controller", render_controller),
    ]:
        out = OUT_DIR / f"{name}.png"
        fn().save(out)
        print(f"  {out.name}")


if __name__ == "__main__":
    main()
