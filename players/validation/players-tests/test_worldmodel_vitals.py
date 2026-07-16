"""Scenario tests for players.player_sdk.worldmodel (vitals).

Ported 1:1 from the embedded smoke test of the original ``swgy_vitals.py``
(sm-policies scripted stack). Scenario comments and ``check`` labels are
preserved verbatim.
"""

from __future__ import annotations

from players.player_sdk.worldmodel.vitals import (
    VitalsConfig,
    hp_deficit,
    is_topped_up,
    should_retreat,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def test_vitals_smoke_scenarios() -> None:

    cfg = VitalsConfig()  # defaults: buffer 15, hp_floor 30, energy_floor 8

    # 1. Healthy + close: no retreat.
    check(
        "1 healthy agent, no retreat",
        should_retreat(hp=80, energy=50, anchor_distance=5, cfg=cfg) is False,
    )

    # 2. HP above floor, but anchor far: distance buffer triggers.
    # walk-home threshold = 30 + 15 = 45; hp 40 < 45.
    check(
        "2 distance buffer triggers retreat",
        should_retreat(hp=40, energy=50, anchor_distance=30, cfg=cfg) is True,
    )

    # 3. HP at floor (29 < 30): absolute floor triggers.
    check(
        "3 hp floor triggers retreat",
        should_retreat(hp=29, energy=50, anchor_distance=0, cfg=cfg) is True,
    )

    # 4. Energy at floor (7 < 8): triggers.
    check(
        "4 energy floor triggers retreat",
        should_retreat(hp=80, energy=7, anchor_distance=2, cfg=cfg) is True,
    )

    # 5. is_topped_up True when energy >= ceiling.
    cfg_ceiling = VitalsConfig(rest_energy_ceiling=100)
    check(
        "5 topped up at ceiling",
        is_topped_up(energy=100, cfg=cfg_ceiling) is True
        and is_topped_up(energy=99, cfg=cfg_ceiling) is False,
    )

    # 6. is_topped_up False when ceiling is None.
    check(
        "6 topped up False without ceiling",
        is_topped_up(energy=10000, cfg=cfg) is False,
    )

    # Extra: hp_deficit sign convention.
    check(
        "extra hp_deficit positive",
        hp_deficit(hp=50, anchor_distance=5, cfg=cfg) == 30,
        f"got {hp_deficit(hp=50, anchor_distance=5, cfg=cfg)}",
    )
    check(
        "extra hp_deficit negative",
        hp_deficit(hp=10, anchor_distance=5, cfg=cfg) == -10,
        f"got {hp_deficit(hp=10, anchor_distance=5, cfg=cfg)}",
    )
