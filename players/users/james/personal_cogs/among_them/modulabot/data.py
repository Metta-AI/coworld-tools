"""Reference data for modulabot: palette, map, sprites, ASCII font.

All the static assets the Nim bot loads at startup: the PICO-8 palette,
shadow map, player-colour ordering, skeld2 map image + walk/wall masks,
eight reference sprites sliced from ``spritesheet.png``, and the
``tiny5``-style glyph font (for voting-chat / interstitial OCR).

Data files live in :mod:`modulabot.data` (i.e. ``among_them/modulabot/data/``)
and are shipped with the bundle. Loading is lazy + cached so the whole
pipeline costs ~20 ms the first time and nothing thereafter.

Port notes:

- The Nim bot uses pixie to decode an aseprite file at runtime. Porting
  an aseprite parser to Python is out of scope; instead we pre-render
  the three map layers to PNG via ``tools/dump_map.nim`` (one-off) and
  palette-decode them here via :func:`_palette_index`.
- :data:`PICO8_PALETTE` and :data:`PLAYER_COLORS` must match
  ``sim.nim``'s ``Palette`` / ``PlayerColors``. Do not re-order; perception
  code indexes by position.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Constants (match sim.nim / protocol.nim)
# ---------------------------------------------------------------------------

SCREEN_WIDTH = 128
SCREEN_HEIGHT = 128
SPRITE_SIZE = 12  # every reference sprite is 12x12
SPRITE_DRAW_OFF_X = 2
SPRITE_DRAW_OFF_Y = 8
MAP_WIDTH = 952
MAP_HEIGHT = 534

#: Palette index used by the sprite format to mean "transparent".
#: v2 uses ``255'u8``; we keep the same value so RGBA-derived pixel
#: arrays can use uint8 without any wider type.
TRANSPARENT_INDEX = 255

#: BitWorld palette in RGB order. Index → (r, g, b). This is **not**
#: standard PICO-8 ordering — bitworld's ``clients/data/pallete.png``
#: reassigns indices (e.g. index 3 is red, not dark green). Must stay
#: aligned with that file; the Nim ``loadPalette`` reads it at startup
#: and ``nearestPaletteIndex`` returns these indices.
PICO8_PALETTE = np.array(
    [
        (0x00, 0x00, 0x00),  #  0 black
        (0xC2, 0xC3, 0xC7),  #  1 light grey
        (0xFF, 0xF1, 0xE8),  #  2 white
        (0xFF, 0x00, 0x4D),  #  3 red          (TintColor — player body placeholder)
        (0xFF, 0x77, 0xA8),  #  4 pink
        (0x5F, 0x57, 0x4F),  #  5 dark grey    (shadow of red)
        (0xAB, 0x52, 0x36),  #  6 brown
        (0xFF, 0xA3, 0x00),  #  7 orange
        (0xFF, 0xEC, 0x27),  #  8 yellow       (radar-dot colour)
        (0x7E, 0x25, 0x53),  #  9 dark purple  (ShadeTintColor — shadowed body)
        (0x00, 0x87, 0x51),  # 10 dark green
        (0x00, 0xE4, 0x36),  # 11 green
        (0x1D, 0x2B, 0x53),  # 12 dark navy    (MapVoidColor)
        (0x83, 0x76, 0x9C),  # 13 indigo
        (0x29, 0xAD, 0xFF),  # 14 blue
        (0xFF, 0xCC, 0xAA),  # 15 peach
    ],
    dtype=np.uint8,
)

#: Palette index used for the "tint" (player colour placeholder) in
#: reference sprites — matches ``TintColor = 3`` in ``sim.nim``. Frame-side
#: pixel at a tint position is interpreted as "a player's colour".
TINT_COLOR = 3
#: Shaded tint used for the non-lit sides of sprite bodies (``9`` in the
#: bitworld palette = dark purple).
SHADE_TINT_COLOR = 9

#: Player-colour ordering used by every per-colour array in the bot.
#: Must match ``PlayerColors`` in ``sim.nim``. Index into this array →
#: palette index of the player's lit tint.
PLAYER_COLORS = np.array(
    [3, 7, 8, 14, 4, 11, 13, 15, 1, 2, 5, 6, 9, 10, 12, 0],
    dtype=np.uint8,
)

PLAYER_COLOR_COUNT = len(PLAYER_COLORS)

#: Human-readable colour names keyed by the same index as
#: :data:`PLAYER_COLORS`. Taken verbatim from ``PlayerColorNames`` in
#: ``among_them/players/modulabot/evidence.nim`` so chat OCR that
#: spells names out (``"sus blue"``) resolves to the same palette
#: index on both sides.
PLAYER_COLOR_NAMES: tuple[str, ...] = (
    "red",
    "orange",
    "yellow",
    "light blue",
    "pink",
    "lime",
    "blue",
    "pale blue",
    "gray",
    "white",
    "dark brown",
    "brown",
    "dark teal",
    "green",
    "dark navy",
    "black",
)

#: Palette index → shadowed palette index. Matches ``ShadowMap`` in
#: ``sim.nim``. Used so ``matchesSpriteShadowed`` and the localizer can
#: accept the shadowed variant of any map pixel.
SHADOW_MAP = np.array(
    [0, 12, 9, 5, 5, 0, 5, 5, 5, 12, 9, 9, 0, 12, 12, 9], dtype=np.uint8
)

#: Palette index used as the "off-map" fill (outside the 952x534 map
#: rectangle). Matches ``MapVoidColor``. Not black, so interstitial
#: detection (≥30% black) can distinguish it from a vote screen.
MAP_VOID_COLOR = 12


# ---------------------------------------------------------------------------
# Sprite and map value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sprite:
    """A fixed-size 2D array of palette indices + ``TRANSPARENT_INDEX``.

    ``pixels`` is a ``(height, width)`` uint8 numpy array. Transparent
    pixels hold :data:`TRANSPARENT_INDEX`. Match ``Sprite`` in
    ``common/server.nim``.
    """

    width: int
    height: int
    pixels: np.ndarray  # shape (height, width), dtype=uint8


@dataclass(frozen=True)
class PixelGlyph:
    """One variable-width tiny-font glyph.

    ``pixels`` is a ``(height, width) bool`` bitmap — ``True`` where
    the glyph paints a foreground pixel. Height matches the parent
    font. ``ch`` is the single character this glyph renders; ``width``
    is variable 1..5 in the stock ``tiny5`` font.
    """

    ch: str  # single character
    width: int
    height: int
    pixels: np.ndarray  # (height, width) bool


@dataclass(frozen=True)
class PixelFont:
    """Variable-width pixel font loaded from a marker-delimited PNG.

    Mirrors ``PixelFont`` in ``common/pixelfonts.nim``. The loader in
    :func:`_load_font` decodes the source image using the yellow
    marker row at ``image[-1, :]`` to pick out glyph boundaries, so
    the stock font renderer / OCR reader stays aligned with whatever
    the BitWorld team ships next.

    - ``height`` — pixel height of each glyph (image height minus the
      marker row).
    - ``spacing`` — horizontal gap between glyphs when rendered or
      scored. Default :data:`DEFAULT_GLYPH_SPACING` = 1.
    - ``background_rgba`` — pixel colour the font decoder treats as
      transparent in the PNG source. Stored only for diagnostics;
      framebuffer matchers use a palette-index background instead
      (typically :data:`SPACE_COLOR` = 0 = black).
    - ``glyphs`` — list of exactly :data:`PRINTABLE_ASCII_COUNT`
      glyphs, indexed by ``ord(ch) - FIRST_PRINTABLE_ASCII``.
      Missing or over-sourced indices fall back to ``'?'`` in the
      matchers.
    """

    height: int
    spacing: int
    background_rgba: tuple[int, int, int, int]
    glyphs: tuple[PixelGlyph, ...]


#: First ASCII code that gets a glyph (space). Matches
#: ``FirstPrintableAscii`` in ``common/pixelfonts.nim``.
FIRST_PRINTABLE_ASCII = 32
#: Last ASCII code that gets a glyph (tilde).
LAST_PRINTABLE_ASCII = 126
PRINTABLE_ASCII_COUNT = LAST_PRINTABLE_ASCII - FIRST_PRINTABLE_ASCII + 1
#: Default horizontal pixel gap between rendered glyphs.
DEFAULT_GLYPH_SPACING = 1
#: Palette index treated as "text background" when scoring rendered
#: glyphs against a frame. BitWorld always paints interstitial text
#: on a black backdrop so 0 (PICO-8 black) is the right default.
SPACE_COLOR = 0


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass(frozen=True)
class TaskStation:
    """One task station as described in ``map.json``."""

    index: int
    name: str
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass(frozen=True)
class Room:
    name: str
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class GameMap:
    """Static map geometry + raster layers."""

    width: int
    height: int
    button: Rect
    home: tuple[int, int]
    tasks: tuple[TaskStation, ...]
    rooms: tuple[Room, ...]
    map_pixels: np.ndarray  # (H, W) uint8 palette indices
    walk_mask: np.ndarray  # (H, W) bool, True = walkable
    wall_mask: np.ndarray  # (H, W) bool, True = wall


@dataclass(frozen=True)
class Sprites:
    """Six reference sprites sliced from ``spritesheet.png``."""

    player: Sprite
    body: Sprite
    ghost: Sprite
    task: Sprite
    kill_button: Sprite
    ghost_icon: Sprite


@dataclass(frozen=True)
class ReferenceData:
    """All the static data a :class:`modulabot.bot.BotCore` needs."""

    map: GameMap
    sprites: Sprites
    #: Variable-width tiny font used for interstitial banners, voting
    #: screen slots, and chat OCR. Loaded from
    #: ``data/tiny5.png`` via :func:`_load_font`. Ported from the
    #: BitWorld ``tiny5.aseprite`` asset — regenerate via
    #: ``among_them/tools/dump_tiny5_font.nim`` if the upstream font
    #: changes.
    font: PixelFont


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


_DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


def _palette_index(rgba_pixel: tuple[int, int, int, int]) -> int:
    """Map one RGBA pixel to a palette index (or ``TRANSPARENT_INDEX``).

    Matches ``nearestPaletteIndex`` in ``common/server.nim``: alpha < 20
    is transparent; otherwise nearest PICO-8 entry by sum-of-squared-RGB
    distance (we also include alpha in the distance, matching the Nim
    implementation for completeness — it never matters for fully-opaque
    pixels but keeps behaviour identical if a sprite ever ships with
    partial alpha).
    """
    r, g, b, a = rgba_pixel
    if a < 20:
        return TRANSPARENT_INDEX
    # Vectorised distance to all 16 entries + alpha delta to 255.
    dr = PICO8_PALETTE[:, 0].astype(np.int32) - r
    dg = PICO8_PALETTE[:, 1].astype(np.int32) - g
    db = PICO8_PALETTE[:, 2].astype(np.int32) - b
    da = 255 - a  # palette entries are fully opaque
    dist = dr * dr + dg * dg + db * db + da * da
    return int(np.argmin(dist))


def _rgba_to_palette(rgba: np.ndarray) -> np.ndarray:
    """Vectorised RGBA (H, W, 4) → palette-index (H, W) uint8 conversion.

    Bulk equivalent of :func:`_palette_index`. Used when loading the
    map raster (952×534 pixels would be slow pixel-by-pixel).
    """
    h, w, _ = rgba.shape
    flat = rgba.reshape(-1, 4)
    alpha = flat[:, 3]
    rgb_f = flat[:, :3].astype(np.int32)
    # (N, 16) distance matrix
    palette_f = PICO8_PALETTE.astype(np.int32)  # (16, 3)
    dr = rgb_f[:, 0:1] - palette_f[:, 0:1].T
    dg = rgb_f[:, 1:2] - palette_f[:, 1:2].T
    db = rgb_f[:, 2:3] - palette_f[:, 2:3].T
    dist = dr * dr + dg * dg + db * db
    indices = np.argmin(dist, axis=1).astype(np.uint8)
    indices[alpha < 20] = TRANSPARENT_INDEX
    return indices.reshape(h, w)


def _load_sprite_sheet(path: Path) -> np.ndarray:
    """Load ``spritesheet.png`` into a (128, 128) uint8 palette array."""
    img = Image.open(path).convert("RGBA")
    return _rgba_to_palette(np.array(img))


def _slice_sprite(sheet: np.ndarray, col: int) -> Sprite:
    """One 12×12 sprite sliced from ``sheet[0:12, col*12 : (col+1)*12]``."""
    x0 = col * SPRITE_SIZE
    pixels = sheet[0:SPRITE_SIZE, x0 : x0 + SPRITE_SIZE].copy()
    return Sprite(width=SPRITE_SIZE, height=SPRITE_SIZE, pixels=pixels)


def _load_sprites(data_dir: Path) -> Sprites:
    sheet = _load_sprite_sheet(data_dir / "spritesheet.png")
    return Sprites(
        player=_slice_sprite(sheet, 0),
        body=_slice_sprite(sheet, 1),
        # col 2 = bone (unused by modulabot)
        kill_button=_slice_sprite(sheet, 3),
        task=_slice_sprite(sheet, 4),
        # col 5 = empty
        ghost=_slice_sprite(sheet, 6),
        ghost_icon=_slice_sprite(sheet, 7),
    )


def _load_map_layers(
    data_dir: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load map / walk / wall PNGs and return palette + boolean masks."""
    map_rgba = np.array(Image.open(data_dir / "map.png").convert("RGBA"))
    walk_rgba = np.array(Image.open(data_dir / "walk.png").convert("RGBA"))
    wall_rgba = np.array(Image.open(data_dir / "wall.png").convert("RGBA"))

    map_pixels = _rgba_to_palette(map_rgba)

    # Walk layer: any non-transparent pixel is walkable (matches
    # bitworld/aseprite.nim semantics).
    walk_mask = walk_rgba[:, :, 3] >= 20

    # Wall layer: non-transparent = wall.
    wall_mask = wall_rgba[:, :, 3] >= 20

    return map_pixels, walk_mask, wall_mask


def _load_map_json(data_dir: Path) -> tuple[Rect, tuple[int, int], tuple[TaskStation, ...], tuple[Room, ...]]:
    data = json.loads((data_dir / "map.json").read_text())
    button = Rect(**data["button"])
    home = (data["home"]["x"], data["home"]["y"])
    tasks = tuple(
        TaskStation(
            index=i,
            name=t["name"],
            x=t["x"],
            y=t["y"],
            w=t["w"],
            h=t["h"],
        )
        for i, t in enumerate(data["tasks"])
    )
    rooms = tuple(
        Room(name=r["name"], x=r["x"], y=r["y"], w=r["w"], h=r["h"])
        for r in data.get("rooms", [])
    )
    return button, home, tasks, rooms


def _is_marker(rgba: np.ndarray) -> np.ndarray:
    """Vectorised equivalent of ``isMarker`` in ``pixelfonts.nim``.

    Accepts an ``(..., 4) uint8`` array and returns a boolean mask of
    the same leading shape. Matches yellow width-marker pixels on the
    bottom row of a decoded pixel-font PNG.
    """
    return (
        (rgba[..., 3] > 20)
        & (rgba[..., 0] > 180)
        & (rgba[..., 1] > 160)
        & (rgba[..., 2] < 120)
    )


def _is_same_color(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Exact RGBA equality. ``a`` is an ``(..., 4) uint8`` array;
    ``b`` is a single ``(4,)`` uint8 pixel."""
    return np.all(a == b, axis=-1)


def _load_font(data_dir: Path, spacing: int = DEFAULT_GLYPH_SPACING) -> PixelFont:
    """Decode a marker-delimited pixel font PNG.

    Matches ``decodePixelFont`` in ``common/pixelfonts.nim``: the
    bottom row is the yellow marker row; each contiguous run of
    markers defines one glyph's horizontal extent, and glyphs are
    assigned ASCII codes starting at :data:`FIRST_PRINTABLE_ASCII`.
    Non-background non-marker pixels inside a glyph's column range
    count as foreground.

    Returns a :class:`PixelFont` whose ``glyphs`` tuple has exactly
    :data:`PRINTABLE_ASCII_COUNT` entries. If the source image
    contains fewer glyphs than that (because the font hasn't been
    extended to the full printable ASCII range) the trailing entries
    are zero-width placeholders.

    Regenerate ``tiny5.png`` from the upstream aseprite source via
    ``among_them/tools/dump_tiny5_font.nim``. The decoder is
    deliberately permissive about height and spacing so a future
    font-size change doesn't require Python edits — just re-render
    the PNG and re-run the tests.
    """
    png_path = data_dir / "tiny5.png"
    if not png_path.exists():
        raise FileNotFoundError(
            f"tiny5.png not found at {png_path}; "
            "regenerate via tools/dump_tiny5_font.nim"
        )
    img = np.array(Image.open(png_path).convert("RGBA"))
    if img.ndim != 3 or img.shape[2] != 4 or img.shape[0] < 2:
        raise ValueError(f"Pixel font {png_path} must be RGBA with height ≥ 2")

    height = img.shape[0] - 1
    background = tuple(int(v) for v in img[0, 0])
    marker_row = img[-1, :, :]
    marker_mask = _is_marker(marker_row)

    # Walk the marker row finding contiguous runs of True → one glyph each.
    glyphs: list[PixelGlyph] = []
    x = 0
    code = FIRST_PRINTABLE_ASCII
    width = img.shape[1]
    while x < width and code <= LAST_PRINTABLE_ASCII:
        # Skip gaps between glyphs.
        while x < width and not bool(marker_mask[x]):
            x += 1
        if x >= width:
            break
        # Measure this glyph's width.
        gw = 0
        while x + gw < width and bool(marker_mask[x + gw]):
            gw += 1

        glyph_rgba = img[:height, x : x + gw, :]
        # A pixel is foreground iff alpha > 20 AND it's not the background
        # colour AND it's not a marker pixel (marker pixels can leak into
        # the upper rows of thin glyphs, matching the Nim decoder).
        bg_np = np.array(background, dtype=np.uint8)
        opaque = glyph_rgba[..., 3] > 20
        non_bg = ~_is_same_color(glyph_rgba, bg_np)
        non_marker = ~_is_marker(glyph_rgba)
        pixels = opaque & non_bg & non_marker
        glyphs.append(
            PixelGlyph(
                ch=chr(code),
                width=gw,
                height=height,
                pixels=pixels.astype(bool),
            )
        )
        x += gw + spacing
        code += 1

    # Pad out to exactly PRINTABLE_ASCII_COUNT entries so the matchers
    # can look up any printable ASCII char without a bounds check.
    while len(glyphs) < PRINTABLE_ASCII_COUNT:
        code = FIRST_PRINTABLE_ASCII + len(glyphs)
        glyphs.append(
            PixelGlyph(
                ch=chr(code),
                width=0,
                height=height,
                pixels=np.zeros((height, 0), dtype=bool),
            )
        )

    return PixelFont(
        height=height,
        spacing=spacing,
        background_rgba=background,
        glyphs=tuple(glyphs[:PRINTABLE_ASCII_COUNT]),
    )


@lru_cache(maxsize=1)
def load_reference_data(data_dir: str | None = None) -> ReferenceData:
    """Load and cache every static artefact modulabot needs."""
    directory = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    if not directory.exists():
        raise FileNotFoundError(
            f"modulabot data directory not found: {directory}. Expected map.png, "
            "walk.png, wall.png, map.json, spritesheet.png, ascii.png."
        )

    map_pixels, walk_mask, wall_mask = _load_map_layers(directory)
    button, home, tasks, rooms = _load_map_json(directory)
    sprites = _load_sprites(directory)
    font = _load_font(directory)

    game_map = GameMap(
        width=MAP_WIDTH,
        height=MAP_HEIGHT,
        button=button,
        home=home,
        tasks=tasks,
        rooms=rooms,
        map_pixels=map_pixels,
        walk_mask=walk_mask,
        wall_mask=wall_mask,
    )
    return ReferenceData(map=game_map, sprites=sprites, font=font)


__all__ = [
    "SCREEN_WIDTH",
    "SCREEN_HEIGHT",
    "SPRITE_SIZE",
    "SPRITE_DRAW_OFF_X",
    "SPRITE_DRAW_OFF_Y",
    "MAP_WIDTH",
    "MAP_HEIGHT",
    "TRANSPARENT_INDEX",
    "PICO8_PALETTE",
    "TINT_COLOR",
    "SHADE_TINT_COLOR",
    "PLAYER_COLORS",
    "PLAYER_COLOR_COUNT",
    "PLAYER_COLOR_NAMES",
    "SHADOW_MAP",
    "MAP_VOID_COLOR",
    "SPACE_COLOR",
    "FIRST_PRINTABLE_ASCII",
    "LAST_PRINTABLE_ASCII",
    "PRINTABLE_ASCII_COUNT",
    "DEFAULT_GLYPH_SPACING",
    "Sprite",
    "PixelGlyph",
    "PixelFont",
    "Rect",
    "TaskStation",
    "Room",
    "GameMap",
    "Sprites",
    "ReferenceData",
    "load_reference_data",
]
