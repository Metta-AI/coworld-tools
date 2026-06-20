"""Paint Arena default policy: a scripted, defensible-territory painter.

This is the seeded "default" Paint Arena policy. Paint Arena is a fully
observable, deterministic, 2-player grid game (see the game-mechanics analysis
in ``README.md``), so the right architecture is a pure scripted decision
function — no LLM, no learned model. ``strategy.choose_move`` is the entire
brain; ``agent`` is just the websocket transport that feeds it observations.
"""

from players.paintarena.default.strategy import Observation, choose_move

__all__ = ["Observation", "choose_move"]
