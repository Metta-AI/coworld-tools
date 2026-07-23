"""The CrewRift player palette and the two role colors.

Player colors are identity, never role: every figure that draws a specific
player uses that player's game color, and role encoding (when a figure is
allowed to know roles at all) uses the shared house semantics instead.

The 16 entries mirror the engine tables ``PlayerColorNames`` /
``PlayerColorPalette`` in ``coworld-crewrift/src/crewrift/sim.nim`` in
engine order. Look colors up **by name** (``player_manifest.color``):
``color_id`` is the engine's internal color byte, drawn from a shuffled
assignment table, and is *not* an index into this palette.

On dark backdrops the saturated identities (blue, purple, navy, brown...)
go illegible; :func:`lifted_player_color` applies the shared hue-preserving
lift instead of substituting hues.
"""

from __future__ import annotations

from episode_analysis.palette import NEGATIVE, PRIMARY, lift

__all__ = [
    "PLAYER_COLORS",
    "PLAYER_COLOR_NAMES",
    "ROLE_COLORS",
    "lifted_player_color",
    "player_color",
]

PLAYER_COLOR_NAMES: tuple[str, ...] = (
    "red",
    "blue",
    "green",
    "pink",
    "orange",
    "yellow",
    "purple",
    "cyan",
    "lime",
    "brown",
    "beige",
    "navy",
    "teal",
    "rose",
    "maroon",
    "gray",
)

PLAYER_COLORS: dict[str, str] = dict(
    zip(
        PLAYER_COLOR_NAMES,
        (
            "#c51111",
            "#132ed1",
            "#117f2d",
            "#ed54ba",
            "#ef7d0d",
            "#f5f557",
            "#6b2fbb",
            "#38fedc",
            "#50ef39",
            "#71491e",
            "#f0d7b7",
            "#1b2148",
            "#38a9a5",
            "#f4a6c8",
            "#6b2b3a",
            "#282a30",
        ),
    )
)

# Role encoding reuses the house semantics: the red that means "something
# bad happened" in every other chart marks the antagonist here.
ROLE_COLORS: dict[str, str] = {"imposter": NEGATIVE, "crew": PRIMARY}


def player_color(name: str) -> str:
    """Hex for a palette color name; raises with the valid names on a miss."""
    try:
        return PLAYER_COLORS[name]
    except KeyError:
        raise ValueError(
            f"unknown player color {name!r}; expected one of {', '.join(PLAYER_COLOR_NAMES)}"
        ) from None


def lifted_player_color(name: str, amount: float = 0.34) -> str:
    """The player's color lifted toward white for dark backdrops."""
    return lift(player_color(name), amount)
