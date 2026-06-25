"""Default mission factory.

Keeping factories in their own module lets tests and alternative CLIs build a
mission without reaching into ``cogame.game`` directly. Every factory returns
a fully-parameterised :class:`cogame.framework.CoGameMission` instance.

TODO(cogame): add additional mission factories (eval missions, tutorials,
curriculum scenarios) here as the game grows.
"""

from __future__ import annotations

from cogame.game import MyMission


def make_default_mission() -> MyMission:
    return MyMission.create()
