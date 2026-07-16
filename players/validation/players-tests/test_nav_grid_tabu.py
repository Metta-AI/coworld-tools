"""Scenario tests for players.player_sdk.nav_grid (tabu).

Ported 1:1 from the embedded smoke test of the original ``swgy_tabu.py``
(sm-policies SWGY-Nav bundle). The numbered scenario comments and the
``check(label, ...)`` assertion labels are preserved verbatim so failures
map straight back to the origin scenarios.
"""

from __future__ import annotations

from players.player_sdk.nav_grid.tabu import (
    TabuConfig,
    TabuState,
    add_tabu,
    gc,
    is_tabu,
    record_failure,
    record_success,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def test_tabu_smoke_scenarios() -> None:

    cfg = TabuConfig(default_ttl=300, strike_threshold=2,
                         strike_window=1, strike_ttl=200)

    # 1. Empty state: nothing is tabu.
    s = TabuState()
    check("1 empty not tabu", not is_tabu(s, (0, 0), 0))

    # 2. add_tabu writes expiry; is_tabu reflects it.
    s = TabuState()
    add_tabu(s, (1, 1), step=10, ttl=50)
    check("2 tabu while live", is_tabu(s, (1, 1), 30))
    check("2b tabu boundary at exp-1", is_tabu(s, (1, 1), 59))
    check("2c tabu expires at exp", not is_tabu(s, (1, 1), 60))
    check("2d tabu expires past exp", not is_tabu(s, (1, 1), 100))

    # 3. add_tabu uses cfg default when ttl is None.
    s = TabuState()
    add_tabu(s, (2, 2), step=0, cfg=cfg)
    check("3 default ttl from cfg",
          s.blacklist[(2, 2)] == cfg.default_ttl)

    # 4. add_tabu uses fallback 300 when neither ttl nor cfg given.
    s = TabuState()
    add_tabu(s, (3, 3), step=0)
    check("4 default ttl fallback", s.blacklist[(3, 3)] == 300)

    # 5. Different key types: Coordinate, (Coord, str), (Coord, role).
    s = TabuState()
    add_tabu(s, (5, 5), step=0, ttl=100)
    add_tabu(s, ((5, 5), "carbon"), step=0, ttl=100)
    add_tabu(s, ((5, 5), "miner"), step=0, ttl=100)
    check("5 cell tabu", is_tabu(s, (5, 5), 50))
    check("5b (cell,element) tabu", is_tabu(s, ((5, 5), "carbon"), 50))
    check("5c (cell,role) tabu", is_tabu(s, ((5, 5), "miner"), 50))
    check("5d (cell,unknown) not tabu", not is_tabu(s, ((5, 5), "iron"), 50))

    # 6. record_failure: first strike doesn't promote.
    s = TabuState()
    promoted = record_failure(s, (6, 6), step=0, cfg=cfg)
    check("6 first strike not promoted", promoted is False)
    check("6b strike count == 1", s.strikes[(6, 6)] == (1, 0))
    check("6c not yet tabu", not is_tabu(s, (6, 6), 0))

    # 7. record_failure: second consecutive strike promotes (threshold=2).
    promoted = record_failure(s, (6, 6), step=1, cfg=cfg)
    check("7 second strike promotes", promoted is True)
    check("7b strike cleared after promotion", (6, 6) not in s.strikes)
    check("7c is now tabu", is_tabu(s, (6, 6), 50))
    # strike_ttl = 200, so expiry = 1 + 200 = 201
    check("7d expiry uses strike_ttl",
          s.blacklist[(6, 6)] == 1 + cfg.strike_ttl)

    # 8. strike_window=1: gap > 1 resets count.
    s = TabuState()
    record_failure(s, (8, 8), step=0, cfg=cfg)   # count 1
    record_failure(s, (8, 8), step=5, cfg=cfg)   # gap 5 > window 1 → reset to 1
    check("8 stale strike resets to 1", s.strikes[(8, 8)] == (1, 5))
    record_failure(s, (8, 8), step=6, cfg=cfg)   # consecutive → promote
    check("8b consecutive after reset promotes", is_tabu(s, (8, 8), 100))

    # 9. strike_window=0: failures accumulate regardless of gap.
    cfg0 = TabuConfig(strike_threshold=3, strike_window=0, strike_ttl=100)
    s = TabuState()
    record_failure(s, (9, 9), step=0, cfg=cfg0)
    record_failure(s, (9, 9), step=100, cfg=cfg0)  # huge gap, but window=0
    check("9 strike window=0 ignores gap", s.strikes[(9, 9)] == (2, 100))
    promoted = record_failure(s, (9, 9), step=200, cfg=cfg0)
    check("9b accumulates to threshold", promoted is True)

    # 10. record_success clears both strikes and blacklist.
    s = TabuState()
    record_failure(s, (10, 10), step=0, cfg=cfg)
    record_success(s, (10, 10))
    check("10a success clears strike", (10, 10) not in s.strikes)
    add_tabu(s, (10, 10), step=0, ttl=100)
    record_success(s, (10, 10))
    check("10b success clears blacklist", (10, 10) not in s.blacklist)
    check("10c success on absent key is no-op", True)  # didn't raise
    record_success(s, (99, 99))   # absent → no error

    # 11. gc drops only expired entries.
    s = TabuState()
    add_tabu(s, "live", step=0, ttl=200)
    add_tabu(s, "expired", step=0, ttl=10)
    gc(s, step=50)   # expired (exp=10) <= 50 → drop; live (exp=200) > 50 → keep
    check("11 gc drops expired", "expired" not in s.blacklist)
    check("11b gc keeps live", "live" in s.blacklist)

    # 12. gc doesn't touch strikes.
    s = TabuState()
    record_failure(s, "key", step=0, cfg=cfg)
    gc(s, step=1000)
    check("12 gc keeps strikes", s.strikes.get("key") == (1, 0))

    # 13. Promotion overwrites a previous (longer) blacklist entry —
    #     the new strike-driven entry replaces.
    s = TabuState()
    add_tabu(s, "k", step=0, ttl=10000)   # long expiry
    record_failure(s, "k", step=0, cfg=cfg)
    record_failure(s, "k", step=1, cfg=cfg)   # promotes; new exp = 1 + 200 = 201
    check("13 promotion overwrites longer entry",
          s.blacklist["k"] == 1 + cfg.strike_ttl)

    # 14. End-to-end miner zero-yield scenario:
    #     extractor at (5,5) for "carbon" yields zero twice → tabu;
    #     then another extractor at (7,7) yields once → success clears it.
    cfg_miner = TabuConfig(strike_threshold=2, strike_window=0,
                               strike_ttl=500)
    s = TabuState()
    k1 = ((5, 5), "carbon")
    k2 = ((7, 7), "carbon")
    record_failure(s, k1, step=10, cfg=cfg_miner)
    promoted = record_failure(s, k1, step=15, cfg=cfg_miner)
    check("14 miner zero-yield promotes", promoted is True)
    check("14b skipped in picker", is_tabu(s, k1, 100))
    check("14c other extractor still pickable", not is_tabu(s, k2, 100))
    record_success(s, k1)
    check("14d success unblocks", not is_tabu(s, k1, 100))

    # 15. End-to-end aligner failed-bump scenario:
    #     two strict-consecutive failures at junction → tabu.
    cfg_align = TabuConfig(strike_threshold=2, strike_window=1,
                               strike_ttl=200)
    s = TabuState()
    record_failure(s, (3, 4), step=100, cfg=cfg_align)
    record_failure(s, (3, 4), step=101, cfg=cfg_align)
    check("15 aligner two-strike consecutive promotes",
          is_tabu(s, (3, 4), 150))
    # Non-consecutive variant: gap > 1 → never accumulates.
    s = TabuState()
    record_failure(s, (3, 4), step=100, cfg=cfg_align)
    record_failure(s, (3, 4), step=110, cfg=cfg_align)  # gap 10 > window 1
    check("15b non-consecutive doesn't promote",
          not is_tabu(s, (3, 4), 150))
