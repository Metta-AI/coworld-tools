"""cogony: a MettaGrid game vendored from cogs_vs_clips.

Importing the package registers the game with cogames so
``cogames play -g cogony`` resolves here. The default mission is
``cogony``.
"""

from __future__ import annotations

from cogony._mettascope_assets import auto_overlay as _auto_overlay

_auto_overlay()

import cogony.registration as _registration  # noqa: E402, F401  (side effect: register_game)

from cogony.mission import CogonyMission  # noqa: E402
from cogony.registration import CogonyGame  # noqa: E402

__all__ = ["CogonyGame", "CogonyMission"]
