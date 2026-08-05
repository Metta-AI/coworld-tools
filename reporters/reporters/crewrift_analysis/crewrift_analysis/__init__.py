"""CrewRift-specific analysis and figures over ``expand_replay`` JSONL.

The game-specific layer above the engine-generic ``episode-analysis``
package::

    crewrift_analysis (this package: game schema, palette, metrics, figures)
        -> episode_analysis (charts, palette semantics, stats)
            -> expand_replay --format jsonl --snapshot-every N  (the input)

- :mod:`.events` — typed adapter: one episode's JSONL -> :class:`Episode`.
- :mod:`.palette` — the 16-color engine player palette + role colors.
- :mod:`.metrics` — the imposter/crew contrast axes (one scalar per
  player-game) and their rank-AUC aggregation.
- ``crewrift_analysis.figures`` — the four figures (contrast table, vote
  ladder, missed-blend overlay, fog of war); requires the ``[charts]``
  extra.
- ``python -m crewrift_analysis`` — dev CLI rendering all four from JSONL
  files on disk.

Origin: adapted from Ron Dahlgren's (swgy) crewrift tooling
(swgy-crewrift ``swgy_tools``); each module's docstring carries its
provenance.
"""

from .events import (
    ChatMessage,
    CrewriftLogError,
    Episode,
    Kill,
    MeetingSpan,
    Player,
    PlayerTrack,
    Sighting,
    Vote,
    load_episode,
    parse_episode,
)
from .metrics import AXES, AxisContrast, AxisSpec, aggregate_contrast, player_game_metrics
from .palette import (
    PLAYER_COLOR_NAMES,
    PLAYER_COLORS,
    ROLE_COLORS,
    lifted_player_color,
    player_color,
)

__all__ = [
    "AXES",
    "AxisContrast",
    "AxisSpec",
    "ChatMessage",
    "CrewriftLogError",
    "Episode",
    "Kill",
    "MeetingSpan",
    "PLAYER_COLORS",
    "PLAYER_COLOR_NAMES",
    "Player",
    "PlayerTrack",
    "ROLE_COLORS",
    "Sighting",
    "Vote",
    "aggregate_contrast",
    "lifted_player_color",
    "load_episode",
    "parse_episode",
    "player_color",
    "player_game_metrics",
]
