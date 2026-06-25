"""Verify that BITWORLD_ACTION_MASKS follows the canonical direction*modifier
ordering that the guided_bot Nim FFI's TrainableMasks relies on.

If this test fails, either mettagrid.bitworld changed its table ordering (and
ffi/lib.nim must be updated to match) or the canonical formula below is wrong.

Run::

    PYTHONPATH=among_them .venv/bin/python -m unittest \
        among_them.guided_bot.test.test_action_table -v
"""

from __future__ import annotations

import unittest

from mettagrid.bitworld import BITWORLD_ACTION_MASKS, BITWORLD_ACTION_NAMES

# Button mask bits -- must match constants.nim.
BUTTON_UP = 0x01
BUTTON_DOWN = 0x02
BUTTON_LEFT = 0x04
BUTTON_RIGHT = 0x08
BUTTON_A = 0x20
BUTTON_B = 0x40

# Canonical ordering: for each direction group, emit {bare, +A, +B}.
DIRECTIONS = [
    0,  # none
    BUTTON_UP,
    BUTTON_DOWN,
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BUTTON_UP | BUTTON_LEFT,
    BUTTON_UP | BUTTON_RIGHT,
    BUTTON_DOWN | BUTTON_LEFT,
    BUTTON_DOWN | BUTTON_RIGHT,
]
MODIFIERS = [0, BUTTON_A, BUTTON_B]

CANONICAL_MASKS = [d | m for d in DIRECTIONS for m in MODIFIERS]
CANONICAL_NAMES = [
    "noop", "a", "b",
    "up", "up+a", "up+b",
    "down", "down+a", "down+b",
    "left", "left+a", "left+b",
    "right", "right+a", "right+b",
    "up+left", "up+left+a", "up+left+b",
    "up+right", "up+right+a", "up+right+b",
    "down+left", "down+left+a", "down+left+b",
    "down+right", "down+right+a", "down+right+b",
]


class TestActionTable(unittest.TestCase):
    """Guard against drift between mettagrid's action table and our FFI."""

    def test_table_length(self):
        self.assertEqual(len(BITWORLD_ACTION_MASKS), 27)
        self.assertEqual(len(BITWORLD_ACTION_NAMES), 27)

    def test_masks_match_canonical(self):
        """Every index in BITWORLD_ACTION_MASKS must match the canonical formula."""
        for i, (got, want) in enumerate(
            zip(BITWORLD_ACTION_MASKS, CANONICAL_MASKS)
        ):
            with self.subTest(index=i, name=CANONICAL_NAMES[i]):
                self.assertEqual(
                    int(got),
                    want,
                    f"index {i}: BITWORLD_ACTION_MASKS has 0x{int(got):02x}, "
                    f"canonical expects 0x{want:02x} ({CANONICAL_NAMES[i]})",
                )

    def test_names_match_canonical(self):
        """Action names follow the same direction*modifier ordering."""
        for i, (got, want) in enumerate(
            zip(BITWORLD_ACTION_NAMES, CANONICAL_NAMES)
        ):
            with self.subTest(index=i):
                self.assertEqual(
                    got,
                    want,
                    f"index {i}: BITWORLD_ACTION_NAMES has {got!r}, "
                    f"canonical expects {want!r}",
                )

    def test_button_constants_match_nim(self):
        """Verify our Python button constants match the Nim constants.nim values."""
        self.assertEqual(BUTTON_UP, 0x01)
        self.assertEqual(BUTTON_DOWN, 0x02)
        self.assertEqual(BUTTON_LEFT, 0x04)
        self.assertEqual(BUTTON_RIGHT, 0x08)
        self.assertEqual(BUTTON_A, 0x20)
        self.assertEqual(BUTTON_B, 0x40)


if __name__ == "__main__":
    unittest.main()
