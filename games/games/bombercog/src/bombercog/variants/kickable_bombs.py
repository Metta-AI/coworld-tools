"""Kickable bombs variant: walking into a bomb pushes it forward."""

from __future__ import annotations

from bombercog._framework import CoGameMissionVariant
from mettagrid.config.filter import isA
from mettagrid.config.handler_config import Handler
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation import PushObjectMutation, RelocateMutation


class KickableBombsVariant(CoGameMissionVariant):
    """Adds a ``kick_bomb`` handler to the move chain that fires when an
    agent walks into a bomb. The PushObjectMutation shoves the bomb one
    cell further along the actor->target direction; RelocateMutation then
    steps the agent into the vacated cell. If the cell beyond the bomb is
    blocked, PushObjectMutation fails and the mutation chain aborts — the
    fallback move handlers then fail too (bomb still occupies the cell),
    so the agent stays put.

    The handler is inserted AFTER ``place_bomb`` in the move chain so
    bomb-vibe placements still take priority on empty cells. If the
    bomb-vibe agent happens to walk into an existing bomb, the kick
    semantics apply (place_bomb fails on TargetLocEmpty first).
    """

    name: str = "kickable_bombs"
    description: str = "Walking into a bomb kicks it one cell further."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        kick_handler = Handler(
            name="kick_bomb",
            filters=[isA("bomb")],
            mutations=[
                PushObjectMutation(),
                RelocateMutation(),
            ],
        )
        # Insert after place_bomb (position 0). Position 1 is safe: the
        # base game only has place_bomb in the Python handlers list; the
        # C++ side appends default relocate/use_target after it.
        env.game.actions.move.handlers.insert(1, kick_handler)
