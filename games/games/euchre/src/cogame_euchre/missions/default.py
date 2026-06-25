"""Default mission factory for Euchre."""

from __future__ import annotations

from cogame_euchre.game import EuchreMission


def make_default_mission() -> EuchreMission:
    return EuchreMission.create()
