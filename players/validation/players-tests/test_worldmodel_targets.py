"""Scenario tests for players.player_sdk.worldmodel (targets).

Ported 1:1 from the embedded smoke test of the original ``swgy_targets.py``
(sm-policies scripted stack). Scenario comments and ``check`` labels are
preserved verbatim.
"""

from __future__ import annotations

from players.player_sdk.worldmodel.targets import (
    TargetConfig,
    TargetState,
    check_arrival,
    clear_target,
    set_target,
    update_target_progress,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def test_targets_smoke_scenarios() -> None:

    from players.player_sdk.nav_grid.distance import manhattan  # canonical metric

    cfg = TargetConfig(progress_window=5)

    # 1. set_target initializes trace from current position.
    s = TargetState()
    set_target(s, target=(0, 10), position=(0, 0), step=0, distance=manhattan, kind="junction")
    check("1 target set", s.target == (0, 10) and s.target_kind == "junction")
    check("1b best_distance from current pos", s.best_distance == 10)
    check("1c last_progress_step", s.last_progress_step == 0)

    # 2. Forward progress updates trace.
    update_target_progress(s, position=(0, 1), step=1, distance=manhattan, cfg=cfg)
    check("2 progress updates best", s.best_distance == 9)
    check("2b progress updates step", s.last_progress_step == 1)

    # 3. Steady forward progress: never drops.
    s = TargetState()
    set_target(s, (0, 10), (0, 0), 0, manhattan)
    dropped_at = None
    for step in range(1, 11):
        if not update_target_progress(s, (0, step), step, manhattan, cfg):
            dropped_at = step
            break
    check("3 steady progress never drops", dropped_at is None)

    # 4. No progress for window: drops.
    s = TargetState()
    set_target(s, (0, 10), (0, 0), 0, manhattan)
    # Stand still at (0, 0): no progress for 5 ticks (window) -> should drop.
    dropped_at = None
    for step in range(1, 10):
        if not update_target_progress(s, (0, 0), step, manhattan, cfg):
            dropped_at = step
            break
    # After step 0 set, window=5 -> drops at step 5 (5 - 0 == window).
    check("4 stuck drops at window boundary", dropped_at == 5, f"got {dropped_at}")

    # 5. Backward motion: trace unchanged, also drops at window.
    s = TargetState()
    set_target(s, (0, 10), (0, 5), 0, manhattan)  # start dist=5
    # Move further away every tick.
    dropped_at = None
    for step in range(1, 10):
        pos = (0, 5 - step)  # (0,4), (0,3), ... worse each time
        if not update_target_progress(s, pos, step, manhattan, cfg):
            dropped_at = step
            break
    check("5 backward motion drops at window", dropped_at == 5, f"got {dropped_at}")
    check("5b backward best unchanged from initial", s.best_distance == 5)

    # 6. Mixed: progress-then-stall resets the window from progress
    #    point.
    s = TargetState()
    set_target(s, (0, 10), (0, 0), 0, manhattan)
    # Step 1: progress (0,1) -> dist 9 -> last_progress_step=1.
    update_target_progress(s, (0, 1), 1, manhattan, cfg)
    # Steps 2..5: stall at (0,1). At step 5, gap=5-1=4 < window=5, still ok.
    # At step 6, gap=5 >= window -> drop.
    dropped_at = None
    for step in range(2, 10):
        if not update_target_progress(s, (0, 1), step, manhattan, cfg):
            dropped_at = step
            break
    check("6 progress resets window", dropped_at == 6, f"got {dropped_at}")

    # 7. Equal-distance moves don't count as progress.
    s = TargetState()
    set_target(s, (0, 10), (0, 0), 0, manhattan)
    # Move sideways: (1, 0) -> still distance 11. NOT progress.
    update_target_progress(s, (1, 0), 1, manhattan, cfg)
    check("7 equal-dist not progress (best)", s.best_distance == 10)
    check("7b equal-dist not progress (step)", s.last_progress_step == 0)

    # 8. clear_target wipes everything.
    s = TargetState()
    set_target(s, (0, 10), (0, 0), 0, manhattan, kind="x")
    clear_target(s)
    check("8 clear", s.target is None and s.target_kind is None
          and s.best_distance is None and s.last_progress_step == 0)

    # 9. update_target_progress on no-target returns False (no-op).
    s = TargetState()
    res = update_target_progress(s, (0, 0), 0, manhattan, cfg)
    check("9 no-target no-op returns False", res is False)

    # 10. set_target overwrites previous target cleanly.
    s = TargetState()
    set_target(s, (0, 5), (0, 0), 0, manhattan, kind="junction")
    set_target(s, (10, 0), (0, 0), 5, manhattan, kind="extractor")
    check("10 retarget updates target", s.target == (10, 0))
    check("10b retarget updates kind", s.target_kind == "extractor")
    check("10c retarget refreshes best", s.best_distance == 10)
    check("10d retarget refreshes step", s.last_progress_step == 5)

    # 11. Verify return semantics: True == still viable.
    s = TargetState()
    set_target(s, (0, 10), (0, 0), 0, manhattan)
    res = update_target_progress(s, (0, 1), 1, manhattan, cfg)
    check("11 viable returns True", res is True)
    res = update_target_progress(s, (0, 1), 6, manhattan, cfg)
    check("11b stuck returns False", res is False)

    # ---- check_arrival ----
    from players.player_sdk.nav_grid.distance import chebyshev

    # 12. No target set: returns False (don't crash).
    s = TargetState()
    check("12 no target arrival is False",
          not check_arrival(s, (0, 0), chebyshev, threshold=1))

    # 13. Geometric-only arrival (no objective): exact-equality.
    s = TargetState()
    set_target(s, (5, 5), (0, 0), 0, manhattan)
    check("13 not at exact-equality target",
          not check_arrival(s, (5, 4), chebyshev, threshold=0))
    check("13b at exact target",
          check_arrival(s, (5, 5), chebyshev, threshold=0))

    # 14. Bump-target arrival (chebyshev=1).
    s = TargetState()
    set_target(s, (5, 5), (0, 0), 0, manhattan)
    check("14 cheb=1 cardinal arrives", check_arrival(s, (5, 4), chebyshev, threshold=1))
    check("14b cheb=1 diagonal arrives", check_arrival(s, (4, 4), chebyshev, threshold=1))
    check("14c cheb=2 not arrived", not check_arrival(s, (3, 5), chebyshev, threshold=1))

    # 15. Objective satisfied: returns True.
    s = TargetState()
    set_target(s, (5, 5), (0, 0), 0, manhattan)
    check("15 geometry+objective arrives",
          check_arrival(s, (5, 5), chebyshev, threshold=1,
                        objective_satisfied=lambda: True))

    # 16. Geometry met, objective not satisfied: returns False.
    items = {"miner": 0}
    check("16 geometry-only without objective stays loitering",
          not check_arrival(s, (5, 5), chebyshev, threshold=1,
                            objective_satisfied=lambda: items.get("miner", 0) > 0))
    items["miner"] = 1
    check("16b objective flips True after gear pickup",
          check_arrival(s, (5, 5), chebyshev, threshold=1,
                        objective_satisfied=lambda: items.get("miner", 0) > 0))

    # 17. Geometry not met: predicate not consulted (short-circuit).
    called = [False]
    def predicate() -> bool:
        called[0] = True
        return True
    check("17 geometry-fail returns False",
          not check_arrival(s, (10, 10), chebyshev, threshold=1,
                            objective_satisfied=predicate))
    check("17b predicate not called when geometry fails",
          called[0] is False)

    # 18. End-to-end station-arrival scenario.
    items_b2 = {"miner": 0}
    s = TargetState()
    set_target(s, (10, 10), (0, 0), 0, manhattan, kind="station_miner")
    check("18 not yet at station",
          not check_arrival(s, (8, 8), chebyshev, threshold=1,
                            objective_satisfied=lambda: items_b2.get("miner", 0) > 0))
    # Walk adjacent without gear (env-side effect not yet emitted):
    check("18b adjacent but no gear: still not arrived",
          not check_arrival(s, (10, 9), chebyshev, threshold=1,
                            objective_satisfied=lambda: items_b2.get("miner", 0) > 0))
    items_b2["miner"] = 1   # bump succeeded
    check("18c adjacent with gear: arrived",
          check_arrival(s, (10, 9), chebyshev, threshold=1,
                        objective_satisfied=lambda: items_b2.get("miner", 0) > 0))

    # 19. End-to-end hub top-up arrival scenario.
    items_b6 = {"heart": 0}
    s = TargetState()
    set_target(s, (0, 0), (5, 5), 0, manhattan, kind="hub")
    topup = 1

    def cond() -> bool:
        return items_b6.get("heart", 0) >= topup

    check("19 adjacent to hub, no hearts yet",
          not check_arrival(s, (0, 1), chebyshev, threshold=1,
                            objective_satisfied=cond))
    items_b6["heart"] = 1
    check("19b adjacent to hub with topup hit: arrived",
          check_arrival(s, (0, 1), chebyshev, threshold=1,
                        objective_satisfied=cond))
