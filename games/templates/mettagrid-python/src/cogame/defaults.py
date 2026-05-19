"""Shared constants for the cogame template game.

TODO(cogame): Replace these placeholders with constants appropriate to your game.
Use module-level ``Final``/``Literal`` constants instead of magic numbers so variants
can reference them.
"""

from __future__ import annotations

from typing import Final

# Inventory item limits.
DEFAULT_ORE_CAP: Final[int] = 10
DEFAULT_HP: Final[int] = 3

# Initial ore_vein inventory (how much ore a vein holds before agents deplete it).
DEFAULT_VEIN_ORE: Final[int] = 50

# Episode length for the default mission.
DEFAULT_MAX_STEPS: Final[int] = 200

# How much ore an agent extracts per successful move-into-vein.
DEFAULT_MINE_AMOUNT: Final[int] = 1

# Number of agents in the default mission.
DEFAULT_NUM_AGENTS: Final[int] = 2
