"""Tests for players.player_sdk.worldmodel.census.

Scenarios adapted from the alive-role-count section of the
``dedicated_runtime.py`` smoke test (sm-policies scripted stack), with the
freshness window an explicit knob instead of the original
``max(20, claim_ttl * 5)`` derivation.
"""

from __future__ import annotations

from players.player_sdk.worldmodel.census import TeamCensus


def make_census(**kw) -> TeamCensus:
    return TeamCensus(roster={0: "miner", 1: "miner", 2: "aligner"}, **kw)


def test_alive_count_requires_positive_hp() -> None:
    c = make_census()
    c.report_alive(0, hp=80, step=100)
    c.report_alive(1, hp=0, step=99)  # dead agents keep reporting, hp=0
    c.report_alive(2, hp=50, step=100)
    # 17. alive_role_count miner: 1 (other dead).
    assert c.alive_count("miner", step=100) == 1
    # 17b. aligner: 1.
    assert c.alive_count("aligner", step=100) == 1
    assert c.total_alive(step=100) == 2


def test_stale_reports_drop_off() -> None:
    c = make_census(freshness_window=125)
    c.report_alive(0, hp=80, step=100)
    # 18. Far-future step: no recent reports == not alive.
    assert c.alive_count("miner", step=10000) == 0
    # Exactly at the window boundary: still credible (<=).
    assert c.is_alive(0, step=100 + 125)
    assert not c.is_alive(0, step=100 + 126)


def test_startup_grace_assumes_alive() -> None:
    c = make_census(startup_grace=5)
    # Never reported, early episode: assumed alive.
    assert c.alive_count("miner", step=3) == 2
    assert c.total_alive(step=5) == 3
    # Past the grace with no report: not alive.
    assert c.alive_count("miner", step=6) == 0


def test_roster_queries() -> None:
    c = make_census()
    assert c.role_of(2) == "aligner"
    assert c.role_of(9) is None
    assert c.roster == {0: "miner", 1: "miner", 2: "aligner"}


def test_revival_and_death_updates() -> None:
    c = make_census()
    c.report_alive(0, hp=10, step=50)
    assert c.is_alive(0, step=51)
    c.report_alive(0, hp=0, step=52)  # died
    assert not c.is_alive(0, step=53)
    c.report_alive(0, hp=5, step=54)  # revived (game-dependent, but supported)
    assert c.is_alive(0, step=55)
