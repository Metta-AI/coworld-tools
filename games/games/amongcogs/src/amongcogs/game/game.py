"""AmongCogs registration hooks for the local and CoGames registries."""

from __future__ import annotations

from cogames.game import CoGame, register_game
from amongcogs.game import ALL_VARIANTS, parse_variants
from amongcogs.missions import AmongUsGame, make_basic_mission
from amongcogs.runtime import register


class AmongUsCoGame(CoGame):
    """AmongCogs game definition for standalone registration."""

    def __init__(self) -> None:
        super().__init__(
            name="amongcogs",
            missions=[make_basic_mission()],
            variants=list(ALL_VARIANTS),
        )


AMONG_US_GAME = AmongUsCoGame()
register_game(AMONG_US_GAME)

register(
    "amongcogs",
    AmongUsGame,
    parse_variants=parse_variants,
    policy_uri="metta://policy/amongcogs_agent",
    policy_packages=[
        "amongcogs.agent.amongcogs_agent",
        "amongcogs.agent.amongcogs_cyborg",
    ],
)
