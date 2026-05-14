"""BitWorld action helpers.

The cogames BitWorld action space has 27 discrete actions covering all
combinations of the four directional buttons with the optional A/B buttons.
Action indices are resolved once at module import via ``mettagrid.bitworld``
so we never have to compute the encoding ourselves at runtime.

This module also provides a small vocabulary of *intent*-level helpers
(``move_toward``, ``press_a_while_moving``, ``press_b_while_moving``) that
return action indices rather than button masks. Policy code should speak in
intents; only this module knows about the 27-wide action table.

If ``mettagrid`` is unavailable (e.g. during a unit test on a stripped
environment), the module falls back to a self-contained lookup table that
matches the tournament action ordering.
"""

from __future__ import annotations

try:
    from mettagrid.bitworld import (
        BITWORLD_ACTION_COUNT,
        BITWORLD_ACTION_NAMES,
        bitworld_action_index,
        encode_buttons,
    )

    _HAVE_METTAGRID = True
except ImportError:
    # Self-contained fallback. Keep in sync with mettagrid/python/src/mettagrid/bitworld.py.
    _HAVE_METTAGRID = False

    _BUTTON_MASKS = {
        "up": 0b0000_0001,
        "down": 0b0000_0010,
        "left": 0b0000_0100,
        "right": 0b0000_1000,
        "select": 0b0001_0000,
        "a": 0b0010_0000,
        "b": 0b0100_0000,
    }
    # Order-preserving action list mirroring the tournament server. This is
    # the exact ordering produced by ``mettagrid.bitworld`` for AmongThem.
    _ACTION_BUTTON_COMBOS = (
        (),
        ("a",),
        ("b",),
        ("up",),
        ("up", "a"),
        ("up", "b"),
        ("down",),
        ("down", "a"),
        ("down", "b"),
        ("left",),
        ("left", "a"),
        ("left", "b"),
        ("right",),
        ("right", "a"),
        ("right", "b"),
        ("up", "left"),
        ("up", "left", "a"),
        ("up", "left", "b"),
        ("up", "right"),
        ("up", "right", "a"),
        ("up", "right", "b"),
        ("down", "left"),
        ("down", "left", "a"),
        ("down", "left", "b"),
        ("down", "right"),
        ("down", "right", "a"),
        ("down", "right", "b"),
    )
    BITWORLD_ACTION_COUNT = len(_ACTION_BUTTON_COMBOS)
    BITWORLD_ACTION_NAMES = tuple(
        "+".join(combo) if combo else "noop" for combo in _ACTION_BUTTON_COMBOS
    )

    def encode_buttons(buttons):  # type: ignore[no-redef]
        mask = 0
        for button in buttons:
            mask |= _BUTTON_MASKS[button]
        return mask

    _COMBO_TO_INDEX = {frozenset(combo): i for i, combo in enumerate(_ACTION_BUTTON_COMBOS)}

    def bitworld_action_index(mask):  # type: ignore[no-redef]
        """Inverse lookup: button mask → action index.

        The tournament server really does use ``mask``-indexed tables; this
        fallback reconstructs the mapping from button combos. Kept only for
        tests where ``mettagrid`` isn't installed.
        """
        combo = frozenset(name for name, m in _BUTTON_MASKS.items() if mask & m)
        return _COMBO_TO_INDEX[combo]


def _idx(*buttons: str) -> int:
    return bitworld_action_index(encode_buttons(buttons))


# ---------------------------------------------------------------------------
# Named action indices
# ---------------------------------------------------------------------------

NOOP = _idx()
A = _idx("a")
B = _idx("b")
UP = _idx("up")
DOWN = _idx("down")
LEFT = _idx("left")
RIGHT = _idx("right")
UP_A = _idx("up", "a")
DOWN_A = _idx("down", "a")
LEFT_A = _idx("left", "a")
RIGHT_A = _idx("right", "a")
UP_B = _idx("up", "b")
DOWN_B = _idx("down", "b")
LEFT_B = _idx("left", "b")
RIGHT_B = _idx("right", "b")
UP_LEFT = _idx("up", "left")
UP_RIGHT = _idx("up", "right")
DOWN_LEFT = _idx("down", "left")
DOWN_RIGHT = _idx("down", "right")
UP_LEFT_A = _idx("up", "left", "a")
UP_RIGHT_A = _idx("up", "right", "a")
DOWN_LEFT_A = _idx("down", "left", "a")
DOWN_RIGHT_A = _idx("down", "right", "a")
UP_LEFT_B = _idx("up", "left", "b")
UP_RIGHT_B = _idx("up", "right", "b")
DOWN_LEFT_B = _idx("down", "left", "b")
DOWN_RIGHT_B = _idx("down", "right", "b")


# ---------------------------------------------------------------------------
# Intent helpers
# ---------------------------------------------------------------------------


def direction_to(dx: int, dy: int, deadband: int = 0) -> int:
    """Return the best 8-way action matching ``(dx, dy)``.

    Returns :data:`NOOP` if both deltas are within ``deadband`` (so
    near-centred targets don't cause thrashing).  When both axes need
    more than 1 pixel of travel a diagonal is returned — this is
    strictly better than cardinal movement when the target is off-axis,
    because the BitWorld sim applies full per-tick speed on each pressed
    axis simultaneously.  Falls back to a cardinal when only one axis
    has meaningful displacement (avoids jitter on axis-aligned
    approaches).
    """
    if abs(dx) <= deadband and abs(dy) <= deadband:
        return NOOP
    ax, ay = abs(dx), abs(dy)
    # Both axes need real travel → diagonal
    if ax > 1 and ay > 1:
        if dx > 0:
            return DOWN_RIGHT if dy > 0 else UP_RIGHT
        return DOWN_LEFT if dy > 0 else UP_LEFT
    # One axis dominant → cardinal
    if ax >= ay:
        return RIGHT if dx > 0 else LEFT
    return DOWN if dy > 0 else UP


def press_a_while(direction: int) -> int:
    """Return the action that presses A while holding ``direction``.

    Supports both cardinal and diagonal inputs. Anything unrecognised
    returns :data:`A` without the directional component.
    """
    _A_MAP = {
        UP: UP_A,
        DOWN: DOWN_A,
        LEFT: LEFT_A,
        RIGHT: RIGHT_A,
        UP_LEFT: UP_LEFT_A,
        UP_RIGHT: UP_RIGHT_A,
        DOWN_LEFT: DOWN_LEFT_A,
        DOWN_RIGHT: DOWN_RIGHT_A,
    }
    return _A_MAP.get(direction, A)


def press_b_while(direction: int) -> int:
    """Return the action that presses B while holding ``direction``.

    B is "vent" for imposters; unused for crewmates. (Report uses A, not B.)
    Supports both cardinal and diagonal inputs.
    """
    _B_MAP = {
        UP: UP_B,
        DOWN: DOWN_B,
        LEFT: LEFT_B,
        RIGHT: RIGHT_B,
        UP_LEFT: UP_LEFT_B,
        UP_RIGHT: UP_RIGHT_B,
        DOWN_LEFT: DOWN_LEFT_B,
        DOWN_RIGHT: DOWN_RIGHT_B,
    }
    return _B_MAP.get(direction, B)


def buttons_for(action: int) -> tuple[str, ...]:
    """Reverse lookup: action index → tuple of button names.

    Useful for debug logs and tests. Returns an empty tuple for :data:`NOOP`.
    """
    name = BITWORLD_ACTION_NAMES[action]
    if name == "noop":
        return ()
    return tuple(name.split("+"))


__all__ = [
    "BITWORLD_ACTION_COUNT",
    "BITWORLD_ACTION_NAMES",
    "NOOP",
    "A",
    "B",
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "UP_A",
    "DOWN_A",
    "LEFT_A",
    "RIGHT_A",
    "UP_B",
    "DOWN_B",
    "LEFT_B",
    "RIGHT_B",
    "UP_LEFT",
    "UP_RIGHT",
    "DOWN_LEFT",
    "DOWN_RIGHT",
    "UP_LEFT_A",
    "UP_RIGHT_A",
    "DOWN_LEFT_A",
    "DOWN_RIGHT_A",
    "UP_LEFT_B",
    "UP_RIGHT_B",
    "DOWN_LEFT_B",
    "DOWN_RIGHT_B",
    "direction_to",
    "press_a_while",
    "press_b_while",
    "buttons_for",
]
