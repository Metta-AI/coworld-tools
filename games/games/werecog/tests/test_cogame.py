from __future__ import annotations

import importlib
import sys

from cogames import game as cogame_module


def test_cogame_import_registers_werecog() -> None:
    cogame_module._GAMES.pop("werecog", None)
    sys.modules.pop("werecog.cogame", None)

    importlib.import_module("werecog.cogame")

    assert cogame_module._GAMES["werecog"].name == "werecog"
