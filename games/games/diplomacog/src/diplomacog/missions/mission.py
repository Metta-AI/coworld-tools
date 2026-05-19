"""Diplomacog mission entrypoints.

This mirrors the package shape used by the decomposed Cogsguard/CvC branch:
- game systems remain defined in the main game module
- mission entrypoints live under `missions/`
"""

from diplomacog.game import DiplomacyGame, make_diplomacog_mission

__all__ = ["DiplomacyGame", "make_diplomacog_mission"]
