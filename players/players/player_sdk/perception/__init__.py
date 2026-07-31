"""Opt-in observation-parsing helpers, one module per wire format.

Today: :mod:`.cogames_tokens` — a single-pass decoder for MettaGrid/cogames
token-stream observations, duck-typed so it needs no mettagrid import.

This subpackage is not re-exported from ``players.player_sdk``; import it
explicitly. Origin: extracted from Ron Dahlgren's (swgy) agent libraries.
"""

from .cogames_tokens import Perception, TagIndex, parse_observation

__all__ = ["Perception", "TagIndex", "parse_observation"]
