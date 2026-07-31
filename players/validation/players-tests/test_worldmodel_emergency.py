"""Scenario tests for players.player_sdk.worldmodel (emergency).

Ported 1:1 from the embedded smoke test of the original ``swgy_emergency.py``
(sm-policies scripted stack). Scenario comments and ``check`` labels are
preserved verbatim.
"""

from __future__ import annotations

from players.player_sdk.worldmodel.emergency import (
    EmergencyConfig,
    pick_threshold,
    should_pivot,
    worst_deficient_resource,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def test_emergency_smoke_scenarios() -> None:

    elements = ("carbon", "oxygen", "germanium", "silicon")

    # ---- pick_threshold ----

    cfg_off = EmergencyConfig(enabled=False, threshold=20, no_specialist_threshold=10)
    check("1 disabled returns 0", pick_threshold(True, cfg_off) == 0)
    check("1b disabled regardless of liveness", pick_threshold(False, cfg_off) == 0)

    cfg_on = EmergencyConfig(enabled=True, threshold=20, no_specialist_threshold=10)
    check("2 alive uses threshold", pick_threshold(True, cfg_on) == 20)
    check("2b dead uses no_specialist_threshold", pick_threshold(False, cfg_on) == 10)

    # Inverted defaults (no_specialist higher than threshold) is the
    # canonical ordering in dedicated stack; verify it works.
    cfg_inv = EmergencyConfig(enabled=True, threshold=7, no_specialist_threshold=21)
    check("3 inverted alive 7", pick_threshold(True, cfg_inv) == 7)
    check("3b inverted dead 21", pick_threshold(False, cfg_inv) == 21)

    # ---- worst_deficient_resource ----

    # 4. All above threshold: None.
    stocks = {"carbon": 50, "oxygen": 40, "germanium": 30, "silicon": 25}
    check("4 all above threshold", worst_deficient_resource(stocks, elements, 20) is None)

    # 5. One element at threshold: it qualifies (<=).
    stocks = {"carbon": 50, "oxygen": 20, "germanium": 30, "silicon": 25}
    check("5 at threshold qualifies", worst_deficient_resource(stocks, elements, 20) == "oxygen")

    # 6. Multiple deficient: lowest wins.
    stocks = {"carbon": 5, "oxygen": 10, "germanium": 3, "silicon": 25}
    check("6 lowest wins", worst_deficient_resource(stocks, elements, 20) == "germanium")

    # 7. Tie at lowest: iteration order wins.
    stocks = {"carbon": 5, "oxygen": 5, "germanium": 30, "silicon": 25}
    check("7 tie iteration order",
          worst_deficient_resource(stocks, elements, 20) == "carbon")
    # Reverse the resources sequence -> oxygen wins.
    check("7b tie reverse",
          worst_deficient_resource(stocks, ("oxygen", "carbon", "germanium", "silicon"), 20)
          == "oxygen")

    # 8. Missing key in stocks treated as 0 (deficient).
    stocks = {"carbon": 50}
    check("8 missing key treated as 0",
          worst_deficient_resource(stocks, elements, 20) == "oxygen")  # first missing in iter order

    # 9. Threshold 0 disables.
    stocks = {"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0}
    check("9 threshold 0 disables", worst_deficient_resource(stocks, elements, 0) is None)

    # 10. Negative threshold disables.
    check("10 negative threshold disables", worst_deficient_resource(stocks, elements, -5) is None)

    # 11. Empty resources sequence: None.
    check("11 empty resources", worst_deficient_resource(stocks, (), 20) is None)

    # ---- should_pivot ----

    # 12. Disabled: always None.
    stocks = {"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0}
    check("12 disabled None alive", should_pivot(stocks, elements, True, cfg_off) is None)
    check("12b disabled None dead", should_pivot(stocks, elements, False, cfg_off) is None)

    # 13. Enabled, alive, healthy stocks: None.
    stocks = {"carbon": 50, "oxygen": 50, "germanium": 50, "silicon": 50}
    check("13 healthy stocks alive", should_pivot(stocks, elements, True, cfg_on) is None)

    # 14. Enabled, alive, deficient: returns worst.
    stocks = {"carbon": 50, "oxygen": 5, "germanium": 50, "silicon": 50}
    check("14 deficient alive", should_pivot(stocks, elements, True, cfg_on) == "oxygen")

    # 15. Enabled, dead, deficient at lower threshold but not higher
    #     threshold: shows the dual-threshold logic.
    cfg_dual = EmergencyConfig(enabled=True, threshold=7, no_specialist_threshold=21)
    stocks = {"carbon": 50, "oxygen": 15, "germanium": 50, "silicon": 50}
    # Alive with threshold=7: 15 > 7 => no pivot.
    check("15 alive no pivot at 15>7",
          should_pivot(stocks, elements, True, cfg_dual) is None)
    # Dead with threshold=21: 15 <= 21 => pivot.
    check("15b dead pivots at 15<=21",
          should_pivot(stocks, elements, False, cfg_dual) == "oxygen")

    # 16. Branch disabled by setting its threshold to 0.
    cfg_alive_only = EmergencyConfig(enabled=True, threshold=20, no_specialist_threshold=0)
    stocks = {"carbon": 5, "oxygen": 5, "germanium": 5, "silicon": 5}
    check("16 alive triggers", should_pivot(stocks, elements, True, cfg_alive_only) == "carbon")
    check("16b dead disabled by threshold=0",
          should_pivot(stocks, elements, False, cfg_alive_only) is None)

    cfg_dead_only = EmergencyConfig(enabled=True, threshold=0, no_specialist_threshold=20)
    check("16c alive disabled by threshold=0",
          should_pivot(stocks, elements, True, cfg_dead_only) is None)
    check("16d dead triggers",
          should_pivot(stocks, elements, False, cfg_dead_only) == "carbon")

    # 17. Skewed stock scenario: the rarest element is selected.
    cfg_tom = EmergencyConfig(enabled=True, threshold=20, no_specialist_threshold=10)
    stocks = {"carbon": 30, "oxygen": 28, "germanium": 8, "silicon": 35}
    check("17 tom-like alive picks germanium",
          should_pivot(stocks, elements, True, cfg_tom) == "germanium")
