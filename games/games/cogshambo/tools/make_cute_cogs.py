#!/usr/bin/env python3
"""Generate the bundled Cogshambo builder sprite set."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal

from PIL import Image, ImageChops, ImageDraw, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
COGS_DIR = REPO_ROOT / "public" / "assets" / "cogshambo" / "cogs"
SHEETS_DIR = REPO_ROOT / "public" / "assets" / "cogshambo" / "sprite-sheets"

STARTER_KEYS = ["cog-ada", "cog-babbage", "cog-mira", "cog-default"]

BodyShape = Literal["round", "capsule", "square", "trapezoid", "hex", "bell", "wide"]
HeadShape = Literal["round", "oval", "square", "dome", "hex", "gear", "visor"]


SPRITES = [
    {
        "key": "cog-nova",
        "label": "Nova",
        "base": "#5dc8ff",
        "accent": "#ffbd54",
        "trim": "#265fa9",
        "head": "oval",
        "body": "capsule",
        "eyes": "wide",
        "chest": "sun",
        "antenna": "spark",
        "ears": "pods",
        "pose": "open",
    },
    {
        "key": "cog-orbit",
        "label": "Orbit",
        "base": "#78e56d",
        "accent": "#ff62cb",
        "trim": "#296343",
        "head": "round",
        "body": "round",
        "eyes": "happy",
        "chest": "orbit",
        "antenna": "halo",
        "ears": "hooks",
        "pose": "small",
    },
    {
        "key": "cog-sprocket",
        "label": "Sprocket",
        "base": "#48d987",
        "accent": "#6ce6ff",
        "trim": "#245c65",
        "head": "square",
        "body": "wide",
        "eyes": "visor",
        "chest": "sash",
        "antenna": "meter",
        "ears": "ticks",
        "pose": "straight",
    },
    {
        "key": "cog-lumen",
        "label": "Lumen",
        "base": "#4f8cff",
        "accent": "#70e9ff",
        "trim": "#27347c",
        "head": "visor",
        "body": "trapezoid",
        "eyes": "visor",
        "chest": "bolt",
        "antenna": "none",
        "ears": "fins",
        "pose": "wide",
    },
    {
        "key": "cog-pixel",
        "label": "Pixel",
        "base": "#fff263",
        "accent": "#ff65a7",
        "trim": "#6d5d26",
        "head": "square",
        "body": "square",
        "eyes": "wide",
        "chest": "heart",
        "antenna": "pixels",
        "ears": "tabs",
        "pose": "straight",
    },
    {
        "key": "cog-pearl",
        "label": "Pearl",
        "base": "#9ef7cf",
        "accent": "#e8fff6",
        "trim": "#2d776a",
        "head": "round",
        "body": "bell",
        "eyes": "sleepy",
        "chest": "gem",
        "antenna": "none",
        "ears": "cheeks",
        "pose": "small",
    },
    {
        "key": "cog-bolt",
        "label": "Bolt",
        "base": "#ffa837",
        "accent": "#58d4ff",
        "trim": "#8a4f19",
        "head": "dome",
        "body": "trapezoid",
        "eyes": "round",
        "chest": "bolt",
        "antenna": "wings",
        "ears": "horns",
        "pose": "wide",
    },
    {
        "key": "cog-echo",
        "label": "Echo",
        "base": "#6dd8ff",
        "accent": "#ff9547",
        "trim": "#285d85",
        "head": "round",
        "body": "round",
        "eyes": "round",
        "chest": "speaker",
        "antenna": "none",
        "ears": "loops",
        "pose": "open",
    },
    {
        "key": "cog-hex",
        "label": "Hex",
        "base": "#af72ff",
        "accent": "#62ff9e",
        "trim": "#51307e",
        "head": "hex",
        "body": "capsule",
        "eyes": "visor",
        "chest": "ring",
        "antenna": "none",
        "ears": "fins",
        "pose": "small",
    },
    {
        "key": "cog-juno",
        "label": "Juno",
        "base": "#ff7eb6",
        "accent": "#ffe25a",
        "trim": "#874166",
        "head": "dome",
        "body": "round",
        "eyes": "sleepy",
        "chest": "star",
        "antenna": "crest",
        "ears": "rings",
        "pose": "open",
    },
    {
        "key": "cog-kip",
        "label": "Kip",
        "base": "#75e8d2",
        "accent": "#b8ecff",
        "trim": "#236978",
        "head": "square",
        "body": "capsule",
        "eyes": "single",
        "chest": "shield",
        "antenna": "beacon",
        "ears": "tabs",
        "pose": "straight",
    },
    {
        "key": "cog-relay",
        "label": "Relay",
        "base": "#65a7ff",
        "accent": "#f8ef70",
        "trim": "#2e4d91",
        "head": "square",
        "body": "square",
        "eyes": "dots",
        "chest": "note",
        "antenna": "flag",
        "ears": "crescent",
        "pose": "small",
    },
    {
        "key": "cog-rook",
        "label": "Rook",
        "base": "#b7c7d6",
        "accent": "#ff8b4c",
        "trim": "#465766",
        "head": "square",
        "body": "trapezoid",
        "eyes": "round",
        "chest": "shield",
        "antenna": "pennant",
        "ears": "bolts",
        "pose": "straight",
    },
    {
        "key": "cog-servo",
        "label": "Servo",
        "base": "#52e6b5",
        "accent": "#5e94ff",
        "trim": "#23634e",
        "head": "gear",
        "body": "capsule",
        "eyes": "single",
        "chest": "ring",
        "antenna": "none",
        "ears": "wings",
        "pose": "wide",
    },
    {
        "key": "cog-spark",
        "label": "Spark",
        "base": "#ffd34d",
        "accent": "#52dcff",
        "trim": "#91672a",
        "head": "round",
        "body": "round",
        "eyes": "wide",
        "chest": "sun",
        "antenna": "propeller",
        "ears": "pods",
        "pose": "open",
    },
    {
        "key": "cog-toggle",
        "label": "Toggle",
        "base": "#9b82ff",
        "accent": "#69f3d1",
        "trim": "#4a3f83",
        "head": "square",
        "body": "round",
        "eyes": "switch",
        "chest": "toggle",
        "antenna": "dual",
        "ears": "pods",
        "pose": "small",
    },
]


def rgb(hex_color: str) -> tuple[int, int, int, int]:
    value = hex_color.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


def mix(a: tuple[int, int, int, int], b: tuple[int, int, int, int], t: float) -> tuple[int, int, int, int]:
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(4))  # type: ignore[return-value]


class Canvas:
    def __init__(self, scale: int = 4) -> None:
        self.scale = scale
        size = 192 * scale
        self.image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.image, "RGBA")

    def s(self, value: float) -> int:
        return round(value * self.scale)

    def box(self, values: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        return tuple(self.s(v) for v in values)  # type: ignore[return-value]

    def ellipse(self, box: tuple[float, float, float, float], fill, outline=None, width: int = 1) -> None:
        self.draw.ellipse(self.box(box), fill=fill, outline=outline, width=self.s(width))

    def rounded(self, box: tuple[float, float, float, float], radius: float, fill, outline=None, width: int = 1) -> None:
        self.draw.rounded_rectangle(self.box(box), radius=self.s(radius), fill=fill, outline=outline, width=self.s(width))

    def line(self, points: list[tuple[float, float]], fill, width: int = 1) -> None:
        self.draw.line([(self.s(x), self.s(y)) for x, y in points], fill=fill, width=self.s(width), joint="curve")

    def polygon(self, points: list[tuple[float, float]], fill, outline=None, width: int = 1) -> None:
        scaled = [(self.s(x), self.s(y)) for x, y in points]
        self.draw.polygon(scaled, fill=fill)
        if outline:
            self.draw.line(scaled + [scaled[0]], fill=outline, width=self.s(width), joint="curve")

    def glossy_fill(
        self,
        mask: Image.Image,
        bounds: tuple[float, float, float, float],
        base: tuple[int, int, int, int],
        shine: float = 0.3,
        shade: float = 0.46,
    ) -> None:
        left, top, right, bottom = self.box(bounds)
        width = max(1, right - left)
        height = max(1, bottom - top)
        light = mix(base, (255, 255, 255, 255), shine)
        dark = mix(base, (0, 0, 0, 255), shade)
        pixels: list[tuple[int, int, int, int]] = []
        for y in range(height):
            yn = y / max(1, height - 1)
            for x in range(width):
                xn = x / max(1, width - 1)
                diagonal = min(1, max(0, yn * 0.42 + xn * 0.58))
                color = mix(light, dark, diagonal)
                spot = max(0, 1 - math.hypot(xn - 0.22, yn - 0.18) / 0.24)
                color = mix(color, (255, 255, 255, 255), spot * 0.46)
                rim = max(0, 1 - math.hypot(xn - 0.9, yn - 0.64) / 0.46)
                color = mix(color, (0, 0, 0, 255), rim * 0.22)
                pixels.append(color)

        layer = Image.new("RGBA", (width, height))
        layer.putdata(pixels)
        layer.putalpha(mask.crop((left, top, right, bottom)))
        self.image.alpha_composite(layer, (left, top))
        self.add_cel_shadow(mask, bounds, base)
        self.add_shine(mask, bounds)

    def alpha_composite_color(self, mask: Image.Image, color: tuple[int, int, int, int]) -> None:
        layer = Image.new("RGBA", self.image.size, color)
        layer.putalpha(mask)
        self.image.alpha_composite(layer)

    def offset_mask(self, mask: Image.Image, dx: float, dy: float) -> Image.Image:
        x_offset = self.s(dx)
        y_offset = self.s(dy)
        width, height = mask.size
        shifted = Image.new("L", mask.size, 0)
        source = mask.crop((0, 0, max(0, width - x_offset), max(0, height - y_offset)))
        shifted.paste(source, (x_offset, y_offset))
        return shifted

    def add_depth(self, mask: Image.Image, base: tuple[int, int, int, int], outline) -> None:
        side = mix(base, (0, 0, 0, 255), 0.58)
        if outline:
            side = mix(side, outline, 0.44)
        side_mask = self.offset_mask(mask, 5, 4)
        rim_mask = ImageChops.subtract(side_mask, mask.filter(ImageFilter.MaxFilter(self.s(2) | 1)))
        side_alpha = ImageChops.lighter(side_mask.point(lambda value: round(value * 0.78)), rim_mask)
        self.alpha_composite_color(side_alpha, side)

    def add_cel_shadow(self, mask: Image.Image, bounds: tuple[float, float, float, float], base) -> None:
        left, top, right, bottom = self.box(bounds)
        width = max(1, right - left)
        height = max(1, bottom - top)
        shadow = Image.new("L", (width, height), 0)
        values: list[int] = []
        for y in range(height):
            yn = y / max(1, height - 1)
            for x in range(width):
                xn = x / max(1, width - 1)
                right_band = max(0, (xn - 0.56) / 0.44)
                lower_band = max(0, (yn - 0.68) / 0.32)
                edge = max(right_band, lower_band * 0.72)
                values.append(round(150 * min(1, edge**1.5)))
        shadow.putdata(values)
        clipped = ImageChops.multiply(shadow, mask.crop((left, top, right, bottom)))
        layer = Image.new("RGBA", (width, height), mix(base, (0, 0, 0, 255), 0.66))
        layer.putalpha(clipped)
        self.image.alpha_composite(layer, (left, top))

    def add_shine(self, mask: Image.Image, bounds: tuple[float, float, float, float]) -> None:
        left, top, right, bottom = bounds
        width = right - left
        height = bottom - top
        if width < 18 or height < 18:
            return

        shine = Image.new("L", self.image.size, 0)
        draw = ImageDraw.Draw(shine)
        draw.ellipse(
            self.box((
                left + width * 0.13,
                top + height * 0.12,
                left + width * 0.32,
                top + height * 0.28,
            )),
            fill=224,
        )
        draw.rounded_rectangle(
            self.box((
                left + width * 0.34,
                top + height * 0.12,
                left + width * 0.54,
                top + height * 0.18,
            )),
            radius=self.s(2),
            fill=132,
        )
        clipped = ImageChops.multiply(shine.filter(ImageFilter.GaussianBlur(self.s(0.45))), mask)
        self.alpha_composite_color(clipped, (255, 255, 255, 230))

    def glossy_ellipse(self, box: tuple[float, float, float, float], base, outline=None, width: int = 1) -> None:
        mask = Image.new("L", self.image.size, 0)
        ImageDraw.Draw(mask).ellipse(self.box(box), fill=255)
        self.add_depth(mask, base, outline)
        self.glossy_fill(mask, box, base)
        if outline:
            self.draw.ellipse(self.box(box), outline=outline, width=self.s(width))

    def glossy_rounded(self, box: tuple[float, float, float, float], radius: float, base, outline=None, width: int = 1) -> None:
        mask = Image.new("L", self.image.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(self.box(box), radius=self.s(radius), fill=255)
        self.add_depth(mask, base, outline)
        self.glossy_fill(mask, box, base)
        if outline:
            self.draw.rounded_rectangle(self.box(box), radius=self.s(radius), outline=outline, width=self.s(width))

    def glossy_polygon(self, points: list[tuple[float, float]], base, outline=None, width: int = 1) -> None:
        scaled = [(self.s(x), self.s(y)) for x, y in points]
        mask = Image.new("L", self.image.size, 0)
        ImageDraw.Draw(mask).polygon(scaled, fill=255)
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        self.add_depth(mask, base, outline)
        self.glossy_fill(mask, (min(xs), min(ys), max(xs), max(ys)), base)
        if outline:
            self.draw.line(scaled + [scaled[0]], fill=outline, width=self.s(width), joint="curve")


def add_shadow(canvas: Canvas) -> None:
    shadow = Image.new("RGBA", canvas.image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow, "RGBA")
    draw.ellipse(canvas.box((55, 147, 137, 169)), fill=(0, 0, 0, 72))
    canvas.image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(canvas.s(5))))


def regular_points(cx: float, cy: float, radius: float, count: int, offset: float = -math.pi / 2) -> list[tuple[float, float]]:
    return [
        (cx + math.cos(offset + index * math.tau / count) * radius, cy + math.sin(offset + index * math.tau / count) * radius)
        for index in range(count)
    ]


def star_points(cx: float, cy: float, outer: float, inner: float, count: int, offset: float = -math.pi / 2) -> list[tuple[float, float]]:
    points = []
    for index in range(count * 2):
        radius = outer if index % 2 == 0 else inner
        points.append((cx + math.cos(offset + index * math.pi / count) * radius, cy + math.sin(offset + index * math.pi / count) * radius))
    return points


def draw_limbs(canvas: Canvas, spec: dict[str, str], base, trim, outline) -> None:
    pose = spec["pose"]
    if pose == "wide":
        arms = [((70, 105), (45, 122), (38, 118)), ((122, 105), (147, 122), (154, 118))]
    elif pose == "open":
        arms = [((71, 105), (51, 112), (44, 104)), ((121, 105), (141, 112), (148, 104))]
    elif pose == "straight":
        arms = [((72, 108), (55, 128), (50, 139)), ((120, 108), (137, 128), (142, 139))]
    else:
        arms = [((74, 112), (59, 123), (53, 123)), ((118, 112), (133, 123), (139, 123))]

    for shoulder, elbow, hand in arms:
        canvas.line([shoulder, elbow], fill=outline, width=5)
        canvas.line([shoulder, elbow], fill=trim, width=3)
        canvas.line([elbow, hand], fill=outline, width=5)
        canvas.line([elbow, hand], fill=trim, width=3)
        canvas.glossy_ellipse((hand[0] - 6, hand[1] - 6, hand[0] + 6, hand[1] + 6), base, outline=outline, width=2)

    for x in (78, 114):
        canvas.line([(x, 136), (x - 4 if x < 96 else x + 4, 154)], fill=outline, width=5)
        canvas.line([(x, 136), (x - 4 if x < 96 else x + 4, 154)], fill=trim, width=3)
        canvas.glossy_rounded((x - 13 if x < 96 else x - 4, 153, x + 7 if x < 96 else x + 16, 160), 3, base, outline=outline, width=2)


def draw_body(canvas: Canvas, shape: BodyShape, base, accent, trim, outline) -> None:
    shade = mix(base, (0, 0, 0, 255), 0.12)
    light = mix(base, (255, 255, 255, 255), 0.22)
    if shape == "round":
        canvas.glossy_ellipse((65, 85, 127, 146), base, outline=outline, width=3)
    elif shape == "capsule":
        canvas.glossy_rounded((64, 82, 128, 146), 24, base, outline=outline, width=3)
    elif shape == "square":
        canvas.glossy_rounded((62, 82, 130, 146), 13, base, outline=outline, width=3)
    elif shape == "trapezoid":
        canvas.glossy_polygon([(68, 84), (124, 84), (136, 145), (56, 145)], base, outline=outline, width=3)
    elif shape == "hex":
        canvas.glossy_polygon(regular_points(96, 115, 37, 6, math.pi / 6), base, outline=outline, width=3)
    elif shape == "bell":
        canvas.glossy_rounded((67, 81, 125, 146), 18, base, outline=outline, width=3)
        canvas.glossy_ellipse((70, 128, 122, 151), base, outline=outline, width=3)
    else:
        canvas.glossy_rounded((56, 88, 136, 144), 19, base, outline=outline, width=3)

    canvas.ellipse((73, 91, 95, 112), fill=(*light[:3], 84))
    canvas.glossy_ellipse((82, 102, 110, 132), accent, outline=outline, width=3)
    canvas.ellipse((88, 108, 104, 126), fill=shade)


def draw_chest(canvas: Canvas, chest: str, accent, trim, outline) -> None:
    if chest == "sun":
        canvas.glossy_polygon(star_points(96, 117, 19, 12, 10), accent, outline=outline, width=2)
        canvas.glossy_ellipse((86, 107, 106, 127), mix(accent, (255, 255, 255, 255), 0.18), outline=outline, width=2)
    elif chest == "orbit":
        canvas.glossy_ellipse((80, 102, 112, 134), accent, outline=outline, width=2)
        canvas.line([(76, 120), (91, 109), (116, 113)], fill=mix(accent, (255, 255, 255, 255), 0.28), width=3)
        canvas.ellipse((111, 109, 118, 116), fill=(255, 255, 255, 255), outline=outline, width=1)
    elif chest == "sash":
        canvas.glossy_polygon([(72, 95), (82, 90), (122, 135), (112, 141)], accent, outline=outline, width=2)
    elif chest == "bolt":
        canvas.glossy_polygon([(99, 96), (84, 120), (96, 119), (88, 139), (111, 111), (99, 112)], accent, outline=outline, width=2)
    elif chest == "heart":
        canvas.glossy_ellipse((83, 104, 99, 120), accent, outline=outline, width=2)
        canvas.glossy_ellipse((93, 104, 109, 120), accent, outline=outline, width=2)
        canvas.glossy_polygon([(80, 114), (112, 114), (96, 134)], accent, outline=outline, width=2)
    elif chest == "gem":
        canvas.glossy_polygon([(96, 100), (113, 115), (96, 135), (79, 115)], accent, outline=outline, width=2)
        canvas.line([(84, 115), (108, 115)], fill=(255, 255, 255, 150), width=2)
    elif chest == "speaker":
        canvas.glossy_ellipse((80, 100, 112, 132), accent, outline=outline, width=2)
        canvas.glossy_ellipse((88, 108, 104, 124), trim, outline=outline, width=2)
        canvas.line([(113, 108), (121, 103)], fill=outline, width=2)
        canvas.line([(115, 119), (124, 119)], fill=outline, width=2)
    elif chest == "ring":
        canvas.glossy_ellipse((79, 100, 113, 134), accent, outline=outline, width=2)
        canvas.ellipse((88, 109, 104, 125), fill=trim)
    elif chest == "star":
        canvas.glossy_polygon(star_points(96, 118, 20, 9, 5), accent, outline=outline, width=2)
    elif chest == "shield":
        canvas.glossy_polygon([(79, 103), (113, 103), (109, 128), (96, 139), (83, 128)], accent, outline=outline, width=2)
    elif chest == "note":
        canvas.line([(93, 101), (93, 128), (110, 124), (110, 98)], fill=outline, width=6)
        canvas.line([(93, 101), (93, 128), (110, 124), (110, 98)], fill=accent, width=3)
        canvas.glossy_ellipse((82, 123, 96, 137), accent, outline=outline, width=2)
    else:
        canvas.glossy_rounded((80, 108, 112, 126), 8, accent, outline=outline, width=2)
        canvas.glossy_ellipse((93, 111, 108, 126), (255, 255, 255, 255), outline=outline, width=2)


def draw_head(canvas: Canvas, shape: HeadShape, base, accent, trim, outline) -> None:
    light = mix(base, (255, 255, 255, 255), 0.3)
    if shape == "round":
        canvas.glossy_ellipse((53, 28, 139, 100), base, outline=outline, width=3)
    elif shape == "oval":
        canvas.glossy_ellipse((48, 32, 144, 97), base, outline=outline, width=3)
    elif shape == "square":
        canvas.glossy_rounded((54, 28, 138, 98), 17, base, outline=outline, width=3)
    elif shape == "dome":
        canvas.glossy_rounded((55, 36, 137, 99), 26, base, outline=outline, width=3)
        canvas.glossy_polygon([(61, 51), (132, 51), (137, 98), (55, 98)], base)
    elif shape == "hex":
        canvas.glossy_polygon(regular_points(96, 65, 47, 6, math.pi / 6), base, outline=outline, width=3)
    elif shape == "gear":
        for point in regular_points(96, 64, 45, 12):
            canvas.glossy_ellipse((point[0] - 8, point[1] - 8, point[0] + 8, point[1] + 8), trim, outline=outline, width=2)
        canvas.glossy_ellipse((53, 22, 139, 106), base, outline=outline, width=3)
    else:
        canvas.glossy_rounded((52, 36, 140, 97), 20, base, outline=outline, width=3)
        canvas.glossy_rounded((66, 50, 126, 76), 10, trim, outline=outline, width=2)

    canvas.ellipse((66, 40, 89, 58), fill=(*light[:3], 90))


def draw_ears(canvas: Canvas, ears: str, base, accent, trim, outline) -> None:
    if ears == "none":
        return
    if ears == "pods":
        for x in (43, 133):
            canvas.glossy_rounded((x - 10, 55, x + 10, 83), 8, trim, outline=outline, width=3)
            canvas.glossy_rounded((x - 6, 60, x + 6, 78), 5, base)
    elif ears == "hooks":
        canvas.line([(49, 63), (35, 73), (35, 88)], fill=outline, width=5)
        canvas.line([(143, 63), (157, 73), (157, 88)], fill=outline, width=5)
        canvas.line([(49, 63), (35, 73), (35, 88)], fill=accent, width=3)
        canvas.line([(143, 63), (157, 73), (157, 88)], fill=accent, width=3)
    elif ears == "ticks":
        for x in (45, 147):
            canvas.glossy_rounded((x - 6, 47, x + 6, 61), 3, accent, outline=outline, width=2)
            canvas.glossy_rounded((x - 6, 73, x + 6, 87), 3, accent, outline=outline, width=2)
    elif ears == "fins":
        canvas.glossy_polygon([(47, 61), (27, 45), (33, 78)], accent, outline=outline, width=3)
        canvas.glossy_polygon([(145, 61), (165, 45), (159, 78)], accent, outline=outline, width=3)
    elif ears == "tabs":
        canvas.glossy_rounded((38, 58, 56, 78), 5, trim, outline=outline, width=2)
        canvas.glossy_rounded((136, 58, 154, 78), 5, trim, outline=outline, width=2)
    elif ears == "cheeks":
        canvas.glossy_ellipse((40, 67, 57, 84), accent, outline=outline, width=2)
        canvas.glossy_ellipse((135, 67, 152, 84), accent, outline=outline, width=2)
    elif ears == "horns":
        canvas.glossy_polygon([(58, 49), (37, 33), (45, 63)], accent, outline=outline, width=3)
        canvas.glossy_polygon([(134, 49), (155, 33), (147, 63)], accent, outline=outline, width=3)
    elif ears == "loops":
        for x in (42, 150):
            canvas.ellipse((x - 18, 51, x + 6, 86), fill=(0, 0, 0, 0), outline=outline, width=4)
            canvas.ellipse((x - 14, 56, x + 2, 81), fill=(0, 0, 0, 0), outline=accent, width=3)
    elif ears == "rings":
        canvas.ellipse((36, 59, 58, 85), fill=(0, 0, 0, 0), outline=accent, width=4)
        canvas.ellipse((134, 59, 156, 85), fill=(0, 0, 0, 0), outline=accent, width=4)
    elif ears == "crescent":
        canvas.ellipse((35, 56, 61, 86), fill=accent, outline=outline, width=3)
        canvas.ellipse((42, 56, 68, 86), fill=(0, 0, 0, 0))
        canvas.ellipse((131, 56, 157, 86), fill=accent, outline=outline, width=3)
        canvas.ellipse((124, 56, 150, 86), fill=(0, 0, 0, 0))
    elif ears == "bolts":
        canvas.glossy_polygon([(49, 54), (35, 66), (46, 68), (33, 84), (57, 66), (46, 64)], accent, outline=outline, width=2)
        canvas.glossy_polygon([(143, 54), (157, 66), (146, 68), (159, 84), (135, 66), (146, 64)], accent, outline=outline, width=2)
    elif ears == "wings":
        canvas.glossy_polygon([(47, 63), (25, 52), (22, 85), (48, 78)], accent, outline=outline, width=3)
        canvas.glossy_polygon([(145, 63), (167, 52), (170, 85), (144, 78)], accent, outline=outline, width=3)


def draw_antenna(canvas: Canvas, antenna: str, base, accent, trim, outline) -> None:
    if antenna == "none":
        return
    if antenna == "spark":
        canvas.line([(96, 31), (96, 13)], fill=outline, width=3)
        canvas.glossy_polygon(star_points(96, 10, 8, 4, 5), accent, outline=outline, width=2)
    elif antenna == "halo":
        canvas.ellipse((72, 14, 120, 25), fill=(0, 0, 0, 0), outline=accent, width=4)
    elif antenna == "meter":
        canvas.line([(88, 28), (88, 13)], fill=outline, width=3)
        canvas.line([(104, 28), (104, 13)], fill=outline, width=3)
        canvas.glossy_rounded((79, 8, 97, 20), 3, accent, outline=outline, width=2)
        canvas.glossy_rounded((101, 8, 115, 20), 3, base, outline=outline, width=2)
    elif antenna == "pixels":
        for x, y, color in [(76, 12, base), (96, 8, accent), (116, 13, trim)]:
            canvas.glossy_rounded((x - 5, y - 5, x + 5, y + 5), 2, color, outline=outline, width=1)
            canvas.line([(x, y + 5), (x, 29)], fill=outline, width=2)
    elif antenna == "wings":
        canvas.glossy_polygon([(83, 36), (66, 18), (86, 26)], accent, outline=outline, width=2)
        canvas.glossy_polygon([(109, 36), (126, 18), (106, 26)], accent, outline=outline, width=2)
    elif antenna == "crest":
        canvas.glossy_polygon([(73, 34), (82, 14), (96, 31), (110, 14), (119, 34)], accent, outline=outline, width=2)
    elif antenna == "beacon":
        canvas.line([(96, 29), (96, 13)], fill=outline, width=3)
        canvas.glossy_ellipse((88, 5, 104, 21), accent, outline=outline, width=2)
    elif antenna == "flag":
        canvas.line([(105, 29), (105, 9)], fill=outline, width=3)
        canvas.glossy_polygon([(106, 10), (128, 16), (106, 23)], accent, outline=outline, width=2)
    elif antenna == "pennant":
        canvas.line([(86, 32), (86, 12)], fill=outline, width=3)
        canvas.glossy_polygon([(88, 12), (109, 20), (88, 25)], accent, outline=outline, width=2)
    elif antenna == "propeller":
        canvas.line([(96, 32), (96, 18)], fill=outline, width=3)
        canvas.glossy_ellipse((75, 10, 96, 24), accent, outline=outline, width=2)
        canvas.glossy_ellipse((96, 10, 117, 24), accent, outline=outline, width=2)
    elif antenna == "dual":
        canvas.line([(82, 31), (74, 14)], fill=outline, width=3)
        canvas.line([(110, 31), (118, 14)], fill=outline, width=3)
        canvas.glossy_ellipse((68, 8, 80, 20), accent, outline=outline, width=2)
        canvas.glossy_ellipse((112, 8, 124, 20), base, outline=outline, width=2)


def draw_face(canvas: Canvas, eyes: str, accent, trim, outline) -> None:
    white = (250, 255, 255, 255)
    dark = (33, 42, 56, 255)

    def eye(cx: float, cy: float, r: float = 8) -> None:
        canvas.ellipse((cx - r, cy - r, cx + r, cy + r), fill=white, outline=outline, width=2)
        canvas.ellipse((cx - r / 2, cy - r / 2, cx + r / 2, cy + r / 2), fill=trim)
        canvas.ellipse((cx - 2, cy - 3, cx + 2, cy + 1), fill=white)

    if eyes == "visor":
        canvas.rounded((67, 56, 125, 76), 9, fill=dark, outline=outline, width=2)
        canvas.rounded((75, 61, 117, 70), 4, fill=accent)
    elif eyes == "single":
        eye(96, 64, 12)
    elif eyes == "sleepy":
        canvas.line([(70, 64), (86, 61)], fill=dark, width=3)
        canvas.line([(106, 61), (122, 64)], fill=dark, width=3)
    elif eyes == "dots":
        canvas.ellipse((75, 59, 86, 70), fill=dark)
        canvas.ellipse((106, 59, 117, 70), fill=dark)
    elif eyes == "switch":
        canvas.rounded((66, 55, 89, 72), 8, fill=dark, outline=outline, width=1)
        canvas.rounded((103, 55, 126, 72), 8, fill=dark, outline=outline, width=1)
        canvas.ellipse((74, 58, 86, 70), fill=accent)
        canvas.ellipse((104, 58, 116, 70), fill=accent)
    else:
        eye(76, 64, 9 if eyes == "wide" else 8)
        eye(116, 64, 9 if eyes == "wide" else 8)

    canvas.ellipse((62, 75, 73, 86), fill=(255, 143, 178, 130))
    canvas.ellipse((119, 75, 130, 86), fill=(255, 143, 178, 130))
    if eyes == "happy":
        canvas.line([(86, 82), (96, 88), (106, 82)], fill=dark, width=3)
    else:
        canvas.line([(88, 83), (96, 86), (104, 83)], fill=dark, width=3)


def render_sprite(spec: dict[str, str]) -> Image.Image:
    base = rgb(spec["base"])
    accent = rgb(spec["accent"])
    trim = rgb(spec["trim"])
    outline = mix(trim, (0, 0, 0, 255), 0.42)
    canvas = Canvas()
    add_shadow(canvas)
    draw_limbs(canvas, spec, base, trim, outline)
    draw_body(canvas, spec["body"], base, accent, trim, outline)  # type: ignore[arg-type]
    draw_chest(canvas, spec["chest"], accent, trim, outline)
    draw_ears(canvas, spec["ears"], base, accent, trim, outline)
    draw_head(canvas, spec["head"], base, accent, trim, outline)  # type: ignore[arg-type]
    draw_antenna(canvas, spec["antenna"], base, accent, trim, outline)
    draw_face(canvas, spec["eyes"], accent, trim, outline)
    return canvas.image.resize((192, 192), Image.Resampling.LANCZOS)


def tinted(image: Image.Image, tint: tuple[int, int, int]) -> Image.Image:
    output = Image.new("RGBA", image.size, (0, 0, 0, 0))
    pixels = image.load()
    out = output.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            amount = 0.12 if luma < 58 or luma > 232 else 0.34
            out[x, y] = (
                round(r * (1 - amount) + tint[0] * amount),
                round(g * (1 - amount) + tint[1] * amount),
                round(b * (1 - amount) + tint[2] * amount),
                a,
            )
    return output


def manifest_for(key: str) -> dict[str, object]:
    frame = f"public/assets/cogshambo/sprite-sheets/{key}/frames/{key}-01.png"
    red = f"public/assets/cogshambo/sprite-sheets/{key}/frames/{key}-01-red.png"
    blue = f"public/assets/cogshambo/sprite-sheets/{key}/frames/{key}-01-blue.png"
    return {
        "name": key,
        "source_sheet": f"public/assets/cogshambo/cogs/{key}.png",
        "source_sheet_url": f"/assets/cogshambo/cogs/{key}.png",
        "frame_width": 192,
        "frame_height": 192,
        "columns": 1,
        "rows": 1,
        "frame_count": 1,
        "frames": [
            {
                "path": frame,
                "url": f"/assets/cogshambo/sprite-sheets/{key}/frames/{key}-01.png",
                "spriteUrls": {
                    "red": f"/assets/cogshambo/sprite-sheets/{key}/frames/{key}-01-red.png",
                    "blue": f"/assets/cogshambo/sprite-sheets/{key}/frames/{key}-01-blue.png",
                },
                "variants": {
                    "red": {"path": red, "url": f"/assets/cogshambo/sprite-sheets/{key}/frames/{key}-01-red.png"},
                    "blue": {"path": blue, "url": f"/assets/cogshambo/sprite-sheets/{key}/frames/{key}-01-blue.png"},
                },
            }
        ],
        "preview": f"public/assets/cogshambo/sprite-sheets/{key}/{key}-preview.png",
        "preview_url": f"/assets/cogshambo/sprite-sheets/{key}/{key}-preview.png",
    }


def save_generated_sprite(spec: dict[str, str]) -> None:
    key = spec["key"]
    image = render_sprite(spec)
    cog_path = COGS_DIR / f"{key}.png"
    frame_dir = SHEETS_DIR / key / "frames"
    frame_path = frame_dir / f"{key}-01.png"
    red_path = frame_dir / f"{key}-01-red.png"
    blue_path = frame_dir / f"{key}-01-blue.png"
    preview_path = SHEETS_DIR / key / f"{key}-preview.png"
    manifest_path = SHEETS_DIR / key / "manifest.json"

    frame_dir.mkdir(parents=True, exist_ok=True)
    image.save(cog_path)
    image.save(frame_path)
    image.save(preview_path)
    tinted(image, (239, 71, 93)).save(red_path)
    tinted(image, (67, 145, 255)).save(blue_path)
    manifest_path.write_text(json.dumps(manifest_for(key), indent=2) + "\n")


def make_preview(keys: list[str]) -> Image.Image:
    columns = 4
    cell = 112
    gap = 12
    rows = math.ceil(len(keys) / columns)
    preview = Image.new("RGBA", (columns * cell + (columns + 1) * gap, rows * cell + (rows + 1) * gap), (19, 24, 29, 255))
    draw = ImageDraw.Draw(preview, "RGBA")
    for y in range(0, preview.height, 12):
        for x in range(0, preview.width, 12):
            if (x // 12 + y // 12) % 2 == 0:
                draw.rectangle((x, y, x + 12, y + 12), fill=(26, 32, 38, 255))

    for index, key in enumerate(keys):
        source = Image.open(COGS_DIR / f"{key}.png").convert("RGBA")
        sprite = source.resize((96, 96), Image.Resampling.LANCZOS)
        column = index % columns
        row = index // columns
        x = gap + column * (cell + gap) + 8
        y = gap + row * (cell + gap) + 6
        preview.alpha_composite(sprite, (x, y))
    return preview


def main() -> None:
    COGS_DIR.mkdir(parents=True, exist_ok=True)
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    for spec in SPRITES:
        save_generated_sprite(spec)
    keys = STARTER_KEYS + [spec["key"] for spec in SPRITES]
    make_preview(keys).save(COGS_DIR / "cute-cogs-preview.png")


if __name__ == "__main__":
    main()
