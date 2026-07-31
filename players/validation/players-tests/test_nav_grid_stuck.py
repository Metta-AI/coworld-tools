"""Scenario tests for players.player_sdk.nav_grid (stuck).

Ported 1:1 from the embedded smoke test of the original ``swgy_stuck.py``
(sm-policies SWGY-Nav bundle). The numbered scenario comments and the
``check(label, ...)`` assertion labels are preserved verbatim so failures
map straight back to the origin scenarios.
"""

from __future__ import annotations

from players.player_sdk.nav_grid.stuck import (
    StuckConfig,
    StuckState,
    axial_stuck,
    check_and_resolve,
    pacing_stuck,
    position_stuck,
    reset,
)
from players.player_sdk.nav_grid.tabu import TabuState, is_tabu


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def test_stuck_smoke_scenarios() -> None:

    cfg = StuckConfig(position_window=8, axial_window=5, axial_min_progress=2)

    # 1. Position changes every tick: never stuck.
    s = StuckState()
    any_stuck = False
    for step in range(20):
        if position_stuck(s, (0, step), step, cfg):
            any_stuck = True
            break
    check("1 position changes every tick", not any_stuck)

    # 2. Position fixed for >= window ticks: triggers.
    s = StuckState()
    triggered_at: int | None = None
    for step in range(20):
        if position_stuck(s, (0, 0), step, cfg):
            triggered_at = step
            break
    check(
        "2 position stuck triggers at window",
        triggered_at == cfg.position_window,
        f"triggered_at={triggered_at}",
    )

    # 3. Position fixed for fewer ticks: no trigger.
    s = StuckState()
    triggered = False
    for step in range(cfg.position_window):  # 0..7, total 8 calls
        if position_stuck(s, (0, 0), step, cfg):
            triggered = True
            break
    check("3 fewer ticks no trigger", not triggered)

    # 4. Axial progress with consistent forward motion: not stuck.
    s = StuckState()
    any_stuck = False
    for step in range(10):
        # Move east one cell per tick, target due east.
        if axial_stuck(s, (0, step), (0, 50), step, cfg):
            any_stuck = True
            break
    check("4 forward motion not stuck", not any_stuck)

    # 5. Axial progress with perpendicular motion: stuck after window.
    # Target is east; we move only north/south.
    s = StuckState()
    triggered_at = None
    for step in range(10):
        pos = (step % 2, 0)  # bounce between (0,0) and (1,0)
        if axial_stuck(s, pos, (0, 50), step, cfg):
            triggered_at = step
            break
    check(
        "5 perpendicular motion stuck",
        triggered_at is not None,
        f"triggered_at={triggered_at}",
    )

    # 6. One reverse step then forward: not stuck (cap-at-zero).
    # Pattern: step east, west, east, east, east, east — over 6 ticks
    # forward progress is 4 cells, reverse contributes 0.
    s = StuckState()
    pattern = [(0, 0), (0, 1), (0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
    triggered = False
    for step, pos in enumerate(pattern):
        if axial_stuck(s, pos, (0, 50), step, cfg):
            triggered = True
            break
    check("6 one reverse step not stuck", not triggered)

    # 7. reset clears state.
    s = StuckState()
    position_stuck(s, (0, 0), 0, cfg)
    axial_stuck(s, (0, 0), (0, 10), 0, cfg)
    pacing_cfg = StuckConfig(pacing_window=4, pacing_unique_threshold=2)
    pacing_stuck(s, (0, 0), 0, pacing_cfg)
    reset(s)
    check(
        "7 reset clears state",
        s.last_position is None
        and s.last_progress_step == 0
        and s.history == []
        and len(s.recent_positions) == 0,
    )

    # 8. Pacing disabled when window=0.
    s = StuckState()
    cfg_off = StuckConfig(pacing_window=0)
    triggered = False
    for step in range(20):
        if pacing_stuck(s, (0, 0), step, cfg_off):
            triggered = True
            break
    check("8 pacing disabled when window=0", not triggered)

    # 9. Pacing fires on tight oscillation: 2 cells over a window of 6
    #    with threshold=3 => 2 unique <= 3 => triggers when full.
    s = StuckState()
    cfg_p = StuckConfig(pacing_window=6, pacing_unique_threshold=3)
    pattern = [(0, 0), (0, 1), (0, 0), (0, 1), (0, 0), (0, 1)]
    triggered_at = None
    for step, pos in enumerate(pattern):
        if pacing_stuck(s, pos, step, cfg_p):
            triggered_at = step
            break
    check("9 pacing tight oscillation", triggered_at == 5, f"triggered_at={triggered_at}")

    # 10. Pacing does NOT fire when agent moves through enough cells.
    s = StuckState()
    cfg_p = StuckConfig(pacing_window=6, pacing_unique_threshold=3)
    triggered = False
    for step in range(10):
        if pacing_stuck(s, (0, step), step, cfg_p):
            triggered = True
            break
    check("10 pacing forward motion clears", not triggered)

    # 11. Pacing window shorter than threshold => never fires.
    #     window of 5 unique cells in a window of 5 with threshold=3 =>
    #     5 > 3 so not stuck.
    s = StuckState()
    cfg_p = StuckConfig(pacing_window=5, pacing_unique_threshold=3)
    pattern = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
    triggered = False
    for step, pos in enumerate(pattern):
        if pacing_stuck(s, pos, step, cfg_p):
            triggered = True
            break
    check("11 pacing 5 unique cells survives threshold=3", not triggered)

    # 12. Pacing edge: exactly threshold unique cells => triggers (<=).
    s = StuckState()
    cfg_p = StuckConfig(pacing_window=6, pacing_unique_threshold=3)
    pattern = [(0, 0), (0, 1), (0, 2), (0, 0), (0, 1), (0, 2)]  # 3 unique
    triggered_at = None
    for step, pos in enumerate(pattern):
        if pacing_stuck(s, pos, step, cfg_p):
            triggered_at = step
            break
    check("12 pacing threshold=unique triggers", triggered_at == 5, f"triggered_at={triggered_at}")

    # ---- check_and_resolve ----

    # 13. No stuck: returns None.
    s = StuckState()
    cfg_cr = StuckConfig(position_window=8, pacing_window=0,
                             position_stuck_tabu_ttl=600,
                             pacing_stuck_tabu_ttl=300)
    tabu = TabuState()
    out = check_and_resolve(s, (0, 0), (5, 5), step=0, cfg=cfg_cr, tabu=tabu)
    check("13 not stuck returns None", out is None)

    # 14. Position stuck: returns position outcome and writes tabu with
    #     the position TTL.
    s = StuckState()
    tabu = TabuState()
    out = None
    for step in range(20):
        out = check_and_resolve(s, (0, 0), (5, 5), step=step, cfg=cfg_cr, tabu=tabu)
        if out is not None:
            break
    check("14 position-stuck fires at window",
          out is not None and out.kind == "position",
          f"got {out}")
    check("14b outcome carries abandoned target",
          out.abandoned_target == (5, 5))
    check("14c outcome ttl matches cfg",
          out.suggested_tabu_ttl == 600)
    check("14d tabu was written with position ttl",
          is_tabu(tabu, (5, 5), out.triggered_at + 599))
    check("14e tabu expires correctly",
          not is_tabu(tabu, (5, 5), out.triggered_at + 600))

    # 15. Pacing stuck (with pacing enabled): returns pacing outcome
    #     and writes tabu with the pacing TTL.
    s = StuckState()
    tabu = TabuState()
    cfg_pp = StuckConfig(position_window=99, pacing_window=6,
                             pacing_unique_threshold=3,
                             pacing_stuck_tabu_ttl=300)
    pattern = [(0, 0), (0, 1), (0, 2), (0, 0), (0, 1), (0, 2)]
    out = None
    for step, pos in enumerate(pattern):
        out = check_and_resolve(s, pos, (9, 9), step=step, cfg=cfg_pp, tabu=tabu)
        if out is not None:
            break
    check("15 pacing-stuck returns pacing kind",
          out is not None and out.kind == "pacing",
          f"got {out}")
    check("15b pacing ttl applied",
          out.suggested_tabu_ttl == 300)
    check("15c pacing tabu written",
          is_tabu(tabu, (9, 9), out.triggered_at + 299))

    # 16. Position takes priority over pacing when both would fire.
    #     Position-stuck fires at window=3 ticks of frozen position;
    #     pacing-stuck would also fire (single unique cell), but its
    #     window is longer so it wouldn't fire first.
    s = StuckState()
    tabu = TabuState()
    cfg_both = StuckConfig(position_window=3, pacing_window=6,
                               pacing_unique_threshold=2,
                               position_stuck_tabu_ttl=600,
                               pacing_stuck_tabu_ttl=300)
    out = None
    for step in range(20):
        out = check_and_resolve(s, (0, 0), (1, 1), step=step, cfg=cfg_both, tabu=tabu)
        if out is not None:
            break
    check("16 position prioritized over pacing",
          out is not None and out.kind == "position", f"got {out}")
    check("16b position ttl was used", out.suggested_tabu_ttl == 600)

    # 16c. Now construct a scenario where pacing fires first and position
    #      hasn't accumulated enough ticks yet — pacing_window=4 short,
    #      position_window=99 long, oscillation. Verify pacing returns.
    s = StuckState()
    tabu = TabuState()
    cfg_pacing_first = StuckConfig(
        position_window=99, pacing_window=4, pacing_unique_threshold=2,
        pacing_stuck_tabu_ttl=300,
    )
    pattern_osc = [(0, 0), (0, 1), (0, 0), (0, 1)]   # 2 unique over window=4
    out = None
    for step, pos in enumerate(pattern_osc):
        out = check_and_resolve(s, pos, (1, 1), step=step,
                                cfg=cfg_pacing_first, tabu=tabu)
        if out is not None:
            break
    check("16c pacing fires when position window not reached",
          out is not None and out.kind == "pacing", f"got {out}")

    # 17. tabu=None makes detection diagnostic (no write).
    s = StuckState()
    out = None
    for step in range(20):
        out = check_and_resolve(s, (0, 0), (5, 5), step=step, cfg=cfg_cr, tabu=None)
        if out is not None:
            break
    check("17 detector fires without tabu",
          out is not None and out.kind == "position")

    # 18. Detection with target=None: outcome carries None target,
    #     tabu is not written (nothing to write).
    s = StuckState()
    tabu = TabuState()
    out = None
    for step in range(20):
        out = check_and_resolve(s, (0, 0), None, step=step, cfg=cfg_cr, tabu=tabu)
        if out is not None:
            break
    check("18 outcome with no target",
          out is not None and out.abandoned_target is None)
    check("18b no tabu write when target is None",
          len(tabu.blacklist) == 0)
