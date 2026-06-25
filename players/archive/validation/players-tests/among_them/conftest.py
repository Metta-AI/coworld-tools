"""Per-game test fixtures for the ``among_them`` player suite.

Both ``among_them`` players (``coborg`` and ``starter``) speak the BitWorld
binary ``bitscreen_v1`` wire protocol — not the JSON ``coworld.player.v1``
protocol the cogsguard images use. There is therefore no JSON handshake to
parametrize over; the lifecycle test only needs to know:

- where each image's local tag lives (matches its ``build.sh``'s
  ``IMAGE_LOCAL_TAG``);
- a human-readable leaf name for parametrization ids.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class AmongThemPlayer:
    """Registry entry for one leaf in ``players/among_them/``."""

    leaf: str
    image_tag: str


PLAYERS: list[AmongThemPlayer] = [
    AmongThemPlayer("coborg", "coborg-among-them:dev"),
    AmongThemPlayer("starter", "among-them-starter:dev"),
]


@pytest.fixture(params=PLAYERS, ids=lambda player: player.leaf)
def among_them_player(request) -> AmongThemPlayer:
    """Auto-parametrize tests over every leaf in ``players/among_them/``."""
    return request.param
